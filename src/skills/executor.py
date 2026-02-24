"""
Исполнитель скиллов.

Формирует промпт из инструкций скилла и сообщения пользователя.
Результат добавляется в контекст LLM.
"""

from __future__ import annotations

import logging

from src.skills.loader import Skill

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Исполнитель скиллов.

    Собирает промпт из инструкций скилла, сообщения пользователя
    и опциональных результатов инструментов.
    """

    async def execute(
        self,
        skill: Skill,
        user_message: str,
        tool_results: dict | None = None,
    ) -> str:
        """Построить промпт из скилла и сообщения пользователя.

        Формирует комбинированный промпт, который будет добавлен
        в сообщения LLM как системный контекст.

        Args:
            skill: Скилл с инструкциями.
            user_message: Сообщение пользователя.
            tool_results: Опциональные результаты выполнения инструментов.

        Returns:
            Строка промпта для LLM.
        """
        logger.debug("Executing skill '%s' for message: %s", skill.name, user_message[:100])

        parts: list[str] = []

        # Skill instructions as system context
        parts.append(f"## Skill: {skill.name}")
        parts.append(f"**Description:** {skill.description}")
        parts.append("")
        parts.append("### Instructions")
        parts.append(skill.instructions)

        # Tool results if available
        if tool_results:
            parts.append("")
            parts.append("### Tool Results")
            for tool_name, result in tool_results.items():
                parts.append(f"**{tool_name}:**")
                parts.append(str(result))

        # User message
        parts.append("")
        parts.append("### User Message")
        parts.append(user_message)

        prompt = "\n".join(parts)

        logger.debug(
            "Built prompt for skill '%s': %d characters",
            skill.name,
            len(prompt),
        )

        return prompt
