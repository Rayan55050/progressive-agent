"""
TTS Tool — Text-to-Speech with animated Telegram video circles.

Primary: OpenAI TTS (tts-1-hd) — natural human-like voice.
Fallback: edge-tts (free Microsoft TTS).

Video circles: frame-by-frame animated robot face with lip-sync,
eye blinking, breathing, and eyebrow movement — all synced to
speech audio amplitude.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import shutil
import struct
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


def _clean_text_for_tts(text: str) -> str:
    """Remove emojis and special characters that TTS shouldn't pronounce."""
    # Remove markdown bold/italic markers
    text = re.sub(r'\*\*?|__|~~', '', text)

    # Remove emojis and other unicode symbols
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)

    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


# ── Provider checks ──────────────────────────────────────────────

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ── Voice maps ───────────────────────────────────────────────────

OPENAI_VOICES: dict[str, str] = {
    "onyx": "onyx",        # deep male, authoritative
    "echo": "echo",        # male, warm
    "fable": "fable",      # male, British
    "alloy": "alloy",      # neutral
    "nova": "nova",        # female, warm
    "shimmer": "shimmer",  # female, clear
}

# Edge-TTS voices (free) — best available neural voices
# Multilingual voices (Andrew, Brian, Ava, Emma) are newest generation:
# they speak Russian naturally despite being "en-US" voices.
EDGE_VOICES: dict[str, str] = {
    # Multilingual (newest, most natural — speak ANY language including Russian)
    "brian": "en-US-BrianMultilingualNeural",   # male, deep, very natural
    "andrew": "en-US-AndrewMultilingualNeural",  # male, warm, natural
    "ava": "en-US-AvaMultilingualNeural",        # female, natural
    "emma": "en-US-EmmaMultilingualNeural",      # female, warm
    # Russian-dedicated (standard neural)
    "ru-male": "ru-RU-DmitryNeural",
    "ru-female": "ru-RU-SvetlanaNeural",
    # English-dedicated
    "en-male": "en-US-GuyNeural",
    "en-female": "en-US-JennyNeural",
    # Ukrainian
    "uk-male": "uk-UA-OstapNeural",
    "uk-female": "uk-UA-PolinaNeural",
}

EDGE_DEFAULT_VOICE = "en-US-BrianMultilingualNeural"

# ── Constants ────────────────────────────────────────────────────

MAX_VIDEO_NOTE_CHARS = 800  # ~60 seconds of speech
VIDEO_SIZE = 384            # Telegram video note diameter (pixels)
FPS = 25                    # video frame rate
BLINK_DURATION_S = 0.24     # eye blink duration (seconds)

# Face geometry (pixels, relative to 384×384 canvas)
HEAD_RX, HEAD_RY = 135, 150
EYE_SPACING = 55             # horizontal distance from center to each eye
EYE_Y_OFF = -40              # eyes above head center
EYE_RX, EYE_RY = 26, 22     # eye ellipse radii (fully open)
MOUTH_Y_OFF = 50             # mouth below head center
MOUTH_HW = 35                # mouth half-width
MOUTH_MAX_H = 20             # max mouth opening height


class TTSTool:
    """Text-to-Speech with animated video circle generation.

    Uses OpenAI TTS for natural voice (if API key available),
    falls back to edge-tts (free).
    Video circles show frame-by-frame animated robot face with
    lip-sync, blinking, and breathing.
    """

    def __init__(
        self,
        openai_api_key: str = "",
        default_voice: str = "onyx",
        speed: float = 1.0,
        avatar_path: str | None = None,
    ) -> None:
        self._openai_key = openai_api_key
        self._openai_client = (
            AsyncOpenAI(api_key=openai_api_key)
            if OPENAI_AVAILABLE and openai_api_key
            else None
        )
        self._default_voice = default_voice
        self._speed = max(0.5, min(speed, 3.0))  # clamp 0.5x–3.0x
        self._avatar_path = Path(avatar_path) if avatar_path else None
        self._ffmpeg = shutil.which("ffmpeg")
        # Pending media queues — consumed by main.py after agent response
        self.pending_video_notes: list[Path] = []
        self.pending_voice: list[Path] = []
        # Indicator callback для показа "recording video note" во время генерации
        self._indicator_callback: Any = None  # async callable() -> None
        self._current_user_id: str | None = None  # set before agent.process()

        if self._openai_client:
            logger.info("TTS: using OpenAI tts-1-hd (natural voice)")
        elif EDGE_TTS_AVAILABLE:
            logger.info("TTS: using edge-tts (free fallback)")
        else:
            logger.warning("TTS: no provider available")

    @property
    def available(self) -> bool:
        return bool(self._openai_client) or EDGE_TTS_AVAILABLE

    def set_indicator_callback(self, callback: Any) -> None:
        """Set callback to show 'recording video note' indicator during TTS generation.

        Callback signature: async def callback() -> None
        """
        self._indicator_callback = callback

    def set_current_user_id(self, user_id: str | None) -> None:
        """Set current user_id for indicator callback. Call before agent.process()."""
        self._current_user_id = user_id

    @property
    def provider(self) -> str:
        if self._openai_client:
            return "openai"
        if EDGE_TTS_AVAILABLE:
            return "edge-tts"
        return "none"

    @property
    def definition(self) -> ToolDefinition:
        if self._openai_client:
            voice_list = ", ".join(OPENAI_VOICES.keys())
            voice_desc = f"OpenAI voice: {voice_list}. Default: onyx (deep male)"
        else:
            voice_list = ", ".join(EDGE_VOICES.keys())
            voice_desc = f"Voice: {voice_list}. Default: brian (multilingual, most natural)"

        return ToolDefinition(
            name="tts",
            description=(
                "Respond with voice instead of text. Sends an animated video circle "
                "(кружочек) with robot avatar that talks, blinks, and moves — or a "
                "simple voice message. Use this as an alternative response format when "
                "you feel it fits the moment better than text."
            ),
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to speak",
                    required=True,
                ),
                ToolParameter(
                    name="voice",
                    type="string",
                    description=voice_desc,
                    required=False,
                ),
                ToolParameter(
                    name="format",
                    type="string",
                    description="Output: 'video_note' (animated circle) or 'audio' (voice message)",
                    required=False,
                    enum=["video_note", "audio"],
                ),
            ],
        )

    # ── Main execute ─────────────────────────────────────────────

    async def execute(
        self,
        text: str,
        voice: str | None = None,
        format: str = "video_note",
        use_pending_queue: bool = True,  # False for direct calls (strangers)
        **kwargs: Any,
    ) -> ToolResult:
        if not self.available:
            return ToolResult(success=False, error="No TTS provider available")

        # Truncate for video notes
        truncated = False
        if format == "video_note" and len(text) > MAX_VIDEO_NOTE_CHARS:
            text = text[:MAX_VIDEO_NOTE_CHARS].rsplit(" ", 1)[0] + "..."
            truncated = True

        # Clean text from emojis and markdown (TTS pronounces them as "star", "smile", etc.)
        text = _clean_text_for_tts(text)

        try:
            temp_dir = Path(tempfile.mkdtemp())
            audio_path = temp_dir / "speech.mp3"

            # Show "recording video note" indicator during generation (if callback set)
            indicator_task = None
            if self._indicator_callback and format == "video_note":
                async def keep_indicator_alive():
                    """Keep sending chat action every 4 seconds while generating."""
                    while True:
                        await self._indicator_callback()
                        await asyncio.sleep(4)

                indicator_task = asyncio.create_task(keep_indicator_alive())

            try:
                # Generate audio (OpenAI primary, edge-tts fallback)
                if self._openai_client:
                    success = await self._generate_openai(text, voice, audio_path)
                    if not success and EDGE_TTS_AVAILABLE:
                        logger.warning("OpenAI TTS failed, falling back to edge-tts")
                        success = await self._generate_edge_tts(text, voice, audio_path)
                else:
                    success = await self._generate_edge_tts(text, voice, audio_path)
            finally:
                if indicator_task:
                    indicator_task.cancel()
                    try:
                        await indicator_task
                    except asyncio.CancelledError:
                        pass

            if not success:
                return ToolResult(success=False, error="Audio generation failed")

            audio_size_kb = audio_path.stat().st_size / 1024
            provider_tag = f"[{self.provider}]"

            # Video circle mode
            if format == "video_note" and self._ffmpeg:
                video_path = temp_dir / "circle.mp4"
                avatar = self._ensure_avatar(temp_dir)

                vid_ok = await self._create_animated_video(
                    avatar, audio_path, video_path
                )

                if vid_ok:
                    # Add to pending queue only if requested (for agent tool calling)
                    # For direct calls (strangers), skip queue and return path immediately
                    if use_pending_queue:
                        self.pending_video_notes.append(video_path)
                    extra = " (обрезано до 60с)" if truncated else ""
                    return ToolResult(
                        success=True,
                        data=str(video_path),  # Return path for send_video_note
                    )
                else:
                    # Fallback to voice message
                    self.pending_voice.append(audio_path)
                    return ToolResult(
                        success=True,
                        data=f"Video failed, sent as voice {provider_tag}",
                    )

            # Audio-only mode
            self.pending_voice.append(audio_path)
            return ToolResult(
                success=True,
                data=f"Voice message generated {provider_tag} ({len(text)} chars, {audio_size_kb:.0f} KB)",
            )

        except Exception as e:
            logger.exception("TTS failed")
            return ToolResult(success=False, error=f"TTS error: {e}")

    # ── Audio generation ─────────────────────────────────────────

    async def _generate_openai(
        self, text: str, voice: str | None, output: Path
    ) -> bool:
        """Generate audio using OpenAI TTS (tts-1-hd)."""
        try:
            voice_id = OPENAI_VOICES.get(voice or "", self._default_voice)
            if voice_id not in OPENAI_VOICES.values():
                voice_id = self._default_voice

            response = await self._openai_client.audio.speech.create(
                model="tts-1-hd",
                voice=voice_id,
                input=text,
                speed=self._speed,
                response_format="mp3",
            )

            output.write_bytes(response.content)
            return output.exists() and output.stat().st_size > 0

        except Exception as e:
            logger.error("OpenAI TTS failed: %s", e)
            return False

    async def _generate_edge_tts(
        self, text: str, voice: str | None, output: Path
    ) -> bool:
        """Generate audio using edge-tts (free fallback)."""
        if not EDGE_TTS_AVAILABLE:
            return False

        try:
            voice_id = EDGE_VOICES.get(voice or "", EDGE_DEFAULT_VOICE)
            # edge-tts rate: "+50%" = 1.5x, "+0%" = 1.0x, "-25%" = 0.75x
            rate_pct = int((self._speed - 1.0) * 100)
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str)
            await communicate.save(str(output))
            return output.exists() and output.stat().st_size > 0

        except Exception as e:
            logger.error("edge-tts failed: %s", e)
            return False

    # ── Animated video (frame-by-frame facial animation) ─────────

    async def _create_animated_video(
        self, avatar: Path, audio: Path, output: Path
    ) -> bool:
        """Create animated video note with frame-by-frame facial animation.

        Draws a robot face with PIL for every video frame:
        - Eyes that glow, pulse, and blink periodically
        - Mouth that opens/closes synced to audio amplitude
        - Eyebrows that rise with speech intensity
        - Subtle breathing animation (head oscillation)
        - Pulsing antenna and forehead decorations
        """
        if not PIL_AVAILABLE or not self._ffmpeg:
            logger.warning("PIL or FFmpeg missing, falling back to static video")
            return await self._create_static_video(avatar, audio, output)

        try:
            ok = await asyncio.to_thread(
                self._render_video_sync, audio, output
            )
            if ok:
                return True
            logger.warning("Frame-by-frame render failed, trying static fallback")
            return await self._create_static_video(avatar, audio, output)
        except Exception as e:
            logger.error("Animated video error: %s", e)
            return await self._create_static_video(avatar, audio, output)

    # ── Synchronous rendering pipeline (runs in thread) ──────────

    def _analyze_audio_sync(self, audio_path: Path) -> list[float]:
        """Extract per-frame amplitude envelope from audio via FFmpeg.

        Returns list of floats 0.0–1.0, one per video frame,
        smoothed with exponential moving average.
        """
        proc = subprocess.run(
            [
                self._ffmpeg, "-y",
                "-i", str(audio_path),
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ac", "1", "-ar", "16000",
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            logger.error("FFmpeg audio decode failed")
            return []

        raw = proc.stdout
        sample_rate = 16000
        spf = sample_rate // FPS          # samples per frame
        bpf = spf * 2                     # bytes per frame (16-bit)

        amplitudes: list[float] = []
        for i in range(0, len(raw) - bpf, bpf):
            chunk = raw[i : i + bpf]
            n = len(chunk) // 2
            samples = struct.unpack(f"<{n}h", chunk[: n * 2])
            rms = math.sqrt(sum(s * s for s in samples) / n) / 32768.0
            amplitudes.append(rms)

        if not amplitudes:
            return []

        # Normalize to 0..1
        peak = max(amplitudes) or 1.0
        amplitudes = [min(a / peak, 1.0) for a in amplitudes]

        # Exponential moving average for smooth mouth movement
        smoothed: list[float] = []
        prev = 0.0
        alpha = 0.35
        for a in amplitudes:
            prev = alpha * a + (1 - alpha) * prev
            smoothed.append(prev)

        return smoothed

    def _render_video_sync(self, audio_path: Path, output: Path) -> bool:
        """Render all frames and pipe to FFmpeg. Runs in a thread."""
        amplitudes = self._analyze_audio_sync(audio_path)
        if not amplitudes:
            return False

        num_frames = len(amplitudes)
        sz = VIDEO_SIZE
        cx, cy = sz // 2, sz // 2

        # Pre-render static background once (expensive gradient)
        bg = self._render_background(sz)

        # Schedule random eye blinks
        blink_times: list[float] = []
        t_next = random.uniform(2.0, 3.5)
        while t_next < num_frames / FPS:
            blink_times.append(t_next)
            t_next += random.uniform(2.5, 5.0)

        # FFmpeg: read raw RGB frames from stdin, mux with audio
        cmd = [
            self._ffmpeg, "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{sz}x{sz}", "-r", str(FPS),
            "-i", "pipe:0",
            "-i", str(audio_path),
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest", "-t", "60",
            str(output),
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Drain stderr in background thread to prevent pipe deadlock on Windows.
        # FFmpeg writes progress to stderr; if the buffer fills, it blocks,
        # which in turn blocks our stdin writes → deadlock.
        stderr_chunks: list[bytes] = []

        def _drain_stderr() -> None:
            try:
                data = proc.stderr.read()
                if data:
                    stderr_chunks.append(data)
            except Exception:
                pass

        drain = threading.Thread(target=_drain_stderr, daemon=True)
        drain.start()

        try:
            for fi in range(num_frames):
                t = fi / FPS
                amp = amplitudes[fi]

                # Eye openness: 1.0 = fully open, 0.0 = closed
                eye_open = 1.0
                for bt in blink_times:
                    if bt <= t <= bt + BLINK_DURATION_S:
                        phase = (t - bt) / BLINK_DURATION_S
                        # Parabolic: 1 → 0 → 1
                        eye_open = abs(2.0 * phase - 1.0)
                        break

                breath = int(2 * math.sin(t * 1.5))
                hcy = cy + breath - 5  # head center y with breathing

                frame = bg.copy()
                draw = ImageDraw.Draw(frame)

                self._draw_head(draw, cx, hcy, t)
                self._draw_eyes(draw, cx, hcy, t, eye_open)
                self._draw_eyebrows(draw, cx, hcy, amp)
                self._draw_nose(draw, cx, hcy)
                self._draw_mouth(draw, cx, hcy, amp)
                self._draw_decorations(draw, cx, hcy, t, breath, amp)

                proc.stdin.write(frame.tobytes())

            proc.stdin.close()
            proc.wait(timeout=120)
            drain.join(timeout=10)

            if proc.returncode != 0:
                err = b"".join(stderr_chunks).decode(errors="replace")[-500:]
                logger.error("FFmpeg pipe error: %s", err)
                return False

            return output.exists() and output.stat().st_size > 0

        except BrokenPipeError:
            logger.error("FFmpeg pipe broke (process exited early)")
            return False
        except Exception as e:
            logger.error("Frame render pipeline error: %s", e)
            try:
                proc.kill()
            except Exception:
                pass
            return False

    # ── Drawing helpers ──────────────────────────────────────────

    @staticmethod
    def _render_background(sz: int) -> Image.Image:
        """Pre-render dark radial gradient background."""
        img = Image.new("RGB", (sz, sz), (5, 5, 20))
        draw = ImageDraw.Draw(img)
        cx, cy = sz // 2, sz // 2
        for r in range(sz // 2, 0, -3):
            frac = 1 - r / (sz // 2)
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                fill=(int(5 + 8 * frac), int(5 + 12 * frac), int(20 + 25 * frac)),
            )
        return img

    @staticmethod
    def _draw_head(draw: ImageDraw.Draw, cx: int, hcy: int, t: float) -> None:
        """Draw head oval with pulsing cyan outline."""
        draw.ellipse(
            [cx - HEAD_RX, hcy - HEAD_RY, cx + HEAD_RX, hcy + HEAD_RY],
            fill=(8, 12, 28),
        )
        glow = int(140 + 40 * math.sin(t * 2))
        draw.ellipse(
            [cx - HEAD_RX, hcy - HEAD_RY, cx + HEAD_RX, hcy + HEAD_RY],
            outline=(0, glow, 255),
            width=2,
        )

    @staticmethod
    def _draw_eyes(
        draw: ImageDraw.Draw, cx: int, hcy: int, t: float, eye_open: float
    ) -> None:
        """Draw eyes with glow halo, iris, pupil, highlight, and blink."""
        ey = hcy + EYE_Y_OFF
        # Vertical radius squishes with blink
        ery = max(2, int(EYE_RY * eye_open))

        for ex in (cx - EYE_SPACING, cx + EYE_SPACING):
            # Outer glow halo (concentric rings, bright near eye → dark outside)
            glow_r = EYE_RX + 8 + int(4 * math.sin(t * 3))
            span = max(glow_r - EYE_RX, 1)
            for i in range(glow_r, EYE_RX, -2):
                frac = 1 - (i - EYE_RX) / span
                g_c = int(30 * frac)
                b_c = int(50 * frac)
                iry = max(1, int(i * ery / EYE_RX))
                draw.ellipse([ex - i, ey - iry, ex + i, ey + iry], fill=(0, g_c, b_c))

            # Eye socket
            draw.ellipse(
                [ex - EYE_RX, ey - ery, ex + EYE_RX, ey + ery],
                fill=(0, 40, 80),
            )

            if eye_open > 0.3:
                # Iris (pulsing cyan)
                ir = int(16 * min(eye_open, 1.0))
                ir_y = min(ir, max(ery - 2, 1))
                ig = int(180 + 40 * math.sin(t * 2.5))
                draw.ellipse(
                    [ex - ir, ey - ir_y, ex + ir, ey + ir_y],
                    fill=(0, ig, 255),
                )

                # Pupil (dark center)
                pr = int(8 * min(eye_open, 1.0))
                pr_y = min(pr, max(ir_y - 1, 1))
                draw.ellipse(
                    [ex - pr, ey - pr_y, ex + pr, ey + pr_y],
                    fill=(0, 60, 120),
                )

                # Specular highlight
                hr = 3
                hx, hy = ex - 4, ey - max(3, int(3 * eye_open))
                draw.ellipse(
                    [hx - hr, hy - hr, hx + hr, hy + hr],
                    fill=(200, 240, 255),
                )

    @staticmethod
    def _draw_eyebrows(
        draw: ImageDraw.Draw, cx: int, hcy: int, amp: float
    ) -> None:
        """Draw eyebrows that rise with speech intensity."""
        ey = hcy + EYE_Y_OFF
        raise_px = int(4 * amp)
        by = ey - 30 - raise_px
        for bx in (cx - EYE_SPACING, cx + EYE_SPACING):
            draw.line(
                [(bx - 18, by + 3), (bx, by), (bx + 18, by + 3)],
                fill=(0, 120, 180),
                width=2,
            )

    @staticmethod
    def _draw_nose(draw: ImageDraw.Draw, cx: int, hcy: int) -> None:
        """Draw small nose line."""
        draw.line([(cx, hcy + 8), (cx, hcy + 22)], fill=(0, 80, 140), width=2)

    @staticmethod
    def _draw_mouth(
        draw: ImageDraw.Draw, cx: int, hcy: int, amp: float
    ) -> None:
        """Draw mouth — height driven by audio amplitude."""
        my = hcy + MOUTH_Y_OFF
        mh = max(2, int(MOUTH_MAX_H * amp))

        # Outer mouth shape
        outline_g = int(120 + 60 * amp)
        outline_b = int(180 + 40 * amp)
        draw.rounded_rectangle(
            [cx - MOUTH_HW, my - mh // 2, cx + MOUTH_HW, my + mh // 2],
            radius=min(mh // 2 + 1, MOUTH_HW),
            fill=(0, 20, 40),
            outline=(0, outline_g, outline_b),
            width=1,
        )

        # Inner darkness when mouth is open
        if mh > 6:
            ih = mh - 4
            iw = MOUTH_HW - 5
            draw.rounded_rectangle(
                [cx - iw, my - ih // 2, cx + iw, my + ih // 2],
                radius=min(ih // 2, iw),
                fill=(5, 8, 20),
            )

    @staticmethod
    def _draw_decorations(
        draw: ImageDraw.Draw,
        cx: int,
        hcy: int,
        t: float,
        breath: int,
        amp: float,
    ) -> None:
        """Draw forehead dots, antenna, and subtle accents."""
        # Forehead dots (pulse with time)
        fy = hcy - 82
        for xo in (-40, -20, 0, 20, 40):
            br = int(50 + 25 * math.sin(t * 2 + xo * 0.1))
            draw.ellipse(
                [cx + xo - 2, fy - 2, cx + xo + 2, fy + 2],
                fill=(0, br, min(int(br * 1.4), 255)),
            )

        # Antenna (glows brighter with speech)
        ay = hcy - HEAD_RY - 3 + breath
        draw.line([(cx, ay), (cx, ay - 22)], fill=(0, 130, 190), width=2)
        ag = int(180 + 60 * math.sin(t * 4) + 40 * amp)
        ag = min(ag, 255)
        draw.ellipse([cx - 4, ay - 26, cx + 4, ay - 18], fill=(0, ag, 255))

    # ── Fallback: static video ───────────────────────────────────

    async def _create_static_video(
        self, avatar: Path, audio: Path, output: Path
    ) -> bool:
        """Fallback: simple static image + audio (if animated fails)."""
        cmd = [
            self._ffmpeg, "-y",
            "-loop", "1", "-i", str(avatar),
            "-i", str(audio),
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={VIDEO_SIZE}:{VIDEO_SIZE}:force_original_aspect_ratio=decrease,"
                   f"pad={VIDEO_SIZE}:{VIDEO_SIZE}:(ow-iw)/2:(oh-ih)/2",
            "-shortest", "-t", "60",
            str(output),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                logger.error(
                    "FFmpeg static fallback error: %s",
                    stderr.decode(errors="replace")[-500:],
                )
                return False

            return output.exists() and output.stat().st_size > 0

        except asyncio.TimeoutError:
            logger.error("FFmpeg static fallback timed out")
            return False
        except Exception as e:
            logger.error("FFmpeg static fallback failed: %s", e)
            return False

    def _ensure_avatar(self, temp_dir: Path) -> Path:
        """Get or create avatar image (used by static fallback)."""
        if self._avatar_path and self._avatar_path.exists():
            return self._avatar_path

        default = Path("data/avatar.png")
        if default.exists():
            return default

        # Generate a simple dark avatar via FFmpeg
        avatar = temp_dir / "avatar.png"
        if self._ffmpeg:
            try:
                subprocess.run(
                    [
                        self._ffmpeg, "-y",
                        "-f", "lavfi", "-i",
                        f"color=c=#0a0a1a:s={VIDEO_SIZE}x{VIDEO_SIZE}:d=0.1",
                        "-frames:v", "1", "-update", "1",
                        str(avatar),
                    ],
                    capture_output=True,
                    timeout=5,
                )
                if avatar.exists():
                    default.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(avatar, default)
                    return default
            except Exception:
                pass

        return avatar
