"""
filing.py — Filing agent: classifies and archives content into the vault.

This is the original "happy path" — content comes in via Slack and gets
filed into the correct Obsidian vault category with full YAML frontmatter.
"""

import logging
from datetime import datetime
from pathlib import Path

from google import genai

from ..processor import _extract_json, _inject_tokens
from .base import AgentResult, BaseAgent, MessageContext, format_thread_history

FILING_PROMPT_FILE = Path(__file__).parent.parent / "prompt.md"


class FilingAgent(BaseAgent):
    """Archives incoming content into the appropriate vault category."""

    name = "file"
    description = (
        "Archives content into the Obsidian vault — notes, links, images, "
        "tasks, bookmarks, reference material, or any content to save."
    )

    def __init__(self, existing_projects: list[str] | None = None):
        self.client = genai.Client()
        self.model_name = "gemini-2.5-flash"
        self.existing_projects = existing_projects or []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def handle(self, context: MessageContext) -> AgentResult:
        """Classify the content and file it into the vault."""

        parts = self._build_prompt(context)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=parts,
            )
        except Exception as e:
            logging.error("Filing agent Gemini error: %s", e)
            raise

        tokens = response.usage_metadata.total_token_count
        data = _extract_json(response.text)

        if data is None:
            # Gemini returned plain text — treat as a direct answer
            return AgentResult(response_text=response.text, tokens_used=tokens)

        # Validate required fields
        if "folder" not in data or "content" not in data:
            logging.warning("Filing: incomplete JSON keys: %s", list(data.keys()))
            return AgentResult(response_text=response.text, tokens_used=tokens)

        # Ensure slug
        if "slug" not in data:
            data["slug"] = datetime.now().strftime("capture-%Y%m%d-%H%M")

        # Inject token count into frontmatter
        data["content"] = _inject_tokens(data["content"], tokens)

        # Save to vault
        file_path = context.vault.save_note(
            folder=data["folder"],
            slug=data["slug"],
            content=data["content"],
        )

        folder = data["folder"]
        filename = file_path.name
        return AgentResult(
            response_text=(
                f"📂 Filed to `{folder}/` as `{filename}` ({tokens} tokens)"
            ),
            filed_path=file_path,
            tokens_used=tokens,
        )

    def refresh_projects(self, vault) -> None:
        """Re-scan the vault for project names (call after filing)."""
        self.existing_projects = vault.list_projects()

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(self, context: MessageContext) -> list:
        """Build the full filing prompt with project context."""

        system_prompt = FILING_PROMPT_FILE.read_text(encoding="utf-8")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        context_parts = [f"Current time: {current_time}"]

        if self.existing_projects:
            projects_list = ", ".join(self.existing_projects)
            context_parts.append(
                f"Existing projects in the vault: [{projects_list}]. "
                "If the input relates to one, set project to its name."
            )

        context_text = "\n".join(context_parts)

        parts: list = [
            system_prompt,
            f"\n## Context\n{context_text}",
            f"\n## Input\n{context.raw_text}",
        ]

        # Include conversation history for threaded follow-ups
        thread_section = format_thread_history(context.thread_history)
        if thread_section:
            parts.insert(2, thread_section)

        if context.attachment_context:
            parts.extend(context.attachment_context)

        return parts
