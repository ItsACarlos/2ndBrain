#!/usr/bin/env bash
# start-brain.sh — Unlock GPG and start 2ndBrain services.
#
# For machines using GPG + pass (no systemd-creds). Run this after each
# reboot to cache the GPG passphrase in gpg-agent, then start the
# systemd user services.
#
# On machines using systemd-creds, services start automatically —
# this script is not needed.
#
# Usage:  ./start-brain.sh
set -euo pipefail

# -----------------------------------------------------------------------
# 1. Unlock GPG by reading the rclone password from pass
# -----------------------------------------------------------------------
echo "Unlocking GPG agent..."
echo "  (Enter your GPG passphrase when prompted)"
echo

# This triggers gpg-agent to cache the passphrase
if ! pass show rclone/gdrive-vault &>/dev/null; then
    echo "ERROR: Could not decrypt rclone/gdrive-vault."
    echo "  Run ./setup-gpg-pass.sh if not yet configured."
    exit 1
fi

echo "→ GPG unlocked."

# -----------------------------------------------------------------------
# 2. Detect which services are installed and start them
# -----------------------------------------------------------------------
UNIT_DIR="${HOME}/.config/systemd/user"

if [[ -f "${UNIT_DIR}/rclone-2ndbrain.service" ]]; then
    # Server mode
    echo "→ Starting rclone mount..."
    systemctl --user restart rclone-2ndbrain.service
    sleep 2

    if [[ -f "${UNIT_DIR}/brain.service" ]]; then
        echo "→ Starting brain listener..."
        systemctl --user restart brain.service
        sleep 1
    fi

    echo
    echo "✓ Server services running. Logs:"
    echo "    journalctl --user -u brain.service -f"

elif [[ -f "${UNIT_DIR}/rclone-2ndbrain-bisync.timer" ]]; then
    # Workstation mode
    echo "→ Starting bisync timer..."
    systemctl --user start rclone-2ndbrain-bisync.timer

    echo
    echo "✓ Bisync timer running (every 30s)."

else
    echo "ERROR: No 2ndBrain service units found."
    echo "  Run ./install.sh first."
    exit 1
fi
