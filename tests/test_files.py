"""
Tests for file tools:
- FileService path validation (security)
- FileSearchTool.execute()
- FileReadTool.execute()
- FileListTool.execute()
- FileWriteTool.execute()
- FileDeleteTool.execute() (restricted)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.tools.file_tool import (
    FileDeleteTool,
    FileListTool,
    FilePdfTool,
    FileReadTool,
    FileSearchTool,
    FileService,
    FileWriteTool,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def file_service(tmp_path: Path) -> FileService:
    """FileService scoped to tmp_path for safety."""
    return FileService(
        allowed_roots=[str(tmp_path)],
        max_file_size_mb=0.01,  # 10KB limit for tests
        max_results=10,
    )


@pytest.fixture
def populated_dir(tmp_path: Path) -> Path:
    """Create a directory with test files."""
    # Files
    (tmp_path / "readme.md").write_text("# Hello\nThis is a test file.")
    (tmp_path / "script.py").write_text("print('hello')\nprint('world')")
    (tmp_path / "data.csv").write_text("name,age\nAlice,30\nBob,25")
    (tmp_path / ".hidden").write_text("secret")

    # Subdirectory
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content")

    return tmp_path


# =========================================================================
# FileService — path validation
# =========================================================================


class TestFileServiceValidation:
    """Test FileService path validation and security."""

    def test_valid_path_inside_root(self, file_service: FileService, tmp_path: Path) -> None:
        ok, p, err = file_service.validate_path(str(tmp_path / "test.txt"))
        assert ok is True
        assert p is not None
        assert err == ""

    def test_reject_path_outside_root(self, file_service: FileService) -> None:
        ok, p, err = file_service.validate_path("C:/Windows/System32/cmd.exe")
        assert ok is False
        assert "Access denied" in err or "outside allowed" in err

    def test_reject_path_traversal(self, file_service: FileService, tmp_path: Path) -> None:
        ok, p, err = file_service.validate_path(str(tmp_path / ".." / ".." / "etc"))
        # After resolution, this should be outside allowed roots
        assert ok is False

    def test_reject_system_directory(self, tmp_path: Path) -> None:
        """Even if somehow under allowed root, block system dir names."""
        # Create a dir named "windows" under tmp_path
        win_dir = tmp_path / "Windows"
        win_dir.mkdir()
        service = FileService(allowed_roots=[str(tmp_path)])
        ok, p, err = service.validate_path(str(win_dir / "test.txt"))
        assert ok is False
        assert "system directory" in err.lower()

    def test_reject_sensitive_file_for_read(self, file_service: FileService, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=123")
        ok, p, err = file_service.validate_path_for_read(str(env_file))
        assert ok is False
        assert "sensitive" in err.lower()

    def test_allow_normal_file_for_read(self, file_service: FileService, tmp_path: Path) -> None:
        normal = tmp_path / "notes.txt"
        normal.write_text("hello")
        ok, p, err = file_service.validate_path_for_read(str(normal))
        assert ok is True


# =========================================================================
# FileSearchTool
# =========================================================================


class TestFileSearchTool:
    """Test FileSearchTool.execute()."""

    @pytest.mark.asyncio
    async def test_search_by_extension(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileSearchTool(file_service)
        result = await tool.execute(query="*.py", path=str(populated_dir))
        assert result.success is True
        assert "script.py" in result.data

    @pytest.mark.asyncio
    async def test_search_by_name(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileSearchTool(file_service)
        result = await tool.execute(query="readme", path=str(populated_dir))
        assert result.success is True
        assert "readme.md" in result.data

    @pytest.mark.asyncio
    async def test_search_nested(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileSearchTool(file_service)
        result = await tool.execute(query="nested", path=str(populated_dir))
        assert result.success is True
        assert "nested.txt" in result.data

    @pytest.mark.asyncio
    async def test_search_no_results(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileSearchTool(file_service)
        result = await tool.execute(query="nonexistent_xyz", path=str(populated_dir))
        assert result.success is True
        assert "No files" in result.data

    @pytest.mark.asyncio
    async def test_search_outside_root(self, file_service: FileService) -> None:
        tool = FileSearchTool(file_service)
        result = await tool.execute(query="*", path="C:/Windows")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_search_requires_query(self, file_service: FileService) -> None:
        tool = FileSearchTool(file_service)
        result = await tool.execute()
        assert result.success is False

    def test_definition(self, file_service: FileService) -> None:
        tool = FileSearchTool(file_service)
        d = tool.definition
        assert d.name == "file_search"
        schema = d.to_anthropic_schema()
        assert "query" in schema["input_schema"]["properties"]


# =========================================================================
# FileReadTool
# =========================================================================


class TestFileReadTool:
    """Test FileReadTool.execute()."""

    @pytest.mark.asyncio
    async def test_read_text_file(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileReadTool(file_service)
        result = await tool.execute(path=str(populated_dir / "readme.md"))
        assert result.success is True
        assert "Hello" in result.data
        assert "readme.md" in result.data

    @pytest.mark.asyncio
    async def test_read_with_line_numbers(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileReadTool(file_service)
        result = await tool.execute(path=str(populated_dir / "script.py"))
        assert result.success is True
        assert "1 |" in result.data
        assert "2 |" in result.data

    @pytest.mark.asyncio
    async def test_read_max_lines(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        big_file = tmp_path / "big.txt"
        big_file.write_text("\n".join(f"line {i}" for i in range(100)))
        tool = FileReadTool(file_service)
        result = await tool.execute(path=str(big_file), max_lines=5)
        assert result.success is True
        assert "showing first 5" in result.data

    @pytest.mark.asyncio
    async def test_read_file_too_large(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        # Service has 10KB limit
        big = tmp_path / "huge.bin"
        big.write_bytes(b"x" * 20_000)
        tool = FileReadTool(file_service)
        result = await tool.execute(path=str(big))
        assert result.success is False
        assert "too large" in (result.error or "")

    @pytest.mark.asyncio
    async def test_read_nonexistent(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileReadTool(file_service)
        result = await tool.execute(path=str(tmp_path / "nope.txt"))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_read_sensitive_file(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text("{}")
        tool = FileReadTool(file_service)
        result = await tool.execute(path=str(creds))
        assert result.success is False
        assert "sensitive" in (result.error or "").lower()

    def test_definition(self, file_service: FileService) -> None:
        tool = FileReadTool(file_service)
        d = tool.definition
        assert d.name == "file_read"


# =========================================================================
# FileListTool
# =========================================================================


class TestFileListTool:
    """Test FileListTool.execute()."""

    @pytest.mark.asyncio
    async def test_list_directory(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileListTool(file_service)
        result = await tool.execute(path=str(populated_dir))
        assert result.success is True
        assert "readme.md" in result.data
        assert "script.py" in result.data
        assert "subdir" in result.data

    @pytest.mark.asyncio
    async def test_list_hides_hidden(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileListTool(file_service)
        result = await tool.execute(path=str(populated_dir), show_hidden=False)
        assert result.success is True
        assert ".hidden" not in result.data

    @pytest.mark.asyncio
    async def test_list_shows_hidden(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileListTool(file_service)
        result = await tool.execute(path=str(populated_dir), show_hidden=True)
        assert result.success is True
        assert ".hidden" in result.data

    @pytest.mark.asyncio
    async def test_list_outside_root(self, file_service: FileService) -> None:
        tool = FileListTool(file_service)
        result = await tool.execute(path="C:/Windows")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_list_not_a_dir(
        self, file_service: FileService, populated_dir: Path
    ) -> None:
        tool = FileListTool(file_service)
        result = await tool.execute(path=str(populated_dir / "readme.md"))
        assert result.success is False
        assert "Not a directory" in (result.error or "")

    def test_definition(self, file_service: FileService) -> None:
        tool = FileListTool(file_service)
        d = tool.definition
        assert d.name == "file_list"


# =========================================================================
# FileWriteTool
# =========================================================================


class TestFileWriteTool:
    """Test FileWriteTool.execute()."""

    @pytest.mark.asyncio
    async def test_write_new_file(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileWriteTool(file_service)
        target = tmp_path / "new_file.txt"
        result = await tool.execute(path=str(target), content="Hello World")
        assert result.success is True
        assert target.read_text() == "Hello World"

    @pytest.mark.asyncio
    async def test_write_creates_dirs(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileWriteTool(file_service)
        target = tmp_path / "a" / "b" / "c" / "deep.txt"
        result = await tool.execute(path=str(target), content="deep")
        assert result.success is True
        assert target.read_text() == "deep"

    @pytest.mark.asyncio
    async def test_append_mode(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileWriteTool(file_service)
        target = tmp_path / "log.txt"
        target.write_text("line1\n")
        result = await tool.execute(
            path=str(target), content="line2\n", mode="append"
        )
        assert result.success is True
        assert target.read_text() == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_write_outside_root(self, file_service: FileService) -> None:
        tool = FileWriteTool(file_service)
        result = await tool.execute(path="C:/Windows/hack.txt", content="bad")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_sensitive_file(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileWriteTool(file_service)
        result = await tool.execute(
            path=str(tmp_path / ".env"), content="SECRET=123"
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_requires_content(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileWriteTool(file_service)
        result = await tool.execute(path=str(tmp_path / "empty.txt"), content="")
        assert result.success is False

    def test_definition(self, file_service: FileService) -> None:
        tool = FileWriteTool(file_service)
        d = tool.definition
        assert d.name == "file_write"


# =========================================================================
# FileDeleteTool — RESTRICTED
# =========================================================================


class TestFileDeleteTool:
    """Test FileDeleteTool.execute() — must be restricted."""

    @pytest.mark.asyncio
    async def test_delete_with_confirm(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        target = tmp_path / "to_delete.txt"
        target.write_text("bye")
        tool = FileDeleteTool(file_service)
        result = await tool.execute(path=str(target), confirm=True)
        assert result.success is True
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_delete_without_confirm(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        target = tmp_path / "keep.txt"
        target.write_text("keep me")
        tool = FileDeleteTool(file_service)
        result = await tool.execute(path=str(target), confirm=False)
        assert result.success is False
        assert target.exists()  # File NOT deleted

    @pytest.mark.asyncio
    async def test_delete_directory_blocked(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        tool = FileDeleteTool(file_service)
        result = await tool.execute(path=str(subdir), confirm=True)
        assert result.success is False
        assert subdir.exists()

    @pytest.mark.asyncio
    async def test_delete_sensitive_file_blocked(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text("{}")
        tool = FileDeleteTool(file_service)
        result = await tool.execute(path=str(creds), confirm=True)
        assert result.success is False
        assert creds.exists()

    @pytest.mark.asyncio
    async def test_delete_outside_root(self, file_service: FileService) -> None:
        tool = FileDeleteTool(file_service)
        result = await tool.execute(path="C:/important.txt", confirm=True)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FileDeleteTool(file_service)
        result = await tool.execute(path=str(tmp_path / "nope.txt"), confirm=True)
        assert result.success is False

    def test_definition_has_restriction_warning(
        self, file_service: FileService
    ) -> None:
        tool = FileDeleteTool(file_service)
        d = tool.definition
        assert d.name == "file_delete"
        assert "RESTRICTED" in d.description
        assert "EXPLICITLY" in d.description


# =========================================================================
# FilePdfTool
# =========================================================================


class TestFilePdfTool:
    """Test FilePdfTool.execute()."""

    @pytest.mark.asyncio
    async def test_create_simple_pdf(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FilePdfTool(file_service)
        target = tmp_path / "report.pdf"
        result = await tool.execute(
            path=str(target),
            content="# Hello World\n\nThis is a test document.",
            title="Test Report",
        )
        assert result.success is True
        assert target.exists()
        assert target.stat().st_size > 0
        assert "report.pdf" in result.data

    @pytest.mark.asyncio
    async def test_create_pdf_with_formatting(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FilePdfTool(file_service)
        target = tmp_path / "formatted.pdf"
        content = (
            "# Main Title\n"
            "## Section One\n"
            "This is **bold** and *italic* text.\n"
            "- Bullet one\n"
            "- Bullet two\n"
            "1. First item\n"
            "2. Second item\n"
            "---\n"
            "### Subsection\n"
            "Final paragraph."
        )
        result = await tool.execute(path=str(target), content=content)
        assert result.success is True
        assert target.exists()

    @pytest.mark.asyncio
    async def test_create_pdf_cyrillic(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FilePdfTool(file_service)
        target = tmp_path / "cyrillic.pdf"
        result = await tool.execute(
            path=str(target),
            content="# Привет мир\n\nЭто тестовый документ на русском языке.",
            title="Тестовый отчёт",
        )
        assert result.success is True
        assert target.exists()

    @pytest.mark.asyncio
    async def test_auto_adds_pdf_extension(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FilePdfTool(file_service)
        target = tmp_path / "noext"
        result = await tool.execute(
            path=str(target), content="Some content"
        )
        assert result.success is True
        # Should have created noext.pdf
        assert (tmp_path / "noext.pdf").exists()

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FilePdfTool(file_service)
        target = tmp_path / "a" / "b" / "deep.pdf"
        result = await tool.execute(
            path=str(target), content="Deep content"
        )
        assert result.success is True
        assert target.exists()

    @pytest.mark.asyncio
    async def test_requires_content(
        self, file_service: FileService, tmp_path: Path
    ) -> None:
        tool = FilePdfTool(file_service)
        result = await tool.execute(
            path=str(tmp_path / "empty.pdf"), content=""
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_outside_root_blocked(self, file_service: FileService) -> None:
        tool = FilePdfTool(file_service)
        result = await tool.execute(
            path="C:/Windows/hack.pdf", content="bad"
        )
        assert result.success is False

    def test_definition(self, file_service: FileService) -> None:
        tool = FilePdfTool(file_service)
        d = tool.definition
        assert d.name == "file_pdf"
        assert "PDF" in d.description
