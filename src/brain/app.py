#!/usr/bin/env python3
"""
app.py — Application entrypoint.

Sets up logging, validates environment, initialises all components,
and starts the Telegram bot with the daily briefing scheduler
running in a background thread.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from telegram.ext import Application, MessageHandler, filters

from .agents import Router
from .agents.filing import FilingAgent
from .agents.memory import MemoryAgent
from .agents.vault_edit import VaultEditAgent
from .agents.vault_query import VaultQueryAgent
from .briefing import start_scheduler
from .listener import handle_message
from .vault import Vault

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()

REQUIRED_ENV = ["TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY"]


def _validate_env():
    """Fail fast if any required environment variable is missing."""
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k, "").strip()]
    if missing:
        logging.critical(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    _validate_env()

    # Initialise Vault (creates folders + .base files on first run)
    vault = Vault()

    # Initialise pluggable agents
    filing_agent = FilingAgent(existing_projects=vault.list_projects())
    vault_query_agent = VaultQueryAgent()
    vault_edit_agent = VaultEditAgent()
    memory_agent = MemoryAgent()

    # Build the router with registered agents
    router = Router(
        agents={
            filing_agent.name: filing_agent,
            vault_query_agent.name: vault_query_agent,
            vault_edit_agent.name: vault_edit_agent,
            memory_agent.name: memory_agent,
        },
        default_agent="file",
    )

    # Initialise Telegram bot
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    # Store shared objects for handlers to access
    app.bot_data["vault"] = vault
    app.bot_data["router"] = router

    # Wire up message handler (handles text, photos, documents, voice)
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VOICE,
            handle_message,
        )
    )

    # Start daily briefing scheduler in background thread
    start_scheduler(app.bot, vault)

    # Start polling
    logging.info("⚡️ 2ndBrain Collector starting up (Telegram)...")
    app.run_polling()


if __name__ == "__main__":
    main()
