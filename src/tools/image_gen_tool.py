"""
Image Generation Tool — DALL-E 3 via OpenAI API.

Generates images from text descriptions. Sends result as Telegram file.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class ImageGenTool:
    """Generate images using DALL-E 3."""

    def __init__(self, api_key: str, pending_sends: list[Path] | None = None) -> None:
        self._api_key = api_key
        self._client = AsyncOpenAI(api_key=api_key) if OPENAI_AVAILABLE and api_key else None
        # Shared pending_sends list (from FileSendTool) — main.py sends these as files
        self._pending_sends = pending_sends if pending_sends is not None else []

    @property
    def available(self) -> bool:
        return OPENAI_AVAILABLE and bool(self._api_key)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="image_gen",
            description=(
                "Generate an image from a text description using DALL-E 3. "
                "The generated image will be automatically sent to the chat."
            ),
            parameters=[
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="Detailed description of the image to generate (English works best for DALL-E)",
                    required=True,
                ),
                ToolParameter(
                    name="size",
                    type="string",
                    description="Image size",
                    required=False,
                    enum=["1024x1024", "1792x1024", "1024x1792"],
                ),
                ToolParameter(
                    name="quality",
                    type="string",
                    description="Image quality: 'standard' or 'hd' (costs more)",
                    required=False,
                    enum=["standard", "hd"],
                ),
            ],
        )

    async def execute(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        **kwargs: Any,
    ) -> ToolResult:
        if not self._client:
            return ToolResult(
                success=False,
                error="OpenAI not configured — set OPENAI_API_KEY in .env",
            )

        try:
            response = await self._client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )

            image_url = response.data[0].url
            revised_prompt = response.data[0].revised_prompt or prompt

            # Download image
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    image_url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"Failed to download image: HTTP {resp.status}",
                        )
                    image_data = await resp.read()

            # Save to temp file
            temp_dir = Path(tempfile.mkdtemp())
            image_path = temp_dir / "generated.png"
            image_path.write_bytes(image_data)

            # Queue for sending
            self._pending_sends.append(image_path)

            logger.info(
                "Image generated: %s (%s, %s, %.1f KB)",
                quality, size, image_path.name, len(image_data) / 1024,
            )

            return ToolResult(
                success=True,
                data=f"Image generated and will be sent.\nDALL-E prompt: {revised_prompt}",
            )

        except Exception as e:
            logger.exception("Image generation failed")
            return ToolResult(success=False, error=f"DALL-E error: {e}")
