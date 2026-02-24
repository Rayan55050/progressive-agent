"""
Twitch tool — check who's live from monitored streamers.

Wraps TwitchMonitor for on-demand queries from the agent.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class TwitchStatusTool:
    """Check which monitored Twitch streamers are currently live."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="twitch_status",
            description=(
                "Проверить, кто из отслеживаемых стримеров сейчас онлайн на Twitch. "
                "Возвращает список стримов с названием, игрой и количеством зрителей."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            live = await self._monitor.get_live_now()
            if not live:
                streamers = self._monitor.streamers
                return ToolResult(
                    success=True,
                    data={
                        "live": [],
                        "message": f"Никто из {len(streamers)} отслеживаемых стримеров не в эфире.",
                        "monitored": streamers,
                    },
                )
            return ToolResult(
                success=True,
                data={
                    "live": live,
                    "count": len(live),
                    "monitored_total": len(self._monitor.streamers),
                },
            )
        except Exception as e:
            logger.error("Twitch status check failed: %s", e)
            return ToolResult(success=False, error=str(e))
