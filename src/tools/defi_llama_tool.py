"""
DefiLlama tool — DeFi protocol analytics, TVL, yields, DEX volumes.

100% FREE, no API key, no rate limits.
API docs: https://defillama.com/docs/api
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.llama.fi"
YIELDS_URL = "https://yields.llama.fi"
STABLECOINS_URL = "https://stablecoins.llama.fi"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class DefiLlamaTool:
    """DeFi analytics: TVL, yields, stablecoins, DEX volumes from DefiLlama."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="defi_llama",
            description=(
                "DeFi analytics from DefiLlama (free, no API key). "
                "Actions: 'tvl' — top protocols by TVL; "
                "'chain' — TVL by blockchain (Ethereum, Solana, etc.); "
                "'protocol' — detailed info about specific protocol; "
                "'yields' — top yield pools (APY); "
                "'stablecoins' — stablecoin market caps; "
                "'dex_volumes' — DEX trading volumes. "
                "No rate limits."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'tvl', 'chain', 'protocol', 'yields', 'stablecoins', 'dex_volumes'",
                    required=True,
                    enum=["tvl", "chain", "protocol", "yields", "stablecoins", "dex_volumes"],
                ),
                ToolParameter(
                    name="protocol",
                    type="string",
                    description="Protocol slug for 'protocol' action (e.g. 'aave', 'uniswap', 'lido')",
                    required=False,
                ),
                ToolParameter(
                    name="chain",
                    type="string",
                    description="Chain name for 'chain' action (e.g. 'Ethereum', 'Solana', 'Arbitrum')",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="string",
                    description="Number of results to return (default '15')",
                    required=False,
                ),
            ],
        )

    async def _get(self, url: str) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"DefiLlama HTTP {resp.status}")
                return await resp.json()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "tvl").strip().lower()
        try:
            if action == "tvl":
                return await self._top_tvl(kwargs)
            elif action == "chain":
                return await self._chain_tvl(kwargs)
            elif action == "protocol":
                return await self._protocol_info(kwargs)
            elif action == "yields":
                return await self._top_yields(kwargs)
            elif action == "stablecoins":
                return await self._stablecoins(kwargs)
            elif action == "dex_volumes":
                return await self._dex_volumes(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("DefiLlama error: %s", e)
            return ToolResult(success=False, error=f"DefiLlama error: {e}")

    async def _top_tvl(self, kwargs: dict) -> ToolResult:
        limit = int(kwargs.get("limit", "15"))
        data = await self._get(f"{BASE_URL}/protocols")

        if not data:
            return ToolResult(success=False, error="No protocol data")

        # Already sorted by TVL descending
        lines = ["**Top DeFi protocols by TVL:**\n"]
        for i, p in enumerate(data[:limit], 1):
            name = p.get("name", "?")
            tvl = p.get("tvl", 0)
            chain = p.get("chain", "Multi")
            change_1d = p.get("change_1d", 0) or 0
            category = p.get("category", "")

            tvl_fmt = self._fmt_usd(tvl)
            sign = "+" if change_1d >= 0 else ""
            lines.append(
                f"{i}. **{name}** — {tvl_fmt} ({sign}{change_1d:.1f}% 24h)\n"
                f"   Chain: {chain} | {category}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _chain_tvl(self, kwargs: dict) -> ToolResult:
        chain_name = kwargs.get("chain", "").strip()

        if chain_name:
            # Specific chain TVL history
            data = await self._get(f"{BASE_URL}/v2/historicalChainTvl/{chain_name}")
            if not data:
                return ToolResult(success=False, error=f"No data for chain '{chain_name}'")

            # Get last entry
            latest = data[-1] if data else {}
            tvl = latest.get("tvl", 0)
            return ToolResult(
                success=True,
                data=f"**{chain_name}** TVL: {self._fmt_usd(tvl)}",
            )
        else:
            # All chains
            data = await self._get(f"{BASE_URL}/v2/chains")
            if not data:
                return ToolResult(success=False, error="No chain data")

            # Sort by TVL
            data.sort(key=lambda x: x.get("tvl", 0), reverse=True)
            limit = int(kwargs.get("limit", "15"))

            lines = ["**Top blockchains by TVL:**\n"]
            for i, c in enumerate(data[:limit], 1):
                name = c.get("name", "?")
                tvl = c.get("tvl", 0)
                lines.append(f"{i}. **{name}** — {self._fmt_usd(tvl)}")

            return ToolResult(success=True, data="\n".join(lines))

    async def _protocol_info(self, kwargs: dict) -> ToolResult:
        slug = kwargs.get("protocol", "").strip().lower()
        if not slug:
            return ToolResult(success=False, error="Protocol slug required (e.g. 'aave', 'uniswap')")

        data = await self._get(f"{BASE_URL}/protocol/{slug}")
        if not data or not data.get("name"):
            return ToolResult(success=False, error=f"Protocol '{slug}' not found")

        name = data.get("name", "?")
        tvl = data.get("tvl", 0)
        category = data.get("category", "?")
        chains = data.get("chains", [])
        description = data.get("description", "")
        url = data.get("url", "")
        change_1d = data.get("change_1d", 0) or 0
        change_7d = data.get("change_7d", 0) or 0

        chains_str = ", ".join(chains[:10])
        if len(chains) > 10:
            chains_str += f" (+{len(chains) - 10} more)"

        result = (
            f"**{name}** ({category})\n"
            f"TVL: {self._fmt_usd(tvl)}\n"
            f"24h: {'+' if change_1d >= 0 else ''}{change_1d:.1f}% | "
            f"7d: {'+' if change_7d >= 0 else ''}{change_7d:.1f}%\n"
            f"Chains: {chains_str}\n"
            f"{description[:200]}\n"
            f"URL: {url}"
        )
        return ToolResult(success=True, data=result)

    async def _top_yields(self, kwargs: dict) -> ToolResult:
        limit = int(kwargs.get("limit", "15"))
        data = await self._get(f"{YIELDS_URL}/pools")

        if not data or not data.get("data"):
            return ToolResult(success=False, error="No yield data")

        pools = data["data"]
        # Filter out tiny pools and sort by APY
        pools = [p for p in pools if (p.get("tvlUsd") or 0) > 100_000]
        pools.sort(key=lambda x: x.get("apy", 0) or 0, reverse=True)

        lines = ["**Top DeFi yield pools (APY, TVL > $100K):**\n"]
        for i, p in enumerate(pools[:limit], 1):
            project = p.get("project", "?")
            symbol = p.get("symbol", "?")
            chain = p.get("chain", "?")
            apy = p.get("apy", 0) or 0
            tvl = p.get("tvlUsd", 0) or 0

            lines.append(
                f"{i}. **{project}** — {symbol}\n"
                f"   APY: {apy:.1f}% | TVL: {self._fmt_usd(tvl)} | {chain}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _stablecoins(self, kwargs: dict) -> ToolResult:
        limit = int(kwargs.get("limit", "15"))
        data = await self._get(f"{STABLECOINS_URL}/stablecoins?includePrices=true")

        if not data or not data.get("peggedAssets"):
            return ToolResult(success=False, error="No stablecoin data")

        stables = data["peggedAssets"]
        # Sort by market cap (circulating)
        stables.sort(
            key=lambda x: sum(v.get("peggedUSD", 0) or 0 for v in (x.get("chainCirculating") or {}).values()),
            reverse=True,
        )

        lines = ["**Top stablecoins by market cap:**\n"]
        for i, s in enumerate(stables[:limit], 1):
            name = s.get("name", "?")
            symbol = s.get("symbol", "?")
            peg = s.get("pegMechanism", "?")
            # Calculate total circulating
            chain_circ = s.get("chainCirculating") or {}
            total = sum(v.get("peggedUSD", 0) or 0 for v in chain_circ.values())

            lines.append(
                f"{i}. **{name}** ({symbol}) — {self._fmt_usd(total)}\n"
                f"   Peg: {peg}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    async def _dex_volumes(self, kwargs: dict) -> ToolResult:
        limit = int(kwargs.get("limit", "15"))
        data = await self._get(f"{BASE_URL}/overview/dexs")

        if not data or not data.get("protocols"):
            return ToolResult(success=False, error="No DEX volume data")

        dexes = data["protocols"]
        # Sort by daily volume
        dexes.sort(key=lambda x: x.get("dailyVolume", 0) or 0, reverse=True)

        total_volume = data.get("totalDataChart", [])
        total_daily = data.get("total24h", 0) or 0

        lines = [f"**DEX volumes (total 24h: {self._fmt_usd(total_daily)}):**\n"]
        for i, d in enumerate(dexes[:limit], 1):
            name = d.get("name", "?")
            vol_24h = d.get("dailyVolume", 0) or 0
            change = d.get("change_1d", 0) or 0
            chains = d.get("chains", [])
            chains_str = ", ".join(chains[:3])

            sign = "+" if change >= 0 else ""
            lines.append(
                f"{i}. **{name}** — {self._fmt_usd(vol_24h)} ({sign}{change:.1f}%)\n"
                f"   Chains: {chains_str}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    @staticmethod
    def _fmt_usd(value: float) -> str:
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        elif value >= 1_000:
            return f"${value / 1_000:.1f}K"
        else:
            return f"${value:.0f}"
