"""
Skill manager tool — create, list, reload, delete skills at runtime.

Gives the agent ability to manage its own skill set without restart.
Hot-reload via SkillRegistry.reload() — new skills available immediately.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult
from src.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillManagerTool:
    """Manage agent skills at runtime.

    Actions:
    - create: write SKILL.md + auto-reload registry
    - list: show all loaded skills
    - reload: hot-reload all skills from disk
    - delete: remove skill directory + auto-reload
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        skills_dir: str = "skills",
    ) -> None:
        self._registry = skill_registry
        self._skills_dir = Path(skills_dir)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="skill_manager",
            description=(
                "Manage agent skills at runtime without restart. "
                "Create new skills (writes SKILL.md + auto-reloads), "
                "list all loaded skills, reload skills from disk (hot-reload), "
                "or delete a skill. After create/delete, reload happens automatically."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action to perform",
                    required=True,
                    enum=["create", "list", "reload", "delete"],
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="Skill name in snake_case (for create/delete)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Short skill description (for create)",
                    required=False,
                ),
                ToolParameter(
                    name="tools",
                    type="array",
                    description="List of tool names the skill uses (for create). Items type: string",
                    required=False,
                ),
                ToolParameter(
                    name="keywords",
                    type="array",
                    description="Trigger keywords in Russian/English (for create). Items type: string",
                    required=False,
                ),
                ToolParameter(
                    name="instructions",
                    type="string",
                    description="Markdown instructions body for the skill (for create)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs.get("action", "").lower()

        try:
            if action == "create":
                return await self._create(kwargs)
            elif action == "list":
                return await self._list()
            elif action == "reload":
                return await self._reload()
            elif action == "delete":
                return await self._delete(kwargs)
            else:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Unknown action: {action}. Use: create, list, reload, delete",
                )
        except Exception as exc:
            logger.error("SkillManager error (%s): %s", action, exc)
            return ToolResult(success=False, data=None, error=str(exc))

    async def _create(self, kwargs: dict[str, Any]) -> ToolResult:
        name = kwargs.get("name", "").strip()
        description = kwargs.get("description", "").strip()
        tools = kwargs.get("tools") or []
        keywords = kwargs.get("keywords") or []
        instructions = kwargs.get("instructions", "").strip()

        if not name:
            return ToolResult(success=False, data=None, error="Missing required parameter: name")

        # Validate snake_case name
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            return ToolResult(
                success=False, data=None,
                error=f"Invalid skill name '{name}'. Use snake_case: lowercase letters, digits, underscores.",
            )

        skill_dir = self._skills_dir / name
        skill_file = skill_dir / "SKILL.md"

        if skill_file.exists():
            return ToolResult(
                success=False, data=None,
                error=f"Skill '{name}' already exists at {skill_file}. Delete it first or use a different name.",
            )

        # Build SKILL.md content
        tools_yaml = "\n".join(f"  - {t}" for t in tools) if tools else "  - web_search"
        keywords_yaml = "\n".join(f"  - {kw}" for kw in keywords) if keywords else f"  - {name}"

        content = f"""---
name: {name}
description: {description or name}
tools:
{tools_yaml}
trigger_keywords:
{keywords_yaml}
---

# {description or name}

{instructions or f"Скилл {name}. Используй доступные инструменты для выполнения задач."}
"""

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(content.strip() + "\n", encoding="utf-8")
        except OSError as exc:
            return ToolResult(success=False, data=None, error=f"Failed to write SKILL.md: {exc}")

        # Auto-reload
        await self._registry.reload()

        logger.info("Skill '%s' created and loaded: %s", name, skill_file)
        return ToolResult(
            success=True,
            data={
                "name": name,
                "path": str(skill_file),
                "tools": tools,
                "keywords": keywords,
                "total_skills": len(self._registry.list_skills()),
            },
        )

    async def _list(self) -> ToolResult:
        skills = self._registry.list_skills()
        if not skills:
            return ToolResult(success=True, data="No skills loaded.")

        lines = []
        for s in skills:
            kw_count = len(s.trigger_keywords) if s.trigger_keywords else 0
            tools_str = ", ".join(s.tools[:5]) if s.tools else "none"
            lines.append(f"- **{s.name}**: {s.description} (tools: {tools_str}, keywords: {kw_count})")

        return ToolResult(
            success=True,
            data=f"Loaded skills ({len(skills)}):\n" + "\n".join(lines),
        )

    async def _reload(self) -> ToolResult:
        before = len(self._registry.list_skills())
        await self._registry.reload()
        after = len(self._registry.list_skills())

        logger.info("Skills reloaded: %d -> %d", before, after)
        return ToolResult(
            success=True,
            data=f"Skills reloaded: {after} skills loaded (was {before}).",
        )

    async def _delete(self, kwargs: dict[str, Any]) -> ToolResult:
        name = kwargs.get("name", "").strip()
        if not name:
            return ToolResult(success=False, data=None, error="Missing required parameter: name")

        skill_dir = self._skills_dir / name

        if not skill_dir.exists():
            return ToolResult(
                success=False, data=None,
                error=f"Skill '{name}' not found at {skill_dir}",
            )

        try:
            shutil.rmtree(skill_dir)
        except OSError as exc:
            return ToolResult(success=False, data=None, error=f"Failed to delete skill: {exc}")

        # Auto-reload
        await self._registry.reload()

        logger.info("Skill '%s' deleted and registry reloaded", name)
        return ToolResult(
            success=True,
            data=f"Skill '{name}' deleted. {len(self._registry.list_skills())} skills remaining.",
        )
