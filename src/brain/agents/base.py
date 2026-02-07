"""
base.py — Base classes for the pluggable agent architecture.

All agents subclass BaseAgent and return AgentResult. The Router
passes MessageContext to each agent's handle() method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..vault import Vault


@dataclass
class MessageContext:
    """Context passed to an agent for processing a Slack message."""

    raw_text: str
    attachment_context: list
    vault: Vault
    router_data: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Result returned by an agent after processing."""

    response_text: str | None = None
    filed_path: Path | None = None
    tokens_used: int = 0


class BaseAgent(ABC):
    """Abstract base class for pluggable agents.

    To create a new agent:
    1. Subclass BaseAgent
    2. Set ``name`` (used as intent identifier by the router)
    3. Set ``description`` (included in the router prompt so Gemini
       knows when to dispatch here)
    4. Implement ``handle()``
    5. Register the instance in app.py when building the Router

    Example::

        class SummaryAgent(BaseAgent):
            name = "summarise"
            description = "Summarises a collection of vault notes on a topic."

            def handle(self, context: MessageContext) -> AgentResult:
                ...
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def handle(self, context: MessageContext) -> AgentResult:
        """Process a message and return a result.

        Args:
            context: Message context with text, attachments, vault
                     reference, and data extracted by the router.

        Returns:
            AgentResult with response text and/or a filed path.
        """
        ...
