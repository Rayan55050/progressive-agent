"""
File tools — search, read, list, write, delete, open, send, PDF files on the local machine.

Security:
- All paths validated against allowed_roots (configurable)
- System directories are blocked (Windows, System32, Program Files)
- Sensitive files blocked (.env, credentials, tokens)
- Delete is ONLY allowed when user explicitly requests it
- Path traversal (..) is blocked
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Directories that must never be touched
BLOCKED_DIRS = {
    "windows", "system32", "syswow64", "program files",
    "program files (x86)", "programdata", "$recycle.bin",
    "system volume information", "recovery",
}

# File name patterns that must never be read/written
SENSITIVE_PATTERNS = {
    ".env", "credentials", "token", "secret", "private_key",
    "id_rsa", "id_ed25519", ".pem", ".key",
}


def _human_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"


def _file_info(p: Path) -> dict[str, Any]:
    """Get basic file/directory info."""
    try:
        st = p.stat()
        return {
            "name": p.name,
            "path": str(p),
            "type": "dir" if p.is_dir() else "file",
            "size": _human_size(st.st_size) if p.is_file() else "-",
            "size_bytes": st.st_size if p.is_file() else 0,
            "modified": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M"),
        }
    except (OSError, PermissionError):
        return {
            "name": p.name,
            "path": str(p),
            "type": "unknown",
            "size": "?",
            "size_bytes": 0,
            "modified": "?",
        }


# ---------------------------------------------------------------------------
# FileService — shared validation & config
# ---------------------------------------------------------------------------


class FileService:
    """Shared service for file operations with security validation."""

    def __init__(
        self,
        allowed_roots: list[str] | None = None,
        max_file_size_mb: float = 1.0,
        max_results: int = 20,
    ) -> None:
        if allowed_roots:
            self._allowed_roots = [
                Path(r).resolve() for r in allowed_roots
            ]
        else:
            # Default: user home directory
            self._allowed_roots = [Path.home().resolve()]

        self._max_file_size = int(max_file_size_mb * 1024 * 1024)
        self._max_results = max_results

        logger.info(
            "FileService initialized: roots=%s, max_size=%s",
            [str(r) for r in self._allowed_roots],
            _human_size(self._max_file_size),
        )

    def validate_path(self, path_str: str) -> tuple[bool, Path | None, str]:
        """Validate a path against security rules.

        Returns:
            (is_valid, resolved_path, error_message)
        """
        try:
            p = Path(path_str).resolve()
        except (ValueError, OSError) as e:
            return False, None, f"Invalid path: {e}"

        logger.debug("validate_path: input='%s' resolved='%s'", path_str, p)

        # Check path traversal (already resolved, but double-check)
        if ".." in Path(path_str).parts:
            return False, None, "Path traversal (..) is not allowed"

        # Check allowed roots
        if not any(self._is_under(p, root) for root in self._allowed_roots):
            roots_str = ", ".join(str(r) for r in self._allowed_roots)
            return False, None, (
                f"Access denied: path is outside allowed directories ({roots_str})"
            )

        # Check blocked system directories
        parts_lower = {part.lower() for part in p.parts}
        blocked = parts_lower & BLOCKED_DIRS
        if blocked:
            return False, None, (
                f"Access denied: system directory ({', '.join(blocked)})"
            )

        return True, p, ""

    def validate_path_for_read(self, path_str: str) -> tuple[bool, Path | None, str]:
        """Validate path for reading — also checks sensitive file patterns."""
        ok, p, err = self.validate_path(path_str)
        if not ok:
            return ok, p, err

        assert p is not None
        # Check sensitive files
        name_lower = p.name.lower()
        for pattern in SENSITIVE_PATTERNS:
            if pattern in name_lower:
                return False, None, (
                    f"Access denied: sensitive file ({p.name})"
                )

        return True, p, ""

    def validate_source_path(self, path_str: str) -> tuple[bool, Path | None, str]:
        """Validate source path for copying — allows temp directories.

        Unlike validate_path, this method allows reading from temp directories
        (for Telegram file downloads) but still validates against allowed_roots
        for non-temp paths.

        Returns:
            (is_valid, resolved_path, error_message)
        """
        try:
            p = Path(path_str).resolve()
        except (ValueError, OSError) as e:
            return False, None, f"Invalid path: {e}"

        # Check path traversal
        if ".." in Path(path_str).parts:
            return False, None, "Path traversal (..) is not allowed"

        # Allow temp directories (used by Telegram downloads)
        import tempfile
        temp_dir = Path(tempfile.gettempdir()).resolve()
        if self._is_under(p, temp_dir):
            logger.debug("validate_source_path: allowing temp path %s", p)
            return True, p, ""

        # For non-temp paths, validate against allowed roots
        if not any(self._is_under(p, root) for root in self._allowed_roots):
            roots_str = ", ".join(str(r) for r in self._allowed_roots)
            return False, None, (
                f"Access denied: source path is outside allowed directories "
                f"and not in temp directory ({roots_str})"
            )

        # Check blocked system directories
        parts_lower = {part.lower() for part in p.parts}
        blocked = parts_lower & BLOCKED_DIRS
        if blocked:
            return False, None, (
                f"Access denied: system directory ({', '.join(blocked)})"
            )

        # Check sensitive files
        name_lower = p.name.lower()
        for pattern in SENSITIVE_PATTERNS:
            if pattern in name_lower:
                return False, None, (
                    f"Access denied: sensitive file ({p.name})"
                )

        return True, p, ""

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        """Check if path is under root directory."""
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


# ---------------------------------------------------------------------------
# FileSearchTool
# ---------------------------------------------------------------------------


class FileSearchTool:
    """Search for files and folders by name/pattern."""

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_search",
            description=(
                "Search for files and folders by name or glob pattern. "
                "Examples: '*.py', 'README', 'report*.pdf'. "
                "Returns matching paths with size and modification date."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description=(
                        "Search pattern — file name, partial name, or glob "
                        "(e.g. '*.py', 'budget*', 'notes.txt')"
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="path",
                    type="string",
                    description=(
                        "Directory to search in. Defaults to user home."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of results (default 20)",
                    required=False,
                    default=20,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query: str = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, error="query is required")

        search_path = kwargs.get("path", str(Path.home()))
        max_results = int(kwargs.get("max_results", self._service._max_results))

        ok, root, err = self._service.validate_path(search_path)
        if not ok:
            return ToolResult(success=False, error=err)

        assert root is not None
        if not root.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {root}")

        # If query doesn't contain glob chars, wrap it as *query*
        if "*" not in query and "?" not in query:
            pattern = f"*{query}*"
        else:
            pattern = query

        # Run rglob in a thread to avoid blocking the event loop.
        # Limit total files scanned to prevent hanging on huge directories.
        max_scan = 50_000  # stop scanning after this many entries

        def _search() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            scanned = 0
            try:
                for p in root.rglob(pattern):
                    scanned += 1
                    if scanned > max_scan:
                        break
                    # Skip blocked dirs
                    parts_lower = {part.lower() for part in p.parts}
                    if parts_lower & BLOCKED_DIRS:
                        continue
                    results.append(_file_info(p))
                    if len(results) >= max_results:
                        break
            except PermissionError:
                pass
            except Exception as e:
                logger.warning("Search error during rglob: %s", e)
            return results

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(_search),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=(
                    f"Search timed out in {root}. "
                    "Try a more specific path (e.g. Desktop, Documents)."
                ),
            )

        if not results:
            return ToolResult(
                success=True,
                data=f"No files matching '{query}' found in {root}",
            )

        # Format as readable text
        lines = [f"Found {len(results)} result(s) in {root}:\n"]
        for item in results:
            icon = "\U0001f4c1" if item["type"] == "dir" else "\U0001f4c4"
            lines.append(
                f"{icon} {item['name']}  ({item['size']}, {item['modified']})\n"
                f"   {item['path']}"
            )

        return ToolResult(success=True, data="\n".join(lines))


# ---------------------------------------------------------------------------
# FileReadTool
# ---------------------------------------------------------------------------


class FileReadTool:
    """Read the contents of a text file or extract text from PDF."""

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_read",
            description=(
                "Read the contents of a file. Works with text files AND PDFs. "
                "For text files: returns content with line numbers. "
                "For PDF files: extracts all text from all pages. "
                "Limited to 10MB for PDFs, 1MB for text files."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Full path to the file to read",
                    required=True,
                ),
                ToolParameter(
                    name="max_lines",
                    type="integer",
                    description="Maximum lines to return (default 200)",
                    required=False,
                    default=200,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs.get("path", "")
        if not path_str:
            return ToolResult(success=False, error="path is required")

        max_lines = int(kwargs.get("max_lines", 200))

        ok, p, err = self._service.validate_path_for_read(path_str)
        if not ok:
            # Allow reading temp files (from Telegram downloads) but
            # still block sensitive file patterns
            import tempfile as _tf
            p = Path(path_str).resolve()
            temp_root = Path(_tf.gettempdir()).resolve()
            is_temp = False
            try:
                p.relative_to(temp_root)
                is_temp = True
            except ValueError:
                pass
            if not is_temp or not p.is_file():
                return ToolResult(success=False, error=err)
            # Check sensitive patterns even for temp files
            name_lower = p.name.lower()
            for pattern in SENSITIVE_PATTERNS:
                if pattern in name_lower:
                    return ToolResult(success=False, error=err)

        assert p is not None
        if not p.is_file():
            return ToolResult(success=False, error=f"Not a file: {p}")

        # Check file size
        try:
            size = p.stat().st_size
        except OSError as e:
            return ToolResult(success=False, error=f"Cannot access file: {e}")

        # PDF files — use pypdf for text extraction
        if p.suffix.lower() == ".pdf":
            return await self._read_pdf(p, size, max_lines)

        # Text files
        if size > self._service._max_file_size:
            return ToolResult(
                success=False,
                error=(
                    f"File too large: {_human_size(size)} "
                    f"(limit: {_human_size(self._service._max_file_size)})"
                ),
            )

        # Read file
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = p.read_text(encoding="latin-1")
            except Exception as e:
                return ToolResult(
                    success=False, error=f"Cannot decode file: {e}"
                )
        except OSError as e:
            return ToolResult(success=False, error=f"Read error: {e}")

        lines = text.splitlines()
        total_lines = len(lines)
        truncated = total_lines > max_lines
        if truncated:
            lines = lines[:max_lines]

        # Format with line numbers
        numbered = "\n".join(
            f"{i + 1:4d} | {line}" for i, line in enumerate(lines)
        )

        info = _file_info(p)
        header = (
            f"File: {p.name} ({info['size']}, {info['modified']})\n"
            f"Lines: {total_lines}"
        )
        if truncated:
            header += f" (showing first {max_lines})"
        header += "\n" + "-" * 40

        return ToolResult(success=True, data=f"{header}\n{numbered}")

    async def _read_pdf(self, p: Path, size: int, max_lines: int) -> ToolResult:
        """Extract text from a PDF file using pypdf."""
        max_pdf_size = 10 * 1024 * 1024  # 10MB limit for PDFs
        if size > max_pdf_size:
            return ToolResult(
                success=False,
                error=f"PDF too large: {_human_size(size)} (limit: 10 MB)",
            )

        def _extract() -> tuple[str, int]:
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            page_count = len(reader.pages)
            pages = []
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"--- Page {page_num + 1} ---\n{text.strip()}")
            return "\n\n".join(pages), page_count

        try:
            text, page_count = await asyncio.to_thread(_extract)
        except Exception as e:
            return ToolResult(success=False, error=f"PDF read error: {e}")

        if not text.strip():
            return ToolResult(
                success=True,
                data=(
                    f"PDF: {p.name} ({_human_size(size)}, {page_count} pages)\n"
                    "No extractable text found (possibly scanned/image-based PDF)."
                ),
            )

        lines = text.splitlines()
        total_lines = len(lines)
        truncated = total_lines > max_lines
        if truncated:
            lines = lines[:max_lines]

        content = "\n".join(lines)
        header = (
            f"PDF: {p.name} ({_human_size(size)}, {page_count} pages)\n"
            f"Lines: {total_lines}"
        )
        if truncated:
            header += f" (showing first {max_lines})"
        header += "\n" + "-" * 40

        return ToolResult(success=True, data=f"{header}\n{content}")


# ---------------------------------------------------------------------------
# FileListTool
# ---------------------------------------------------------------------------


class FileListTool:
    """List contents of a directory."""

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_list",
            description=(
                "List files and folders in a directory. "
                "Shows name, type, size, and modification date."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description=(
                        "Directory path to list. Defaults to user home."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="show_hidden",
                    type="boolean",
                    description="Show hidden files (default false)",
                    required=False,
                    default=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str = kwargs.get("path", str(Path.home()))
        show_hidden = bool(kwargs.get("show_hidden", False))

        ok, p, err = self._service.validate_path(path_str)
        if not ok:
            return ToolResult(success=False, error=err)

        assert p is not None
        if not p.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {p}")

        items: list[dict[str, Any]] = []
        try:
            for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if not show_hidden and child.name.startswith("."):
                    continue
                items.append(_file_info(child))
        except PermissionError:
            return ToolResult(
                success=False, error=f"Permission denied: {p}"
            )
        except OSError as e:
            return ToolResult(success=False, error=f"List error: {e}")

        if not items:
            return ToolResult(
                success=True, data=f"Directory is empty: {p}"
            )

        # Format as readable table
        lines = [f"Contents of {p} ({len(items)} items):\n"]
        for item in items:
            icon = "\U0001f4c1" if item["type"] == "dir" else "\U0001f4c4"
            size_str = item["size"].rjust(10) if item["type"] == "file" else "       <DIR>"
            lines.append(
                f"{icon} {item['name']:<40s} {size_str}  {item['modified']}"
            )

        return ToolResult(success=True, data="\n".join(lines))


# ---------------------------------------------------------------------------
# FileWriteTool
# ---------------------------------------------------------------------------


class FileWriteTool:
    """Write or append content to a file."""

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_write",
            description=(
                "Create or write content to a file. "
                "Creates parent directories if needed. "
                "Use mode='append' to add to existing file."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Full path for the file to write",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Text content to write",
                    required=True,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'write' (overwrite) or 'append' (add to end)",
                    required=False,
                    default="write",
                    enum=["write", "append"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs.get("path", "")
        content: str = kwargs.get("content", "")
        mode: str = kwargs.get("mode", "write")

        if not path_str:
            return ToolResult(success=False, error="path is required")
        if not content:
            return ToolResult(success=False, error="content is required")

        ok, p, err = self._service.validate_path(path_str)
        if not ok:
            return ToolResult(success=False, error=err)

        assert p is not None

        # Check sensitive file patterns
        name_lower = p.name.lower()
        for pattern in SENSITIVE_PATTERNS:
            if pattern in name_lower:
                return ToolResult(
                    success=False,
                    error=f"Cannot write to sensitive file: {p.name}",
                )

        # Create parent directories
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ToolResult(
                success=False, error=f"Cannot create directory: {e}"
            )

        # Write file
        try:
            if mode == "append":
                with open(p, "a", encoding="utf-8") as f:
                    f.write(content)
                action = "Appended to"
            else:
                p.write_text(content, encoding="utf-8")
                action = "Written to"
        except OSError as e:
            return ToolResult(success=False, error=f"Write error: {e}")

        size = p.stat().st_size
        logger.info("File written: %s (%s)", p, _human_size(size))

        return ToolResult(
            success=True,
            data=f"{action} {p.name} ({_human_size(size)})\nPath: {p}",
        )


# ---------------------------------------------------------------------------
# FileDeleteTool — RESTRICTED
# ---------------------------------------------------------------------------


class FileDeleteTool:
    """Delete a file. ONLY use when user EXPLICITLY asks to delete."""

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_delete",
            description=(
                "RESTRICTED: Delete a file. "
                "ONLY use this tool when the user EXPLICITLY and DIRECTLY "
                "asks to delete a specific file. NEVER delete files on your own "
                "initiative, as part of cleanup, or as a side effect of other operations. "
                "Cannot delete directories — only individual files."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Full path to the file to delete",
                    required=True,
                ),
                ToolParameter(
                    name="confirm",
                    type="boolean",
                    description=(
                        "Must be true to confirm deletion. "
                        "Set to true ONLY if user explicitly confirmed."
                    ),
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs.get("path", "")
        confirm: bool = bool(kwargs.get("confirm", False))

        if not path_str:
            return ToolResult(success=False, error="path is required")

        if not confirm:
            return ToolResult(
                success=False,
                error="Deletion not confirmed. Set confirm=true only if user explicitly asked to delete.",
            )

        ok, p, err = self._service.validate_path(path_str)
        if not ok:
            return ToolResult(success=False, error=err)

        assert p is not None

        if not p.exists():
            return ToolResult(success=False, error=f"File not found: {p}")

        if p.is_dir():
            return ToolResult(
                success=False,
                error="Cannot delete directories. Only individual files can be deleted.",
            )

        # Check sensitive files
        name_lower = p.name.lower()
        for pattern in SENSITIVE_PATTERNS:
            if pattern in name_lower:
                return ToolResult(
                    success=False,
                    error=f"Cannot delete sensitive file: {p.name}",
                )

        # Delete
        try:
            size = p.stat().st_size
            p.unlink()
        except OSError as e:
            return ToolResult(success=False, error=f"Delete error: {e}")

        logger.warning(
            "FILE DELETED by user request: %s (%s)", p, _human_size(size)
        )

        return ToolResult(
            success=True,
            data=f"Deleted: {p.name} ({_human_size(size)})\nPath: {p}",
        )


# ---------------------------------------------------------------------------
# FileOpenTool — open file/folder on the local machine
# ---------------------------------------------------------------------------


class FileOpenTool:
    """Manage apps and open files on the user's computer.

    Actions:
    - open: launch app by name (Desktop shortcuts) or open file by path
    - close: kill app process by name
    - list: show running apps or available Desktop shortcuts
    - recycle_bin: check or empty the recycle bin
    """

    _DESKTOP_DIRS: list[str] = [
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop"),
    ]

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_open",
            description=(
                "Manage apps and files on the user's computer. "
                "Actions: open (launch app or open file), close (kill app), "
                "list (show running/available apps), "
                "recycle_bin (check or empty the recycle bin). "
                "For apps: pass just the name (Discord, Telegram, Obsidian). "
                "For files: pass the full path. "
                "For recycle bin: use action='recycle_bin' with path='check' or path='empty'."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description=(
                        "App name (e.g. 'Discord', 'Opera GX'), full file/folder path, "
                        "or for recycle_bin action: 'check' (show contents) or 'empty' (clear bin)."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "Action: 'open' (launch/open, default), "
                        "'close' (kill app process), "
                        "'list' (show running apps or Desktop shortcuts), "
                        "'recycle_bin' (check or empty the recycle bin)"
                    ),
                    required=False,
                    default="open",
                ),
            ],
        )

    def _find_desktop_shortcut(self, app_name: str) -> Path | None:
        """Find a .lnk shortcut on Desktop matching the app name."""
        name_lower = app_name.lower().strip()
        for desktop_dir in self._DESKTOP_DIRS:
            desktop = Path(desktop_dir)
            if not desktop.exists():
                continue
            for lnk in desktop.glob("*.lnk"):
                if lnk.stem.lower() == name_lower:
                    return lnk
            for lnk in desktop.glob("*.lnk"):
                if name_lower in lnk.stem.lower():
                    return lnk
        return None

    def _get_desktop_apps(self) -> list[str]:
        """Get list of app names from Desktop shortcuts."""
        apps = []
        for desktop_dir in self._DESKTOP_DIRS:
            desktop = Path(desktop_dir)
            if desktop.exists():
                apps.extend(lnk.stem for lnk in desktop.glob("*.lnk"))
        return sorted(set(apps))

    @staticmethod
    def _shell_open(path: Path) -> None:
        """Open via 'cmd /c start' — works from background processes."""
        import subprocess
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @staticmethod
    async def _find_processes(app_name: str) -> list[dict[str, str]]:
        """Find running processes matching app name."""
        import subprocess as sp
        name_lower = app_name.lower().strip()
        found: list[dict[str, str]] = []
        try:
            result = sp.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
            )
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    proc_name = parts[0].strip('"')
                    pid = parts[1].strip('"')
                    # Match by process name (without .exe)
                    stem = proc_name.rsplit(".", 1)[0].lower()
                    if name_lower in stem or stem in name_lower:
                        found.append({"name": proc_name, "pid": pid})
        except Exception as e:
            logger.error("Process list failed: %s", e)
        return found

    @staticmethod
    async def _kill_processes(app_name: str) -> tuple[bool, str]:
        """Kill processes matching app name. Returns (success, message)."""
        import subprocess as sp
        name_lower = app_name.lower().strip()

        # First find matching processes
        procs = await FileOpenTool._find_processes(app_name)
        if not procs:
            return False, f"Процесс '{app_name}' не найден среди запущенных"

        # Kill each matching process
        killed = []
        for proc in procs:
            try:
                sp.run(
                    ["taskkill", "/PID", proc["pid"], "/F"],
                    capture_output=True, timeout=10,
                    creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
                )
                killed.append(proc["name"])
            except Exception:
                pass

        if killed:
            names = ", ".join(set(killed))
            return True, f"Закрыл: {names}"
        return False, f"Не удалось закрыть {app_name}"

    @staticmethod
    async def _list_running_apps() -> str:
        """List user-visible running apps (not system services)."""
        import subprocess as sp
        # Get processes with window titles (visible apps)
        try:
            result = sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
                 "Select-Object ProcessName, Id, MainWindowTitle | "
                 "Format-Table -AutoSize | Out-String -Width 200"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
            )
            output = result.stdout.strip()
            if output:
                return f"Запущенные приложения:\n\n{output}"
            return "Нет видимых приложений"
        except Exception as e:
            return f"Ошибка: {e}"

    # --- Recycle Bin operations (direct filesystem, NOT buggy COM) ---

    @staticmethod
    async def _recycle_bin_check() -> ToolResult:
        """Check recycle bin contents across all drives — direct filesystem scan."""
        import subprocess as sp

        # Use PowerShell script to avoid $_ escaping issues
        script = (
            '$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n'
            '$totalFiles = 0\n'
            '$details = @()\n'
            'foreach ($drive in (Get-PSDrive -PSProvider FileSystem)) {\n'
            '    $path = "$($drive.Root)`$Recycle.Bin\\$sid"\n'
            '    if (Test-Path $path) {\n'
            '        $items = Get-ChildItem $path -Force -ErrorAction SilentlyContinue | '
            'Where-Object { $_.Name -ne "desktop.ini" }\n'
            '        foreach ($item in $items) {\n'
            '            $totalFiles++\n'
            '            $size = if ($item.Length) { $item.Length } else { 0 }\n'
            '            $details += "$($drive.Root) | $($item.Name) | $size bytes | $($item.LastWriteTime)"\n'
            '        }\n'
            '    }\n'
            '}\n'
            'Write-Host "TOTAL:$totalFiles"\n'
            'foreach ($d in $details) { Write-Host "ITEM:$d" }\n'
        )

        try:
            result = sp.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
            )
            output = result.stdout.strip()
            total = 0
            items: list[str] = []
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("TOTAL:"):
                    total = int(line.split(":")[1])
                elif line.startswith("ITEM:"):
                    items.append(line[5:])

            if total == 0:
                return ToolResult(success=True, data="Корзина пустая (0 файлов на всех дисках)")

            details = "\n".join(f"  {item}" for item in items)
            # Count $R files (actual deleted files, not $I metadata)
            real_files = sum(1 for i in items if "| $R" in i)
            return ToolResult(
                success=True,
                data=f"В корзине {real_files} файл(ов) (всего записей: {total}):\n{details}",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Ошибка проверки корзины: {e}")

    @staticmethod
    async def _recycle_bin_empty() -> ToolResult:
        """Empty recycle bin across all drives — direct file deletion + verification."""
        import subprocess as sp

        # Step 1: Count before
        script_count = (
            '$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n'
            '$total = 0\n'
            'foreach ($drive in (Get-PSDrive -PSProvider FileSystem)) {\n'
            '    $path = "$($drive.Root)`$Recycle.Bin\\$sid"\n'
            '    if (Test-Path $path) {\n'
            '        $items = Get-ChildItem $path -Force -ErrorAction SilentlyContinue | '
            'Where-Object { $_.Name -ne "desktop.ini" }\n'
            '        $total += ($items | Measure-Object).Count\n'
            '    }\n'
            '}\n'
            'Write-Host $total\n'
        )

        try:
            before_result = sp.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script_count],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
            )
            before_count = int(before_result.stdout.strip() or "0")
        except Exception:
            before_count = -1

        if before_count == 0:
            return ToolResult(success=True, data="Корзина уже пустая — нечего очищать")

        # Step 2: Delete files directly from $Recycle.Bin
        script_delete = (
            '$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n'
            '$deleted = 0\n'
            '$failed = 0\n'
            'foreach ($drive in (Get-PSDrive -PSProvider FileSystem)) {\n'
            '    $path = "$($drive.Root)`$Recycle.Bin\\$sid"\n'
            '    if (Test-Path $path) {\n'
            '        Get-ChildItem $path -Force -ErrorAction SilentlyContinue | '
            'Where-Object { $_.Name -ne "desktop.ini" } | ForEach-Object {\n'
            '            try {\n'
            '                Remove-Item $_.FullName -Force -Recurse -ErrorAction Stop\n'
            '                $deleted++\n'
            '            } catch {\n'
            '                $failed++\n'
            '            }\n'
            '        }\n'
            '    }\n'
            '}\n'
            'Write-Host "DELETED:$deleted"\n'
            'Write-Host "FAILED:$failed"\n'
        )

        try:
            del_result = sp.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script_delete],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
            )
            del_output = del_result.stdout.strip()
            deleted = 0
            failed = 0
            for line in del_output.split("\n"):
                line = line.strip()
                if line.startswith("DELETED:"):
                    deleted = int(line.split(":")[1])
                elif line.startswith("FAILED:"):
                    failed = int(line.split(":")[1])
        except Exception as e:
            return ToolResult(success=False, error=f"Ошибка очистки корзины: {e}")

        # Step 3: VERIFY — count again
        try:
            after_result = sp.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script_count],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
            )
            after_count = int(after_result.stdout.strip() or "0")
        except Exception:
            after_count = -1

        # Step 4: Return HONEST result
        if after_count == 0:
            msg = f"Корзина очищена! Удалено файлов: {deleted}"
            if failed > 0:
                msg += f" (не удалось удалить: {failed}, но корзина всё равно пустая)"
            return ToolResult(success=True, data=msg)
        elif after_count > 0:
            return ToolResult(
                success=False,
                error=(
                    f"Корзина НЕ полностью очищена! "
                    f"Было: {before_count}, удалено: {deleted}, осталось: {after_count}. "
                    f"Некоторые файлы заблокированы."
                ),
            )
        else:
            # Couldn't verify
            return ToolResult(
                success=True,
                data=f"Удалено {deleted} файлов. Не удалось проверить результат — проверь корзину вручную.",
            )

    def _is_app_name(self, path_str: str) -> bool:
        """Check if input looks like an app name (not a file path)."""
        return "\\" not in path_str and "/" not in path_str and ":" not in path_str

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs.get("path", "").strip()
        action: str = kwargs.get("action", "open").strip().lower()

        if not path_str and action not in ("list", "recycle_bin"):
            return ToolResult(success=False, error="path is required")

        # --- RECYCLE BIN: check or empty ---
        if action == "recycle_bin":
            sub = path_str.lower().strip()
            if sub in ("empty", "clear", "clean", "очистить", "очисти"):
                return await self._recycle_bin_empty()
            else:
                return await self._recycle_bin_check()

        # --- LIST: show running apps or Desktop shortcuts ---
        if action == "list":
            if path_str and path_str.lower() == "desktop":
                apps = self._get_desktop_apps()
                return ToolResult(
                    success=True,
                    data=f"Ярлыки на рабочем столе:\n" + "\n".join(f"  {a}" for a in apps),
                )
            output = await self._list_running_apps()
            return ToolResult(success=True, data=output)

        # --- CLOSE: kill app process ---
        if action == "close":
            success, msg = await self._kill_processes(path_str)
            logger.info("App close: %s -> %s", path_str, msg)
            return ToolResult(success=success, data=msg if success else None, error=msg if not success else None)

        # --- OPEN: launch app or open file ---
        if self._is_app_name(path_str):
            shortcut = self._find_desktop_shortcut(path_str)
            if shortcut:
                try:
                    self._shell_open(shortcut)
                except Exception as e:
                    return ToolResult(success=False, error=f"Cannot launch: {e}")
                logger.info("Launched app via Desktop shortcut: %s -> %s", path_str, shortcut)
                return ToolResult(
                    success=True,
                    data=f"Запустил {shortcut.stem} (ярлык с рабочего стола)",
                )

            apps = self._get_desktop_apps()
            if apps:
                apps_list = ", ".join(apps)
                return ToolResult(
                    success=False,
                    error=f"Ярлык '{path_str}' не найден на рабочем столе. Доступные: {apps_list}",
                )
            return ToolResult(success=False, error=f"Ярлык '{path_str}' не найден")

        # Full path mode
        ok, p, err = self._service.validate_path(path_str)
        if not ok:
            return ToolResult(success=False, error=err)
        assert p is not None
        if not p.exists():
            return ToolResult(success=False, error=f"Path not found: {p}")

        try:
            self._shell_open(p)
        except Exception as e:
            return ToolResult(success=False, error=f"Cannot open: {e}")

        kind = "folder" if p.is_dir() else "file"
        logger.info("Opened %s on local machine: %s", kind, p)
        return ToolResult(success=True, data=f"Opened {kind}: {p.name}\nPath: {p}")


# ---------------------------------------------------------------------------
# FileCopyTool — copy / move files (binary-safe)
# ---------------------------------------------------------------------------


class FileCopyTool:
    """Copy or move a file to a new location.

    Binary-safe: works with any file type (PDF, images, archives, etc.).
    Use this when the user sends a file and wants it saved somewhere,
    or when copying files between directories.
    """

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_copy",
            description=(
                "Copy a file to a new location. Works with ANY file type "
                "(PDF, images, documents, archives). Use this to save files "
                "the user sent to a specific directory (e.g. Desktop). "
                "Source can be a temp path (from received Telegram files)."
            ),
            parameters=[
                ToolParameter(
                    name="source",
                    type="string",
                    description="Full path to the source file",
                    required=True,
                ),
                ToolParameter(
                    name="destination",
                    type="string",
                    description=(
                        "Full path for the destination. If it's a directory, "
                        "the file keeps its original name."
                    ),
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        import shutil

        source_str: str = kwargs.get("source", "")
        dest_str: str = kwargs.get("destination", "")

        if not source_str:
            return ToolResult(success=False, error="source is required")
        if not dest_str:
            return ToolResult(success=False, error="destination is required")

        # Validate source: allow temp paths (from Telegram downloads) but validate non-temp
        ok, src_path, err = self._service.validate_source_path(source_str)
        if not ok:
            return ToolResult(success=False, error=err)

        assert src_path is not None
        if not src_path.is_file():
            return ToolResult(success=False, error=f"Source file not found: {src_path}")

        # Destination must be within allowed roots
        ok, dest_path, err = self._service.validate_path(dest_str)
        if not ok:
            return ToolResult(success=False, error=err)

        assert dest_path is not None

        # If destination is a directory, keep original filename
        if dest_path.is_dir():
            dest_path = dest_path / src_path.name

        # Create parent directories if needed
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ToolResult(success=False, error=f"Cannot create directory: {e}")

        # Copy (binary-safe)
        try:
            await asyncio.to_thread(shutil.copy2, str(src_path), str(dest_path))
        except Exception as e:
            return ToolResult(success=False, error=f"Copy failed: {e}")

        size = dest_path.stat().st_size
        logger.info("File copied: %s -> %s (%s)", src_path, dest_path, _human_size(size))

        return ToolResult(
            success=True,
            data=(
                f"Copied: {src_path.name} ({_human_size(size)})\n"
                f"From: {src_path}\n"
                f"To: {dest_path}"
            ),
        )


# ---------------------------------------------------------------------------
# FileSendTool — send file as Telegram attachment
# ---------------------------------------------------------------------------


class FileSendTool:
    """Send a file to the user as a Telegram attachment.

    Uses a pending_sends queue: the tool validates and queues the file,
    then main.py drains the queue after agent.process() and sends
    the actual files via Telegram.
    """

    def __init__(self, service: FileService) -> None:
        self._service = service
        self.pending_sends: list[Path] = []

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_send",
            description=(
                "Send a file to the user as a Telegram attachment/document. "
                "Use this when the user asks to receive, download, or get a file. "
                "The file will be sent as an attachment in the chat."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Full path to the file to send",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs.get("path", "")
        if not path_str:
            return ToolResult(success=False, error="path is required")

        ok, p, err = self._service.validate_path_for_read(path_str)
        if not ok:
            return ToolResult(success=False, error=err)

        assert p is not None

        if not p.is_file():
            return ToolResult(success=False, error=f"Not a file: {p}")

        # Check size (Telegram limit: 50MB)
        try:
            size = p.stat().st_size
        except OSError as e:
            return ToolResult(success=False, error=f"Cannot access file: {e}")

        if size > 50 * 1024 * 1024:
            return ToolResult(
                success=False,
                error=f"File too large for Telegram: {_human_size(size)} (limit: 50 MB)",
            )

        self.pending_sends.append(p)
        logger.info("File queued for sending: %s (%s)", p, _human_size(size))

        return ToolResult(
            success=True,
            data=f"File queued for sending: {p.name} ({_human_size(size)})",
        )


# ---------------------------------------------------------------------------
# FilePdfTool — create PDF from markdown-like content
# ---------------------------------------------------------------------------

# Windows fonts path
_FONTS_DIR = Path("C:/Windows/Fonts")
_FONT_REGULAR = _FONTS_DIR / "arial.ttf"
_FONT_BOLD = _FONTS_DIR / "arialbd.ttf"
_FONT_ITALIC = _FONTS_DIR / "ariali.ttf"
_FONT_BOLD_ITALIC = _FONTS_DIR / "arialbi.ttf"


def _md_to_pdf_lines(text: str) -> list[dict[str, Any]]:
    """Parse markdown-like text into structured lines for PDF rendering.

    Returns list of dicts:
        {"type": "h1"|"h2"|"h3"|"p"|"bullet"|"hr", "text": str}
    """
    lines: list[dict[str, Any]] = []
    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped:
            lines.append({"type": "spacer", "text": ""})
        elif stripped.startswith("### "):
            lines.append({"type": "h3", "text": stripped[4:]})
        elif stripped.startswith("## "):
            lines.append({"type": "h2", "text": stripped[3:]})
        elif stripped.startswith("# "):
            lines.append({"type": "h1", "text": stripped[2:]})
        elif stripped == "---" or stripped == "***" or stripped == "___":
            lines.append({"type": "hr", "text": ""})
        elif re.match(r"^[-*+]\s", stripped):
            lines.append({"type": "bullet", "text": stripped[2:]})
        elif re.match(r"^\d+\.\s", stripped):
            # Numbered list — strip "1. " prefix
            lines.append({"type": "numbered", "text": re.sub(r"^\d+\.\s", "", stripped)})
        else:
            lines.append({"type": "p", "text": stripped})
    return lines


def _render_rich_text(pdf: Any, text: str, default_style: str = "") -> None:
    """Render text with **bold** and *italic* markdown inline formatting.

    Uses pdf.write() with font switching for inline formatting.
    """
    # Pattern: **bold**, *italic*, ***bold+italic***
    parts = re.split(r"(\*{1,3})(.*?)\1", text)
    # parts comes in groups of 3: [before, stars, content, after, ...]
    i = 0
    while i < len(parts):
        if i + 2 < len(parts) and parts[i + 1] in ("*", "**", "***"):
            # Text before the marker
            if parts[i]:
                pdf.set_font("Arial", default_style, pdf.font_size_pt)
                pdf.write(pdf.font_size_pt / 2.2, parts[i])
            # Styled content
            stars = parts[i + 1]
            content = parts[i + 2]
            if stars == "***":
                style = "BI"
            elif stars == "**":
                style = "B"
            else:
                style = "I"
            pdf.set_font("Arial", style, pdf.font_size_pt)
            pdf.write(pdf.font_size_pt / 2.2, content)
            pdf.set_font("Arial", default_style, pdf.font_size_pt)
            i += 3
        else:
            if parts[i]:
                pdf.set_font("Arial", default_style, pdf.font_size_pt)
                pdf.write(pdf.font_size_pt / 2.2, parts[i])
            i += 1


def _build_pdf(content: str, title: str | None, output_path: Path) -> None:
    """Build a PDF file from markdown-like content. Runs synchronously."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Register Arial Unicode font (Cyrillic support)
    if _FONT_REGULAR.exists():
        pdf.add_font("Arial", "", str(_FONT_REGULAR))
        pdf.add_font("Arial", "B", str(_FONT_BOLD))
        if _FONT_ITALIC.exists():
            pdf.add_font("Arial", "I", str(_FONT_ITALIC))
        if _FONT_BOLD_ITALIC.exists():
            pdf.add_font("Arial", "BI", str(_FONT_BOLD_ITALIC))
    else:
        # Fallback to built-in (no Cyrillic)
        logger.warning("Arial TTF not found, falling back to built-in font (no Cyrillic)")

    # Title
    if title:
        pdf.set_font("Arial", "B", 18)
        pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(4)

    # Parse and render content
    parsed = _md_to_pdf_lines(content)
    bullet_num = 0

    for line in parsed:
        lt = line["type"]
        text = line["text"]

        if lt == "spacer":
            pdf.ln(4)
            bullet_num = 0
        elif lt == "hr":
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(4)
            bullet_num = 0
        elif lt == "h1":
            pdf.ln(3)
            pdf.set_font("Arial", "B", 16)
            pdf.multi_cell(0, 9, text)
            pdf.ln(2)
            bullet_num = 0
        elif lt == "h2":
            pdf.ln(2)
            pdf.set_font("Arial", "B", 14)
            pdf.multi_cell(0, 8, text)
            pdf.ln(1)
            bullet_num = 0
        elif lt == "h3":
            pdf.ln(1)
            pdf.set_font("Arial", "B", 12)
            pdf.multi_cell(0, 7, text)
            pdf.ln(1)
            bullet_num = 0
        elif lt == "bullet":
            pdf.set_font("Arial", "", 11)
            x = pdf.get_x()
            pdf.set_x(x + 6)
            pdf.write(6, "\u2022  ")
            _render_rich_text(pdf, text)
            pdf.ln(6)
        elif lt == "numbered":
            bullet_num += 1
            pdf.set_font("Arial", "", 11)
            x = pdf.get_x()
            pdf.set_x(x + 6)
            pdf.write(6, f"{bullet_num}.  ")
            _render_rich_text(pdf, text)
            pdf.ln(6)
        else:  # paragraph
            pdf.set_font("Arial", "", 11)
            _render_rich_text(pdf, text)
            pdf.ln(6)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


async def _html_to_pdf(html_path: Path, output_path: Path) -> None:
    """Convert HTML file to PDF using PDFEndpoint cloud API.

    Uses PDFEndpoint REST API (free tier) with inline delivery mode
    for high-quality HTML→PDF with full CSS rendering.
    """
    import os

    import aiohttp

    api_key = os.getenv("PDFENDPOINT_API_KEY", "")
    if not api_key:
        raise RuntimeError("PDFENDPOINT_API_KEY not set in .env")

    html_content = html_path.read_text(encoding="utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "html": html_content,
        "orientation": "horizontal",
        "viewport": "1280x720",
        "margin_top": "0mm",
        "margin_bottom": "0mm",
        "margin_left": "0mm",
        "margin_right": "0mm",
        "delivery_mode": "inline",
        "image_compression_quality": 75,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.pdfendpoint.com/v1/convert",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"PDFEndpoint API error {resp.status}: {body[:300]}")

            pdf_bytes = await resp.read()
            if not pdf_bytes or not pdf_bytes[:5].startswith(b"%PDF"):
                raise RuntimeError("PDFEndpoint returned invalid PDF data")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(pdf_bytes)

    logger.info("HTML→PDF (PDFEndpoint): %s → %s (%d bytes)",
                html_path.name, output_path.name, output_path.stat().st_size)


class FilePdfTool:
    """Create PDF from text/markdown OR convert HTML file to PDF.

    Mode 1 (text): headers (#, ##, ###), bold (**text**), italic (*text*),
    bullet lists (- item), numbered lists (1. item), horizontal rules (---).
    Cyrillic/Unicode supported via Arial TTF font.

    Mode 2 (HTML): provide source=path.html — PDFEndpoint cloud API renders
    HTML with full CSS support into a pixel-perfect PDF.
    """

    def __init__(self, service: FileService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_pdf",
            description=(
                "Create PDF from text OR convert HTML to PDF. "
                "Two modes: (1) Pass content= with markdown text to generate PDF from scratch. "
                "(2) Pass source= with path to .html file to convert HTML→PDF with full CSS "
                "(uses PDFEndpoint cloud API — pixel-perfect rendering). "
                "Supports Cyrillic/Ukrainian/Russian text in both modes."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Output path for the PDF file (must end with .pdf)",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description=(
                        "Text content in markdown format. Use # for headers, "
                        "**bold**, *italic*, - for bullets, 1. for numbered lists. "
                        "Not needed if source is provided."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="Optional document title (for text mode only)",
                    required=False,
                ),
                ToolParameter(
                    name="source",
                    type="string",
                    description=(
                        "Path to .html file to convert to PDF. "
                        "When provided, Playwright renders the HTML with full CSS into PDF. "
                        "content parameter is ignored when source is set."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs.get("path", "")
        content: str = kwargs.get("content", "")
        title: str | None = kwargs.get("title")
        source: str = kwargs.get("source", "")

        if not path_str:
            return ToolResult(success=False, error="path is required")

        # Ensure .pdf extension
        if not path_str.lower().endswith(".pdf"):
            path_str += ".pdf"

        ok, p, err = self._service.validate_path(path_str)
        if not ok:
            return ToolResult(success=False, error=err)
        assert p is not None

        # Mode 2: HTML → PDF via Playwright
        if source:
            html_path = Path(source)
            if not html_path.is_absolute():
                html_path = Path.cwd() / html_path
            if not html_path.exists():
                return ToolResult(success=False, error=f"HTML file not found: {html_path}")
            if not html_path.suffix.lower() in (".html", ".htm"):
                return ToolResult(success=False, error="source must be an .html or .htm file")

            try:
                await _html_to_pdf(html_path, p)
            except Exception as e:
                logger.error("HTML→PDF failed: %s", e)
                return ToolResult(success=False, error=f"HTML→PDF conversion failed: {e}")

            size = p.stat().st_size
            logger.info("HTML→PDF created: %s (%s)", p, _human_size(size))
            return ToolResult(
                success=True,
                data=(
                    f"PDF created from HTML: {p.name} ({_human_size(size)})\n"
                    f"Source: {html_path.name}\n"
                    f"Path: {p}\n"
                    "Use file_send to send this PDF to the user, "
                    "or file_open to open it on the computer."
                ),
            )

        # Mode 1: Text/Markdown → PDF via FPDF2
        if not content:
            return ToolResult(success=False, error="Either content or source is required")

        try:
            await asyncio.to_thread(_build_pdf, content, title, p)
        except Exception as e:
            logger.error("PDF creation failed: %s", e)
            return ToolResult(success=False, error=f"PDF creation failed: {e}")

        size = p.stat().st_size
        logger.info("PDF created: %s (%s)", p, _human_size(size))

        return ToolResult(
            success=True,
            data=(
                f"PDF created: {p.name} ({_human_size(size)})\n"
                f"Path: {p}\n"
                "Use file_send to send this PDF to the user, "
                "or file_open to open it on the computer."
            ),
        )
