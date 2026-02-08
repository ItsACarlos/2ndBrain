"""
vault_edit.py — Vault Edit agent: modifies existing notes in the vault.

Supports bulk frontmatter updates (e.g. "set priority to urgent on all
matching notes") and targeted field changes on specific files.  Uses
Gemini to interpret the user's edit request and map it to concrete
``{filename → {field: value}}`` operations, then applies them via
``Vault.update_frontmatter()``.
"""

import logging
from datetime import datetime
from pathlib import Path

from google import genai

from ..processor import _extract_json
from .base import AgentResult, BaseAgent, MessageContext, format_thread_history
from .router import Router

#: System prompt sent to Gemini when planning edits.
_EDIT_PLANNER_PROMPT_FILE = Path(__file__).parent / "vault_edit_prompt.md"


#: Maximum number of files that can be edited in a single request.
#: Prevents accidental bulk damage from vague requests.
MAX_BULK_EDITS = 10


class VaultEditAgent(BaseAgent):
    """Modifies existing vault notes (frontmatter fields, bulk updates)."""

    name = "vault_edit"
    description = (
        "Edits existing vault notes — change frontmatter fields like "
        "priority, status, tags, or due_date across one or many files. "
        "Use when the user wants to *modify* existing notes rather than "
        "create new ones."
    )

    def __init__(self) -> None:
        self.client = genai.Client()
        self.model_name = "gemini-2.5-flash"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def handle(self, context: MessageContext) -> AgentResult:
        """Find target notes, plan edits via Gemini, apply them."""

        # 1. Find candidate notes using router-provided search terms
        candidates = self._find_candidates(context)
        if not candidates:
            return AgentResult(
                response_text=(
                    "I couldn't find any vault notes matching that request. "
                    "Try being more specific about which files to edit."
                ),
                tokens_used=0,
            )

        # 2. Ask Gemini to plan the edits
        edit_plan, tokens = self._plan_edits(context, candidates)
        if edit_plan is None:
            return AgentResult(
                response_text=(
                    "I wasn't able to figure out what edits to make. "
                    "Could you be more specific?"
                ),
                tokens_used=tokens,
            )

        edits = edit_plan.get("edits", [])
        if not edits:
            summary = edit_plan.get("summary", "No edits needed.")
            return AgentResult(response_text=summary, tokens_used=tokens)

        # 2b. Guard against excessively large bulk edits
        if len(edits) > MAX_BULK_EDITS:
            return AgentResult(
                response_text=(
                    f"⚠️ That would modify {len(edits)} files, but the "
                    f"safety limit is {MAX_BULK_EDITS}. Please narrow "
                    "your request or target specific files."
                ),
                tokens_used=tokens,
            )

        # 3. Apply edits
        results = self._apply_edits(context.vault, edits)

        # 4. Build response
        response = self._format_results(results, edit_plan.get("summary", ""))
        return AgentResult(response_text=response, tokens_used=tokens)

    # ------------------------------------------------------------------
    # Internal — file discovery
    # ------------------------------------------------------------------

    def _find_candidates(self, context: MessageContext) -> list[dict]:
        """Search the vault for notes matching the edit target."""

        search_terms = context.router_data.get("search_terms", [])
        folders = context.router_data.get("folders")
        target_files = context.router_data.get("target_files", [])

        # If the router extracted explicit filenames, find them directly
        if target_files:
            candidates: list[dict] = []
            for name in target_files:
                path = context.vault.find_note(name)
                if path:
                    # Use search_notes with the exact stem as keyword
                    matches = context.vault.search_notes(
                        keywords=[path.stem],
                        folders=[path.parent.name],
                        max_results=1,
                    )
                    if matches:
                        candidates.append(matches[0])
                    else:
                        candidates.append(
                            {
                                "filename": path.name,
                                "folder": path.parent.name,
                                "frontmatter": {},
                            }
                        )
            if candidates:
                return candidates

        # Fall back to keyword search
        return context.vault.search_notes(
            keywords=search_terms or None,
            folders=folders,
            max_results=50,
        )

    # ------------------------------------------------------------------
    # Internal — Gemini edit planning
    # ------------------------------------------------------------------

    def _plan_edits(
        self, context: MessageContext, candidates: list[dict]
    ) -> tuple[dict | None, int]:
        """Ask Gemini what edits to apply to the candidate files."""

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        prompt_template = _EDIT_PLANNER_PROMPT_FILE.read_text(encoding="utf-8")
        system = prompt_template.replace("{current_time}", current_time)

        # Build candidate summary
        cand_lines: list[str] = []
        for c in candidates:
            fm_str = ", ".join(f"{k}={v}" for k, v in c.get("frontmatter", {}).items())
            cand_lines.append(f"- {c['filename']} (in {c['folder']}/) [{fm_str}]")
        candidates_text = "\n".join(cand_lines)

        parts: list[str] = [
            system,
            f"\n## Candidate Notes\n{candidates_text}",
        ]

        # Inject directives
        directives_text = Router.format_directives(context.vault)
        parts.append(f"\n## Directives\n{directives_text}")

        # Thread history (critical for "set all those to …" follow-ups)
        thread_section = format_thread_history(context.thread_history)
        if thread_section:
            parts.append(thread_section)

        edit_desc = context.router_data.get("edit_description", context.raw_text)
        parts.append(f"\n## Edit Request\n{edit_desc}")

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=parts,
            )
        except Exception as e:
            logging.error("VaultEdit planner Gemini error: %s", e)
            raise

        tokens = (
            (response.usage_metadata.total_token_count or 0)
            if response.usage_metadata
            else 0
        )

        data = _extract_json(response.text or "")
        if data is None:
            logging.warning("VaultEdit: unparseable Gemini response")
            return None, tokens

        logging.info(
            "VaultEdit: planned %d edits (%d tokens)",
            len(data.get("edits", [])),
            tokens,
        )
        return data, tokens

    # ------------------------------------------------------------------
    # Internal — applying edits
    # ------------------------------------------------------------------

    def _apply_edits(self, vault, edits: list[dict]) -> list[dict]:
        """Apply planned edits and collect results per file."""

        results: list[dict] = []

        for edit in edits:
            filename = edit.get("filename", "")
            folder = edit.get("folder")
            updates = edit.get("frontmatter_updates", {})

            if not filename or not updates:
                continue

            path = vault.find_note(filename, folder=folder)
            if path is None:
                results.append({"filename": filename, "status": "not_found"})
                continue

            try:
                changed = vault.update_frontmatter(path, updates)
                results.append(
                    {
                        "filename": filename,
                        "folder": folder or path.parent.name,
                        "status": "ok",
                        "changed": changed,
                    }
                )
            except Exception as e:
                logging.error("VaultEdit: failed to edit %s: %s", filename, e)
                results.append(
                    {"filename": filename, "status": "error", "error": str(e)}
                )

        return results

    # ------------------------------------------------------------------
    # Internal — response formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_results(results: list[dict], summary: str) -> str:
        """Build a Slack-friendly response from the edit results."""

        ok = [r for r in results if r["status"] == "ok"]
        failed = [r for r in results if r["status"] != "ok"]

        lines: list[str] = []

        if summary:
            lines.append(f"✏️ {summary}")

        if ok:
            lines.append(f"\n*Updated {len(ok)} file(s):*")
            for r in ok:
                changes = ", ".join(f"{k}→{v}" for k, v in r.get("changed", {}).items())
                lines.append(f"  • `{r['filename']}` ({changes})")

        if failed:
            lines.append(f"\n⚠️ {len(failed)} file(s) could not be updated:")
            for r in failed:
                reason = r.get("error", r["status"])
                lines.append(f"  • `{r['filename']}` — {reason}")

        return "\n".join(lines) if lines else "No changes were made."
