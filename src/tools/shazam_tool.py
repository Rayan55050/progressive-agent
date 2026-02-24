"""
Shazam tool — music recognition from audio files.

Uses shazamio library (async, free, no API key needed).
Identifies songs from voice messages, audio files, or any audio.

pip install shazamio
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ShazamTool:
    """Recognize music from audio files using Shazam."""

    def __init__(self) -> None:
        self._shazam: Any = None

    def _ensure_client(self) -> Any:
        """Lazy-load shazamio on first use."""
        if self._shazam is None:
            from shazamio import Shazam
            self._shazam = Shazam()
            logger.info("Shazam client initialized")
        return self._shazam

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shazam",
            description=(
                "Recognize a song from an audio file (voice message, MP3, OGG, WAV). "
                "Returns song title, artist, album, and links. "
                "Use when user sends audio and asks 'what song is this?', "
                "'что за песня?', 'шазам', etc."
            ),
            parameters=[
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to audio file (OGG, MP3, WAV, etc.)",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        file_path: str = kwargs.get("file_path", "")
        if not file_path:
            return ToolResult(success=False, error="file_path is required")

        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        try:
            shazam = self._ensure_client()
            result = await shazam.recognize(str(path))

            track = result.get("track")
            if not track:
                return ToolResult(
                    success=True,
                    data={"recognized": False, "message": "Song not recognized. Try a clearer recording."},
                )

            title = track.get("title", "Unknown")
            artist = track.get("subtitle", "Unknown")
            album = ""
            genres = ""
            shazam_url = track.get("url", "")
            cover_art = ""
            release_year = ""

            # Extract metadata sections
            for section in track.get("sections", []):
                if section.get("type") == "SONG":
                    for meta in section.get("metadata", []):
                        if meta.get("title") == "Album":
                            album = meta.get("text", "")
                        elif meta.get("title") == "Released":
                            release_year = meta.get("text", "")
                        elif meta.get("title") == "Label":
                            pass  # skip label

            # Extract genres
            raw_genres = track.get("genres", {})
            if raw_genres and "primary" in raw_genres:
                genres = raw_genres["primary"]

            # Cover art
            images = track.get("images", {})
            if images:
                cover_art = images.get("coverarthq", images.get("coverart", ""))

            # External links (Spotify, Apple Music, etc.)
            links: dict[str, str] = {}
            for provider in track.get("hub", {}).get("providers", []):
                name = provider.get("type", "").capitalize()
                for action in provider.get("actions", []):
                    if action.get("uri"):
                        links[name] = action["uri"]

            # Build Tavily-like response for consistent formatting
            snippet_parts = [f"{artist}"]
            if album:
                snippet_parts.append(f"Album: {album}")
            if release_year:
                snippet_parts.append(f"Year: {release_year}")
            if genres:
                snippet_parts.append(f"Genre: {genres}")

            results = []
            if shazam_url:
                results.append({
                    "title": f"{artist} — {title}",
                    "url": shazam_url,
                    "snippet": ". ".join(snippet_parts),
                })

            for name, uri in links.items():
                if uri.startswith("http"):
                    results.append({
                        "title": f"{title} on {name}",
                        "url": uri,
                        "snippet": f"Listen on {name}",
                    })

            data = {
                "recognized": True,
                "title": title,
                "artist": artist,
                "album": album,
                "year": release_year,
                "genre": genres,
                "cover_art": cover_art,
                "answer": f"Song recognized: {artist} — {title}",
                "results": results,
            }

            logger.info("Shazam recognized: %s — %s", artist, title)
            return ToolResult(success=True, data=data)

        except Exception as e:
            logger.error("Shazam failed for %s: %s", file_path, e)
            return ToolResult(success=False, error=f"Shazam recognition failed: {e}")
