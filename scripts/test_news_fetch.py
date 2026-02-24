"""Quick debug: test each news source individually."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import aiohttp
from src.monitors.news_radar_monitor import NewsRadarMonitor


async def main():
    # Dummy monitor (no LLM, no notify)
    monitor = NewsRadarMonitor(
        notify=lambda *a: None,
        llm_provider=None,
        user_id="",
        config={
            "world_enabled": True,
            "google_news_topics": ["Trump", "Ukraine war"],
            "reddit_worldnews_rss": True,
            "max_articles_per_source": 5,
        },
    )
    monitor._initialized = True

    async with aiohttp.ClientSession() as session:
        # Test Google News Trump
        print("=== Google News: Trump ===")
        arts = await monitor._fetch_google_news(session, "Trump", "google_trump", "world")
        print(f"  {len(arts)} articles")
        for a in arts[:3]:
            print(f"  - {a.title[:90]}")
            print(f"    {a.url[:100]}")

        # Test Google News Ukraine
        print("\n=== Google News: Ukraine war ===")
        arts = await monitor._fetch_google_news(session, "Ukraine war", "google_ukraine", "world")
        print(f"  {len(arts)} articles")
        for a in arts[:3]:
            print(f"  - {a.title[:90]}")
            print(f"    {a.url[:100]}")

        # Test Reddit worldnews
        print("\n=== Reddit r/worldnews ===")
        arts = await monitor._fetch_rss(
            session,
            "https://www.reddit.com/r/worldnews/top/.rss?t=day",
            "reddit_worldnews",
            "world",
        )
        print(f"  {len(arts)} articles")
        for a in arts[:3]:
            print(f"  - {a.title[:90]}")

        # Test full fetch
        print("\n=== Full fetch (all sources) ===")
        all_arts = await monitor._fetch_all()
        channels = {}
        for a in all_arts:
            channels.setdefault(a.channel, []).append(a)
        for ch, ch_arts in sorted(channels.items()):
            print(f"  {ch}: {len(ch_arts)} articles")


if __name__ == "__main__":
    asyncio.run(main())
