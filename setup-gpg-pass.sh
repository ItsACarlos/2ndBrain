#!/usr/bin/env bash
# setup-gpg-pass.sh — Set up GPG + pass to encrypt the rclone config password.
#
# Fallback for machines without systemd ≥ 256 (no systemd-creds --user).
# Services are NOT auto-started; use ./start-brain.sh to unlock GPG and
# start services after each reboot.
#
# This script:
#   1. Creates a GPG key if none exists
#   2. Initialises the pass password store
#   3. Stores the rclone config password in pass
#
# Safe to re-run — skips steps that are already done.
#
# Usage:  ./setup-gpg-pass.sh
set -euo pipefail

echo "=== GPG + pass Setup for 2ndBrain ==="
echo

# -----------------------------------------------------------------------
# 1. Check prerequisites
# -----------------------------------------------------------------------
for cmd in gpg pass; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is not installed."
        echo "  sudo apt install gnupg pass   # Debian/Ubuntu"
        echo "  sudo dnf install gnupg2 pass  # RHEL/Fedora"
        exit 1
    fi
done

# -----------------------------------------------------------------------
# 2. GPG key
# -----------------------------------------------------------------------
if gpg --list-secret-keys --keyid-format LONG 2>/dev/null | grep -q "^sec"; then
    GPG_EMAIL=$(gpg --list-secret-keys --keyid-format LONG 2>/dev/null \
        | grep "^uid" | head -1 | sed 's/.*<\(.*\)>/\1/')
    echo "→ GPG key found: ${GPG_EMAIL}"
else
    echo "→ No GPG key found. Creating one..."
    echo "  You will be prompted for your name, email, and a passphrase."
    echo "  REMEMBER THIS PASSPHRASE — you need it after each reboot."
    echo
    gpg --full-generate-key
    GPG_EMAIL=$(gpg --list-secret-keys --keyid-format LONG 2>/dev/null \
        | grep "^uid" | head -1 | sed 's/.*<\(.*\)>/\1/')
    echo "  GPG key created for: ${GPG_EMAIL}"
fi
echo

# -----------------------------------------------------------------------
# 3. Initialise pass
# -----------------------------------------------------------------------
if [[ -d "${HOME}/.password-store" ]]; then
    echo "→ pass store already initialised."
else
    echo "→ Initialising pass with GPG key: ${GPG_EMAIL}"
    pass init "${GPG_EMAIL}"
fi
echo

# -----------------------------------------------------------------------
# 4. Store rclone password in pass
# -----------------------------------------------------------------------
if pass show rclone/gdrive-vault &>/dev/null 2>&1; then
    echo "→ rclone/gdrive-vault already in pass store."
else
    echo "→ Store the rclone config encryption password."
    echo "  This is the password you used (or will use) when running 'rclone config'."
    pass insert rclone/gdrive-vault
fi
echo

# Verify
if pass show rclone/gdrive-vault &>/dev/null 2>&1; then
    echo "✓ pass can decrypt rclone/gdrive-vault — setup complete!"
else
    echo "⚠ Could not decrypt rclone/gdrive-vault."
    exit 1
fi

echo
echo "=== GPG + pass setup complete ==="
echo
echo "After running install.sh, use ./start-brain.sh to unlock GPG"
echo "and start the 2ndBrain services after each reboot."
