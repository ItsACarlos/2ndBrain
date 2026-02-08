# Quick Start

Get 2ndBrain running from scratch in five steps. This guide covers the
minimal setup — see the linked how-to guides for full details on each
component.

## Server and workstation

The system has two roles that can run on separate machines:

- **Server** — runs the Slack listener and writes notes into the vault
  via an rclone FUSE mount to Google Drive. You need exactly **one** server.
- **Workstation** — syncs the vault to a local folder with rclone bisync
  so Obsidian can read and edit the notes directly. You can set up
  **multiple** workstations (laptop, desktop, etc.) — they all sync
  through Google Drive.

The server needs to be always-on so it can receive Slack messages at any
time. Good options include:

- A spare machine on your LAN (a Raspberry Pi, NUC, or home server)
- A cheap VPS (any provider with a Linux VM will work)
- The same desktop you use for Obsidian — you can run both roles on one
  machine by installing with `--server`

Workstations only need to run when you want to use Obsidian, so a laptop
that sleeps is fine.

## Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) package manager
- A Linux machine (Ubuntu 24.04 recommended)
- A Google account (for Google Drive sync via rclone)
- A Slack workspace where you can create apps

## 1. Clone and install

```bash
git clone https://github.com/gilesknap/2ndBrain.git
cd 2ndBrain
uv sync
```

Verify the installation:

```bash
uv run brain --version
```

## 2. Configure rclone and create the Slack app

These two steps can be done in any order:

- **Slack app** — Create a Socket Mode app with the required OAuth scopes.
  See [Slack App Setup](../how-to/setup_slack_app.md) for the full
  walkthrough.

- **rclone** — This can be done for you by the install script (see below).
  See [rclone Setup](../how-to/setup_rclone.md) for detailed instructions.

  ```bash
  rclone config
  ```

## 3. Configure environment variables

```bash
cp .env.template .env
```

Edit `.env` and fill in the three required values:

| Variable          | Source                         |
|-------------------|--------------------------------|
| `SLACK_BOT_TOKEN` | Slack OAuth — starts with `xoxb-` |
| `SLACK_APP_TOKEN` | Slack Socket Mode — starts with `xapp-` |
| `GEMINI_API_KEY`  | [Google AI Studio](https://aistudio.google.com/apikey) |

Optional settings:

| Variable           | Default  | Description                       |
|--------------------|----------|-----------------------------------|
| `BRIEFING_CHANNEL` | *(none)* | Slack channel ID for daily briefing |
| `BRIEFING_TIME`    | `07:00`  | Time for the daily briefing       |

## 4. Deploy

Choose the deployment mode that matches your machine:

```bash
# Headless server: rclone FUSE mount + Slack listener
./install.sh --server

# Desktop with Obsidian: rclone bisync (no listener)
./install.sh --workstation
```

For the server mode, enable linger so the service starts on boot:

```bash
sudo loginctl enable-linger $USER
```

## 5. Set up credential encryption

The rclone configuration is encrypted at rest and needs a password at
runtime. The service units must be installed (step 4) before this step.
Two backends are supported — check which one your system can use:

```bash
systemctl --version | head -1
```

### systemd ≥ 256 → `systemd-creds`

If the version is **256 or higher**, use the hardware-backed credential
encryption:

```bash
./setup-systemd-creds.sh
```

This encrypts the rclone password to the host's TPM/credential key and
injects it into the installed service units. Services auto-start on boot
with no manual unlock needed.

### systemd < 256 → GPG + `pass`

On older systemd (Ubuntu 24.04 = 255, RHEL 9 ≈ 252), fall back to GPG:

```bash
./setup-gpg-pass.sh
```

This creates a GPG key, initialises the `pass` password store, and
stores the rclone config password. **Services are not auto-enabled** in
this mode — after each reboot you must unlock GPG and start them
manually with:

```bash
./start-brain.sh
```

This prompts for your GPG passphrase, caches it in `gpg-agent`, and
starts the appropriate services for your deployment mode.

See [rclone Setup](../how-to/setup_rclone.md) for manual steps and
troubleshooting.

## Verify it's running

### Server

Check that both the rclone mount and the brain listener are active:

```bash
systemctl --user status rclone-2ndbrain.service
systemctl --user status brain.service
journalctl --user -u brain.service -f
```

You should see:

```
⚡️ 2ndBrain Collector starting up...
⚡️ Bolt app is running!
```

Send a DM to your bot in Slack — it should respond and file the note
into the vault.

### Workstation

Check that the bisync timer is firing:

```bash
systemctl --user list-timers rclone-2ndbrain-bisync.timer
systemctl --user status rclone-2ndbrain-bisync.service
```

The timer should show a `LAST` trigger within the last 30 seconds. Open
Obsidian and confirm the vault folder appears at
`~/Documents/2ndBrain/2ndBrainVault/`.

## Next steps

- Read the [Architecture](../explanations/architecture.md) to understand
  the agent pipeline
- Teach the bot rules with directives: send "remember: always tag
  cooking recipes with #cooking"
- Set up the daily briefing by configuring `BRIEFING_CHANNEL` in `.env`
  (see [Slack App Setup](../how-to/setup_slack_app.md) for channel ID instructions)
