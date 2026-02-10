# 2ndBrain Collector Agent Instructions

## Terminal Tool Usage

When using the `run_in_terminal` tool:

- The tool result may show only a minimal acknowledgment (e.g., `#` with a timestamp) rather than the actual command output
- **ALWAYS** use `terminal_last_command` tool afterward to retrieve the actual output if the `run_in_terminal` result appears empty or truncated
- Check the exit code in the context to determine if the command succeeded before assuming failure

**CRITICAL: Avoid repeating commands**

- The `<context>` block at the start of each user message contains terminal state including:
  - `Last Command`: The command that was run
  - `Exit Code`: Whether it succeeded (0) or failed
- **BEFORE** running a command, check if the context already shows it ran successfully
- **NEVER** re-run a command that the context shows already completed with exit code 0
- If you need the output and the context doesn't show it, use `terminal_last_command` once - do not re-run the command

**Common mistake to avoid:**
- ❌ Run command → Get minimal output → Try to run same command again
- ✅ Run command → Get minimal output → Check context for exit code → Use `terminal_last_command` to get full output
- The `run_in_terminal` tool often returns minimal acknowledgment, but the command still executed successfully
- Always check the context in the next turn - if Exit Code: 0, the command succeeded; just get the output with `terminal_last_command`

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
- **Secrets:** `systemd-creds` (systemd ≥ 256) or GPG + `pass` (fallback)
  for rclone config encryption

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

## Code Organization
- **`src/brain/`** — Main Python package
  - `app.py` — Entrypoint, wires components together
  - `listener.py` — Slack event handlers
  - `vault.py` — All vault I/O and template syncing
  - `processor.py` — Gemini JSON extraction, token injection
  - `agents/` — Pluggable agent architecture (see below)
  - `vault_templates/` — `.base` files and Obsidian configs
- **`service-units/`** — systemd service definitions
- **`scripts/`** — Installation, credential setup, utilities
- **`docs/`** — Sphinx documentation (MyST Markdown)

See `vault.py` for vault categories. See `app.py` for agent registration.

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
  → intent dispatches to registered agent (see app.py for registry)
  ← reply posted in-thread (if message was threaded)
```

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

## Gemini Integration Details
- **Prompt:** Lives in `src/brain/prompt.md` — edit this to change
  classification rules, frontmatter schema, or output format.
- **Output format:** Gemini returns raw JSON `{"folder", "slug", "content"}`
  for notes, or plain text for direct answers to questions.
- **JSON extraction:** `processor.py` uses two strategies — fenced code
  block detection first, then balanced-brace matching as fallback.
- **Token injection:** `_inject_tokens()` parses YAML frontmatter properly
  and inserts `tokens_used` into the existing block.

## Obsidian Configuration

### Metadata Menu Preset Fields
The vault includes a **Metadata Menu** plugin configuration at
`.obsidian/plugins/metadata-menu/data.json` in the templates directory.
This file defines preset fields with dropdown options for properties:

- **`status`**: todo, in_progress, done, completed, cancelled, to_consume,
  consuming, consumed
- **`priority`**: 1 - Urgent, 2 - High, 3 - Medium, 4 - Low
- **`media_type`**: book, film, tv, podcast, article, video, music

These fields provide dropdown menus when editing frontmatter properties in
Obsidian, improving data consistency. The configuration is synced to new
vaults automatically via the template system.

### .base File Conventions
### .base File Conventions
The vault uses **Obsidian Bases** (native `.base` files) for dashboards.
Templates live in `src/brain/vault_templates/` and are synced to the vault
by `vault.py._ensure_base_files()` via timestamp comparison.

**CRITICAL filter syntax:** All `filters:` blocks MUST be an object with
exactly one key: `and:`, `or:`, or `not:`. A plain YAML list will cause
an Obsidian parse error. Even single conditions must be wrapped:

```yaml
filters:
  and:
    - 'file.ext == "md"'
```

When adding new categories or frontmatter fields, update both
`src/brain/prompt.md` (so Gemini produces them) and the corresponding
`_*_base()` method in `vault.py` (so the dashboard displays them).

## Service Management

**Server mode:** `brain.service` listens for Slack messages and writes to an
rclone FUSE mount. `Requires=rclone-2ndbrain.service` ensures mount is ready.

**Workstation mode:** `rclone-2ndbrain-bisync.timer` syncs every 30s.
Bisync creates real local files (inotify events for Obsidian), unlike rclone
mount. First run auto-executes `--resync` to establish baseline from Google Drive.

**Stale mount recovery:** `fusermount -uz ~/Documents/2ndBrain` then restart.

### Installation
1. Configure rclone remote (see [setup_rclone.md](docs/how-to/setup_rclone.md))
2. Run `./scripts/install.sh --server` or `./scripts/install.sh --workstation`
3. Set up credentials: `./scripts/setup-systemd-creds.sh` (systemd ≥256) or
   `./scripts/setup-gpg-pass.sh` (older systemd + GPG)
4. **Server only:** Create Slack app (see [setup_slack_app.md](docs/how-to/setup_slack_app.md)), fill `.env`
5. **Server only:** `sudo loginctl enable-linger $USER` for auto-start on boot

## Common Workflows
- **After any code change:** Always run
  `uv run ruff check --fix; uv run pyright tests src` to lint and
  type-check before committing.
- **Update code:** After modifying any `src/brain/*.py` file, run
  `systemctl --user restart brain.service` or use `./scripts/restart.sh`.
- **Monitor logs:** `journalctl --user -u brain.service -f`
- **Check rclone (server):** Ensure the mount is active at
  `~/Documents/2ndBrain/` before attempting file operations.
- **Check bisync (workstation):** `systemctl --user list-timers` to
  verify the timer is active.
- **Update a .base file:** Edit the template in `src/brain/vault_templates/`,
  restart the service — the newer timestamp triggers an automatic copy.
- **Add a new vault category:** Add to `CATEGORIES` dict in `vault.py`,
  add classification rules in `prompt.md`, create a new template file in
  `vault_templates/`.
- **Change the daily briefing time:** Set `BRIEFING_TIME=08:00` in `.env`.
  Set `BRIEFING_CHANNEL` to a Slack channel ID to enable it.
- **Install deps:** `uv sync` (not pip install)

## Documentation
This project uses **MyST Markdown** (MyST = Markedly Structured Text) for
documentation, built with Sphinx. MyST extends CommonMark Markdown with
powerful features for technical documentation.

### Adding New Documentation
- **ALWAYS** add new documentation files to the appropriate index:
  - Explanations → `docs/explanations.md` toctree
  - How-to guides → `docs/how-to.md` toctree
  - Reference → `docs/reference.md` toctree
  - Tutorials → `docs/tutorials.md` toctree

### Cross-References and Anchors
MyST provides explicit anchor targets for cross-referencing specific sections:

**Creating an anchor:**
```markdown
(my-anchor-name)=
## Section Title
```

The anchor must be on its own line immediately before the heading, using
the syntax `(anchor-name)=`.

**Linking to an anchor:**
Note that no path to the file is required in the links as the anchors are global.
```markdown
See the [section title](#my-anchor-name) for details.
```


**Key points:**
- Anchor names should be lowercase-with-hyphens
- Anchors work across files (with no paths)
- Running `tox -e docs` will report missing cross-references

### Building Documentation

```bash
# Build HTML docs
tox -e docs

# Check for warnings (missing references, etc.)
tox -e docs 2>&1 | grep WARNING
```

## Boundaries
- Never hardcode API keys; always use `os.environ` or `.env`.
- Do not use `sudo` unless explicitly requested for system package installs.
- Do not use the deprecated `google-generativeai` package; use `google-genai`.
- Vault path is `~/Documents/2ndBrain/2ndBrainVault/` — not the mount root.
