"""
Hacker News Tool — top/best/new stories, search, story details.

Completely free, no API key needed.
Uses HN Firebase API + Algolia search.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

_HN_API = "https://hacker-news.firebaseio.com/v0"
_ALGOLIA = "https://hn.algolia.com/api/v1"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class HackerNewsTool:
    """Hacker News: top stories, search, details."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="hackernews",
            description=(
                "Hacker News: топ посты, поиск, детали с комментариями. "
                "Бесплатно, без ключа. Лучший источник AI/tech новостей."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "top — топ постов на главной. "
                        "best — лучшие посты. "
                        "new — новые посты. "
                        "search — поиск по запросу. "
                        "story — детали конкретного поста + топ комментарии."
                    ),
                    required=True,
                    enum=["top", "best", "new", "search", "story"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Поисковый запрос (для search) или ID поста (для story)",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Количество результатов (1-30, по умолчанию 10)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "top")
        try:
            if action in ("top", "best", "new"):
                return await self._list_stories(action, kwargs)
            elif action == "search":
                return await self._search(kwargs)
            elif action == "story":
                return await self._story(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("HackerNews tool error: %s", e)
            return ToolResult(success=False, error=str(e))

    async def _list_stories(self, category: str, kwargs: dict[str, Any]) -> ToolResult:
        """Fetch top/best/new story IDs, then get details."""
        limit = min(int(kwargs.get("limit", 10)), 30)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_HN_API}/{category}stories.json",
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HN API {resp.status}")
                ids = await resp.json()

            stories = await self._fetch_items(session, ids[:limit])

        results = []
        for s in stories:
            title = s.get("title", "")
            url = s.get("url") or s.get("hn_url", "")
            points = s.get("points", 0)
            comments = s.get("comments", 0)
            results.append({
                "title": title,
                "url": url,
                "snippet": f"{points} points, {comments} comments",
            })

        return ToolResult(
            success=True,
            data={
                "answer": f"Top {len(results)} Hacker News {category} stories.",
                "results": results,
            },
        )

    async def _search(self, kwargs: dict[str, Any]) -> ToolResult:
        """Search HN via Algolia."""
        query = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, error="query обязателен для search")

        limit = min(int(kwargs.get("limit", 10)), 30)

        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": limit,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_ALGOLIA}/search",
                params=params,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"Algolia API {resp.status}")
                data = await resp.json()

        results = []
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            points = hit.get("points", 0) or 0
            comments = hit.get("num_comments", 0) or 0
            results.append({
                "title": title,
                "url": url,
                "snippet": f"{points} points, {comments} comments",
            })

        return ToolResult(
            success=True,
            data={
                "answer": f"Found {len(results)} HN stories matching '{query}'.",
                "results": results,
            },
        )

    async def _story(self, kwargs: dict[str, Any]) -> ToolResult:
        """Get story details with top comments."""
        story_id = kwargs.get("query", "")
        if not story_id:
            return ToolResult(success=False, error="query (ID поста) обязателен для story")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_HN_API}/item/{story_id}.json",
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HN API {resp.status}")
                item = await resp.json()

            if not item:
                return ToolResult(success=False, error=f"Story {story_id} not found")

            kid_ids = (item.get("kids") or [])[:5]
            comments = await self._fetch_items(session, kid_ids)

        title = item.get("title", "")
        url = item.get("url", "") or f"https://news.ycombinator.com/item?id={story_id}"
        text = (item.get("text") or "")[:500]

        snippet = f"{item.get('score', 0)} points, {item.get('descendants', 0)} comments"
        if text:
            snippet += f". {text}"
        if comments:
            top_comments = []
            for c in comments:
                if c.get("text"):
                    author = c.get("author", c.get("by", ""))
                    top_comments.append(f"{author}: {c['text'][:150]}")
            if top_comments:
                snippet += "\n\nTop comments:\n" + "\n".join(top_comments)

        return ToolResult(
            success=True,
            data={
                "answer": f"Story details for '{title}'.",
                "results": [{"title": title, "url": url, "snippet": snippet}],
            },
        )

    async def _fetch_items(
        self, session: aiohttp.ClientSession, ids: list[int]
    ) -> list[dict[str, Any]]:
        """Fetch multiple HN items in parallel."""
        import asyncio

        async def fetch_one(item_id: int) -> dict[str, Any] | None:
            try:
                async with session.get(
                    f"{_HN_API}/item/{item_id}.json",
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and data.get("type") == "story":
                            return {
                                "id": data.get("id"),
                                "title": data.get("title", ""),
                                "url": data.get("url", ""),
                                "hn_url": f"https://news.ycombinator.com/item?id={data.get('id')}",
                                "points": data.get("score", 0),
                                "comments": data.get("descendants", 0) or 0,
                                "author": data.get("by", ""),
                            }
                        elif data and data.get("type") == "comment":
                            return {
                                "author": data.get("by", ""),
                                "text": (data.get("text") or "")[:300],
                            }
            except Exception:
                pass
            return None

        results = await asyncio.gather(*[fetch_one(i) for i in ids])
        return [r for r in results if r is not None]
