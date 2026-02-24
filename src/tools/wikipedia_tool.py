"""
Wikipedia tool — search articles, get summaries, facts.

100% FREE, no API key needed.
Uses Wikipedia REST API + Wikidata.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

WIKI_API = "https://{lang}.wikipedia.org/api/rest_v1"
WIKI_ACTION = "https://{lang}.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_HEADERS = {"User-Agent": "ProgressiveAgent/1.0 (Telegram bot; contact: progressive@agent.local)"}


class WikipediaTool:
    """Wikipedia and Wikidata: articles, summaries, facts, search."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="wikipedia",
            description=(
                "Wikipedia + Wikidata (free, no key). "
                "Actions: 'search' — find articles by query; "
                "'summary' — get article summary/extract; "
                "'full' — get full article text (first ~2000 chars); "
                "'wikidata' — structured facts from Wikidata about an entity. "
                "Supports multiple languages: 'en', 'ru', 'uk'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'search', 'summary', 'full', 'wikidata'",
                    required=True,
                    enum=["search", "summary", "full", "wikidata"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query or article title (e.g. 'Bitcoin', 'Ukraine', 'Claude AI')",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type="string",
                    description="Wikipedia language: 'en' (default), 'ru', 'uk', 'de', 'fr', etc.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "summary").strip().lower()
        query = kwargs.get("query", "").strip()
        lang = kwargs.get("lang", "en").strip().lower()

        if not query:
            return ToolResult(success=False, error="Query is required")

        try:
            if action == "search":
                return await self._search(query, lang)
            elif action == "summary":
                return await self._summary(query, lang)
            elif action == "full":
                return await self._full_article(query, lang)
            elif action == "wikidata":
                return await self._wikidata(query)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("Wikipedia error: %s", e)
            return ToolResult(success=False, error=f"Wikipedia error: {e}")

    async def _search(self, query: str, lang: str) -> ToolResult:
        url = WIKI_ACTION.format(lang=lang)
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": "10",
            "format": "json",
        }

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(url, params=params, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"Wikipedia HTTP {resp.status}")
                data = await resp.json()

        results = data.get("query", {}).get("search", [])
        if not results:
            return ToolResult(success=True, data=f"No Wikipedia articles found for '{query}'")

        lines = [f"**Wikipedia search '{query}' ({lang}):**\n"]
        for r in results:
            title = r.get("title", "?")
            snippet = r.get("snippet", "")
            # Strip HTML from snippet
            import re
            snippet = re.sub(r"<[^>]+>", "", snippet)[:120]
            lines.append(f"  **{title}**\n  {snippet}...")

        return ToolResult(success=True, data="\n".join(lines))

    async def _summary(self, query: str, lang: str) -> ToolResult:
        url = f"{WIKI_API.format(lang=lang)}/page/summary/{quote(query)}"

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status == 404:
                    return ToolResult(success=False, error=f"Article '{query}' not found on {lang}.wikipedia.org")
                if resp.status != 200:
                    raise ValueError(f"Wikipedia HTTP {resp.status}")
                data = await resp.json()

        title = data.get("title", "?")
        extract = data.get("extract", "No summary available.")
        description = data.get("description", "")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

        result = f"**{title}**"
        if description:
            result += f" — {description}"
        result += f"\n\n{extract}"
        if page_url:
            result += f"\n\n{page_url}"

        return ToolResult(success=True, data=result)

    async def _full_article(self, query: str, lang: str) -> ToolResult:
        url = WIKI_ACTION.format(lang=lang)
        params = {
            "action": "query",
            "titles": query,
            "prop": "extracts",
            "explaintext": "1",
            "exlimit": "1",
            "format": "json",
        }

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(url, params=params, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"Wikipedia HTTP {resp.status}")
                data = await resp.json()

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return ToolResult(success=False, error=f"Article '{query}' not found")

        page = next(iter(pages.values()))
        if page.get("pageid") is None or int(next(iter(pages.keys()))) < 0:
            return ToolResult(success=False, error=f"Article '{query}' not found")

        title = page.get("title", "?")
        extract = page.get("extract", "")

        # Truncate to ~2000 chars
        if len(extract) > 2000:
            extract = extract[:2000] + "\n\n... [truncated]"

        return ToolResult(success=True, data=f"**{title}**\n\n{extract}")

    async def _wikidata(self, query: str) -> ToolResult:
        # Search Wikidata for entity
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "limit": "1",
            "format": "json",
        }

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(WIKIDATA_API, params=params, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"Wikidata HTTP {resp.status}")
                data = await resp.json()

        results = data.get("search", [])
        if not results:
            return ToolResult(success=True, data=f"No Wikidata entity found for '{query}'")

        entity_id = results[0].get("id", "")
        label = results[0].get("label", "?")
        description = results[0].get("description", "")

        # Get entity details
        params2 = {
            "action": "wbgetentities",
            "ids": entity_id,
            "languages": "en|ru|uk",
            "props": "labels|descriptions|claims",
            "format": "json",
        }

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(WIKIDATA_API, params=params2, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"Wikidata HTTP {resp.status}")
                data = await resp.json()

        entity = data.get("entities", {}).get(entity_id, {})
        claims = entity.get("claims", {})

        # Extract key properties
        lines = [f"**{label}** ({entity_id})"]
        if description:
            lines.append(f"_{description}_\n")

        # Common property IDs
        prop_names = {
            "P31": "Instance of",
            "P17": "Country",
            "P571": "Inception",
            "P856": "Website",
            "P1082": "Population",
            "P36": "Capital",
            "P2044": "Elevation",
            "P625": "Coordinates",
            "P154": "Logo",
            "P18": "Image",
        }

        for prop_id, prop_label in prop_names.items():
            if prop_id in claims:
                claim = claims[prop_id]
                if claim:
                    value = self._extract_claim_value(claim[0])
                    if value:
                        lines.append(f"  {prop_label}: {value}")

        lines.append(f"\nhttps://www.wikidata.org/wiki/{entity_id}")

        return ToolResult(success=True, data="\n".join(lines))

    @staticmethod
    def _extract_claim_value(claim: dict) -> str | None:
        snak = claim.get("mainsnak", {})
        dv = snak.get("datavalue", {})
        if not dv:
            return None

        val_type = dv.get("type", "")
        value = dv.get("value", "")

        if val_type == "string":
            return str(value)
        elif val_type == "wikibase-entityid":
            return value.get("id", "?")
        elif val_type == "time":
            return value.get("time", "?").lstrip("+").split("T")[0]
        elif val_type == "quantity":
            amount = value.get("amount", "?")
            if isinstance(amount, str) and amount.startswith("+"):
                amount = amount[1:]
            return str(amount)
        elif val_type == "globecoordinate":
            lat = value.get("latitude", 0)
            lon = value.get("longitude", 0)
            return f"{lat:.4f}, {lon:.4f}"

        return str(value)[:100]
