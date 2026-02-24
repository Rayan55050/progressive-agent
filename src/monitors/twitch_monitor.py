"""
Twitch monitor — notifies when followed streamers go live.

Uses Twitch Helix API with client_credentials (app access token).
Token auto-refreshes on expiry. Checks every N minutes.
State (who's live) persisted to disk so restarts don't re-notify.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/twitch_monitor_state.json")
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
STREAMS_URL = "https://api.twitch.tv/helix/streams"

_LIVE_TEMPLATES = [
    "🔴 *{name}* стримит!",
    "🎮 *{name}* в эфире!",
    "📺 *{name}* запустил стрим!",
    "🟣 *{name}* онлайн на Twitch!",
]


class TwitchMonitor:
    """Monitors Twitch streamers and notifies when they go live.

    Runs as a scheduled job via APScheduler (default: every 3 min).
    Uses Twitch Helix API with app access token (client_credentials).
    Token auto-refreshes when expired.

    State (currently live set) persisted to disk to avoid
    duplicate notifications on restart.
    """

    def __init__(
        self,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        client_id: str,
        client_secret: str,
        streamers: list[str],
        user_id: str = "",
    ) -> None:
        self._notify = notify
        self._client_id = client_id
        self._client_secret = client_secret
        self._streamers = [s.lower().strip() for s in streamers if s.strip()]
        self._user_id = user_id

        # Token state
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

        # Live tracking
        self._live_set: set[str] = set()  # logins currently live
        self._initialized = False
        self._consecutive_errors = 0

        self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._live_set = set(data.get("live_set", []))
                self._initialized = bool(data.get("initialized", False))
                if self._initialized:
                    logger.info(
                        "Twitch monitor state loaded: %d live", len(self._live_set)
                    )
        except Exception as e:
            logger.warning("Failed to load twitch monitor state: %s", e)

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "live_set": list(self._live_set),
                "initialized": self._initialized,
                "updated_at": int(time.time()),
            }
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save twitch monitor state: %s", e)

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _ensure_token(self, session: aiohttp.ClientSession) -> bool:
        """Get or refresh app access token. Returns True if valid."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return True

        try:
            async with session.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.error("Twitch token request failed: HTTP %d", resp.status)
                    return False
                data = await resp.json()
                self._access_token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                logger.info("Twitch app token refreshed (expires in %ds)", data.get("expires_in", 0))
                return True
        except Exception as e:
            logger.error("Twitch token request error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Stream checking
    # ------------------------------------------------------------------

    async def _fetch_live_streams(
        self, session: aiohttp.ClientSession
    ) -> dict[str, dict[str, Any]] | None:
        """Fetch currently live streams for monitored streamers.

        Returns dict: {login: stream_data} or None on error.
        Twitch allows max 100 user_login params per request.
        """
        if not await self._ensure_token(session):
            return None

        headers = {
            "Client-ID": self._client_id,
            "Authorization": f"Bearer {self._access_token}",
        }
        params = [("user_login", s) for s in self._streamers]

        try:
            async with session.get(
                STREAMS_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    # Token expired — force refresh
                    self._access_token = ""
                    logger.warning("Twitch token expired, will refresh next cycle")
                    return None
                if resp.status != 200:
                    logger.warning("Twitch streams API HTTP %d", resp.status)
                    return None
                data = await resp.json()

            result: dict[str, dict[str, Any]] = {}
            for stream in data.get("data", []):
                login = stream.get("user_login", "").lower()
                if login:
                    result[login] = {
                        "display_name": stream.get("user_name", login),
                        "title": stream.get("title", ""),
                        "game": stream.get("game_name", ""),
                        "viewers": stream.get("viewer_count", 0),
                        "started_at": stream.get("started_at", ""),
                    }
            return result
        except Exception as e:
            logger.warning("Twitch streams fetch failed: %s", e)
            return None

    def _format_notification(self, login: str, info: dict[str, Any]) -> str:
        """Build notification for a streamer going live."""
        import random

        name = info.get("display_name", login)
        template = random.choice(_LIVE_TEMPLATES)
        lines = [template.format(name=name)]

        title = info.get("title", "")
        if title:
            lines.append(f"📝 {title}")

        game = info.get("game", "")
        if game:
            lines.append(f"🎮 {game}")

        viewers = info.get("viewers", 0)
        if viewers:
            lines.append(f"👥 {viewers:,} зрителей")

        lines.append(f"\n🔗 [Смотреть](https://twitch.tv/{login})")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main check (called by scheduler)
    # ------------------------------------------------------------------

    async def check(self) -> None:
        """Check which streamers are live and notify about new ones."""
        if not self._streamers:
            return

        if not self._client_id or not self._client_secret:
            logger.warning("Twitch credentials not configured, skipping check")
            return

        async with aiohttp.ClientSession() as session:
            live_data = await self._fetch_live_streams(session)

        if live_data is None:
            self._consecutive_errors += 1
            if self._consecutive_errors >= 5:
                logger.error(
                    "Twitch monitor: %d consecutive failures",
                    self._consecutive_errors,
                )
            return

        self._consecutive_errors = 0
        current_live = set(live_data.keys())

        # First run — baseline, don't notify
        if not self._initialized:
            self._live_set = current_live
            self._initialized = True
            self._save_state()
            if current_live:
                logger.info(
                    "Twitch monitor initialized: %s live",
                    ", ".join(current_live),
                )
            else:
                logger.info("Twitch monitor initialized: nobody live")
            return

        # Find who just went live
        newly_live = current_live - self._live_set

        if newly_live and self._user_id:
            for login in newly_live:
                info = live_data[login]
                text = self._format_notification(login, info)
                try:
                    await self._notify(self._user_id, text)
                    logger.info("Twitch notification sent: %s is live", login)
                except Exception as e:
                    logger.error("Failed to send twitch notification for %s: %s", login, e)

        # Update state
        self._live_set = current_live
        self._save_state()

    async def get_live_now(self) -> list[dict[str, Any]]:
        """On-demand check: who's live right now? Returns list of stream info dicts."""
        if not self._streamers or not self._client_id or not self._client_secret:
            return []

        async with aiohttp.ClientSession() as session:
            live_data = await self._fetch_live_streams(session)

        if live_data is None:
            return []

        result = []
        for login, info in live_data.items():
            result.append({
                "login": login,
                "display_name": info.get("display_name", login),
                "title": info.get("title", ""),
                "game": info.get("game", ""),
                "viewers": info.get("viewers", 0),
                "url": f"https://twitch.tv/{login}",
            })
        return result

    @property
    def streamers(self) -> list[str]:
        """List of monitored streamer logins."""
        return list(self._streamers)

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "streamers_monitored": len(self._streamers),
            "streamers": self._streamers,
            "currently_live": list(self._live_set),
            "initialized": self._initialized,
            "consecutive_errors": self._consecutive_errors,
            "has_token": bool(self._access_token),
        }
