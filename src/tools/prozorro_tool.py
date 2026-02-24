"""
Prozorro tool — Ukrainian public procurement (tenders, contracts).

Free public API, no API key, no registration.
API docs: https://prozorro-api-docs.readthedocs.io/
Base URL: https://public-api.prozorro.gov.ua/api/2.5
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://public-api.prozorro.gov.ua/api/2.5"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_HEADERS = {"User-Agent": "ProgressiveAgent/1.0"}


class ProzorroTool:
    """Ukrainian public procurement: tenders, contracts, plans."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="prozorro",
            description=(
                "Prozorro — все госзакупки Украины (free API, без ключа). "
                "Actions: 'tenders' — последние тендеры (с фильтрами); "
                "'tender' — детали конкретного тендера по ID; "
                "'contracts' — последние контракты; "
                "'plans' — планы закупок; "
                "'search' — поиск тендеров по ключевому слову (в описании). "
                "Используй когда спрашивают: 'тендеры', 'госзакупки', 'прозорро', "
                "'закупки по ЄДРПОУ', 'prozorro', 'держзакупівлі'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "Action: 'tenders', 'tender', 'contracts', 'plans', 'search'"
                    ),
                    required=True,
                    enum=["tenders", "tender", "contracts", "plans", "search"],
                ),
                ToolParameter(
                    name="tender_id",
                    type="string",
                    description="Tender ID for 'tender' action (e.g. 'UA-2024-01-01-000001-a')",
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
                    description="Number of results (default 10, max 100)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "tenders")
        limit = min(int(kwargs.get("limit", 10)), 100)

        try:
            if action == "tenders":
                return await self._list_tenders(limit)
            elif action == "tender":
                tender_id = kwargs.get("tender_id", "")
                if not tender_id:
                    return ToolResult(success=False, error="tender_id is required for 'tender' action")
                return await self._get_tender(tender_id)
            elif action == "contracts":
                return await self._list_contracts(limit)
            elif action == "plans":
                return await self._list_plans(limit)
            elif action == "search":
                query = kwargs.get("query", "")
                if not query:
                    return ToolResult(success=False, error="query is required for 'search' action")
                return await self._search_tenders(query, limit)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            logger.exception("Prozorro API error")
            return ToolResult(success=False, error=f"Prozorro API error: {e}")

    async def _list_tenders(self, limit: int) -> ToolResult:
        """Get latest tenders (newest first)."""
        url = f"{BASE_URL}/tenders"
        params = {"limit": limit, "descending": "1"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        items = data.get("data", [])
        if not items:
            return ToolResult(success=True, data={"answer": "Тендеров не найдено."})

        # Fetch details for each tender (feed only contains IDs)
        tenders = await self._fetch_tender_details(items[:limit])

        lines = [f"Последние {len(tenders)} тендеров Prozorro:\n"]
        for i, t in enumerate(tenders, 1):
            lines.append(self._format_tender_short(i, t))

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(tenders),
        })

    async def _get_tender(self, tender_id: str) -> ToolResult:
        """Get full tender details."""
        url = f"{BASE_URL}/tenders/{tender_id}"

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url) as resp:
                if resp.status == 404:
                    return ToolResult(success=False, error=f"Tender not found: {tender_id}")
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        t = data.get("data", {})
        return ToolResult(success=True, data={
            "answer": self._format_tender_full(t),
        })

    async def _list_contracts(self, limit: int) -> ToolResult:
        """Get latest contracts."""
        url = f"{BASE_URL}/contracts"
        params = {"limit": limit, "descending": "1"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        items = data.get("data", [])
        lines = [f"Последние {len(items)} контрактов Prozorro:\n"]
        for i, c in enumerate(items, 1):
            cid = c.get("id", "?")
            date = c.get("dateModified", "")[:10]
            lines.append(f"{i}. ID: {cid} | Дата: {date}")

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(items),
        })

    async def _list_plans(self, limit: int) -> ToolResult:
        """Get latest procurement plans."""
        url = f"{BASE_URL}/plans"
        params = {"limit": limit, "descending": "1"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        items = data.get("data", [])
        lines = [f"Последние {len(items)} планов закупок:\n"]
        for i, p in enumerate(items, 1):
            pid = p.get("id", "?")
            date = p.get("dateModified", "")[:10]
            lines.append(f"{i}. ID: {pid} | Дата: {date}")

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(items),
        })

    async def _search_tenders(self, query: str, limit: int) -> ToolResult:
        """Search tenders — fetches recent and filters by keyword in title/description."""
        # Prozorro API is feed-based (no search endpoint), so we fetch a batch
        # and filter client-side by keyword
        url = f"{BASE_URL}/tenders"
        params = {"limit": 100, "descending": "1"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        items = data.get("data", [])
        # Fetch details for filtering
        tenders = await self._fetch_tender_details(items)

        query_lower = query.lower()
        matched = []
        for t in tenders:
            title = t.get("title", "").lower()
            desc = t.get("description", "").lower()
            edrpou = t.get("procuringEntity", {}).get("identifier", {}).get("id", "").lower()
            entity_name = t.get("procuringEntity", {}).get("name", "").lower()

            if (query_lower in title or query_lower in desc
                    or query_lower in edrpou or query_lower in entity_name):
                matched.append(t)
                if len(matched) >= limit:
                    break

        if not matched:
            return ToolResult(success=True, data={
                "answer": f"По запросу '{query}' тендеров не найдено (проверено последние 100).",
            })

        lines = [f"Найдено {len(matched)} тендеров по '{query}':\n"]
        for i, t in enumerate(matched, 1):
            lines.append(self._format_tender_short(i, t))

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(matched),
            "query": query,
        })

    async def _fetch_tender_details(self, feed_items: list[dict]) -> list[dict]:
        """Fetch full details for tenders from feed (which only contains IDs)."""
        tenders = []
        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            for item in feed_items:
                tid = item.get("id", "")
                if not tid:
                    continue
                try:
                    async with session.get(f"{BASE_URL}/tenders/{tid}") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            tenders.append(data.get("data", {}))
                except Exception:
                    continue
        return tenders

    @staticmethod
    def _format_tender_short(num: int, t: dict) -> str:
        """Format tender as one-liner."""
        title = t.get("title", "Без назви")[:120]
        status = t.get("status", "?")
        amount = t.get("value", {}).get("amount", "")
        currency = t.get("value", {}).get("currency", "UAH")
        entity = t.get("procuringEntity", {}).get("name", "?")[:50]
        edrpou = t.get("procuringEntity", {}).get("identifier", {}).get("id", "")
        tid = t.get("tenderID", t.get("id", "?"))

        price_str = f"{amount:,.0f} {currency}" if amount else "не вказано"
        edrpou_str = f" (ЄДРПОУ: {edrpou})" if edrpou else ""

        link = f"https://prozorro.gov.ua/tender/{tid}" if isinstance(tid, str) and tid.startswith("UA-") else ""
        link_line = f"   {link}\n" if link else ""

        return (
            f"{num}. {title}\n"
            f"   Статус: {status} | Сума: {price_str}\n"
            f"   Замовник: {entity}{edrpou_str}\n"
            f"   ID: {tid}\n"
            f"{link_line}"
        )

    @staticmethod
    def _format_tender_full(t: dict) -> str:
        """Format full tender details."""
        lines = []

        title = t.get("title", "Без назви")
        lines.append(f"Тендер: {title}")
        lines.append(f"ID: {t.get('tenderID', t.get('id', '?'))}")
        lines.append(f"Статус: {t.get('status', '?')}")

        # Value
        val = t.get("value", {})
        if val.get("amount"):
            lines.append(f"Сума: {val['amount']:,.0f} {val.get('currency', 'UAH')} (з ПДВ: {val.get('valueAddedTaxIncluded', '?')})")

        # Procuring entity
        pe = t.get("procuringEntity", {})
        if pe:
            name = pe.get("name", "?")
            edrpou = pe.get("identifier", {}).get("id", "")
            lines.append(f"Замовник: {name}")
            if edrpou:
                lines.append(f"ЄДРПОУ: {edrpou}")

        # Description
        desc = t.get("description", "")
        if desc:
            lines.append(f"Опис: {desc[:500]}")

        # Dates
        if t.get("tenderPeriod"):
            tp = t["tenderPeriod"]
            lines.append(f"Період подачі: {tp.get('startDate', '?')[:16]} — {tp.get('endDate', '?')[:16]}")

        if t.get("auctionPeriod"):
            ap = t["auctionPeriod"]
            lines.append(f"Аукціон: {ap.get('startDate', '?')[:16]}")

        # Items
        items = t.get("items", [])
        if items:
            lines.append(f"\nПозиції ({len(items)}):")
            for it in items[:10]:
                desc_item = it.get("description", "?")[:100]
                qty = it.get("quantity", "")
                unit = it.get("unit", {}).get("name", "")
                cpv = it.get("classification", {}).get("id", "")
                lines.append(f"  • {desc_item} — {qty} {unit} (CPV: {cpv})")

        # Link
        tid = t.get("tenderID", "")
        if tid:
            lines.append(f"\nhttps://prozorro.gov.ua/tender/{tid}")

        return "\n".join(lines)
