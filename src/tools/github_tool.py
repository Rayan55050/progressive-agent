"""
GitHub Tool — trending repos, search, repo details.

Free API, no key required (60 req/h unauthenticated, 5000 with token).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = "ProgressiveAgent/1.0"

# Keywords relevant to our agent's tech stack
_AGENT_KEYWORDS = {
    "agent", "telegram-bot", "llm", "claude", "anthropic", "openai",
    "langchain", "llamaindex", "rag", "embedding", "vector", "mcp",
    "tool-use", "function-calling", "chatbot", "ai-assistant",
    "asyncio", "aiogram", "python-bot", "personal-assistant",
    "autopilot", "crewai", "autogpt", "memory", "prompt",
}


def _headers() -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _format_stars(count: int) -> str:
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def _relevance_tags(name: str, desc: str, topics: list[str]) -> list[str]:
    """Return matched keyword tags for agent relevance."""
    combined = (name + " " + desc + " " + " ".join(topics)).lower()
    return [kw for kw in _AGENT_KEYWORDS if kw in combined]


class GitHubTool:
    """GitHub trending repos, search, and repo details."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="github",
            description=(
                "GitHub: trending репозитории, поиск проектов, информация о репо. "
                "Бесплатно, без API ключа."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "trending — топ новых репозиториев за неделю (AI/tech). "
                        "search — поиск репозиториев по запросу. "
                        "repo — детали конкретного репозитория."
                    ),
                    required=True,
                    enum=["trending", "search", "repo"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Поисковый запрос (для search) или owner/name (для repo)",
                    required=False,
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Фильтр по языку: python, javascript, rust, etc.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Количество результатов (1-20, по умолчанию 10)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "trending")
        try:
            if action == "trending":
                return await self._trending(kwargs)
            elif action == "search":
                return await self._search(kwargs)
            elif action == "repo":
                return await self._repo(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("GitHub tool error: %s", e)
            return ToolResult(success=False, error=str(e))

    def _item_to_result(self, item: dict[str, Any]) -> dict[str, str]:
        """Convert a GitHub API item to a Tavily-like result dict."""
        name = item.get("full_name", "")
        desc = item.get("description", "") or "No description"
        stars = _format_stars(item.get("stargazers_count", 0))
        lang = item.get("language", "") or ""
        url = item.get("html_url", "")
        topics = item.get("topics", [])
        tags = _relevance_tags(name, desc, topics)

        snippet = f"{desc}. {stars} stars"
        if lang:
            snippet += f", {lang}"
        if tags:
            snippet += f". Agent relevance: {', '.join(tags[:5])}"

        return {"title": name, "url": url, "snippet": snippet}

    async def _trending(self, kwargs: dict[str, Any]) -> ToolResult:
        """Get trending repos (created in last 7 days, sorted by stars)."""
        from datetime import datetime, timedelta, timezone

        limit = min(int(kwargs.get("limit", 10)), 20)
        language = kwargs.get("language", "")

        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        q = f"created:>{week_ago} stars:>50"
        if language:
            q += f" language:{language}"

        params = {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": limit,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_API}/search/repositories",
                params=params,
                headers=_headers(),
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return ToolResult(success=False, error=f"GitHub API {resp.status}: {body[:200]}")
                data = await resp.json()

        results = [self._item_to_result(item) for item in data.get("items", [])[:limit]]

        return ToolResult(
            success=True,
            data={
                "answer": f"Top {len(results)} trending GitHub repos this week (sorted by stars).",
                "results": results,
            },
        )

    async def _search(self, kwargs: dict[str, Any]) -> ToolResult:
        """Search repositories by query."""
        query = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, error="query обязателен для search")

        limit = min(int(kwargs.get("limit", 10)), 20)
        language = kwargs.get("language", "")

        q = query
        if language:
            q += f" language:{language}"

        params = {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": limit,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_API}/search/repositories",
                params=params,
                headers=_headers(),
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return ToolResult(success=False, error=f"GitHub API {resp.status}: {body[:200]}")
                data = await resp.json()

        results = [self._item_to_result(item) for item in data.get("items", [])[:limit]]

        return ToolResult(
            success=True,
            data={
                "answer": f"Found {len(results)} repos matching '{query}'.",
                "results": results,
            },
        )

    async def _repo(self, kwargs: dict[str, Any]) -> ToolResult:
        """Get details for a specific repo (owner/name)."""
        query = kwargs.get("query", "")
        if not query or "/" not in query:
            return ToolResult(
                success=False,
                error="query должен быть в формате owner/name (например: anthropics/claude-code)",
            )

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_API}/repos/{query}",
                headers=_headers(),
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status == 404:
                    return ToolResult(success=False, error=f"Репо {query} не найден")
                if resp.status != 200:
                    body = await resp.text()
                    return ToolResult(success=False, error=f"GitHub API {resp.status}: {body[:200]}")
                item = await resp.json()

        result = self._item_to_result(item)
        forks = item.get("forks_count", 0)
        license_id = (item.get("license") or {}).get("spdx_id", "None")
        topics = item.get("topics", [])

        result["snippet"] += f", {forks} forks, license: {license_id}"
        if topics:
            result["snippet"] += f". Topics: {', '.join(topics[:10])}"

        return ToolResult(
            success=True,
            data={
                "answer": f"Details for {query}.",
                "results": [result],
            },
        )
