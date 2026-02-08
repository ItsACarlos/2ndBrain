[![CI](https://github.com/gilesknap/2ndBrain/actions/workflows/ci.yml/badge.svg)](https://github.com/gilesknap/2ndBrain/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/gilesknap/2ndBrain/branch/main/graph/badge.svg)](https://codecov.io/gh/gilesknap/2ndBrain)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# 2ndBrain — Gemini-Powered Quick Capture for Obsidian

A Slack-driven quick-capture system that uses **Gemini AI** to classify,
enrich, and file notes into an **Obsidian vault**. Send messages — text,
images, PDFs — via Slack and they are automatically categorised with full
YAML frontmatter into the correct vault folder.

Source          | <https://github.com/gilesknap/2ndBrain>
:---:           | :---:
Documentation   | <https://gilesknap.github.io/2ndBrain>
Releases        | <https://github.com/gilesknap/2ndBrain/releases>

## Features

- **AI-powered filing** — Gemini 2.5 Flash classifies content into
  Projects, Actions, Media, Reference, Memories, or Inbox with structured frontmatter
- **Pluggable agent architecture** — Router dispatches messages to
  specialist agents; new capabilities are a single subclass away
- **Vault queries** — Ask questions about your filed content
  ("What actions are due this week?", "List my recent media saves")
- **Vault editing** — Modify existing notes in bulk
  ("set priority to urgent on all epics-containers actions")
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
  → FilingAgent | VaultQueryAgent | VaultEditAgent | MemoryAgent | Direct answer
  → reply posted in Slack thread
```

See [Architecture](explanations/architecture.md) for the full design.

See [Prompts](reference/prompts.md) for the Gemini system instructions.

See [Security](explanations/security.md) for the threat model and hardening guide.

## Tech Stack

| Component     | Technology                                      |
|---------------|-------------------------------------------------|
| Runtime       | Python 3.12, managed with `uv`                  |
| AI            | Gemini 2.5 Flash via `google-genai` SDK         |
| Messaging     | Slack Bolt (Socket Mode)                        |
| Vault         | Obsidian, synced via rclone to Google Drive      |
| Services      | systemd user units (no root required)           |
| Secrets       | `systemd-creds` (≥ 256) or GPG + `pass` fallback |

## Getting Started

See the [Quick Start](tutorials/quickstart.md) tutorial and the
full [documentation](https://gilesknap.github.io/2ndBrain).

## License

See [LICENSE](https://github.com/gilesknap/2ndBrain/blob/main/LICENSE).

<!-- README only content. Anything below this line won't be included in index.md -->

See https://gilesknap.github.io/2ndBrain for more detailed documentation.
