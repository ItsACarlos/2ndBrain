# 2ndBrain Collector Agent Instructions

## Purpose
A Slack-driven quick-capture system that uses Gemini AI to classify, enrich,
and file notes into an Obsidian vault. The user sends messages (text,
images, PDFs) via Slack; the system auto-categorises them and writes
structured Markdown with YAML frontmatter into the correct vault folder.

## Tech Stack & Environment
- **Runtime:** Python 3.12, managed with `uv`, on Ubuntu 24.04 (headless)
- **Framework:** Slack Bolt (Socket Mode)
- **AI SDK:** `google-genai` (new Client-based SDK — NOT the deprecated
  `google-generativeai` package)
- **AI Model:** `gemini-2.5-flash` — do not downgrade
- **Vault storage:** rclone mount at `~/Documents/2ndBrain/`
  (vault root: `~/Documents/2ndBrain/2ndBrainVault/`)
- **Service manager:** systemd user units (no sudo required)

## Project Structure
```
src/brain/
├── __init__.py      # Package marker
├── __main__.py      # python -m src.brain.app entrypoint
├── app.py           # Main entrypoint — env validation, component wiring
├── listener.py      # Slack event handlers, attachment download/processing
├── processor.py     # Gemini prompt building, API calls, JSON extraction
├── vault.py         # All Obsidian vault I/O, folder management, .base files
├── briefing.py      # Daily morning summary posted to Slack
└── prompt.md        # System prompt sent to Gemini
service-units/
└── brain.service    # systemd user service unit
pyproject.toml       # uv/pip metadata and dependencies
.env                 # SLACK_BOT_TOKEN, SLACK_APP_TOKEN, GEMINI_API_KEY
                     #   (optional: BRIEFING_CHANNEL, BRIEFING_TIME)
restart.sh           # Convenience script for systemd reload/restart/logs
```

## Vault Categories
Notes are filed into exactly one of these folders inside the vault root:

| Folder        | Purpose                                              |
|---------------|------------------------------------------------------|
| Projects      | Project docs, snippets, whiteboard photos, ideas     |
| Actions       | Tasks/to-dos with due dates and status tracking      |
| Media         | Books, films, TV, podcasts, articles, videos         |
| Reference     | How-tos, explanations, technical notes               |
| Attachments   | Binary files (images, PDFs) linked from other notes  |
| Inbox         | Fallback for truly ambiguous captures                |

## Architectural Rules
1. **Model version:** Always use `gemini-2.5-flash`. Do not downgrade.
2. **SDK:** Use `google.genai.Client()` (auto-reads `GEMINI_API_KEY` from
   env). Binary parts use `types.Part.from_bytes(data=..., mime_type=...)`.
3. **File naming:** Descriptive hyphenated slugs (e.g. `fix-garden-fence.md`).
   Dates go in YAML frontmatter, NOT in filenames.
4. **Frontmatter:** Every note requires at minimum: `title`, `date`,
   `source: slack`, `category`, `tags`, `tokens_used`. Category-specific
   fields are defined in `src/brain/prompt.md`.
5. **Attachments:** Binary files save to `Attachments/` with timestamped
   names. Notes reference them with `![[filename]]` wiki-links.
   Small text files (<50 KB) are inlined in the Gemini prompt instead.
6. **Project inference:** Gemini checks existing project names (passed in
   the prompt context) and infers project association. Users can force
   a project with `#projectname` in their message.
7. **Permissions:** All commands run as the current user.
   Use `systemctl --user` for service management.

## Gemini Integration Details
- **Prompt:** Lives in `src/brain/prompt.md` — edit this to change
  classification rules, frontmatter schema, or output format.
- **Output format:** Gemini returns raw JSON `{"folder", "slug", "content"}`
  for notes, or plain text for direct answers to questions.
- **JSON extraction:** `processor.py` uses two strategies — fenced code
  block detection first, then balanced-brace matching as fallback.
- **Token injection:** `_inject_tokens()` parses YAML frontmatter properly
  and inserts `tokens_used` into the existing block.

## Obsidian Bases
The vault uses **Obsidian Bases** (native `.base` files, NOT the Dataview
plugin) for dashboards and filtered views. These are generated on first
startup by `vault.py._ensure_base_files()` and never overwritten.

### .base File Format
Obsidian `.base` files are YAML documents with three top-level keys:

```yaml
filters:                          # Which files to include
  - 'file.inFolder("Actions")'   # folder filter
  - 'file.ext == "md"'           # only markdown

properties:                       # Columns from YAML frontmatter
  title:
    displayName: Title
  status:
    displayName: Status

views:                            # One or more table/board views
  - type: table
    name: "Open Actions"
    filters:                      # Per-view additional filters
      and:
        - 'status != "done"'
        - 'status != "completed"'
    order:                        # Column display order
      - note.due_date
      - note.priority
      - note.title
    groupBy:                      # Optional grouping
      property: note.media_type
      direction: ASC
```

### Filter Syntax
- `file.inFolder("FolderName")` — match files in a specific vault folder
- `file.ext == "md"` — file extension check
- `file.mtime > now() - "7 days"` — recency filter
- `status != "done"` — frontmatter property comparison
- Combine with `and:` / `or:` blocks for compound filters

### Property References
- `note.<property>` — references a YAML frontmatter key
- `file.mtime` — file modification time
- `file.name` — filename

### Generated .base Files
| File                        | Purpose                                     |
|-----------------------------|---------------------------------------------|
| `Projects/Projects.base`   | All project notes sorted by priority/date   |
| `Actions/Actions.base`     | "Open Actions" + "All Actions" views        |
| `Media/Media.base`         | Grouped by media_type, "To Consume" filter  |
| `Reference/Reference.base` | All reference notes by topic                |
| `Dashboard.base`           | Master: Today's Actions, Recent, All Open   |

When adding new categories or frontmatter fields, update both
`src/brain/prompt.md` (so Gemini produces them) and the corresponding
`_*_base()` method in `vault.py` (so the dashboard displays them).
Delete the old `.base` file from the vault to trigger regeneration.

## Common Workflows
- **Update code:** After modifying any `src/brain/*.py` file, run
  `systemctl --user restart brain.service` or use `./restart.sh`.
- **Monitor logs:** `journalctl --user -u brain.service -f`
- **Check rclone:** Ensure the mount is active at `~/Documents/2ndBrain/`
  before attempting file operations. The vault init checks this at startup
  and fails fast if the mount is missing.
- **Regenerate a .base file:** Delete it from the vault, restart the service.
- **Add a new vault category:** Add to `CATEGORIES` dict in `vault.py`,
  add classification rules in `prompt.md`, add a `_*_base()` method,
  register it in `_ensure_base_files()`.
- **Change the daily briefing time:** Set `BRIEFING_TIME=08:00` in `.env`.
  Set `BRIEFING_CHANNEL` to a Slack channel ID to enable it.
- **Install deps:** `uv sync` (not pip install)

## Environment Variables (.env)
| Variable          | Required | Description                                |
|-------------------|----------|--------------------------------------------|
| SLACK_BOT_TOKEN   | Yes      | Slack bot token (xoxb-…)                   |
| SLACK_APP_TOKEN   | Yes      | Slack app-level token (xapp-…)             |
| GEMINI_API_KEY    | Yes      | Google Gemini API key                      |
| BRIEFING_CHANNEL  | No       | Slack channel ID for daily briefing        |
| BRIEFING_TIME     | No       | Time for daily briefing (default: "07:00") |

## Slack Bot Scopes Required
The Slack app must have these OAuth scopes:
- `chat:write` — send messages
- `files:read` — download file attachments
- Socket Mode must be enabled (uses app-level token)

## Boundaries
- Never hardcode API keys; always use `os.environ` or `.env`.
- Do not use `sudo` unless explicitly requested for system package installs.
- Do not use the deprecated `google-generativeai` package; use `google-genai`.
- Vault path is `~/Documents/2ndBrain/2ndBrainVault/` — not the mount root.
