#!/usr/bin/env bash
# Refresh template files from the vault back into the project
# Useful for capturing manual edits made in Obsidian back to source

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

VAULT_ROOT="${HOME}/Documents/2ndBrain/2ndBrainVault"
TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/src/brain/vault_templates"

# Check if vault exists
if [[ ! -d "${VAULT_ROOT}" ]]; then
    echo -e "${RED}Error: Vault not found at ${VAULT_ROOT}${NC}"
    echo "Make sure rclone is mounted (server) or bisync has run (workstation)"
    exit 1
fi

echo -e "${GREEN}Refreshing templates from ${VAULT_ROOT}${NC}"
echo ""

pulled_count=0
skipped_count=0

# Find all files in vault_templates and sync from corresponding vault locations
while IFS= read -r -d '' template_file; do
    # Get the relative path from TEMPLATE_DIR
    rel_path="${template_file#${TEMPLATE_DIR}/}"

    # Use relative path as vault source path (files in _brain/ folder reflect vault's _brain/ folder)
    vault_path="${rel_path}"
    source_file="${VAULT_ROOT}/${vault_path}"

    # Skip if source doesn't exist in vault
    if [[ ! -f "${source_file}" ]]; then
        continue
    fi

    # Compare timestamps
    if [[ -f "${template_file}" ]]; then
        source_time=$(stat -c %Y "${source_file}" 2>/dev/null || stat -f %m "${source_file}" 2>/dev/null)
        dest_time=$(stat -c %Y "${template_file}" 2>/dev/null || stat -f %m "${template_file}" 2>/dev/null)

        if [[ ${source_time} -le ${dest_time} ]]; then
            echo -e "  Skip: ${rel_path} (project version is newer)"
            skipped_count=$((skipped_count + 1))
            continue
        fi
    fi

    # Copy with timestamp preservation
    mkdir -p "$(dirname "${template_file}")"
    cp -p "${source_file}" "${template_file}"
    echo -e "${GREEN}✓${NC} ${rel_path}"
    pulled_count=$((pulled_count + 1))
done < <(find "${TEMPLATE_DIR}" -type f -print0)

echo ""
echo -e "${GREEN}Summary: Pulled ${pulled_count}, Skipped ${skipped_count}${NC}"

if [[ ${pulled_count} -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}Note: Restart brain.service to deploy these changes back to the vault:${NC}"
    echo "  systemctl --user restart brain.service"
fi
