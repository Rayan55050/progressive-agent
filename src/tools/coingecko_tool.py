"""
CoinGecko tool — crypto market data, prices, trending coins.

Free tier: 30 requests/min, no API key needed (demo endpoints).
API docs: https://docs.coingecko.com/reference/introduction
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coingecko.com/api/v3"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class CoinGeckoTool:
    """Crypto market data: prices, market cap, trending, coin details."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="coingecko",
            description=(
                "CoinGecko crypto data (free, 30 req/min). "
                "Actions: 'price' — current price of coins (up to 50 at once); "
                "'markets' — top coins by market cap with full data; "
                "'trending' — trending coins right now; "
                "'coin' — detailed info about specific coin; "
                "'search' — search coins by name/symbol; "
                "'categories' — top crypto categories by market cap; "
                "'global' — global crypto market stats."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'price', 'markets', 'trending', 'coin', 'search', 'categories', 'global'",
                    required=True,
                    enum=["price", "markets", "trending", "coin", "search", "categories", "global"],
                ),
                ToolParameter(
                    name="ids",
                    type="string",
                    description="Comma-separated coin IDs for 'price' (e.g. 'bitcoin,ethereum,solana')",
                    required=False,
                ),
                ToolParameter(
                    name="coin_id",
                    type="string",
                    description="Coin ID for 'coin' action (e.g. 'bitcoin', 'ethereum', 'solana')",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query for 'search' action (e.g. 'pepe', 'doge')",
                    required=False,
                ),
                ToolParameter(
                    name="currency",
                    type="string",
                    description="Quote currency (default 'usd'). Also: 'eur', 'uah', 'btc'",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="string",
                    description="Number of results (default '15')",
                    required=False,
                ),
            ],
        )

    async def _get(self, url: str, params: dict | None = None) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=_TIMEOUT) as resp:
                if resp.status == 429:
                    raise ValueError("CoinGecko rate limit (30/min). Try again later.")
                if resp.status != 200:
                    raise ValueError(f"CoinGecko HTTP {resp.status}")
                return await resp.json()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "markets").strip().lower()
        try:
            if action == "price":
                return await self._price(kwargs)
            elif action == "markets":
                return await self._markets(kwargs)
            elif action == "trending":
                return await self._trending()
            elif action == "coin":
                return await self._coin(kwargs)
            elif action == "search":
                return await self._search(kwargs)
            elif action == "categories":
                return await self._categories(kwargs)
            elif action == "global":
                return await self._global_stats()
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("CoinGecko error: %s", e)
            return ToolResult(success=False, error=f"CoinGecko error: {e}")

    async def _price(self, kwargs: dict) -> ToolResult:
        ids = kwargs.get("ids", "bitcoin,ethereum").strip()
        currency = kwargs.get("currency", "usd").strip().lower()

        data = await self._get(
            f"{BASE_URL}/simple/price",
            {
                "ids": ids,
                "vs_currencies": currency,
                "include_24hr_change": "true",
                "include_market_cap": "true",
            },
        )

        if not data:
            return ToolResult(success=False, error="No price data")

        lines = [f"**Crypto prices ({currency.upper()}):**\n"]
        for coin_id, info in data.items():
            price = info.get(currency, 0)
            change = info.get(f"{currency}_24h_change", 0) or 0
            mcap = info.get(f"{currency}_market_cap", 0) or 0
            sign = "+" if change >= 0 else ""
            arrow = "📈" if change >= 0 else "📉"
            lines.append(
                f"{arrow} **{coin_id}**: {self._fmt_price(price)} {currency.upper()} "
                f"({sign}{change:.2f}%) | MCap: {self._fmt_usd(mcap)}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _markets(self, kwargs: dict) -> ToolResult:
        currency = kwargs.get("currency", "usd").strip().lower()
        limit = int(kwargs.get("limit", "15"))

        data = await self._get(
            f"{BASE_URL}/coins/markets",
            {
                "vs_currency": currency,
                "order": "market_cap_desc",
                "per_page": str(limit),
                "page": "1",
                "sparkline": "false",
            },
        )

        if not data:
            return ToolResult(success=False, error="No market data")

        lines = [f"**Top {limit} crypto by market cap:**\n"]
        for i, c in enumerate(data, 1):
            name = c.get("name", "?")
            symbol = c.get("symbol", "?").upper()
            price = c.get("current_price", 0)
            change_24h = c.get("price_change_percentage_24h", 0) or 0
            mcap = c.get("market_cap", 0) or 0
            vol = c.get("total_volume", 0) or 0

            sign = "+" if change_24h >= 0 else ""
            arrow = "📈" if change_24h >= 0 else "📉"
            lines.append(
                f"{i}. {arrow} **{name}** ({symbol}) — {self._fmt_price(price)} {currency.upper()}\n"
                f"   {sign}{change_24h:.2f}% | MCap: {self._fmt_usd(mcap)} | Vol: {self._fmt_usd(vol)}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _trending(self) -> ToolResult:
        data = await self._get(f"{BASE_URL}/search/trending")

        coins = data.get("coins", [])
        if not coins:
            return ToolResult(success=True, data="No trending coins right now")

        lines = ["**Trending coins on CoinGecko:**\n"]
        for i, item in enumerate(coins[:15], 1):
            c = item.get("item", {})
            name = c.get("name", "?")
            symbol = c.get("symbol", "?")
            mcap_rank = c.get("market_cap_rank", "?")
            price_btc = c.get("price_btc", 0) or 0

            lines.append(
                f"{i}. **{name}** ({symbol}) — rank #{mcap_rank}\n"
                f"   Price: {price_btc:.8f} BTC"
            )

        # Also trending categories if available
        categories = data.get("categories", [])
        if categories:
            lines.append("\n**Trending categories:**")
            for cat in categories[:5]:
                cat_data = cat.get("item", cat)
                lines.append(f"  • {cat_data.get('name', '?')}")

        return ToolResult(success=True, data="\n".join(lines))

    async def _coin(self, kwargs: dict) -> ToolResult:
        coin_id = kwargs.get("coin_id", "").strip().lower()
        if not coin_id:
            return ToolResult(success=False, error="coin_id required (e.g. 'bitcoin', 'ethereum')")

        data = await self._get(
            f"{BASE_URL}/coins/{coin_id}",
            {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
            },
        )

        if not data or not data.get("name"):
            return ToolResult(success=False, error=f"Coin '{coin_id}' not found")

        name = data.get("name", "?")
        symbol = data.get("symbol", "?").upper()
        md = data.get("market_data", {})

        price = md.get("current_price", {}).get("usd", 0)
        mcap = md.get("market_cap", {}).get("usd", 0)
        vol = md.get("total_volume", {}).get("usd", 0)
        high_24h = md.get("high_24h", {}).get("usd", 0)
        low_24h = md.get("low_24h", {}).get("usd", 0)
        ath = md.get("ath", {}).get("usd", 0)
        ath_change = md.get("ath_change_percentage", {}).get("usd", 0)
        change_24h = md.get("price_change_percentage_24h", 0) or 0
        change_7d = md.get("price_change_percentage_7d", 0) or 0
        change_30d = md.get("price_change_percentage_30d", 0) or 0
        total_supply = md.get("total_supply", 0)
        circulating = md.get("circulating_supply", 0)
        rank = data.get("market_cap_rank", "?")

        desc = data.get("description", {}).get("en", "")
        if desc:
            # Strip HTML
            import re
            desc = re.sub(r"<[^>]+>", "", desc)[:200]

        result = (
            f"**{name}** ({symbol}) — #{rank}\n"
            f"Price: ${self._fmt_price(price)}\n"
            f"24h: {'+' if change_24h >= 0 else ''}{change_24h:.2f}% | "
            f"7d: {'+' if change_7d >= 0 else ''}{change_7d:.2f}% | "
            f"30d: {'+' if change_30d >= 0 else ''}{change_30d:.2f}%\n"
            f"High/Low 24h: ${self._fmt_price(high_24h)} / ${self._fmt_price(low_24h)}\n"
            f"ATH: ${self._fmt_price(ath)} ({ath_change:.1f}% from ATH)\n"
            f"Market cap: {self._fmt_usd(mcap)} | Vol: {self._fmt_usd(vol)}\n"
            f"Supply: {self._fmt_supply(circulating)} / {self._fmt_supply(total_supply)}\n"
            f"\n{desc}"
        )
        return ToolResult(success=True, data=result)

    async def _search(self, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Query required for search")

        data = await self._get(f"{BASE_URL}/search", {"query": query})
        coins = data.get("coins", [])

        if not coins:
            return ToolResult(success=True, data=f"No coins found for '{query}'")

        lines = [f"**Search '{query}':**\n"]
        for c in coins[:10]:
            name = c.get("name", "?")
            symbol = c.get("symbol", "?")
            coin_id = c.get("id", "?")
            rank = c.get("market_cap_rank") or "?"
            lines.append(f"  **{name}** ({symbol}) — id: `{coin_id}` | rank #{rank}")

        return ToolResult(success=True, data="\n".join(lines))

    async def _categories(self, kwargs: dict) -> ToolResult:
        limit = int(kwargs.get("limit", "15"))
        data = await self._get(
            f"{BASE_URL}/coins/categories",
            {"order": "market_cap_desc"},
        )

        if not data:
            return ToolResult(success=False, error="No category data")

        lines = ["**Top crypto categories:**\n"]
        for i, cat in enumerate(data[:limit], 1):
            name = cat.get("name", "?")
            mcap = cat.get("market_cap", 0) or 0
            change = cat.get("market_cap_change_24h", 0) or 0
            top3 = cat.get("top_3_coins", [])
            sign = "+" if change >= 0 else ""
            lines.append(
                f"{i}. **{name}** — {self._fmt_usd(mcap)} ({sign}{change:.2f}%)"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _global_stats(self) -> ToolResult:
        data = await self._get(f"{BASE_URL}/global")
        d = data.get("data", {})

        if not d:
            return ToolResult(success=False, error="No global data")

        total_mcap = d.get("total_market_cap", {}).get("usd", 0)
        total_vol = d.get("total_volume", {}).get("usd", 0)
        btc_dom = d.get("market_cap_percentage", {}).get("btc", 0)
        eth_dom = d.get("market_cap_percentage", {}).get("eth", 0)
        active_coins = d.get("active_cryptocurrencies", 0)
        markets = d.get("markets", 0)
        change_24h = d.get("market_cap_change_percentage_24h_usd", 0) or 0

        sign = "+" if change_24h >= 0 else ""
        result = (
            f"**Global Crypto Market:**\n"
            f"Total Market Cap: {self._fmt_usd(total_mcap)} ({sign}{change_24h:.2f}% 24h)\n"
            f"24h Volume: {self._fmt_usd(total_vol)}\n"
            f"BTC Dominance: {btc_dom:.1f}%\n"
            f"ETH Dominance: {eth_dom:.1f}%\n"
            f"Active coins: {active_coins:,}\n"
            f"Markets: {markets:,}"
        )
        return ToolResult(success=True, data=result)

    @staticmethod
    def _fmt_usd(value: float) -> str:
        if not value:
            return "$0"
        if value >= 1_000_000_000_000:
            return f"${value / 1_000_000_000_000:.2f}T"
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        elif value >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:.0f}"

    @staticmethod
    def _fmt_price(value: float) -> str:
        if not value:
            return "0"
        if value >= 1:
            return f"{value:,.2f}"
        elif value >= 0.01:
            return f"{value:.4f}"
        else:
            return f"{value:.8f}"

    @staticmethod
    def _fmt_supply(value: float | None) -> str:
        if not value:
            return "?"
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        elif value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:.0f}"
