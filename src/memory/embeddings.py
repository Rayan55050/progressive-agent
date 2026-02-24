"""
Генерация эмбеддингов через fastembed (локально, без API).

Использует ONNX Runtime для инференса. Модель загружается один раз
при первом вызове (lazy loading), затем кэшируется в памяти.
Поддерживает русский и ещё ~50 языков.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

# Мультиязычная модель (русский + 50 языков), 384 dimensions, ~180MB
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DIMENSIONS = 384

# Максимальный размер LRU-кэша
DEFAULT_CACHE_SIZE = 512


class EmbeddingGenerator:
    """Генератор эмбеддингов через fastembed (локально).

    Использует ONNX Runtime, без внешних API.
    Модель загружается лениво при первом вызове generate().

    Usage:
        gen = EmbeddingGenerator()
        embedding = await gen.generate("Hello world")
        blob = EmbeddingGenerator.to_bytes(embedding)
        restored = EmbeddingGenerator.from_bytes(blob)
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        cache_size: int = DEFAULT_CACHE_SIZE,
        **_kwargs: Any,
    ) -> None:
        self._model_name = model
        self._model: Any = None
        self._dimensions = DEFAULT_DIMENSIONS
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

        logger.info(
            "EmbeddingGenerator configured (model=%s, cache=%d)",
            self._model_name,
            self._cache_size,
        )

    def _ensure_model(self) -> Any:
        """Загрузить модель при первом использовании (lazy loading)."""
        if self._model is None:
            from fastembed import TextEmbedding

            logger.info("Loading embedding model: %s ...", self._model_name)
            self._model = TextEmbedding(model_name=self._model_name)
            # Определяем реальную размерность из модели
            test = list(self._model.embed(["test"]))[0]
            self._dimensions = len(test)
            logger.info(
                "Embedding model loaded (dims=%d)",
                self._dimensions,
            )
        return self._model

    @property
    def dimensions(self) -> int:
        """Размерность эмбеддингов."""
        return self._dimensions

    async def generate(self, text: str) -> list[float]:
        """Сгенерировать эмбеддинг для одного текста.

        Args:
            text: Текст для эмбеддинга.

        Returns:
            Вектор размерности self._dimensions.
        """
        # Проверяем кэш
        if text in self._cache:
            self._cache.move_to_end(text)
            logger.debug("Embedding cache hit for text (len=%d)", len(text))
            return self._cache[text]

        logger.debug("Generating embedding for text (len=%d)", len(text))

        def _compute() -> list[float]:
            model = self._ensure_model()
            return list(model.embed([text]))[0].tolist()

        embedding = await asyncio.to_thread(_compute)

        # Сохраняем в кэш
        self._put_cache(text, embedding)

        return embedding

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """Сгенерировать эмбеддинги для пакета текстов.

        Тексты, уже имеющиеся в кэше, берутся оттуда.
        Остальные обрабатываются batch-инференсом.

        Args:
            texts: Список текстов для эмбеддинга.

        Returns:
            Список векторов в том же порядке, что и texts.
        """
        results: list[list[float] | None] = [None] * len(texts)
        texts_to_fetch: list[tuple[int, str]] = []

        # Забираем из кэша что есть
        for i, text in enumerate(texts):
            if text in self._cache:
                self._cache.move_to_end(text)
                results[i] = self._cache[text]
            else:
                texts_to_fetch.append((i, text))

        if not texts_to_fetch:
            logger.debug("All %d embeddings served from cache", len(texts))
            return results  # type: ignore[return-value]

        logger.debug(
            "Generating batch embeddings: %d local, %d from cache",
            len(texts_to_fetch),
            len(texts) - len(texts_to_fetch),
        )

        # Batch-инференс через fastembed (offload to thread)
        def _batch_compute() -> list:
            model = self._ensure_model()
            return list(model.embed([t for _, t in texts_to_fetch]))

        batch_embeddings = await asyncio.to_thread(_batch_compute)

        for (original_idx, text), emb in zip(texts_to_fetch, batch_embeddings):
            embedding = emb.tolist()
            results[original_idx] = embedding
            self._put_cache(text, embedding)

        return results  # type: ignore[return-value]

    def _put_cache(self, key: str, value: list[float]) -> None:
        """Добавить в LRU-кэш с вытеснением старых записей."""
        if key in self._cache:
            self._cache[key] = value
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._cache_size:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug("Evicted embedding from cache (key_len=%d)", len(evicted_key))
            self._cache[key] = value

    @staticmethod
    def to_bytes(embedding: list[float]) -> bytes:
        """Сериализовать эмбеддинг в bytes для хранения в SQLite BLOB.

        Использует struct для эффективной бинарной упаковки float32.

        Args:
            embedding: Вектор float'ов.

        Returns:
            Байтовое представление (little-endian float32 array).
        """
        return struct.pack(f"<{len(embedding)}f", *embedding)

    @staticmethod
    def from_bytes(blob: bytes) -> list[float]:
        """Десериализовать эмбеддинг из bytes (SQLite BLOB).

        Args:
            blob: Байтовое представление (little-endian float32 array).

        Returns:
            Вектор float'ов.
        """
        count = len(blob) // 4  # float32 = 4 bytes
        return list(struct.unpack(f"<{count}f", blob))
