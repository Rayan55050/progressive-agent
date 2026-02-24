"""
Реестр скиллов агента.

Хранит все загруженные скиллы, предоставляет поиск по имени и ключевым словам.
Поддерживает горячую перезагрузку (hot-reload).
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.skills.loader import Skill, SkillLoader

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Реестр скиллов агента.

    Загружает скиллы из директории, хранит в словаре,
    предоставляет поиск по имени и ключевым словам.
    """

    def __init__(self, skills_dir: str = "skills") -> None:
        """Инициализация реестра.

        Args:
            skills_dir: Путь к директории со скиллами (относительно корня проекта).
        """
        self._skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}
        self._loader = SkillLoader()

    async def load(self) -> None:
        """Загрузить все скиллы из директории.

        Ищет SKILL.md файлы во всех поддиректориях skills_dir.
        """
        logger.info("Loading skills from %s", self._skills_dir)

        skills = await self._loader.load_directory(self._skills_dir)

        self._skills.clear()
        for skill in skills:
            if skill.name in self._skills:
                logger.warning(
                    "Duplicate skill name '%s', overwriting with latest",
                    skill.name,
                )
            self._skills[skill.name] = skill

        logger.info("Registry loaded: %d skills", len(self._skills))

    def get(self, name: str) -> Skill | None:
        """Получить скилл по имени.

        Args:
            name: Имя скилла.

        Returns:
            Объект Skill или None, если не найден.
        """
        return self._skills.get(name)

    def find_by_keyword(self, text: str) -> Skill | None:
        """Найти скилл по ключевому слову в тексте.

        Проверяет, содержит ли текст trigger_keywords какого-либо скилла.
        Возвращает первый найденный скилл.

        Args:
            text: Текст для поиска ключевых слов (например, сообщение пользователя).

        Returns:
            Объект Skill или None, если ни одно ключевое слово не найдено.
        """
        text_lower = text.lower()

        for skill in self._skills.values():
            for keyword in skill.trigger_keywords:
                if keyword.lower() in text_lower:
                    logger.debug(
                        "Keyword '%s' matched skill '%s' in text",
                        keyword,
                        skill.name,
                    )
                    return skill

        return None

    def list_skills(self) -> list[Skill]:
        """Получить список всех загруженных скиллов.

        Returns:
            Список всех скиллов.
        """
        return list(self._skills.values())

    async def reload(self) -> None:
        """Перезагрузить все скиллы (hot-reload).

        Полностью очищает реестр и загружает скиллы заново.
        """
        logger.info("Reloading skills from %s", self._skills_dir)
        await self.load()
        logger.info("Skills reloaded: %d skills", len(self._skills))
