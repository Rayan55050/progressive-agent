"""
SQLite-хранилище для памяти агента.

Асинхронные операции через aiosqlite.
Основная таблица `memories` — центральное хранилище всех воспоминаний.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

from src.memory.models import Memory

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'conversation',
    importance REAL DEFAULT 0.5,
    embedding BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);",
    "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);",
    "CREATE INDEX IF NOT EXISTS idx_memories_accessed_at ON memories(accessed_at);",
    "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);",
]


class SQLiteStore:
    """Асинхронное SQLite-хранилище для памяти агента.

    Использует aiosqlite для неблокирующих операций с БД.
    Автоматически создаёт таблицу при инициализации.

    Usage:
        store = SQLiteStore("data/memory.db")
        await store.init()
        memory_id = await store.store(Memory(...))
        memory = await store.get(memory_id)
        await store.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        """Получить соединение с БД. Бросает RuntimeError если не инициализировано."""
        if self._db is None:
            raise RuntimeError("SQLiteStore not initialized. Call init() first.")
        return self._db

    async def init(self) -> None:
        """Инициализировать БД: подключиться и создать таблицы."""
        logger.info("Initializing SQLite store at %s", self._db_path)
        # Ensure data directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA foreign_keys=ON;")
        await self._db.execute(CREATE_TABLE_SQL)
        for index_sql in CREATE_INDEX_SQL:
            await self._db.execute(index_sql)
        await self._db.commit()
        logger.info("SQLite store initialized successfully")

    async def store(self, memory: Memory) -> str:
        """Сохранить воспоминание в БД.

        Если id не задан, генерирует UUID4.

        Args:
            memory: Объект Memory для сохранения.

        Returns:
            ID сохранённого воспоминания.
        """
        if not memory.id:
            memory.id = str(uuid4())

        logger.debug("Storing memory %s (type=%s)", memory.id, memory.type)

        await self.db.execute(
            """
            INSERT INTO memories (id, content, type, importance, embedding,
                                  created_at, accessed_at, access_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.content,
                memory.type,
                memory.importance,
                None,  # embedding хранится отдельно через vector_search
                memory.created_at.isoformat(),
                memory.accessed_at.isoformat(),
                memory.access_count,
                memory.metadata_json(),
            ),
        )
        await self.db.commit()
        logger.debug("Memory %s stored successfully", memory.id)
        return memory.id

    async def get(self, memory_id: str, update_access: bool = True) -> Memory | None:
        """Получить воспоминание по ID.

        Args:
            memory_id: UUID воспоминания.
            update_access: Обновлять accessed_at и access_count (default True).
                Set False for read-only access (e.g. search scoring).

        Returns:
            Memory или None если не найдено.
        """
        if update_access:
            # Обновляем время доступа и счётчик
            await self.db.execute(
                """
                UPDATE memories
                SET accessed_at = ?, access_count = access_count + 1
                WHERE id = ?
                """,
                (datetime.now().isoformat(), memory_id),
            )
            await self.db.commit()

        # Читаем запись (after update so returned data reflects new values)
        cursor = await self.db.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            logger.debug("Memory %s not found", memory_id)
            return None

        return self._row_to_memory(row)

    async def update(self, memory_id: str, **fields: Any) -> bool:
        """Обновить поля воспоминания.

        Args:
            memory_id: UUID воспоминания.
            **fields: Поля для обновления (content, type, importance, metadata и т.д.).

        Returns:
            True если обновлено, False если не найдено.
        """
        if not fields:
            return False

        # Сериализуем metadata если передан как dict
        if "metadata" in fields and isinstance(fields["metadata"], dict):
            fields["metadata"] = json.dumps(fields["metadata"], ensure_ascii=False)

        set_clauses = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        values.append(memory_id)

        result = await self.db.execute(
            f"UPDATE memories SET {set_clauses} WHERE id = ?",  # noqa: S608
            values,
        )
        await self.db.commit()

        updated = result.rowcount > 0
        if updated:
            logger.debug("Memory %s updated: %s", memory_id, list(fields.keys()))
        else:
            logger.debug("Memory %s not found for update", memory_id)
        return updated

    async def delete(self, memory_id: str) -> bool:
        """Удалить воспоминание по ID.

        Args:
            memory_id: UUID воспоминания.

        Returns:
            True если удалено, False если не найдено.
        """
        result = await self.db.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,),
        )
        await self.db.commit()

        deleted = result.rowcount > 0
        if deleted:
            logger.debug("Memory %s deleted", memory_id)
        else:
            logger.debug("Memory %s not found for deletion", memory_id)
        return deleted

    async def list_recent(self, limit: int = 20) -> list[Memory]:
        """Получить последние воспоминания, отсортированные по дате создания.

        Args:
            limit: Максимальное количество результатов.

        Returns:
            Список Memory, отсортированный от новых к старым.
        """
        cursor = await self.db.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        logger.debug("Listed %d recent memories", len(rows))
        return [self._row_to_memory(row) for row in rows]

    async def search_by_type(self, memory_type: str, limit: int = 50) -> list[Memory]:
        """Поиск воспоминаний по типу.

        Args:
            memory_type: Тип ("conversation", "fact", "preference", "task").
            limit: Максимальное количество результатов.

        Returns:
            Список Memory данного типа.
        """
        cursor = await self.db.execute(
            "SELECT * FROM memories WHERE type = ? ORDER BY created_at DESC LIMIT ?",
            (memory_type, limit),
        )
        rows = await cursor.fetchall()
        logger.debug("Found %d memories of type '%s'", len(rows), memory_type)
        return [self._row_to_memory(row) for row in rows]

    async def close(self) -> None:
        """Закрыть соединение с БД."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.info("SQLite store connection closed")

    @staticmethod
    def _row_to_memory(row: aiosqlite.Row) -> Memory:
        """Конвертировать строку БД в объект Memory."""
        return Memory(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            importance=row["importance"],
            created_at=_parse_datetime(row["created_at"]),
            accessed_at=_parse_datetime(row["accessed_at"]),
            access_count=row["access_count"],
            metadata=Memory.metadata_from_json(row["metadata"]),
        )


def _parse_datetime(value: str | None) -> datetime:
    """Парсинг datetime из строки SQLite."""
    if value is None:
        return datetime.now()
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now()
