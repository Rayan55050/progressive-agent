"""
Media download tool — download videos/audio from YouTube, Twitter, etc.

Uses yt-dlp (100K+ GitHub stars, supports 1000+ sites).
Falls back gracefully if yt-dlp is not installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "downloads"

try:
    import yt_dlp

    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not installed — media download disabled. Install: pip install yt-dlp")

# Max file size (50MB for Telegram)
MAX_FILE_SIZE = 50 * 1024 * 1024


class MediaDownloadTool:
    """Download videos and audio from YouTube, Twitter, and 1000+ sites."""

    def __init__(self, pending_sends: list[Path] | None = None) -> None:
        self._pending_sends = pending_sends

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="media_download",
            description=(
                "Download videos or audio from YouTube, Twitter/X, Instagram, TikTok, "
                "SoundCloud, and 1000+ other sites using yt-dlp. "
                "Actions: 'video' — download video (MP4); "
                "'audio' — extract audio only (MP3); "
                "'info' — get video metadata without downloading. "
                "Downloaded files are auto-sent to Telegram."
            ),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL of the video/audio to download",
                    required=True,
                ),
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'video', 'audio', or 'info'",
                    required=False,
                    enum=["video", "audio", "info"],
                ),
                ToolParameter(
                    name="quality",
                    type="string",
                    description="Video quality: 'best', '720p', '480p', '360p'. Default: '720p' (fits Telegram 50MB limit)",
                    required=False,
                    enum=["best", "720p", "480p", "360p"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not YTDLP_AVAILABLE:
            return ToolResult(
                success=False,
                error="yt-dlp not installed. Run: pip install yt-dlp",
            )

        url = kwargs.get("url", "").strip()
        if not url:
            return ToolResult(success=False, error="URL is required")

        action = kwargs.get("action", "video").strip().lower()

        try:
            if action == "info":
                return await asyncio.to_thread(self._get_info, url)
            elif action == "audio":
                return await asyncio.to_thread(self._download_audio, url)
            elif action == "video":
                quality = kwargs.get("quality", "720p").strip().lower()
                return await asyncio.to_thread(self._download_video, url, quality)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("Media download error: %s", e)
            return ToolResult(success=False, error=f"Download error: {e}")

    def _get_info(self, url: str) -> ToolResult:
        """Get video metadata without downloading."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            return ToolResult(success=False, error=f"Cannot access URL: {e}")

        if not info:
            return ToolResult(success=False, error="No info found for URL")

        title = info.get("title", "?")
        duration = info.get("duration")
        uploader = info.get("uploader", "?")
        view_count = info.get("view_count")
        like_count = info.get("like_count")
        upload_date = info.get("upload_date", "")
        description = (info.get("description") or "")[:500]

        lines = [
            f"**{title}**",
            f"Channel: {uploader}",
        ]
        if duration:
            mins, secs = divmod(duration, 60)
            hours, mins = divmod(mins, 60)
            if hours:
                lines.append(f"Duration: {hours}h {mins}m {secs}s")
            else:
                lines.append(f"Duration: {mins}m {secs}s")
        if view_count:
            lines.append(f"Views: {view_count:,}")
        if like_count:
            lines.append(f"Likes: {like_count:,}")
        if upload_date:
            lines.append(f"Date: {upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}")
        if description:
            lines.append(f"\nDescription: {description}{'...' if len(info.get('description', '')) > 500 else ''}")

        return ToolResult(success=True, data="\n".join(lines))

    def _download_audio(self, url: str) -> ToolResult:
        """Download audio only (MP3)."""
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(DOWNLOAD_DIR / "%(title).80s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
            "max_filesize": MAX_FILE_SIZE,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            return ToolResult(success=False, error=f"Download failed: {e}")

        if not info:
            return ToolResult(success=False, error="Download returned no info")

        title = info.get("title", "audio")
        # Find the downloaded file (yt-dlp renames with post-processing)
        safe_title = self._safe_filename(title)[:80]
        candidates = list(DOWNLOAD_DIR.glob(f"{safe_title}*"))
        if not candidates:
            # Fallback: most recent file in download dir
            candidates = sorted(DOWNLOAD_DIR.iterdir(), key=os.path.getmtime, reverse=True)

        if candidates:
            found = candidates[0]
            file_size = found.stat().st_size
            if self._pending_sends is not None:
                self._pending_sends.append(found)  # Path object, not str
            return ToolResult(
                success=True,
                data=f"Audio downloaded: {title}\nFile: {found} ({file_size / 1024 / 1024:.1f} MB)\nWill be sent to Telegram.",
            )

        return ToolResult(success=True, data=f"Audio downloaded: {title} (file path unknown)")

    def _download_video(self, url: str, quality: str) -> ToolResult:
        """Download video (MP4)."""
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Format selection based on quality
        format_map = {
            "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "720p": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
            "480p": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
            "360p": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best",
        }

        opts = {
            "format": format_map.get(quality, format_map["720p"]),
            "outtmpl": str(DOWNLOAD_DIR / "%(title).80s.%(ext)s"),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "max_filesize": MAX_FILE_SIZE,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            return ToolResult(success=False, error=f"Download failed: {e}")

        if not info:
            return ToolResult(success=False, error="Download returned no info")

        title = info.get("title", "video")
        safe_title = self._safe_filename(title)[:80]
        candidates = list(DOWNLOAD_DIR.glob(f"{safe_title}*"))
        if not candidates:
            candidates = sorted(DOWNLOAD_DIR.iterdir(), key=os.path.getmtime, reverse=True)

        if candidates:
            found = candidates[0]
            file_size = found.stat().st_size
            if file_size > MAX_FILE_SIZE:
                return ToolResult(
                    success=True,
                    data=f"Video downloaded but too large for Telegram ({file_size / 1024 / 1024:.1f} MB > 50 MB).\nFile: {found}\nTry 'audio' action or lower quality.",
                )
            if self._pending_sends is not None:
                self._pending_sends.append(found)  # Path object, not str
            return ToolResult(
                success=True,
                data=f"Video downloaded: {title}\nFile: {found} ({file_size / 1024 / 1024:.1f} MB)\nWill be sent to Telegram.",
            )

        return ToolResult(success=True, data=f"Video downloaded: {title} (file path unknown)")

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Make filename safe for glob matching."""
        return "".join(c if c.isalnum() or c in " .-_" else "_" for c in name).strip()
