# 2ndBrain Collector Agent Instructions

## Tech Stack & Environment
- **Runtime:** Python 3.x on Ubuntu 24.04 (Headless)
- **Framework:** Slack Bolt (Socket Mode)
- **AI Model:** Google Gemini 2.5 Flash (`gemini-2.5-flash`)
- **Storage:** rclone mount at `~/Documents/2ndBrain/`

## Project Structure
- `brain.py`: Main listener and processor.
- `brain.service`: Systemd user service managing the lifecycle.
- `.env`: Contains SLACK_BOT_TOKEN, SLACK_APP_TOKEN, GEMINI_API_KEY.

## Architectural Rules
1. **Model Version:** Always use `gemini-2.5-flash` for the intake pipeline. Do not downgrade to 1.5.
2. **File Handling:** Notes must be saved to the `Inbox/` directory with the slugified naming convention `capture-YYYYMMDD-HHmm.md`.
3. **Metadata:** Every note must include YAML frontmatter with `date`, `source: slack`, `tags`, and `tokens_used`.
4. **Permissions:** All commands should be run in the context of the current user. Use `systemctl --user` for service management.

## Common Workflows
- **Update Logic:** When modifying `brain.py`, always suggest a `systemctl --user restart brain.service` afterwards.
- **Debugging:** Use `journalctl --user -u brain.service -f` to monitor real-time message processing.
- **Rclone:** Ensure the mount is active at `~/Documents/2ndBrain/` before attempting file operations.

## Boundaries
- Never hardcode API keys; always reference `os.environ` or the `.env` file.
- Do not attempt to use `sudo` unless explicitly requested for system-level package installs.
