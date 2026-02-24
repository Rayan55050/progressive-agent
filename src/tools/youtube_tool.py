"""
YouTube tools — search videos and get video info via YouTube Data API v3.

Wraps YouTubeMonitor for on-demand queries from the agent.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class YouTubeSearchTool:
    """Search YouTube for videos by query."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="youtube_search",
            description=(
                "Поиск видео на YouTube по запросу. "
                "Возвращает список видео с названием, каналом, описанием и ссылкой."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Поисковый запрос",
                    required=True,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Максимум результатов (1-10, по умолчанию 5)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, error="query is required")

        max_results = min(int(kwargs.get("max_results", 5)), 10)

        try:
            results = await self._monitor.search(query, max_results=max_results)
            if not results:
                return ToolResult(
                    success=True,
                    data={"videos": [], "message": "Ничего не найдено по запросу."},
                )
            return ToolResult(
                success=True,
                data={"videos": results, "count": len(results)},
            )
        except Exception as e:
            logger.error("YouTube search failed: %s", e)
            return ToolResult(success=False, error=str(e))


class YouTubeSubscriptionsTool:
    """List user's YouTube subscriptions (requires OAuth)."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="youtube_subscriptions",
            description=(
                "Получить список YouTube-подписок пользователя. "
                "Показывает каналы, на которые подписан пользователь. "
                "Требует OAuth авторизацию."
            ),
            parameters=[
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Максимум результатов (1-200, по умолчанию 50)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._monitor.oauth_available:
            return ToolResult(
                success=False,
                error="YouTube OAuth не настроен. Нужна авторизация: python -m src.monitors.youtube_monitor --setup",
            )

        max_results = min(int(kwargs.get("max_results", 50)), 200)

        try:
            subs = await self._monitor.get_subscriptions(max_results=max_results)
            if not subs:
                return ToolResult(
                    success=True,
                    data={"subscriptions": [], "message": "Подписки не найдены или OAuth не авторизован."},
                )
            return ToolResult(
                success=True,
                data={"subscriptions": subs, "count": len(subs)},
            )
        except Exception as e:
            logger.error("YouTube subscriptions failed: %s", e)
            return ToolResult(success=False, error=str(e))


class YouTubeLikedTool:
    """List user's liked YouTube videos (requires OAuth)."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="youtube_liked",
            description=(
                "Получить список лайкнутых видео на YouTube. "
                "Показывает последние видео, которые пользователь лайкнул. "
                "Требует OAuth авторизацию."
            ),
            parameters=[
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Максимум результатов (1-50, по умолчанию 20)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._monitor.oauth_available:
            return ToolResult(
                success=False,
                error="YouTube OAuth не настроен. Нужна авторизация: python -m src.monitors.youtube_monitor --setup",
            )

        max_results = min(int(kwargs.get("max_results", 20)), 50)

        try:
            videos = await self._monitor.get_liked_videos(max_results=max_results)
            if not videos:
                return ToolResult(
                    success=True,
                    data={"videos": [], "message": "Лайкнутые видео не найдены."},
                )
            return ToolResult(
                success=True,
                data={"videos": videos, "count": len(videos)},
            )
        except Exception as e:
            logger.error("YouTube liked videos failed: %s", e)
            return ToolResult(success=False, error=str(e))


class YouTubeInfoTool:
    """Get detailed info about a specific YouTube video."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="youtube_info",
            description=(
                "Получить подробную информацию о видео на YouTube: "
                "название, канал, описание, длительность, просмотры, лайки. "
                "Принимает URL видео или video ID."
            ),
            parameters=[
                ToolParameter(
                    name="video",
                    type="string",
                    description="URL видео или video ID (например, dQw4w9WgXcQ или https://youtu.be/dQw4w9WgXcQ)",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        video_ref = kwargs.get("video", "")
        if not video_ref:
            return ToolResult(success=False, error="video URL or ID is required")

        try:
            info = await self._monitor.get_video_info(video_ref)
            if not info:
                return ToolResult(
                    success=True,
                    data={"message": "Видео не найдено или недоступно."},
                )
            return ToolResult(success=True, data=info)
        except Exception as e:
            logger.error("YouTube info failed: %s", e)
            return ToolResult(success=False, error=str(e))


class YouTubeSummaryTool:
    """Fetch YouTube video transcript for summarization by LLM."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="youtube_summary",
            description=(
                "Получить транскрипт (субтитры) видео на YouTube для суммаризации. "
                "Возвращает полный текст видео, который можно пересказать/суммаризировать. "
                "Принимает URL видео или video ID. Работает без API ключа."
            ),
            parameters=[
                ToolParameter(
                    name="video",
                    type="string",
                    description="URL видео или video ID (например, dQw4w9WgXcQ или https://youtu.be/dQw4w9WgXcQ)",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        video_ref = kwargs.get("video", "")
        if not video_ref:
            return ToolResult(success=False, error="video URL or ID is required")

        try:
            result = await self._monitor.get_transcript(video_ref)
            if "error" in result:
                return ToolResult(success=False, error=result["error"])
            return ToolResult(success=True, data=result)
        except Exception as e:
            logger.error("YouTube summary failed: %s", e)
            return ToolResult(success=False, error=str(e))
