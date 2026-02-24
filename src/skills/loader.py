"""
Загрузчик скиллов из Markdown файлов.

Скиллы хранятся как SKILL.md файлы с YAML frontmatter и Markdown body.
SkillLoader парсит эти файлы и возвращает объекты Skill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """Скилл агента, загруженный из SKILL.md файла."""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    instructions: str = ""


class SkillLoader:
    """Загрузчик скиллов из SKILL.md файлов.

    Парсит YAML frontmatter (между --- маркерами) и Markdown body.
    """

    FRONTMATTER_DELIMITER = "---"
    SKILL_FILENAME = "SKILL.md"

    async def load_file(self, path: Path) -> Skill:
        """Загрузить скилл из одного SKILL.md файла.

        Args:
            path: Путь к SKILL.md файлу.

        Returns:
            Объект Skill с данными из файла.

        Raises:
            FileNotFoundError: Файл не найден.
            ValueError: Некорректный формат файла.
        """
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")

        logger.debug("Loading skill from %s", path)

        content = path.read_text(encoding="utf-8")
        frontmatter, body = self._parse_frontmatter(content, path)

        name = frontmatter.get("name")
        if not name:
            raise ValueError(f"Skill file {path} missing required 'name' in frontmatter")

        description = frontmatter.get("description", "")
        tools = frontmatter.get("tools", [])
        trigger_keywords = frontmatter.get("trigger_keywords", [])

        skill = Skill(
            name=name,
            description=description,
            tools=tools if isinstance(tools, list) else [tools],
            trigger_keywords=trigger_keywords if isinstance(trigger_keywords, list) else [trigger_keywords],
            instructions=body.strip(),
        )

        logger.info("Loaded skill: %s (%d tools, %d keywords)", skill.name, len(skill.tools), len(skill.trigger_keywords))
        return skill

    async def load_directory(self, path: Path) -> list[Skill]:
        """Загрузить все скиллы из поддиректорий.

        Ищет SKILL.md файлы в каждой поддиректории указанного пути.

        Args:
            path: Корневая директория скиллов.

        Returns:
            Список загруженных скиллов.
        """
        if not path.exists():
            logger.warning("Skills directory not found: %s", path)
            return []

        if not path.is_dir():
            logger.warning("Skills path is not a directory: %s", path)
            return []

        skills: list[Skill] = []

        for subdir in sorted(path.iterdir()):
            if not subdir.is_dir():
                continue

            skill_file = subdir / self.SKILL_FILENAME
            if not skill_file.exists():
                logger.debug("No %s in %s, skipping", self.SKILL_FILENAME, subdir.name)
                continue

            try:
                skill = await self.load_file(skill_file)
                skills.append(skill)
            except (ValueError, yaml.YAMLError) as e:
                logger.error("Failed to load skill from %s: %s", skill_file, e)

        logger.info("Loaded %d skills from %s", len(skills), path)
        return skills

    def _parse_frontmatter(self, content: str, path: Path) -> tuple[dict, str]:
        """Разделить YAML frontmatter и Markdown body.

        Args:
            content: Полное содержимое файла.
            path: Путь к файлу (для сообщений об ошибках).

        Returns:
            Кортеж (frontmatter_dict, markdown_body).

        Raises:
            ValueError: Некорректный формат frontmatter.
        """
        stripped = content.strip()

        if not stripped.startswith(self.FRONTMATTER_DELIMITER):
            raise ValueError(
                f"Skill file {path} must start with '{self.FRONTMATTER_DELIMITER}' (YAML frontmatter)"
            )

        # Find the second --- delimiter
        second_delimiter_pos = stripped.find(
            self.FRONTMATTER_DELIMITER, len(self.FRONTMATTER_DELIMITER)
        )

        if second_delimiter_pos == -1:
            raise ValueError(
                f"Skill file {path} missing closing '{self.FRONTMATTER_DELIMITER}' for frontmatter"
            )

        # Extract YAML between the two delimiters
        yaml_content = stripped[len(self.FRONTMATTER_DELIMITER):second_delimiter_pos].strip()

        # Extract Markdown body after the second delimiter
        body_start = second_delimiter_pos + len(self.FRONTMATTER_DELIMITER)
        body = stripped[body_start:]

        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter in {path}: {e}") from e

        if not isinstance(frontmatter, dict):
            raise ValueError(f"Frontmatter in {path} must be a YAML mapping, got {type(frontmatter).__name__}")

        return frontmatter, body
