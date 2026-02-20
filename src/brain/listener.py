"""
listener.py — Telegram message handlers.

Handles incoming messages, downloads attachments,
delegates to the agent router, and replies in Telegram.
"""

import io
import logging
import os
import re

import requests
from google.genai import types
from telegram import Message, Update
from telegram.ext import ContextTypes

from .agents import MessageContext, Router
from .processor import GEMINI_BINARY_MIMES, TEXT_INLINE_MAX_BYTES, _normalize_mime
from .vault import Vault

# Telegram user IDs allowed to interact with the bot (empty = allow all)
_ALLOWED_USERS: set[str] = {
    uid.strip()
    for uid in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if uid.strip()
}

# Regex to extract plain URLs from message text
_URL_PATTERN = re.compile(r"https?://\S+")

# oEmbed endpoints keyed by domain fragments.
# Each value is the provider's oEmbed URL; the video URL is appended as ?url=…
_OEMBED_ENDPOINTS: dict[str, str] = {
    "youtube.com": "https://www.youtube.com/oembed",
    "youtu.be": "https://www.youtube.com/oembed",
    "music.youtube.com": "https://www.youtube.com/oembed",
    "vimeo.com": "https://vimeo.com/api/oembed.json",
}


def _fetch_url_titles(text: str) -> str:
    """Extract URLs from message text and fetch their oEmbed metadata.

    Uses oEmbed APIs (YouTube, Vimeo) to retrieve the actual video title
    and author, then appends the metadata so Gemini can use them for
    naming the note.

    Returns:
        Extra context string to append to the message, or empty string.
    """
    urls = _URL_PATTERN.findall(text)
    if not urls:
        return ""

    enrichments: list[str] = []
    for url in urls:
        oembed_url: str | None = None
        for domain, endpoint in _OEMBED_ENDPOINTS.items():
            if domain in url:
                oembed_url = endpoint
                break
        if oembed_url is None:
            continue

        try:
            resp = requests.get(
                oembed_url,
                params={"url": url, "format": "json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            title = data.get("title", "").strip()
            author = data.get("author_name", "").strip()
            if title:
                parts = [f'Page title for {url} is: "{title}".']
                if author:
                    parts.append(f'Author/channel: "{author}".')
                parts.append("Use this as the note title and filename.")
                enrichments.append(f"[System: {' '.join(parts)}]")
                logging.info("oEmbed title for %s: %s (by %s)", url, title, author)
        except Exception as e:
            logging.warning("Failed to fetch oEmbed for %s: %s", url, e)

    return "\n".join(enrichments)


async def _transcribe_voice(ogg_bytes: bytes) -> str:
    """Transcribe a Telegram voice message using OpenAI Whisper.

    Returns:
        Transcribed text, or empty string if transcription fails or
        OPENAI_API_KEY is not set.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        logging.warning("OPENAI_API_KEY not set — skipping voice transcription")
        return ""

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        audio_file = io.BytesIO(ogg_bytes)
        audio_file.name = "voice.ogg"
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )
        logging.info("Whisper transcription: %s", transcript.text[:80])
        return transcript.text
    except Exception as e:
        logging.warning("Voice transcription failed: %s", e)
        return ""


async def _process_tg_attachments(
    message: Message, vault: Vault, bot
) -> tuple[list, str]:
    """Download Telegram attachments and prepare prompt context.

    Handles photos, documents, and voice messages.
    Voice is transcribed via Whisper and returned separately as text.

    Returns:
        (parts, voice_text) — parts is a list of prompt parts for Gemini,
        voice_text is the transcription (empty string if no voice message).
    """
    parts: list[str | types.Part] = []
    voice_text = ""

    async def _save_binary(file_id: str, name: str, mime: str) -> None:
        tg_file = await bot.get_file(file_id)
        content = bytes(await tg_file.download_as_bytearray())
        normalised_mime = _normalize_mime(mime)

        if normalised_mime in GEMINI_BINARY_MIMES:
            saved_name = vault.save_attachment(name, content)
            logging.info("Saved binary attachment: %s (%s)", saved_name, mime)
            parts.append(types.Part.from_bytes(data=content, mime_type=normalised_mime))
            link_syntax = (
                f"![[{saved_name}]]"
                if normalised_mime.startswith("image/")
                else f"[[{saved_name}]]"
            )
            parts.append(
                f"\n[System: Attachment '{name}' saved as '{saved_name}'. "
                f"Include {link_syntax} in your output to link it.]"
            )
        else:
            if len(content) > TEXT_INLINE_MAX_BYTES:
                saved_name = vault.save_attachment(name, content)
                parts.append(
                    f"\n[System: Large file '{name}' saved as '{saved_name}'. "
                    f"Include [[{saved_name}]] in your output.]"
                )
            else:
                try:
                    text_content = content.decode("utf-8")
                    parts.append(f"\n### File: {name}\n```\n{text_content}\n```")
                except UnicodeDecodeError:
                    saved_name = vault.save_attachment(name, content)
                    logging.info("Saved unknown binary: %s", saved_name)
                    parts.append(
                        f"\n[System: Binary file '{name}' saved as '{saved_name}'. "
                        f"Include [[{saved_name}]] in your output.]"
                    )

    # Photos — Telegram sends multiple sizes; take the largest (-1)
    if message.photo:
        parts.append("\n## Attachments")
        photo = message.photo[-1]
        await _save_binary(photo.file_id, "photo.jpg", "image/jpeg")

    # Documents (PDFs, text files, arbitrary files)
    if message.document:
        if not parts:
            parts.append("\n## Attachments")
        doc = message.document
        name = doc.file_name or "document"
        mime = doc.mime_type or "application/octet-stream"
        await _save_binary(doc.file_id, name, mime)

    # Voice messages — transcribe with Whisper
    if message.voice:
        tg_file = await bot.get_file(message.voice.file_id)
        ogg_bytes = bytes(await tg_file.download_as_bytearray())
        voice_text = await _transcribe_voice(ogg_bytes)
        if voice_text:
            logging.info("Voice message transcribed (%d chars)", len(voice_text))
        else:
            # Fallback: save the ogg file to vault
            saved_name = vault.save_attachment("voice.ogg", ogg_bytes)
            parts.append(
                f"\n[System: Voice message saved as '{saved_name}' "
                "(transcription unavailable).]"
            )

    return parts, voice_text


def _get_reply_context(message: Message) -> list[dict]:
    """Extract shallow reply context from a Telegram reply chain.

    Telegram doesn't expose full thread history via the API in polling mode,
    so we capture just the single message being replied to.

    Returns:
        List of dicts with 'role' and 'text' keys, or empty list.
    """
    reply = message.reply_to_message
    if not reply:
        return []

    role = "assistant" if reply.from_user and reply.from_user.is_bot else "user"
    text = reply.text or reply.caption or ""
    if not text:
        return []

    return [{"role": role, "text": text}]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main Telegram message handler.

    Validates the sender, processes attachments, enriches text with URL
    metadata, builds a MessageContext, routes to the appropriate agent,
    and replies to the user.
    """
    message = update.message
    if not message:
        return

    # Security: reject messages from users not in the allowlist
    user_id = str(update.effective_user.id) if update.effective_user else ""
    if _ALLOWED_USERS and user_id not in _ALLOWED_USERS:
        logging.warning("Rejected message from unlisted user %s", user_id)
        return

    vault: Vault = context.bot_data["vault"]
    router: Router = context.bot_data["router"]

    # Prefer text; fall back to caption (set on photo/document messages)
    text = message.text or message.caption or ""
    logging.info(
        "📥 Incoming: %s... (photo=%s doc=%s voice=%s)",
        text[:60],
        bool(message.photo),
        bool(message.document),
        bool(message.voice),
    )

    try:
        # Process attachments (photos, documents, voice)
        attachment_context, voice_text = await _process_tg_attachments(
            message, vault, context.bot
        )

        # Prepend voice transcription to text if present
        if voice_text:
            text = f"{voice_text}\n{text}".strip()

        # Enrich text with URL oEmbed metadata
        url_context = _fetch_url_titles(text)
        enriched_text = f"{text}\n{url_context}" if url_context else text

        # Shallow reply context from Telegram reply chain
        thread_history = _get_reply_context(message)
        if thread_history:
            logging.info("Reply context: 1 prior message")

        # Build context and route to the appropriate agent
        msg_context = MessageContext(
            raw_text=enriched_text,
            attachment_context=attachment_context,
            vault=vault,
            thread_history=thread_history,
        )
        result = router.route(msg_context)

        if result.response_text:
            await message.reply_text(result.response_text)

    except Exception as e:
        logging.exception("Error processing message")
        await message.reply_text(f"⚠️ Brain Error: {e}")
