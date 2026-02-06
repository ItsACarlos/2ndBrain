#!/usr/bin/python3
import os
import re
import json
import logging
from datetime import datetime
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import google.generativeai as genai
from dotenv import load_dotenv
from pathlib import Path


# 1. Setup & Configuration
load_dotenv()
BASE_VAULT_PATH = Path.home() / "Documents" / "2ndBrain"
# Ensure our core directories exist
for folder in ["Inbox", "Projects", "Actions", "Ideas", "Media"]:
    (BASE_VAULT_PATH / folder).mkdir(parents=True, exist_ok=True)

# Initialize AI
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

def process_with_gemini(raw_text):
    """
    Categorizes the note into folders and cleans up the Markdown content.
    """
    model = genai.GenerativeModel('gemini-2.5-flash')

    # Prompt reflects the logic defined in your AGENTS.md
    prompt_file = Path(__file__).parent / "slack_prompt.md"
    prompt = prompt_file.read_text() + f"\n\nInput:\n{raw_text}"

    response = model.generate_content(prompt)

    # Extract Token Usage for your frontmatter
    usage = response.usage_metadata
    tokens = usage.total_token_count

    # Extract JSON string from response
    json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
    if not json_match:
        raise ValueError("AI failed to return a valid JSON object.")

    data = json.loads(json_match.group())

    # Inject token usage into the content's YAML frontmatter
    data['content'] = data['content'].replace(
        "tags:", f"tokens_used: {tokens}\ntags:"
    )

    return data, tokens

@app.event("message")
def handle_message(event, say):
    # Ignore bot messages and channel joins/leaves
    if event.get("subtype") or event.get("bot_id"):
        return

    text = event.get("text")
    print(f"📥 Incoming from Slack: {text[:50]}...")

    try:
        # The AI "Refiner" Step
        data, token_count = process_with_gemini(text)

        # Determine final file path
        target_folder = BASE_VAULT_PATH / data['folder']
        file_path = target_folder / data['filename']

        # Write the file
        with open(file_path, "w") as f:
            f.write(data['content'])

        # Logging to journalctl
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Filed to {data['folder']}/{data['filename']} ({token_count} tokens)")

        # Feedback to user in Slack
        say(f"📂 Filed to `{data['folder']}` as `{data['filename']}`. (Used {token_count} tokens)")

    except Exception as e:
        error_msg = f"Error processing message: {str(e)}"
        print(error_msg)
        say(f"⚠️ Brain Error: {str(e)}")

if __name__ == "__main__":
    print("⚡️ 2ndBrain Collector is starting up...")
    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    handler.start()