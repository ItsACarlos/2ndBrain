"""
vault_query.py — Vault Query agent: searches the vault and answers questions.

Supports three query modes:
- **default**: keyword search + frontmatter, top matches sent to Gemini
- **metadata**: lightweight full-vault index (name, size, date, frontmatter)
- **grep**: local text search across file contents, results sent to Gemini
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
        "open actions, filed media, project notes, recent captures, etc. "
        "Supports metadata listings, text search, and content queries."
    )

    def __init__(self):
        self.client = genai.Client()
        self.model_name = "gemini-2.5-flash"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def handle(self, context: MessageContext) -> AgentResult:
        """Route to the appropriate query strategy."""

        mode = context.router_data.get("query_mode", "default")

        if mode == "metadata":
            return self._handle_metadata(context)
        elif mode == "grep":
            return self._handle_grep(context)
        else:
            return self._handle_default(context)

    # ------------------------------------------------------------------
    # Strategy: default (keyword search, limited matches)
    # ------------------------------------------------------------------

    def _handle_default(self, context: MessageContext) -> AgentResult:
        """Original strategy: keyword + frontmatter search."""

        search_terms = context.router_data.get("search_terms", [])
        folders = context.router_data.get("folders")
        question = context.router_data.get("question", context.raw_text)

        matches = context.vault.search_notes(
            keywords=search_terms,
            folders=folders,
        )

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
                    "I searched the vault but didn't find any matching "
                    "notes. Try rephrasing your question or being more "
                    "specific about what you're looking for."
                ),
                tokens_used=0,
            )

        note_summaries = self._format_matches(matches)
        prompt = self._build_prompt(question, note_summaries, context)

        return self._ask_gemini(prompt, len(matches), "default")

    # ------------------------------------------------------------------
    # Strategy: metadata (full-vault index, no file contents)
    # ------------------------------------------------------------------

    def _handle_metadata(self, context: MessageContext) -> AgentResult:
        """Lightweight index of all vault files for stats/listing queries."""

        folders = context.router_data.get("folders")
        question = context.router_data.get("question", context.raw_text)

        index = context.vault.index_all_notes(
            folders=folders,
            max_results=500,
        )

        if not index:
            return AgentResult(
                response_text="The vault appears to be empty.",
                tokens_used=0,
            )

        note_summaries = self._format_matches(index)

        prompt = self._build_prompt(
            question,
            note_summaries,
            context,
            preamble=(
                "Below is a complete metadata index of ALL notes in the "
                "vault (no file body text, just filenames, folders, "
                "sizes, dates, and frontmatter properties). "
                f"Total files: {len(index)}.\n\n"
                "Use this to answer the user's question about "
                "statistics, rankings, listings, or file properties."
            ),
        )

        return self._ask_gemini(prompt, len(index), "metadata")

    # ------------------------------------------------------------------
    # Strategy: grep (local text search, no full contents to Gemini)
    # ------------------------------------------------------------------

    def _handle_grep(self, context: MessageContext) -> AgentResult:
        """Text search across vault file contents."""

        search_terms = context.router_data.get("search_terms", [])
        folders = context.router_data.get("folders")
        question = context.router_data.get("question", context.raw_text)

        if not search_terms:
            return AgentResult(
                response_text=(
                    "I need a search term to grep for. "
                    "What word or phrase should I look for?"
                ),
                tokens_used=0,
            )

        # Search for each term and merge results
        all_results: list[dict] = []
        seen: set[str] = set()

        for term in search_terms:
            hits = context.vault.grep_notes(
                pattern=term,
                folders=folders,
                max_results=100,
            )
            for hit in hits:
                key = f"{hit['folder']}/{hit['filename']}"
                if key not in seen:
                    seen.add(key)
                    all_results.append(hit)

        if not all_results:
            terms_str = ", ".join(f'"{t}"' for t in search_terms)
            return AgentResult(
                response_text=(f"No files in the vault contain {terms_str}."),
                tokens_used=0,
            )

        grep_summary = self._format_grep_results(all_results)

        prompt = self._build_prompt(
            question,
            grep_summary,
            context,
            preamble=(
                "Below are the results of a text search across all "
                "vault files. Each entry shows the filename, folder, "
                "number of matches, and short context snippets around "
                f"each match. Total files matched: {len(all_results)}."
            ),
        )

        return self._ask_gemini(prompt, len(all_results), "grep")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _ask_gemini(
        self, prompt: list[str], match_count: int, mode: str
    ) -> AgentResult:
        """Send the assembled prompt to Gemini and return the result."""
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
            "VaultQuery [%s]: %d matches, %d tokens",
            mode,
            match_count,
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
                fs_items.append(f"~{m['word_count']} words")
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

    @staticmethod
    def _format_grep_results(results: list[dict]) -> str:
        """Format grep search results into a concise text block."""
        lines = []
        for r in results:
            header = (
                f"- **{r['filename']}** (in {r['folder']}/) "
                f"— {r['match_count']} match(es)"
            )
            lines.append(header)
            for snippet in r.get("snippets", []):
                lines.append(f"  > {snippet}")
        return "\n".join(lines)

    def _build_prompt(
        self,
        question: str,
        note_summaries: str,
        context: MessageContext,
        preamble: str | None = None,
    ) -> list[str]:
        """Build the vault-query prompt."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        data_description = preamble or (
            "Below is a list of matching vault notes with their "
            "filenames, file-system metadata (size in bytes, word "
            "count, last modified date), and YAML frontmatter "
            "properties.  Use this information to answer the "
            "user's question.  If the metadata is insufficient, "
            "say so."
        )

        system = (
            "You are a helpful assistant answering questions about "
            "the user's Obsidian vault.  The vault is a personal "
            "knowledge base organised into folders: Projects, "
            "Actions, Media, Reference, Memories, Inbox.\n\n"
            f"Current time: {current_time}\n\n"
            f"{data_description}\n\n"
            "Respond in concise, conversational plain text suitable "
            "for Slack.  Use bullet points or numbered lists where "
            "appropriate.  Do NOT return JSON."
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
