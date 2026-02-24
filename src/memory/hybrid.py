"""
Гибридный поиск: vector + keyword + temporal decay + importance.

Объединяет результаты векторного (sqlite-vec) и полнотекстового (FTS5) поиска,
добавляя временное затухание и важность для финального ранжирования.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING

from src.memory.models import Memory

if TYPE_CHECKING:
    from src.memory.embeddings import EmbeddingGenerator
    from src.memory.keyword_search import KeywordSearch
    from src.memory.sqlite_store import SQLiteStore
    from src.memory.vector_search import VectorSearch

logger = logging.getLogger(__name__)

# Веса компонентов гибридного скоринга
WEIGHT_VECTOR = 0.4
WEIGHT_KEYWORD = 0.3
WEIGHT_TEMPORAL = 0.2
WEIGHT_IMPORTANCE = 0.1

# Lambda для temporal decay: exp(-lambda * days)
DEFAULT_TEMPORAL_DECAY_LAMBDA = 0.01


class HybridSearch:
    """Гибридный поиск по памяти агента.

    Комбинирует четыре сигнала:
    1. Vector similarity (sqlite-vec, cosine distance) — семантическое сходство
    2. Keyword match (FTS5, BM25) — точное совпадение ключевых слов
    3. Temporal decay — предпочтение недавним воспоминаниям
    4. Importance — важность воспоминания (0.0-1.0)

    Combined score = 0.4 * vector + 0.3 * keyword + 0.2 * temporal + 0.1 * importance

    Usage:
        hs = HybridSearch(vector_search, keyword_search, sqlite_store, embedding_gen)
        results = await hs.search("что мы обсуждали вчера?", limit=10)
    """

    def __init__(
        self,
        vector_search: VectorSearch | None,
        keyword_search: KeywordSearch,
        sqlite_store: SQLiteStore,
        embedding_generator: EmbeddingGenerator | None,
        temporal_decay_lambda: float = DEFAULT_TEMPORAL_DECAY_LAMBDA,
    ) -> None:
        self._vector_search = vector_search
        self._keyword_search = keyword_search
        self._sqlite_store = sqlite_store
        self._embedding_generator = embedding_generator
        self._decay_lambda = temporal_decay_lambda

    async def search(self, query: str, limit: int = 10) -> list[Memory]:
        """Выполнить гибридный поиск.

        1. Генерирует эмбеддинг запроса (если доступен)
        2. Параллельно ищет по вектору и ключевым словам
        3. Нормализует скоры к 0-1
        4. Рассчитывает temporal decay для каждого результата
        5. Комбинирует скоры с весами
        6. Дедуплицирует, сортирует, возвращает top-K

        Args:
            query: Поисковый запрос (естественный язык).
            limit: Максимальное количество результатов.

        Returns:
            Список Memory с заполненным полем score, отсортированный
            по релевантности (от наиболее к наименее релевантному).
        """
        logger.debug("Hybrid search for query: '%s' (limit=%d)", query, limit)

        fetch_limit = limit * 3
        vector_results: list[tuple[str, float]] = []

        # 1. Vector search (only if embeddings are available)
        if self._embedding_generator and self._vector_search:
            query_embedding = await self._embedding_generator.generate(query)
            vector_results = await self._vector_search.search(query_embedding, limit=fetch_limit)

        # 2. Keyword search (always available)
        keyword_results = await self._keyword_search.search(query, limit=fetch_limit)

        # 3. Нормализуем скоры к 0-1
        vector_scores = _normalize_vector_scores(vector_results)
        keyword_scores = _normalize_keyword_scores(keyword_results)

        # 4. Собираем все уникальные ID
        all_ids: set[str] = set()
        all_ids.update(vector_scores.keys())
        all_ids.update(keyword_scores.keys())

        if not all_ids:
            logger.debug("Hybrid search returned no results")
            return []

        # 5. Для каждого ID рассчитываем финальный скор
        scored_memories: list[tuple[str, float, Memory]] = []
        now = datetime.now()

        for memory_id in all_ids:
            # Read-only access — don't reset accessed_at (preserves temporal decay)
            memory = await self._sqlite_store.get(memory_id, update_access=False)
            if memory is None:
                logger.warning("Memory %s found in index but missing from store", memory_id)
                continue

            # Компоненты скора
            v_score = vector_scores.get(memory_id, 0.0)
            k_score = keyword_scores.get(memory_id, 0.0)

            # Temporal decay: exp(-lambda * days_since_access)
            days_since_access = (now - memory.accessed_at).total_seconds() / 86400.0
            t_score = math.exp(-self._decay_lambda * days_since_access)

            # Importance
            i_score = memory.importance

            # Combined score
            combined = (
                WEIGHT_VECTOR * v_score
                + WEIGHT_KEYWORD * k_score
                + WEIGHT_TEMPORAL * t_score
                + WEIGHT_IMPORTANCE * i_score
            )

            scored_memories.append((memory_id, combined, memory))

        # 6. Сортируем по скору (от большего к меньшему) и берём top-K
        scored_memories.sort(key=lambda x: x[1], reverse=True)
        top_entries = scored_memories[:limit]

        # 7. Собираем финальный результат (reuse cached memories, no second get)
        results: list[Memory] = []
        for _mid, score, memory in top_entries:
            memory.score = score
            results.append(memory)

        logger.debug(
            "Hybrid search returned %d results (vector=%d, keyword=%d, merged=%d)",
            len(results),
            len(vector_results),
            len(keyword_results),
            len(all_ids),
        )

        return results


def _normalize_vector_scores(results: list[tuple[str, float]]) -> dict[str, float]:
    """Нормализовать cosine distance к similarity score 0-1.

    Cosine distance: 0 = идентичные, 2 = противоположные.
    Similarity = 1 - distance/2 -> [0, 1].

    Args:
        results: Список (id, distance) от VectorSearch.

    Returns:
        Dict {id: normalized_score}.
    """
    if not results:
        return {}

    scores: dict[str, float] = {}
    for memory_id, distance in results:
        # Cosine distance ∈ [0, 2] -> similarity ∈ [0, 1]
        similarity = max(0.0, 1.0 - distance / 2.0)
        scores[memory_id] = similarity

    return scores


def _normalize_keyword_scores(results: list[tuple[str, float]]) -> dict[str, float]:
    """Нормализовать BM25 scores к 0-1 (min-max normalization).

    BM25 scores после инвертирования: больше = лучше, но диапазон произвольный.

    Args:
        results: Список (id, bm25_score) от KeywordSearch (уже инвертированные).

    Returns:
        Dict {id: normalized_score}.
    """
    if not results:
        return {}

    raw_scores = [score for _, score in results]
    min_score = min(raw_scores)
    max_score = max(raw_scores)
    score_range = max_score - min_score

    scores: dict[str, float] = {}
    for memory_id, score in results:
        if score_range > 0:
            normalized = (score - min_score) / score_range
        else:
            # Все скоры одинаковые — ставим 1.0
            normalized = 1.0
        scores[memory_id] = normalized

    return scores
