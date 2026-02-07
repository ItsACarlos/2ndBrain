"""
router.py — Message router: classifies intent and dispatches to agents.

Uses a lightweight Gemini call to determine which registered agent
should handle an incoming Slack message.  The routing prompt is built
dynamically from agent descriptions so new agents are picked up
automatically.
"""

import logging
from datetime import datetime
from pathlib import Path

from google import genai

from ..processor import _extract_json
from .base import AgentResult, BaseAgent, MessageContext, format_thread_history

ROUTER_PROMPT_FILE = Path(__file__).parent / "router_prompt.md"


class Router:
    """Classifies incoming messages and dispatches to the appropriate agent."""

    def __init__(
        self,
        agents: dict[str, BaseAgent],
        default_agent: str = "file",
    ):
        self.client = genai.Client()
        self.model_name = "gemini-2.5-flash"
        self.agents = agents
        self.default_agent = default_agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, context: MessageContext) -> AgentResult:
        """Classify a message and dispatch to the right agent."""

        intent_data = self._classify(context)
        intent = intent_data.get("intent", self.default_agent)

        # Simple questions are answered directly by the router — no
        # second Gemini call needed.
        if intent == "question":
            answer = intent_data.get("answer", "")
            if answer:
                tokens = intent_data.get("_tokens", 0)
                return AgentResult(response_text=answer, tokens_used=tokens)

        # Look up the registered agent
        agent = self.agents.get(intent)
        if agent is None:
            logging.warning(
                "Unknown intent '%s', falling back to '%s'",
                intent,
                self.default_agent,
            )
            agent = self.agents[self.default_agent]

        # Forward router metadata so the agent can use it
        context.router_data = intent_data

        return agent.handle(context)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classify(self, context: MessageContext) -> dict:
        """Call Gemini to classify the message intent."""

        prompt_template = ROUTER_PROMPT_FILE.read_text(encoding="utf-8")

        # Build agent descriptions dynamically
        agent_lines = []
        for name, agent in self.agents.items():
            agent_lines.append(f'- **"{name}"**: {agent.description}')
        agent_descriptions = "\n".join(agent_lines)

        prompt = prompt_template.replace(
            "{{agent_descriptions}}", agent_descriptions
        ).replace("{{current_time}}", datetime.now().strftime("%Y-%m-%d %H:%M"))

        parts: list = [prompt, f"\n## User Message\n{context.raw_text}"]

        # Include conversation history for follow-up context
        thread_section = format_thread_history(context.thread_history)
        if thread_section:
            parts.insert(1, thread_section)

        # Include text descriptions of attachments for routing (not
        # binary data — that is reserved for the handling agent).
        if context.attachment_context:
            text_parts = [p for p in context.attachment_context if isinstance(p, str)]
            if text_parts:
                parts.extend(text_parts)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=parts,
            )
        except Exception as e:
            logging.error("Router Gemini error: %s", e)
            return {"intent": self.default_agent}

        tokens = response.usage_metadata.total_token_count

        data = _extract_json(response.text)
        if data is None:
            logging.warning(
                "Router returned unparseable response, defaulting to '%s'",
                self.default_agent,
            )
            return {"intent": self.default_agent}

        data["_tokens"] = tokens
        logging.info(
            "Router classified intent: %s (%d tokens)",
            data.get("intent"),
            tokens,
        )
        return data
