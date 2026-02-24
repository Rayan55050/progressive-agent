"""
Ukrainska Pravda RSS tool — news from UP, Ekonomichna Pravda, Evropeyska Pravda.

Free RSS feeds, no API key, no registration.
Sources:
  - Ukrainska Pravda (pravda.com.ua) — main Ukrainian news
  - Ekonomichna Pravda (epravda.com.ua) — economy, business, finance
  - Evropeyska Pravda (eurointegration.com.ua) — EU, foreign policy
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

import aiohttp
import feedparser

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=15)
_HEADERS = {
    "User-Agent": "ProgressiveAgent/1.0",
    "Accept-Encoding": "gzip, deflate",  # no brotli — aiohttp can't decode it without Brotli pkg
}

# RSS feed URLs
_FEEDS: dict[str, dict[str, str]] = {
    "up": {
        "name": "Українська правда",
        "url": "https://www.pravda.com.ua/rss/view_news/",
    },
    "epravda": {
        "name": "Економічна правда",
        "url": "https://www.epravda.com.ua/rss/view_news/",
    },
    "euro": {
        "name": "Європейська правда",
        "url": "https://www.eurointegration.com.ua/rss/view_news/",
    },
}


class UkrPravdaTool:
    """Ukrainian news from Pravda RSS feeds."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ukrpravda",
            description=(
                "Новини з Української правди, Економічної правди та Європейської правди (RSS). "
                "Free, без ключа. "
                "Actions: 'news' — останні новини (всі або конкретне видання); "
                "'search' — пошук по заголовках новин. "
                "Sources: 'up' (Українська правда), 'epravda' (Економічна правда), "
                "'euro' (Європейська правда), 'all' (всі). "
                "Використовуй коли питають: 'новини', 'що нового', 'українська правда', "
                "'новини України', 'економічні новини', 'правда', 'що відбувається'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'news' (latest headlines), 'search' (search by keyword)",
                    required=True,
                    enum=["news", "search"],
                ),
                ToolParameter(
                    name="source",
                    type="string",
                    description="Source: 'up', 'epravda', 'euro', 'all' (default: 'all')",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search keyword for 'search' action",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of results (default 15, max 50)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "news")
        source = kwargs.get("source", "all")
        limit = min(int(kwargs.get("limit", 15)), 50)

        try:
            if action == "news":
                return await self._get_news(source, limit)
            elif action == "search":
                query = kwargs.get("query", "")
                if not query:
                    return ToolResult(success=False, error="query is required for 'search' action")
                return await self._search_news(query, source, limit)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("UkrPravda RSS error")
            return ToolResult(success=False, error=f"RSS error: {e}")

    async def _get_news(self, source: str, limit: int) -> ToolResult:
        """Fetch latest news from RSS feeds."""
        feeds_to_fetch = self._get_feeds(source)
        all_articles = await self._fetch_feeds(feeds_to_fetch)

        # Sort by published date (newest first)
        all_articles.sort(key=lambda a: a.get("published_ts", 0), reverse=True)
        articles = all_articles[:limit]

        if not articles:
            return ToolResult(success=True, data={"answer": "Новин не знайдено."})

        source_label = _FEEDS.get(source, {}).get("name", "всі видання")
        lines = [f"Останні новини ({source_label}):\n"]
        for i, a in enumerate(articles, 1):
            lines.append(_format_article(i, a))

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(articles),
        })

    async def _search_news(self, query: str, source: str, limit: int) -> ToolResult:
        """Search news by keyword in title."""
        feeds_to_fetch = self._get_feeds(source)
        all_articles = await self._fetch_feeds(feeds_to_fetch)

        query_lower = query.lower()
        matched = [
            a for a in all_articles
            if query_lower in a.get("title", "").lower()
            or query_lower in a.get("summary", "").lower()
        ]
        matched.sort(key=lambda a: a.get("published_ts", 0), reverse=True)
        matched = matched[:limit]

        if not matched:
            return ToolResult(success=True, data={
                "answer": f"По запиту '{query}' новин не знайдено.",
            })

        lines = [f"Новини по '{query}' ({len(matched)}):\n"]
        for i, a in enumerate(matched, 1):
            lines.append(_format_article(i, a))

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(matched),
            "query": query,
        })

    @staticmethod
    def _get_feeds(source: str) -> list[dict[str, str]]:
        """Get feed configs for requested source."""
        if source in _FEEDS:
            return [_FEEDS[source]]
        return list(_FEEDS.values())

    async def _fetch_feeds(self, feeds: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Fetch and parse multiple RSS feeds in parallel."""
        articles: list[dict[str, Any]] = []

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            tasks = [self._fetch_one(session, f) for f in feeds]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                articles.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Feed fetch error: %s", result)

        return articles

    @staticmethod
    async def _fetch_one(session: aiohttp.ClientSession, feed: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch and parse a single RSS feed."""
        url = feed["url"]
        name = feed["name"]

        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning("RSS %s returned HTTP %d", name, resp.status)
                return []
            raw = await resp.text()

        parsed = feedparser.parse(raw)
        articles = []

        for entry in parsed.entries:
            pub_date = ""
            pub_ts = 0
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    dt = datetime(*entry.published_parsed[:6])
                    pub_date = dt.strftime("%d.%m %H:%M")
                    pub_ts = dt.timestamp()
                except Exception:
                    pass
            elif hasattr(entry, "published"):
                pub_date = entry.published[:16]

            summary = ""
            if hasattr(entry, "summary"):
                summary = re.sub(r"<[^>]+>", "", entry.summary)[:200]

            articles.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": name,
                "published": pub_date,
                "published_ts": pub_ts,
                "summary": summary,
            })

        logger.debug("RSS %s: %d articles", name, len(articles))
        return articles


def _format_article(num: int, a: dict[str, Any]) -> str:
    """Format single article."""
    title = a.get("title", "?")[:120]
    url = a.get("url", "")
    source = a.get("source", "")
    pub = a.get("published", "")

    time_str = f" | {pub}" if pub else ""
    src_str = f" [{source}]" if source else ""

    return f"{num}. {title}{src_str}{time_str}\n   {url}\n"
