"""
MemoryManager — центральный интерфейс системы памяти.

Координирует работу всех компонентов памяти:
SQLiteStore, EmbeddingGenerator, VectorSearch, KeywordSearch, HybridSearch.

Единственный класс, который должен использоваться внешними модулями
(Agent, Skills и т.д.).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from src.memory.embeddings import EmbeddingGenerator
from src.memory.hybrid import HybridSearch
from src.memory.keyword_search import KeywordSearch
from src.memory.models import Memory
from src.memory.sqlite_store import SQLiteStore
from src.memory.vector_search import VectorSearch

logger = logging.getLogger(__name__)


class MemoryManager:
    """Центральный интерфейс системы памяти агента.

    Координирует все компоненты: хранение, эмбеддинги,
    векторный поиск, полнотекстовый поиск, гибридный поиск.

    Usage:
        manager = MemoryManager(db_path="data/memory.db")
        await manager.init()

        # Сохранить
        memory_id = await manager.store("Пользователь любит Python", type="preference")

        # Найти
        results = await manager.search("что пользователь предпочитает?")

        # Закрыть
        await manager.close()
    """

    def __init__(
        self,
        db_path: str,
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        **_kwargs: Any,
    ) -> None:
        self._db_path = db_path
        self._embedding_model = embedding_model

        # Компоненты (инициализируются в init())
        self._store: SQLiteStore | None = None
        self._embeddings: EmbeddingGenerator | None = None
        self._vector_search: VectorSearch | None = None
        self._keyword_search: KeywordSearch | None = None
        self._hybrid_search: HybridSearch | None = None
        self._initialized = False

    @property
    def sqlite_store(self) -> SQLiteStore:
        """Доступ к SQLite-хранилищу."""
        if self._store is None:
            raise RuntimeError("MemoryManager not initialized. Call init() first.")
        return self._store

    @property
    def is_initialized(self) -> bool:
        """Проверка, инициализирован ли менеджер."""
        return self._initialized

    async def init(self) -> None:
        """Инициализировать все компоненты памяти.

        Создаёт/открывает БД, загружает расширения, создаёт таблицы.
        Должно быть вызвано перед любым другим методом.
        """
        if self._initialized:
            logger.warning("MemoryManager already initialized, skipping")
            return

        logger.info("Initializing MemoryManager (db=%s)", self._db_path)

        # 1. SQLite store
        self._store = SQLiteStore(self._db_path)
        await self._store.init()

        # 2. Embedding generator (local fastembed, no API key needed)
        self._embeddings = EmbeddingGenerator(model=self._embedding_model)

        # 3. Vector search (uses same DB connection)
        self._vector_search = VectorSearch()
        await self._vector_search.init_db(self._store.db)

        # 4. Keyword search (uses same DB connection)
        self._keyword_search = KeywordSearch()
        await self._keyword_search.init_db(self._store.db)

        # 5. Hybrid search
        self._hybrid_search = HybridSearch(
            vector_search=self._vector_search,
            keyword_search=self._keyword_search,
            sqlite_store=self._store,
            embedding_generator=self._embeddings,
        )

        self._initialized = True
        logger.info("MemoryManager initialized successfully")

    async def store(
        self,
        content: str,
        type: str = "conversation",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Сохранить новое воспоминание.

        Сохраняет в SQLite, генерирует эмбеддинг, добавляет в индексы.

        Args:
            content: Текстовое содержимое воспоминания.
            type: Тип — "conversation", "fact", "preference", "task".
            importance: Важность от 0.0 до 1.0.
            metadata: Дополнительные данные.

        Returns:
            UUID созданного воспоминания.
        """
        self._ensure_initialized()

        memory_id = str(uuid4())
        now = datetime.now()

        memory = Memory(
            id=memory_id,
            content=content,
            type=type,
            importance=importance,
            created_at=now,
            accessed_at=now,
            access_count=0,
            metadata=metadata or {},
        )

        # 1. Сохраняем в основную таблицу
        await self._store.store(memory)  # type: ignore[union-attr]

        # 2. Генерируем эмбеддинг и добавляем в vector index (if available)
        if self._embeddings and self._vector_search:
            try:
                embedding = await self._embeddings.generate(content)
                await self._vector_search.add(memory_id, embedding)

                # Сохраняем эмбеддинг как BLOB в основной таблице
                blob = EmbeddingGenerator.to_bytes(embedding)
                await self._store.update(memory_id, embedding=blob)  # type: ignore[union-attr]
            except Exception:
                logger.exception("Failed to generate/store embedding for memory %s", memory_id)

        # 3. Добавляем в FTS5 index
        try:
            await self._keyword_search.add(memory_id, content, type)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Failed to add FTS entry for memory %s", memory_id)

        logger.info("Stored memory %s (type=%s, importance=%.2f)", memory_id, type, importance)
        return memory_id

    async def save(
        self,
        content: str,
        memory_type: str = "conversation",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Alias for store() — used by Agent."""
        return await self.store(
            content=content,
            type=memory_type,
            importance=importance,
            metadata=metadata,
        )

    async def search(self, query: str, limit: int = 10) -> list[Memory]:
        """Гибридный поиск по памяти.

        Комбинирует vector similarity, keyword match,
        temporal decay и importance для ранжирования.

        Args:
            query: Поисковый запрос (естественный язык).
            limit: Максимальное количество результатов.

        Returns:
            Список Memory, отсортированный по релевантности.
        """
        self._ensure_initialized()
        return await self._hybrid_search.search(query, limit=limit)  # type: ignore[union-attr]

    async def get(self, memory_id: str) -> Memory | None:
        """Получить воспоминание по ID.

        Обновляет accessed_at и access_count.

        Args:
            memory_id: UUID воспоминания.

        Returns:
            Memory или None если не найдено.
        """
        self._ensure_initialized()
        return await self._store.get(memory_id)  # type: ignore[union-attr]

    async def update_importance(self, memory_id: str, importance: float) -> bool:
        """Обновить важность воспоминания.

        Args:
            memory_id: UUID воспоминания.
            importance: Новое значение (0.0-1.0).

        Returns:
            True если обновлено, False если не найдено.
        """
        self._ensure_initialized()
        importance = max(0.0, min(1.0, importance))
        result = await self._store.update(memory_id, importance=importance)  # type: ignore[union-attr]
        if result:
            logger.info("Updated importance of memory %s to %.2f", memory_id, importance)
        return result

    async def cleanup(
        self,
        older_than_days: int = 90,
        min_importance: float = 0.3,
    ) -> int:
        """Очистить старые неважные воспоминания.

        Удаляет воспоминания, которые:
        - Последний доступ старше older_than_days дней
        - Важность ниже min_importance

        Args:
            older_than_days: Порог давности в днях.
            min_importance: Порог важности.

        Returns:
            Количество удалённых воспоминаний.
        """
        self._ensure_initialized()

        cutoff = datetime.now() - timedelta(days=older_than_days)
        cutoff_str = cutoff.isoformat()

        logger.info(
            "Cleaning up memories older than %d days with importance < %.2f",
            older_than_days,
            min_importance,
        )

        # Находим кандидатов на удаление
        cursor = await self._store.db.execute(  # type: ignore[union-attr]
            """
            SELECT id FROM memories
            WHERE accessed_at < ? AND importance < ?
            """,
            (cutoff_str, min_importance),
        )
        rows = await cursor.fetchall()
        ids_to_delete = [row[0] for row in rows]

        if not ids_to_delete:
            logger.info("No memories to clean up")
            return 0

        # Удаляем из всех индексов
        for memory_id in ids_to_delete:
            try:
                await self._vector_search.remove(memory_id)  # type: ignore[union-attr]
            except Exception:
                logger.debug("Vector entry for %s not found during cleanup", memory_id)

            try:
                await self._keyword_search.remove(memory_id)  # type: ignore[union-attr]
            except Exception:
                logger.debug("FTS entry for %s not found during cleanup", memory_id)

            await self._store.delete(memory_id)  # type: ignore[union-attr]

        logger.info("Cleaned up %d memories", len(ids_to_delete))
        return len(ids_to_delete)

    async def get_recent_conversations(
        self,
        user_id: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Get recent conversation memories in chronological order.

        Used to restore conversation history after bot restart.

        Args:
            user_id: Filter by user_id in metadata. None = all users.
            limit: Maximum number of conversation memories to return.

        Returns:
            List of Memory objects, oldest first (chronological order).
        """
        self._ensure_initialized()

        if user_id:
            # Filter by user_id stored in metadata JSON
            cursor = await self._store.db.execute(
                """
                SELECT * FROM memories
                WHERE type = 'conversation'
                  AND json_extract(metadata, '$.user_id') = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        else:
            cursor = await self._store.db.execute(
                """
                SELECT * FROM memories
                WHERE type = 'conversation'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )

        rows = await cursor.fetchall()
        memories = [SQLiteStore._row_to_memory(row) for row in rows]
        # Reverse to chronological order (oldest first)
        memories.reverse()
        return memories

    async def purge_orphans(self) -> int:
        """Remove orphaned entries from vector + FTS indexes.

        Finds IDs in indexes that no longer exist in the store and removes them.
        Should be called at startup to fix index/store desync.
        """
        self._ensure_initialized()
        removed = 0

        try:
            db = self._store.db

            # Collect orphan IDs from vector index
            vec_orphans: list[str] = []
            try:
                cursor = await db.execute("SELECT id FROM vec_memories")
                rows = await cursor.fetchall()
                for (vid,) in rows:
                    mem = await self._store.get(vid, update_access=False)
                    if mem is None:
                        vec_orphans.append(vid)
            except Exception as e:
                logger.debug("Could not scan vec_memories: %s", e)

            # Collect orphan IDs from FTS index
            fts_orphans: list[str] = []
            try:
                cursor = await db.execute("SELECT id FROM memories_fts")
                rows = await cursor.fetchall()
                for (fid,) in rows:
                    mem = await self._store.get(fid, update_access=False)
                    if mem is None:
                        fts_orphans.append(fid)
            except Exception as e:
                logger.debug("Could not scan memories_fts: %s", e)

            # Remove orphans
            for oid in vec_orphans:
                await self._vector_search.remove(oid)
                removed += 1
            for oid in fts_orphans:
                await self._keyword_search.remove(oid)
                removed += 1

            if removed:
                logger.info(
                    "Purged %d orphaned index entries (vec=%d, fts=%d)",
                    removed, len(vec_orphans), len(fts_orphans),
                )
        except Exception as e:
            logger.error("Orphan purge failed: %s", e)

        return removed

    async def close(self) -> None:
        """Закрыть все соединения и освободить ресурсы."""
        if self._store is not None:
            await self._store.close()
        self._initialized = False
        logger.info("MemoryManager closed")

    def _ensure_initialized(self) -> None:
        """Проверить, что менеджер инициализирован."""
        if not self._initialized:
            raise RuntimeError("MemoryManager not initialized. Call init() first.")
