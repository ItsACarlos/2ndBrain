"""
memory.py — Memory agent: manages persistent directives.

Handles "remember", "forget", and "list directives" commands.
Directives are stored in ``_brain/directives.md`` in the vault and
are included in agent prompts to influence behaviour.
"""

import logging

from .base import AgentResult, BaseAgent, MessageContext


class MemoryAgent(BaseAgent):
    """Adds, removes, and lists persistent directives (long-term memory)."""

    name = "memory"
    description = (
        "Manages persistent directives — 'remember' to add a behaviour rule, "
        "'forget' to remove one, 'list directives' to see all current rules."
    )

    def handle(self, context: MessageContext) -> AgentResult:
        """Dispatch to add, remove, or list based on router_data."""

        action = context.router_data.get("memory_action", "list")
        directive_text = context.router_data.get("directive_text", "")
        directive_index = context.router_data.get("directive_index")

        if action == "add" and directive_text:
            return self._add(context, directive_text)
        elif action == "remove" and directive_index is not None:
            return self._remove(context, directive_index)
        else:
            return self._list(context)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add(self, context: MessageContext, directive: str) -> AgentResult:
        """Add a new directive."""
        directives = context.vault.add_directive(directive)
        logging.info("Memory: added directive (%d total)", len(directives))
        return AgentResult(
            response_text=(
                f"✅ Remembered: _{directive}_\n"
                f"I now have {len(directives)} directive(s)."
            ),
        )

    def _remove(self, context: MessageContext, index: int) -> AgentResult:
        """Remove a directive by index."""
        removed, directives = context.vault.remove_directive(index)
        if removed:
            return AgentResult(
                response_text=(
                    f"🗑️ Forgot directive #{index}: _{removed}_\n"
                    f"{len(directives)} directive(s) remaining."
                ),
            )
        return AgentResult(
            response_text=(
                f"⚠️ No directive #{index}. "
                f"I have {len(directives)} directive(s). "
                "Use 'list directives' to see them."
            ),
        )

    def _list(self, context: MessageContext) -> AgentResult:
        """List all current directives."""
        directives = context.vault.get_directives()
        if not directives:
            return AgentResult(
                response_text=(
                    "I don't have any directives yet. "
                    "Send me 'remember: <rule>' to add one."
                ),
            )

        lines = ["📋 *Current Directives:*"]
        for i, d in enumerate(directives, 1):
            lines.append(f"  {i}. {d}")
        lines.append(
            f"\n_{len(directives)} directive(s). Say 'forget #N' to remove one._"
        )
        return AgentResult(response_text="\n".join(lines))
