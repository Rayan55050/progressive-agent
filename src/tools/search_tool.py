"""
Мультипровайдерный веб-поиск.

Поддерживает 4 провайдера (все из закладок владельца):
- Tavily — основной поисковик (структурированные результаты)
- Jina — Reader API (чтение веб-страниц) + Search API
- SerpApi — Google/Bing поисковая выдача
- Firecrawl — веб-скрапинг и глубокий crawl

Провайдеры используются каскадно: если основной не доступен,
пробуется следующий. Или можно указать конкретный через параметр.

Tavily API cost (credits per request):
- Search basic: 1, advanced: 2
- Extract: 1 per 5 URLs
- Research mini: 4-110, pro: 15-250

Tavily key rotation: multiple API keys with automatic failover
when credits run out on the current key.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class TavilyKeyPool:
    """Pool of Tavily API keys with automatic rotation.

    When credits run out on the current key (HTTP 401/429 or UsageLimitError),
    automatically switches to the next key. All Tavily tools share one pool.
    """

    def __init__(self, keys: list[str]) -> None:
        self._keys = [k for k in keys if k and k.strip()]
        self._current_idx = 0
        self._clients: dict[int, Any] = {}  # idx -> TavilyClient
        if self._keys:
            logger.info("TavilyKeyPool: %d keys loaded, active key #1", len(self._keys))
        else:
            logger.warning("TavilyKeyPool: no keys configured")

    @property
    def available(self) -> bool:
        return len(self._keys) > 0

    @property
    def current_key(self) -> str:
        if not self._keys:
            return ""
        return self._keys[self._current_idx]

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def get_client(self) -> Any:
        """Get TavilyClient for the current active key."""
        from tavily import TavilyClient

        idx = self._current_idx
        if idx not in self._clients:
            self._clients[idx] = TavilyClient(api_key=self._keys[idx])
        return self._clients[idx]

    def rotate(self) -> bool:
        """Switch to next key. Returns True if rotated, False if no more keys."""
        if len(self._keys) <= 1:
            return False
        old_idx = self._current_idx
        self._current_idx = (self._current_idx + 1) % len(self._keys)
        # If we've wrapped around to the start, all keys are exhausted
        if self._current_idx == 0:
            logger.error("TavilyKeyPool: ALL %d keys exhausted!", len(self._keys))
            return False
        key_preview = self._keys[self._current_idx][:12] + "..."
        logger.warning(
            "TavilyKeyPool: key #%d exhausted, rotating to key #%d (%s)",
            old_idx + 1, self._current_idx + 1, key_preview,
        )
        return True

    @staticmethod
    def is_credit_error(exc: Exception) -> bool:
        """Check if exception indicates credits exhausted."""
        msg = str(exc).lower()
        # Tavily returns various error messages for exhausted credits
        return any(kw in msg for kw in (
            "usage limit", "credit", "quota", "exceeded",
            "rate limit", "insufficient", "payment required",
            "unauthorized", "forbidden",
        ))


# Global shared pool — initialized once, used by all Tavily tools
_tavily_pool: TavilyKeyPool | None = None


def init_tavily_pool(keys: list[str]) -> TavilyKeyPool:
    """Initialize the global Tavily key pool. Call once at startup."""
    global _tavily_pool
    _tavily_pool = TavilyKeyPool(keys)
    return _tavily_pool


def get_tavily_pool() -> TavilyKeyPool | None:
    """Get the global Tavily key pool."""
    return _tavily_pool

# Keywords that hint at a news-related query
_NEWS_KEYWORDS = {
    "новост", "news", "latest", "последн", "свеж", "сегодня", "today",
    "вчера", "yesterday", "анонс", "релиз", "release", "launch", "вышел",
    "выпустил", "обновлен", "update",
}

# Keywords that hint at a finance-related query
_FINANCE_KEYWORDS = {
    "цена", "price", "курс", "bitcoin", "btc", "eth", "крипт", "crypto",
    "акци", "stock", "биржа", "market", "торг", "trade", "инвест", "invest",
    "доход", "revenue", "profit",
}


def _detect_topic(query: str) -> str:
    """Auto-detect search topic from query keywords.

    Returns 'news', 'finance', or 'general'.
    """
    lower = query.lower()
    for kw in _NEWS_KEYWORDS:
        if kw in lower:
            return "news"
    for kw in _FINANCE_KEYWORDS:
        if kw in lower:
            return "finance"
    return "general"


class SearchTool:
    """Мультипровайдерный инструмент веб-поиска.

    Cascade: Tavily → SerpApi → Jina.
    Firecrawl используется отдельно для скрапинга полных страниц.
    """

    def __init__(
        self,
        tavily_key: str | None = None,
        serpapi_key: str | None = None,
        jina_key: str | None = None,
        firecrawl_key: str | None = None,
    ) -> None:
        self._tavily_key = tavily_key or os.getenv("TAVILY_API_KEY", "")
        self._serpapi_key = serpapi_key or os.getenv("SERPAPI_API_KEY", "")
        self._jina_key = jina_key or os.getenv("JINA_API_KEY", "")
        self._firecrawl_key = firecrawl_key or os.getenv("FIRECRAWL_API_KEY", "")
        self._tavily_client: Any = None

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description=(
                "Search the web for information. Uses advanced depth, "
                "auto-detects topic (news/finance/general), returns "
                "AI-generated answer + source results with URLs."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query string",
                    required=True,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of results (default: 5)",
                    required=False,
                    default=5,
                ),
                ToolParameter(
                    name="topic",
                    type="string",
                    description="Search topic: general, news, finance (default: auto-detect from query)",
                    required=False,
                    default="auto",
                    enum=["auto", "general", "news", "finance"],
                ),
                ToolParameter(
                    name="time_range",
                    type="string",
                    description="Time filter: day, week, month, year (default: none)",
                    required=False,
                    default="",
                    enum=["", "day", "week", "month", "year"],
                ),
                ToolParameter(
                    name="provider",
                    type="string",
                    description="Search provider: tavily, serpapi, jina, firecrawl (default: auto)",
                    required=False,
                    default="auto",
                    enum=["auto", "tavily", "serpapi", "jina", "firecrawl"],
                ),
            ],
        )

    @property
    def available_providers(self) -> list[str]:
        """List of providers with configured API keys."""
        providers = []
        pool = get_tavily_pool()
        if (pool and pool.available) or self._tavily_key:
            providers.append("tavily")
        if self._serpapi_key:
            providers.append("serpapi")
        if self._jina_key:
            providers.append("jina")
        if self._firecrawl_key:
            providers.append("firecrawl")
        return providers

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute web search with auto-fallback between providers."""
        query: str = kwargs.get("query", "")
        max_results: int = kwargs.get("max_results", 5)
        provider: str = kwargs.get("provider", "auto")
        topic: str = kwargs.get("topic", "auto")
        time_range: str = kwargs.get("time_range", "")

        if not query:
            return ToolResult(success=False, error="Search query is required")

        if not self.available_providers:
            return ToolResult(
                success=False,
                error="No search API keys configured. Set TAVILY_API_KEY, SERPAPI_API_KEY, or JINA_API_KEY in .env",
            )

        # Auto-detect topic if not specified
        if topic == "auto":
            topic = _detect_topic(query)

        logger.info(
            "Searching: '%s' (provider=%s, topic=%s, max=%d)",
            query, provider, topic, max_results,
        )

        # Specific provider requested
        if provider != "auto":
            return await self._search_with(provider, query, max_results, topic, time_range)

        # Auto: cascade through available providers
        for prov in self.available_providers:
            result = await self._search_with(prov, query, max_results, topic, time_range)
            if result.success:
                return result
            logger.warning("Provider %s failed, trying next...", prov)

        return ToolResult(success=False, error="All search providers failed")

    async def _search_with(
        self, provider: str, query: str, max_results: int,
        topic: str = "general", time_range: str = "",
    ) -> ToolResult:
        """Route to specific provider."""
        try:
            if provider == "tavily":
                return await self._search_tavily(query, max_results, topic, time_range)
            elif provider == "serpapi":
                return await self._search_serpapi(query, max_results)
            elif provider == "jina":
                return await self._search_jina(query, max_results)
            elif provider == "firecrawl":
                return await self._scrape_firecrawl(query, max_results)
            else:
                return ToolResult(success=False, error=f"Unknown provider: {provider}")
        except Exception as e:
            logger.error("Provider %s failed: %s", provider, e)
            return ToolResult(success=False, error=f"{provider} failed: {e}")

    # -----------------------------------------------------------------------
    # Tavily
    # -----------------------------------------------------------------------

    async def _search_tavily(
        self, query: str, max_results: int,
        topic: str = "general", time_range: str = "",
    ) -> ToolResult:
        """Search using Tavily API with advanced depth and AI answer.

        Costs 2 credits per request (advanced depth).
        Uses TavilyKeyPool for automatic key rotation on credit exhaustion.
        """
        pool = get_tavily_pool()

        # Determine client source
        if pool and pool.available:
            client = pool.get_client()
        elif self._tavily_key:
            from tavily import TavilyClient
            if self._tavily_client is None:
                self._tavily_client = TavilyClient(api_key=self._tavily_key)
            client = self._tavily_client
        else:
            return ToolResult(success=False, error="TAVILY_API_KEY not set")

        # Build search kwargs
        search_kwargs: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": True,
            "topic": topic,
        }
        if time_range:
            search_kwargs["time_range"] = time_range

        try:
            response = await asyncio.to_thread(lambda: client.search(**search_kwargs))
        except Exception as e:
            if pool and TavilyKeyPool.is_credit_error(e) and pool.rotate():
                logger.warning("Tavily credits exhausted, rotated key: %s", e)
                client = pool.get_client()
                response = await asyncio.to_thread(lambda: client.search(**search_kwargs))
            else:
                raise

        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "score": item.get("score", 0),
                "source": "tavily",
            }
            for item in response.get("results", [])
        ]

        # Prepend AI-generated answer if available
        answer = response.get("answer", "")
        data: dict[str, Any] = {
            "answer": answer,
            "results": results,
            "topic": topic,
        }

        logger.info(
            "Tavily returned %d results (topic=%s, answer=%s)",
            len(results), topic, "yes" if answer else "no",
        )
        return ToolResult(success=True, data=data)

    # -----------------------------------------------------------------------
    # SerpApi
    # -----------------------------------------------------------------------

    async def _search_serpapi(self, query: str, max_results: int) -> ToolResult:
        """Search using SerpApi (Google search results)."""
        if not self._serpapi_key:
            return ToolResult(success=False, error="SERPAPI_API_KEY not set")

        params = {
            "q": query,
            "api_key": self._serpapi_key,
            "engine": "google",
            "num": max_results,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return ToolResult(success=False, error=f"SerpApi HTTP {resp.status}: {text[:200]}")

                data = await resp.json()

        results = []
        for item in data.get("organic_results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": "serpapi",
            })

        logger.info("SerpApi returned %d results", len(results))
        return ToolResult(success=True, data=results)

    # -----------------------------------------------------------------------
    # Jina
    # -----------------------------------------------------------------------

    async def _search_jina(self, query: str, max_results: int) -> ToolResult:
        """Search using Jina Search API (s.jina.ai)."""
        if not self._jina_key:
            return ToolResult(success=False, error="JINA_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self._jina_key}",
            "Accept": "application/json",
            "X-Return-Format": "text",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://s.jina.ai/{query}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return ToolResult(success=False, error=f"Jina HTTP {resp.status}: {text[:200]}")

                data = await resp.json()

        results = []
        for item in data.get("data", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", item.get("content", ""))[:500],
                "source": "jina",
            })

        logger.info("Jina returned %d results", len(results))
        return ToolResult(success=True, data=results)

    # -----------------------------------------------------------------------
    # Firecrawl
    # -----------------------------------------------------------------------

    async def _scrape_firecrawl(self, query: str, max_results: int) -> ToolResult:
        """Scrape/search using Firecrawl API.

        If query looks like a URL, scrapes that URL.
        Otherwise, uses Firecrawl search endpoint.
        """
        if not self._firecrawl_key:
            return ToolResult(success=False, error="FIRECRAWL_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self._firecrawl_key}",
            "Content-Type": "application/json",
        }

        is_url = query.startswith("http://") or query.startswith("https://")

        async with aiohttp.ClientSession() as session:
            if is_url:
                # Scrape a specific URL
                async with session.post(
                    "https://api.firecrawl.dev/v1/scrape",
                    headers=headers,
                    json={"url": query, "formats": ["markdown"]},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return ToolResult(success=False, error=f"Firecrawl HTTP {resp.status}: {text[:200]}")
                    data = await resp.json()

                content = data.get("data", {}).get("markdown", "")
                return ToolResult(success=True, data={
                    "url": query,
                    "content": content[:5000],
                    "source": "firecrawl",
                })
            else:
                # Search
                async with session.post(
                    "https://api.firecrawl.dev/v1/search",
                    headers=headers,
                    json={"query": query, "limit": max_results},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return ToolResult(success=False, error=f"Firecrawl HTTP {resp.status}: {text[:200]}")
                    data = await resp.json()

        results = []
        for item in data.get("data", [])[:max_results]:
            results.append({
                "title": item.get("title", item.get("metadata", {}).get("title", "")),
                "url": item.get("url", ""),
                "snippet": item.get("markdown", item.get("description", ""))[:500],
                "source": "firecrawl",
            })

        logger.info("Firecrawl returned %d results", len(results))
        return ToolResult(success=True, data=results)


class WebReaderTool:
    """Инструмент для чтения содержимого веб-страниц.

    Использует Jina Reader API (r.jina.ai) для конвертации
    веб-страницы в чистый текст/markdown.
    Fallback: Firecrawl scrape.
    """

    def __init__(
        self,
        jina_key: str | None = None,
        firecrawl_key: str | None = None,
    ) -> None:
        self._jina_key = jina_key or os.getenv("JINA_API_KEY", "")
        self._firecrawl_key = firecrawl_key or os.getenv("FIRECRAWL_API_KEY", "")

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_reader",
            description="Read and extract content from a web page URL",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL of the web page to read",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Read web page content."""
        url: str = kwargs.get("url", "")
        if not url:
            return ToolResult(success=False, error="URL is required")

        # Try Jina Reader first
        if self._jina_key:
            try:
                return await self._read_jina(url)
            except Exception as e:
                logger.warning("Jina Reader failed: %s", e)

        # Fallback to Firecrawl
        if self._firecrawl_key:
            try:
                return await self._read_firecrawl(url)
            except Exception as e:
                logger.warning("Firecrawl failed: %s", e)

        return ToolResult(success=False, error="No web reader API keys configured (JINA_API_KEY or FIRECRAWL_API_KEY)")

    async def _read_jina(self, url: str) -> ToolResult:
        """Read URL using Jina Reader API."""
        headers = {
            "Authorization": f"Bearer {self._jina_key}",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://r.jina.ai/{url}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return ToolResult(success=False, error=f"Jina Reader HTTP {resp.status}: {text[:200]}")
                data = await resp.json()

        content = data.get("data", {}).get("content", "")
        title = data.get("data", {}).get("title", "")

        return ToolResult(success=True, data={
            "url": url,
            "title": title,
            "content": content[:10000],
            "source": "jina",
        })

    async def _read_firecrawl(self, url: str) -> ToolResult:
        """Read URL using Firecrawl scrape."""
        headers = {
            "Authorization": f"Bearer {self._firecrawl_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers=headers,
                json={"url": url, "formats": ["markdown"]},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return ToolResult(success=False, error=f"Firecrawl HTTP {resp.status}: {text[:200]}")
                data = await resp.json()

        content = data.get("data", {}).get("markdown", "")
        title = data.get("data", {}).get("metadata", {}).get("title", "")

        return ToolResult(success=True, data={
            "url": url,
            "title": title,
            "content": content[:10000],
            "source": "firecrawl",
        })


class WebExtractTool:
    """Extract clean content from URLs using Tavily Extract API.

    Costs 1 credit per 5 URLs. Much cheaper than web_reader (Jina/Firecrawl)
    and supports batch extraction of up to 20 URLs at once.
    """

    def __init__(self, tavily_key: str | None = None) -> None:
        self._tavily_key = tavily_key or os.getenv("TAVILY_API_KEY", "")
        self._tavily_client: Any = None

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_extract",
            description=(
                "Extract clean content from one or more web page URLs. "
                "Returns markdown text, images, and metadata. "
                "Supports up to 20 URLs at once. Costs 1 credit per 5 URLs."
            ),
            parameters=[
                ToolParameter(
                    name="urls",
                    type="array",
                    description="List of URLs to extract content from (max 20)",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Extract content from URLs using Tavily Extract."""
        urls = kwargs.get("urls", [])

        # Handle single URL passed as string
        if isinstance(urls, str):
            urls = [urls]

        if not urls:
            return ToolResult(success=False, error="At least one URL is required")

        if len(urls) > 20:
            return ToolResult(success=False, error="Maximum 20 URLs per request")

        pool = get_tavily_pool()

        if pool and pool.available:
            client = pool.get_client()
        elif self._tavily_key:
            from tavily import TavilyClient
            if self._tavily_client is None:
                self._tavily_client = TavilyClient(api_key=self._tavily_key)
            client = self._tavily_client
        else:
            return ToolResult(success=False, error="TAVILY_API_KEY not set")

        try:
            response = await asyncio.to_thread(lambda: client.extract(urls=urls))
        except Exception as e:
            if pool and TavilyKeyPool.is_credit_error(e) and pool.rotate():
                logger.warning("Tavily credits exhausted (extract), rotated key: %s", e)
                client = pool.get_client()
                response = await asyncio.to_thread(lambda: client.extract(urls=urls))
            else:
                logger.error("Tavily extract failed: %s", e)
                return ToolResult(success=False, error=f"Extract failed: {e}")

        results = []
        for item in response.get("results", []):
            results.append({
                "url": item.get("url", ""),
                "content": item.get("raw_content", "")[:10000],
                "images": item.get("images", [])[:5],
            })

        failed = [f.get("url", "") for f in response.get("failed_results", [])]
        if failed:
            logger.warning("Failed to extract %d URLs: %s", len(failed), failed)

        logger.info("Tavily extracted %d URLs successfully", len(results))
        return ToolResult(success=True, data={
            "results": results,
            "failed": failed,
        })


class WebResearchTool:
    """Deep research on a topic using Tavily Research API.

    Creates a comprehensive research report with multiple searches,
    analysis, and citations. Use for in-depth research tasks.

    Cost: mini 4-110 credits, pro 15-250 credits per request.
    """

    def __init__(self, tavily_key: str | None = None) -> None:
        self._tavily_key = tavily_key or os.getenv("TAVILY_API_KEY", "")
        self._tavily_client: Any = None

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_research",
            description=(
                "Conduct deep research on a topic. Tavily performs multiple "
                "searches, analyzes sources, and produces a detailed report "
                "with citations. Use for comprehensive research, articles, "
                "and analysis. Costs 4-250 credits depending on complexity."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Research topic or question",
                    required=True,
                ),
                ToolParameter(
                    name="model",
                    type="string",
                    description="Research depth: mini (cheap, 4-110 credits) or pro (deep, 15-250 credits). Default: mini",
                    required=False,
                    default="mini",
                    enum=["mini", "pro"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute deep research via Tavily Research API."""
        query: str = kwargs.get("query", "")
        model: str = kwargs.get("model", "mini")

        if not query:
            return ToolResult(success=False, error="Research query is required")

        pool = get_tavily_pool()

        if pool and pool.available:
            client = pool.get_client()
        elif self._tavily_key:
            from tavily import TavilyClient
            if self._tavily_client is None:
                self._tavily_client = TavilyClient(api_key=self._tavily_key)
            client = self._tavily_client
        else:
            return ToolResult(success=False, error="TAVILY_API_KEY not set")

        logger.info("Starting Tavily research: '%s' (model=%s)", query, model)

        try:
            return await self._do_research(client, query, model)
        except Exception as e:
            if pool and TavilyKeyPool.is_credit_error(e) and pool.rotate():
                logger.warning("Tavily credits exhausted (research), rotated key: %s", e)
                client = pool.get_client()
                return await self._do_research(client, query, model)
            logger.error("Tavily research failed: %s", e)
            return ToolResult(success=False, error=f"Research failed: {e}")

    async def _do_research(self, client: Any, query: str, model: str) -> ToolResult:
        """Execute research call and poll for results."""
        response = await asyncio.to_thread(
            lambda: client.research(
                input=query,
                model=model,
                citation_format="numbered",
                timeout=600,
            )
        )

        request_id = response.get("request_id", "")
        status = response.get("status", "")

        if status == "completed":
            return self._format_research_result(response)

        # Poll for results (research takes time)
        for _ in range(60):  # Max 5 minutes (60 * 5s)
            await asyncio.sleep(5)
            result = await asyncio.to_thread(lambda: client.get_research(request_id))
            status = result.get("status", "")

            if status == "completed":
                return self._format_research_result(result)
            elif status == "failed":
                return ToolResult(success=False, error="Research task failed")

            logger.debug("Research status: %s", status)

        return ToolResult(success=False, error="Research timed out after 5 minutes")

    def _format_research_result(self, result: dict[str, Any]) -> ToolResult:
        """Format research API response into ToolResult."""
        content = result.get("content", "")
        sources = result.get("sources", [])

        formatted_sources = []
        for src in sources:
            formatted_sources.append({
                "title": src.get("title", ""),
                "url": src.get("url", ""),
            })

        logger.info("Research completed: %d chars, %d sources", len(content), len(sources))
        return ToolResult(success=True, data={
            "report": content,
            "sources": formatted_sources,
        })
