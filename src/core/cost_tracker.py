"""
Cost tracker with SQLite storage.

Tracks API usage per provider/model, calculates costs,
and enforces daily/monthly budget limits.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.core.config import CostConfig

logger = logging.getLogger(__name__)


class BudgetStatus(Enum):
    """Budget check result."""

    OK = "ok"
    WARNING = "warning"  # >80% of limit (configurable threshold)
    EXCEEDED = "exceeded"


@dataclass
class UsageRecord:
    """Single API usage record."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime


# ---------------------------------------------------------------------------
# Token pricing per model (USD per 1M tokens)
# ---------------------------------------------------------------------------

# Prices as of latest public pricing.
# Keys are substrings matched against model names.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4": {
        "input_per_1m": 15.0,
        "output_per_1m": 75.0,
    },
    "claude-sonnet-4": {
        "input_per_1m": 3.0,
        "output_per_1m": 15.0,
    },
    "claude-haiku-4": {
        "input_per_1m": 0.80,
        "output_per_1m": 4.0,
    },
    # Legacy models
    "claude-3-5-sonnet": {
        "input_per_1m": 3.0,
        "output_per_1m": 15.0,
    },
    "claude-3-5-haiku": {
        "input_per_1m": 0.80,
        "output_per_1m": 4.0,
    },
    "claude-3-opus": {
        "input_per_1m": 15.0,
        "output_per_1m": 75.0,
    },
}

# Fallback pricing if model not recognized
DEFAULT_PRICING = {
    "input_per_1m": 3.0,
    "output_per_1m": 15.0,
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for a given model and token counts.

    Matches the model name against known pricing patterns.
    Falls back to Sonnet pricing if model is not recognized.

    Args:
        model: Model identifier string.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    pricing = DEFAULT_PRICING
    for model_key, model_pricing in MODEL_PRICING.items():
        if model_key in model:
            pricing = model_pricing
            break

    input_cost = (input_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
    return input_cost + output_cost


class CostTracker:
    """Tracks API costs with SQLite persistence and budget enforcement.

    Stores every API call with provider, model, token counts, and cost.
    Provides daily/monthly spend queries and budget status checks.
    """

    def __init__(self, config: CostConfig) -> None:
        self._config = config
        self._db_path = Path(config.db_path)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

        logger.info(
            "CostTracker initialized: db=%s, daily_limit=$%.2f, monthly_limit=$%.2f",
            self._db_path,
            config.daily_limit_usd,
            config.monthly_limit_usd,
        )

    async def initialize(self) -> None:
        """Create database and table if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._init_db)
        logger.info("Cost tracker database initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Synchronous DB initialization (run in executor)."""
        conn = self._get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp
            ON usage (timestamp)
            """
        )
        conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create SQLite connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    async def track(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record a usage event and return the cost.

        Args:
            provider: Provider name (e.g. 'claude').
            model: Model identifier.
            input_tokens: Number of input tokens consumed.
            output_tokens: Number of output tokens generated.

        Returns:
            Cost in USD for this usage event.
        """
        cost = calculate_cost(model, input_tokens, output_tokens)
        now = datetime.now(timezone.utc).isoformat()

        async with self._lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._insert_usage,
                provider,
                model,
                input_tokens,
                output_tokens,
                cost,
                now,
            )

        logger.debug(
            "Tracked usage: provider=%s, model=%s, in=%d, out=%d, cost=$%.6f",
            provider,
            model,
            input_tokens,
            output_tokens,
            cost,
        )
        return cost

    def _insert_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        timestamp: str,
    ) -> None:
        """Insert usage record (run in executor)."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO usage (provider, model, input_tokens, output_tokens, cost_usd, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (provider, model, input_tokens, output_tokens, cost, timestamp),
        )
        conn.commit()

    async def check_budget(self) -> BudgetStatus:
        """Check current budget status against configured limits.

        Returns:
            BudgetStatus.OK if under threshold,
            BudgetStatus.WARNING if over warning threshold but under limit,
            BudgetStatus.EXCEEDED if over daily or monthly limit.
        """
        daily = await self.get_daily_spend()
        monthly = await self.get_monthly_spend()

        daily_limit = self._config.daily_limit_usd
        monthly_limit = self._config.monthly_limit_usd
        threshold = self._config.warning_threshold

        if daily >= daily_limit or monthly >= monthly_limit:
            logger.warning(
                "Budget EXCEEDED: daily=$%.4f/$%.2f, monthly=$%.4f/$%.2f",
                daily,
                daily_limit,
                monthly,
                monthly_limit,
            )
            return BudgetStatus.EXCEEDED

        if (
            daily >= daily_limit * threshold
            or monthly >= monthly_limit * threshold
        ):
            logger.warning(
                "Budget WARNING: daily=$%.4f/$%.2f, monthly=$%.4f/$%.2f",
                daily,
                daily_limit,
                monthly,
                monthly_limit,
            )
            return BudgetStatus.WARNING

        return BudgetStatus.OK

    async def get_daily_spend(self) -> float:
        """Get total spend for today (UTC).

        Returns:
            Total USD spent today.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with self._lock:
            loop = asyncio.get_running_loop()
            result: Any = await loop.run_in_executor(
                None, self._query_spend, f"{today}%"
            )

        return result or 0.0

    async def get_monthly_spend(self) -> float:
        """Get total spend for the current month (UTC).

        Returns:
            Total USD spent this month.
        """
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")

        async with self._lock:
            loop = asyncio.get_running_loop()
            result: Any = await loop.run_in_executor(
                None, self._query_spend, f"{month_prefix}%"
            )

        return result or 0.0

    def _query_spend(self, timestamp_pattern: str) -> float | None:
        """Query total spend matching a timestamp pattern (run in executor)."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT SUM(cost_usd) FROM usage WHERE timestamp LIKE ?",
            (timestamp_pattern,),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else 0.0

    async def close(self) -> None:
        """Close the database connection."""
        async with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                logger.info("Cost tracker database connection closed")
