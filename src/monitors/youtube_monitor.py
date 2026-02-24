"""
YouTube monitor — track new videos from subscribed channels.

Uses YouTube Data API v3 (API key for public data, OAuth2 for personal data).
Efficient: uses playlistItems.list (1 unit/call) instead of search (100 units/call).
Daily quota: 10,000 units. With 20 channels checked every 30 min = ~960 units/day.

OAuth2 setup (optional, for subscriptions):
1. Use same gmail_credentials.json (OAuth client)
2. Run: python -m src.monitors.youtube_monitor --setup
3. Authorize with your YouTube Google account in browser
4. Token saved to data/youtube_token.json (separate from Gmail)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# YouTube OAuth2 scope: read-only access to subscriptions, playlists, liked videos
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

STATE_FILE = Path("data/youtube_monitor_state.json")

_NEW_VIDEO_TEMPLATES = [
    "Новое видео на YouTube!",
    "Свежак на YouTube!",
    "Вышло новое видео!",
    "YouTube обновление!",
]


class YouTubeMonitor:
    """Monitor YouTube channels for new video uploads.

    Uses playlistItems.list to check each channel's uploads playlist.
    First run = baseline (saves current videos, no notifications).
    """

    def __init__(
        self,
        notify: Any,  # async (user_id: str, text: str) -> None
        api_key: str,
        channels: list[str],
        user_id: str,
        credentials_path: str = "config/gmail_credentials.json",
        token_path: str = "data/youtube_token.json",
    ) -> None:
        self._notify = notify
        self._api_key = api_key
        self._channels = list(channels)  # channel IDs or @handles
        self._user_id = user_id
        self._initialized = False
        self._consecutive_errors = 0

        # OAuth2 paths (for subscriptions / personal data)
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._yt_service: Any = None

        # State: channel_id -> {uploads_playlist_id, seen_video_ids, channel_title}
        self._state: dict[str, dict[str, Any]] = {}
        # Resolved channel IDs (handle -> ID mapping)
        self._resolved_ids: dict[str, str] = {}

        self._load_state()

    def _load_state(self) -> None:
        """Load persistent state from JSON file."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._state = data.get("channels", {})
                self._resolved_ids = data.get("resolved_ids", {})
                self._initialized = data.get("initialized", False)
                logger.info(
                    "YouTube monitor state loaded: %d channels, initialized=%s",
                    len(self._state),
                    self._initialized,
                )
            except Exception as e:
                logger.error("Failed to load YouTube state: %s", e)

    def _save_state(self) -> None:
        """Persist state to JSON file."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "channels": self._state,
                "resolved_ids": self._resolved_ids,
                "initialized": self._initialized,
            }
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save YouTube state: %s", e)

    async def _resolve_channel_id(
        self, session: aiohttp.ClientSession, channel_ref: str
    ) -> str | None:
        """Resolve @handle or channel URL to channel ID.

        Accepts:
        - UC... channel ID (returned as-is)
        - @handle
        - Full URL (extracts channel ID or handle)
        """
        # Already a channel ID
        if channel_ref.startswith("UC") and len(channel_ref) == 24:
            return channel_ref

        # Check cache
        if channel_ref in self._resolved_ids:
            return self._resolved_ids[channel_ref]

        # Extract handle from URL
        handle = channel_ref
        if "youtube.com" in channel_ref:
            # https://www.youtube.com/@handle or /channel/UCxxx
            match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{22})", channel_ref)
            if match:
                cid = match.group(1)
                self._resolved_ids[channel_ref] = cid
                return cid
            match = re.search(r"/@([a-zA-Z0-9_.-]+)", channel_ref)
            if match:
                handle = f"@{match.group(1)}"

        # Ensure handle starts with @
        if not handle.startswith("@"):
            handle = f"@{handle}"

        # Resolve via channels.list (forHandle) — 1 unit
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "id,snippet",
            "forHandle": handle.lstrip("@"),
            "key": self._api_key,
        }
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error("YouTube channels.list failed for %s: %d", handle, resp.status)
                    return None
                data = await resp.json()
                items = data.get("items", [])
                if not items:
                    logger.warning("YouTube channel not found: %s", handle)
                    return None
                cid = items[0]["id"]
                self._resolved_ids[channel_ref] = cid
                logger.info("Resolved YouTube %s -> %s", handle, cid)
                return cid
        except Exception as e:
            logger.error("Failed to resolve YouTube channel %s: %s", handle, e)
            return None

    async def _get_uploads_playlist(
        self, session: aiohttp.ClientSession, channel_id: str
    ) -> tuple[str | None, str]:
        """Get the 'uploads' playlist ID for a channel. Returns (playlist_id, channel_title)."""
        # Check cache
        if channel_id in self._state and self._state[channel_id].get("uploads_playlist_id"):
            return (
                self._state[channel_id]["uploads_playlist_id"],
                self._state[channel_id].get("channel_title", ""),
            )

        # The uploads playlist ID is always "UU" + channel_id[2:]
        # This is a YouTube convention, no API call needed
        uploads_id = "UU" + channel_id[2:]

        # But we still need the channel title — 1 unit
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "snippet",
            "id": channel_id,
            "key": self._api_key,
        }
        title = channel_id
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("items", [])
                    if items:
                        title = items[0]["snippet"]["title"]
        except Exception as e:
            logger.debug("Failed to get channel title for %s: %s", channel_id, e)

        return uploads_id, title

    async def _fetch_latest_videos(
        self, session: aiohttp.ClientSession, playlist_id: str, max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Fetch latest videos from an uploads playlist. Returns list of video info dicts."""
        url = "https://www.googleapis.com/youtube/v3/playlistItems"
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": max_results,
            "key": self._api_key,
        }
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        "YouTube playlistItems failed for %s: %d %s",
                        playlist_id, resp.status, error_text[:200],
                    )
                    return []
                data = await resp.json()
                videos = []
                for item in data.get("items", []):
                    snippet = item.get("snippet", {})
                    content = item.get("contentDetails", {})
                    video_id = content.get("videoId", "")
                    if not video_id:
                        continue
                    videos.append({
                        "video_id": video_id,
                        "title": snippet.get("title", ""),
                        "channel_title": snippet.get("channelTitle", ""),
                        "published_at": content.get("videoPublishedAt", ""),
                        "description": (snippet.get("description", "") or "")[:300],
                        "url": f"https://youtu.be/{video_id}",
                    })
                return videos
        except Exception as e:
            logger.error("Failed to fetch playlist %s: %s", playlist_id, e)
            return []

    def _format_notification(self, video: dict[str, Any]) -> str:
        """Format a new video notification for Telegram."""
        header = random.choice(_NEW_VIDEO_TEMPLATES)
        title = video.get("title", "Untitled")
        channel = video.get("channel_title", "Unknown")
        url = video.get("url", "")
        desc = video.get("description", "")

        # Truncate description
        if desc and len(desc) > 200:
            desc = desc[:200] + "..."

        lines = [
            header,
            "",
            f"📺 *{channel}*",
            f"🎬 {title}",
        ]
        if desc:
            lines.append(f"📝 {desc}")
        lines.append(f"🔗 {url}")
        return "\n".join(lines)

    async def check(self) -> None:
        """Main monitor check — called by scheduler."""
        if not self._api_key or not self._channels:
            return

        try:
            async with aiohttp.ClientSession() as session:
                for channel_ref in self._channels:
                    # Resolve channel ID
                    channel_id = await self._resolve_channel_id(session, channel_ref)
                    if not channel_id:
                        continue

                    # Get uploads playlist
                    playlist_id, channel_title = await self._get_uploads_playlist(
                        session, channel_id
                    )
                    if not playlist_id:
                        continue

                    # Fetch latest videos
                    videos = await self._fetch_latest_videos(session, playlist_id)
                    if not videos:
                        continue

                    # Initialize state for this channel if needed
                    if channel_id not in self._state:
                        self._state[channel_id] = {
                            "uploads_playlist_id": playlist_id,
                            "channel_title": channel_title,
                            "seen_video_ids": [],
                        }

                    state = self._state[channel_id]
                    state["uploads_playlist_id"] = playlist_id
                    state["channel_title"] = channel_title
                    seen = set(state.get("seen_video_ids", []))

                    if not self._initialized:
                        # First run: save all current videos as seen (no notifications)
                        state["seen_video_ids"] = [v["video_id"] for v in videos]
                        continue

                    # Check for new videos
                    new_videos = [v for v in videos if v["video_id"] not in seen]

                    for video in new_videos:
                        if self._user_id:
                            try:
                                text = self._format_notification(video)
                                await self._notify(self._user_id, text)
                                logger.info(
                                    "YouTube notification: %s — %s",
                                    video.get("channel_title"),
                                    video.get("title"),
                                )
                            except Exception as e:
                                logger.error("Failed to send YouTube notification: %s", e)
                        # Mark as seen AFTER successful notify (or if no user_id)
                        seen.add(video["video_id"])

                    # Keep last 50 video IDs per channel, preserving order
                    existing_ids = state.get("seen_video_ids", [])
                    new_ids = [v["video_id"] for v in new_videos if v["video_id"] in seen]
                    ordered = existing_ids + new_ids
                    state["seen_video_ids"] = ordered[-50:]

            # Mark as initialized after first full cycle
            if not self._initialized:
                self._initialized = True
                total_seen = sum(
                    len(s.get("seen_video_ids", []))
                    for s in self._state.values()
                )
                logger.info(
                    "YouTube monitor initialized: %d channels, %d videos baselined",
                    len(self._state),
                    total_seen,
                )

            self._consecutive_errors = 0
            self._save_state()

        except Exception as e:
            self._consecutive_errors += 1
            logger.error(
                "YouTube monitor check failed (attempt %d): %s",
                self._consecutive_errors, e,
            )

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search YouTube for videos. Returns list of video info dicts.

        Costs 100 units per call — use sparingly.
        """
        if not self._api_key:
            return []

        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": self._api_key,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.error("YouTube search failed: %d", resp.status)
                        return []
                    data = await resp.json()
                    results = []
                    for item in data.get("items", []):
                        snippet = item.get("snippet", {})
                        video_id = item.get("id", {}).get("videoId", "")
                        if not video_id:
                            continue
                        results.append({
                            "video_id": video_id,
                            "title": snippet.get("title", ""),
                            "channel_title": snippet.get("channelTitle", ""),
                            "published_at": snippet.get("publishedAt", ""),
                            "description": (snippet.get("description", "") or "")[:300],
                            "url": f"https://youtu.be/{video_id}",
                            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                        })
                    return results
        except Exception as e:
            logger.error("YouTube search failed: %s", e)
            return []

    async def get_video_info(self, video_id: str) -> dict[str, Any] | None:
        """Get detailed info about a specific video. Costs 1 unit."""
        if not self._api_key:
            return None

        # Extract video ID from URL if needed
        video_id = self._extract_video_id(video_id)
        if not video_id:
            return None

        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": self._api_key,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    items = data.get("items", [])
                    if not items:
                        return None

                    item = items[0]
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    content = item.get("contentDetails", {})

                    return {
                        "video_id": video_id,
                        "title": snippet.get("title", ""),
                        "channel_title": snippet.get("channelTitle", ""),
                        "channel_id": snippet.get("channelId", ""),
                        "published_at": snippet.get("publishedAt", ""),
                        "description": snippet.get("description", ""),
                        "duration": content.get("duration", ""),
                        "views": int(stats.get("viewCount") or 0),
                        "likes": int(stats.get("likeCount") or 0),
                        "comments": int(stats.get("commentCount") or 0),
                        "url": f"https://youtu.be/{video_id}",
                        "thumbnail": snippet.get("thumbnails", {}).get("maxres", snippet.get("thumbnails", {}).get("high", {})).get("url", ""),
                    }
        except Exception as e:
            logger.error("YouTube video info failed for %s: %s", video_id, e)
            return None

    async def get_transcript(
        self, video_ref: str, languages: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch video transcript (subtitles) for summarization.

        Uses youtube-transcript-api (no API key needed, no quota cost).
        Returns {video_id, title, transcript, language, char_count}.
        """
        video_id = self._extract_video_id(video_ref)
        if not video_id:
            return {"error": "Invalid video URL or ID"}

        # Preferred languages: Ukrainian, Russian, English, then auto-generated
        if languages is None:
            languages = ["uk", "ru", "en"]

        def _fetch() -> dict[str, Any]:
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt_api = YouTubeTranscriptApi()

            # Try direct fetch with language preferences (v1.0.0+ API)
            try:
                fetched = ytt_api.fetch(video_id, languages=languages)
                full_text = " ".join(
                    snippet.text.strip() for snippet in fetched
                )
                lang_used = fetched.language_code
            except Exception:
                # Fallback: list all transcripts and take any available
                try:
                    transcript_list = ytt_api.list(video_id)
                    selected = None
                    for t in transcript_list:
                        if t.is_generated:
                            selected = t
                            break
                    if selected is None:
                        for t in transcript_list:
                            selected = t
                            break
                    if selected is None:
                        return {"error": "Субтитры недоступны для этого видео"}

                    fetched = selected.fetch()
                    full_text = " ".join(
                        snippet.text.strip() for snippet in fetched
                    )
                    lang_used = selected.language_code
                except Exception as e:
                    return {"error": f"Субтитры недоступны: {e}"}

            # Trim to ~15000 chars (~4000 tokens) to keep LLM context reasonable
            if len(full_text) > 15000:
                full_text = full_text[:15000] + "... [обрезано]"

            return {
                "video_id": video_id,
                "transcript": full_text,
                "language": lang_used,
                "char_count": len(full_text),
            }

        result = await asyncio.to_thread(_fetch)

        # Enrich with video title if we have API key
        if "error" not in result and self._api_key:
            info = await self.get_video_info(video_id)
            if info:
                result["title"] = info.get("title", "")
                result["channel_title"] = info.get("channel_title", "")
                result["duration"] = info.get("duration", "")
                result["url"] = info.get("url", f"https://youtu.be/{video_id}")

        return result

    @staticmethod
    def _extract_video_id(ref: str) -> str:
        """Extract video ID from URL or return as-is if already an ID."""
        if not ref:
            return ""

        # Already a video ID (11 chars, alphanumeric + - _)
        if re.match(r"^[a-zA-Z0-9_-]{11}$", ref):
            return ref

        # youtu.be/VIDEO_ID
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", ref)
        if match:
            return match.group(1)

        # youtube.com/watch?v=VIDEO_ID
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", ref)
        if match:
            return match.group(1)

        # youtube.com/embed/VIDEO_ID
        match = re.search(r"/embed/([a-zA-Z0-9_-]{11})", ref)
        if match:
            return match.group(1)

        return ref

    @property
    def channels(self) -> list[str]:
        """List of monitored channel references."""
        return list(self._channels)

    # ---------- OAuth2 (subscriptions, personal data) ----------

    @property
    def oauth_available(self) -> bool:
        """Check if YouTube OAuth token exists."""
        return self._token_path.exists()

    def _get_youtube_service(self) -> Any:
        """Get or create YouTube API service via OAuth2 (synchronous)."""
        if self._yt_service is not None:
            return self._yt_service

        if not self._token_path.exists():
            logger.warning(
                "YouTube OAuth not configured. Run: python -m src.monitors.youtube_monitor --setup"
            )
            return None

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds: Credentials | None = None

        creds = Credentials.from_authorized_user_file(
            str(self._token_path), YOUTUBE_SCOPES
        )

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._token_path.write_text(creds.to_json())
                logger.info("YouTube OAuth token refreshed")
            except Exception as e:
                logger.error("YouTube token refresh failed: %s", e)
                creds = None

        if not creds or not creds.valid:
            logger.warning(
                "YouTube OAuth token invalid. Run: python -m src.monitors.youtube_monitor --setup"
            )
            return None

        self._yt_service = build("youtube", "v3", credentials=creds)
        logger.info("YouTube OAuth service initialized")
        return self._yt_service

    async def _yt_svc(self) -> Any:
        """Get YouTube OAuth service in async context."""
        return await asyncio.to_thread(self._get_youtube_service)

    async def get_subscriptions(self, max_results: int = 50) -> list[dict[str, Any]]:
        """Fetch user's YouTube subscriptions via OAuth.

        Returns list of {channel_id, channel_title, description, thumbnail}.
        """
        service = await self._yt_svc()
        if not service:
            return []

        subscriptions: list[dict[str, Any]] = []
        page_token: str | None = None

        try:
            while True:
                request = service.subscriptions().list(
                    part="snippet",
                    mine=True,
                    maxResults=min(max_results - len(subscriptions), 50),
                    pageToken=page_token,
                )
                response = await asyncio.to_thread(request.execute)

                for item in response.get("items", []):
                    snippet = item.get("snippet", {})
                    res = snippet.get("resourceId", {})
                    channel_id = res.get("channelId", "")
                    if not channel_id:
                        continue
                    subscriptions.append({
                        "channel_id": channel_id,
                        "channel_title": snippet.get("title", ""),
                        "description": (snippet.get("description", "") or "")[:200],
                        "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    })

                    if len(subscriptions) >= max_results:
                        break

                page_token = response.get("nextPageToken")
                if not page_token or len(subscriptions) >= max_results:
                    break

            logger.info("Fetched %d YouTube subscriptions", len(subscriptions))
            return subscriptions

        except Exception as e:
            logger.error("Failed to fetch YouTube subscriptions: %s", e)
            return []

    async def get_liked_videos(self, max_results: int = 20) -> list[dict[str, Any]]:
        """Fetch user's liked videos via OAuth.

        Returns list of {video_id, title, channel_title, url}.
        """
        service = await self._yt_svc()
        if not service:
            return []

        try:
            request = service.videos().list(
                part="snippet,statistics",
                myRating="like",
                maxResults=max_results,
            )
            response = await asyncio.to_thread(request.execute)

            videos = []
            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                video_id = item.get("id", "")
                videos.append({
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "url": f"https://youtu.be/{video_id}",
                })
            return videos

        except Exception as e:
            logger.error("Failed to fetch liked videos: %s", e)
            return []

    async def sync_subscriptions(self) -> int:
        """Sync monitored channels with user's YouTube subscriptions.

        Replaces the channel list with current subscriptions.
        Removes stale channels from state that are no longer subscribed.
        Returns total number of channels after sync.
        """
        subs = await self.get_subscriptions(max_results=200)
        if not subs:
            return 0

        sub_ids = {sub["channel_id"] for sub in subs}

        # Replace channels list with current subscriptions
        self._channels = list(sub_ids)

        # Clean state: remove channels no longer in subscriptions
        stale = [cid for cid in self._state if cid not in sub_ids]
        for cid in stale:
            title = self._state[cid].get("channel_title", cid)
            del self._state[cid]
            logger.info("Removed unsubscribed channel from state: %s", title)

        if stale:
            self._save_state()
            logger.info(
                "Cleaned %d unsubscribed channels from state", len(stale),
            )

        logger.info(
            "YouTube subscriptions synced: %d channels", len(self._channels),
        )
        return len(self._channels)

    @classmethod
    def run_setup(
        cls,
        credentials_path: str = "config/gmail_credentials.json",
        token_path: str = "data/youtube_token.json",
    ) -> bool:
        """Interactive OAuth2 setup — run from terminal.

        Opens browser for Google authorization (YouTube account).
        Saves token to token_path.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds_path = Path(credentials_path)
        tok_path = Path(token_path)

        if not creds_path.exists():
            print(
                f"ERROR: Credentials file not found: {creds_path}\n"
                "Use the same gmail_credentials.json from Gmail setup.\n"
                "If you don't have it:\n"
                "  1. Go to https://console.cloud.google.com/apis/credentials\n"
                "  2. Create OAuth 2.0 Client ID (Desktop application)\n"
                "  3. Download JSON and save as config/gmail_credentials.json"
            )
            return False

        print("YouTube OAuth Setup")
        print("=" * 40)
        print("A browser window will open.")
        print("Log in with your YOUTUBE Google account")
        print("(can be different from Gmail account).\n")

        flow = InstalledAppFlow.from_client_secrets_file(
            str(creds_path), YOUTUBE_SCOPES
        )
        creds = flow.run_local_server(port=0)

        tok_path.parent.mkdir(parents=True, exist_ok=True)
        tok_path.write_text(creds.to_json())
        print(f"\nYouTube authorized! Token saved to {tok_path}")
        print("Now restart the bot — subscriptions will sync automatically.")
        return True

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "channels_configured": len(self._channels),
            "channels_resolved": len(self._state),
            "initialized": self._initialized,
            "consecutive_errors": self._consecutive_errors,
            "has_api_key": bool(self._api_key),
            "has_oauth": self.oauth_available,
            "channel_details": {
                cid: {
                    "title": s.get("channel_title", ""),
                    "videos_seen": len(s.get("seen_video_ids", [])),
                }
                for cid, s in self._state.items()
            },
        }


# ---------- CLI entry point ----------

def _cli_main() -> None:
    """CLI entry point for YouTube OAuth setup."""
    if "--setup" in sys.argv:
        YouTubeMonitor.run_setup()
    else:
        print("Usage: python -m src.monitors.youtube_monitor --setup")
        print("  Runs OAuth2 authorization for YouTube (subscriptions, liked videos)")


if __name__ == "__main__":
    _cli_main()
