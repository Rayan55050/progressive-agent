"""
Speech-to-Text tool using local faster-whisper.

Runs entirely on the local machine (CPU).
No API keys needed, no per-minute costs, privacy-first.
Converts audio files (OGG from Telegram voice messages, MP3, WAV) to text.

Model sizes:
- tiny: ~75MB, fastest, lower accuracy
- base: ~150MB, good balance for short voice messages
- small: ~500MB, better accuracy
- medium: ~1.5GB, high accuracy
- large-v3: ~3GB, best accuracy (recommended for mixed languages)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Model: "large-v3" for best accuracy with Ukrainian/Russian/mixed speech
DEFAULT_MODEL = "large-v3"


def _ensure_ffmpeg_in_path() -> None:
    """Add WinGet Links to PATH so faster-whisper can find ffmpeg on Windows."""
    if sys.platform != "win32":
        return
    winget_links = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"
    if winget_links.is_dir() and str(winget_links) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(winget_links) + os.pathsep + os.environ.get("PATH", "")
        logger.debug("Added WinGet Links to PATH: %s", winget_links)


class STTTool:
    """Speech-to-Text tool using local faster-whisper.

    Lazy-loads the model on first use to avoid slowing down startup.
    """

    def __init__(self, model_size: str = DEFAULT_MODEL, **_kwargs: Any) -> None:
        """Initialize the STT tool.

        Args:
            model_size: Whisper model size (tiny/base/small/medium/large-v3).
            **_kwargs: Ignored (backward compat with old api_key param).
        """
        self._model_size = model_size
        self._model: Any = None

    def _ensure_model(self) -> Any:
        """Lazy-load the whisper model on first use."""
        if self._model is None:
            _ensure_ffmpeg_in_path()
            from faster_whisper import WhisperModel

            logger.info(
                "Loading faster-whisper model '%s' (first use, may download)...",
                self._model_size,
            )
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
            )
            logger.info("faster-whisper model '%s' loaded", self._model_size)
        return self._model

    @property
    def definition(self) -> ToolDefinition:
        """Tool definition for LLM function calling."""
        return ToolDefinition(
            name="stt",
            description="Convert audio file to text using local Whisper model",
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
        """Transcribe an audio file to text.

        Args:
            **kwargs: Tool parameters.
                file_path (str): Path to the audio file (required).

        Returns:
            ToolResult with transcribed text on success, or error on failure.
        """
        file_path: str = kwargs.get("file_path", "")
        if not file_path:
            return ToolResult(success=False, error="file_path is required")

        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        try:
            model = self._ensure_model()

            # Run transcription in a thread to avoid blocking the event loop
            # (faster-whisper is CPU-bound, can take 5-10s for long audio)
            def _transcribe():
                segs, inf = model.transcribe(
                    str(path),
                    beam_size=5,
                    vad_filter=True,
                    word_timestamps=True,
                )
                txt = " ".join(seg.text.strip() for seg in segs)
                return txt, inf

            text, info = await asyncio.to_thread(_transcribe)

            logger.info(
                "STT transcribed %s: %d chars (lang=%s, prob=%.2f)",
                path.name, len(text),
                info.language, info.language_probability,
            )
            return ToolResult(success=True, data=text)
        except Exception as e:
            logger.error("STT failed for %s: %s", file_path, e)
            return ToolResult(success=False, error=f"STT failed: {e}")
