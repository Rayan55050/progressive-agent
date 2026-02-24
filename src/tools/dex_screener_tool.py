"""
DexScreener tool — real-time DEX pair prices, trending tokens, new pools.

100% FREE, no API key needed.
API docs: https://docs.dexscreener.com/api/reference
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class DexScreenerTool:
    """Real-time DEX pair data: search tokens, trending, new pairs."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="dex_screener",
            description=(
                "DexScreener: real-time DEX data (free, no API key). "
                "Actions: 'search' — find token pairs by name/symbol/address; "
                "'trending' — top boosted/trending tokens; "
                "'pair' — get specific pair info by chain + pair address; "
                "'token' — all pairs for a token address; "
                "'new_pairs' — recently created pairs. "
                "Covers all major DEXes: Uniswap, PancakeSwap, Raydium, etc."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'search', 'trending', 'pair', 'token', 'new_pairs'",
                    required=True,
                    enum=["search", "trending", "pair", "token", "new_pairs"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query for 'search' (e.g. 'PEPE', 'SOL', 'Uniswap')",
                    required=False,
                ),
                ToolParameter(
                    name="chain",
                    type="string",
                    description="Chain for 'pair'/'new_pairs' (e.g. 'ethereum', 'solana', 'bsc', 'arbitrum')",
                    required=False,
                ),
                ToolParameter(
                    name="address",
                    type="string",
                    description="Token or pair address for 'pair'/'token' actions",
                    required=False,
                ),
            ],
        )

    async def _get(self, url: str) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"DexScreener HTTP {resp.status}")
                return await resp.json()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "search").strip().lower()
        try:
            if action == "search":
                return await self._search(kwargs)
            elif action == "trending":
                return await self._trending()
            elif action == "pair":
                return await self._pair(kwargs)
            elif action == "token":
                return await self._token(kwargs)
            elif action == "new_pairs":
                return await self._new_pairs(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("DexScreener error: %s", e)
            return ToolResult(success=False, error=f"DexScreener error: {e}")

    async def _search(self, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Query required for search")

        data = await self._get(f"{BASE_URL}/latest/dex/search?q={query}")
        pairs = data.get("pairs") or []

        if not pairs:
            return ToolResult(success=True, data=f"No pairs found for '{query}'")

        lines = [f"**DEX pairs for '{query}':**\n"]
        for p in pairs[:10]:
            lines.append(self._format_pair(p))

        return ToolResult(success=True, data="\n".join(lines))

    async def _trending(self) -> ToolResult:
        data = await self._get(f"{BASE_URL}/token-boosts/top/v1")

        if not data:
            return ToolResult(success=True, data="No trending tokens right now")

        lines = ["**Trending tokens (DexScreener boosts):**\n"]
        seen = set()
        for t in data[:15]:
            token_addr = t.get("tokenAddress", "")
            if token_addr in seen:
                continue
            seen.add(token_addr)

            symbol = t.get("symbol") or t.get("name") or "?"
            chain = t.get("chainId", "?")
            description = t.get("description", "")[:80]
            url = t.get("url", "")

            lines.append(
                f"  **{symbol}** ({chain})\n"
                f"  {description}\n"
                f"  {url}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _pair(self, kwargs: dict) -> ToolResult:
        chain = kwargs.get("chain", "").strip().lower()
        address = kwargs.get("address", "").strip()

        if not chain or not address:
            return ToolResult(success=False, error="Both 'chain' and 'address' required for pair lookup")

        data = await self._get(f"{BASE_URL}/latest/dex/pairs/{chain}/{address}")
        pairs = data.get("pairs") or data.get("pair")

        if not pairs:
            return ToolResult(success=False, error=f"Pair not found: {chain}/{address}")

        if isinstance(pairs, list):
            pair = pairs[0]
        else:
            pair = pairs

        return ToolResult(success=True, data=self._format_pair_detailed(pair))

    async def _token(self, kwargs: dict) -> ToolResult:
        address = kwargs.get("address", "").strip()
        if not address:
            return ToolResult(success=False, error="Token address required")

        data = await self._get(f"{BASE_URL}/latest/dex/tokens/{address}")
        pairs = data.get("pairs") or []

        if not pairs:
            return ToolResult(success=False, error=f"No pairs for token {address}")

        lines = [f"**Pairs for token {address[:10]}...:**\n"]
        for p in pairs[:10]:
            lines.append(self._format_pair(p))

        return ToolResult(success=True, data="\n".join(lines))

    async def _new_pairs(self, kwargs: dict) -> ToolResult:
        chain = kwargs.get("chain", "").strip().lower()

        # DexScreener latest profiles endpoint
        data = await self._get(f"{BASE_URL}/token-profiles/latest/v1")

        if not data:
            return ToolResult(success=True, data="No new pairs data")

        if chain:
            data = [t for t in data if t.get("chainId", "").lower() == chain]

        lines = [f"**Latest token profiles{f' ({chain})' if chain else ''}:**\n"]
        for t in data[:15]:
            symbol = t.get("symbol") or t.get("name") or "?"
            ch = t.get("chainId", "?")
            desc = t.get("description", "")[:80]
            url = t.get("url", "")
            lines.append(f"  **{symbol}** ({ch}) — {desc}\n  {url}")

        return ToolResult(success=True, data="\n".join(lines))

    def _format_pair(self, p: dict) -> str:
        base = p.get("baseToken", {})
        quote = p.get("quoteToken", {})
        name = f"{base.get('symbol', '?')}/{quote.get('symbol', '?')}"
        price = p.get("priceUsd", "?")
        chain = p.get("chainId", "?")
        dex = p.get("dexId", "?")
        vol_24h = p.get("volume", {}).get("h24", 0)
        liq = p.get("liquidity", {}).get("usd", 0)
        change_24h = p.get("priceChange", {}).get("h24", 0)

        sign = "+" if (change_24h or 0) >= 0 else ""
        return (
            f"  **{name}** — ${price} ({sign}{change_24h or 0:.1f}% 24h)\n"
            f"  {dex} on {chain} | Vol: ${self._fmt(vol_24h)} | Liq: ${self._fmt(liq)}"
        )

    def _format_pair_detailed(self, p: dict) -> str:
        base = p.get("baseToken", {})
        quote = p.get("quoteToken", {})
        name = f"{base.get('symbol', '?')}/{quote.get('symbol', '?')}"
        price = p.get("priceUsd", "?")
        chain = p.get("chainId", "?")
        dex = p.get("dexId", "?")
        vol = p.get("volume", {})
        price_change = p.get("priceChange", {})
        liq = p.get("liquidity", {}).get("usd", 0)
        fdv = p.get("fdv", 0)
        pair_created = p.get("pairCreatedAt", "")
        url = p.get("url", "")

        return (
            f"**{name}** on {dex} ({chain})\n"
            f"Price: ${price}\n"
            f"Changes: 5m {price_change.get('m5', '?')}% | "
            f"1h {price_change.get('h1', '?')}% | "
            f"6h {price_change.get('h6', '?')}% | "
            f"24h {price_change.get('h24', '?')}%\n"
            f"Volume 24h: ${self._fmt(vol.get('h24', 0))}\n"
            f"Liquidity: ${self._fmt(liq)}\n"
            f"FDV: ${self._fmt(fdv)}\n"
            f"Base: {base.get('name', '?')} ({base.get('address', '?')[:12]}...)\n"
            f"{url}"
        )

    @staticmethod
    def _fmt(value: float | None) -> str:
        if not value:
            return "0"
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        elif value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:.0f}"
