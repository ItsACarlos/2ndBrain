"""
vault.py — All Obsidian vault I/O operations.

Handles folder structure, note writing, attachment saving,
project discovery, and Obsidian Bases file generation.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

# Category folders and their descriptions
CATEGORIES = {
    "Projects": "Project documentation, snippets, whiteboard photos, ideas",
    "Actions": "Tasks and to-dos with due dates and status tracking",
    "Media": "Books, films, TV, podcasts, articles, videos to consume",
    "Reference": "How-tos, explanations, useful information to find again",
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
        """Generate Obsidian .base files if they don't already exist."""
        bases = {
            "Projects/Projects.base": self._projects_base(),
            "Actions/Actions.base": self._actions_base(),
            "Media/Media.base": self._media_base(),
            "Reference/Reference.base": self._reference_base(),
            "Dashboard.base": self._dashboard_base(),
        }

        for rel_path, content in bases.items():
            full_path = self.base_path / rel_path
            if not full_path.exists():
                full_path.write_text(content, encoding="utf-8")
                logging.info(f"Created Obsidian base: {rel_path}")

    @staticmethod
    def _projects_base() -> str:
        return """\
filters:
  and:
    - 'file.inFolder("Projects")'
    - 'file.ext == "md"'
properties:
  title:
    displayName: Title
  project_name:
    displayName: Project
  priority:
    displayName: Priority
  date:
    displayName: Date
  tags:
    displayName: Tags
views:
  - type: table
    name: All Projects
    order:
      - note.priority
      - note.date
      - note.title
      - note.project_name
      - note.tags
"""

    @staticmethod
    def _actions_base() -> str:
        return """\
filters:
  and:
    - 'file.inFolder("Actions")'
    - 'file.ext == "md"'
properties:
  title:
    displayName: Title
  action_item:
    displayName: Action
  status:
    displayName: Status
  due_date:
    displayName: Due Date
  priority:
    displayName: Priority
  project:
    displayName: Project
views:
  - type: table
    name: Open Actions
    filters:
      and:
        - 'status != "done"'
        - 'status != "completed"'
    order:
      - note.due_date
      - note.priority
      - note.action_item
      - note.status
      - note.project
  - type: table
    name: All Actions
    order:
      - note.due_date
      - note.priority
      - note.action_item
      - note.status
      - note.project
"""

    @staticmethod
    def _media_base() -> str:
        return """\
filters:
  and:
    - 'file.inFolder("Media")'
    - 'file.ext == "md"'
properties:
  media_title:
    displayName: Title
  media_type:
    displayName: Type
  creator:
    displayName: Creator
  status:
    displayName: Status
  url:
    displayName: URL
views:
  - type: table
    name: All Media
    groupBy:
      property: note.media_type
      direction: ASC
    order:
      - note.media_title
      - note.media_type
      - note.creator
      - note.status
      - note.url
  - type: table
    name: To Consume
    filters:
      and:
        - 'status == "to_consume"'
    order:
      - note.media_title
      - note.media_type
      - note.creator
"""

    @staticmethod
    def _reference_base() -> str:
        return """\
filters:
  and:
    - 'file.inFolder("Reference")'
    - 'file.ext == "md"'
properties:
  title:
    displayName: Title
  topic:
    displayName: Topic
  tags:
    displayName: Tags
  date:
    displayName: Date
views:
  - type: table
    name: All Reference
    order:
      - note.title
      - note.topic
      - note.tags
      - note.date
"""

    @staticmethod
    def _dashboard_base() -> str:
        return """\
filters:
  and:
    - 'file.ext == "md"'
properties:
  title:
    displayName: Title
  category:
    displayName: Category
  status:
    displayName: Status
  due_date:
    displayName: Due Date
  priority:
    displayName: Priority
  date:
    displayName: Date
views:
  - type: table
    name: "Today's Actions"
    filters:
      and:
        - 'file.inFolder("Actions")'
        - 'status != "done"'
        - 'status != "completed"'
    order:
      - note.priority
      - note.due_date
      - note.title
      - note.status
  - type: table
    name: Recent Captures
    filters:
      and:
        - 'file.mtime > now() - "7 days"'
    order:
      - file.mtime
      - note.title
      - note.category
  - type: table
    name: All Open Actions
    filters:
      and:
        - 'file.inFolder("Actions")'
        - 'status != "done"'
        - 'status != "completed"'
    order:
      - note.due_date
      - note.priority
      - note.title
"""
