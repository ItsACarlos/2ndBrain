"""
vault.py — All Obsidian vault I/O operations.

Handles folder structure, note writing, attachment saving,
project discovery, and Obsidian Bases file generation.
"""

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

#: Directory containing .base and .md template files shipped with the package.
_TEMPLATES_DIR = Path(__file__).parent / "vault_templates"

#: Mapping of template filename → vault-relative destination path.
_TEMPLATE_MAP: dict[str, str] = {
    "Projects.base": "Projects/Projects.base",
    "Actions.base": "Actions/Actions.base",
    "Media.base": "Media/Media.base",
    "Reference.base": "Reference/Reference.base",
    "Memories.base": "Memories/Memories.base",
    "Dashboard.base": "_brain/Dashboard.base",
    "Dashboard.md": "Dashboard.md",
}

# Category folders and their descriptions
CATEGORIES = {
    "Projects": "Project documentation, snippets, whiteboard photos, ideas",
    "Actions": "Tasks and to-dos with due dates and status tracking",
    "Media": "Books, films, TV, podcasts, articles, videos to consume",
    "Reference": "How-tos, explanations, useful information to find again",
    "Memories": "Personal memories, family photos, experiences, milestones",
    "Attachments": "Binary files (images, PDFs) linked from categorised notes",
    "Inbox": "Uncategorised fallback for ambiguous captures",
}

VALID_FOLDERS = set(CATEGORIES.keys())


class Vault:
    """Manages all interactions with the Obsidian vault on disk."""

    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or (
            Path.home() / "Documents" / "2ndBrain" / "2ndBrainVault"
        )
        self._validate_vault()
        self._ensure_folders()
        self._ensure_base_files()
        self._ensure_brain_dir()
        logging.info("Vault initialised OK at %s", self.base_path)

    def _validate_vault(self):
        """Check that the vault root is accessible (rclone mount present)."""
        if not self.base_path.parent.exists():
            logging.critical(
                "Vault mount point not found: %s — is rclone running?",
                self.base_path.parent,
            )
            raise SystemExit(1)

        if not self.base_path.exists():
            logging.warning("Vault root not found, creating: %s", self.base_path)
            self.base_path.mkdir(parents=True, exist_ok=True)

    def _ensure_folders(self):
        """Create all category folders if they don't exist."""
        for folder in CATEGORIES:
            folder_path = self.base_path / folder
            created = not folder_path.exists()
            folder_path.mkdir(parents=True, exist_ok=True)
            if created:
                logging.info("Created category folder: %s/", folder)

    def _ensure_brain_dir(self):
        """Create the _brain/ directory for system files (directives, etc.)."""
        brain_dir = self.base_path / "_brain"
        brain_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Directives (persistent memory)
    # ------------------------------------------------------------------

    @property
    def _directives_path(self) -> Path:
        return self.base_path / "_brain" / "directives.md"

    def get_directives(self) -> list[str]:
        """Read all directives from the persistent memory file.

        Returns a list of directive strings (one per bullet point).
        """
        path = self._directives_path
        if not path.exists():
            return []

        text = path.read_text(encoding="utf-8")
        directives = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                directives.append(stripped[2:].strip())
        return directives

    def add_directive(self, directive: str) -> list[str]:
        """Append a directive to the memory file. Returns the updated list."""
        directives = self.get_directives()
        directives.append(directive)
        self._write_directives(directives)
        logging.info("Added directive: %s", directive[:60])
        return directives

    def remove_directive(self, index: int) -> tuple[str | None, list[str]]:
        """Remove a directive by 1-based index.

        Returns (removed_text or None, updated list).
        """
        directives = self.get_directives()
        if 1 <= index <= len(directives):
            removed = directives.pop(index - 1)
            self._write_directives(directives)
            logging.info("Removed directive #%d: %s", index, removed[:60])
            return removed, directives
        return None, directives

    def _write_directives(self, directives: list[str]) -> None:
        """Write the full directives list back to disk."""
        lines = ["# Brain Directives\n"]
        for d in directives:
            lines.append(f"- {d}")
        self._directives_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Note writing
    # ------------------------------------------------------------------

    def save_note(self, folder: str, slug: str, content: str) -> Path:
        """
        Save a markdown note to the vault.

        Args:
            folder: Category folder name (validated against whitelist).
            slug: Descriptive slug for the filename (e.g. 'fix-garden-fence').
            content: Full markdown content including YAML frontmatter.

        Returns:
            Path to the saved file.

        Raises:
            ValueError: If folder is not in the allowed category list.
        """
        if folder not in VALID_FOLDERS:
            logging.warning(f"Invalid folder '{folder}', falling back to Inbox")
            folder = "Inbox"

        filename = f"{slug}.md"
        folder_path = self.base_path / folder
        # Ensure folder exists (safety net for rclone sync delays)
        folder_path.mkdir(parents=True, exist_ok=True)
        file_path = folder_path / filename

        # Deduplicate if file already exists
        counter = 1
        while file_path.exists():
            filename = f"{slug}-{counter}.md"
            file_path = folder_path / filename
            counter += 1

        file_path.write_text(content, encoding="utf-8")
        logging.info(f"Saved note: {folder}/{filename}")
        return file_path

    # ------------------------------------------------------------------
    # Note editing
    # ------------------------------------------------------------------

    def update_frontmatter(
        self,
        file_path: Path,
        updates: dict[str, str | None],
    ) -> dict[str, str]:
        """Update YAML frontmatter fields in an existing markdown note.

        Args:
            file_path: Absolute path to the .md file.
            updates: Dict of field→value. Set value to ``None``
                     to remove a field.

        Returns:
            Dict of actually changed fields {field: new_value}
            (or {field: "<removed>"} for deletions).

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            ValueError: If the file has no YAML frontmatter block.
        """
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        text = file_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise ValueError(f"No frontmatter block in {file_path.name}")

        end = text.find("---", 3)
        if end == -1:
            raise ValueError(f"Unterminated frontmatter in {file_path.name}")

        fm_block = text[3:end]
        body = text[end + 3 :]  # everything after the closing ---

        # Parse existing lines preserving order
        fm_lines: list[str] = fm_block.strip().splitlines()
        existing_keys: dict[str, int] = {}
        for i, line in enumerate(fm_lines):
            if ":" in line:
                key = line.partition(":")[0].strip()
                existing_keys[key] = i

        changed: dict[str, str] = {}

        for key, value in updates.items():
            if value is None:
                # Remove field
                if key in existing_keys:
                    idx = existing_keys[key]
                    fm_lines[idx] = ""  # blank it, cleaned up below
                    changed[key] = "<removed>"
            else:
                new_line = f"{key}: {value}"
                if key in existing_keys:
                    idx = existing_keys[key]
                    if fm_lines[idx].strip() != new_line:
                        fm_lines[idx] = new_line
                        changed[key] = str(value)
                else:
                    fm_lines.append(new_line)
                    changed[key] = str(value)

        if not changed:
            return changed

        # Re-assemble file
        cleaned = [ln for ln in fm_lines if ln.strip()]
        new_fm = "\n".join(cleaned)
        new_text = f"---\n{new_fm}\n---{body}"
        file_path.write_text(new_text, encoding="utf-8")
        logging.info("Updated frontmatter in %s: %s", file_path.name, changed)
        return changed

    def find_note(self, filename: str, folder: str | None = None) -> Path | None:
        """Locate a note by exact filename, optionally limited to a folder.

        Returns the absolute path, or ``None`` if not found.
        """
        if folder:
            candidate = self.base_path / folder / filename
            return candidate if candidate.is_file() else None

        for cat in CATEGORIES:
            candidate = self.base_path / cat / filename
            if candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------------------
    # Attachment handling
    # ------------------------------------------------------------------

    def save_attachment(self, original_name: str, data: bytes) -> str:
        """
        Save a binary attachment to the Attachments folder.

        Args:
            original_name: Original filename from Slack.
            data: Raw file bytes.

        Returns:
            The saved filename (for use in wiki-links).
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = re.sub(r"[^a-zA-Z0-9._-]", "", original_name)
        saved_filename = f"{timestamp}_{clean_name}"
        att_dir = self.base_path / "Attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        save_path = att_dir / saved_filename

        save_path.write_bytes(data)
        logging.info(f"Saved attachment: Attachments/{saved_filename}")
        return saved_filename

    # ------------------------------------------------------------------
    # Project discovery
    # ------------------------------------------------------------------

    def list_projects(self) -> list[str]:
        """
        Scan the Projects folder for existing project names.

        Returns a list of project names derived from subfolder names
        and note titles in the Projects directory.
        """
        projects_dir = self.base_path / "Projects"
        project_names = set()

        for item in projects_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                project_names.add(item.name)
            elif item.is_file() and item.suffix == ".md":
                # Use the stem as a project name hint
                project_names.add(item.stem)

        return sorted(project_names)

    # ------------------------------------------------------------------
    # Vault scanning (for daily briefing)
    # ------------------------------------------------------------------

    def scan_actions(self) -> list[dict]:
        """
        Read all action notes and parse their frontmatter.

        Returns a list of dicts with keys: path, title, status,
        due_date, priority, project.
        """
        actions_dir = self.base_path / "Actions"
        results = []

        for md_file in actions_dir.glob("*.md"):
            fm = self._parse_frontmatter(md_file)
            if fm:
                results.append(
                    {
                        "path": md_file,
                        "title": fm.get("title", md_file.stem),
                        "status": fm.get("status", "todo"),
                        "due_date": fm.get("due_date"),
                        "priority": fm.get("priority", "medium"),
                        "project": fm.get("project"),
                    }
                )

        return results

    def scan_recent(self, hours: int = 24) -> list[dict]:
        """Find all notes modified within the last N hours."""
        from datetime import timedelta

        cutoff = datetime.now().timestamp() - timedelta(hours=hours).total_seconds()
        results = []

        for folder in CATEGORIES:
            folder_path = self.base_path / folder
            for md_file in folder_path.glob("*.md"):
                if md_file.stat().st_mtime > cutoff:
                    fm = self._parse_frontmatter(md_file)
                    results.append(
                        {
                            "path": md_file,
                            "folder": folder,
                            "title": fm.get("title", md_file.stem)
                            if fm
                            else md_file.stem,
                        }
                    )

        return results

    def scan_media_backlog(self) -> list[dict]:
        """Find media items with status 'to_consume'."""
        media_dir = self.base_path / "Media"
        results = []

        for md_file in media_dir.glob("*.md"):
            fm = self._parse_frontmatter(md_file)
            if fm and fm.get("status") == "to_consume":
                results.append(
                    {
                        "path": md_file,
                        "title": fm.get("media_title", md_file.stem),
                        "media_type": fm.get("media_type", "unknown"),
                    }
                )

        return results

    # ------------------------------------------------------------------
    # Vault search (used by agents)
    # ------------------------------------------------------------------

    def search_notes(
        self,
        keywords: list[str] | None = None,
        folders: list[str] | None = None,
        max_results: int = 30,
    ) -> list[dict]:
        """
        Search vault notes and attachments by keyword and/or folder.

        Returns a list of dicts with keys: filename, folder, frontmatter,
        size_bytes, modified, word_count (0 for binary files).
        Keywords are matched case-insensitively against the filename and
        all frontmatter values.

        Args:
            keywords: Terms to match in filenames / frontmatter values.
                      If empty or None, all files in the target folders
                      are returned.
            folders: Category folders to search. None means all folders
                     (including Attachments).
            max_results: Cap the number of returned matches.
        """
        search_folders = folders or list(CATEGORIES)
        # Validate folder names
        search_folders = [f for f in search_folders if f in VALID_FOLDERS]

        lower_keywords = [k.lower() for k in (keywords or [])]
        results: list[dict] = []

        for folder in search_folders:
            folder_path = self.base_path / folder
            if not folder_path.exists():
                continue

            # Attachments contain binary files; other folders have .md
            glob_pattern = "*" if folder == "Attachments" else "*.md"

            for file_path in folder_path.glob(glob_pattern):
                if not file_path.is_file():
                    continue

                # Parse frontmatter for markdown files only
                is_md = file_path.suffix == ".md"
                fm = self._parse_frontmatter(file_path) or {} if is_md else {}

                if lower_keywords:
                    searchable = file_path.stem.lower()
                    for v in fm.values():
                        searchable += " " + str(v).lower()

                    if not any(kw in searchable for kw in lower_keywords):
                        continue

                # Enrich with file-system metadata
                stat = file_path.stat()
                word_count = 0
                if is_md:
                    try:
                        text = file_path.read_text(encoding="utf-8")
                        word_count = len(text.split())
                    except Exception:
                        pass

                results.append(
                    {
                        "filename": file_path.name,
                        "folder": folder,
                        "frontmatter": fm,
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "word_count": word_count,
                    }
                )

                if len(results) >= max_results:
                    return results

        return results

    # ------------------------------------------------------------------
    # Metadata index (lightweight — no file contents sent to Gemini)
    # ------------------------------------------------------------------

    def index_all_notes(
        self,
        folders: list[str] | None = None,
        max_results: int = 500,
    ) -> list[dict]:
        """Build a compact metadata index of every note in the vault.

        Returns a list of dicts with: filename, folder, size_bytes,
        modified, word_count, and frontmatter.
        No file body text is loaded — only stat() and frontmatter.
        """
        search_folders = folders or list(CATEGORIES)
        search_folders = [f for f in search_folders if f in VALID_FOLDERS]
        results: list[dict] = []

        for folder in search_folders:
            folder_path = self.base_path / folder
            if not folder_path.exists():
                continue

            glob = "*" if folder == "Attachments" else "*.md"
            for fp in folder_path.glob(glob):
                if not fp.is_file():
                    continue

                is_md = fp.suffix == ".md"
                fm = (self._parse_frontmatter(fp) or {}) if is_md else {}
                stat = fp.stat()

                # Word count from size estimate (avoids full read)
                word_count = 0
                if is_md:
                    # ~6 bytes per word is a rough English estimate
                    word_count = stat.st_size // 6

                results.append(
                    {
                        "filename": fp.name,
                        "folder": folder,
                        "frontmatter": fm,
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "word_count": word_count,
                    }
                )
                if len(results) >= max_results:
                    return results

        return results

    # ------------------------------------------------------------------
    # Grep search (returns matching filenames + snippets)
    # ------------------------------------------------------------------

    def grep_notes(
        self,
        pattern: str,
        folders: list[str] | None = None,
        max_results: int = 100,
        context_chars: int = 80,
    ) -> list[dict]:
        """Search vault file contents for a text pattern.

        Returns a list of dicts with: filename, folder, matches
        (list of short context snippets around each hit).

        This is a local operation — no Gemini call required.
        """
        search_folders = folders or list(CATEGORIES)
        search_folders = [f for f in search_folders if f in VALID_FOLDERS]
        lower_pattern = pattern.lower()
        results: list[dict] = []

        for folder in search_folders:
            folder_path = self.base_path / folder
            if not folder_path.exists():
                continue

            for fp in folder_path.glob("*.md"):
                if not fp.is_file():
                    continue

                try:
                    text = fp.read_text(encoding="utf-8")
                except Exception:
                    continue

                lower_text = text.lower()
                positions = []
                start = 0
                while True:
                    idx = lower_text.find(lower_pattern, start)
                    if idx == -1:
                        break
                    positions.append(idx)
                    start = idx + 1

                if not positions:
                    continue

                # Extract short snippets around each match
                snippets: list[str] = []
                for pos in positions[:3]:  # max 3 snippets per file
                    snip_start = max(0, pos - context_chars)
                    snip_end = min(len(text), pos + len(pattern) + context_chars)
                    snippet = text[snip_start:snip_end].replace("\n", " ")
                    if snip_start > 0:
                        snippet = "..." + snippet
                    if snip_end < len(text):
                        snippet = snippet + "..."
                    snippets.append(snippet)

                results.append(
                    {
                        "filename": fp.name,
                        "folder": folder,
                        "match_count": len(positions),
                        "snippets": snippets,
                    }
                )

                if len(results) >= max_results:
                    return results

        return results

    # ------------------------------------------------------------------
    # Frontmatter parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_frontmatter(file_path: Path) -> dict | None:
        """
        Extract YAML frontmatter from a markdown file.

        Returns a dict of frontmatter fields, or None if no
        valid frontmatter block is found.
        """
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        if not text.startswith("---"):
            return None

        end = text.find("---", 3)
        if end == -1:
            return None

        # Simple key: value parsing (no nested YAML dependency)
        frontmatter = {}
        for line in text[3:end].strip().splitlines():
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if value:
                    frontmatter[key] = value

        return frontmatter

    # ------------------------------------------------------------------
    # Obsidian .base file generation
    # ------------------------------------------------------------------

    def _ensure_base_files(self):
        """Copy vault template files when the source is newer or dest is missing."""
        for template_name, vault_rel in _TEMPLATE_MAP.items():
            src = _TEMPLATES_DIR / template_name
            dest = self.base_path / vault_rel

            if not src.exists():
                logging.warning("Template not found: %s", src)
                continue

            if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
                continue  # vault copy is up-to-date

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            logging.info("Synced vault template: %s", vault_rel)
