#!/usr/bin/env python3
"""
migrate-dates-to-datetime.py — Convert all date fields to ISO 8601 datetime format.

Scans all markdown files in the vault and converts date fields from
YYYY-MM-DD format to ISO 8601 datetime format (YYYY-MM-DDTHH:MM:SS).
For dates without a specific time, uses 09:00:00 as default.

Usage:
    python scripts/migrate-dates-to-datetime.py [--dry-run]
"""

import argparse
import re
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Convert date fields from YYYY-MM-DD to ISO 8601 datetime"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    args = parser.parse_args()

    vault_root = Path.home() / "Documents" / "2ndBrain" / "2ndBrainVault"

    if not vault_root.exists():
        print(f"Error: Vault not found at {vault_root}")
        return 1

    # Find all markdown files
    md_files = list(vault_root.rglob("*.md"))
    print(f"Found {len(md_files)} markdown files")

    updated_count = 0
    skipped_count = 0

    for md_file in sorted(md_files):
        relative_path = md_file.relative_to(vault_root)

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"⚠️  Skipped {relative_path}: {e}")
            skipped_count += 1
            continue

        # Check if file has YAML frontmatter with a date field
        if not content.startswith("---"):
            print(f"⊘ Skipped {relative_path}: No frontmatter")
            skipped_count += 1
            continue

        # Match frontmatter block
        fm_match = re.match(r"^(---\n)(.*?)(\n---)", content, re.DOTALL)
        if not fm_match:
            print(f"⊘ Skipped {relative_path}: Malformed frontmatter")
            skipped_count += 1
            continue

        before, fm_body, after = fm_match.group(1), fm_match.group(2), fm_match.group(3)
        rest = content[fm_match.end() :]

        # Look for date field
        date_match = re.search(r"^date:\s*(.+)$", fm_body, re.MULTILINE)
        if not date_match:
            print(f"⊘ Skipped {relative_path}: No date field")
            skipped_count += 1
            continue

        old_date_str = date_match.group(1).strip()

        # Check if already in ISO 8601 datetime format (contains T)
        if "T" in old_date_str:
            print(f"✓ Already datetime: {relative_path}")
            skipped_count += 1
            continue

        # Try to parse as YYYY-MM-DD format
        try:
            # Handle various date formats
            if len(old_date_str) == 10 and old_date_str.count("-") == 2:
                # YYYY-MM-DD format
                parsed_date = datetime.strptime(old_date_str, "%Y-%m-%d")
                # Use 09:00:00 as default time for date-only fields
                new_date_str = parsed_date.strftime("%Y-%m-%dT09:00:00")
            else:
                # Try ISO format with time
                try:
                    parsed_date = datetime.fromisoformat(old_date_str)
                    new_date_str = parsed_date.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    print(
                        f"⚠️  Skipped {relative_path}: Unrecognized date"
                        f" format '{old_date_str}'"
                    )
                    skipped_count += 1
                    continue

            # Replace the date line in frontmatter
            new_fm = re.sub(
                r"^date:\s*.+$",
                f"date: {new_date_str}",
                fm_body,
                count=1,
                flags=re.MULTILINE,
            )

            new_content = f"{before}{new_fm}{after}{rest}"

            if args.dry_run:
                print(f"→ DRY RUN: {relative_path}")
                print(f"  {old_date_str} → {new_date_str}")
            else:
                md_file.write_text(new_content, encoding="utf-8")
                print(f"✓ Updated {relative_path}: {old_date_str} → {new_date_str}")

            updated_count += 1

        except Exception as e:
            print(f"⚠️  Error processing {relative_path}: {e}")
            skipped_count += 1
            continue

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Updated: {updated_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Total:   {len(md_files)}")

    if args.dry_run:
        print("\nDry run mode — no files were modified.")
        print("Run without --dry-run to apply changes.")

    return 0


if __name__ == "__main__":
    exit(main())
