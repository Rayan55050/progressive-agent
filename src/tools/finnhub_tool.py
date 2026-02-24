"""
Finnhub finance tool — real-time stocks, forex, crypto data.

Free tier: 60 API calls/minute, unlimited daily.
Uses aiohttp directly.

API docs: https://finnhub.io/docs/api
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


class FinnhubTool:
    """Real-time financial data: stocks, forex, crypto quotes and news."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="finance",
            description=(
                "Get real-time financial data from Finnhub. "
                "Actions: 'quote' — stock/crypto price (e.g. AAPL, BINANCE:BTCUSDT); "
                "'search' — find ticker symbol by name; "
                "'news' — market news (general or company-specific); "
                "'candles' — historical OHLCV data; "
                "'profile' — company profile info. "
                "Free tier: 60 calls/min."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'quote', 'search', 'news', 'candles', 'profile'",
                    required=True,
                    enum=["quote", "search", "news", "candles", "profile"],
                ),
                ToolParameter(
                    name="symbol",
                    type="string",
                    description=(
                        "Ticker symbol (e.g. 'AAPL', 'MSFT', 'BINANCE:BTCUSDT', 'OANDA:EUR_USD'). "
                        "Required for quote, candles, profile."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (for 'search' action, e.g. 'Apple', 'Bitcoin')",
                    required=False,
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="News category for 'news' action: 'general', 'forex', 'crypto', 'merger'",
                    required=False,
                    enum=["general", "forex", "crypto", "merger"],
                ),
            ],
        )

    async def _api_get(self, endpoint: str, params: dict[str, str]) -> dict | list:
        """Make authenticated GET request to Finnhub API."""
        params["token"] = self._api_key
        url = f"{FINNHUB_BASE}{endpoint}"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 401:
                    raise ValueError("Finnhub API key invalid")
                if resp.status == 429:
                    raise ValueError("Finnhub rate limit exceeded (60/min)")
                if resp.status != 200:
                    body = await resp.text()
                    raise ValueError(f"Finnhub API error {resp.status}: {body[:200]}")
                return await resp.json()

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._api_key:
            return ToolResult(
                success=False,
                error="Finnhub API key not configured. Get free key at https://finnhub.io/ and set FINNHUB_API_KEY in .env",
            )

        action = kwargs.get("action", "").strip().lower()

        try:
            if action == "quote":
                return await self._quote(kwargs)
            elif action == "search":
                return await self._search(kwargs)
            elif action == "news":
                return await self._news(kwargs)
            elif action == "candles":
                return await self._candles(kwargs)
            elif action == "profile":
                return await self._profile(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("Finnhub error: %s", e)
            return ToolResult(success=False, error=f"Finnhub error: {e}")

    async def _quote(self, kwargs: dict) -> ToolResult:
        symbol = kwargs.get("symbol", "").strip().upper()
        if not symbol:
            return ToolResult(success=False, error="Symbol required for quote (e.g. 'AAPL')")

        data = await self._api_get("/quote", {"symbol": symbol})

        if not data or data.get("c", 0) == 0:
            return ToolResult(success=False, error=f"No quote data for {symbol}. Check symbol.")

        current = data.get("c", 0)
        change = data.get("d", 0)
        change_pct = data.get("dp", 0)
        high = data.get("h", 0)
        low = data.get("l", 0)
        open_price = data.get("o", 0)
        prev_close = data.get("pc", 0)

        arrow = "📈" if change >= 0 else "📉"
        sign = "+" if change >= 0 else ""

        result = (
            f"{arrow} **{symbol}**: ${current:.2f}\n"
            f"Change: {sign}{change:.2f} ({sign}{change_pct:.2f}%)\n"
            f"Open: ${open_price:.2f} | High: ${high:.2f} | Low: ${low:.2f}\n"
            f"Prev close: ${prev_close:.2f}"
        )
        return ToolResult(success=True, data=result)

    async def _search(self, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Query required for search")

        data = await self._api_get("/search", {"q": query})
        results = data.get("result", [])

        if not results:
            return ToolResult(success=True, data=f"No results for '{query}'")

        lines = [f"Search results for '{query}':"]
        for item in results[:10]:
            symbol = item.get("symbol", "?")
            desc = item.get("description", "")
            item_type = item.get("type", "")
            lines.append(f"  {symbol} — {desc} [{item_type}]")

        return ToolResult(success=True, data="\n".join(lines))

    async def _news(self, kwargs: dict) -> ToolResult:
        category = kwargs.get("category", "general").strip().lower()
        symbol = kwargs.get("symbol", "").strip().upper()

        if symbol:
            # Company-specific news
            from datetime import datetime, timedelta
            today = datetime.now().strftime("%Y-%m-%d")
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            data = await self._api_get(
                "/company-news",
                {"symbol": symbol, "from": week_ago, "to": today},
            )
        else:
            data = await self._api_get("/news", {"category": category})

        if not data:
            return ToolResult(success=True, data="No news found")

        lines = [f"Market news ({category}):"] if not symbol else [f"News for {symbol}:"]
        for article in data[:8]:
            headline = article.get("headline", "")
            source = article.get("source", "")
            url = article.get("url", "")
            lines.append(f"  • {headline} [{source}]\n    {url}")

        return ToolResult(success=True, data="\n".join(lines))

    async def _candles(self, kwargs: dict) -> ToolResult:
        symbol = kwargs.get("symbol", "").strip().upper()
        if not symbol:
            return ToolResult(success=False, error="Symbol required for candles")

        import time
        now = int(time.time())
        week_ago = now - 7 * 24 * 3600

        data = await self._api_get(
            "/stock/candle",
            {"symbol": symbol, "resolution": "D", "from": str(week_ago), "to": str(now)},
        )

        if data.get("s") == "no_data":
            return ToolResult(success=False, error=f"No candle data for {symbol}")

        closes = data.get("c", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        timestamps = data.get("t", [])

        from datetime import datetime
        lines = [f"Daily candles for {symbol} (last {len(closes)} days):"]
        for i in range(len(closes)):
            dt = datetime.fromtimestamp(timestamps[i]).strftime("%m/%d")
            lines.append(f"  {dt}: Close ${closes[i]:.2f} | H ${highs[i]:.2f} | L ${lows[i]:.2f}")

        return ToolResult(success=True, data="\n".join(lines))

    async def _profile(self, kwargs: dict) -> ToolResult:
        symbol = kwargs.get("symbol", "").strip().upper()
        if not symbol:
            return ToolResult(success=False, error="Symbol required for profile")

        data = await self._api_get("/stock/profile2", {"symbol": symbol})

        if not data or not data.get("name"):
            return ToolResult(success=False, error=f"No profile for {symbol}")

        result = (
            f"**{data.get('name', '?')}** ({data.get('ticker', '?')})\n"
            f"Industry: {data.get('finnhubIndustry', '?')}\n"
            f"Country: {data.get('country', '?')}\n"
            f"Market cap: ${data.get('marketCapitalization', 0):.0f}M\n"
            f"IPO: {data.get('ipo', '?')}\n"
            f"Web: {data.get('weburl', '?')}"
        )
        return ToolResult(success=True, data=result)
