"""
Background Removal tool — remove background from images.

Uses rembg library (local ONNX model, no API key needed).
First call downloads ~170MB model, then works offline.

pip install rembg[cpu]
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class BackgroundRemovalTool:
    """Remove background from images using rembg (local AI model)."""

    def __init__(self, pending_sends: list[Path] | None = None) -> None:
        # Shared pending_sends list — main.py sends these as files
        self._pending_sends = pending_sends if pending_sends is not None else []

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="bg_remove",
            description=(
                "Remove background from an image, making it transparent (PNG). "
                "Works with photos, portraits, product shots, logos. "
                "Use when user asks: 'убери фон', 'remove background', "
                "'сделай прозрачный фон', 'вырежи объект'."
            ),
            parameters=[
                ToolParameter(
                    name="image_path",
                    type="string",
                    description="Path to the image file to process",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        image_path: str = kwargs.get("image_path", "")
        if not image_path:
            return ToolResult(success=False, error="image_path is required")

        path = Path(image_path)
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {image_path}")

        try:
            # Run in executor — rembg is CPU-intensive and synchronous
            loop = asyncio.get_event_loop()
            output_path = await loop.run_in_executor(None, self._process_image, path)

            # Queue for sending via Telegram
            self._pending_sends.append(output_path)

            size_kb = output_path.stat().st_size / 1024
            logger.info(
                "Background removed: %s → %s (%.1f KB)",
                path.name, output_path.name, size_kb,
            )

            return ToolResult(
                success=True,
                data=f"Background removed. Transparent PNG ({size_kb:.0f} KB) will be sent.",
            )

        except Exception as e:
            logger.exception("Background removal failed for %s", image_path)
            return ToolResult(success=False, error=f"Background removal failed: {e}")

    @staticmethod
    def _process_image(input_path: Path) -> Path:
        """Synchronous image processing (runs in thread pool)."""
        from PIL import Image
        from rembg import remove

        input_img = Image.open(input_path)
        output_img = remove(input_img)

        # Save to temp directory as PNG (supports transparency)
        temp_dir = Path(tempfile.mkdtemp())
        output_path = temp_dir / f"{input_path.stem}_no_bg.png"
        output_img.save(output_path, format="PNG")

        return output_path
