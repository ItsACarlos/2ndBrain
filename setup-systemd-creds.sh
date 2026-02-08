#!/usr/bin/env bash
# setup-systemd-creds.sh — Encrypt the rclone config password with systemd-creds.
#
# Requirements: systemd ≥ 256 (for `systemd-creds encrypt --user`).
# Run this AFTER install.sh has installed the service units.
#
# The encrypted credential is stored at ~/.config/2ndbrain/ — no
# plaintext file is kept on disk. At service start, rclone's
# --password-command calls `systemd-creds decrypt --user` to retrieve
# the password.
#
# Safe to re-run — skips encryption if the credential file already exists.
#
# Usage:  ./setup-systemd-creds.sh
set -euo pipefail

CACHE_DIR="${HOME}/.config/2ndbrain"
CRED_FILE="${CACHE_DIR}/rclone-config-pass.cred"
CRED_NAME="rclone-config-pass"

# -----------------------------------------------------------------------
# 1. Check prerequisites
# -----------------------------------------------------------------------
if ! command -v systemd-creds &>/dev/null; then
    echo "ERROR: systemd-creds not found."
    echo "  This script requires systemd ≥ 256."
    echo "  Use ./setup-gpg-pass.sh instead on older systems."
    exit 1
fi

# Quick version check — extract major version number
SYSTEMD_VER=$(systemctl --version 2>/dev/null | head -1 | awk '{print $2}')
if [[ "${SYSTEMD_VER}" -lt 256 ]] 2>/dev/null; then
    echo "ERROR: systemd ${SYSTEMD_VER} found, but ≥ 256 is required"
    echo "  for --user encrypted credentials."
    echo "  Use ./setup-gpg-pass.sh instead."
    exit 1
fi

# -----------------------------------------------------------------------
# 2. Encrypt the rclone config password
# -----------------------------------------------------------------------
if [[ -f "${CRED_FILE}" ]]; then
    echo "→ Encrypted credential found at ${CRED_FILE}."
    echo "  To re-encrypt, delete it and re-run this script."
else
    echo "=== systemd-creds Credential Setup ==="
    echo
    echo "Enter the password that rclone uses to decrypt rclone.conf."
    echo "It will be encrypted so only this machine can decrypt it."
    echo
    read -rsp "rclone config password: " RCLONE_PASS
    echo

    mkdir -p "${CACHE_DIR}"
    echo -n "${RCLONE_PASS}" \
        | systemd-creds encrypt --user --name="${CRED_NAME}" - "${CRED_FILE}"
    unset RCLONE_PASS

    chmod 600 "${CRED_FILE}"
    echo "→ Credential encrypted and saved."
fi

# -----------------------------------------------------------------------
# 3. Verify decryption works
# -----------------------------------------------------------------------
echo "→ Verifying decryption..."
if systemd-creds decrypt --user --name="${CRED_NAME}" "${CRED_FILE}" - >/dev/null 2>&1; then
    echo "  ✓ Decryption OK."
else
    echo "  ✗ Decryption failed. Try deleting ${CRED_FILE} and re-running."
    exit 1
fi

# -----------------------------------------------------------------------
# 4. Enable and start services
# -----------------------------------------------------------------------
echo "→ Reloading systemd..."
systemctl --user daemon-reload

echo "→ Starting services..."
for unit in rclone-2ndbrain.service brain.service rclone-2ndbrain-bisync.timer; do
    unit_path="${HOME}/.config/systemd/user/${unit}"
    [[ -f "${unit_path}" ]] || continue
    systemctl --user enable "${unit}" 2>/dev/null || true
    systemctl --user restart "${unit}" 2>/dev/null || true
    echo "  ✓ ${unit}"
done

echo
echo "✓ Done. Services are running (no passphrase prompt needed)."
echo "  Check status with: systemctl --user list-units 'rclone-*' 'brain.*'"
