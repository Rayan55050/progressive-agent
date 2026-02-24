"""
Полнотекстовый поиск через SQLite FTS5.

Использует FTS5 с BM25-ранжированием для keyword-поиска
по содержимому воспоминаний.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

CREATE_FTS_TABLE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    content,
    type
);
"""


class KeywordSearch:
    """Полнотекстовый поиск через SQLite FTS5.

    Использует BM25-скоринг для ранжирования результатов.
    Таблица memories_fts синхронизируется с основной таблицей memories
    через явные add/remove вызовы.

    Usage:
        ks = KeywordSearch()
        await ks.init_db(db)
        await ks.add("id-123", "some text content", "conversation")
        results = await ks.search("text", limit=10)
    """

    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init_db(self, db: aiosqlite.Connection) -> None:
        """Создать виртуальную таблицу FTS5.

        Args:
            db: Активное соединение aiosqlite.
        """
        self._db = db
        await db.execute(CREATE_FTS_TABLE_SQL)
        await db.commit()
        logger.info("Keyword search (FTS5) initialized")

    @property
    def db(self) -> aiosqlite.Connection:
        """Получить соединение с БД."""
        if self._db is None:
            raise RuntimeError("KeywordSearch not initialized. Call init_db() first.")
        return self._db

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Полнотекстовый поиск по BM25.

        Args:
            query: Поисковый запрос (поддерживает FTS5 синтаксис).
            limit: Максимальное количество результатов.

        Returns:
            Список кортежей (id, bm25_score).
            bm25_score отрицательный (чем ближе к 0, тем хуже матч;
            более отрицательные значения — лучше). Мы возвращаем
            абсолютное значение, так что больше = лучше.
        """
        # Экранируем спецсимволы FTS5 для безопасности
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            logger.debug("Empty query after sanitization, returning empty results")
            return []

        cursor = await self.db.execute(
            """
            SELECT id, bm25(memories_fts) AS score
            FROM memories_fts
            WHERE memories_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (safe_query, limit),
        )
        rows = await cursor.fetchall()

        # bm25() возвращает отрицательные значения (ближе к 0 = хуже).
        # Инвертируем знак чтобы больше = лучше.
        results = [(row[0], -row[1]) for row in rows]
        logger.debug("Keyword search for '%s' returned %d results", query, len(results))
        return results

    async def add(self, memory_id: str, content: str, memory_type: str) -> None:
        """Добавить документ в FTS5-индекс.

        Args:
            memory_id: UUID воспоминания.
            content: Текстовое содержимое.
            memory_type: Тип воспоминания.
        """
        await self.db.execute(
            "INSERT INTO memories_fts (id, content, type) VALUES (?, ?, ?)",
            (memory_id, content, memory_type),
        )
        await self.db.commit()
        logger.debug("Added FTS entry for memory %s", memory_id)

    async def remove(self, memory_id: str) -> None:
        """Удалить документ из FTS5-индекса.

        Args:
            memory_id: UUID воспоминания.
        """
        await self.db.execute(
            "DELETE FROM memories_fts WHERE id = ?",
            (memory_id,),
        )
        await self.db.commit()
        logger.debug("Removed FTS entry for memory %s", memory_id)


def _sanitize_fts_query(query: str) -> str:
    """Санитизация поискового запроса для FTS5.

    Убирает спецсимволы FTS5, оставляя только слова.
    Если все слова удалены, возвращает пустую строку.

    Args:
        query: Исходный поисковый запрос.

    Returns:
        Безопасный запрос для FTS5 MATCH.
    """
    # Удаляем символы, которые имеют специальное значение в FTS5
    # Includes FTS5 operators and punctuation that causes syntax errors
    special_chars = set('"*^{}():-+?!@#$%&=~|\\/<>[];,.')
    cleaned = "".join(c if c not in special_chars else " " for c in query)

    # Разбиваем на слова, фильтруем пустые и FTS5 operator keywords
    fts5_operators = {"AND", "OR", "NOT", "NEAR"}
    words = [
        w.strip() for w in cleaned.split()
        if w.strip() and w.strip().upper() not in fts5_operators
    ]

    if not words:
        return ""

    # Quote each word to prevent FTS5 operator interpretation
    return " OR ".join(f'"{w}"' for w in words)
