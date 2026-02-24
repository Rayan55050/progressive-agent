"""
Configuration loader for Progressive Agent.

Loads TOML config from config/agent.toml and secrets from .env.
Uses Pydantic BaseModel for validation and type safety.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# Project root: progressive-agent/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class AgentConfig(BaseModel):
    """Core agent configuration."""

    name: str = "Progressive Agent"
    default_model: str = "claude-opus-4-6"
    fallback_model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096
    temperature: float = 0.7


class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    allowed_users: list[int] = Field(default_factory=list)
    streaming_chunk_size: int = 50


class MemoryConfig(BaseModel):
    """Memory subsystem configuration."""

    db_path: str = "data/memory.db"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimensions: int = 384
    max_context_memories: int = 10
    temporal_decay_lambda: float = 0.01


class CostConfig(BaseModel):
    """Cost tracking and budget limits."""

    daily_limit_usd: float = 5.0
    monthly_limit_usd: float = 50.0
    warning_threshold: float = 0.8
    db_path: str = "data/costs.db"


class EmailConfig(BaseModel):
    """Email (Gmail) configuration."""

    credentials_path: str = "config/gmail_credentials.json"
    token_path: str = "data/gmail_token.json"
    check_interval_minutes: int = 1
    max_results: int = 20


class CryptoConfig(BaseModel):
    """Crypto monitor configuration."""

    check_interval_minutes: int = 2
    threshold_usd: float = 500.0


class MonobankConfig(BaseModel):
    """Monobank API configuration."""

    check_interval_minutes: int = 3
    notify_transactions: bool = True


class SubscriptionConfig(BaseModel):
    """Subscription monitor configuration."""

    check_hour: int = 9  # Hour (local time) to run daily check


class ObsidianConfig(BaseModel):
    """Obsidian vault configuration."""

    vault_path: str = ""
    daily_folder: str = "01 Daily"
    inbox_folder: str = "00 Inbox"
    templates_folder: str = "Templates"


class TwitchConfig(BaseModel):
    """Twitch streamer monitor configuration."""

    check_interval_minutes: int = 3
    streamers: list[str] = Field(default_factory=list)


class YouTubeConfig(BaseModel):
    """YouTube monitor configuration."""

    check_interval_minutes: int = 30
    channels: list[str] = Field(default_factory=list)
    credentials_path: str = "config/gmail_credentials.json"
    token_path: str = "data/youtube_token.json"
    sync_subscriptions: bool = True  # auto-add subscribed channels to monitor


class NewsRadarConfig(BaseModel):
    """NewsRadar monitor — crypto + AI/tech + world news digest."""

    check_interval_hours: int = 4
    crypto_enabled: bool = True
    ai_enabled: bool = True
    world_enabled: bool = True
    cointelegraph_rss: bool = True
    coindesk_rss: bool = True
    reddit_crypto_rss: bool = True
    hackernews_enabled: bool = True
    huggingface_papers: bool = True
    reddit_ai_rss: bool = True
    github_trending: bool = True
    google_news_topics: list[str] = ["AI", "Technology"]
    reddit_worldnews_rss: bool = True
    max_articles_per_source: int = 10
    max_articles_total: int = 30
    max_seen_urls: int = 5000


class NovaPoshtaConfig(BaseModel):
    """Nova Poshta parcel monitor configuration."""

    check_interval_minutes: int = 30


class FilesConfig(BaseModel):
    """File tools configuration."""

    allowed_roots: list[str] = Field(default_factory=lambda: [str(Path.home())])
    max_file_size_mb: float = 1.0
    max_results: int = 20


class SearchConfig(BaseModel):
    """Search provider configuration."""

    provider: str = "tavily"
    max_results: int = 5


class WeatherConfig(BaseModel):
    """Weather tool configuration."""

    default_city: str = ""


class TTSConfig(BaseModel):
    """TTS / voice / video circle configuration."""

    default_voice: str = "ru-RU-DmitryNeural"
    speed: float = 1.0  # Speech speed multiplier (1.0=normal, 1.5=fast)
    avatar_path: str = ""  # Custom avatar PNG, empty = auto-generate


class MorningBriefingConfig(BaseModel):
    """Morning briefing configuration."""

    enabled: bool = True
    hour: int = 8
    minute: int = 0


class AppConfig(BaseModel):
    """Top-level application configuration combining all sections."""

    agent: AgentConfig = Field(default_factory=AgentConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    crypto: CryptoConfig = Field(default_factory=CryptoConfig)
    monobank: MonobankConfig = Field(default_factory=MonobankConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    subscription: SubscriptionConfig = Field(default_factory=SubscriptionConfig)
    twitch: TwitchConfig = Field(default_factory=TwitchConfig)
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    news_radar: NewsRadarConfig = Field(default_factory=NewsRadarConfig)
    files: FilesConfig = Field(default_factory=FilesConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    morning_briefing: MorningBriefingConfig = Field(default_factory=MorningBriefingConfig)
    novaposhta: NovaPoshtaConfig = Field(default_factory=NovaPoshtaConfig)

    # Scheduler
    scheduler_timezone: str = "Europe/Kiev"

    # Heartbeat — autonomous task interval (minutes)
    heartbeat_interval_minutes: int = 30

    # Secrets loaded from .env (not in TOML)
    claude_proxy_url: str = "http://127.0.0.1:8317/v1"
    anthropic_api_key: str = ""  # fallback only
    mistral_api_key: str = ""  # free tier fallback (1B tokens/month)
    telegram_bot_token: str = ""
    openai_api_key: str = ""
    tavily_api_key: str = ""
    tavily_api_keys: str = ""  # Comma-separated pool of Tavily keys for auto-rotation
    serpapi_api_key: str = ""
    jina_api_key: str = ""
    firecrawl_api_key: str = ""
    monobank_api_token: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    youtube_api_key: str = ""
    deepl_api_key: str = ""
    finnhub_api_key: str = ""
    novaposhta_api_key: str = ""
    gemini_api_key: str = ""  # Google Gemini free tier (15 RPM)
    cloudflare_api_key: str = ""  # Cloudflare Workers AI (10K req/day free)
    cloudflare_account_id: str = ""
    alerts_ua_token: str = ""  # alerts.in.ua air raid alerts
    tmdb_api_key: str = ""  # TMDB movies/TV shows (free)


def load_config(config_path: str = "config/agent.toml") -> AppConfig:
    """Load application config from TOML file and .env secrets.

    Args:
        config_path: Path to TOML config file, relative to project root.

    Returns:
        Fully populated AppConfig instance.
    """
    # Load .env file
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info("Loaded .env from %s", env_path)
    else:
        logger.warning("No .env file found at %s", env_path)

    # Load TOML config
    toml_path = PROJECT_ROOT / config_path
    toml_data: dict[str, Any] = {}

    if toml_path.exists():
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)
        logger.info("Loaded TOML config from %s", toml_path)
    else:
        logger.warning(
            "Config file not found at %s, using defaults", toml_path
        )

    # Build section configs from TOML data
    agent_cfg = AgentConfig(**toml_data.get("agent", {}))
    telegram_cfg = TelegramConfig(**toml_data.get("telegram", {}))
    memory_cfg = MemoryConfig(**toml_data.get("memory", {}))
    costs_cfg = CostConfig(**toml_data.get("costs", {}))
    search_cfg = SearchConfig(**toml_data.get("search", {}))
    email_cfg = EmailConfig(**toml_data.get("email", {}))
    crypto_cfg = CryptoConfig(**toml_data.get("crypto", {}))
    monobank_cfg = MonobankConfig(**toml_data.get("monobank", {}))
    obsidian_cfg = ObsidianConfig(**toml_data.get("obsidian", {}))
    subscription_cfg = SubscriptionConfig(**toml_data.get("subscription", {}))
    twitch_cfg = TwitchConfig(**toml_data.get("twitch", {}))
    youtube_cfg = YouTubeConfig(**toml_data.get("youtube", {}))
    news_radar_cfg = NewsRadarConfig(**toml_data.get("news_radar", {}))
    files_cfg = FilesConfig(**toml_data.get("files", {}))
    weather_cfg = WeatherConfig(**toml_data.get("weather", {}))
    tts_cfg = TTSConfig(**toml_data.get("tts", {}))
    morning_briefing_cfg = MorningBriefingConfig(**toml_data.get("morning_briefing", {}))
    novaposhta_cfg = NovaPoshtaConfig(**toml_data.get("novaposhta", {}))
    scheduler_tz = toml_data.get("scheduler", {}).get("timezone", "Europe/Kiev")
    heartbeat_interval = toml_data.get("heartbeat", {}).get("interval_minutes", 30)

    # Load secrets from environment
    config = AppConfig(
        agent=agent_cfg,
        telegram=telegram_cfg,
        memory=memory_cfg,
        costs=costs_cfg,
        search=search_cfg,
        email=email_cfg,
        crypto=crypto_cfg,
        monobank=monobank_cfg,
        obsidian=obsidian_cfg,
        subscription=subscription_cfg,
        twitch=twitch_cfg,
        youtube=youtube_cfg,
        news_radar=news_radar_cfg,
        files=files_cfg,
        weather=weather_cfg,
        tts=tts_cfg,
        morning_briefing=morning_briefing_cfg,
        novaposhta=novaposhta_cfg,
        scheduler_timezone=scheduler_tz,
        heartbeat_interval_minutes=heartbeat_interval,
        claude_proxy_url=os.getenv("CLAUDE_PROXY_URL", "http://127.0.0.1:8317/v1"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        mistral_api_key=os.getenv("MISTRAL_API_KEY", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        tavily_api_keys=os.getenv("TAVILY_API_KEYS", ""),
        serpapi_api_key=os.getenv("SERPAPI_API_KEY", ""),
        jina_api_key=os.getenv("JINA_API_KEY", ""),
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", ""),
        monobank_api_token=os.getenv("MONOBANK_API_TOKEN", ""),
        twitch_client_id=os.getenv("TWITCH_CLIENT_ID", ""),
        twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
        deepl_api_key=os.getenv("DEEPL_API_KEY", ""),
        finnhub_api_key=os.getenv("FINNHUB_API_KEY", ""),
        novaposhta_api_key=os.getenv("NOVAPOSHTA_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        cloudflare_api_key=os.getenv("CLOUDFLARE_API_KEY", ""),
        cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
        alerts_ua_token=os.getenv("ALERTS_UA_TOKEN", ""),
        tmdb_api_key=os.getenv("TMDB_API_KEY", ""),
    )

    # Warn about missing critical secrets
    if not config.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set in environment")
    if not config.claude_proxy_url and not config.anthropic_api_key:
        logger.warning("No Claude provider configured (CLAUDE_PROXY_URL or ANTHROPIC_API_KEY)")

    logger.info(
        "Config loaded: agent=%s, model=%s",
        config.agent.name,
        config.agent.default_model,
    )

    return config
