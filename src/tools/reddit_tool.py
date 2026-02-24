"""
Reddit Tool — subreddit posts, search, hot/top/new.

Free, no API key. Uses Reddit's public JSON API.
Rate limit: ~30 req/min without auth.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

_BASE = "https://www.reddit.com"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = "ProgressiveAgent/1.0 (personal bot, no scraping)"

# Default subreddits for different topics
_SUGGESTED_SUBS = {
    "crypto": "CryptoCurrency+Bitcoin+defi+ethfinance",
    "ai": "LocalLLaMA+MachineLearning+artificial+singularity",
    "tech": "programming+technology+webdev+devops",
    "trading": "wallstreetbets+stocks+options+Forex",
    "ukraine": "ukraine+ukraina",
}


def _format_score(count: int) -> str:
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


class RedditTool:
    """Reddit: hot/top/new posts, search, subreddit info."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reddit",
            description=(
                "Reddit: посты из сабреддитов, поиск, hot/top/new. "
                "Бесплатно, без ключа. "
                "Популярные сабы: crypto (CryptoCurrency+Bitcoin), "
                "ai (LocalLLaMA+MachineLearning), "
                "trading (wallstreetbets+stocks), "
                "tech (programming+technology)."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "hot — горячие посты. "
                        "top — топ посты (за day/week/month/year/all). "
                        "new — новые посты. "
                        "search — поиск по Reddit."
                    ),
                    required=True,
                    enum=["hot", "top", "new", "search"],
                ),
                ToolParameter(
                    name="subreddit",
                    type="string",
                    description=(
                        "Сабреддит или шорткат: crypto, ai, tech, trading, ukraine. "
                        "Можно объединять: 'CryptoCurrency+Bitcoin'. "
                        "Если не указан для hot/top/new — используется r/all."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Поисковый запрос (для action=search)",
                    required=False,
                ),
                ToolParameter(
                    name="timeframe",
                    type="string",
                    description="Период для top: day, week, month, year, all (по умолчанию day)",
                    required=False,
                    enum=["day", "week", "month", "year", "all"],
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Количество постов (1-25, по умолчанию 10)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "hot")
        try:
            if action in ("hot", "top", "new"):
                return await self._list_posts(action, kwargs)
            elif action == "search":
                return await self._search(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("Reddit tool error: %s", e)
            return ToolResult(success=False, error=str(e))

    def _resolve_sub(self, raw: str) -> str:
        if not raw:
            return ""
        return _SUGGESTED_SUBS.get(raw.lower(), raw)

    async def _fetch_json(
        self, session: aiohttp.ClientSession, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        headers = {"User-Agent": _USER_AGENT}
        try:
            async with session.get(
                url, params=params, headers=headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status == 429:
                    return {"error": "Rate limited (429). Подожди минуту."}
                if resp.status == 403:
                    return {"error": "Subreddit private или забанен (403)."}
                if resp.status != 200:
                    return {"error": f"Reddit HTTP {resp.status}"}
                return await resp.json()
        except Exception as e:
            return {"error": str(e)}

    def _parse_to_results(self, data: dict[str, Any], limit: int) -> list[dict[str, str]]:
        """Parse Reddit listing into Tavily-like result dicts."""
        results = []
        children = data.get("data", {}).get("children", [])
        for child in children[:limit]:
            p = child.get("data", {})
            if p.get("stickied"):
                continue
            title = p.get("title", "")
            sub = p.get("subreddit", "")
            score = _format_score(p.get("score", 0))
            comments = p.get("num_comments", 0)
            permalink = p.get("permalink", "")
            url = f"https://reddit.com{permalink}"

            snippet = f"r/{sub}, {score} score, {comments} comments"
            selftext = (p.get("selftext") or "")[:200]
            if selftext:
                snippet += f". {selftext}"

            results.append({"title": title, "url": url, "snippet": snippet})
        return results

    async def _list_posts(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        sub = self._resolve_sub(kwargs.get("subreddit", ""))
        limit = min(int(kwargs.get("limit", 10)), 25)
        timeframe = kwargs.get("timeframe", "day")

        if sub:
            url = f"{_BASE}/r/{sub}/{action}.json"
        else:
            url = f"{_BASE}/{action}.json"

        params: dict[str, Any] = {"limit": limit + 5, "raw_json": 1}
        if action == "top":
            params["t"] = timeframe

        async with aiohttp.ClientSession() as session:
            data = await self._fetch_json(session, url, params)

        if not data:
            return ToolResult(success=False, error="No response from Reddit")
        if "error" in data and isinstance(data["error"], str):
            return ToolResult(success=False, error=data["error"])

        results = self._parse_to_results(data, limit)
        sub_label = f"r/{sub}" if sub else "r/all"

        return ToolResult(
            success=True,
            data={
                "answer": f"Top {len(results)} {action} posts from {sub_label}.",
                "results": results,
            },
        )

    async def _search(self, kwargs: dict[str, Any]) -> ToolResult:
        query = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, error="query обязателен для search")

        sub = self._resolve_sub(kwargs.get("subreddit", ""))
        limit = min(int(kwargs.get("limit", 10)), 25)
        timeframe = kwargs.get("timeframe", "week")

        if sub:
            url = f"{_BASE}/r/{sub}/search.json"
        else:
            url = f"{_BASE}/search.json"

        params = {
            "q": query,
            "sort": "relevance",
            "t": timeframe,
            "limit": limit + 5,
            "restrict_sr": "on" if sub else "off",
            "raw_json": 1,
        }

        async with aiohttp.ClientSession() as session:
            data = await self._fetch_json(session, url, params)

        if not data:
            return ToolResult(success=False, error="No response from Reddit")
        if "error" in data and isinstance(data["error"], str):
            return ToolResult(success=False, error=data["error"])

        results = self._parse_to_results(data, limit)

        return ToolResult(
            success=True,
            data={
                "answer": f"Found {len(results)} Reddit posts matching '{query}'.",
                "results": results,
            },
        )
