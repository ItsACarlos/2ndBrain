#!/usr/bin/env bash
# Pull .base files and Dashboard.md from the vault into the project
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

# Array of non-.base files to pull: vault_path:template_name
declare -a FILES=(
    "Dashboard.md:Dashboard.md"
    ".obsidian/plugins/metadata-menu/data.json:.obsidian/plugins/metadata-menu/data.json"
    ".obsidian/snippets/base-width.css:.obsidian/snippets/base-width.css"
)

echo -e "${GREEN}Pulling vault templates from ${VAULT_ROOT}${NC}"
echo "Target: ${TEMPLATE_DIR}"
echo ""

pulled_count=0
skipped_count=0
missing_count=0

# Pull all .base files from _brain/
echo "Pulling .base files from _brain/..."
if [[ -d "${VAULT_ROOT}/_brain" ]]; then
    while IFS= read -r -d '' source_file; do
        filename=$(basename "${source_file}")
        dest_file="${TEMPLATE_DIR}/${filename}"

        if [[ -f "${dest_file}" ]]; then
            source_time=$(stat -c %Y "${source_file}" 2>/dev/null || stat -f %m "${source_file}" 2>/dev/null)
            dest_time=$(stat -c %Y "${dest_file}" 2>/dev/null || stat -f %m "${dest_file}" 2>/dev/null)

            if [[ ${source_time} -le ${dest_time} ]]; then
                echo -e "  Skip: ${filename} (project version is newer)"
                skipped_count=$((skipped_count + 1))
                continue
            fi
        fi

        cp -p "${source_file}" "${dest_file}"
        echo -e "${GREEN}✓ Pulled: ${filename}${NC}"
        pulled_count=$((pulled_count + 1))
    done < <(find "${VAULT_ROOT}/_brain" -maxdepth 1 -name "*.base" -type f -print0)
fi

# Pull other files
for file_pair in "${FILES[@]}"; do
    IFS=':' read -r vault_path template_name <<< "${file_pair}"

    source_file="${VAULT_ROOT}/${vault_path}"
    dest_file="${TEMPLATE_DIR}/${template_name}"

    if [[ ! -f "${source_file}" ]]; then
        echo -e "${YELLOW}⚠ Missing: ${vault_path}${NC}"
        missing_count=$((missing_count + 1))
        continue
    fi

    # Check if destination exists and compare timestamps
    if [[ -f "${dest_file}" ]]; then
        source_time=$(stat -c %Y "${source_file}" 2>/dev/null || stat -f %m "${source_file}" 2>/dev/null)
        dest_time=$(stat -c %Y "${dest_file}" 2>/dev/null || stat -f %m "${dest_file}" 2>/dev/null)

        if [[ ${source_time} -le ${dest_time} ]]; then
            echo -e "  Skip: ${template_name} (project version is newer)"
            skipped_count=$((skipped_count + 1))
            continue
        fi
    fi

    # Copy with timestamp preservation
    mkdir -p "$(dirname "${dest_file}")"
    cp -p "${source_file}" "${dest_file}"
    echo -e "${GREEN}✓ Pulled: ${template_name}${NC}"
    pulled_count=$((pulled_count + 1))
done

echo ""
echo -e "${GREEN}Summary:${NC}"
echo -e "  Pulled: ${pulled_count}"
echo -e "  Skipped: ${skipped_count}"
[[ ${missing_count} -gt 0 ]] && echo -e "  ${YELLOW}Missing: ${missing_count}${NC}" || true

if [[ ${pulled_count} -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}Note: Restart brain.service to deploy these changes back to the vault:${NC}"
    echo "  systemctl --user restart brain.service"
fi
