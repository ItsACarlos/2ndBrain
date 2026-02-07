#!/usr/bin/python3
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 1. Setup & Configuration
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
load_dotenv()
BASE_VAULT_PATH = Path.home() / "Documents" / "2ndBrain" / "2ndBrainVault"
# Ensure our core directories exist
for folder in ["Inbox", "Projects", "Actions", "Ideas", "Media"]:
    (BASE_VAULT_PATH / folder).mkdir(parents=True, exist_ok=True)

# Initialize AI
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


def download_slack_file(url, client=None, file_id=None):
    """
    Downloads a file from Slack, with extra diagnostics for permission errors.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is missing")

    # 1. Diagnostic: Verify the token has permission using the Web API
    if client and file_id:
        try:
            client.files_info(file=file_id)
        except Exception as e:
            logging.error(f"API Check Failed: {e}")
            if "missing_scope" in str(e):
                logging.error("CRITCAL: Your Bot Token is missing 'files:read'. Go to api.slack.com -> OAuth & Permissions -> Add 'files:read' -> Reinstall App.")
            elif "file_not_found" in str(e):
                 logging.error("CRITCAL: Bot cannot see this file. If it's in a private channel/DM, ensure the bot is a member.")
            raise e

    # 2. Download with explicit no-redirects to catch auth failures (302)
    headers = {"Authorization": f"Bearer {token}"}
    logging.info(f"Downloading {url}...")

    resp = requests.get(url, headers=headers, allow_redirects=False)

    if resp.status_code in [301, 302]:
        redirect_url = resp.headers.get("Location", "")
        logging.error(f"Auth Failed: Redirected to {redirect_url}")
        raise ValueError(f"Slack rejected the token. Ensure 'files:read' scope is active. URL: {url}")

    resp.raise_for_status()

    if "text/html" in resp.headers.get("Content-Type", ""):
        raise ValueError("Slack returned HTML (likely login page). Token lacks permissions.")

    return resp.content


def process_with_gemini(raw_text, files=None, client=None):
    """
    Categorizes the note into folders and cleans up the Markdown content.
    """
    model = genai.GenerativeModel("gemini-2.5-flash")

    # Prompt reflects the logic defined in your AGENTS.md
    prompt_file = Path(__file__).parent / "slack_prompt.md"

    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        prompt_file.read_text(),
        f"Context:\nCurrent system time: {current_time_str}\n(Use this exact time for the filename timestamp)",
        f"\n\nInput:\n{raw_text}",
    ]

    if files:
        parts.append("\n\nAttachments:")
        for file in files:
            try:
                # Use url_private (API URL) instead of browser download URL
                url = file.get("url_private")
                content = download_slack_file(url, client=client, file_id=file.get("id"))
                mime = file.get("mimetype", "")

                # 1. Save file to Vault
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # Remove unsafe chars from filename
                clean_name = re.sub(r'[^a-zA-Z0-9._-]', '', file['name'])
                saved_filename = f"{timestamp}_{clean_name}"
                save_path = BASE_VAULT_PATH / "Media" / saved_filename

                with open(save_path, "wb") as f:
                    f.write(content)
                logging.info(f"Saved attachment to {save_path}")

                parts.append(f"\n[System Notice: I have saved this attachment to the vault at 'Media/{saved_filename}'. You MUST include a link to it in your Markdown output using the format ![[{saved_filename}]] for images or [[{saved_filename}]] for other files. Do describing the image content in text unless necessary, just link it.]")

                # Normalize common mime types if needed
                if mime == "image/jpg":
                    mime = "image/jpeg"

                # Pass images and PDFs as data parts
                # Gemini supports: PDF, JPEG, PNG, WEBP, HEIC
                if mime in ["application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]:
                    logging.info(f"Attaching {mime} file ({len(content)} bytes)")
                    parts.append({"mime_type": mime, "data": content})
                    parts.append(f"\n[Attached file: {file['name']}]")

                # Treat everything else as text (code, markdown, etc.)
                else:
                    try:
                        text_content = content.decode("utf-8")
                        parts.append(
                            f"\n\nFile: {file['name']}\n```\n{text_content}\n```"
                        )
                    except UnicodeDecodeError:
                         logging.warning(f"Skipping binary file {file['name']} with mime {mime}")
                         parts.append(f"\n[Skipped binary file: {file['name']} ({mime})]")

            except Exception as e:
                logging.warning(f"Failed to process attachment {file['name']}: {e}")

    try:
        response = model.generate_content(parts)
    except Exception as e:
        # Log the detailed API error which usually explains why it failed
        logging.error(f"Gemini API Error: {e}")
        raise e


    # Extract Token Usage for your frontmatter
    usage = response.usage_metadata
    tokens = usage.total_token_count

    # Extract JSON string from response
    json_match = re.search(r"\{.*\}", response.text, re.DOTALL)
    if not json_match:
        # assume this is an unstructured answer to a question
        return response.text, tokens, True

    data = json.loads(json_match.group())

    data["content"] = data["content"].replace("tags:", f"tokens_used: {tokens}\ntags:")

    return data, tokens, False


@app.event("message")
def handle_message(event, say):
    # Ignore bot messages and channel joins/leaves
    subtype = event.get("subtype")
    if (subtype and subtype != "file_share") or event.get("bot_id"):
        return

    text = event.get("text") or ""
    files = event.get("files", [])
    logging.info(f"📥 Incoming from Slack: {text[:50]}... ({len(files)} files)")

    try:
        # The AI "Refiner" Step
        data, token_count, is_answer = process_with_gemini(text, files, client=app.client)

        if is_answer:
            say(data)
            return

        # Determine final file path
        target_folder = BASE_VAULT_PATH / data["folder"]
        file_path = target_folder / data["filename"]

        # Write the file
        with open(file_path, "w") as f:
            f.write(data["content"])

        # Logging to journalctl
        logging.info(
            f"Filed to {data['folder']}/{data['filename']} ({token_count} tokens)"
        )

        # Feedback to user in Slack
        say(
            f"📂 Filed to `{data['folder']}` as `{data['filename']}`. (Used {token_count} tokens)"
        )

    except Exception as e:
        logging.exception("Error processing message")
        say(f"⚠️ Brain Error: {str(e)}")


if __name__ == "__main__":
    logging.info("⚡️ 2ndBrain Collector is starting up...")
    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    handler.start()
