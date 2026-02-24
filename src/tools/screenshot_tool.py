"""
Screenshot tool — capture screen and optionally OCR via Claude Vision.

Uses mss for fast cross-platform screenshots.
OCR is done by sending the image to Claude Vision API.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "screenshots"


class ScreenshotTool:
    """Capture screen screenshots with optional OCR."""

    def __init__(self, llm_provider: Any = None) -> None:
        """Init with optional LLM provider for OCR.

        Args:
            llm_provider: Object with `complete_vision(prompt, image_b64)` method.
                         If None, OCR won't be available but screenshots still work.
        """
        self._llm = llm_provider

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="screenshot",
            description=(
                "Capture a screenshot of the screen. "
                "Actions: 'capture' — save screenshot as PNG; "
                "'ocr' — capture + extract text using Claude Vision; "
                "'read' — OCR an existing image file. "
                "Useful for reading on-screen content, debugging UI, etc."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'capture', 'ocr', or 'read'",
                    required=True,
                    enum=["capture", "ocr", "read"],
                ),
                ToolParameter(
                    name="monitor",
                    type="integer",
                    description="Monitor number (1 = primary, 2 = secondary). Default: 1",
                    required=False,
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to existing image file (for 'read' action)",
                    required=False,
                ),
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="Custom OCR prompt (for 'ocr'/'read'). Default: extract all text",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()

        try:
            if action == "capture":
                return await self._capture(kwargs)
            elif action == "ocr":
                return await self._ocr(kwargs)
            elif action == "read":
                return await self._read_image(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("Screenshot error: %s", e)
            return ToolResult(success=False, error=f"Screenshot error: {e}")

    async def _capture(self, kwargs: dict) -> ToolResult:
        """Capture screenshot and save to file."""
        try:
            import mss
        except ImportError:
            return ToolResult(
                success=False,
                error="mss not installed. Run: pip install mss",
            )

        monitor_num = int(kwargs.get("monitor", 1))

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = SCREENSHOT_DIR / f"screenshot_{timestamp}.png"

        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_num >= len(monitors):
                monitor_num = 1  # fallback to primary
            monitor = monitors[monitor_num]

            sct_img = sct.grab(monitor)

            # Convert to PNG using mss tools
            from mss.tools import to_png
            to_png(sct_img.rgb, sct_img.size, output=str(out_path))

        logger.info("Screenshot saved: %s (%dx%d)", out_path, monitor["width"], monitor["height"])
        return ToolResult(
            success=True,
            data=f"Screenshot saved: {out_path}\nResolution: {monitor['width']}x{monitor['height']}",
        )

    async def _ocr(self, kwargs: dict) -> ToolResult:
        """Capture screenshot and OCR via Claude Vision."""
        # First capture
        capture_result = await self._capture(kwargs)
        if not capture_result.success:
            return capture_result

        # Extract file path from capture result
        path_str = capture_result.data.split("\n")[0].replace("Screenshot saved: ", "")
        return await self._do_ocr(Path(path_str), kwargs.get("prompt", ""))

    async def _read_image(self, kwargs: dict) -> ToolResult:
        """OCR an existing image file."""
        file_path = kwargs.get("file_path", "").strip()
        if not file_path:
            return ToolResult(success=False, error="file_path required for 'read' action")

        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        return await self._do_ocr(path, kwargs.get("prompt", ""))

    async def _do_ocr(self, image_path: Path, custom_prompt: str = "") -> ToolResult:
        """Send image to LLM provider for OCR.

        Goes through provider.complete() → proxy → free via subscription.
        Does NOT call Anthropic API directly.
        """
        if not self._llm:
            return ToolResult(
                success=True,
                data=f"Screenshot saved at {image_path} (OCR not available — no LLM provider configured)",
            )

        # Read and encode image
        image_data = image_path.read_bytes()
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        # Determine media type
        suffix = image_path.suffix.lower()
        media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
        media_type = media_types.get(suffix, "image/png")

        prompt = custom_prompt or "Extract ALL text from this screenshot. Preserve formatting and structure."

        try:
            # Use provider.complete() — routes through proxy (FREE via subscription)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ]

            response = await self._llm.complete(messages=messages)
            text = response.content if response.content else ""

            logger.info("OCR complete: %d chars from %s", len(text), image_path.name)
            return ToolResult(
                success=True,
                data=f"Screenshot: {image_path}\n\nOCR Result:\n{text}",
            )

        except Exception as e:
            logger.error("OCR failed: %s", e)
            return ToolResult(
                success=True,
                data=f"Screenshot saved at {image_path}\nOCR failed: {e}",
            )
