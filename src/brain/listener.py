"""
listener.py — Slack event handlers.

Handles incoming messages, downloads attachments,
delegates to the agent router, and replies in Slack.
"""

import logging
import os
import re

import requests
from google.genai import types

from .agents import MessageContext, Router
from .processor import GEMINI_BINARY_MIMES, TEXT_INLINE_MAX_BYTES, _normalize_mime
from .vault import Vault

# Maximum number of prior thread messages to include for context
MAX_THREAD_MESSAGES = 10

# Regex to find URLs in message text (Slack wraps them in < >)
_URL_PATTERN = re.compile(r"<(https?://[^>|]+)(?:\|[^>]*)?>")

# Domains worth fetching page titles from
_TITLE_DOMAINS = {"youtube.com", "youtu.be", "music.youtube.com", "vimeo.com"}

# HTML <title> tag extraction
_TITLE_TAG = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


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


def _fetch_url_titles(text: str) -> str:
    """Extract URLs from Slack message text and fetch their page titles.

    Fetches the HTML ``<title>`` for media URLs (YouTube, Vimeo, etc.)
    and appends the metadata so Gemini can use the actual video/song
    title for naming.

    Returns:
        Extra context string to append to the message, or empty string.
    """
    urls = _URL_PATTERN.findall(text)
    if not urls:
        return ""

    enrichments: list[str] = []
    for url in urls:
        # Only fetch titles for known media domains
        if not any(domain in url for domain in _TITLE_DOMAINS):
            continue

        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
                allow_redirects=True,
            )
            resp.raise_for_status()
            match = _TITLE_TAG.search(resp.text[:10000])
            if match:
                title = match.group(1).strip()
                # Clean up common YouTube suffixes
                title = re.sub(r"\s*[-–—]\s*YouTube$", "", title)
                enrichments.append(
                    f'[System: Page title for {url} is: "{title}". '
                    f"Use this as the note title and filename.]"
                )
                logging.info("Fetched page title for %s: %s", url, title)
        except Exception as e:
            logging.warning("Failed to fetch title for %s: %s", url, e)

    return "\n".join(enrichments)


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

    parts: list[str | types.Part] = ["\n## Attachments"]

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


def _fetch_thread_history(
    client, channel: str, thread_ts: str, current_ts: str
) -> list[dict]:
    """
    Fetch prior messages from a Slack thread for conversation context.

    Returns a list of dicts with keys: role ('user' | 'assistant'), text.
    Oldest messages first, capped at MAX_THREAD_MESSAGES.
    The current message (current_ts) is excluded.
    """
    try:
        resp = client.conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=MAX_THREAD_MESSAGES + 5,  # fetch a few extra to filter
        )
    except Exception as e:
        logging.warning("Failed to fetch thread history: %s", e)
        return []

    history = []
    for msg in resp.get("messages", []):
        # Skip the current message
        if msg.get("ts") == current_ts:
            continue
        # Determine role
        role = "assistant" if msg.get("bot_id") else "user"
        text = msg.get("text", "").strip()
        if text:
            history.append({"role": role, "text": text})

    # Cap and return oldest-first
    return history[-MAX_THREAD_MESSAGES:]


def register_listeners(app, vault: Vault, router: Router):
    """
    Register Slack event handlers on the given app.

    Args:
        app: The slack_bolt App instance.
        vault: Vault instance for file I/O.
        router: Router instance for dispatching messages to agents.
    """

    @app.event("message")
    def handle_message(event, say, client):
        # Allow file_share subtype, ignore all other subtypes and bots
        subtype = event.get("subtype")
        if (subtype and subtype != "file_share") or event.get("bot_id"):
            return

        text = event.get("text") or ""
        files = event.get("files", [])
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts")
        message_ts = event.get("ts", "")
        logging.info(f"📥 Incoming: {text[:60]}... ({len(files)} files)")

        try:
            # Process attachments
            attachment_context = _process_attachments(files, vault)

            # Enrich message with URL metadata (video titles, etc.)
            url_context = _fetch_url_titles(text)
            enriched_text = f"{text}\n{url_context}" if url_context else text

            # Fetch thread history if this message is in a thread
            thread_history = []
            if thread_ts:
                thread_history = _fetch_thread_history(
                    client, channel, thread_ts, message_ts
                )
                logging.info("Thread context: %d prior messages", len(thread_history))

            # Build context and route to the appropriate agent
            context = MessageContext(
                raw_text=enriched_text,
                attachment_context=attachment_context,
                vault=vault,
                thread_history=thread_history,
            )
            result = router.route(context)

            if result.response_text:
                # Reply in-thread if the message was in a thread
                say(
                    result.response_text,
                    thread_ts=thread_ts or message_ts,
                )

        except Exception as e:
            logging.exception("Error processing message")
            say(f"⚠️ Brain Error: {e}")
