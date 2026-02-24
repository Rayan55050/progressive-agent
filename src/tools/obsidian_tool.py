"""
Obsidian vault tools for Progressive Agent.

Provides four LLM-callable tools:
- obsidian_note: create/update notes with templates and frontmatter
- obsidian_search: full-text search across vault with tag/folder filters
- obsidian_daily: daily notes (create/read/append)
- obsidian_list: vault overview and folder listing

Works directly with .md files in the vault — no Obsidian API needed.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ObsidianService:
    """Shared Obsidian vault service.

    Handles vault operations: note CRUD, search, templates, frontmatter parsing.
    """

    def __init__(
        self,
        vault_path: str,
        daily_folder: str = "01 Daily",
        inbox_folder: str = "00 Inbox",
        templates_folder: str = "Templates",
    ) -> None:
        self.vault = Path(vault_path)
        self.daily_folder = daily_folder
        self.inbox_folder = inbox_folder
        self.templates_folder = templates_folder

    @property
    def available(self) -> bool:
        return self.vault.exists() and self.vault.is_dir()

    # --- Folder mapping ---

    FOLDER_MAP = {
        "inbox": "00 Inbox",
        "daily": "01 Daily",
        "projects": "02 Projects",
        "ideas": "03 Ideas",
        "knowledge": "04 Knowledge",
        "bookmarks": "05 Bookmarks",
        "people": "06 People",
    }

    def _resolve_folder(self, folder: str) -> Path:
        """Resolve folder alias to full path."""
        mapped = self.FOLDER_MAP.get(folder.lower(), folder)
        path = self.vault / mapped
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --- Frontmatter ---

    @staticmethod
    def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}, content

        end = content.find("---", 3)
        if end == -1:
            return {}, content

        fm_text = content[3:end].strip()
        body = content[end + 3:].strip()

        meta: dict[str, Any] = {}
        for line in fm_text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                # Parse list values: [tag1, tag2]
                if value.startswith("[") and value.endswith("]"):
                    items = [
                        v.strip().strip("'\"")
                        for v in value[1:-1].split(",")
                        if v.strip()
                    ]
                    meta[key] = items
                else:
                    meta[key] = value
        return meta, body

    @staticmethod
    def build_frontmatter(meta: dict[str, Any]) -> str:
        """Build YAML frontmatter string."""
        lines = ["---"]
        for key, value in meta.items():
            if isinstance(value, list):
                items = ", ".join(str(v) for v in value)
                lines.append(f"{key}: [{items}]")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines)

    # --- Wiki-links and tags ---

    @staticmethod
    def extract_links(content: str) -> list[str]:
        """Extract [[wiki-links]] from content."""
        return re.findall(r"\[\[([^\]]+)\]\]", content)

    @staticmethod
    def extract_tags(content: str, meta: dict[str, Any] | None = None) -> list[str]:
        """Extract tags from content (#tag) and frontmatter."""
        tags = set()
        # Inline #tags
        for tag in re.findall(r"(?:^|\s)#([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ0-9_/-]+)", content):
            tags.add(tag)
        # Frontmatter tags
        if meta and "tags" in meta:
            fm_tags = meta["tags"]
            if isinstance(fm_tags, list):
                tags.update(fm_tags)
            elif isinstance(fm_tags, str):
                tags.add(fm_tags)
        return sorted(tags)

    # --- Template handling ---

    def _load_template(self, template_name: str) -> str | None:
        """Load template content by name."""
        template_path = self.vault / self.templates_folder / f"{template_name}.md"
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        # Try capitalized
        template_path = self.vault / self.templates_folder / f"{template_name.capitalize()}.md"
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        return None

    def _apply_template(self, template: str, title: str, date: str) -> str:
        """Replace {{placeholders}} in template."""
        result = template.replace("{{title}}", title)
        result = result.replace("{{date}}", date)
        return result

    # --- Note resolution ---

    def _find_note(self, name: str) -> Path | None:
        """Find a note by name (with or without .md extension)."""
        if not name.endswith(".md"):
            name += ".md"

        # Direct path
        direct = self.vault / name
        if direct.exists():
            return direct

        # Search everywhere in vault
        for p in self.vault.rglob(name):
            if p.is_file():
                return p

        return None

    # --- Core operations ---

    async def create_note(
        self,
        title: str,
        content: str = "",
        folder: str = "inbox",
        tags: list[str] | None = None,
        template: str | None = None,
    ) -> dict[str, Any]:
        """Create a new note in the vault."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        folder_path = self._resolve_folder(folder)

        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', "", title).strip()
        if not safe_title:
            safe_title = f"note-{today}"

        file_path = folder_path / f"{safe_title}.md"

        # Check if exists
        if file_path.exists():
            # Append mode
            existing = file_path.read_text(encoding="utf-8")
            if content:
                new_content = existing.rstrip() + "\n\n" + content + "\n"
                file_path.write_text(new_content, encoding="utf-8")
                return {
                    "action": "appended",
                    "path": str(file_path.relative_to(self.vault)),
                    "title": safe_title,
                }

        # Build from template or scratch
        if template:
            tmpl = self._load_template(template)
            if tmpl:
                note_content = self._apply_template(tmpl, title=safe_title, date=today)
                # Replace body placeholder if content provided
                if content:
                    # Add content after the last heading
                    note_content = note_content.rstrip() + "\n\n" + content + "\n"
            else:
                note_content = self._build_note(safe_title, content, tags, today)
        else:
            note_content = self._build_note(safe_title, content, tags, today)

        file_path.write_text(note_content, encoding="utf-8")

        return {
            "action": "created",
            "path": str(file_path.relative_to(self.vault)),
            "title": safe_title,
        }

    def _build_note(
        self, title: str, content: str, tags: list[str] | None, date: str
    ) -> str:
        """Build a note with frontmatter from scratch."""
        meta: dict[str, Any] = {
            "created": date,
        }
        if tags:
            meta["tags"] = tags

        fm = self.build_frontmatter(meta)
        body = f"\n# {title}\n\n{content}\n" if content else f"\n# {title}\n"
        return fm + body

    async def read_note(self, name_or_path: str) -> dict[str, Any] | None:
        """Read a note by name or path. Returns content + metadata."""
        path = self._find_note(name_or_path)
        if not path:
            return None

        content = path.read_text(encoding="utf-8")
        meta, body = self.parse_frontmatter(content)
        links = self.extract_links(content)
        tags = self.extract_tags(content, meta)

        return {
            "path": str(path.relative_to(self.vault)),
            "title": path.stem,
            "content": body,
            "meta": meta,
            "links": links,
            "tags": tags,
        }

    async def search_notes(
        self,
        query: str,
        tag: str | None = None,
        folder: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search across vault .md files."""
        results: list[dict[str, Any]] = []
        query_lower = query.lower()

        search_root = self.vault
        if folder:
            search_root = self._resolve_folder(folder)

        for md_file in search_root.rglob("*.md"):
            # Skip templates
            try:
                rel = md_file.relative_to(self.vault / self.templates_folder)
                continue  # it's a template
            except ValueError:
                pass

            # Skip .obsidian
            if ".obsidian" in md_file.parts:
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            meta, body = self.parse_frontmatter(content)

            # Tag filter
            if tag:
                note_tags = self.extract_tags(content, meta)
                if tag.lower() not in [t.lower() for t in note_tags]:
                    continue

            # Text search
            if query_lower not in content.lower():
                continue

            # Build preview (first 200 chars of body)
            preview = body[:200].strip()
            if len(body) > 200:
                preview += "..."

            tags_list = self.extract_tags(content, meta)

            results.append({
                "path": str(md_file.relative_to(self.vault)),
                "title": md_file.stem,
                "preview": preview,
                "tags": tags_list,
                "modified": md_file.stat().st_mtime,
            })

        # Sort by modification time (newest first)
        results.sort(key=lambda x: x["modified"], reverse=True)
        return results[:20]

    async def daily_note(
        self,
        date: str | None = None,
        append_text: str | None = None,
    ) -> dict[str, Any]:
        """Get or create a daily note."""
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        daily_path = self.vault / self.daily_folder / f"{date}.md"

        if daily_path.exists():
            content = daily_path.read_text(encoding="utf-8")

            if append_text:
                # Append text
                new_content = content.rstrip() + "\n\n" + append_text + "\n"
                daily_path.write_text(new_content, encoding="utf-8")
                meta, body = self.parse_frontmatter(new_content)
                return {
                    "action": "appended",
                    "path": str(daily_path.relative_to(self.vault)),
                    "date": date,
                    "content": body,
                }

            # Just return content
            meta, body = self.parse_frontmatter(content)
            return {
                "action": "read",
                "path": str(daily_path.relative_to(self.vault)),
                "date": date,
                "content": body,
            }

        # Create from template
        tmpl = self._load_template("Daily")
        if tmpl:
            note_content = self._apply_template(tmpl, title=date, date=date)
        else:
            note_content = (
                f"---\ntype: daily\ndate: {date}\ntags: [daily]\n---\n\n"
                f"# {date}\n\n## Задачи\n- [ ]\n\n## Заметки\n\n## Итоги дня\n"
            )

        if append_text:
            note_content = note_content.rstrip() + "\n\n" + append_text + "\n"

        daily_path.parent.mkdir(parents=True, exist_ok=True)
        daily_path.write_text(note_content, encoding="utf-8")

        meta, body = self.parse_frontmatter(note_content)
        return {
            "action": "created",
            "path": str(daily_path.relative_to(self.vault)),
            "date": date,
            "content": body,
        }

    async def list_notes(
        self,
        folder: str | None = None,
        sort_by: str = "date",
        limit: int = 20,
    ) -> dict[str, Any]:
        """List vault structure or folder contents."""
        if not folder:
            # Show vault overview: folders + note counts
            folders_info: list[dict[str, Any]] = []
            for item in sorted(self.vault.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    md_count = len(list(item.rglob("*.md")))
                    folders_info.append({
                        "name": item.name,
                        "notes": md_count,
                    })
            total = len(list(self.vault.rglob("*.md")))
            return {
                "type": "overview",
                "folders": folders_info,
                "total_notes": total,
            }

        # List notes in specific folder
        folder_path = self._resolve_folder(folder)
        notes: list[dict[str, Any]] = []

        for md_file in folder_path.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            meta, body = self.parse_frontmatter(content)
            preview = body[:150].strip()
            if len(body) > 150:
                preview += "..."

            notes.append({
                "path": str(md_file.relative_to(self.vault)),
                "title": md_file.stem,
                "preview": preview,
                "tags": self.extract_tags(content, meta),
                "modified": md_file.stat().st_mtime,
                "size": md_file.stat().st_size,
            })

        # Sort
        if sort_by == "name":
            notes.sort(key=lambda x: x["title"].lower())
        elif sort_by == "size":
            notes.sort(key=lambda x: x["size"], reverse=True)
        else:  # date
            notes.sort(key=lambda x: x["modified"], reverse=True)

        return {
            "type": "listing",
            "folder": folder,
            "notes": notes[:limit],
            "total": len(notes),
        }

    async def find_backlinks(self, note_name: str) -> list[str]:
        """Find notes that link to the given note via [[wiki-links]]."""
        backlinks: list[str] = []
        target = note_name.replace(".md", "")

        for md_file in self.vault.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            links = self.extract_links(content)
            if target in links:
                backlinks.append(str(md_file.relative_to(self.vault)))

        return backlinks

    async def get_tags(self) -> dict[str, int]:
        """Get tag cloud with counts across entire vault."""
        tag_counts: dict[str, int] = {}

        for md_file in self.vault.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                rel = md_file.relative_to(self.vault / self.templates_folder)
                continue
            except ValueError:
                pass

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            meta, _ = self.parse_frontmatter(content)
            tags = self.extract_tags(content, meta)
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True))


# ---------------------------------------------------------------------------
# Tool: obsidian_note
# ---------------------------------------------------------------------------


class ObsidianNoteTool:
    """Create or update a note in Obsidian vault."""

    def __init__(self, service: ObsidianService) -> None:
        self._obs = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_note",
            description=(
                "Create or update a note in Obsidian vault. "
                "Supports folders (inbox, ideas, knowledge, projects, bookmarks, people), "
                "tags, and templates (daily, project, idea, bookmark). "
                "If a note with the same title exists, content is appended."
            ),
            parameters=[
                ToolParameter(
                    name="title",
                    type="string",
                    description="Note title (used as filename)",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Note content (markdown)",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="folder",
                    type="string",
                    description=(
                        "Target folder: inbox, ideas, knowledge, projects, "
                        "bookmarks, people (default: inbox)"
                    ),
                    required=False,
                    default="inbox",
                ),
                ToolParameter(
                    name="tags",
                    type="string",
                    description="Comma-separated tags (e.g. 'trading, идея, crypto')",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="template",
                    type="string",
                    description="Template to use: project, idea, bookmark (optional)",
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._obs.available:
            return ToolResult(success=False, error="Obsidian vault не найден")

        title = kwargs.get("title", "").strip()
        if not title:
            return ToolResult(success=False, error="Укажи заголовок заметки")

        content = kwargs.get("content", "")
        folder = kwargs.get("folder", "inbox")
        tags_str = kwargs.get("tags", "")
        template = kwargs.get("template", "")

        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None

        try:
            result = await self._obs.create_note(
                title=title,
                content=content,
                folder=folder,
                tags=tags,
                template=template or None,
            )
            action = result["action"]
            path = result["path"]

            if action == "appended":
                return ToolResult(success=True, data=f"Дополнил заметку: {path}")
            return ToolResult(success=True, data=f"Заметка создана: {path}")

        except Exception as e:
            logger.error("obsidian_note failed: %s", e)
            return ToolResult(success=False, error=f"Obsidian error: {e}")


# ---------------------------------------------------------------------------
# Tool: obsidian_search
# ---------------------------------------------------------------------------


class ObsidianSearchTool:
    """Search notes in Obsidian vault."""

    def __init__(self, service: ObsidianService) -> None:
        self._obs = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_search",
            description=(
                "Search notes in Obsidian vault by text content, tags, or folder. "
                "Full-text search across all .md files. "
                "Returns matching notes with preview and tags."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search text (searches in title + content)",
                    required=True,
                ),
                ToolParameter(
                    name="tag",
                    type="string",
                    description="Filter by tag (e.g. 'project', 'idea')",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="folder",
                    type="string",
                    description="Limit search to folder (inbox, ideas, knowledge, etc.)",
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._obs.available:
            return ToolResult(success=False, error="Obsidian vault не найден")

        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Укажи текст для поиска")

        tag = kwargs.get("tag", "").strip() or None
        folder = kwargs.get("folder", "").strip() or None

        try:
            results = await self._obs.search_notes(query=query, tag=tag, folder=folder)

            if not results:
                return ToolResult(success=True, data="Ничего не найдено")

            lines = [f"Найдено заметок: {len(results)}", ""]
            for r in results:
                tags_str = ", ".join(r["tags"]) if r["tags"] else ""
                line = f"**{r['title']}** ({r['path']})"
                if tags_str:
                    line += f" [{tags_str}]"
                line += f"\n{r['preview']}"
                lines.append(line)
                lines.append("")

            return ToolResult(success=True, data="\n".join(lines))

        except Exception as e:
            logger.error("obsidian_search failed: %s", e)
            return ToolResult(success=False, error=f"Obsidian error: {e}")


# ---------------------------------------------------------------------------
# Tool: obsidian_daily
# ---------------------------------------------------------------------------


class ObsidianDailyTool:
    """Daily notes in Obsidian vault."""

    def __init__(self, service: ObsidianService) -> None:
        self._obs = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_daily",
            description=(
                "Work with daily notes in Obsidian. "
                "Without text — returns today's daily note (creates if missing). "
                "With text — appends to today's daily note. "
                "Supports custom date (YYYY-MM-DD)."
            ),
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to append to daily note (empty = just show note)",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="date",
                    type="string",
                    description="Date in YYYY-MM-DD format (default: today)",
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._obs.available:
            return ToolResult(success=False, error="Obsidian vault не найден")

        text = kwargs.get("text", "").strip() or None
        date = kwargs.get("date", "").strip() or None

        try:
            result = await self._obs.daily_note(date=date, append_text=text)

            action = result["action"]
            path = result["path"]
            content = result["content"]

            if action == "created":
                header = f"Создал daily note: {path}"
            elif action == "appended":
                header = f"Дополнил daily note: {path}"
            else:
                header = f"Daily note: {path}"

            return ToolResult(success=True, data=f"{header}\n\n{content}")

        except Exception as e:
            logger.error("obsidian_daily failed: %s", e)
            return ToolResult(success=False, error=f"Obsidian error: {e}")


# ---------------------------------------------------------------------------
# Tool: obsidian_list
# ---------------------------------------------------------------------------


class ObsidianListTool:
    """List and browse Obsidian vault structure."""

    def __init__(self, service: ObsidianService) -> None:
        self._obs = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_list",
            description=(
                "List Obsidian vault structure. "
                "Without folder — shows vault overview (folders + note counts). "
                "With folder — lists notes in that folder with preview."
            ),
            parameters=[
                ToolParameter(
                    name="folder",
                    type="string",
                    description=(
                        "Folder to list: inbox, daily, ideas, knowledge, projects, "
                        "bookmarks, people. Empty = vault overview."
                    ),
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="sort",
                    type="string",
                    description="Sort: date (default), name, size",
                    required=False,
                    default="date",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._obs.available:
            return ToolResult(success=False, error="Obsidian vault не найден")

        folder = kwargs.get("folder", "").strip() or None
        sort_by = kwargs.get("sort", "date").strip()

        try:
            result = await self._obs.list_notes(folder=folder, sort_by=sort_by)

            if result["type"] == "overview":
                lines = [f"Obsidian Vault ({result['total_notes']} заметок):", ""]
                for f in result["folders"]:
                    lines.append(f"  {f['name']}: {f['notes']} заметок")
                return ToolResult(success=True, data="\n".join(lines))

            # Folder listing
            notes = result["notes"]
            total = result["total"]
            if not notes:
                return ToolResult(success=True, data=f"Папка '{folder}' пуста")

            lines = [f"Папка '{folder}' ({total} заметок):", ""]
            for n in notes:
                tags_str = ", ".join(n["tags"]) if n["tags"] else ""
                line = f"**{n['title']}**"
                if tags_str:
                    line += f" [{tags_str}]"
                line += f"\n{n['preview']}"
                lines.append(line)
                lines.append("")

            return ToolResult(success=True, data="\n".join(lines))

        except Exception as e:
            logger.error("obsidian_list failed: %s", e)
            return ToolResult(success=False, error=f"Obsidian error: {e}")
