"""
NewsRadar monitor — crypto + AI/tech + world news digest every N hours.

Fetches from multiple sources in parallel, deduplicates,
uses LLM to filter by importance, pushes digest to Telegram.

Sources:
  Ukraine: Ukrainska Pravda, Ekonomichna Pravda, Evropeyska Pravda (RSS)
  Crypto: CoinTelegraph RSS, CoinDesk RSS, Reddit crypto
  AI/Tech: Hacker News Algolia, HuggingFace Daily Papers, Reddit AI, GitHub Trending
  World:  Google News (custom topics), Reddit worldnews
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/news_radar_state.json")

# Timeouts for individual source fetches
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = "ProgressiveAgent/1.0 (news-monitor)"


@dataclass
class NewsArticle:
    """A single news article from any source."""

    title: str
    url: str
    source: str  # "cointelegraph", "coindesk", "hackernews", etc.
    channel: str  # "crypto" or "ai"
    published: str = ""  # ISO datetime or raw string
    score: int = 0  # upvotes/points if available
    summary: str = ""  # short snippet


class NewsRadarMonitor:
    """Monitors crypto + AI/tech news and pushes digests to Telegram.

    Runs as a scheduled job via APScheduler (default: every 4 hours).
    Fetches from multiple sources in parallel, deduplicates by URL,
    uses LLM to filter importance and format the digest.

    State (seen URLs) persisted to disk to avoid re-notifying.
    """

    def __init__(
        self,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        llm_provider: Any,
        user_id: str = "",
        config: dict[str, Any] | None = None,
    ) -> None:
        self._notify = notify
        self._llm = llm_provider
        self._user_id = user_id
        self._cfg = config or {}
        self._seen_urls: dict[str, None] = {}  # ordered set (preserves insertion order)
        self._initialized = False
        self._consecutive_errors = 0
        self._max_seen = self._cfg.get("max_seen_urls", 5000)
        self._max_per_source = self._cfg.get("max_articles_per_source", 10)
        self._max_total = self._cfg.get("max_articles_total", 30)
        self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._seen_urls = dict.fromkeys(data.get("seen_urls", []))
                self._initialized = bool(self._seen_urls)
                if self._initialized:
                    logger.info(
                        "NewsRadar state loaded: %d seen URLs", len(self._seen_urls)
                    )
        except Exception as e:
            logger.warning("Failed to load news radar state: %s", e)

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            seen_list = list(self._seen_urls)
            if len(seen_list) > self._max_seen:
                seen_list = seen_list[-self._max_seen :]
                self._seen_urls = dict.fromkeys(seen_list)
            data = {"seen_urls": seen_list, "updated_at": int(time.time())}
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save news radar state: %s", e)

    # ------------------------------------------------------------------
    # Source fetchers — each returns list[NewsArticle], never raises
    # ------------------------------------------------------------------

    async def _fetch_rss(
        self,
        session: aiohttp.ClientSession,
        rss_url: str,
        source_name: str,
        channel: str,
    ) -> list[NewsArticle]:
        """Generic RSS fetcher using feedparser."""
        import feedparser

        try:
            headers = {"User-Agent": _USER_AGENT}
            async with session.get(
                rss_url, headers=headers, timeout=_FETCH_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    logger.warning("%s RSS HTTP %d", source_name, resp.status)
                    return []
                text = await resp.text()
            feed = feedparser.parse(text)
            articles = []
            for entry in feed.entries[: self._max_per_source]:
                articles.append(
                    NewsArticle(
                        title=entry.get("title", ""),
                        url=entry.get("link", ""),
                        source=source_name,
                        channel=channel,
                        published=getattr(entry, "published", ""),
                        summary=entry.get("summary", "")[:200],
                    )
                )
            return articles
        except Exception as e:
            logger.warning("%s RSS fetch failed: %s", source_name, e)
            return []

    async def _fetch_hackernews(
        self, session: aiohttp.ClientSession
    ) -> list[NewsArticle]:
        """HN Algolia — AI-related stories from last 24h."""
        url = "https://hn.algolia.com/api/v1/search"
        params = {
            "query": "AI OR LLM OR GPT OR Claude OR machine learning OR neural network",
            "tags": "story",
            "numericFilters": f"created_at_i>{int(time.time()) - 86400}",
            "hitsPerPage": self._max_per_source,
        }
        try:
            async with session.get(url, params=params, timeout=_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning("HN Algolia HTTP %d", resp.status)
                    return []
                data = await resp.json()
            articles = []
            for hit in data.get("hits", []):
                hn_url = hit.get("url") or (
                    f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
                )
                articles.append(
                    NewsArticle(
                        title=hit.get("title", ""),
                        url=hn_url,
                        source="hackernews",
                        channel="ai",
                        published=hit.get("created_at", ""),
                        score=hit.get("points", 0) or 0,
                    )
                )
            return articles
        except Exception as e:
            logger.warning("HN Algolia fetch failed: %s", e)
            return []

    async def _fetch_huggingface(
        self, session: aiohttp.ClientSession
    ) -> list[NewsArticle]:
        """HuggingFace Daily Papers — curated AI research."""
        url = "https://huggingface.co/api/daily_papers"
        try:
            async with session.get(url, timeout=_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning("HuggingFace papers HTTP %d", resp.status)
                    return []
                data = await resp.json()
            articles = []
            for paper in data[: self._max_per_source]:
                paper_info = paper.get("paper", {})
                paper_id = paper_info.get("id", "")
                articles.append(
                    NewsArticle(
                        title=paper_info.get("title", ""),
                        url=f"https://huggingface.co/papers/{paper_id}" if paper_id else "",
                        source="huggingface",
                        channel="ai",
                        published=paper_info.get("publishedAt", ""),
                        score=paper.get("numUpvotes", 0) or 0,
                        summary=paper_info.get("summary", "")[:200],
                    )
                )
            return articles
        except Exception as e:
            logger.warning("HuggingFace papers fetch failed: %s", e)
            return []

    async def _fetch_google_news(
        self,
        session: aiohttp.ClientSession,
        query: str,
        source_name: str,
        channel: str,
    ) -> list[NewsArticle]:
        """Google News RSS — search for a topic, return top articles."""
        import feedparser
        from urllib.parse import quote

        url = (
            f"https://news.google.com/rss/search?"
            f"q={quote(query)}&hl=ru&gl=UA&ceid=UA:ru"
        )
        try:
            headers = {"User-Agent": _USER_AGENT}
            async with session.get(url, headers=headers, timeout=_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning("%s Google News HTTP %d", source_name, resp.status)
                    return []
                text = await resp.text()
            feed = feedparser.parse(text)
            articles = []
            for entry in feed.entries[: self._max_per_source]:
                articles.append(
                    NewsArticle(
                        title=entry.get("title", ""),
                        url=entry.get("link", ""),
                        source=source_name,
                        channel=channel,
                        published=getattr(entry, "published", ""),
                        summary=entry.get("summary", "")[:200],
                    )
                )
            return articles
        except Exception as e:
            logger.warning("%s Google News fetch failed: %s", source_name, e)
            return []

    async def _fetch_github_trending(
        self, session: aiohttp.ClientSession
    ) -> list[NewsArticle]:
        """GitHub Trending — scrape daily trending repos, filter AI-related."""
        from bs4 import BeautifulSoup

        url = "https://github.com/trending?since=daily"
        try:
            headers = {"User-Agent": _USER_AGENT}
            async with session.get(url, headers=headers, timeout=_FETCH_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning("GitHub trending HTTP %d", resp.status)
                    return []
                html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            ai_keywords = {
                "ai", "llm", "gpt", "machine-learning", "ml", "neural",
                "transformer", "diffusion", "agent", "rag", "embedding",
                "model", "nlp", "deep-learning", "anthropic", "openai",
                "langchain", "llamaindex", "huggingface", "mistral", "gemma",
            }
            articles = []
            rows = soup.select("article.Box-row")
            if not rows:
                # GitHub may have changed HTML structure — try alternative selector
                rows = soup.select("[class*='Box-row']")
                if not rows:
                    logger.warning(
                        "GitHub Trending: no rows found with any selector. "
                        "HTML structure may have changed."
                    )
                    return []
            for row in rows:
                h2 = row.select_one("h2 a")
                if not h2:
                    continue
                repo_path = h2.get("href", "").strip()
                repo_name = repo_path.lstrip("/")
                desc_p = row.select_one("p")
                desc = desc_p.get_text(strip=True) if desc_p else ""
                combined = (repo_name + " " + desc).lower()
                if not any(kw in combined for kw in ai_keywords):
                    continue
                articles.append(
                    NewsArticle(
                        title=repo_name,
                        url=f"https://github.com{repo_path}",
                        source="github_trending",
                        channel="ai",
                        published=datetime.now(timezone.utc).isoformat(),
                        summary=desc[:200],
                    )
                )
                if len(articles) >= self._max_per_source:
                    break
            return articles
        except Exception as e:
            logger.warning("GitHub trending fetch failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Parallel fetch + dedup
    # ------------------------------------------------------------------

    async def _fetch_all(self) -> list[NewsArticle]:
        """Fetch from all enabled sources in parallel, deduplicate."""
        cfg = self._cfg
        tasks: list[Any] = []

        async with aiohttp.ClientSession() as session:
            # Crypto sources
            if cfg.get("crypto_enabled", True):
                if cfg.get("cointelegraph_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://cointelegraph.com/rss",
                            "cointelegraph",
                            "crypto",
                        )
                    )
                if cfg.get("coindesk_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.coindesk.com/arc/outboundfeeds/rss/",
                            "coindesk",
                            "crypto",
                        )
                    )
                if cfg.get("reddit_crypto_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.reddit.com/r/CryptoCurrency+Bitcoin/top/.rss?t=day",
                            "reddit_crypto",
                            "crypto",
                        )
                    )

            # AI sources
            if cfg.get("ai_enabled", True):
                if cfg.get("hackernews_enabled", True):
                    tasks.append(self._fetch_hackernews(session))
                if cfg.get("huggingface_papers", True):
                    tasks.append(self._fetch_huggingface(session))
                if cfg.get("reddit_ai_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.reddit.com/r/LocalLLaMA+MachineLearning/top/.rss?t=day",
                            "reddit_ai",
                            "ai",
                        )
                    )
                if cfg.get("github_trending", True):
                    tasks.append(self._fetch_github_trending(session))

            # World / general news sources
            if cfg.get("world_enabled", True):
                # Google News RSS for custom topics
                topics = cfg.get("google_news_topics", ["Trump", "Ukraine"])
                for topic in topics:
                    safe_name = f"google_{topic.lower().replace(' ', '_')}"
                    tasks.append(
                        self._fetch_google_news(
                            session, topic, safe_name, "world"
                        )
                    )
                if cfg.get("reddit_worldnews_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.reddit.com/r/worldnews/top/.rss?t=day",
                            "reddit_worldnews",
                            "world",
                        )
                    )

            # Ukraine news (Ukr Pravda RSS feeds)
            if cfg.get("ukraine_enabled", True):
                if cfg.get("pravda_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.pravda.com.ua/rss/view_news/",
                            "ukr_pravda",
                            "ukraine",
                        )
                    )
                if cfg.get("epravda_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.epravda.com.ua/rss/view_news/",
                            "ekonom_pravda",
                            "ukraine",
                        )
                    )
                if cfg.get("europravda_rss", True):
                    tasks.append(
                        self._fetch_rss(
                            session,
                            "https://www.eurointegration.com.ua/rss/view_news/",
                            "euro_pravda",
                            "ukraine",
                        )
                    )

            if not tasks:
                return []

            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten + filter errors
        all_articles: list[NewsArticle] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Source fetch exception: %s", result)
                continue
            if isinstance(result, list):
                all_articles.extend(result)

        # Dedup by URL within batch
        seen_in_batch: set[str] = set()
        deduped: list[NewsArticle] = []
        for article in all_articles:
            if article.url and article.url not in seen_in_batch:
                seen_in_batch.add(article.url)
                deduped.append(article)

        # Filter out already-seen URLs
        new_articles = [a for a in deduped if a.url not in self._seen_urls]

        # Take top articles per channel (balanced), then fill with rest
        per_channel: dict[str, list[NewsArticle]] = {}
        for a in new_articles:
            per_channel.setdefault(a.channel, []).append(a)

        # Sort each channel by score
        for ch_articles in per_channel.values():
            ch_articles.sort(key=lambda a: a.score, reverse=True)

        # Balanced selection: up to max_total / num_channels per channel, then fill
        num_channels = max(len(per_channel), 1)
        per_ch_limit = max(self._max_total // num_channels, 5)
        result: list[NewsArticle] = []
        overflow: list[NewsArticle] = []
        for ch_articles in per_channel.values():
            result.extend(ch_articles[:per_ch_limit])
            overflow.extend(ch_articles[per_ch_limit:])

        # Fill remaining slots with overflow (sorted by score)
        remaining = self._max_total - len(result)
        if remaining > 0:
            overflow.sort(key=lambda a: a.score, reverse=True)
            result.extend(overflow[:remaining])

        return result

    # ------------------------------------------------------------------
    # LLM filtering + formatting
    # ------------------------------------------------------------------

    async def _filter_and_format(self, articles: list[NewsArticle]) -> str | None:
        """Use LLM to filter important articles and format digest.

        Returns formatted Telegram message or None if nothing important.
        """
        if not articles:
            return None

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Build article list for LLM — include URLs
        crypto_lines = []
        ai_lines = []
        world_lines = []
        ukraine_lines = []
        for a in articles:
            line = f"- {a.title} ({a.source}) — {a.url}"
            if a.score > 0:
                line += f" [score: {a.score}]"
            if a.summary:
                line += f"\n  {a.summary[:150]}"
            if a.channel == "crypto":
                crypto_lines.append(line)
            elif a.channel == "world":
                world_lines.append(line)
            elif a.channel == "ukraine":
                ukraine_lines.append(line)
            else:
                ai_lines.append(line)

        articles_text = ""
        if ukraine_lines:
            articles_text += "UKRAINE NEWS:\n" + "\n".join(ukraine_lines) + "\n\n"
        if world_lines:
            articles_text += "WORLD NEWS:\n" + "\n".join(world_lines) + "\n\n"
        if crypto_lines:
            articles_text += "CRYPTO NEWS:\n" + "\n".join(crypto_lines) + "\n\n"
        if ai_lines:
            articles_text += "AI/TECH NEWS:\n" + "\n".join(ai_lines) + "\n\n"

        system_prompt = (
            f"Сейчас: {now}.\n"
            "Отфильтруй только ВАЖНОЕ из списка новостей. Убери мелочёвку, дубли, кликбейт.\n\n"
            "Формат каждой новости:\n"
            "🔥 *Заголовок*\n"
            "Краткое описание 1-2 предложения с инлайн [ссылкой](url) из данных.\n\n"
            "Правила:\n"
            "- Раздели на секции: 🌍 МИР, 🪙 КРИПТО и 🤖 AI/TECH (только те где есть новости)\n"
            "- Эмодзи-маркер (🔥📌🚀💰🤖) + *bold заголовок*\n"
            "- Ссылка ВНУТРИ текста как [текст](url), НЕ отдельным списком\n"
            "- Язык: русский\n"
            "- Если ничего важного — ответь: SKIP\n"
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": articles_text.strip()}],
                system=system_prompt,
            )
            text = response.content.strip()
            if text == "SKIP" or not text:
                return None
            return text
        except Exception as e:
            logger.error("NewsRadar LLM filtering failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Main check (called by scheduler)
    # ------------------------------------------------------------------

    async def check(self) -> None:
        """Fetch news, filter via LLM, notify if important."""
        try:
            articles = await self._fetch_all()
        except Exception as e:
            self._consecutive_errors += 1
            logger.error("NewsRadar fetch failed: %s", e)
            if self._consecutive_errors >= 3:
                logger.error(
                    "NewsRadar: %d consecutive failures", self._consecutive_errors
                )
            return

        self._consecutive_errors = 0

        if not articles:
            logger.info("NewsRadar: no new articles found")
            return

        # First run — baseline, don't notify
        if not self._initialized:
            for a in articles:
                self._seen_urls[a.url] = None
            self._initialized = True
            self._save_state()
            logger.info("NewsRadar initialized: %d articles baselined", len(articles))
            return

        # Filter + format via LLM
        digest = await self._filter_and_format(articles)

        # Mark all as seen (even if LLM filtered them out)
        for a in articles:
            self._seen_urls[a.url] = None
        self._save_state()

        if digest and self._user_id:
            # Split if too long for Telegram (4096 limit)
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
                "NewsRadar digest sent: %d articles processed, %d chars",
                len(articles),
                len(digest),
            )
        else:
            logger.info("NewsRadar: LLM filtered everything (nothing important)")

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "seen_urls_count": len(self._seen_urls),
            "initialized": self._initialized,
            "consecutive_errors": self._consecutive_errors,
        }
