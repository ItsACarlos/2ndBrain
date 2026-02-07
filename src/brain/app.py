#!/usr/bin/env python3
"""
app.py — Application entrypoint.

Sets up logging, validates environment, initialises all components,
and starts the Slack socket-mode listener with the daily briefing
scheduler running in a background thread.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .briefing import start_scheduler
from .listener import register_listeners
from .processor import GeminiProcessor
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

REQUIRED_ENV = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "GEMINI_API_KEY"]


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

    # Initialise processor with knowledge of existing projects
    processor = GeminiProcessor(existing_projects=vault.list_projects())

    # Initialise Slack app
    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    # Wire up event handlers
    register_listeners(app, vault, processor)

    # Start daily briefing scheduler in background thread
    start_scheduler(app.client, vault)

    # Start listening
    logging.info("⚡️ 2ndBrain Collector starting up...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()


if __name__ == "__main__":
    main()
