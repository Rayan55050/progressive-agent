"""
data.gov.ua tool — Ukrainian open government data (CKAN API).

Free public API, no API key, no registration.
80,000+ datasets across economy, health, infrastructure, etc.
API docs: https://data.gov.ua/api/3/action/
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://data.gov.ua/api/3/action"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_HEADERS = {"User-Agent": "ProgressiveAgent/1.0"}


class DataGovTool:
    """Ukrainian open government data: datasets, organizations, resources."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="datagov",
            description=(
                "data.gov.ua — відкриті держдані України (free CKAN API, без ключа). "
                "80,000+ датасетів: економіка, здоров'я, інфраструктура, ЄДРПОУ, реєстри. "
                "Actions: 'search' — пошук датасетів по ключовому слову; "
                "'dataset' — деталі датасету по ID (з ресурсами/файлами); "
                "'organizations' — список організацій-постачальників даних; "
                "'recent' — нещодавно оновлені датасети. "
                "Використовуй коли питають: 'відкриті дані', 'держдані', 'реєстри', "
                "'data.gov.ua', 'ЄДРПОУ реєстр', 'статистика України'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'search', 'dataset', 'organizations', 'recent'",
                    required=True,
                    enum=["search", "dataset", "organizations", "recent"],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search keyword for 'search' action (e.g. 'ЄДРПОУ', 'бюджет', 'COVID')",
                    required=False,
                ),
                ToolParameter(
                    name="dataset_id",
                    type="string",
                    description="Dataset ID or name for 'dataset' action",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of results (default 10, max 50)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "search")
        limit = min(int(kwargs.get("limit", 10)), 50)

        try:
            if action == "search":
                query = kwargs.get("query", "")
                if not query:
                    return ToolResult(success=False, error="query is required for 'search' action")
                return await self._search(query, limit)
            elif action == "dataset":
                dataset_id = kwargs.get("dataset_id", "")
                if not dataset_id:
                    return ToolResult(success=False, error="dataset_id is required")
                return await self._get_dataset(dataset_id)
            elif action == "organizations":
                return await self._list_organizations(limit)
            elif action == "recent":
                return await self._recent_datasets(limit)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            logger.exception("data.gov.ua API error")
            return ToolResult(success=False, error=f"data.gov.ua API error: {e}")

    async def _search(self, query: str, limit: int) -> ToolResult:
        """Search datasets by keyword."""
        url = f"{BASE_URL}/package_search"
        params = {"q": query, "rows": limit}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        if not data.get("success"):
            return ToolResult(success=False, error="API returned error")

        results = data.get("result", {}).get("results", [])
        total = data.get("result", {}).get("count", 0)

        if not results:
            return ToolResult(success=True, data={
                "answer": f"По запиту '{query}' датасетів не знайдено.",
            })

        lines = [f"Знайдено {total} датасетів по '{query}' (показано {len(results)}):\n"]
        for i, ds in enumerate(results, 1):
            lines.append(self._format_dataset_short(i, ds))

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "total": total,
            "count": len(results),
            "query": query,
        })

    async def _get_dataset(self, dataset_id: str) -> ToolResult:
        """Get full dataset details with resources."""
        url = f"{BASE_URL}/package_show"
        params = {"id": dataset_id}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    if "Not Found" in text:
                        return ToolResult(success=False, error=f"Dataset not found: {dataset_id}")
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        if not data.get("success"):
            return ToolResult(success=False, error="Dataset not found")

        ds = data.get("result", {})
        return ToolResult(success=True, data={
            "answer": self._format_dataset_full(ds),
        })

    async def _list_organizations(self, limit: int) -> ToolResult:
        """List organizations that publish data."""
        url = f"{BASE_URL}/organization_list"
        params = {"all_fields": "true", "limit": limit, "sort": "package_count desc"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        if not data.get("success"):
            return ToolResult(success=False, error="API returned error")

        orgs = data.get("result", [])
        if not orgs:
            return ToolResult(success=True, data={"answer": "Організацій не знайдено."})

        lines = [f"Топ-{len(orgs)} організацій на data.gov.ua:\n"]
        for i, org in enumerate(orgs, 1):
            name = org.get("title") or org.get("display_name") or org.get("name", "?")
            count = org.get("package_count", 0)
            lines.append(f"{i}. {name} — {count} датасетів")

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(orgs),
        })

    async def _recent_datasets(self, limit: int) -> ToolResult:
        """Get recently updated datasets."""
        url = f"{BASE_URL}/package_search"
        params = {"rows": limit, "sort": "metadata_modified desc"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return ToolResult(success=False, error=f"HTTP {resp.status}")
                data = await resp.json()

        if not data.get("success"):
            return ToolResult(success=False, error="API returned error")

        results = data.get("result", {}).get("results", [])

        if not results:
            return ToolResult(success=True, data={"answer": "Нічого не знайдено."})

        lines = [f"Нещодавно оновлені датасети ({len(results)}):\n"]
        for i, ds in enumerate(results, 1):
            lines.append(self._format_dataset_short(i, ds))

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(results),
        })

    @staticmethod
    def _format_dataset_short(num: int, ds: dict) -> str:
        """Format dataset as short summary."""
        title = ds.get("title", "Без назви")[:120]
        org = ds.get("organization", {})
        org_name = org.get("title", "") if org else ""
        modified = ds.get("metadata_modified", "")[:10]
        num_resources = len(ds.get("resources", []))
        ds_id = ds.get("name") or ds.get("id", "?")

        org_str = f" | {org_name}" if org_name else ""
        return (
            f"{num}. {title}\n"
            f"   Оновлено: {modified}{org_str} | Ресурсів: {num_resources}\n"
            f"   ID: {ds_id}\n"
        )

    @staticmethod
    def _format_dataset_full(ds: dict) -> str:
        """Format full dataset details."""
        lines = []

        title = ds.get("title", "Без назви")
        lines.append(f"Датасет: {title}")
        lines.append(f"ID: {ds.get('name') or ds.get('id', '?')}")

        org = ds.get("organization", {})
        if org:
            lines.append(f"Організація: {org.get('title', '?')}")

        notes = ds.get("notes", "")
        if notes:
            lines.append(f"Опис: {notes[:500]}")

        modified = ds.get("metadata_modified", "")
        if modified:
            lines.append(f"Оновлено: {modified[:16]}")

        # Tags
        tags = ds.get("tags", [])
        if tags:
            tag_names = [t.get("display_name") or t.get("name", "") for t in tags[:10]]
            lines.append(f"Теги: {', '.join(tag_names)}")

        # Resources (files/APIs)
        resources = ds.get("resources", [])
        if resources:
            lines.append(f"\nРесурси ({len(resources)}):")
            for r in resources[:15]:
                name = r.get("name") or r.get("description", "Файл")
                fmt = r.get("format", "?").upper()
                url = r.get("url", "")
                size = r.get("size")
                size_str = f" ({_human_size(size)})" if size else ""
                lines.append(f"  • [{fmt}] {name[:80]}{size_str}")
                if url:
                    lines.append(f"    {url}")

        # Link
        ds_name = ds.get("name") or ds.get("id", "")
        if ds_name:
            lines.append(f"\nhttps://data.gov.ua/dataset/{ds_name}")

        return "\n".join(lines)


def _human_size(size: Any) -> str:
    """Convert bytes to human readable."""
    try:
        b = int(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"
