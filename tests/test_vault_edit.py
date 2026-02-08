"""Tests for vault_edit agent and Vault.update_frontmatter."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set a fake API key so ``genai.Client()`` doesn't raise during tests.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from brain.agents.base import MessageContext  # noqa: E402
from brain.agents.vault_edit import VaultEditAgent  # noqa: E402
from brain.vault import Vault  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Vault:
    """Create a minimal Vault in a temp directory."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    # Create the parent directory that Vault._validate_vault checks
    return Vault(base_path=vault_root)


def _write_note(vault: Vault, folder: str, name: str, content: str) -> Path:
    """Write a markdown file into a vault folder."""
    folder_path = vault.base_path / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    path = folder_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Vault.update_frontmatter
# ---------------------------------------------------------------------------


class TestUpdateFrontmatter:
    """Tests for the Vault.update_frontmatter method."""

    def test_update_existing_field(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Actions",
            "test.md",
            "---\ntitle: Test\npriority: low\n---\nBody text\n",
        )

        changed = vault.update_frontmatter(path, {"priority": "urgent"})

        assert changed == {"priority": "urgent"}
        text = path.read_text(encoding="utf-8")
        assert "priority: urgent" in text
        assert "priority: low" not in text
        assert "Body text" in text

    def test_add_new_field(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Actions",
            "test.md",
            "---\ntitle: Test\n---\nBody\n",
        )

        changed = vault.update_frontmatter(path, {"priority": "high"})

        assert changed == {"priority": "high"}
        text = path.read_text(encoding="utf-8")
        assert "priority: high" in text
        assert "title: Test" in text

    def test_remove_field(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Actions",
            "test.md",
            "---\ntitle: Test\npriority: low\nstatus: todo\n---\nBody\n",
        )

        changed = vault.update_frontmatter(path, {"priority": None})

        assert changed == {"priority": "<removed>"}
        text = path.read_text(encoding="utf-8")
        assert "priority" not in text
        assert "title: Test" in text
        assert "status: todo" in text

    def test_no_change_when_already_correct(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Actions",
            "test.md",
            "---\ntitle: Test\npriority: urgent\n---\nBody\n",
        )

        changed = vault.update_frontmatter(path, {"priority": "urgent"})

        assert changed == {}  # Nothing changed

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)

        with pytest.raises(FileNotFoundError):
            vault.update_frontmatter(tmp_path / "nonexistent.md", {"priority": "high"})

    def test_raises_on_no_frontmatter(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Actions",
            "test.md",
            "# Just a heading\nNo frontmatter here\n",
        )

        with pytest.raises(ValueError, match="No frontmatter"):
            vault.update_frontmatter(path, {"priority": "high"})

    def test_multiple_updates(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Projects",
            "test.md",
            "---\ntitle: Project\npriority: low\nstatus: todo\n---\nBody\n",
        )

        changed = vault.update_frontmatter(
            path, {"priority": "urgent", "status": "in-progress"}
        )

        assert changed == {"priority": "urgent", "status": "in-progress"}
        text = path.read_text(encoding="utf-8")
        assert "priority: urgent" in text
        assert "status: in-progress" in text

    def test_preserves_body_content(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        body = "\n# My Note\n\n- [ ] Todo item 1\n- [x] Done item\n\nParagraph.\n"
        path = _write_note(
            vault,
            "Actions",
            "test.md",
            f"---\ntitle: Test\npriority: low\n---{body}",
        )

        vault.update_frontmatter(path, {"priority": "high"})

        text = path.read_text(encoding="utf-8")
        assert body in text


# ---------------------------------------------------------------------------
# Vault.find_note
# ---------------------------------------------------------------------------


class TestFindNote:
    """Tests for the Vault.find_note method."""

    def test_find_in_specific_folder(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(vault, "Actions", "test.md", "---\ntitle: T\n---\n")

        found = vault.find_note("test.md", folder="Actions")
        assert found == path

    def test_find_across_folders(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(vault, "Projects", "proj.md", "---\ntitle: P\n---\n")

        found = vault.find_note("proj.md")
        assert found == path

    def test_not_found(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)

        assert vault.find_note("nonexistent.md") is None

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        # A file that exists outside the vault category folders
        secret = tmp_path / "vault" / "secret.md"
        secret.write_text("top secret", encoding="utf-8")

        # Traversal via folder argument
        assert vault.find_note("../../secret.md", folder="Actions") is None

    def test_path_traversal_blocked_no_folder(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        # The filename alone tries to escape
        assert vault.find_note("../../../etc/passwd") is None


# ---------------------------------------------------------------------------
# VaultEditAgent
# ---------------------------------------------------------------------------


class TestVaultEditAgent:
    """Tests for the VaultEditAgent.handle method."""

    def test_no_candidates_returns_message(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        agent = VaultEditAgent()
        context = MessageContext(
            raw_text="set priority to urgent",
            attachment_context=[],
            vault=vault,
            router_data={"search_terms": ["nonexistent"]},
        )

        result = agent.handle(context)

        assert result.response_text is not None
        assert "couldn't find" in result.response_text.lower()

    @patch.object(VaultEditAgent, "_plan_edits")
    def test_applies_planned_edits(self, mock_plan: MagicMock, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        path = _write_note(
            vault,
            "Actions",
            "my-action.md",
            "---\ntitle: My Action\npriority: low\n---\nBody\n",
        )

        mock_plan.return_value = (
            {
                "edits": [
                    {
                        "filename": "my-action.md",
                        "folder": "Actions",
                        "frontmatter_updates": {"priority": "1 - Urgent"},
                    }
                ],
                "summary": "Set priority to 1 - Urgent on 1 file.",
            },
            500,
        )

        agent = VaultEditAgent()
        context = MessageContext(
            raw_text="set priority to urgent",
            attachment_context=[],
            vault=vault,
            router_data={"search_terms": ["my-action"]},
        )

        result = agent.handle(context)

        assert result.tokens_used == 500
        assert result.response_text is not None
        assert "my-action.md" in result.response_text
        # Verify the file was actually modified
        text = path.read_text(encoding="utf-8")
        assert "priority: 1 - Urgent" in text

    @patch.object(VaultEditAgent, "_plan_edits")
    def test_handles_target_files_from_thread(
        self, mock_plan: MagicMock, tmp_path: Path
    ) -> None:
        """Simulates the 'set all those to urgent' scenario."""
        vault = _make_vault(tmp_path)
        _write_note(
            vault,
            "Projects",
            "Project A.md",
            "---\ntitle: Project A\npriority: medium\n---\nBody\n",
        )
        _write_note(
            vault,
            "Actions",
            "Action B.md",
            "---\ntitle: Action B\npriority: low\n---\nBody\n",
        )

        mock_plan.return_value = (
            {
                "edits": [
                    {
                        "filename": "Project A.md",
                        "folder": "Projects",
                        "frontmatter_updates": {"priority": "1 - Urgent"},
                    },
                    {
                        "filename": "Action B.md",
                        "folder": "Actions",
                        "frontmatter_updates": {"priority": "1 - Urgent"},
                    },
                ],
                "summary": "Set priority to 1 - Urgent on 2 files.",
            },
            800,
        )

        agent = VaultEditAgent()
        context = MessageContext(
            raw_text="set all those to urgent priority",
            attachment_context=[],
            vault=vault,
            router_data={
                "target_files": ["Project A.md", "Action B.md"],
                "edit_description": "set priority to urgent on all matching notes",
            },
            thread_history=[
                {"role": "user", "text": "show me todos in epics-containers"},
                {
                    "role": "assistant",
                    "text": "Found: Project A.md, Action B.md",
                },
            ],
        )

        result = agent.handle(context)

        assert result.response_text is not None
        assert "2" in result.response_text
        # Verify both files updated
        p = vault.base_path / "Projects" / "Project A.md"
        assert "priority: 1 - Urgent" in p.read_text(encoding="utf-8")
        a = vault.base_path / "Actions" / "Action B.md"
        assert "priority: 1 - Urgent" in a.read_text(encoding="utf-8")

    def test_format_results_ok(self) -> None:
        results = [
            {
                "filename": "test.md",
                "folder": "Actions",
                "status": "ok",
                "changed": {"priority": "1 - Urgent"},
            }
        ]
        text = VaultEditAgent._format_results(results, "Updated 1 file.")
        assert "Updated 1 file" in text
        assert "test.md" in text
        assert "priority→1 - Urgent" in text

    def test_format_results_mixed(self) -> None:
        results = [
            {
                "filename": "ok.md",
                "folder": "Actions",
                "status": "ok",
                "changed": {"priority": "1 - Urgent"},
            },
            {"filename": "bad.md", "status": "not_found"},
        ]
        text = VaultEditAgent._format_results(results, "Batch edit.")
        assert "1 file(s)" in text  # updated
        assert "1 file(s) could not" in text
        assert "bad.md" in text

    @patch.object(VaultEditAgent, "_plan_edits")
    def test_bulk_edit_cap_rejects_large_batch(
        self, mock_plan: MagicMock, tmp_path: Path
    ) -> None:
        """Edits exceeding MAX_BULK_EDITS are refused."""
        from brain.agents.vault_edit import MAX_BULK_EDITS

        vault = _make_vault(tmp_path)
        # Create enough notes so candidates are found
        for i in range(MAX_BULK_EDITS + 5):
            _write_note(
                vault,
                "Actions",
                f"note-{i}.md",
                f"---\ntitle: Note {i}\npriority: low\n---\nBody\n",
            )

        # Gemini "plans" more edits than the cap allows
        mock_plan.return_value = (
            {
                "edits": [
                    {
                        "filename": f"note-{i}.md",
                        "folder": "Actions",
                        "frontmatter_updates": {"priority": "1 - Urgent"},
                    }
                    for i in range(MAX_BULK_EDITS + 5)
                ],
                "summary": f"Set priority on {MAX_BULK_EDITS + 5} files.",
            },
            600,
        )

        agent = VaultEditAgent()
        context = MessageContext(
            raw_text="set everything to urgent",
            attachment_context=[],
            vault=vault,
            router_data={"search_terms": ["note"]},
        )

        result = agent.handle(context)

        assert result.response_text is not None
        assert "safety limit" in result.response_text.lower()
        # Verify NO files were actually modified
        for i in range(MAX_BULK_EDITS + 5):
            path = vault.base_path / "Actions" / f"note-{i}.md"
            assert "priority: low" in path.read_text(encoding="utf-8")
