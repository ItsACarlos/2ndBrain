#!/usr/bin/env python3
"""
migrate_vault.py — Migrate old vault into 2ndBrain.

Reads every markdown file from the old vault, sends content to
Gemini for classification, and writes properly frontmattered notes
into the new vault. Binary attachments are copied to Attachments/.

Usage:
    cd /home/giles/2nd_brain
    .venv/bin/python migrate_vault.py [--dry-run] [--resume]
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

# ── Configuration ──────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

OLD_VAULT = Path("/home/giles/gilesOldVault")
NEW_VAULT = Path("/home/giles/Documents/2ndBrain/2ndBrainVault")
ATTACHMENTS_DIR = NEW_VAULT / "Attachments"
PROGRESS_FILE = Path(__file__).parent / "migrate_progress.json"

VALID_CATEGORIES = {"Projects", "Actions", "Media", "Reference", "Memories", "Inbox"}

# Folders/patterns to skip in the old vault
SKIP_PATTERNS = {
    ".obsidian",
    ".trash",
    "template",
}

# File extensions to skip (these are structural/config, not content)
SKIP_EXTENSIONS = {".base", ".css", ".js", ".json"}

# Binary attachment extensions
BINARY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".heic"}

MODEL = "gemini-2.5-flash"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "migrate.log"),
    ],
)
log = logging.getLogger(__name__)


MIGRATE_PROMPT_FILE = Path(__file__).parent / "migrate_prompt.md"
SYSTEM_PROMPT = MIGRATE_PROMPT_FILE.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict | None:
    """Extract JSON from a Gemini response using fenced blocks or brace balancing."""
    # Strategy 1: fenced code block
    fence_match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 2: balanced brace matching
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def get_md_files(vault: Path) -> list[Path]:
    """Collect all markdown files to migrate, skipping excluded paths."""
    files = []
    for f in sorted(vault.rglob("*.md")):
        rel = f.relative_to(vault)
        parts = rel.parts

        # Skip excluded directories
        if any(skip in parts for skip in SKIP_PATTERNS):
            continue

        # Skip excalidraw files
        if f.name.endswith(".excalidraw.md"):
            continue

        # Skip _Readme files
        if f.name == "_Readme.md":
            continue

        files.append(f)
    return files


def get_binary_files(vault: Path) -> list[Path]:
    """Collect all binary attachment files to copy."""
    files = []
    for ext in BINARY_EXTENSIONS:
        for f in vault.rglob(f"*{ext}"):
            rel = f.relative_to(vault)
            parts = rel.parts
            if any(skip in parts for skip in SKIP_PATTERNS):
                continue
            files.append(f)
    return files


def load_progress() -> dict:
    """Load migration progress from disk."""
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"completed": [], "failed": [], "skipped": []}


def save_progress(progress: dict):
    """Save migration progress to disk."""
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def make_safe_filename(slug: str) -> str:
    """Make a filesystem-safe filename from a slug."""
    # Remove unsafe characters
    safe = re.sub(r'[:/\\?*"<>|]', "", slug)
    # Collapse multiple spaces
    safe = re.sub(r"\s+", " ", safe).strip()
    # Truncate if too long
    if len(safe) > 100:
        safe = safe[:100].strip()
    return safe


def classify_with_gemini(
    client: genai.Client,
    content: str,
    original_path: str,
    file_date: str,
) -> dict | None:
    """Send content to Gemini for classification and get structured output."""

    user_prompt = f"""Classify and convert this note from an old Obsidian vault.

**Original path in vault:** {original_path}
**File date:** {file_date}

**Content:**
{content}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=user_prompt)],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                ),
            )

            if not response.text:
                log.warning("Empty response from Gemini for %s", original_path)
                return None

            result = _extract_json(response.text)
            if (
                result
                and "folder" in result
                and "slug" in result
                and "content" in result
            ):
                # Validate category
                if result["folder"] not in VALID_CATEGORIES:
                    log.warning(
                        "Invalid category %r for %s, using Inbox",
                        result["folder"],
                        original_path,
                    )
                    result["folder"] = "Inbox"
                return result

            log.warning(
                "Failed to parse JSON from Gemini response for %s (attempt %d)",
                original_path,
                attempt + 1,
            )
            if attempt < 2:
                time.sleep(2)

        except Exception as e:
            log.error("Gemini API error for %s: %s", original_path, e)
            if attempt < 2:
                wait = 5 * (attempt + 1)
                log.info("Retrying in %ds...", wait)
                time.sleep(wait)

    return None


def _force_frontmatter_date(content: str, file_date: str) -> str:
    """Override the date field in YAML frontmatter with the original file's mtime in ISO 8601 datetime format."""
    # Match the frontmatter block
    fm_match = re.match(r"^(---\n)(.*?)(\n---)", content, re.DOTALL)
    if not fm_match:
        return content
    before, fm_body, after = fm_match.group(1), fm_match.group(2), fm_match.group(3)
    rest = content[fm_match.end() :]

    # Replace existing date line, or append one
    if re.search(r"^date:\s*.*$", fm_body, re.MULTILINE):
        fm_body = re.sub(
            r"^date:\s*.*$", f"date: {file_date}", fm_body, count=1, flags=re.MULTILINE
        )
    else:
        fm_body += f"\ndate: {file_date}"

    return f"{before}{fm_body}{after}{rest}"


def write_note(
    folder: str, slug: str, content: str, dry_run: bool = False
) -> Path | None:
    """Write a classified note to the new vault."""
    safe_name = make_safe_filename(slug)
    dest_dir = NEW_VAULT / folder
    dest_file = dest_dir / f"{safe_name}.md"

    # Handle duplicates by appending a number
    counter = 1
    while dest_file.exists():
        dest_file = dest_dir / f"{safe_name} ({counter}).md"
        counter += 1

    if dry_run:
        log.info("[DRY RUN] Would write: %s", dest_file)
        return dest_file

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file.write_text(content, encoding="utf-8")
    log.info("Wrote: %s", dest_file)
    return dest_file


def copy_binary_files(vault: Path, dry_run: bool = False) -> int:
    """Copy binary attachment files to the new vault's Attachments folder."""
    binaries = get_binary_files(vault)
    copied = 0

    for src in binaries:
        dest = ATTACHMENTS_DIR / src.name

        # Handle duplicates
        if dest.exists():
            # Skip if identical size
            if dest.stat().st_size == src.stat().st_size:
                log.debug("Skipping duplicate: %s", src.name)
                continue
            # Rename with number
            stem = dest.stem
            ext = dest.suffix
            counter = 1
            while dest.exists():
                dest = ATTACHMENTS_DIR / f"{stem} ({counter}){ext}"
                counter += 1

        if dry_run:
            log.info("[DRY RUN] Would copy: %s -> %s", src, dest)
        else:
            ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            log.info("Copied attachment: %s -> %s", src.name, dest.name)
        copied += 1

    return copied


def main():
    parser = argparse.ArgumentParser(description="Migrate old vault to 2ndBrain")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without writing"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from last progress checkpoint"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Process only N files then stop (0=all)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.error("GEMINI_API_KEY not set")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Get files to process
    md_files = get_md_files(OLD_VAULT)
    log.info("Found %d markdown files to process", len(md_files))

    # Load progress
    progress = (
        load_progress()
        if args.resume
        else {"completed": [], "failed": [], "skipped": []}
    )
    completed_set = set(progress["completed"])

    # Copy binary attachments first
    log.info("=== Copying binary attachments ===")
    n_copied = copy_binary_files(OLD_VAULT, dry_run=args.dry_run)
    log.info("Copied %d binary attachments", n_copied)

    # Process markdown files
    log.info("=== Processing markdown files ===")
    processed = 0
    succeeded = 0
    failed = 0

    for i, md_file in enumerate(md_files):
        rel_path = str(md_file.relative_to(OLD_VAULT))

        # Skip already done
        if rel_path in completed_set:
            log.debug("Skipping (already done): %s", rel_path)
            continue

        # Read content
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            log.error("Failed to read %s: %s", rel_path, e)
            progress["failed"].append(rel_path)
            save_progress(progress)
            failed += 1
            continue

        # Skip very short / empty files
        stripped = content.strip()
        if len(stripped) < 10:
            log.info("Skipping near-empty file: %s", rel_path)
            progress["skipped"].append(rel_path)
            save_progress(progress)
            continue

        # Get file modification date in ISO 8601 datetime format
        try:
            mtime = md_file.stat().st_mtime
            file_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            file_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        log.info("[%d/%d] Processing: %s", i + 1, len(md_files), rel_path)

        # Classify with Gemini
        result = classify_with_gemini(client, content, rel_path, file_date)

        if result is None:
            log.error("Classification failed for: %s", rel_path)
            progress["failed"].append(rel_path)
            save_progress(progress)
            failed += 1
            continue

        # Force the date in frontmatter to the original file's mtime
        result["content"] = _force_frontmatter_date(result["content"], file_date)

        # Write the note
        dest = write_note(
            result["folder"],
            result["slug"],
            result["content"],
            dry_run=args.dry_run,
        )

        if dest:
            progress["completed"].append(rel_path)
            succeeded += 1
        else:
            progress["failed"].append(rel_path)
            failed += 1

        save_progress(progress)
        processed += 1

        # Rate limiting — Gemini free tier: 15 RPM for flash
        # Be conservative: ~2 seconds between requests
        time.sleep(2)

        if args.batch_size and processed >= args.batch_size:
            log.info("Batch limit reached (%d files)", args.batch_size)
            break

    # Summary
    log.info("=" * 60)
    log.info("Migration complete!")
    log.info("  Processed: %d", processed)
    log.info("  Succeeded: %d", succeeded)
    log.info("  Failed:    %d", failed)
    log.info("  Skipped:   %d", len(progress["skipped"]))
    log.info(
        "  Total completed (all runs): %d / %d",
        len(progress["completed"]),
        len(md_files),
    )

    if progress["failed"]:
        log.warning("Failed files:")
        for f in progress["failed"]:
            log.warning("  - %s", f)


if __name__ == "__main__":
    main()
