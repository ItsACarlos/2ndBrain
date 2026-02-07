"""
listener.py — Slack event handlers.

Handles incoming messages, downloads attachments,
delegates to the Gemini processor, and saves results to the vault.
"""

import logging
import os

import requests
from google.genai import types

from .processor import GEMINI_BINARY_MIMES, TEXT_INLINE_MAX_BYTES, _normalize_mime
from .vault import Vault


def download_slack_file(url: str) -> bytes:
    """
    Download a file from Slack using the bot token.

    Uses allow_redirects=False to catch auth failures (302 → login page).

    Raises:
        ValueError: If token is missing or Slack rejects the request.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is not set")

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        allow_redirects=False,
    )

    if resp.status_code in (301, 302):
        location = resp.headers.get("Location", "")
        logging.error(f"Slack auth redirect → {location}")
        raise ValueError(
            "Slack rejected the token. Ensure 'files:read' scope is active "
            "and the app has been reinstalled."
        )

    resp.raise_for_status()

    if "text/html" in resp.headers.get("Content-Type", ""):
        raise ValueError("Slack returned HTML. Token likely lacks 'files:read'.")

    return resp.content


def _process_attachments(files: list[dict], vault: Vault) -> list:
    """
    Download Slack attachments and prepare prompt context.

    Binary files (images, PDFs) are saved to Attachments/ and
    passed as data parts to Gemini.

    Small text files are inlined into the prompt as code blocks
    (not saved separately).

    Returns:
        List of prompt parts (strings and/or binary data dicts).
    """
    if not files:
        return []

    parts = ["\n## Attachments"]

    for file_info in files:
        name = file_info.get("name", "unknown")
        try:
            url = file_info.get("url_private")
            if not url:
                logging.warning(f"No url_private for file {name}")
                continue

            content = download_slack_file(url)
            mime = _normalize_mime(file_info.get("mimetype", ""))

            if mime in GEMINI_BINARY_MIMES:
                # Save binary to Attachments/
                saved_name = vault.save_attachment(name, content)
                logging.info(f"Saved binary attachment: {saved_name} ({mime})")

                # Add binary data for Gemini to analyse
                parts.append(types.Part.from_bytes(data=content, mime_type=mime))

                # Instruct Gemini to link the saved file
                link_syntax = (
                    f"![[{saved_name}]]"
                    if mime.startswith("image/")
                    else f"[[{saved_name}]]"
                )
                parts.append(
                    f"\n[System: Attachment '{name}' saved as '{saved_name}'. "
                    f"Include {link_syntax} in your output to link it.]"
                )

            else:
                # Try to read as text and inline
                try:
                    if len(content) > TEXT_INLINE_MAX_BYTES:
                        # Too large to inline — save as attachment
                        saved_name = vault.save_attachment(name, content)
                        parts.append(
                            f"\n[System: Large file '{name}' saved as '{saved_name}'. "
                            f"Include [[{saved_name}]] in your output.]"
                        )
                    else:
                        text_content = content.decode("utf-8")
                        parts.append(f"\n### File: {name}\n```\n{text_content}\n```")

                except UnicodeDecodeError:
                    # Binary file with unrecognised MIME — save it
                    saved_name = vault.save_attachment(name, content)
                    logging.info(f"Saved unknown binary: {saved_name}")
                    parts.append(
                        f"\n[System: Binary file '{name}' saved as '{saved_name}'. "
                        f"Include [[{saved_name}]] in your output.]"
                    )

        except Exception as e:
            logging.warning(f"Failed to process attachment '{name}': {e}")

    return parts


def register_listeners(app, vault: Vault, processor):
    """
    Register Slack event handlers on the given app.

    Args:
        app: The slack_bolt App instance.
        vault: Vault instance for file I/O.
        processor: GeminiProcessor instance.
    """

    @app.event("message")
    def handle_message(event, say):
        # Allow file_share subtype, ignore all other subtypes and bots
        subtype = event.get("subtype")
        if (subtype and subtype != "file_share") or event.get("bot_id"):
            return

        text = event.get("text") or ""
        files = event.get("files", [])
        logging.info(f"📥 Incoming: {text[:60]}... ({len(files)} files)")

        try:
            # Process attachments
            attachment_context = _process_attachments(files, vault)

            # Run through Gemini
            data, token_count, is_answer = processor.process(text, attachment_context)

            if is_answer:
                say(str(data))
                return

            # Save the note
            file_path = vault.save_note(
                folder=data["folder"],
                slug=data["slug"],
                content=data["content"],
            )

            folder = data["folder"]
            filename = file_path.name
            say(f"📂 Filed to `{folder}/` as `{filename}` ({token_count} tokens)")

        except Exception as e:
            logging.exception("Error processing message")
            say(f"⚠️ Brain Error: {e}")
