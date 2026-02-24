"""
Tests for memory system:
- SQLiteStore CRUD operations (in-memory DB)
- EmbeddingGenerator (local fastembed)
- KeywordSearch FTS5
- HybridSearch score combination
- MemoryManager store and search
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from src.memory.embeddings import EmbeddingGenerator
from src.memory.hybrid import (
    WEIGHT_IMPORTANCE,
    WEIGHT_KEYWORD,
    WEIGHT_TEMPORAL,
    WEIGHT_VECTOR,
    HybridSearch,
    _normalize_keyword_scores,
    _normalize_vector_scores,
)
from src.memory.keyword_search import KeywordSearch, _sanitize_fts_query
from src.memory.models import Memory
from src.memory.sqlite_store import SQLiteStore


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
async def sqlite_store() -> SQLiteStore:
    """Create an in-memory SQLiteStore for testing."""
    store = SQLiteStore(":memory:")
    await store.init()
    yield store
    await store.close()


@pytest.fixture
async def keyword_search(sqlite_store: SQLiteStore) -> KeywordSearch:
    """Create a KeywordSearch connected to the in-memory store."""
    ks = KeywordSearch()
    await ks.init_db(sqlite_store.db)
    return ks


@pytest.fixture
def sample_memory() -> Memory:
    """Create a sample Memory object."""
    return Memory(
        id="mem-001",
        content="User prefers Python over JavaScript",
        type="preference",
        importance=0.8,
        created_at=datetime.now(),
        accessed_at=datetime.now(),
        access_count=0,
        metadata={"source": "conversation"},
    )


@pytest.fixture
def sample_memories() -> list[Memory]:
    """Create multiple sample Memory objects."""
    now = datetime.now()
    return [
        Memory(
            id="mem-001",
            content="User prefers Python programming",
            type="preference",
            importance=0.9,
            created_at=now,
            accessed_at=now,
        ),
        Memory(
            id="mem-002",
            content="Had a conversation about machine learning",
            type="conversation",
            importance=0.5,
            created_at=now - timedelta(days=2),
            accessed_at=now - timedelta(days=2),
        ),
        Memory(
            id="mem-003",
            content="Task: finish the report by Friday",
            type="task",
            importance=0.7,
            created_at=now - timedelta(days=1),
            accessed_at=now - timedelta(days=1),
        ),
    ]


# =========================================================================
# Tests: SQLiteStore
# =========================================================================


class TestSQLiteStore:
    """Tests for SQLiteStore CRUD operations using in-memory DB."""

    @pytest.mark.asyncio
    async def test_store_and_get(self, sqlite_store: SQLiteStore, sample_memory: Memory) -> None:
        """Store a memory and retrieve it by ID."""
        stored_id = await sqlite_store.store(sample_memory)
        assert stored_id == "mem-001"

        retrieved = await sqlite_store.get("mem-001")
        assert retrieved is not None
        assert retrieved.id == "mem-001"
        assert retrieved.content == "User prefers Python over JavaScript"
        assert retrieved.type == "preference"
        assert retrieved.importance == pytest.approx(0.8)
        assert retrieved.metadata == {"source": "conversation"}

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, sqlite_store: SQLiteStore) -> None:
        """Getting a non-existent memory returns None."""
        result = await sqlite_store.get("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_update(self, sqlite_store: SQLiteStore, sample_memory: Memory) -> None:
        """Update fields of an existing memory."""
        await sqlite_store.store(sample_memory)

        updated = await sqlite_store.update("mem-001", importance=0.95, type="fact")
        assert updated is True

        retrieved = await sqlite_store.get("mem-001")
        assert retrieved is not None
        assert retrieved.importance == pytest.approx(0.95)
        assert retrieved.type == "fact"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, sqlite_store: SQLiteStore) -> None:
        """Updating a non-existent memory returns False."""
        result = await sqlite_store.update("nonexistent", importance=0.5)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete(self, sqlite_store: SQLiteStore, sample_memory: Memory) -> None:
        """Delete a memory by ID."""
        await sqlite_store.store(sample_memory)

        deleted = await sqlite_store.delete("mem-001")
        assert deleted is True

        retrieved = await sqlite_store.get("mem-001")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, sqlite_store: SQLiteStore) -> None:
        """Deleting a non-existent memory returns False."""
        result = await sqlite_store.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_recent(
        self, sqlite_store: SQLiteStore, sample_memories: list[Memory]
    ) -> None:
        """list_recent() returns memories ordered by creation date (newest first)."""
        for mem in sample_memories:
            await sqlite_store.store(mem)

        recent = await sqlite_store.list_recent(limit=2)
        assert len(recent) == 2
        # Most recent first
        assert recent[0].id == "mem-001"

    @pytest.mark.asyncio
    async def test_search_by_type(
        self, sqlite_store: SQLiteStore, sample_memories: list[Memory]
    ) -> None:
        """search_by_type() filters memories by type."""
        for mem in sample_memories:
            await sqlite_store.store(mem)

        preferences = await sqlite_store.search_by_type("preference")
        assert len(preferences) == 1
        assert preferences[0].type == "preference"

    @pytest.mark.asyncio
    async def test_get_updates_access_count(
        self, sqlite_store: SQLiteStore, sample_memory: Memory
    ) -> None:
        """Getting a memory increments access_count."""
        await sqlite_store.store(sample_memory)

        mem1 = await sqlite_store.get("mem-001")
        assert mem1 is not None
        assert mem1.access_count == 1

        mem2 = await sqlite_store.get("mem-001")
        assert mem2 is not None
        assert mem2.access_count == 2

    @pytest.mark.asyncio
    async def test_store_generates_id_if_empty(self, sqlite_store: SQLiteStore) -> None:
        """Store generates a UUID if memory.id is empty."""
        mem = Memory(id="", content="Test content")
        stored_id = await sqlite_store.store(mem)
        assert stored_id != ""
        assert len(stored_id) > 0

        retrieved = await sqlite_store.get(stored_id)
        assert retrieved is not None
        assert retrieved.content == "Test content"


# =========================================================================
# Tests: EmbeddingGenerator
# =========================================================================


class TestEmbeddingGenerator:
    """Tests for EmbeddingGenerator (local fastembed)."""

    def test_creation(self) -> None:
        """EmbeddingGenerator initializes with correct parameters."""
        gen = EmbeddingGenerator(model="test-model")
        assert gen.dimensions == 384  # default before model loaded
        assert gen._model is None  # lazy loading

    @pytest.mark.asyncio
    async def test_generate(self) -> None:
        """generate() calls fastembed model and returns vector."""
        import numpy as np

        gen = EmbeddingGenerator()
        # Mock the model to avoid downloading
        mock_model = MagicMock()
        mock_model.embed = MagicMock(return_value=[np.array([0.1] * 384)])
        gen._model = mock_model
        gen._dimensions = 384

        result = await gen.generate("Hello world")

        assert len(result) == 384
        assert result == [0.1] * 384
        mock_model.embed.assert_called_once_with(["Hello world"])

    @pytest.mark.asyncio
    async def test_generate_uses_cache(self) -> None:
        """generate() returns cached result on second call for same text."""
        import numpy as np

        gen = EmbeddingGenerator()
        mock_model = MagicMock()
        mock_model.embed = MagicMock(return_value=[np.array([0.5] * 384)])
        gen._model = mock_model
        gen._dimensions = 384

        result1 = await gen.generate("Same text")
        result2 = await gen.generate("Same text")

        assert result1 == result2
        # Only called once, second call from cache
        assert mock_model.embed.call_count == 1

    def test_to_bytes_and_from_bytes(self) -> None:
        """to_bytes() and from_bytes() are inverses."""
        original = [0.1, 0.2, 0.3, -0.5, 1.0]
        blob = EmbeddingGenerator.to_bytes(original)
        restored = EmbeddingGenerator.from_bytes(blob)

        assert len(restored) == len(original)
        for a, b in zip(original, restored):
            assert a == pytest.approx(b, abs=1e-6)

    def test_to_bytes_format(self) -> None:
        """to_bytes() produces little-endian float32 binary."""
        embedding = [1.0, 2.0]
        blob = EmbeddingGenerator.to_bytes(embedding)
        # float32 = 4 bytes, so 2 floats = 8 bytes
        assert len(blob) == 8
        unpacked = struct.unpack("<2f", blob)
        assert unpacked == pytest.approx((1.0, 2.0))


# =========================================================================
# Tests: KeywordSearch
# =========================================================================


class TestKeywordSearch:
    """Tests for KeywordSearch FTS5."""

    @pytest.mark.asyncio
    async def test_add_and_search(self, keyword_search: KeywordSearch) -> None:
        """Add entries and search by keyword."""
        await keyword_search.add("mem-001", "Python programming language", "preference")
        await keyword_search.add("mem-002", "JavaScript framework React", "conversation")
        await keyword_search.add("mem-003", "Python machine learning project", "task")

        results = await keyword_search.search("Python")
        assert len(results) >= 1
        ids = [r[0] for r in results]
        assert "mem-001" in ids

    @pytest.mark.asyncio
    async def test_search_bm25_scores(self, keyword_search: KeywordSearch) -> None:
        """Search results have positive BM25 scores (inverted from raw)."""
        await keyword_search.add("mem-001", "Python is great", "fact")
        await keyword_search.add("mem-002", "Python Python Python", "fact")

        results = await keyword_search.search("Python")
        assert len(results) >= 1
        for _id, score in results:
            assert score >= 0  # Scores are inverted to positive

    @pytest.mark.asyncio
    async def test_search_no_results(self, keyword_search: KeywordSearch) -> None:
        """Search returns empty list when no match."""
        await keyword_search.add("mem-001", "Python programming", "fact")

        results = await keyword_search.search("JavaScript")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_remove(self, keyword_search: KeywordSearch) -> None:
        """Remove entry from FTS index."""
        await keyword_search.add("mem-001", "Python is great", "fact")
        await keyword_search.remove("mem-001")

        results = await keyword_search.search("Python")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_limit(self, keyword_search: KeywordSearch) -> None:
        """Search respects limit parameter."""
        for i in range(10):
            await keyword_search.add(f"mem-{i:03d}", f"Python programming topic {i}", "fact")

        results = await keyword_search.search("Python", limit=3)
        assert len(results) <= 3

    def test_sanitize_fts_query(self) -> None:
        """_sanitize_fts_query removes FTS5 special characters."""
        assert _sanitize_fts_query('"hello" world') == '"hello" OR "world"'
        assert _sanitize_fts_query("test*") == '"test"'
        assert _sanitize_fts_query("") == ""
        assert _sanitize_fts_query("simple query") == '"simple" OR "query"'
        # FTS5 operator words are stripped
        assert _sanitize_fts_query("NOT working") == '"working"'
        assert _sanitize_fts_query("this AND that") == '"this" OR "that"'


# =========================================================================
# Tests: HybridSearch
# =========================================================================


class TestHybridSearch:
    """Tests for HybridSearch score combination."""

    def test_normalize_vector_scores(self) -> None:
        """_normalize_vector_scores converts cosine distance to similarity."""
        results = [
            ("id-1", 0.0),   # distance=0 -> similarity=1.0
            ("id-2", 1.0),   # distance=1 -> similarity=0.5
            ("id-3", 2.0),   # distance=2 -> similarity=0.0
        ]
        scores = _normalize_vector_scores(results)

        assert scores["id-1"] == pytest.approx(1.0)
        assert scores["id-2"] == pytest.approx(0.5)
        assert scores["id-3"] == pytest.approx(0.0)

    def test_normalize_vector_scores_empty(self) -> None:
        """_normalize_vector_scores returns empty dict for empty input."""
        assert _normalize_vector_scores([]) == {}

    def test_normalize_keyword_scores(self) -> None:
        """_normalize_keyword_scores applies min-max normalization."""
        results = [
            ("id-1", 10.0),
            ("id-2", 5.0),
            ("id-3", 0.0),
        ]
        scores = _normalize_keyword_scores(results)

        assert scores["id-1"] == pytest.approx(1.0)
        assert scores["id-2"] == pytest.approx(0.5)
        assert scores["id-3"] == pytest.approx(0.0)

    def test_normalize_keyword_scores_all_equal(self) -> None:
        """All-equal BM25 scores normalize to 1.0."""
        results = [("id-1", 5.0), ("id-2", 5.0)]
        scores = _normalize_keyword_scores(results)
        assert scores["id-1"] == 1.0
        assert scores["id-2"] == 1.0

    def test_normalize_keyword_scores_empty(self) -> None:
        """Empty keyword results return empty dict."""
        assert _normalize_keyword_scores([]) == {}

    @pytest.mark.asyncio
    async def test_search_combines_scores(self) -> None:
        """HybridSearch.search() combines vector, keyword, temporal, importance."""
        now = datetime.now()

        # Mock components
        mock_vector = MagicMock()
        mock_vector.search = AsyncMock(
            return_value=[("mem-001", 0.2)]  # low distance = high similarity
        )

        mock_keyword = MagicMock()
        mock_keyword.search = AsyncMock(
            return_value=[("mem-001", 5.0)]  # BM25 score
        )

        mock_store = MagicMock()
        test_memory = Memory(
            id="mem-001",
            content="Python is great",
            type="fact",
            importance=0.8,
            created_at=now,
            accessed_at=now,
            access_count=1,
        )
        mock_store.get = AsyncMock(return_value=test_memory)

        mock_embeddings = MagicMock()
        mock_embeddings.generate = AsyncMock(return_value=[0.1] * 384)

        hybrid = HybridSearch(
            vector_search=mock_vector,
            keyword_search=mock_keyword,
            sqlite_store=mock_store,
            embedding_generator=mock_embeddings,
        )

        results = await hybrid.search("Python", limit=10)

        assert len(results) >= 1
        assert results[0].id == "mem-001"
        assert results[0].score is not None
        assert results[0].score > 0

    @pytest.mark.asyncio
    async def test_search_no_results(self) -> None:
        """HybridSearch returns empty list when no matches found."""
        mock_vector = MagicMock()
        mock_vector.search = AsyncMock(return_value=[])

        mock_keyword = MagicMock()
        mock_keyword.search = AsyncMock(return_value=[])

        mock_store = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.generate = AsyncMock(return_value=[0.1] * 384)

        hybrid = HybridSearch(
            vector_search=mock_vector,
            keyword_search=mock_keyword,
            sqlite_store=mock_store,
            embedding_generator=mock_embeddings,
        )

        results = await hybrid.search("nonexistent query", limit=10)
        assert results == []

    def test_weight_constants_sum_to_one(self) -> None:
        """Hybrid search weights should sum to 1.0."""
        total = WEIGHT_VECTOR + WEIGHT_KEYWORD + WEIGHT_TEMPORAL + WEIGHT_IMPORTANCE
        assert total == pytest.approx(1.0)


# =========================================================================
# Tests: MemoryManager
# =========================================================================


class TestMemoryManager:
    """Tests for MemoryManager store and search (fully mocked)."""

    @pytest.mark.asyncio
    @patch("src.memory.manager.SQLiteStore")
    @patch("src.memory.manager.EmbeddingGenerator")
    @patch("src.memory.manager.VectorSearch")
    @patch("src.memory.manager.KeywordSearch")
    @patch("src.memory.manager.HybridSearch")
    async def test_store(
        self,
        mock_hybrid_cls: MagicMock,
        mock_kw_cls: MagicMock,
        mock_vec_cls: MagicMock,
        mock_emb_cls: MagicMock,
        mock_store_cls: MagicMock,
    ) -> None:
        """MemoryManager.store() saves to store, generates embedding, indexes."""
        from src.memory.manager import MemoryManager

        # Configure mocks
        mock_store_inst = MagicMock()
        mock_store_inst.init = AsyncMock()
        mock_store_inst.store = AsyncMock(return_value="mem-001")
        mock_store_inst.update = AsyncMock(return_value=True)
        mock_store_inst.db = MagicMock()
        mock_store_inst.close = AsyncMock()
        mock_store_cls.return_value = mock_store_inst

        mock_emb_inst = MagicMock()
        mock_emb_inst.generate = AsyncMock(return_value=[0.1] * 384)
        mock_emb_cls.return_value = mock_emb_inst
        mock_emb_cls.to_bytes = MagicMock(return_value=b"\x00" * 1024)

        mock_vec_inst = MagicMock()
        mock_vec_inst.init_db = AsyncMock()
        mock_vec_inst.add = AsyncMock()
        mock_vec_cls.return_value = mock_vec_inst

        mock_kw_inst = MagicMock()
        mock_kw_inst.init_db = AsyncMock()
        mock_kw_inst.add = AsyncMock()
        mock_kw_cls.return_value = mock_kw_inst

        mock_hybrid_inst = MagicMock()
        mock_hybrid_cls.return_value = mock_hybrid_inst

        manager = MemoryManager(db_path=":memory:")
        await manager.init()
        assert manager.is_initialized is True

        memory_id = await manager.store(
            content="User likes Python",
            type="preference",
            importance=0.8,
        )

        assert isinstance(memory_id, str)
        assert len(memory_id) > 0
        mock_store_inst.store.assert_awaited_once()
        mock_emb_inst.generate.assert_awaited_once_with("User likes Python")
        mock_vec_inst.add.assert_awaited_once()
        mock_kw_inst.add.assert_awaited_once()

        await manager.close()

    @pytest.mark.asyncio
    @patch("src.memory.manager.SQLiteStore")
    @patch("src.memory.manager.EmbeddingGenerator")
    @patch("src.memory.manager.VectorSearch")
    @patch("src.memory.manager.KeywordSearch")
    @patch("src.memory.manager.HybridSearch")
    async def test_search(
        self,
        mock_hybrid_cls: MagicMock,
        mock_kw_cls: MagicMock,
        mock_vec_cls: MagicMock,
        mock_emb_cls: MagicMock,
        mock_store_cls: MagicMock,
    ) -> None:
        """MemoryManager.search() delegates to HybridSearch."""
        from src.memory.manager import MemoryManager

        mock_store_inst = MagicMock()
        mock_store_inst.init = AsyncMock()
        mock_store_inst.db = MagicMock()
        mock_store_inst.close = AsyncMock()
        mock_store_cls.return_value = mock_store_inst

        mock_emb_cls.return_value = MagicMock()

        mock_vec_inst = MagicMock()
        mock_vec_inst.init_db = AsyncMock()
        mock_vec_cls.return_value = mock_vec_inst

        mock_kw_inst = MagicMock()
        mock_kw_inst.init_db = AsyncMock()
        mock_kw_cls.return_value = mock_kw_inst

        expected_results = [
            Memory(id="mem-001", content="Python is great", score=0.9),
        ]
        mock_hybrid_inst = MagicMock()
        mock_hybrid_inst.search = AsyncMock(return_value=expected_results)
        mock_hybrid_cls.return_value = mock_hybrid_inst

        manager = MemoryManager(db_path=":memory:")
        await manager.init()

        results = await manager.search("Python", limit=5)

        assert len(results) == 1
        assert results[0].id == "mem-001"
        mock_hybrid_inst.search.assert_awaited_once_with("Python", limit=5)

        await manager.close()

    @pytest.mark.asyncio
    async def test_not_initialized_raises(self) -> None:
        """MemoryManager methods raise RuntimeError when not initialized."""
        from src.memory.manager import MemoryManager

        manager = MemoryManager(db_path=":memory:")

        with pytest.raises(RuntimeError, match="not initialized"):
            await manager.store("test")

        with pytest.raises(RuntimeError, match="not initialized"):
            await manager.search("test")


# =========================================================================
# Tests: Memory model
# =========================================================================


class TestMemoryModel:
    """Tests for Memory dataclass."""

    def test_metadata_json(self) -> None:
        """metadata_json() serializes metadata to JSON string."""
        mem = Memory(id="m1", content="test", metadata={"key": "value"})
        json_str = mem.metadata_json()
        assert '"key"' in json_str
        assert '"value"' in json_str

    def test_metadata_from_json(self) -> None:
        """metadata_from_json() deserializes JSON string."""
        result = Memory.metadata_from_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_metadata_from_json_empty(self) -> None:
        """metadata_from_json() handles empty/None input."""
        assert Memory.metadata_from_json(None) == {}
        assert Memory.metadata_from_json("") == {}

    def test_metadata_from_json_invalid(self) -> None:
        """metadata_from_json() handles invalid JSON gracefully."""
        assert Memory.metadata_from_json("not json") == {}
