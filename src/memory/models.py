"""
Модели данных для системы памяти.

Memory — основной dataclass, используемый всеми компонентами памяти.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Memory:
    """Единица памяти агента.

    Attributes:
        id: Уникальный идентификатор (UUID4).
        content: Текстовое содержимое.
        type: Тип памяти — "conversation", "fact", "preference", "task".
        importance: Важность от 0.0 до 1.0.
        created_at: Время создания.
        accessed_at: Время последнего доступа.
        access_count: Количество обращений.
        metadata: Дополнительные данные (JSON-сериализуемый dict).
        score: Релевантность (заполняется при поиске, не хранится в БД).
    """

    id: str
    content: str
    type: str = "conversation"
    importance: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None

    def metadata_json(self) -> str:
        """Сериализовать metadata в JSON-строку."""
        return json.dumps(self.metadata, ensure_ascii=False)

    @staticmethod
    def metadata_from_json(raw: str | None) -> dict[str, Any]:
        """Десериализовать metadata из JSON-строки."""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
