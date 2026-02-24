"""
QR Code generator tool.

Generates QR codes from text/URLs and saves as PNG images.
Uses qrcode library with Pillow backend.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "qr_codes"


class QRCodeTool:
    """Generate QR codes from text or URLs."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="qr_code",
            description=(
                "Generate a QR code image from text or URL. "
                "Returns the file path to the generated PNG image. "
                "Useful for sharing links, Wi-Fi credentials, contact info, etc."
            ),
            parameters=[
                ToolParameter(
                    name="data",
                    type="string",
                    description="Text or URL to encode in the QR code",
                    required=True,
                ),
                ToolParameter(
                    name="filename",
                    type="string",
                    description="Output filename (without extension). Default: auto-generated",
                    required=False,
                ),
                ToolParameter(
                    name="size",
                    type="integer",
                    description="Box size in pixels (1-20). Default: 10",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        data = kwargs.get("data", "").strip()
        if not data:
            return ToolResult(success=False, error="No data provided for QR code")

        filename = kwargs.get("filename", "").strip()
        size = int(kwargs.get("size", 10))
        size = max(1, min(20, size))

        try:
            import qrcode
            from qrcode.image.pil import PilImage
        except ImportError:
            return ToolResult(
                success=False,
                error="qrcode library not installed. Run: pip install qrcode[pil]",
            )

        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            qr = qrcode.QRCode(
                version=None,  # auto-detect
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=size,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)

            img: PilImage = qr.make_image(fill_color="black", back_color="white")

            if not filename:
                # Auto-generate from data (sanitize)
                safe = "".join(c if c.isalnum() else "_" for c in data[:30])
                filename = f"qr_{safe}"

            out_path = OUTPUT_DIR / f"{filename}.png"
            img.save(str(out_path))

            logger.info("QR code saved: %s (%d chars encoded)", out_path, len(data))
            return ToolResult(
                success=True,
                data=f"QR code saved: {out_path}\nEncoded: {data[:100]}{'...' if len(data) > 100 else ''}",
            )

        except Exception as e:
            logger.error("QR generation failed: %s", e)
            return ToolResult(success=False, error=f"QR generation failed: {e}")
