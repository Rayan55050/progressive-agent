"""
TechRadar monitor — curated GitHub/HN/Reddit discoveries for the agent owner.

Runs every 6 hours. Fetches trending repos, top HN/Reddit posts,
uses LLM to translate to Russian and analyze relevance for the agent.

Unlike NewsRadar (general news), TechRadar focuses on:
- GitHub trending repos with agent-relevance scoring
- HN top posts about AI/agents/tools
- Reddit posts from AI/crypto/trading subs

All content is translated to Russian with analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/tech_radar_state.json")
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = "ProgressiveAgent/1.0 (tech-radar)"

# Keywords for agent-relevance scoring
_AGENT_KEYWORDS = {
    "agent", "telegram-bot", "llm", "claude", "anthropic", "openai",
    "langchain", "llamaindex", "rag", "embedding", "vector", "mcp",
    "tool-use", "function-calling", "chatbot", "ai-assistant",
    "asyncio", "aiogram", "python-bot", "personal-assistant",
    "crewai", "autogpt", "memory", "prompt-engineering",
    "fine-tuning", "lora", "qlora", "inference", "ollama",
    "vllm", "tts", "stt", "whisper", "voice",
}

# Broader AI/tech keywords for HN/Reddit filtering
_TECH_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "gemini", "mistral", "openai",
    "anthropic", "machine learning", "deep learning", "neural",
    "transformer", "diffusion", "stable diffusion", "midjourney",
    "agent", "rag", "vector", "embedding", "python", "rust",
    "crypto", "bitcoin", "ethereum", "defi", "trading",
    "automation", "api", "open-source", "self-hosted",
}


@dataclass
class TechItem:
    """A single tech discovery."""

    title: str
    url: str
    source: str  # "github", "hackernews", "reddit"
    score: int = 0
    description: str = ""
    language: str = ""
    stars: int = 0
    topics: list[str] = field(default_factory=list)
    subreddit: str = ""
    comments: int = 0


class TechRadarMonitor:
    """Monitors GitHub/HN/Reddit for tech discoveries.

    Pushes curated, translated content to Telegram with agent-relevance analysis.
    """

    def __init__(
        self,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        llm_provider: Any,
        user_id: str = "",
    ) -> None:
        self._notify = notify
        self._llm = llm_provider
        self._user_id = user_id
        self._seen_urls: dict[str, None] = {}
        self._initialized = False
        self._consecutive_errors = 0
        self._load_state()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._seen_urls = dict.fromkeys(data.get("seen_urls", []))
                self._initialized = bool(self._seen_urls)
                if self._initialized:
                    logger.info(
                        "TechRadar state loaded: %d seen URLs", len(self._seen_urls)
                    )
        except Exception as e:
            logger.warning("Failed to load tech radar state: %s", e)

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            seen_list = list(self._seen_urls)
            if len(seen_list) > 3000:
                seen_list = seen_list[-3000:]
                self._seen_urls = dict.fromkeys(seen_list)
            data = {"seen_urls": seen_list, "updated_at": int(time.time())}
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save tech radar state: %s", e)

    # ------------------------------------------------------------------
    # Fetchers
    # ------------------------------------------------------------------

    async def _fetch_github_trending(
        self, session: aiohttp.ClientSession
    ) -> list[TechItem]:
        """GitHub API — repos created in last 7 days with 100+ stars."""
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {
            "q": f"created:>{week_ago} stars:>100",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        }
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        }
        try:
            async with session.get(
                "https://api.github.com/search/repositories",
                params=params,
                headers=headers,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    logger.warning("GitHub API HTTP %d", resp.status)
                    return []
                data = await resp.json()

            items = []
            for repo in data.get("items", [])[:20]:
                name = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                topics = repo.get("topics", [])
                url = repo.get("html_url", "")

                items.append(TechItem(
                    title=name,
                    url=url,
                    source="github",
                    score=repo.get("stargazers_count", 0),
                    description=desc[:300],
                    language=repo.get("language", "") or "",
                    stars=repo.get("stargazers_count", 0),
                    topics=topics[:10],
                ))
            return items
        except Exception as e:
            logger.warning("GitHub trending fetch failed: %s", e)
            return []

    async def _fetch_hackernews(
        self, session: aiohttp.ClientSession
    ) -> list[TechItem]:
        """HN Algolia — top AI/tech stories from last 12h."""
        cutoff = int(time.time()) - 43200  # 12 hours
        params = {
            "tags": "story",
            "numericFilters": f"created_at_i>{cutoff},points>50",
            "hitsPerPage": 20,
        }
        try:
            async with session.get(
                "https://hn.algolia.com/api/v1/search",
                params=params,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    logger.warning("HN Algolia HTTP %d", resp.status)
                    return []
                data = await resp.json()

            items = []
            for hit in data.get("hits", []):
                title = hit.get("title", "").lower()
                # Filter: must be AI/tech related
                if not any(kw in title for kw in _TECH_KEYWORDS):
                    continue
                story_url = hit.get("url") or (
                    f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
                )
                items.append(TechItem(
                    title=hit.get("title", ""),
                    url=story_url,
                    source="hackernews",
                    score=hit.get("points", 0) or 0,
                    comments=hit.get("num_comments", 0) or 0,
                ))
            return items
        except Exception as e:
            logger.warning("HN fetch failed: %s", e)
            return []

    async def _fetch_reddit(
        self, session: aiohttp.ClientSession
    ) -> list[TechItem]:
        """Reddit JSON — top posts from AI/crypto/trading subs."""
        subs = [
            ("LocalLLaMA+MachineLearning", "ai"),
            ("CryptoCurrency+Bitcoin", "crypto"),
        ]
        headers = {"User-Agent": _USER_AGENT}
        all_items: list[TechItem] = []

        for sub_name, _tag in subs:
            try:
                url = f"https://www.reddit.com/r/{sub_name}/top.json"
                params = {"t": "day", "limit": 10, "raw_json": 1}
                async with session.get(
                    url, params=params, headers=headers, timeout=_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Reddit %s HTTP %d", sub_name, resp.status)
                        continue
                    data = await resp.json()

                for child in data.get("data", {}).get("children", []):
                    p = child.get("data", {})
                    if p.get("stickied"):
                        continue
                    if p.get("score", 0) < 50:
                        continue
                    all_items.append(TechItem(
                        title=p.get("title", ""),
                        url=f"https://reddit.com{p.get('permalink', '')}",
                        source="reddit",
                        score=p.get("score", 0),
                        comments=p.get("num_comments", 0),
                        subreddit=p.get("subreddit", ""),
                        description=(p.get("selftext") or "")[:200],
                    ))
            except Exception as e:
                logger.warning("Reddit %s fetch failed: %s", sub_name, e)

        return all_items

    # ------------------------------------------------------------------
    # LLM analysis + formatting
    # ------------------------------------------------------------------

    async def _analyze_and_format(self, items: list[TechItem]) -> str | None:
        """Use LLM to translate, analyze, and format discoveries."""
        if not items:
            return None

        # Build sections
        github_lines = []
        hn_lines = []
        reddit_lines = []

        for item in items:
            agent_tags = self._check_agent_relevance(item)
            tag_str = f" [AGENT-RELEVANT: {', '.join(agent_tags)}]" if agent_tags else ""

            if item.source == "github":
                line = (
                    f"- {item.title} ⭐{item.stars} ({item.language}) — {item.url}\n"
                    f"  Description: {item.description}\n"
                    f"  Topics: {', '.join(item.topics[:6])}{tag_str}"
                )
                github_lines.append(line)
            elif item.source == "hackernews":
                line = f"- {item.title} (👍{item.score}, 💬{item.comments}) — {item.url}{tag_str}"
                hn_lines.append(line)
            elif item.source == "reddit":
                line = (
                    f"- [{item.subreddit}] {item.title} "
                    f"(👍{item.score}, 💬{item.comments}) — {item.url}{tag_str}"
                )
                reddit_lines.append(line)

        text_parts = []
        if github_lines:
            text_parts.append("GITHUB TRENDING:\n" + "\n".join(github_lines))
        if hn_lines:
            text_parts.append("HACKER NEWS:\n" + "\n".join(hn_lines))
        if reddit_lines:
            text_parts.append("REDDIT:\n" + "\n".join(reddit_lines))

        articles_text = "\n\n".join(text_parts)

        system_prompt = (
            "Ты — техно-скаут. Твоя задача: отфильтровать, перевести на русский "
            "и проанализировать tech-находки для владельца AI-агента.\n\n"
            "Контекст: у владельца есть AI-агент на Python (asyncio, aiogram, Claude API) "
            "с 60+ инструментами: крипто, браузер, файлы, CLI, память, мониторы.\n\n"
            "Для КАЖДОГО элемента (оставь только интересные, убери мусор):\n\n"
            "🔹 GitHub репо:\n"
            "⭐ *Название* (⭐stars, язык)\n"
            "Описание на русском, 1-2 предложения\n"
            "🤖 Полезно для агента: ДА/НЕТ + почему (1 предложение)\n"
            "[Ссылка](url)\n\n"
            "🔸 HN/Reddit:\n"
            "📰 *Заголовок на русском*\n"
            "О чём: 1-2 предложения\n"
            "[Ссылка](url)\n\n"
            "Правила:\n"
            "- Раздели на: 🐙 GITHUB, 📰 HACKER NEWS, 🔴 REDDIT\n"
            "- Убирай дубли и мелочёвку (score < 100 для HN/Reddit — подозрительно)\n"
            "- Для GitHub: обязательно отмечай что помечено [AGENT-RELEVANT]\n"
            "- Markdown formatting для Telegram (без HTML)\n"
            "- Если ничего интересного — ответь: SKIP\n"
            "- Лимит: 15 элементов макс\n"
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": articles_text.strip()}],
                system=system_prompt,
            )
            text = response.content.strip()
            if text == "SKIP" or not text:
                return None

            # Add header
            now = datetime.now(timezone.utc).strftime("%H:%M UTC")
            header = f"🔬 *Tech Radar* — {now}\n\n"
            return header + text

        except Exception as e:
            logger.error("TechRadar LLM analysis failed: %s", e)
            return None

    def _check_agent_relevance(self, item: TechItem) -> list[str]:
        """Check if item is relevant to our agent."""
        combined = (
            item.title + " " + item.description + " " + " ".join(item.topics)
        ).lower()
        return [kw for kw in _AGENT_KEYWORDS if kw in combined]

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    async def check(self) -> None:
        """Fetch, analyze, notify."""
        try:
            async with aiohttp.ClientSession() as session:
                results = await asyncio.gather(
                    self._fetch_github_trending(session),
                    self._fetch_hackernews(session),
                    self._fetch_reddit(session),
                    return_exceptions=True,
                )
        except Exception as e:
            self._consecutive_errors += 1
            logger.error("TechRadar fetch failed: %s", e)
            return

        self._consecutive_errors = 0

        # Flatten
        all_items: list[TechItem] = []
        for result in results:
            if isinstance(result, list):
                all_items.extend(result)
            elif isinstance(result, Exception):
                logger.warning("TechRadar source error: %s", result)

        # Dedup + filter seen
        new_items: list[TechItem] = []
        for item in all_items:
            if item.url and item.url not in self._seen_urls:
                new_items.append(item)

        if not new_items:
            logger.info("TechRadar: no new items")
            return

        # First run — baseline
        if not self._initialized:
            for item in new_items:
                self._seen_urls[item.url] = None
            self._initialized = True
            self._save_state()
            logger.info("TechRadar initialized: %d items baselined", len(new_items))
            return

        # Sort by score, take top items
        new_items.sort(key=lambda x: x.score, reverse=True)
        top_items = new_items[:25]

        # LLM analysis
        digest = await self._analyze_and_format(top_items)

        # Mark all as seen
        for item in new_items:
            self._seen_urls[item.url] = None
        self._save_state()

        if digest and self._user_id:
            if len(digest) <= 4000:
                await self._notify(self._user_id, digest)
            else:
                mid = len(digest) // 2
                split_pos = digest.rfind("\n\n", 0, mid + 500)
                if split_pos == -1:
                    split_pos = mid
                await self._notify(self._user_id, digest[:split_pos])
                await self._notify(self._user_id, digest[split_pos:].lstrip())
            logger.info(
                "TechRadar digest sent: %d items, %d chars",
                len(top_items),
                len(digest),
            )
        else:
            logger.info("TechRadar: nothing interesting or LLM filtered all")

    def get_status(self) -> dict[str, Any]:
        return {
            "seen_urls_count": len(self._seen_urls),
            "initialized": self._initialized,
            "consecutive_errors": self._consecutive_errors,
        }
