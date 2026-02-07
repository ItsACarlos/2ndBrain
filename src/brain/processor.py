"""
processor.py — Gemini AI processing.

Builds prompts, calls Gemini, parses structured JSON responses,
and injects token usage into frontmatter.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

PROMPT_FILE = Path(__file__).parent / "prompt.md"

# Size threshold: text files smaller than this are inlined in the prompt
TEXT_INLINE_MAX_BYTES = 50 * 1024  # 50 KB

# MIME types that Gemini can process as binary data parts
GEMINI_BINARY_MIMES = frozenset(
    [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    ]
)


def _normalize_mime(mime: str) -> str:
    """Normalize common MIME type variants."""
    if mime == "image/jpg":
        return "image/jpeg"
    return mime


def _extract_json(text: str) -> dict | None:
    """
    Extract JSON from a Gemini response.

    Strategy:
    1. Look for a ```json fenced block first.
    2. Fall back to finding the outermost { ... } pair with brace balancing.
    """
    # Strategy 1: fenced code block
    fence_match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 2: balanced brace matching
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None

    return None


def _inject_tokens(content: str, tokens: int) -> str:
    """
    Inject tokens_used into frontmatter by parsing the YAML block
    rather than doing a fragile string replace.
    """
    if not content.startswith("---"):
        # No frontmatter — prepend one with just tokens_used
        return f"---\ntokens_used: {tokens}\n---\n{content}"

    end = content.find("---", 3)
    if end == -1:
        return content

    frontmatter_block = content[3:end]
    rest = content[end:]

    # Insert tokens_used as the last frontmatter field
    frontmatter_block = frontmatter_block.rstrip("\n") + f"\ntokens_used: {tokens}\n"

    return f"---{frontmatter_block}{rest}"


class GeminiProcessor:
    """Handles all Gemini AI interactions for note processing."""

    def __init__(self, existing_projects: list[str] | None = None):
        self.client = genai.Client()  # reads GEMINI_API_KEY from env
        self.model_name = "gemini-2.5-flash"
        self.existing_projects = existing_projects or []

    def process(
        self,
        raw_text: str,
        attachment_context: list | None = None,
    ) -> tuple[dict | str, int, bool]:
        """
        Process a Slack message through Gemini.

        Args:
            raw_text: The message text from Slack.
            attachment_context: List of prompt parts for attachments
                (strings, and/or binary data dicts).

        Returns:
            Tuple of (data, token_count, is_answer).
            - If is_answer is True, data is a plain string response.
            - Otherwise, data is a dict with 'folder', 'slug', 'content'.
        """
        parts = self._build_prompt(raw_text, attachment_context)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=parts,
            )
        except Exception as e:
            logging.error(f"Gemini API error: {e}")
            raise

        usage = response.usage_metadata
        tokens = usage.total_token_count

        # Try to parse structured JSON
        data = _extract_json(response.text)

        if data is None:
            # No JSON found — treat as a direct answer to a question
            return response.text, tokens, True

        # Validate required fields
        if "folder" not in data or "content" not in data:
            logging.warning(f"Gemini returned incomplete JSON: {list(data.keys())}")
            return response.text, tokens, True

        # Ensure slug exists
        if "slug" not in data:
            # Generate a basic slug from the date
            data["slug"] = datetime.now().strftime("capture-%Y%m%d-%H%M")

        # Inject token count into frontmatter
        data["content"] = _inject_tokens(data["content"], tokens)

        return data, tokens, False

    def _build_prompt(
        self,
        raw_text: str,
        attachment_context: list | None = None,
    ) -> list:
        """Build the multimodal prompt parts list."""
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Context section
        context_parts = [f"Current time: {current_time}"]

        if self.existing_projects:
            projects_list = ", ".join(self.existing_projects)
            context_parts.append(
                f"Existing projects in the vault: [{projects_list}]. "
                "If the input relates to one, set project to its name."
            )

        context = "\n".join(context_parts)

        parts = [
            system_prompt,
            f"\n## Context\n{context}",
            f"\n## Input\n{raw_text}",
        ]

        # Append attachment context (strings + binary data dicts)
        if attachment_context:
            parts.extend(attachment_context)

        return parts
