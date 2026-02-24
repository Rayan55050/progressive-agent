"""
Browser tools — Chrome control + Playwright page interaction.

browser_open: opens URL in user's Chrome (subprocess, fast, reliable)
browser_action: Playwright-based page interaction (click, fill, read, screenshot)
browser_history: read Chrome History SQLite
browser_bookmarks: read Chrome Bookmarks JSON
browser_close: close Playwright browser (not Chrome)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Chrome paths (Windows)
CHROME_USER_DATA_DIR = Path.home() / "AppData/Local/Google/Chrome/User Data"
CHROME_DEFAULT_PROFILE = CHROME_USER_DATA_DIR / "Default"
CHROME_HISTORY_DB = CHROME_DEFAULT_PROFILE / "History"
CHROME_BOOKMARKS_FILE = CHROME_DEFAULT_PROFILE / "Bookmarks"


def _find_chrome() -> str:
    """Find Chrome executable on Windows."""
    candidates = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _clean_url(raw: str) -> str:
    """Strip quotes and garbage from URL."""
    url = raw.strip()
    # Strip all quote types
    for ch in ['"', "'", '`', '\u201c', '\u201d', '\u2018', '\u2019', '\u00ab', '\u00bb']:
        url = url.strip(ch)
    url = url.replace("%22", "").replace("%27", "")
    # Extract URL if buried in garbage
    m = re.search(r'(https?://\S+)', url)
    if m:
        url = m.group(1).rstrip("\"'`>,;)}")
    return url.strip()


# -----------------------------------------------------------------------
# BrowserService — Chrome data (history, bookmarks)
# -----------------------------------------------------------------------

class BrowserService:
    """Chrome data access + chrome path."""

    def __init__(self) -> None:
        self.chrome_path = _find_chrome()

    @property
    def available(self) -> bool:
        return bool(self.chrome_path)

    async def open_url(
        self, url: str, incognito: bool = False, new_window: bool = False,
    ) -> dict[str, Any]:
        """Open URL in the user's Chrome. If Chrome is running, opens new tab."""
        if not self.chrome_path:
            return {"error": "Chrome not found"}

        url = _clean_url(url)
        if not url:
            return {"error": "Empty URL"}

        # Add scheme if missing
        if not url.startswith(("http://", "https://", "file://")):
            url = "https://" + url

        args = [self.chrome_path]
        if incognito:
            args.append("--incognito")
        if new_window:
            args.append("--new-window")
        args.append(url)

        logger.info("Opening in Chrome: %s (incognito=%s)", url, incognito)

        try:
            await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return {"url": url, "opened": True, "incognito": incognito}
        except Exception as e:
            return {"error": str(e)}

    def get_history(
        self, query: str = "", limit: int = 20, days: int = 1,
    ) -> list[dict[str, str]]:
        """Read Chrome browsing history (copies DB to avoid lock)."""
        if not CHROME_HISTORY_DB.exists():
            return []

        tmp = Path(tempfile.gettempdir()) / "chrome_history_copy.db"
        try:
            shutil.copy2(str(CHROME_HISTORY_DB), str(tmp))
        except PermissionError:
            logger.warning("Chrome History DB locked, trying direct read")
            tmp = CHROME_HISTORY_DB
        except Exception as e:
            logger.error("Failed to copy History DB: %s", e)
            return []

        results = []
        try:
            conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            chrome_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_chrome = int((cutoff - chrome_epoch).total_seconds() * 1_000_000)

            if query:
                sql = (
                    "SELECT url, title, last_visit_time, visit_count "
                    "FROM urls WHERE last_visit_time > ? "
                    "AND (title LIKE ? OR url LIKE ?) "
                    "ORDER BY last_visit_time DESC LIMIT ?"
                )
                like = f"%{query}%"
                rows = conn.execute(sql, (cutoff_chrome, like, like, limit)).fetchall()
            else:
                sql = (
                    "SELECT url, title, last_visit_time, visit_count "
                    "FROM urls WHERE last_visit_time > ? "
                    "ORDER BY last_visit_time DESC LIMIT ?"
                )
                rows = conn.execute(sql, (cutoff_chrome, limit)).fetchall()

            for row in rows:
                ts = chrome_epoch + timedelta(microseconds=row["last_visit_time"])
                results.append({
                    "url": row["url"],
                    "title": row["title"] or "(no title)",
                    "visited": ts.strftime("%Y-%m-%d %H:%M"),
                    "visits": str(row["visit_count"]),
                })
            conn.close()
        except Exception as e:
            logger.error("Failed to read Chrome history: %s", e)
        finally:
            if tmp != CHROME_HISTORY_DB:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        return results

    def get_bookmarks(self, query: str = "", limit: int = 30) -> list[dict[str, str]]:
        """Read Chrome bookmarks from JSON file."""
        if not CHROME_BOOKMARKS_FILE.exists():
            return []
        try:
            data = json.loads(CHROME_BOOKMARKS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to read bookmarks: %s", e)
            return []

        results: list[dict[str, str]] = []
        query_lower = query.lower() if query else ""

        def _walk(node: dict[str, Any], folder: str = "") -> None:
            if len(results) >= limit:
                return
            if node.get("type") == "url":
                name = node.get("name", "")
                url = node.get("url", "")
                if not query_lower or (
                    query_lower in name.lower() or query_lower in url.lower()
                ):
                    results.append({"name": name, "url": url, "folder": folder})
            elif node.get("type") == "folder":
                fname = node.get("name", "")
                path = f"{folder}/{fname}" if folder else fname
                for child in node.get("children", []):
                    _walk(child, path)

        for rname, rnode in data.get("roots", {}).items():
            if isinstance(rnode, dict):
                _walk(rnode, rname)
        return results


# -----------------------------------------------------------------------
# Playwright (lazy, only for browser_action)
# -----------------------------------------------------------------------

class _PlaywrightManager:
    """Lazy Playwright — only starts when browser_action is called."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()

    async def get_page(self) -> Any:
        async with self._lock:
            if self._page and not self._page.is_closed():
                return self._page

            if not self._pw:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()

            if self._ctx:
                try:
                    await self._ctx.close()
                except Exception:
                    pass

            # Use temp profile (Playwright-managed, separate from user's Chrome)
            tmp = Path(tempfile.gettempdir()) / "pw_browser"
            tmp.mkdir(exist_ok=True)
            self._ctx = await self._pw.chromium.launch_persistent_context(
                str(tmp),
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1920, "height": 1080},
                locale="uk-UA",
                timezone_id="Europe/Kyiv",
            )
            try:
                from playwright_stealth import stealth_async
                await stealth_async(self._ctx)
            except ImportError:
                pass

            self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            return self._page

    async def close(self) -> None:
        async with self._lock:
            self._page = None
            if self._ctx:
                try:
                    await self._ctx.close()
                except Exception:
                    pass
                self._ctx = None
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None


# Module-level singleton
_pw_manager = _PlaywrightManager()


# -----------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------

class BrowserOpenTool:
    """Open URL in user's Chrome — fast, simple, no Playwright."""

    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser_open",
            description=(
                "Open URL in Chrome browser. Opens in existing Chrome if running. "
                "Supports incognito mode and new window. "
                "For page interaction (click, fill, read content) use browser_action."
            ),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description=(
                        "URL to open: youtube.com, https://github.com, etc. "
                        "Or search query like 'python tutorial' (opens Google search)."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="incognito",
                    type="boolean",
                    description="Open in incognito mode (default false).",
                    required=False,
                    default="false",
                ),
                ToolParameter(
                    name="new_window",
                    type="boolean",
                    description="Open in new window instead of new tab (default false).",
                    required=False,
                    default="false",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = _clean_url(kwargs.get("url", ""))
        incognito = str(kwargs.get("incognito", "false")).lower() in ("true", "1", "yes")
        new_window = str(kwargs.get("new_window", "false")).lower() in ("true", "1", "yes")

        if not url:
            return ToolResult(success=False, error="url is required")

        # Search query → Google
        if " " in url and "." not in url:
            url = f"https://www.google.com/search?q={url.replace(' ', '+')}"

        result = await self._service.open_url(url, incognito=incognito, new_window=new_window)
        if "error" in result:
            return ToolResult(success=False, error=result["error"])
        return ToolResult(success=True, data=result)


class BrowserActionTool:
    """Interact with a page via Playwright (navigate, click, fill, read, screenshot)."""

    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser_action",
            description=(
                "Interact with a web page using Playwright browser. "
                "Actions: navigate (go to URL and read content), click, fill, type, "
                "select, press, scroll, screenshot, eval_js, wait. "
                "Opens a separate Playwright browser (not user's Chrome)."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description=(
                        "Action: navigate (open URL + return markdown content), "
                        "click, fill, type, select, press (key), "
                        "scroll (up/down), screenshot, eval_js, wait."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="selector",
                    type="string",
                    description="CSS selector for target element.",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="value",
                    type="string",
                    description=(
                        "URL for navigate, text for fill/type, key for press, "
                        "up/down for scroll, JS for eval_js, seconds for wait."
                    ),
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        selector = kwargs.get("selector", "").strip()
        value = kwargs.get("value", "").strip()

        if not action:
            return ToolResult(success=False, error="action is required")

        try:
            page = await _pw_manager.get_page()

            if action == "navigate":
                url = _clean_url(value)
                if not url:
                    return ToolResult(success=False, error="value (URL) required for navigate")
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url

                resp = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                title = await page.title()
                content = await page.inner_text("body")
                if len(content) > 15000:
                    content = content[:15000] + "\n...(truncated)"
                return ToolResult(success=True, data={
                    "url": page.url,
                    "title": title,
                    "status": resp.status if resp else 0,
                    "content": content,
                })

            elif action == "click":
                if not selector:
                    return ToolResult(success=False, error="selector required for click")
                await page.click(selector, timeout=10000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                return ToolResult(success=True, data={"action": "click", "selector": selector})

            elif action == "fill":
                if not selector:
                    return ToolResult(success=False, error="selector required for fill")
                await page.fill(selector, value, timeout=10000)
                return ToolResult(success=True, data={"action": "fill", "selector": selector})

            elif action == "type":
                if not value:
                    return ToolResult(success=False, error="value required for type")
                if selector:
                    await page.click(selector, timeout=10000)
                await page.keyboard.type(value, delay=50)
                return ToolResult(success=True, data={"action": "type"})

            elif action == "select":
                if not selector:
                    return ToolResult(success=False, error="selector required for select")
                await page.select_option(selector, value, timeout=10000)
                return ToolResult(success=True, data={"action": "select"})

            elif action == "press":
                key = value or "Enter"
                if selector:
                    await page.press(selector, key, timeout=10000)
                else:
                    await page.keyboard.press(key)
                return ToolResult(success=True, data={"action": "press", "key": key})

            elif action == "scroll":
                delta = 500 if value.lower() != "up" else -500
                await page.mouse.wheel(0, delta)
                await asyncio.sleep(0.3)
                return ToolResult(success=True, data={"action": "scroll", "direction": value or "down"})

            elif action == "screenshot":
                data = await page.screenshot(type="png")
                b64 = base64.b64encode(data).decode("ascii")
                return ToolResult(success=True, data={
                    "action": "screenshot",
                    "base64_length": len(b64),
                    "screenshot_base64": b64,
                })

            elif action == "eval_js":
                if not value:
                    return ToolResult(success=False, error="JS code required")

                # Security: Only allow eval_js on localhost or whitelisted domains
                current_url = page.url
                from urllib.parse import urlparse
                parsed = urlparse(current_url)
                hostname = parsed.hostname or ""

                # Whitelist: localhost, 127.0.0.1, and explicitly safe domains
                allowed_hosts = {
                    "localhost", "127.0.0.1", "::1",
                    # Add more whitelisted domains here if needed
                }

                if hostname not in allowed_hosts:
                    logger.warning(
                        "eval_js blocked for security: current_url=%s, hostname=%s",
                        current_url, hostname
                    )
                    return ToolResult(
                        success=False,
                        error=(
                            f"Security: eval_js is restricted to localhost only. "
                            f"Current domain: {hostname} (not whitelisted)"
                        )
                    )

                result = await page.evaluate(value)
                return ToolResult(success=True, data={
                    "action": "eval_js",
                    "result": str(result)[:5000],
                })

            elif action == "wait":
                if selector:
                    await page.wait_for_selector(selector, timeout=int(value or "10000"))
                else:
                    await asyncio.sleep(float(value or "2"))
                return ToolResult(success=True, data={"action": "wait"})

            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")

        except Exception as e:
            logger.error("browser_action failed: %s", e)
            return ToolResult(success=False, error=str(e))


class BrowserHistoryTool:
    """Read Chrome browsing history."""

    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser_history",
            description="Read Chrome browsing history. Filter by query and days.",
            parameters=[
                ToolParameter(name="query", type="string",
                              description="Search by title or URL. Empty = all recent.",
                              required=False, default=""),
                ToolParameter(name="days", type="integer",
                              description="Days back (default 1).",
                              required=False, default="1"),
                ToolParameter(name="limit", type="integer",
                              description="Max results (default 20).",
                              required=False, default="20"),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        days = max(1, int(kwargs.get("days", 1)))
        limit = min(100, max(1, int(kwargs.get("limit", 20))))

        results = await asyncio.to_thread(
            self._service.get_history, query=query, limit=limit, days=days
        )
        if not results:
            return ToolResult(success=True, data="No history found.")

        lines = []
        for i, item in enumerate(results, 1):
            lines.append(
                f"{i}. {item['title']}\n"
                f"   {item['url']}\n"
                f"   Visited: {item['visited']} ({item['visits']} times)"
            )
        return ToolResult(success=True, data="\n\n".join(lines))


class BrowserBookmarksTool:
    """Search Chrome bookmarks."""

    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser_bookmarks",
            description="Search or list Chrome bookmarks.",
            parameters=[
                ToolParameter(name="query", type="string",
                              description="Search by name or URL. Empty = list all.",
                              required=False, default=""),
                ToolParameter(name="limit", type="integer",
                              description="Max results (default 30).",
                              required=False, default="30"),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        limit = int(kwargs.get("limit", 30))

        results = await asyncio.to_thread(
            self._service.get_bookmarks, query=query, limit=limit
        )
        if not results:
            return ToolResult(success=True, data="No bookmarks found." if query else "Bookmarks empty.")

        lines = []
        for i, item in enumerate(results, 1):
            folder = f" [{item['folder']}]" if item["folder"] else ""
            lines.append(f"{i}. {item['name']}{folder}\n   {item['url']}")
        return ToolResult(success=True, data="\n\n".join(lines))


class BrowserCloseTool:
    """Close the Playwright browser (not user's Chrome)."""

    def __init__(self, service: BrowserService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="browser_close",
            description="Close the Playwright browser. Does NOT close user's Chrome.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            await _pw_manager.close()
            return ToolResult(success=True, data="Playwright browser closed.")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
