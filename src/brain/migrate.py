"""
migrate.py — Vault migration utilities.

Provides deterministic and AI-assisted operations for updating vault
notes to current standards: renaming files, fixing frontmatter, and
updating wiki-links.
"""

import logging
import os
import re
from pathlib import Path

from ruamel.yaml import YAML

from .vault import VALID_FOLDERS

# Folders to skip during migration (not user content)
SKIP_FOLDERS = {"_brain", "Attachments", "Demo"}

# Characters unsafe for filenames (stripped during Title Case conversion)
UNSAFE_CHARS = re.compile(r'[:/\\?*"<>|]')

yaml = YAML()
yaml.preserve_quotes = True


# ------------------------------------------------------------------
# YAML frontmatter round-trip helpers
# ------------------------------------------------------------------


def _read_frontmatter(file_path: Path) -> tuple[dict | None, str, str]:
    """Read a markdown file and parse its YAML frontmatter.

    Returns:
        (frontmatter_dict, raw_yaml_text, body_text)
        frontmatter_dict is None if no valid frontmatter block is found.
    """
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, "", text

    end = text.find("---", 3)
    if end == -1:
        return None, "", text

    raw_yaml = text[3:end].strip()
    body = text[end + 3 :].lstrip("\n")

    try:
        from io import StringIO

        data = yaml.load(StringIO(raw_yaml))
    except Exception:
        return None, raw_yaml, body

    return (dict(data) if data else {}), raw_yaml, body


def _write_frontmatter(file_path: Path, fm: dict, body: str) -> None:
    """Write frontmatter dict and body back to a markdown file."""
    from io import StringIO

    stream = StringIO()
    yaml.dump(fm, stream)
    yaml_text = stream.getvalue().rstrip("\n")

    file_path.write_text(f"---\n{yaml_text}\n---\n\n{body}", encoding="utf-8")


# ------------------------------------------------------------------
# Title Case helpers
# ------------------------------------------------------------------


def _slug_to_title(stem: str) -> str:
    """Convert a hyphenated-lowercase slug to Title Case with spaces.

    Examples:
        'fix-garden-fence'  -> 'Fix Garden Fence'
        'react-hook-patterns' -> 'React Hook Patterns'
    """
    return " ".join(word.capitalize() for word in stem.split("-"))


def _title_to_filename(title: str) -> str:
    """Convert a title string to a safe filename (no .md extension).

    Strips unsafe filesystem characters and collapses whitespace.
    """
    clean = UNSAFE_CHARS.sub("", title)
    return " ".join(clean.split())


def _is_hyphenated_slug(stem: str) -> bool:
    """Check if a filename stem is old-style hyphenated-lowercase."""
    return stem == stem.lower() and "-" in stem and not stem.startswith("_")


# ------------------------------------------------------------------
# rename_to_title_case
# ------------------------------------------------------------------


def rename_to_title_case(vault_path: Path, dry_run: bool = False) -> dict[str, str]:
    """Rename old-style hyphenated files to Title Case.

    Reads the ``title`` from each note's frontmatter to derive the new
    filename. Falls back to converting the slug if no title is available.

    Args:
        vault_path: Root path of the Obsidian vault.
        dry_run: If True, log proposed changes but don't modify files.

    Returns:
        A rename map ``{old_stem: new_stem}`` for use by
        :func:`update_wiki_links`.
    """
    rename_map: dict[str, str] = {}

    for folder in VALID_FOLDERS - SKIP_FOLDERS:
        folder_path = vault_path / folder
        if not folder_path.exists():
            continue

        for md_file in sorted(folder_path.glob("*.md")):
            old_stem = md_file.stem

            # Only rename old-style slugs
            if not _is_hyphenated_slug(old_stem):
                continue

            # Try to get a title from frontmatter
            fm, _, _ = _read_frontmatter(md_file)
            if fm and fm.get("title"):
                new_stem = _title_to_filename(str(fm["title"]))
            else:
                new_stem = _slug_to_title(old_stem)

            if new_stem == old_stem:
                continue

            new_path = md_file.with_stem(new_stem)

            # Deduplicate
            counter = 1
            while new_path.exists() and new_path != md_file:
                new_path = md_file.parent / f"{new_stem} {counter}.md"
                counter += 1

            rename_map[old_stem] = new_path.stem

            if dry_run:
                logging.info("[DRY RUN] Rename: %s -> %s", md_file.name, new_path.name)
            else:
                md_file.rename(new_path)
                logging.info("Renamed: %s -> %s", md_file.name, new_path.name)

    return rename_map


# ------------------------------------------------------------------
# update_wiki_links
# ------------------------------------------------------------------


def update_wiki_links(
    vault_path: Path,
    rename_map: dict[str, str],
    dry_run: bool = False,
) -> int:
    """Update wiki-links throughout the vault to reflect renamed files.

    Scans all ``.md`` files (including Demo and other folders) and
    replaces ``[[old-stem]]`` / ``![[old-stem]]`` references with the
    new names from *rename_map*.

    Args:
        vault_path: Root path of the Obsidian vault.
        rename_map: ``{old_stem: new_stem}`` from :func:`rename_to_title_case`.
        dry_run: If True, log changes without writing.

    Returns:
        Number of files modified.
    """
    if not rename_map:
        return 0

    # Build a single regex matching any old stem inside [[ ]]
    escaped = [re.escape(old) for old in rename_map]
    # Match [[old-stem]] and ![[old-stem]] (with optional display text)
    pattern = re.compile(r"(!?\[\[)(" + "|".join(escaped) + r")((?:\|[^\]]*)?)\]\]")

    modified_count = 0

    for md_file in vault_path.rglob("*.md"):
        # Skip system files
        if md_file.parent.name == "_brain":
            continue

        text = md_file.read_text(encoding="utf-8")
        new_text = pattern.sub(
            lambda m: f"{m.group(1)}{rename_map[m.group(2)]}{m.group(3)}]]",
            text,
        )

        if new_text != text:
            if dry_run:
                logging.info("[DRY RUN] Update links in: %s", md_file.name)
            else:
                md_file.write_text(new_text, encoding="utf-8")
                logging.info("Updated links in: %s", md_file.name)
            modified_count += 1

    return modified_count


# ------------------------------------------------------------------
# fix_frontmatter
# ------------------------------------------------------------------

# Canonical priority values (numeric prefix ensures correct sort order)
_PRIORITY_VALUES = ("1 - Urgent", "2 - High", "3 - Medium", "4 - Low")

# Migration map for old bare-word priority values
_PRIORITY_MIGRATE: dict[str, str] = {
    "urgent": "1 - Urgent",
    "high": "2 - High",
    "medium": "3 - Medium",
    "low": "4 - Low",
}

# Required fields per category, with default values
_CATEGORY_DEFAULTS: dict[str, dict[str, str]] = {
    "Projects": {"project_name": "", "priority": "3 - Medium"},
    "Actions": {
        "action_item": "",
        "status": "todo",
        "priority": "3 - Medium",
        "due_date": "",
        "project": "",
    },
    "Media": {
        "media_type": "article",
        "creator": "",
        "url": "",
        "status": "to_consume",
    },
    "Reference": {"topic": ""},
    "Memories": {"people": "", "location": "", "memory_date": ""},
}


def fix_frontmatter(vault_path: Path, dry_run: bool = False) -> int:
    """Sync frontmatter ``category`` with actual folder and add missing fields.

    For each note:
    - Sets ``category`` to match the folder it lives in.
    - Adds any missing category-specific fields with defaults.
    - Ensures ``source: slack`` is present.

    Args:
        vault_path: Root path of the Obsidian vault.
        dry_run: If True, log changes without writing.

    Returns:
        Number of files modified.
    """
    modified = 0

    for folder in VALID_FOLDERS - SKIP_FOLDERS:
        folder_path = vault_path / folder
        if not folder_path.exists():
            continue

        defaults = _CATEGORY_DEFAULTS.get(folder, {})

        for md_file in sorted(folder_path.glob("*.md")):
            fm, raw_yaml, body = _read_frontmatter(md_file)
            if fm is None:
                continue

            changed = False

            # Sync category with folder
            if fm.get("category") != folder:
                logging.info(
                    "  Fix category: %s -> %s (%s)",
                    fm.get("category"),
                    folder,
                    md_file.name,
                )
                fm["category"] = folder
                changed = True

            # Ensure source
            if fm.get("source") != "slack":
                fm["source"] = "slack"
                changed = True

            # Add missing category-specific fields
            for key, default in defaults.items():
                if key not in fm:
                    fm[key] = default
                    changed = True
                    logging.info("  Add field %s=%r to %s", key, default, md_file.name)

            # Migrate bare-word priority values to prefixed enum
            raw_priority = str(fm.get("priority", "")).strip().lower()
            if raw_priority in _PRIORITY_MIGRATE:
                new_val = _PRIORITY_MIGRATE[raw_priority]
                logging.info(
                    "  Migrate priority: %s -> %s (%s)",
                    fm["priority"],
                    new_val,
                    md_file.name,
                )
                fm["priority"] = new_val
                changed = True

            # Convert tags with spaces to kebab-case
            tags = fm.get("tags")
            if isinstance(tags, list):
                new_tags = [
                    t.strip().replace(" ", "-") if isinstance(t, str) else t
                    for t in tags
                ]
                if new_tags != tags:
                    logging.info("  Kebab-case tags: %s (%s)", new_tags, md_file.name)
                    fm["tags"] = new_tags
                    changed = True

            if changed:
                modified += 1
                if dry_run:
                    logging.info("[DRY RUN] Fix frontmatter: %s", md_file.name)
                else:
                    _write_frontmatter(md_file, fm, body)
                    logging.info("Fixed frontmatter: %s", md_file.name)

    return modified


# ------------------------------------------------------------------
# reclassify_notes (AI-assisted)
# ------------------------------------------------------------------

_RECLASSIFY_PROMPT = """\
You are reviewing an existing Obsidian vault note. Given its current YAML
frontmatter and body, return a JSON object with corrected/improved values.

ONLY return fields that should CHANGE. Do not include fields that are already
correct. If nothing needs changing, return an empty JSON object {{}}.

Possible changes:
- category: move to a better folder (Projects/Actions/Media/Reference/Memories/Inbox)
- tags: improved/expanded tag list (YAML list of strings)
- Any category-specific field (see the schema below)

Category field schemas:
- Projects: project_name, priority (1 - Urgent / 2 - High / 3 - Medium / 4 - Low)
- Actions: action_item, due_date, project (wiki-link), status, priority
- Media: media_title, media_type (book/film/tv/podcast/article/video), creator,
  url, status
- Reference: topic, related_projects (list of wiki-links)
- Memories: people (list of names), location, memory_date

Return ONLY raw JSON — no markdown fences, no explanation.

## Current frontmatter
{frontmatter}

## Note body (first 500 chars)
{body}
"""


def reclassify_notes(vault_path: Path, dry_run: bool = False) -> int:
    """Use Gemini to re-evaluate and improve note metadata.

    Requires ``GEMINI_API_KEY`` in the environment (loaded from ``.env``).

    Args:
        vault_path: Root path of the Obsidian vault.
        dry_run: If True, log proposed changes without writing.

    Returns:
        Number of files modified.
    """
    from google import genai

    from .processor import _extract_json

    client = genai.Client()
    modified = 0
    total_tokens = 0

    for folder in VALID_FOLDERS - SKIP_FOLDERS:
        folder_path = vault_path / folder
        if not folder_path.exists():
            continue

        for md_file in sorted(folder_path.glob("*.md")):
            fm, _, body = _read_frontmatter(md_file)
            if fm is None:
                continue

            prompt = _RECLASSIFY_PROMPT.format(
                frontmatter=str(fm),
                body=body[:500],
            )

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[prompt],
                )
            except Exception as e:
                logging.error("Reclassify error for %s: %s", md_file.name, e)
                continue

            tokens = (
                (response.usage_metadata.total_token_count or 0)
                if response.usage_metadata
                else 0
            )
            total_tokens += tokens

            text = response.text or ""
            changes = _extract_json(text)

            if not changes:
                continue

            # Apply changes
            new_folder = changes.pop("category", None)
            if changes or new_folder:
                modified += 1
                for key, value in changes.items():
                    fm[key] = value

                if new_folder and new_folder != folder and new_folder in VALID_FOLDERS:
                    fm["category"] = new_folder
                    dest = vault_path / new_folder / md_file.name
                    if dry_run:
                        logging.info(
                            "[DRY RUN] Reclassify %s: %s -> %s + %s",
                            md_file.name,
                            folder,
                            new_folder,
                            changes,
                        )
                    else:
                        _write_frontmatter(md_file, fm, body)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        md_file.rename(dest)
                        logging.info(
                            "Reclassified %s: %s -> %s",
                            md_file.name,
                            folder,
                            new_folder,
                        )
                else:
                    if dry_run:
                        logging.info(
                            "[DRY RUN] Update metadata: %s -> %s",
                            md_file.name,
                            changes,
                        )
                    else:
                        _write_frontmatter(md_file, fm, body)
                        logging.info(
                            "Updated metadata: %s -> %s", md_file.name, changes
                        )

    logging.info("Reclassify complete. Total tokens used: %d", total_tokens)
    return modified


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------


def run_migration(
    vault_path: Path,
    *,
    rename: bool = False,
    fix_fm: bool = False,
    update_links: bool = False,
    reclassify: bool = False,
    dry_run: bool = False,
) -> dict[str, int | dict]:
    """Run selected migration operations in the correct order.

    Order: reclassify -> fix_frontmatter -> rename -> update_links

    Args:
        vault_path: Root path of the Obsidian vault.
        rename: Rename hyphenated files to Title Case.
        fix_fm: Fix frontmatter category mismatches and missing fields.
        update_links: Update wiki-links after renames.
        reclassify: Use Gemini to re-evaluate notes (requires API key).
        dry_run: Preview changes without writing.

    Returns:
        Summary dict with counts for each operation performed.
    """
    if not os.environ.get("GEMINI_API_KEY") and reclassify:
        logging.error(
            "GEMINI_API_KEY not set — cannot reclassify. "
            "Set it in .env or the environment."
        )
        reclassify = False

    summary: dict[str, int | dict] = {}

    if dry_run:
        logging.info("=== DRY RUN — no files will be modified ===")

    if reclassify:
        logging.info("--- Step 1: Reclassify notes (Gemini) ---")
        summary["reclassified"] = reclassify_notes(vault_path, dry_run)

    if fix_fm:
        logging.info("--- Step 2: Fix frontmatter ---")
        summary["frontmatter_fixed"] = fix_frontmatter(vault_path, dry_run)

    rename_map: dict[str, str] = {}
    if rename:
        logging.info("--- Step 3: Rename to Title Case ---")
        rename_map = rename_to_title_case(vault_path, dry_run)
        summary["renamed"] = len(rename_map)
        summary["rename_map"] = rename_map

    if update_links:
        logging.info("--- Step 4: Update wiki-links ---")
        link_map = rename_map  # Use renames from this run
        summary["links_updated"] = update_wiki_links(vault_path, link_map, dry_run)

    logging.info("=== Migration summary: %s ===", summary)
    return summary
