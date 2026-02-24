"""
Audio Capture tool — record system audio (what's playing in headphones/speakers).

Uses sounddevice + Stereo Mix (Realtek loopback, Windows WDM-KS).
Records N seconds of system audio to a WAV file for Shazam recognition.

Requirements:
- sounddevice (already installed)
- soundfile (for WAV writing)
- Stereo Mix enabled in Windows Sound Settings
  (Recording devices > right-click > Show Disabled > Enable Stereo Mix)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Default recording duration
DEFAULT_DURATION = 10  # seconds — enough for Shazam to recognize


class AudioCaptureTool:
    """Record system audio (loopback) for music recognition."""

    def __init__(self) -> None:
        self._stereo_mix_device: int | None = None
        self._initialized = False

    def _find_stereo_mix(self) -> int | None:
        """Find Stereo Mix device (Realtek loopback)."""
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            for i, d in enumerate(devs):
                if "Stereo Mix" in d["name"] and d["max_input_channels"] > 0:
                    logger.info("Found Stereo Mix: device %d — %s", i, d["name"])
                    return i
        except Exception as e:
            logger.error("Failed to enumerate audio devices: %s", e)
        return None

    def _ensure_device(self) -> int | None:
        """Lazy-init: find Stereo Mix device on first use."""
        if not self._initialized:
            self._stereo_mix_device = self._find_stereo_mix()
            self._initialized = True
        return self._stereo_mix_device

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="audio_capture",
            description=(
                "Record system audio (what's currently playing in headphones/speakers). "
                "Captures N seconds of audio from the system output. "
                "Use together with 'shazam' to identify what song is playing. "
                "Use when user asks: 'что сейчас играет?', 'запиши что играет', "
                "'шазам что в наушниках', 'record system audio'."
            ),
            parameters=[
                ToolParameter(
                    name="duration",
                    type="integer",
                    description="Recording duration in seconds (default: 10, max: 30)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        duration = min(int(kwargs.get("duration", DEFAULT_DURATION)), 30)
        if duration < 1:
            duration = DEFAULT_DURATION

        device = self._ensure_device()
        if device is None:
            return ToolResult(
                success=False,
                error=(
                    "Stereo Mix not found. Enable it: "
                    "Sound Settings → Recording → right-click → "
                    "Show Disabled Devices → Enable Stereo Mix"
                ),
            )

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._record, device, duration
            )
            return result
        except Exception as e:
            logger.exception("Audio capture failed")
            return ToolResult(success=False, error=f"Audio capture failed: {e}")

    @staticmethod
    def _record(device: int, duration: int) -> ToolResult:
        """Synchronous recording (runs in thread pool)."""
        import numpy as np
        import sounddevice as sd
        import soundfile as sf

        dev_info = sd.query_devices(device)
        samplerate = int(dev_info["default_samplerate"])
        channels = min(dev_info["max_input_channels"], 2)

        logger.info(
            "Recording %ds system audio (device=%d, sr=%d, ch=%d)",
            duration, device, samplerate, channels,
        )

        audio = sd.rec(
            frames=int(samplerate * duration),
            samplerate=samplerate,
            channels=channels,
            device=device,
            dtype="float32",
        )
        sd.wait()

        max_amp = float(np.max(np.abs(audio)))

        if max_amp < 0.001:
            return ToolResult(
                success=True,
                data={
                    "file_path": "",
                    "silent": True,
                    "message": (
                        "Recording is silent — nothing is playing. "
                        "Make sure audio is playing and Stereo Mix is not muted."
                    ),
                },
            )

        # Save to temp WAV
        temp_dir = Path(tempfile.mkdtemp())
        output_path = temp_dir / "system_audio.wav"
        sf.write(str(output_path), audio, samplerate)

        size_kb = output_path.stat().st_size / 1024
        logger.info(
            "System audio recorded: %s (%.1f KB, max_amp=%.4f)",
            output_path.name, size_kb, max_amp,
        )

        return ToolResult(
            success=True,
            data={
                "file_path": str(output_path),
                "duration": duration,
                "silent": False,
                "max_amplitude": round(max_amp, 4),
                "message": (
                    f"Recorded {duration}s of system audio. "
                    f"File: {output_path}. "
                    "Use shazam tool with this file_path to identify the song."
                ),
            },
        )
