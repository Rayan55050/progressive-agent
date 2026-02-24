"""
Manual test: fetch news, filter via LLM, send to Telegram.

Usage:
    python scripts/test_news_radar.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Ensure project root in path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.core.config import load_config
from src.core.llm import create_provider
from src.monitors.news_radar_monitor import NewsRadarMonitor


async def main():
    config = load_config()

    # Use API key directly to avoid proxy auth issues
    api_key = config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        provider = create_provider(
            proxy_url=None,
            api_key=api_key,
            model="claude-sonnet-4-5-20250929",  # cheaper for filtering
            max_tokens=2048,
        )
    else:
        provider = create_provider(
            proxy_url=config.claude_proxy_url,
            api_key=None,
            model=config.agent.default_model,
            max_tokens=config.agent.max_tokens,
        )
    print(f"LLM provider: {provider.name}")

    # Telegram send function
    from aiogram import Bot
    bot = Bot(token=config.telegram_bot_token)
    user_id = str(config.telegram.allowed_users[0])

    async def notify(uid: str, text: str) -> None:
        try:
            await bot.send_message(
                chat_id=int(uid),
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            # Markdown parse error — retry as plain text
            await bot.send_message(
                chat_id=int(uid),
                text=text,
                disable_web_page_preview=True,
            )
        print(f"Sent to Telegram: {len(text)} chars")

    # Build config
    news_cfg = {
        "crypto_enabled": config.news_radar.crypto_enabled,
        "ai_enabled": config.news_radar.ai_enabled,
        "world_enabled": config.news_radar.world_enabled,
        "cointelegraph_rss": config.news_radar.cointelegraph_rss,
        "coindesk_rss": config.news_radar.coindesk_rss,
        "reddit_crypto_rss": config.news_radar.reddit_crypto_rss,
        "hackernews_enabled": config.news_radar.hackernews_enabled,
        "huggingface_papers": config.news_radar.huggingface_papers,
        "reddit_ai_rss": config.news_radar.reddit_ai_rss,
        "github_trending": config.news_radar.github_trending,
        "google_news_topics": config.news_radar.google_news_topics,
        "reddit_worldnews_rss": config.news_radar.reddit_worldnews_rss,
        "max_articles_per_source": config.news_radar.max_articles_per_source,
        "max_articles_total": 45,  # more room for 3 channels
        "max_seen_urls": config.news_radar.max_seen_urls,
    }

    monitor = NewsRadarMonitor(
        notify=notify,
        llm_provider=provider,
        user_id=user_id,
        config=news_cfg,
    )

    # Force skip baseline (we want results NOW)
    monitor._initialized = True

    print("Fetching news from all sources...")
    articles = await monitor._fetch_all()
    print(f"Found {len(articles)} new articles")

    # Show what we got per channel
    channels: dict[str, list] = {}
    for a in articles:
        channels.setdefault(a.channel, []).append(a)

    for ch, arts in sorted(channels.items()):
        print(f"\n  {ch.upper()}: {len(arts)} articles")
        for a in arts[:3]:
            print(f"    - {a.title[:80]} ({a.source})")

    if not articles:
        print("\nNo new articles found!")
        await bot.session.close()
        return

    print(f"\nFiltering {len(articles)} articles via LLM...")
    digest = await monitor._filter_and_format(articles)

    if digest:
        print(f"\nDigest ready ({len(digest)} chars), sending to Telegram...")
        await notify(user_id, digest)
        print("Done!")
    else:
        print("\nLLM filtered everything out (nothing important)")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
