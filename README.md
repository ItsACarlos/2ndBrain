# 2ndBrain — Gemini-Powered Quick Capture for Obsidian

A Slack-driven quick-capture system that uses **Gemini AI** to classify,
enrich, and file notes into an **Obsidian vault**. Send messages — text,
images, PDFs — via Slack and they are automatically categorised with full
YAML frontmatter into the correct vault folder.

## Features

- **AI-powered filing** — Gemini 2.5 Flash classifies content into
  Projects, Actions, Media, Reference, or Inbox with structured frontmatter
- **Pluggable agent architecture** — Router dispatches messages to
  specialist agents; new capabilities are a single subclass away
- **Vault queries** — Ask questions about your filed content
  ("What actions are due this week?", "List my recent media saves")
- **Persistent memory** — Teach the bot rules via directives
  ("remember: always tag cooking recipes with #cooking")
- **Thread context** — Reply in a Slack thread for natural follow-up
  conversations with full history
- **Attachment handling** — Images and PDFs are saved to Attachments/
  and linked from notes with Obsidian wiki-links
- **Daily briefing** — Optional morning summary of open actions and
  recent captures posted to a Slack channel
- **Obsidian Bases dashboards** — Auto-generated `.base` files for
  Projects, Actions, Media, Reference, and a master Dashboard

## Architecture

```
Slack message → listener.py (attachment prep + thread history)
  → Router (Gemini classification) → intent JSON
  → FilingAgent | VaultQueryAgent | MemoryAgent | Direct answer
  → reply posted in Slack thread
```

See [docs/architecture.md](docs/architecture.md) for the full design
including Mermaid diagrams, and [AGENTS.md](AGENTS.md) for comprehensive
agent instructions.

## Tech Stack

| Component     | Technology                                      |
|---------------|-------------------------------------------------|
| Runtime       | Python 3.12, managed with `uv`                  |
| AI            | Gemini 2.5 Flash via `google-genai` SDK         |
| Messaging     | Slack Bolt (Socket Mode)                        |
| Vault         | Obsidian, synced via rclone to Google Drive      |
| Services      | systemd user units (no root required)           |
| Secrets       | GPG + `pass` for rclone config encryption        |

## Quick Start

```bash
# 1. Set up GPG + pass (first time only)
./setup-gpg-pass.sh

# 2. Configure rclone remote (see docs/setup_rclone.md)
rclone config

# 3. Create .env from template
cp .env.template .env
# Fill in SLACK_BOT_TOKEN, SLACK_APP_TOKEN, GEMINI_API_KEY

# 4. Install (choose one)
./install.sh --server       # Headless: rclone mount + Slack listener
./install.sh --workstation  # Desktop: rclone bisync for Obsidian

# 5. Check it's running
systemctl --user status brain.service
journalctl --user -u brain.service -f
```

See [docs/setup_slack_app.md](docs/setup_slack_app.md) for Slack app
creation and OAuth scopes, and [docs/setup_rclone.md](docs/setup_rclone.md)
for rclone configuration details.

## Documentation

| Document                                                  | Contents                              |
|-----------------------------------------------------------|---------------------------------------|
| [AGENTS.md](AGENTS.md)                                    | Full agent instructions & project ref |
| [docs/architecture.md](docs/architecture.md)              | Agent architecture & design           |
| [docs/architecture-decisions.md](docs/architecture-decisions.md) | Architecture Decision Records   |
| [docs/setup_rclone.md](docs/setup_rclone.md)              | rclone + GPG/pass setup               |
| [docs/setup_slack_app.md](docs/setup_slack_app.md)        | Slack app creation guide              |

## License

See [LICENSE.md](LICENSE.md).