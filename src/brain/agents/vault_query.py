"""
vault_query.py — Vault Query agent: searches the vault and answers questions.

Searches for matching notes by keyword / folder, collects their names and
YAML frontmatter metadata, then sends a focused query to Gemini to answer
the user's question about their filed content.
"""

import logging
from datetime import datetime

from google import genai

from .base import AgentResult, BaseAgent, MessageContext, format_thread_history
from .router import Router


class VaultQueryAgent(BaseAgent):
    """Searches the Obsidian vault and uses Gemini to answer questions."""

    name = "vault_query"
    description = (
        "Answers questions about previously saved vault content — "
        "open actions, filed media, project notes, recent captures, etc."
    )

    def __init__(self):
        self.client = genai.Client()
        self.model_name = "gemini-2.5-flash"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def handle(self, context: MessageContext) -> AgentResult:
        """Search the vault, build a retrieval prompt, and answer."""

        search_terms = context.router_data.get("search_terms", [])
        folders = context.router_data.get("folders")  # list or None
        question = context.router_data.get("question", context.raw_text)

        matches = context.vault.search_notes(
            keywords=search_terms,
            folders=folders,
        )

        # If keyword search returned nothing, retry without keywords
        # so aggregate queries ("largest", "most recent") still work.
        if not matches and search_terms:
            logging.info(
                "VaultQuery: no matches for %s, retrying without keywords",
                search_terms,
            )
            matches = context.vault.search_notes(
                keywords=None,
                folders=folders,
            )

        if not matches:
            return AgentResult(
                response_text=(
                    "I searched the vault but didn't find any matching notes. "
                    "Try rephrasing your question or being more specific about "
                    "what you're looking for."
                ),
                tokens_used=0,
            )

        # Build a compact representation of each match
        note_summaries = self._format_matches(matches)

        prompt = self._build_prompt(question, note_summaries, context)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
        except Exception as e:
            logging.error("VaultQuery agent Gemini error: %s", e)
            raise

        tokens = (
            (response.usage_metadata.total_token_count or 0)
            if response.usage_metadata
            else 0
        )
        logging.info(
            "VaultQuery: %d matches, %d tokens",
            len(matches),
            tokens,
        )

        return AgentResult(
            response_text=response.text or "",
            tokens_used=tokens,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _format_matches(matches: list[dict]) -> str:
        """Format matched notes into a concise text block."""
        lines = []
        for m in matches:
            parts = [f"- **{m['filename']}** (in {m['folder']}/)"]

            # File-system metadata
            fs_items = []
            if "size_bytes" in m:
                fs_items.append(f"{m['size_bytes']} bytes")
            if "word_count" in m:
                fs_items.append(f"{m['word_count']} words")
            if "modified" in m:
                fs_items.append(f"modified {m['modified']}")
            if fs_items:
                parts.append("  " + " | ".join(fs_items))

            # YAML frontmatter fields
            meta_items = []
            for key, value in m.get("frontmatter", {}).items():
                meta_items.append(f"{key}: {value}")
            if meta_items:
                parts.append("  " + " | ".join(meta_items))

            lines.append("\n".join(parts))

        return "\n".join(lines)

    def _build_prompt(
        self, question: str, note_summaries: str, context: MessageContext
    ) -> list[str]:
        """Build the vault-query prompt."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        system = (
            "You are a helpful assistant answering questions about the user's "
            "Obsidian vault.  The vault is a personal knowledge base organised "
            "into folders: Projects, Actions, Media, Reference, Inbox.\n\n"
            f"Current time: {current_time}\n\n"
            "Below is a list of matching vault notes with their filenames, "
            "file-system metadata (size in bytes, word count, last modified "
            "date), and YAML frontmatter properties.  Use this information to "
            "answer the user's question.  If the metadata is insufficient, "
            "say so.\n\n"
            "Respond in concise, conversational plain text suitable for Slack.  "
            "Use bullet points or numbered lists where appropriate.  Do NOT "
            "return JSON."
        )

        parts = [
            system,
            f"\n## Matching Notes\n{note_summaries}",
        ]

        # Inject persistent directives
        directives_text = Router.format_directives(context.vault)
        parts.append(f"\n## Directives\n{directives_text}")

        # Include conversation history for threaded follow-ups
        thread_section = format_thread_history(context.thread_history)
        if thread_section:
            parts.append(thread_section)

        parts.append(f"\n## Question\n{question}")

        return parts
