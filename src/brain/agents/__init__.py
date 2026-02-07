"""
agents — Pluggable agent system for message routing and processing.

To add a new agent:
1. Create a new module in this package
2. Subclass BaseAgent, set name + description, implement handle()
3. Register the agent in app.py when building the Router

The Router dynamically builds its classification prompt from the
registered agents' descriptions, so new agents are automatically
included in intent routing.
"""

from .base import AgentResult, BaseAgent, MessageContext, format_thread_history
from .router import Router

__all__ = ["BaseAgent", "AgentResult", "MessageContext", "Router", "format_thread_history"]
