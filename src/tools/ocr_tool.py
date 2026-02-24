"""
OCR tool — extract text from images.

Uses RapidOCR (ONNX Runtime backend, no PyTorch needed).
Supports: English, Russian, Ukrainian, Chinese, and more.
First call downloads ~12MB models, then works offline.

pip install rapidocr-onnxruntime
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class OCRTool:
    """Extract text from images using RapidOCR (local ONNX model)."""

    def __init__(self) -> None:
        self._ocr: Any = None

    def _ensure_engine(self) -> Any:
        """Lazy-load RapidOCR on first use."""
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            logger.info("RapidOCR engine initialized (ONNX Runtime)")
        return self._ocr

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ocr",
            description=(
                "Extract text from an image using OCR (Optical Character Recognition). "
                "Works with screenshots, documents, photos of text, receipts, etc. "
                "Supports English, Russian, Ukrainian, and other languages. "
                "Use when user asks: 'распознай текст', 'что написано на картинке', "
                "'OCR', 'extract text from image'."
            ),
            parameters=[
                ToolParameter(
                    name="image_path",
                    type="string",
                    description="Path to the image file (JPG, PNG, BMP, etc.)",
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
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._run_ocr, path)
            return result
        except Exception as e:
            logger.exception("OCR failed for %s", image_path)
            return ToolResult(success=False, error=f"OCR failed: {e}")

    def _run_ocr(self, image_path: Path) -> ToolResult:
        """Synchronous OCR processing (runs in thread pool)."""
        ocr = self._ensure_engine()

        result, elapse = ocr(str(image_path))

        if not result:
            return ToolResult(
                success=True,
                data={"text": "", "message": "No text found in image."},
            )

        # result is list of [bbox, text, confidence]
        lines = []
        total_conf = 0.0
        for item in result:
            text = item[1]
            confidence = item[2]
            lines.append(text)
            total_conf += confidence

        full_text = "\n".join(lines)
        avg_conf = total_conf / len(result) if result else 0

        logger.info(
            "OCR extracted %d lines from %s (avg confidence: %.1f%%, elapsed: %.2fs)",
            len(lines), image_path.name, avg_conf * 100, sum(elapse) if elapse else 0,
        )

        return ToolResult(
            success=True,
            data={
                "text": full_text,
                "lines_count": len(lines),
                "avg_confidence": round(avg_conf, 3),
                "answer": f"Extracted text ({len(lines)} lines):\n\n{full_text}",
            },
        )
