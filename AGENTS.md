# 2ndBrain Collector Agent Instructions

## Purpose
A Slack-driven quick-capture system that uses Gemini AI to classify, enrich,
and file notes into an Obsidian vault. The user sends messages (text,
images, PDFs) via Slack; the system auto-categorises them and writes
structured Markdown with YAML frontmatter into the correct vault folder.

## Tech Stack & Environment
- **Runtime:** Python 3.12, managed with `uv`, on Ubuntu 24.04
- **Framework:** Slack Bolt (Socket Mode)
- **AI SDK:** `google-genai` (new Client-based SDK — NOT the deprecated
  `google-generativeai` package)
- **AI Model:** `gemini-2.5-flash` — do not downgrade
- **HTTP:** `requests` for Slack file downloads
- **Scheduling:** `schedule` for daily briefing timer
- **Vault storage:** rclone to Google Drive at `~/Documents/2ndBrain/`
  (vault root: `~/Documents/2ndBrain/2ndBrainVault/`)
- **Service manager:** systemd user units (no sudo required)
- **Secrets:** GPG + `pass` for rclone config encryption

## Deployment Modes
The system supports two deployment modes via `install.sh`:

| Mode          | Sync method   | Use case                                |
|---------------|---------------|-----------------------------------------|
| **Server**    | rclone mount  | Headless machine running the Slack listener |
| **Workstation** | rclone bisync | Desktop with Obsidian (no listener)     |

- **Server:** FUSE mount provides instant writes. The brain.service
  listens for Slack messages and writes notes directly to the mount.
- **Workstation:** bisync every 30s creates real local files, giving
  Obsidian proper inotify events. rclone mount does NOT generate
  inotify events — this is why bisync is required for Obsidian.

## Project Structure
```
src/brain/
├── __init__.py      # Package marker
├── __main__.py      # python -m src.brain.app entrypoint
├── app.py           # Main entrypoint — env validation, component wiring
├── listener.py      # Slack event handlers, attachment download/processing
├── processor.py     # Gemini utility functions (JSON extraction, token injection)
├── vault.py         # All Obsidian vault I/O, folder management, .base files
├── briefing.py      # Daily morning summary posted to Slack
├── prompt.md        # System prompt for the filing agent (Gemini)
└── agents/          # Pluggable agent architecture
    ├── __init__.py      # Package exports: BaseAgent, AgentResult, MessageContext, Router
    ├── base.py          # BaseAgent ABC, AgentResult & MessageContext dataclasses
    ├── router.py        # Intent classifier — dispatches to registered agents
    ├── router_prompt.md # System prompt for the router's classification call
    ├── filing.py        # FilingAgent — classifies & archives content to vault
    └── vault_query.py   # VaultQueryAgent — searches vault & answers questions
service-units/
├── brain.service                   # Slack listener (server, template with @@PROJECT_DIR@@)
├── rclone-2ndbrain.service         # rclone FUSE mount (server)
├── rclone-2ndbrain-bisync.service  # rclone bisync oneshot (workstation)
└── rclone-2ndbrain-bisync.timer    # 30s bisync timer (workstation)
docs/
├── setup_rclone.md   # rclone + GPG/pass setup guide
└── setup_slack_app.md # Slack app creation + OAuth scopes guide
install.sh           # Two-mode installer (--server / --workstation)
setup-gpg-pass.sh    # GPG key, pass, keygrip preset automation
restart.sh           # Convenience script for systemd reload/restart/logs
pyproject.toml       # uv/pip metadata and dependencies
.env                 # Runtime secrets (not committed)
.env.template        # Template for .env
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

## Pluggable Agent Architecture

Messages flow through a two-stage pipeline:

1. **Router** (`agents/router.py`): A lightweight Gemini call that
   classifies the user's intent into one of the registered agent names,
   or `"question"` for simple direct answers. The router prompt is
   generated dynamically from agent descriptions, so adding an agent
   automatically updates the classification.

2. **Agent** (`agents/<name>.py`): The matched agent receives a
   `MessageContext` (raw text, attachments, vault reference, thread
   history, and extra data from the router) and returns an `AgentResult`
   (Slack reply text and/or a filed path).

### Conversation Context (Thread Follow-ups)

When a message arrives in a Slack thread, `listener.py` fetches up to
10 prior messages via `conversations.replies` and passes them as
`thread_history` on `MessageContext`. Both the router and all agents
include this history in their prompts, enabling natural follow-up
questions like:

- "What YouTube videos did I file this week?" → answer
- (reply in thread) "What about podcasts?" → understands context

### Message Flow
```
Slack message → listener.py (attachment prep + thread history fetch)
  → Router._classify()  — lightweight Gemini call → intent JSON
  → intent == "question"  → direct answer (no second call)
  → intent == "file"      → FilingAgent.handle()  → save to vault
  → intent == "vault_query" → VaultQueryAgent.handle() → search + answer
  → intent == <new agent> → YourAgent.handle()
  ← reply posted in-thread (if message was threaded)
```

### Registered Agents

| Intent        | Agent            | Purpose                                     |
|---------------|------------------|---------------------------------------------|
| `file`        | `FilingAgent`    | Classify and archive content into the vault |
| `vault_query` | `VaultQueryAgent`| Search vault notes and answer questions     |

### Adding a New Agent

1. **Create** `src/brain/agents/my_agent.py`:

   ```python
   from .base import AgentResult, BaseAgent, MessageContext

   class MyAgent(BaseAgent):
       name = "my_intent"
       description = "One-line description used in the router prompt."

       def handle(self, context: MessageContext) -> AgentResult:
           # context.raw_text      — user's message
           # context.vault         — Vault instance for I/O
           # context.router_data   — dict from the router (search_terms, etc.)
           return AgentResult(response_text="Done!")
   ```

2. **Register** in `app.py`:

   ```python
   from .agents.my_agent import MyAgent
   my_agent = MyAgent()
   router = Router(
       agents={
           filing_agent.name: filing_agent,
           vault_query_agent.name: vault_query_agent,
           my_agent.name: my_agent,
       },
   )
   ```

3. **Optionally** add extra `router_data` fields by extending the
   router prompt in `agents/router_prompt.md` with a new intent block.

4. **Update this file** with the new intent in the Registered Agents
   table above.

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
filters:                          # MUST use and:/or:/not: — NEVER a plain list
  and:
    - 'file.inFolder("Actions")'
    - 'file.ext == "md"'

properties:                       # Columns from YAML frontmatter
  title:
    displayName: Title
  status:
    displayName: Status

views:                            # One or more table/board views
  - type: table
    name: "Open Actions"
    filters:                      # Per-view filters also require and:/or:/not:
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
**CRITICAL:** All `filters:` blocks — both top-level and per-view — MUST be
an object with exactly one key: `and:`, `or:`, or `not:`. A plain YAML list
under `filters:` will cause an Obsidian parse error:
> "filters" may only have one of an "and", "or", or "not" keys.

Even a single filter condition must be wrapped:
```yaml
filters:
  and:
    - 'file.ext == "md"'
```

Available filter expressions:
- `file.inFolder("FolderName")` — match files in a specific vault folder
- `file.ext == "md"` — file extension check
- `file.mtime > now() - "7 days"` — recency filter
- `status != "done"` — frontmatter property comparison

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

## Service Architecture

### brain.service (server only)
- **Template:** `service-units/brain.service` uses `@@PROJECT_DIR@@`
  placeholders, substituted by `install.sh` via `sed` at install time.
- **Mount dependency:** `Requires=rclone-2ndbrain.service` — won't start
  if rclone fails. `ExecStartPre` polls for up to 30s waiting for the
  mount directory to appear.
- **Env loading:** `.env` is loaded both by systemd (`EnvironmentFile`)
  and Python (`load_dotenv()`).
- **Invocation:** `.venv/bin/python -m src.brain.app` (also available as
  `brain` console script via `pyproject.toml [project.scripts]`).

### rclone-2ndbrain.service (server only)
- FUSE mount with `--vfs-cache-mode full`, `--poll-interval 15s`,
  `--dir-cache-time 5s`.
- Uses `--password-command "pass rclone/gdrive-vault"` — requires
  GPG/pass infrastructure (see `setup-gpg-pass.sh`).
- `ExecStop` does a clean `fusermount -u`.

### rclone-2ndbrain-bisync.service + .timer (workstation only)
- `Type=oneshot` — runs bisync and exits (fired by timer every 30s).
- `--resilient --recover --conflict-resolve newer` for robustness.
- First run needs `--resync` to establish baseline (handled by `install.sh`).

### Stale mount recovery
If rclone crashes and leaves a dead FUSE mount ("Transport endpoint not
connected"), use: `fusermount -uz ~/Documents/2ndBrain` then restart
the service.

## Installation
1. **GPG + pass:** Run `./setup-gpg-pass.sh` first on any new machine.
   This creates the GPG key, password store, and keygrip preset needed
   for rclone to decrypt its config non-interactively.
2. **rclone remote:** Configure via `rclone config` — see
   `docs/setup_rclone.md`.
3. **Install services:** `./install.sh --server` or `./install.sh --workstation`.
4. **Slack app (server only):** Create the app and get tokens — see
   `docs/setup_slack_app.md`. Fill in `.env` from `.env.template`.
5. **Enable linger (server only):** `sudo loginctl enable-linger $USER`
   so services run on boot without a login session.

## Common Workflows
- **Update code:** After modifying any `src/brain/*.py` file, run
  `systemctl --user restart brain.service` or use `./restart.sh`.
- **Monitor logs:** `journalctl --user -u brain.service -f`
- **Check rclone (server):** Ensure the mount is active at
  `~/Documents/2ndBrain/` before attempting file operations.
- **Check bisync (workstation):** `systemctl --user list-timers` to
  verify the timer is active.
- **Regenerate a .base file:** Delete it from the vault, restart the service.
- **Add a new vault category:** Add to `CATEGORIES` dict in `vault.py`,
  add classification rules in `prompt.md`, add a `_*_base()` method,
  register it in `_ensure_base_files()`.
- **Change the daily briefing time:** Set `BRIEFING_TIME=08:00` in `.env`.
  Set `BRIEFING_CHANNEL` to a Slack channel ID to enable it.
- **Install deps:** `uv sync` (not pip install)
- **Migrate to new machine:** Copy `~/.gnupg/`, `~/.password-store/`,
  and `~/.config/rclone/rclone.conf` from the old machine, then run
  `./setup-gpg-pass.sh` and `./install.sh`. See `docs/setup_rclone.md`
  section 6 for details.

## Environment Variables (.env)
| Variable          | Required | Description                                |
|-------------------|----------|--------------------------------------------|
| SLACK_BOT_TOKEN   | Yes      | Slack bot token (xoxb-…)                   |
| SLACK_APP_TOKEN   | Yes      | Slack app-level token (xapp-…)             |
| GEMINI_API_KEY    | Yes      | Google Gemini API key                      |
| BRIEFING_CHANNEL  | No       | Slack channel ID for daily briefing        |
| BRIEFING_TIME     | No       | Time for daily briefing (default: "07:00") |

## Slack Bot Configuration
The Slack app requires Socket Mode enabled with an app-level token
(scope: `connections:write`) and the `message.im` event subscription.

### Required Bot Token Scopes
| Scope                | Purpose                                        |
|----------------------|------------------------------------------------|
| `app_mentions:read`  | View messages that mention @2ndBrain           |
| `channels:history`   | View messages in public channels app is in     |
| `chat:write`         | Send messages as @2ndBrain                     |
| `files:read`         | Download file attachments from conversations   |
| `groups:history`     | View messages in private channels app is in    |
| `im:history`         | View direct messages with the bot              |
| `incoming-webhook`   | Post messages to specific channels (briefings) |

After adding or changing scopes, you must **reinstall the app** to the
workspace for changes to take effect. See `docs/setup_slack_app.md`.

## Boundaries
- Never hardcode API keys; always use `os.environ` or `.env`.
- Do not use `sudo` unless explicitly requested for system package installs.
- Do not use the deprecated `google-generativeai` package; use `google-genai`.
- Vault path is `~/Documents/2ndBrain/2ndBrainVault/` — not the mount root.
