# Installation

## Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) package manager
- A configured Slack app (see [Slack App Setup](../../docs/setup_slack_app.md))
- rclone configured for Google Drive (see [rclone Setup](../../docs/setup_rclone.md))

## Clone and install

```
$ git clone https://github.com/gilesknap/2ndBrain.git
$ cd 2ndBrain
$ uv sync
```

## Verify the installation

```
$ uv run brain --version
```

## Deployment

Use the included installer for either server or workstation mode:

```
$ ./install.sh --server       # Headless: rclone FUSE mount + Slack listener
$ ./install.sh --workstation  # Desktop:  rclone bisync for Obsidian
```

See the [README](https://github.com/gilesknap/2ndBrain#readme) for full
deployment details.
