"""
Progressive Agent — main entry point.

Loads config, initializes all components, starts the Telegram bot.

Usage:
    python -m src.main
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from dotenv import load_dotenv

# Ensure project root is in path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.channels.base import IncomingMessage, OutgoingMessage
from src.channels.telegram import TelegramChannel
from src.core.agent import Agent
from src.core.config import CostConfig, load_config
from src.core.cost_tracker import CostTracker
from src.core.dispatcher import NativeDispatcher
from src.core.llm import create_provider
from src.core.router import Router
from src.core.tools import ToolRegistry
from src.memory.manager import MemoryManager
from src.skills.registry import SkillRegistry
from src.core.scheduler import Scheduler
from src.monitors.crypto_monitor import CryptoMonitor
from src.monitors.email_monitor import EmailMonitor
from src.monitors.monobank_monitor import MonobankMonitor
from src.monitors.subscription_monitor import SubscriptionMonitor
from src.monitors.news_radar_monitor import NewsRadarMonitor
from src.monitors.twitch_monitor import TwitchMonitor
from src.monitors.novaposhta_monitor import NovaPoshtaMonitor
from src.monitors.youtube_monitor import YouTubeMonitor
from src.tools.subscription_tool import (
    SubscriptionAddTool,
    SubscriptionListTool,
    SubscriptionRemoveTool,
)
from src.tools.monobank_tool import (
    MonobankBalanceTool,
    MonobankRatesTool,
    MonobankService,
    MonobankTransactionsTool,
)
from src.tools.obsidian_tool import (
    ObsidianDailyTool,
    ObsidianListTool,
    ObsidianNoteTool,
    ObsidianSearchTool,
    ObsidianService,
)
from src.tools.email_tool import EmailComposeTool, EmailInboxTool, EmailReadTool, GmailService
from src.tools.file_tool import (
    FileCopyTool, FileDeleteTool, FileListTool, FileOpenTool, FilePdfTool,
    FileReadTool, FileSearchTool, FileSendTool, FileService, FileWriteTool,
)
from src.tools.contact_tool import ContactTool
from src.tools.novaposhta_tool import NovaPoshtaTool
from src.tools.cli_tool import CliExecTool
from src.tools.browser_tool import (
    BrowserActionTool, BrowserBookmarksTool, BrowserCloseTool,
    BrowserHistoryTool, BrowserOpenTool, BrowserService,
)
from src.tools.search_tool import SearchTool, WebExtractTool, WebReaderTool, WebResearchTool, init_tavily_pool
from src.tools.twitch_tool import TwitchStatusTool
from src.tools.youtube_tool import (
    YouTubeInfoTool,
    YouTubeLikedTool,
    YouTubeSearchTool,
    YouTubeSubscriptionsTool,
    YouTubeSummaryTool,
)
from src.tools.stt_tool import STTTool
from src.tools.document_parser import parse_document
from src.tools.git_tool import GitTool
from src.tools.agent_control_tool import AgentControlTool
from src.tools.weather_tool import WeatherTool
from src.tools.image_gen_tool import ImageGenTool
from src.tools.bg_removal_tool import BackgroundRemovalTool
from src.tools.tts_tool import TTSTool
from src.tools.scheduler_tool import SchedulerService, SchedulerAddTool, SchedulerListTool, SchedulerRemoveTool
from src.core.heartbeat import HeartbeatEngine
from src.tools.qr_tool import QRCodeTool
from src.tools.clipboard_tool import ClipboardTool
from src.tools.deepl_tool import DeepLTool
from src.tools.finnhub_tool import FinnhubTool
from src.tools.screenshot_tool import ScreenshotTool
from src.core.self_improve import SelfImproveTool, load_agents_md
from src.tools.exchange_rates_tool import ExchangeRatesTool
from src.tools.system_tool import SystemTool
from src.tools.media_tool import MediaDownloadTool
from src.monitors.morning_briefing_monitor import MorningBriefingMonitor
from src.tools.defi_llama_tool import DefiLlamaTool
from src.tools.dex_screener_tool import DexScreenerTool
from src.tools.coingecko_tool import CoinGeckoTool
from src.tools.fear_greed_tool import FearGreedTool
from src.tools.alerts_ua_tool import AlertsUaTool
from src.tools.wikipedia_tool import WikipediaTool
from src.tools.tmdb_tool import TMDBTool
from src.tools.github_tool import GitHubTool
from src.tools.hackernews_tool import HackerNewsTool
from src.tools.reddit_tool import RedditTool
from src.tools.shazam_tool import ShazamTool
from src.tools.audio_capture_tool import AudioCaptureTool
from src.tools.ocr_tool import OCRTool
from src.tools.diagram_tool import DiagramTool
from src.monitors.tech_radar_monitor import TechRadarMonitor
from src.tools.speedtest_tool import SpeedTestTool
from src.tools.exif_tool import ExifReaderTool
from src.tools.prozorro_tool import ProzorroTool
from src.tools.datagov_tool import DataGovTool
from src.tools.ukrpravda_tool import UkrPravdaTool
from src.tools.csv_tool import CSVAnalystTool
from src.tools.pdf_tool import PDFSwissKnifeTool
from src.tools.goal_tool import GoalTool
from src.tools.orchestrator_tool import OrchestratorTool
from src.core.goals import GoalEngine
from src.core.orchestrator import MultiAgentOrchestrator

logger = logging.getLogger("progressive_agent")


def _cleanup_temp_files(msg: IncomingMessage) -> None:
    """Remove temp directories created for downloaded media files."""
    temp_base = tempfile.gettempdir()
    for attr in ("voice_file_path", "audio_file_path", "video_note_file_path", "document_file_path", "photo_file_path"):
        path = getattr(msg, attr, None)
        if path and isinstance(path, Path):
            parent = path.parent
            if str(parent).startswith(temp_base):
                shutil.rmtree(parent, ignore_errors=True)


def _clean_text_for_tts(text: str) -> str:
    """Remove emojis and special characters that TTS shouldn't pronounce.

    Keeps: letters, numbers, punctuation, spaces
    Removes: emojis, special symbols, markdown formatting
    """
    import re

    # Remove markdown bold/italic markers
    text = re.sub(r'\*\*?|__|~~', '', text)

    # Remove emojis and other unicode symbols
    # Keep basic Latin, Cyrillic, punctuation, numbers
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)

    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


# Image MIME types by extension
_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _encode_image(file_path: Path) -> tuple[str, str]:
    """Read an image file and return (base64_data, media_type).

    Args:
        file_path: Path to the image file.

    Returns:
        Tuple of (base64-encoded string, MIME type).
    """
    ext = file_path.suffix.lower()
    media_type = _IMAGE_MEDIA_TYPES.get(ext, "image/jpeg")
    data = file_path.read_bytes()
    return base64.standard_b64encode(data).decode("ascii"), media_type


def setup_logging() -> None:
    """Configure application-wide logging to console + file."""
    log_dir = project_root / "data"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "agent.log"

    # Root logger: both console and file
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root_logger.addHandler(console_handler)

    # File handler (rotating-like: 5 MB max, keep last log)
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        str(log_file), maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root_logger.addHandler(file_handler)


def setup_crash_handlers() -> None:
    """Install global crash handlers so fatal errors are logged before death.

    Catches: unhandled exceptions (sys.excepthook), unhandled thread
    exceptions (threading.excepthook), and asyncio loop exceptions.
    Without this, a crash in a thread or C extension dies silently.
    """
    import sys
    import threading

    crash_log = project_root / "data" / "crash.log"

    def _write_crash(label: str, text: str) -> None:
        """Append crash info to crash.log (bypasses logging in case it's broken)."""
        try:
            crash_log.parent.mkdir(exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n{ts} | {label}\n{text}\n")
        except Exception:
            pass

    # 1. Unhandled Python exceptions (main thread)
    _original_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("FATAL unhandled exception:\n%s", tb)
        _write_crash("sys.excepthook", tb)
        _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # 2. Unhandled exceptions in threads (e.g. asyncio.to_thread workers)
    def _threading_excepthook(args):
        import traceback
        tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        thread_name = args.thread.name if args.thread else "unknown"
        logger.critical("FATAL unhandled thread exception [%s]:\n%s", thread_name, tb)
        _write_crash(f"threading.excepthook [{thread_name}]", tb)

    threading.excepthook = _threading_excepthook

    # 3. asyncio event loop exception handler (installed later in main)
    logger.info("Global crash handlers installed (sys + threading + crash.log)")



PROXY_EXE = project_root / "CLIProxyAPI" / "cli-proxy-api.exe"


async def ensure_proxy_running(proxy_url: str) -> bool:
    """Check if CLIProxyAPI is alive; auto-start it if not.

    Returns True if proxy is reachable after this call.
    """
    parsed = urlparse(proxy_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    models_url = f"{base}/v1/models"

    # 1. Quick health check
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                models_url,
                headers={"Authorization": "Bearer progressive-agent-local"},
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = len(data.get("data", []))
                    logger.info("CLIProxyAPI already running — %d models available", count)
                    return True
    except Exception:
        pass

    # 2. Proxy not reachable — try to auto-start
    if not PROXY_EXE.exists():
        logger.error(
            "CLIProxyAPI not found at %s — agent cannot connect to Claude. "
            "Download it or start it manually.",
            PROXY_EXE,
        )
        return False

    logger.warning("CLIProxyAPI not running — auto-starting...")
    try:
        subprocess.Popen(
            [str(PROXY_EXE)],
            cwd=str(PROXY_EXE.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        logger.exception("Failed to auto-start CLIProxyAPI")
        return False

    # 3. Wait for proxy to become ready (up to 10s)
    for i in range(10):
        await asyncio.sleep(1)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    models_url,
                    headers={"Authorization": "Bearer progressive-agent-local"},
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        count = len(data.get("data", []))
                        logger.info(
                            "CLIProxyAPI auto-started successfully — %d models available",
                            count,
                        )
                        return True
        except Exception:
            pass

    logger.error("CLIProxyAPI started but not responding after 10s")
    return False


async def check_proxy_auth(proxy_url: str) -> tuple[bool, bool, str]:
    """Check if proxy is alive AND has valid auth.

    Returns:
        (is_reachable, is_auth_ok, detail_message)
    """
    parsed = urlparse(proxy_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Quick health check via /v1/models
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base}/v1/models",
                headers={"Authorization": "Bearer progressive-agent-local"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return True, True, "OK"
                elif resp.status in (500, 503):
                    data = await resp.json()
                    msg = data.get("error", {}).get("message", "")
                    if "auth" in msg.lower():
                        return True, False, f"Auth expired: {msg}"
                    return True, False, f"Server error: {msg}"
                else:
                    return True, False, f"HTTP {resp.status}"
    except aiohttp.ClientConnectorError:
        return False, False, "Proxy not reachable (connection refused)"
    except Exception as e:
        return False, False, f"Health check failed: {e}"


class ProxyMonitor:
    """Periodically checks CLIProxyAPI status and notifies on failures."""

    def __init__(
        self,
        proxy_url: str,
        notify_callback: Any,  # async (str) -> None
        user_id: str,
    ) -> None:
        self._proxy_url = proxy_url
        self._notify = notify_callback
        self._user_id = user_id
        self._last_status_ok = True  # assume OK at start
        self._notified_down = False

    async def check(self) -> None:
        """Run a health check; notify user on status transitions."""
        reachable, auth_ok, detail = await check_proxy_auth(self._proxy_url)

        if reachable and auth_ok:
            if not self._last_status_ok:
                # Recovered!
                logger.info("CLIProxyAPI recovered: %s", detail)
                self._last_status_ok = True
                self._notified_down = False
                if self._user_id:
                    await self._notify(
                        self._user_id,
                        "Claude proxy восстановлен, бот снова работает.",
                    )
            return

        # Something is wrong
        self._last_status_ok = False

        if not reachable:
            logger.warning("CLIProxyAPI not reachable — attempting auto-restart")
            restarted = await ensure_proxy_running(self._proxy_url)
            if restarted:
                logger.info("CLIProxyAPI auto-restarted successfully")
                self._last_status_ok = True
                self._notified_down = False
                return

        # Auth expired — try automatic token refresh
        if reachable and not auth_ok and "auth" in detail.lower():
            logger.warning("Proxy auth expired — attempting auto-refresh")
            refreshed = await self._try_token_refresh()
            if refreshed:
                # Re-check after refresh
                reachable2, auth_ok2, _ = await check_proxy_auth(self._proxy_url)
                if reachable2 and auth_ok2:
                    logger.info("Token auto-refreshed, proxy recovered!")
                    self._last_status_ok = True
                    self._notified_down = False
                    if self._user_id:
                        await self._notify(
                            self._user_id,
                            "OAuth токен обновлён автоматически, бот работает.",
                        )
                    return

        # Notify user (once per failure episode)
        if not self._notified_down and self._user_id:
            self._notified_down = True
            if not reachable:
                msg = (
                    "Claude proxy упал и не смог перезапуститься. "
                    "Запусти CLIProxyAPI вручную."
                )
            else:
                msg = (
                    "Claude proxy: авторизация слетела, авто-рефреш не помог. "
                    "Запусти proxy-manager.bat → пункт 6 (переавторизация)."
                )
            logger.error("Proxy alert: %s (%s)", msg, detail)
            await self._notify(self._user_id, msg)

    async def _try_token_refresh(self) -> bool:
        """Try to refresh the OAuth token using refresh_token."""
        try:
            from scripts.refresh_proxy_token import async_refresh_token
            return await async_refresh_token()
        except Exception as e:
            logger.error("Token auto-refresh failed: %s", e)
            # Fallback: try running the script directly
            try:
                import asyncio
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(Path(__file__).resolve().parent.parent / "scripts" / "refresh_proxy_token.py"),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode == 0:
                    logger.info("Token refreshed via subprocess")
                    return True
                else:
                    logger.error("Token refresh subprocess failed: %s", stderr.decode())
                    return False
            except Exception as e2:
                logger.error("Token refresh subprocess also failed: %s", e2)
                return False


async def main() -> None:
    """Main async entry point — initialize components and run the bot."""
    load_dotenv()
    setup_logging()
    setup_crash_handlers()
    logger.info("Starting Progressive Agent...")

    # Asyncio-level exception handler — catches unhandled errors in tasks/callbacks
    loop = asyncio.get_running_loop()

    def _asyncio_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "")
        if exc:
            logger.critical(
                "Asyncio unhandled exception: %s — %s", msg, exc, exc_info=exc,
            )
        else:
            logger.critical("Asyncio error: %s", msg)

    loop.set_exception_handler(_asyncio_exception_handler)

    # 1. Load config
    config = load_config()
    logger.info("Config loaded: %s", config.agent.name)

    # 1.5. Ensure CLIProxyAPI is running (auto-start if needed)
    if config.claude_proxy_url:
        proxy_ok = await ensure_proxy_running(config.claude_proxy_url)
        if not proxy_ok:
            logger.error(
                "Claude proxy not available. Start it via Proxy Manager or set ANTHROPIC_API_KEY as fallback."
            )
            if not config.anthropic_api_key:
                logger.critical("No LLM provider available — exiting.")
                sys.exit(1)
            logger.warning("Falling back to Anthropic API key")

    # 2. Initialize memory
    memory = MemoryManager(
        db_path=config.memory.db_path,
        embedding_model=config.memory.embedding_model,
    )
    await memory.init()
    purged = await memory.purge_orphans()
    if purged:
        logger.info("Memory initialized (purged %d orphaned index entries)", purged)
    else:
        logger.info("Memory initialized")

    # 3. Initialize tools
    tool_registry = ToolRegistry()

    # Initialize Tavily key pool for auto-rotation
    tavily_keys = [k.strip() for k in config.tavily_api_keys.split(",") if k.strip()]
    if not tavily_keys and config.tavily_api_key:
        tavily_keys = [config.tavily_api_key]
    if tavily_keys:
        tavily_pool = init_tavily_pool(tavily_keys)
        logger.info("Tavily key pool: %d keys loaded", tavily_pool.key_count)

    # Multi-provider search (Tavily + SerpApi + Jina + Firecrawl)
    search_tool = SearchTool(
        tavily_key=config.tavily_api_key,
        serpapi_key=config.serpapi_api_key,
        jina_key=config.jina_api_key,
        firecrawl_key=config.firecrawl_api_key,
    )
    tool_registry.register(search_tool)
    logger.info("Search providers: %s", search_tool.available_providers)

    # Web reader (Jina + Firecrawl fallback)
    web_reader = WebReaderTool(
        jina_key=config.jina_api_key,
        firecrawl_key=config.firecrawl_api_key,
    )
    tool_registry.register(web_reader)

    # Tavily Extract (batch URL content extraction, 1 credit per 5 URLs)
    web_extract = WebExtractTool(tavily_key=config.tavily_api_key)
    tool_registry.register(web_extract)

    # Tavily Research (deep research reports, 4-250 credits per request)
    web_research = WebResearchTool(tavily_key=config.tavily_api_key)
    tool_registry.register(web_research)

    # Speech-to-Text (local faster-whisper, no API key needed)
    stt_tool = STTTool(model_size="base")
    tool_registry.register(stt_tool)

    # Gmail tools (OAuth2 — needs config/gmail_credentials.json + first-time setup)
    gmail_service = GmailService(
        credentials_path=config.email.credentials_path,
        token_path=config.email.token_path,
    )
    if gmail_service.available:
        tool_registry.register(EmailInboxTool(gmail_service))
        tool_registry.register(EmailReadTool(gmail_service))
        tool_registry.register(EmailComposeTool(gmail_service))
        logger.info("Gmail tools registered (3 tools)")
    else:
        logger.warning(
            "Gmail not configured — run: python -m src.tools.email_tool --setup"
        )

    # File tools (search, read, list, write, delete)
    file_service = FileService(
        allowed_roots=config.files.allowed_roots,
        max_file_size_mb=config.files.max_file_size_mb,
        max_results=config.files.max_results,
    )
    file_send_tool = FileSendTool(file_service)
    tool_registry.register(FileSearchTool(file_service))
    tool_registry.register(FileReadTool(file_service))
    tool_registry.register(FileListTool(file_service))
    tool_registry.register(FileWriteTool(file_service))
    tool_registry.register(FileDeleteTool(file_service))
    tool_registry.register(FileOpenTool(file_service))
    tool_registry.register(file_send_tool)
    tool_registry.register(FilePdfTool(file_service))
    tool_registry.register(FileCopyTool(file_service))
    logger.info("File tools registered (9 tools)")

    # Contact management tool
    tool_registry.register(ContactTool())
    logger.info("Contact tool registered")

    # 3c. CLI tool
    cli_tool = CliExecTool()
    tool_registry.register(cli_tool)
    logger.info("CLI tool registered")

    # 3d. Monobank tools (balance, transactions, rates)
    mono_service = MonobankService(token=config.monobank_api_token)
    if mono_service.available:
        tool_registry.register(MonobankBalanceTool(mono_service))
        tool_registry.register(MonobankTransactionsTool(mono_service))
        tool_registry.register(MonobankRatesTool(mono_service))
        logger.info("Monobank tools registered (3 tools)")
    else:
        mono_service = None
        logger.warning("Monobank not configured — set MONOBANK_API_TOKEN in .env")

    # 3e. Obsidian tools (note, search, daily, list)
    obsidian_service = ObsidianService(
        vault_path=config.obsidian.vault_path,
        daily_folder=config.obsidian.daily_folder,
        inbox_folder=config.obsidian.inbox_folder,
        templates_folder=config.obsidian.templates_folder,
    )
    if obsidian_service.available:
        tool_registry.register(ObsidianNoteTool(obsidian_service))
        tool_registry.register(ObsidianSearchTool(obsidian_service))
        tool_registry.register(ObsidianDailyTool(obsidian_service))
        tool_registry.register(ObsidianListTool(obsidian_service))
        logger.info("Obsidian tools registered (4 tools)")
    else:
        logger.warning("Obsidian vault not found at %s", config.obsidian.vault_path)

    # 3f. Browser tools (Playwright: open, action, history, bookmarks, close)
    browser_service = BrowserService()
    if browser_service.available:
        tool_registry.register(BrowserOpenTool(browser_service))
        tool_registry.register(BrowserActionTool(browser_service))
        tool_registry.register(BrowserHistoryTool(browser_service))
        tool_registry.register(BrowserBookmarksTool(browser_service))
        tool_registry.register(BrowserCloseTool(browser_service))
        logger.info("Browser tools registered (5 tools)")
    else:
        logger.warning("Chrome not found — browser tools disabled")

    # 3g. Git tool (first-class git operations)
    tool_registry.register(GitTool())
    logger.info("Git tool registered")

    # 3h. Agent control tool (restart, update, health)
    tool_registry.register(AgentControlTool())
    logger.info("Agent control tool registered")

    # 3i. Weather tool (wttr.in, free, no API key)
    weather_tool = WeatherTool(default_city=config.weather.default_city)
    tool_registry.register(weather_tool)
    logger.info("Weather tool registered (city: %s)", config.weather.default_city)

    # 3j. Image generation tool (DALL-E 3)
    image_gen_tool = None
    if config.openai_api_key:
        image_gen_tool = ImageGenTool(
            api_key=config.openai_api_key,
            pending_sends=file_send_tool.pending_sends,
        )
        tool_registry.register(image_gen_tool)
        logger.info("Image generation tool registered (DALL-E 3)")
    else:
        logger.warning("DALL-E not configured — set OPENAI_API_KEY in .env")

    # 3j2. Background removal tool (rembg, local AI, no API key)
    bg_removal_tool = BackgroundRemovalTool(
        pending_sends=file_send_tool.pending_sends,
    )
    tool_registry.register(bg_removal_tool)
    logger.info("Background removal tool registered (rembg)")

    # 3k. TTS tool (OpenAI tts-1-hd primary, edge-tts fallback, video circles)
    tts_tool = TTSTool(
        openai_api_key=config.openai_api_key,
        default_voice=config.tts.default_voice,
        speed=config.tts.speed,
        avatar_path=config.tts.avatar_path or None,
    )
    if tts_tool.available:
        tool_registry.register(tts_tool)
        logger.info("TTS tool registered (provider: %s, voice: %s)", tts_tool.provider, config.tts.default_voice)
    else:
        logger.warning("TTS not available — set OPENAI_API_KEY or install edge-tts")

    # 3l. QR Code tool (no API key needed)
    tool_registry.register(QRCodeTool())
    logger.info("QR Code tool registered")

    # 3m. Clipboard tool (no API key needed)
    tool_registry.register(ClipboardTool())
    logger.info("Clipboard tool registered")

    # 3n. DeepL translation tool (free API, 500K chars/mo)
    if config.deepl_api_key:
        tool_registry.register(DeepLTool(api_key=config.deepl_api_key))
        logger.info("DeepL translation tool registered")
    else:
        logger.warning("DeepL not configured — set DEEPL_API_KEY in .env for translations")

    # 3o. Finnhub finance tool (free API, 60 calls/min)
    if config.finnhub_api_key:
        tool_registry.register(FinnhubTool(api_key=config.finnhub_api_key))
        logger.info("Finnhub finance tool registered")
    else:
        logger.warning("Finnhub not configured — get free key at https://finnhub.io/ and set FINNHUB_API_KEY in .env")

    # 3p. Self-improve tool (AGENTS.md learnings)
    tool_registry.register(SelfImproveTool())
    logger.info("Self-improve (learn) tool registered")

    # 3r. Exchange rates tool (PrivatBank + NBU, no API key)
    tool_registry.register(ExchangeRatesTool())
    logger.info("Exchange rates tool registered (PrivatBank + NBU)")

    # 3s. System monitoring tool (psutil)
    tool_registry.register(SystemTool())
    logger.info("System monitoring tool registered")

    # 3t. Media download tool (yt-dlp)
    media_tool = MediaDownloadTool(pending_sends=file_send_tool.pending_sends)
    tool_registry.register(media_tool)
    logger.info("Media download tool registered (yt-dlp)")

    # 3u. Nova Poshta tool (parcel tracking, free API)
    if config.novaposhta_api_key:
        tool_registry.register(NovaPoshtaTool(api_key=config.novaposhta_api_key))
        logger.info("Nova Poshta tool registered")
    else:
        logger.warning("Nova Poshta not configured — set NOVAPOSHTA_API_KEY in .env")

    # 3v. DeFi / Crypto tools (all FREE, no API keys)
    tool_registry.register(DefiLlamaTool())
    tool_registry.register(DexScreenerTool())
    tool_registry.register(CoinGeckoTool())
    tool_registry.register(FearGreedTool())
    logger.info("DeFi/Crypto tools registered (4 tools: DefiLlama, DexScreener, CoinGecko, Fear&Greed)")

    # 3w. Wikipedia + Wikidata (FREE, no API key)
    tool_registry.register(WikipediaTool())
    logger.info("Wikipedia + Wikidata tool registered")

    # 3x. Alerts.in.ua (Ukrainian air raid alerts)
    if config.alerts_ua_token:
        tool_registry.register(AlertsUaTool(api_token=config.alerts_ua_token))
        logger.info("Alerts.in.ua tool registered (air raid alerts)")
    else:
        logger.warning("Alerts.in.ua not configured — set ALERTS_UA_TOKEN in .env")

    # 3y. TMDB (movies, TV shows)
    if config.tmdb_api_key:
        tool_registry.register(TMDBTool(api_key=config.tmdb_api_key))
        logger.info("TMDB tool registered (movies & TV shows)")
    else:
        logger.warning("TMDB not configured — get free key at themoviedb.org and set TMDB_API_KEY in .env")

    # 3z. GitHub + Hacker News + Reddit (FREE, no API keys)
    tool_registry.register(GitHubTool())
    tool_registry.register(HackerNewsTool())
    tool_registry.register(RedditTool())
    logger.info("GitHub + HackerNews + Reddit tools registered (all free, no keys)")

    # --- Shazam + Audio Capture (music recognition, free, no API key) ---
    tool_registry.register(ShazamTool())
    tool_registry.register(AudioCaptureTool())
    logger.info("Shazam + AudioCapture tools registered (Stereo Mix loopback)")

    # --- OCR (text extraction from images, local ONNX, no API key) ---
    tool_registry.register(OCRTool())
    logger.info("OCR tool registered (RapidOCR, ONNX Runtime)")

    # --- Diagram generator (Mermaid → PNG via mermaid.ink, free) ---
    diagram_tool = DiagramTool(pending_sends=file_send_tool.pending_sends)
    tool_registry.register(diagram_tool)
    logger.info("Diagram tool registered (mermaid.ink)")

    # --- Speed test (Ookla, no API key) ---
    tool_registry.register(SpeedTestTool())
    logger.info("Speed test tool registered (Ookla)")

    # --- EXIF Reader (Pillow + geopy, no API key) ---
    tool_registry.register(ExifReaderTool())
    logger.info("EXIF reader tool registered (Pillow + geopy)")

    # --- Prozorro (Ukrainian public procurement, free API) ---
    tool_registry.register(ProzorroTool())
    logger.info("Prozorro tool registered (госзакупки)")

    # --- data.gov.ua (Ukrainian open data, CKAN API, free) ---
    tool_registry.register(DataGovTool())
    logger.info("data.gov.ua tool registered (відкриті дані)")

    # --- UkrPravda RSS (UP + Epravda + EuroPravda, free) ---
    tool_registry.register(UkrPravdaTool())
    logger.info("UkrPravda RSS tool registered (3 feeds)")

    # --- CSV/Excel Analyst (pandas + matplotlib, no API key) ---
    csv_tool = CSVAnalystTool(pending_sends=file_send_tool.pending_sends)
    tool_registry.register(csv_tool)
    logger.info("CSV/Excel analyst tool registered (pandas + matplotlib)")

    # --- PDF Swiss Knife (pypdf, no API key) ---
    pdf_knife = PDFSwissKnifeTool(pending_sends=file_send_tool.pending_sends)
    tool_registry.register(pdf_knife)
    logger.info("PDF Swiss Knife tool registered (pypdf)")

    logger.info("Tools registered: %d (subscription + scheduler + screenshot deferred)", len(tool_registry.list_tools()))

    # 4. Initialize skills
    skill_registry = SkillRegistry(skills_dir="skills")
    await skill_registry.load()
    logger.info("Skills loaded: %d", len(skill_registry.list_skills()))

    # 4a. Skill manager tool (hot-reload, create, delete skills at runtime)
    from src.tools.skill_manager_tool import SkillManagerTool
    skill_manager = SkillManagerTool(skill_registry=skill_registry)
    tool_registry.register(skill_manager)
    logger.info("Skill manager tool registered (hot-reload enabled)")

    # 5. Initialize cost tracker
    cost_tracker = CostTracker(
        config=CostConfig(
            daily_limit_usd=config.costs.daily_limit_usd,
            monthly_limit_usd=config.costs.monthly_limit_usd,
            warning_threshold=config.costs.warning_threshold,
            db_path=config.costs.db_path,
        ),
    )
    await cost_tracker.initialize()

    # 6. Build agent — Claude через подписку (primary) + Mistral fallback (free tier)
    provider = create_provider(
        proxy_url=config.claude_proxy_url,
        api_key=config.anthropic_api_key,
        mistral_api_key=config.mistral_api_key,
        openai_api_key=config.openai_api_key,
        gemini_api_key=config.gemini_api_key,
        cloudflare_api_key=config.cloudflare_api_key,
        cloudflare_account_id=config.cloudflare_account_id,
        model=config.agent.default_model,
        max_tokens=config.agent.max_tokens,
    )
    logger.info("LLM provider: %s", provider.name)

    # 3q. Screenshot tool (needs LLM provider for OCR)
    screenshot_tool = ScreenshotTool(llm_provider=provider)
    tool_registry.register(screenshot_tool)
    logger.info("Screenshot + OCR tool registered")

    agent = (
        Agent.builder()
        .provider(provider)
        .memory(memory)
        .tools(tool_registry)
        .soul_path("soul")
        .skills(skill_registry)
        .config(config)
        .router(
            Router(
                default_model=config.agent.default_model,
                fast_model=config.agent.fallback_model,
            )
        )
        .dispatcher(NativeDispatcher())
        .cost_tracker(cost_tracker)
        .build()
    )
    logger.info("Agent built successfully")

    # 7. Initialize Telegram channel
    telegram = TelegramChannel(
        bot_token=config.telegram_bot_token,
        allowed_users=config.telegram.allowed_users,
        streaming_chunk_size=config.telegram.streaming_chunk_size,
    )

    # Set up TTS indicator callback (shows "recording video note" during generation)
    if tts_tool.available:
        async def show_video_note_indicator():
            if tts_tool._current_user_id:
                await telegram.send_record_video_note(tts_tool._current_user_id)

        tts_tool.set_indicator_callback(show_video_note_indicator)
        logger.info("TTS indicator callback registered")

    # Owner user ID for monitor notifications
    monitor_user = str(config.telegram.allowed_users[0]) if config.telegram.allowed_users else ""

    # Register subscription tools (needs monitor_user + telegram)
    async def _sub_notify(user_id: str, text: str) -> None:
        await telegram.send(OutgoingMessage(user_id=user_id, text=text))

    sub_monitor = SubscriptionMonitor(notify=_sub_notify, user_id=monitor_user)
    tool_registry.register(SubscriptionAddTool(sub_monitor))
    tool_registry.register(SubscriptionListTool(sub_monitor))
    tool_registry.register(SubscriptionRemoveTool(sub_monitor))
    logger.info("Subscription tools registered (3 tools, %d subs)", len(sub_monitor.list_all()))

    # --- Multi-Agent Orchestrator (parallel sub-agents via Claude proxy, zero cost) ---
    orchestrator = MultiAgentOrchestrator(provider=provider)
    tool_registry.register(OrchestratorTool(orchestrator))
    logger.info("Multi-Agent Orchestrator tool registered (max 5 parallel agents)")

    # 8. Message processing loop
    queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()

    # Stranger rate-limit state
    stranger_timestamps: dict[str, list[float]] = {}  # uid -> [monotonic timestamps]
    stranger_notified: set[str] = set()  # uids we already alerted owner about

    async def process_messages() -> None:
        """Consume messages from the queue and process through the agent."""
        while True:
            msg = await queue.get()
            try:
                # Handle voice -> text conversion
                if msg.voice_file_path and not msg.text:
                    stt_result = await stt_tool.execute(
                        file_path=str(msg.voice_file_path)
                    )
                    if stt_result.success:
                        msg.text = stt_result.data
                    else:
                        logger.error("STT failed: %s", stt_result.error)
                        error_detail = stt_result.error or "unknown error"
                        await telegram.send(
                            OutgoingMessage(
                                user_id=msg.user_id,
                                text=f"Не удалось распознать голосовое: {error_detail}",
                            )
                        )
                        continue

                # Inject voice file path so LLM can call shazam if needed
                if msg.voice_file_path:
                    voice_note = (
                        f"\n\n[Голосовое сообщение сохранено: {msg.voice_file_path}. "
                        "Если пользователь просит распознать песню/музыку, "
                        "используй shazam tool с этим file_path.]"
                    )
                    msg.text = (msg.text or "") + voice_note

                # Handle audio file (MP3/M4A sent as music)
                if msg.audio_file_path:
                    audio_note = (
                        f"\n\n[Аудиофайл получен: {msg.audio_file_path}. "
                        "Используй shazam tool для распознавания песни, "
                        "или stt tool для транскрипции речи.]"
                    )
                    if msg.text:
                        msg.text += audio_note
                    else:
                        msg.text = f"Пользователь отправил аудиофайл.{audio_note}"

                # Handle video note (кружок) — STT audio + thumbnail for Vision
                if msg.video_note_file_path:
                    stt_result = await stt_tool.execute(
                        file_path=str(msg.video_note_file_path)
                    )
                    if stt_result.success and stt_result.data:
                        vn_text = f"\U0001F3A5 Видео-кружок (расшифровка аудио):\n\"{stt_result.data}\""
                    else:
                        vn_text = "\U0001F3A5 Видео-кружок (аудио не удалось расшифровать)"
                        logger.warning("Video note STT failed: %s", stt_result.error)

                    if msg.text:
                        msg.text = f"{msg.text}\n\n{vn_text}"
                    else:
                        msg.text = vn_text

                    # Auto-respond with circle when user sends circle
                    if tts_tool.available:
                        msg.text += (
                            "\n\n[Пользователь отправил видео-кружочек. "
                            "Ответь тоже кружочком — используй tts tool с format=video_note. "
                            "Ответ должен быть коротким и живым.]"
                        )

                # Secret trigger: if message contains smile ") " or "))", respond with circle
                # But only if it's a real smile, not text in parentheses like "(text)"
                # Check: if more closing ) than opening ( → it's a smile
                _tts_tool = agent._tool_registry._tools.get("tts")
                if _tts_tool and hasattr(_tts_tool, 'available') and _tts_tool.available and msg.text and ')' in msg.text:
                    open_count = msg.text.count('(')
                    close_count = msg.text.count(')')
                    if close_count > open_count:
                        msg.text += (
                            "\n\n[Секретный триггер активирован (улыбка в сообщении). "
                            "Ответь кружочком — используй tts tool с format=video_note.]"
                        )

                # Handle document attachments — parse content and inject into text
                if msg.document_file_path:
                    doc_content = await asyncio.to_thread(
                        parse_document,
                        msg.document_file_path, msg.document_file_name or "file",
                    )
                    _doc_name = msg.document_file_name or "file"
                    file_header = f"\U0001F4CE Файл: {_doc_name}\n\n"
                    if msg.text:
                        msg.text = f"{msg.text}\n\n{file_header}{doc_content}"
                    else:
                        msg.text = f"{file_header}{doc_content}"

                # Handle photo attachments — encode as base64 for Claude Vision
                if msg.photo_file_path:
                    try:
                        b64_data, media_type = _encode_image(msg.photo_file_path)
                        msg.image_base64 = b64_data
                        msg.image_media_type = media_type
                        if not msg.text:
                            msg.text = ""  # Vision needs at least empty text
                        logger.info(
                            "Image encoded for vision: %s (%s, %d KB)",
                            msg.photo_file_path.name,
                            media_type,
                            len(b64_data) * 3 // 4 // 1024,
                        )
                        # Inject photo path so LLM can call bg_remove / ocr
                        photo_note = (
                            f"\n\n[Фото сохранено: {msg.photo_file_path}. "
                            "Если пользователь просит убрать фон → bg_remove image_path=...; "
                            "распознать текст → ocr image_path=...]"
                        )
                        msg.text = (msg.text or "") + photo_note
                    except Exception as exc:
                        logger.error("Failed to encode image: %s", exc)
                        photo_info = f"[Не удалось прочитать фото: {exc}]"
                        if msg.text:
                            msg.text = f"{msg.text}\n\n{photo_info}"
                        else:
                            msg.text = photo_info

                # Prepend forward context so Claude knows it's a forwarded message
                if msg.forward_info and msg.text:
                    msg.text = f"[{msg.forward_info}]\n\n{msg.text}"
                elif msg.forward_info and not msg.text:
                    msg.text = f"[{msg.forward_info}]"

                if not msg.text:
                    continue

                # --- Stranger fast path (troll mode, rate-limited) ---
                if not msg.is_owner:
                    now = time.monotonic()
                    uid = msg.user_id

                    # Rate limit: 20 messages per 10 minutes per stranger
                    stranger_timestamps[uid] = [
                        t for t in stranger_timestamps.get(uid, [])
                        if now - t < 600  # 10 min window
                    ]

                    rate_limited = len(stranger_timestamps[uid]) >= 20

                    _RATE_LIMIT_REPLIES = [
                        "Слушай, ты уже достаточно написал. Отдохни минут 10 😏",
                        "Лимит исчерпан. Попробуй позже... или не пробуй",
                        "Тебе хватит. Иди попей чаю и приходи через 10 минут",
                        "Окей, ты настойчивый. Но я всё равно молчу. Подожди немного",
                    ]

                    try:
                        if rate_limited:
                            response = random.choice(_RATE_LIMIT_REPLIES)
                        else:
                            # Get user name from Telegram profile
                            raw = msg.raw
                            first_name = ""
                            if raw and hasattr(raw, "from_user") and raw.from_user:
                                first_name = raw.from_user.first_name or ""

                            # Add name to system prompt context (use sparingly, not in every message)
                            if first_name and msg.text:
                                msg.text = f"[Человека зовут {first_name}. Используй имя РЕДКО, только когда уместно.]\n\n{msg.text}"
                            elif first_name:
                                msg.text = f"[Человека зовут {first_name}. Используй имя РЕДКО, только когда уместно.]"

                            await telegram.send_typing(msg.user_id)
                            response = await agent.process(msg)

                        stranger_timestamps[uid].append(now)

                        # Send text response to stranger (no video circles for strangers)
                        await telegram.send(OutgoingMessage(user_id=msg.user_id, text=response))

                        # Notify owner about stranger message
                        if monitor_user:
                            raw = msg.raw
                            username = ""
                            first_name = ""
                            if raw and hasattr(raw, "from_user") and raw.from_user:
                                username = raw.from_user.username or ""
                                first_name = raw.from_user.first_name or ""
                            user_label = f"@{username}" if username else first_name or "unknown"
                            is_new = uid not in stranger_notified
                            stranger_notified.add(uid)
                            stranger_text = (msg.text or "")[:300]
                            bot_reply = (response or "")[:300]
                            header = "👤 Новый чужой пишет боту!" if is_new else f"👤 {user_label} пишет:"

                            alert = (
                                f"{header}\n\n"
                                f"Кто: {user_label} (ID: {uid})\n"
                                f"Написал: {stranger_text}\n\n"
                                f"Бот ответил: {bot_reply}"
                            )
                            await telegram.send(OutgoingMessage(user_id=monitor_user, text=alert))
                    except Exception as exc:
                        logger.warning("Stranger processing failed: %s", exc)
                    continue

                # --- Progress notification system ---
                status_msg_id: str | None = None
                tool_call_count: int = 0
                stage_sent: int = 0  # 0=none, 1=start, 2=20%, 3=50%, 4=80%
                is_research: bool = False
                typing_task: asyncio.Task | None = None  # noqa: UP031

                # Research progress: 4 stages mapped to tool call counts
                # Typical research: 8-12 tool calls over 4-6 iterations
                RESEARCH_STAGES = {
                    0: "Запускаю глубокий поиск в интернете. Это займет немного времени...",
                    2: "Нашел первые результаты, углубляюсь дальше...",
                    5: "Обрабатываю найденную информацию...",
                    8: "Почти готово, формирую ответ...",
                }
                # Generic (non-research) progress: multi-stage for long tool chains
                GENERIC_STAGES = {
                    3: "Обрабатываю, подожди немного...",
                    7: "Всё ещё работаю...",
                    12: "Сложная задача, ещё немного...",
                    18: "Почти готово...",
                }

                async def _keep_typing() -> None:
                    """Send typing indicator every 4s while agent is working."""
                    try:
                        while True:
                            try:
                                await telegram.send_typing(msg.user_id)
                            except Exception:
                                pass  # network hiccup — keep trying
                            await asyncio.sleep(4)
                    except asyncio.CancelledError:
                        pass

                async def _send_status(text: str) -> None:
                    """Send or update the status message."""
                    nonlocal status_msg_id
                    try:
                        if status_msg_id is None:
                            status_msg_id = await telegram.send(
                                OutgoingMessage(user_id=msg.user_id, text=text)
                            )
                        else:
                            await telegram.draft_update(
                                msg.user_id, status_msg_id, text
                            )
                    except Exception as e:
                        logger.debug("Progress update failed: %s", e)

                async def _progress(event: str, detail: dict) -> None:
                    nonlocal status_msg_id, tool_call_count, stage_sent, is_research

                    if event == "routed":
                        # Detect research queries by skill name
                        skill = detail.get("skill")
                        if skill in ("web_search", "research"):
                            is_research = True
                            stage_sent = 1
                            await _send_status(RESEARCH_STAGES[0])
                        return

                    if event == "tool_start":
                        tool_call_count += 1

                        if is_research:
                            # Research: update at 20%, 50%, 80%
                            if tool_call_count == 2 and stage_sent < 2:
                                stage_sent = 2
                                await _send_status(RESEARCH_STAGES[2])
                            elif tool_call_count == 5 and stage_sent < 3:
                                stage_sent = 3
                                await _send_status(RESEARCH_STAGES[5])
                            elif tool_call_count == 8 and stage_sent < 4:
                                stage_sent = 4
                                await _send_status(RESEARCH_STAGES[8])
                        else:
                            # Generic: multi-stage progress for long tool chains
                            if tool_call_count == 3 and stage_sent < 1:
                                stage_sent = 1
                                await _send_status(GENERIC_STAGES[3])
                            elif tool_call_count == 7 and stage_sent < 2:
                                stage_sent = 2
                                await _send_status(GENERIC_STAGES[7])
                            elif tool_call_count == 12 and stage_sent < 3:
                                stage_sent = 3
                                await _send_status(GENERIC_STAGES[12])
                            elif tool_call_count == 18 and stage_sent < 4:
                                stage_sent = 4
                                await _send_status(GENERIC_STAGES[18])
                        return

                    if event == "tool_progress":
                        # Periodic update during long-running tool (every 30s)
                        tool_name = detail.get("tool_name", "tool")
                        elapsed = detail.get("elapsed_seconds", 0)
                        minutes = elapsed // 60
                        seconds = elapsed % 60

                        if minutes > 0:
                            time_str = f"{minutes} мин {seconds} сек" if seconds > 0 else f"{minutes} мин"
                        else:
                            time_str = f"{seconds} сек"

                        # Different messages for different tools
                        if "research" in tool_name.lower():
                            text = f"🔍 Продолжаю глубокий поиск... (прошло {time_str})"
                        elif "search" in tool_name.lower():
                            text = f"🔎 Ищу информацию... (прошло {time_str})"
                        else:
                            text = f"⏳ Обрабатываю... (прошло {time_str})"

                        await _send_status(text)
                        return

                    if event == "done":
                        # Silently remove status message — result speaks for itself
                        if status_msg_id:
                            try:
                                await telegram.delete_message(
                                    msg.user_id, status_msg_id
                                )
                            except Exception:
                                pass
                        return

                # Start continuous typing indicator
                typing_task = asyncio.create_task(_keep_typing())

                # Set current user_id for TTS indicator (if agent decides to use TTS)
                if tts_tool.available:
                    tts_tool.set_current_user_id(msg.user_id)

                try:
                    # Process with agent (with live progress)
                    response = await agent.process(msg, progress=_progress)
                finally:
                    # Clear current user_id
                    if tts_tool.available:
                        tts_tool.set_current_user_id(None)

                    # Stop typing indicator
                    if typing_task:
                        typing_task.cancel()
                        try:
                            await typing_task
                        except asyncio.CancelledError:
                            pass

                # Send the response (skip if it's just a placeholder dot — tools-only response)
                has_files = bool(file_send_tool.pending_sends)
                has_video = bool(tts_tool.available and tts_tool.pending_video_notes)
                has_voice = bool(tts_tool.available and tts_tool.pending_voice)
                has_media = has_files or has_video or has_voice

                if response and response.strip() and response.strip() != ".":
                    await telegram.send(
                        OutgoingMessage(user_id=msg.user_id, text=response)
                    )
                elif not has_media and tool_call_count > 0:
                    # Bot worked (called tools) but produced no text and no media
                    # This happens when max_tool_iterations is hit — don't leave user in silence
                    await telegram.send(
                        OutgoingMessage(
                            user_id=msg.user_id,
                            text="Хм, не смог довести до конца с первого раза. Попробуй ещё раз или уточни задачу."
                        )
                    )

                # Send any queued files as Telegram attachments
                if file_send_tool.pending_sends:
                    _AUDIO_EXT = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}
                    for _fp in file_send_tool.pending_sends:
                        try:
                            file_path = _fp if isinstance(_fp, Path) else Path(str(_fp))
                            if file_path.suffix.lower() in _AUDIO_EXT:
                                await telegram.send_audio(
                                    msg.user_id, file_path,
                                    title=file_path.stem,
                                )
                            else:
                                await telegram.send_file(
                                    msg.user_id, file_path
                                )
                        except Exception as fe:
                            logger.error("Failed to send file %s: %s", file_path, fe)
                    file_send_tool.pending_sends.clear()

                # Send TTS video circles (кружочки)
                if tts_tool.available and tts_tool.pending_video_notes:
                    for vn_path in tts_tool.pending_video_notes:
                        try:
                            await telegram.send_video_note(msg.user_id, vn_path)
                        except Exception as ve:
                            logger.error("Failed to send video note: %s", ve)
                    tts_tool.pending_video_notes.clear()

                # Send TTS voice messages
                if tts_tool.available and tts_tool.pending_voice:
                    for voice_path in tts_tool.pending_voice:
                        try:
                            await telegram.send_voice(msg.user_id, voice_path)
                        except Exception as ve:
                            logger.error("Failed to send voice: %s", ve)
                    tts_tool.pending_voice.clear()

            except Exception as exc:
                logger.exception("Error processing message from %s", msg.user_id)
                error_type = type(exc).__name__
                error_brief = str(exc)[:200]
                error_msg = (
                    f"Ошибка: {error_type}: {error_brief}\n"
                    "Попробуй ещё раз или переформулируй запрос."
                )
                try:
                    await telegram.send(
                        OutgoingMessage(
                            user_id=msg.user_id,
                            text=error_msg,
                        )
                    )
                    # Save error context to history so bot knows what happened
                    agent._history[msg.user_id].append(
                        {"role": "user", "content": msg.text or "(message)"}
                    )
                    agent._history[msg.user_id].append(
                        {"role": "assistant", "content": error_msg}
                    )
                except Exception:
                    logger.exception("Failed to send error message")
            finally:
                _cleanup_temp_files(msg)
                queue.task_done()

    # 9. Initialize scheduler + monitors
    scheduler = Scheduler(timezone=config.scheduler_timezone)

    # 9a. Scheduler tools (reminders, recurring tasks)
    async def _sched_notify(user_id: str, text: str) -> None:
        await telegram.send(OutgoingMessage(user_id=user_id, text=text))

    scheduler_service = SchedulerService(
        scheduler=scheduler,
        notify=_sched_notify,
        user_id=monitor_user,
    )
    tool_registry.register(SchedulerAddTool(scheduler_service))
    tool_registry.register(SchedulerListTool(scheduler_service))
    tool_registry.register(SchedulerRemoveTool(scheduler_service))
    restored_reminders = scheduler_service.restore_jobs()
    logger.info(
        "Scheduler tools registered (3 tools, %d reminders restored)",
        restored_reminders,
    )

    if gmail_service.available:
        async def _email_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        email_monitor = EmailMonitor(
            gmail=gmail_service, notify=_email_notify, user_id=monitor_user,
        )
        scheduler.add_job(
            email_monitor.check,
            trigger="interval",
            minutes=config.email.check_interval_minutes,
            name="email_inbox_check",
        )
        logger.info("Email monitor scheduled (every %d min)", config.email.check_interval_minutes)

    # Crypto monitor — BTC price tracker, notify on $500+ movement
    async def _crypto_notify(user_id: str, text: str) -> None:
        await telegram.send(OutgoingMessage(user_id=user_id, text=text))

    crypto_monitor = CryptoMonitor(
        notify=_crypto_notify,
        user_id=monitor_user,
        threshold_usd=config.crypto.threshold_usd,
    )
    scheduler.add_job(
        crypto_monitor.check,
        trigger="interval",
        minutes=config.crypto.check_interval_minutes,
        name="crypto_btc_check",
    )
    logger.info(
        "Crypto monitor scheduled (every %d min, threshold $%.0f)",
        config.crypto.check_interval_minutes,
        config.crypto.threshold_usd,
    )

    # Nova Poshta parcel monitor — track active parcels, push on status change
    if config.novaposhta_api_key:
        async def _np_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        novaposhta_monitor = NovaPoshtaMonitor(
            api_key=config.novaposhta_api_key,
            notify=_np_notify,
            user_id=monitor_user,
        )
        scheduler.add_job(
            novaposhta_monitor.check,
            trigger="interval",
            minutes=config.novaposhta.check_interval_minutes,
            name="novaposhta_parcel_check",
        )
        logger.info(
            "Nova Poshta monitor scheduled (every %d min)",
            config.novaposhta.check_interval_minutes,
        )

    # Monobank transaction monitor — push on new transactions
    if mono_service:
        async def _mono_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        mono_monitor = MonobankMonitor(
            service=mono_service,
            notify=_mono_notify,
            user_id=monitor_user,
        )
        scheduler.add_job(
            mono_monitor.check,
            trigger="interval",
            minutes=config.monobank.check_interval_minutes,
            name="monobank_tx_check",
        )
        logger.info(
            "Monobank monitor scheduled (every %d min)",
            config.monobank.check_interval_minutes,
        )

    # Proxy health monitor — check every 2 min, notify on failures
    if config.claude_proxy_url:
        async def _proxy_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        proxy_monitor = ProxyMonitor(
            proxy_url=config.claude_proxy_url,
            notify_callback=_proxy_notify,
            user_id=monitor_user,
        )
        scheduler.add_job(
            proxy_monitor.check,
            trigger="interval",
            minutes=2,
            name="proxy_health_check",
        )
        logger.info("Proxy health monitor scheduled (every 2 min)")

        # Preventive token refresh — every 6 hours (tokens last ~8h)
        async def _preventive_token_refresh():
            try:
                from scripts.refresh_proxy_token import async_check_and_refresh
                refreshed = await async_check_and_refresh()
                if refreshed:
                    logger.info("Preventive token check passed")
            except Exception as e:
                logger.error("Preventive token refresh error: %s", e)

        scheduler.add_job(
            _preventive_token_refresh,
            trigger="interval",
            hours=6,
            name="proxy_token_refresh",
        )
        logger.info("Proxy token auto-refresh scheduled (every 6 hours)")

    # Subscription monitor — daily check at configured hour
    scheduler.add_job(
        sub_monitor.check,
        trigger="cron",
        hour=config.subscription.check_hour,
        name="subscription_daily_check",
    )
    logger.info(
        "Subscription monitor scheduled (daily at %02d:00, %d subs)",
        config.subscription.check_hour,
        len(sub_monitor.list_all()),
    )

    # NewsRadar monitor — crypto + AI/tech news digest
    async def _news_notify(user_id: str, text: str) -> None:
        await telegram.send(OutgoingMessage(user_id=user_id, text=text))

    news_radar_cfg = {
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
        "max_articles_total": config.news_radar.max_articles_total,
        "max_seen_urls": config.news_radar.max_seen_urls,
    }
    news_radar = NewsRadarMonitor(
        notify=_news_notify,
        llm_provider=provider,
        user_id=monitor_user,
        config=news_radar_cfg,
    )
    # Run first check shortly after startup (60s delay for other services to init),
    # then repeat every N hours. Without this, interval trigger waits the full
    # interval before first execution — and if the bot restarts frequently,
    # the check never fires.
    from datetime import datetime as _dt, timedelta

    _news_first_run = _dt.now() + timedelta(seconds=60)
    scheduler.add_job(
        news_radar.check,
        trigger="interval",
        hours=config.news_radar.check_interval_hours,
        next_run_time=_news_first_run,
        name="news_radar_digest",
    )
    logger.info(
        "NewsRadar monitor scheduled (every %d hours)",
        config.news_radar.check_interval_hours,
    )

    # TechRadar monitor — GitHub/HN/Reddit curated tech discoveries
    async def _tech_radar_notify(user_id: str, text: str) -> None:
        await telegram.send(OutgoingMessage(user_id=user_id, text=text))

    tech_radar = TechRadarMonitor(
        notify=_tech_radar_notify,
        llm_provider=provider,
        user_id=monitor_user,
    )
    _tech_first_run = _dt.now() + timedelta(minutes=10)
    scheduler.add_job(
        tech_radar.check,
        trigger="interval",
        hours=6,
        next_run_time=_tech_first_run,
        name="tech_radar_digest",
    )
    logger.info("TechRadar monitor scheduled (every 6 hours)")

    # Twitch monitor — streamer live notifications
    twitch_monitor = None
    if config.twitch_client_id and config.twitch_client_secret and config.twitch.streamers:
        async def _twitch_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        twitch_monitor = TwitchMonitor(
            notify=_twitch_notify,
            client_id=config.twitch_client_id,
            client_secret=config.twitch_client_secret,
            streamers=config.twitch.streamers,
            user_id=monitor_user,
        )
        tool_registry.register(TwitchStatusTool(twitch_monitor))
        scheduler.add_job(
            twitch_monitor.check,
            trigger="interval",
            minutes=config.twitch.check_interval_minutes,
            name="twitch_live_check",
        )
        logger.info(
            "Twitch monitor scheduled (every %d min, %d streamers)",
            config.twitch.check_interval_minutes,
            len(config.twitch.streamers),
        )

    # YouTube monitor — new video notifications from channels
    youtube_monitor = None
    if config.youtube_api_key:
        async def _yt_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        youtube_monitor = YouTubeMonitor(
            notify=_yt_notify,
            api_key=config.youtube_api_key,
            channels=config.youtube.channels,
            user_id=monitor_user,
            credentials_path=config.youtube.credentials_path,
            token_path=config.youtube.token_path,
        )
        # Public tools (API key + transcript)
        tool_registry.register(YouTubeSearchTool(youtube_monitor))
        tool_registry.register(YouTubeInfoTool(youtube_monitor))
        tool_registry.register(YouTubeSummaryTool(youtube_monitor))
        # OAuth tools (subscriptions, liked videos)
        if youtube_monitor.oauth_available:
            tool_registry.register(YouTubeSubscriptionsTool(youtube_monitor))
            tool_registry.register(YouTubeLikedTool(youtube_monitor))
            logger.info("YouTube OAuth tools registered (subscriptions, liked)")
            # Auto-sync subscriptions to channel monitor list
            if config.youtube.sync_subscriptions:
                try:
                    synced = await youtube_monitor.sync_subscriptions()
                    if synced:
                        logger.info("YouTube: synced %d channels from subscriptions", synced)
                except Exception as e:
                    logger.warning("YouTube subscription sync failed: %s", e)
        else:
            logger.info(
                "YouTube OAuth not configured — run: python -m src.monitors.youtube_monitor --setup"
            )
        # Schedule channel monitor if there are channels (config + synced)
        if youtube_monitor.channels:
            scheduler.add_job(
                youtube_monitor.check,
                trigger="interval",
                minutes=config.youtube.check_interval_minutes,
                name="youtube_new_videos",
            )
            logger.info(
                "YouTube monitor scheduled (every %d min, %d channels)",
                config.youtube.check_interval_minutes,
                len(youtube_monitor.channels),
            )
        else:
            logger.info("YouTube tools registered, no channels to monitor")

    # Heartbeat engine — autonomous tasks from HEARTBEAT.md
    if monitor_user:
        async def _heartbeat_agent(prompt: str) -> str:
            """Run a prompt through the agent as if the owner sent it."""
            from src.channels.base import IncomingMessage as _HBMsg
            hb_msg = _HBMsg(
                user_id=monitor_user,
                text=prompt,
                channel="heartbeat",
                message_id="heartbeat",
                is_owner=True,
            )
            return await agent.process(hb_msg)

        async def _heartbeat_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        heartbeat = HeartbeatEngine(
            agent_callback=_heartbeat_agent,
            notify_callback=_heartbeat_notify,
            user_id=monitor_user,
        )
        scheduler.add_job(
            heartbeat.run,
            trigger="interval",
            minutes=config.heartbeat_interval_minutes,
            name="heartbeat_tasks",
        )
        logger.info(
            "Heartbeat engine scheduled (every %d min)",
            config.heartbeat_interval_minutes,
        )

    # Autonomous Goal Pursuit — long-running background goals (apartments, cars, crypto entries)
    goal_engine = None
    if monitor_user:
        async def _goal_agent(prompt: str) -> str:
            """Run a goal check prompt through the agent."""
            from src.channels.base import IncomingMessage as _GoalMsg
            goal_msg = _GoalMsg(
                user_id=monitor_user,
                text=prompt,
                channel="goal_engine",
                message_id="goal_check",
                is_owner=True,
            )
            return await agent.process(goal_msg)

        async def _goal_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        goal_engine = GoalEngine(
            agent_callback=_goal_agent,
            notify_callback=_goal_notify,
            user_id=monitor_user,
        )
        tool_registry.register(GoalTool(goal_engine))
        # Check goals every 15 min — each goal has its own interval internally
        scheduler.add_job(
            goal_engine.check,
            trigger="interval",
            minutes=15,
            name="goal_pursuit_check",
        )
        active_goals = len(goal_engine.store.list_active())
        logger.info(
            "Goal Pursuit engine scheduled (check every 15 min, %d active goals)",
            active_goals,
        )

    # Morning briefing — data-driven daily digest (no LLM tokens!)
    if monitor_user and config.morning_briefing.enabled:
        async def _briefing_notify(user_id: str, text: str) -> None:
            await telegram.send(OutgoingMessage(user_id=user_id, text=text))

        morning_briefing = MorningBriefingMonitor(
            notify=_briefing_notify,
            user_id=monitor_user,
            city=config.weather.default_city,
            crypto_monitor=crypto_monitor,
            gmail_service=gmail_service,
            sub_monitor=sub_monitor,
        )
        scheduler.add_job(
            morning_briefing.send_briefing,
            trigger="cron",
            hour=config.morning_briefing.hour,
            minute=config.morning_briefing.minute,
            name="morning_briefing",
        )
        logger.info(
            "Morning briefing scheduled (daily at %02d:%02d, data-driven)",
            config.morning_briefing.hour,
            config.morning_briefing.minute,
        )

    scheduler.start()

    # 10. Restore conversation history from persistent memory
    if monitor_user:
        restored = await agent.restore_history(monitor_user, limit=3)
        logger.info("Restored %d conversation turns from memory", restored)

    # 11. Send startup notification to owner
    if monitor_user:
        tool_count = len(tool_registry.list_tools())
        skill_count = len(skill_registry.list_skills())
        monitors = []
        if gmail_service.available:
            monitors.append("Email")
        monitors.append("Crypto")
        if mono_service:
            monitors.append("Monobank")
        if sub_monitor.list_all():
            monitors.append(f"Subscriptions ({len(sub_monitor.list_all())})")
        if config.claude_proxy_url:
            monitors.append("Proxy")
        monitors.append(f"NewsRadar ({config.news_radar.check_interval_hours}h)")
        if twitch_monitor:
            monitors.append(f"Twitch ({len(config.twitch.streamers)} streamers)")
        if youtube_monitor and youtube_monitor.channels:
            oauth_tag = " +OAuth" if youtube_monitor.oauth_available else ""
            monitors.append(f"YouTube ({len(youtube_monitor.channels)} ch{oauth_tag})")
        elif youtube_monitor:
            monitors.append("YouTube (tools only)")
        from src.core.heartbeat import parse_heartbeat_file
        hb_tasks = parse_heartbeat_file()
        if hb_tasks:
            monitors.append(f"Heartbeat ({len(hb_tasks)} tasks, {config.heartbeat_interval_minutes}m)")
        if config.morning_briefing.enabled:
            monitors.append(f"MorningBriefing ({config.morning_briefing.hour:02d}:{config.morning_briefing.minute:02d})")
        if goal_engine and goal_engine.store.list_active():
            monitors.append(f"Goals ({len(goal_engine.store.list_active())} active)")
        monitors.append("MultiAgent")
        monitors_str = ", ".join(monitors)

        from src.tools.search_tool import get_tavily_pool
        _tpool = get_tavily_pool()
        tavily_info = f"Tavily: {_tpool.key_count} keys (auto-rotate)\n" if _tpool and _tpool.key_count > 1 else ""
        startup_msg = (
            f"Progressive Agent запущен!\n\n"
            f"LLM: {provider.name}\n"
            f"Tools: {tool_count}\n"
            f"Skills: {skill_count}\n"
            f"Monitors: {monitors_str}\n"
            f"{tavily_info}"
            f"History: {restored} msgs restored\n\n"
            f"Ready to work."
        )
        try:
            await telegram.send(
                OutgoingMessage(user_id=monitor_user, text=startup_msg)
            )
            logger.info("Startup notification sent to owner")
        except Exception as e:
            logger.warning("Failed to send startup notification: %s", e)

    # 12. Run everything
    logger.info("Starting message processing loop and Telegram bot...")

    processor_task = asyncio.create_task(process_messages())

    try:
        await telegram.start(queue)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        processor_task.cancel()
        try:
            await processor_task
        except asyncio.CancelledError:
            pass
        scheduler.stop()
        await telegram.stop()
        await cost_tracker.close()
        await memory.close()
        logger.info("Progressive Agent stopped")


if __name__ == "__main__":
    asyncio.run(main())
