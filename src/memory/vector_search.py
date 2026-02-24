"""
Векторный поиск через sqlite-vec.

Использует расширение sqlite-vec для эффективного поиска
по косинусному сходству в пространстве эмбеддингов.
"""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING

import sqlite_vec

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# Размерность эмбеддингов (должна совпадать с EmbeddingGenerator)
# paraphrase-multilingual-MiniLM-L12-v2 = 384 dims
EMBEDDING_DIMENSIONS = 384

CREATE_VEC_TABLE_SQL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[{EMBEDDING_DIMENSIONS}]
);
"""


class VectorSearch:
    """Векторный поиск по эмбеддингам через sqlite-vec.

    Использует виртуальную таблицу vec0 для хранения и поиска
    векторов с косинусным расстоянием.

    Usage:
        vs = VectorSearch()
        await vs.init_db(db)
        await vs.add("id-123", [0.1, 0.2, ...])
        results = await vs.search(query_embedding, limit=10)
    """

    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init_db(self, db: aiosqlite.Connection) -> None:
        """Инициализировать расширение sqlite-vec и создать виртуальную таблицу.

        Args:
            db: Активное соединение aiosqlite.
        """
        self._db = db

        # Загружаем расширение sqlite-vec
        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())
        await db.enable_load_extension(False)

        await db.execute(CREATE_VEC_TABLE_SQL)
        await db.commit()
        logger.info("Vector search initialized (dimensions=%d)", EMBEDDING_DIMENSIONS)

    @property
    def db(self) -> aiosqlite.Connection:
        """Получить соединение с БД."""
        if self._db is None:
            raise RuntimeError("VectorSearch not initialized. Call init_db() first.")
        return self._db

    async def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Поиск ближайших соседей по косинусному расстоянию.

        Args:
            query_embedding: Вектор запроса (размерность = EMBEDDING_DIMENSIONS).
            limit: Максимальное количество результатов.

        Returns:
            Список кортежей (id, distance), отсортированных по расстоянию.
            distance — косинусное расстояние (0 = идентичные, 2 = противоположные).
        """
        query_blob = _embedding_to_blob(query_embedding)

        cursor = await self.db.execute(
            """
            SELECT id, distance
            FROM vec_memories
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (query_blob, limit),
        )
        rows = await cursor.fetchall()
        results = [(row[0], row[1]) for row in rows]
        logger.debug("Vector search returned %d results", len(results))
        return results

    async def add(self, memory_id: str, embedding: list[float]) -> None:
        """Добавить эмбеддинг в индекс.

        Args:
            memory_id: UUID воспоминания.
            embedding: Вектор эмбеддинга.
        """
        blob = _embedding_to_blob(embedding)

        await self.db.execute(
            "INSERT INTO vec_memories (id, embedding) VALUES (?, ?)",
            (memory_id, blob),
        )
        await self.db.commit()
        logger.debug("Added vector for memory %s", memory_id)

    async def remove(self, memory_id: str) -> None:
        """Удалить эмбеддинг из индекса.

        Args:
            memory_id: UUID воспоминания.
        """
        await self.db.execute(
            "DELETE FROM vec_memories WHERE id = ?",
            (memory_id,),
        )
        await self.db.commit()
        logger.debug("Removed vector for memory %s", memory_id)


def _embedding_to_blob(embedding: list[float]) -> bytes:
    """Конвертировать список float в bytes для sqlite-vec.

    sqlite-vec ожидает little-endian float32 массив.
    """
    return struct.pack(f"<{len(embedding)}f", *embedding)
