"""
Fear & Greed Index tool — crypto market sentiment indicator.

100% FREE, no API key needed.
Source: alternative.me
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

API_URL = "https://api.alternative.me/fng/"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


class FearGreedTool:
    """Crypto Fear & Greed Index — market sentiment from 0 (Extreme Fear) to 100 (Extreme Greed)."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="fear_greed",
            description=(
                "Crypto Fear & Greed Index (free, no key). "
                "Shows market sentiment from 0 (Extreme Fear) to 100 (Extreme Greed). "
                "Actions: 'current' — today's index; "
                "'history' — last N days of index values. "
                "Useful for gauging market mood and timing entries/exits."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'current' or 'history'",
                    required=False,
                    enum=["current", "history"],
                ),
                ToolParameter(
                    name="days",
                    type="string",
                    description="Number of days for 'history' (default '7', max '30')",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "current").strip().lower()
        try:
            if action == "current":
                return await self._current()
            elif action == "history":
                days = min(int(kwargs.get("days", "7")), 30)
                return await self._history(days)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("Fear & Greed error: %s", e)
            return ToolResult(success=False, error=f"Fear & Greed error: {e}")

    async def _current(self) -> ToolResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}?limit=1", timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")
                data = await resp.json()

        entries = data.get("data", [])
        if not entries:
            return ToolResult(success=False, error="No data")

        entry = entries[0]
        value = int(entry.get("value", 0))
        classification = entry.get("value_classification", "?")

        emoji = self._emoji(value)
        bar = self._bar(value)

        result = (
            f"{emoji} **Fear & Greed Index: {value}/100**\n"
            f"Classification: **{classification}**\n"
            f"{bar}\n\n"
            f"0 = Extreme Fear | 50 = Neutral | 100 = Extreme Greed"
        )
        return ToolResult(success=True, data=result)

    async def _history(self, days: int) -> ToolResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}?limit={days}", timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")
                data = await resp.json()

        entries = data.get("data", [])
        if not entries:
            return ToolResult(success=False, error="No data")

        from datetime import datetime

        lines = [f"**Fear & Greed Index (last {days} days):**\n"]
        for entry in entries:
            value = int(entry.get("value", 0))
            classification = entry.get("value_classification", "?")
            ts = int(entry.get("timestamp", 0))
            date = datetime.fromtimestamp(ts).strftime("%m/%d") if ts else "?"
            emoji = self._emoji(value)
            lines.append(f"  {date}: {emoji} {value} — {classification}")

        # Average
        values = [int(e.get("value", 0)) for e in entries]
        avg = sum(values) / len(values) if values else 0
        lines.append(f"\nAverage: {avg:.0f}/100 ({self._classify(avg)})")

        return ToolResult(success=True, data="\n".join(lines))

    @staticmethod
    def _emoji(value: int) -> str:
        if value <= 20:
            return "😱"  # Extreme Fear
        elif value <= 40:
            return "😰"  # Fear
        elif value <= 60:
            return "😐"  # Neutral
        elif value <= 80:
            return "😊"  # Greed
        else:
            return "🤑"  # Extreme Greed

    @staticmethod
    def _classify(value: float) -> str:
        if value <= 20:
            return "Extreme Fear"
        elif value <= 40:
            return "Fear"
        elif value <= 60:
            return "Neutral"
        elif value <= 80:
            return "Greed"
        return "Extreme Greed"

    @staticmethod
    def _bar(value: int) -> str:
        filled = value // 5
        empty = 20 - filled
        return f"[{'█' * filled}{'░' * empty}]"
