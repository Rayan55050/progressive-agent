"""
Diagram tool — generate diagrams from Mermaid syntax.

Uses mermaid.ink free API (no install, no API key).
Renders Mermaid code to PNG image.

Supports: flowcharts, sequence diagrams, class diagrams,
state diagrams, ER diagrams, Gantt charts, pie charts, etc.
"""

from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

MERMAID_INK_URL = "https://mermaid.ink/img/"


class DiagramTool:
    """Generate diagrams from Mermaid syntax using mermaid.ink API."""

    def __init__(self, pending_sends: list[Path] | None = None) -> None:
        self._pending_sends = pending_sends if pending_sends is not None else []

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="diagram",
            description=(
                "Generate a diagram/chart from Mermaid syntax. "
                "Supports: flowcharts, sequence diagrams, class diagrams, "
                "state diagrams, ER diagrams, Gantt charts, pie charts, mind maps. "
                "Use when user asks: 'нарисуй диаграмму', 'схема', 'flowchart', "
                "'блок-схема', 'визуализируй архитектуру'."
            ),
            parameters=[
                ToolParameter(
                    name="code",
                    type="string",
                    description=(
                        "Mermaid diagram code. Example: "
                        "'graph TD\\n  A[Start] --> B{Decision}\\n  B -->|Yes| C[OK]\\n  B -->|No| D[End]'"
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="Optional title for the diagram (used as filename)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        code: str = kwargs.get("code", "").strip()
        if not code:
            return ToolResult(success=False, error="Mermaid code is required")

        title: str = kwargs.get("title", "diagram").strip()

        try:
            # Encode mermaid code for URL
            encoded = base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii")
            url = f"{MERMAID_INK_URL}{encoded}"

            # Fetch rendered PNG
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        return ToolResult(
                            success=False,
                            error=f"mermaid.ink returned HTTP {resp.status}. Check syntax. Response: {body[:200]}",
                        )
                    image_data = await resp.read()

            if len(image_data) < 100:
                return ToolResult(
                    success=False,
                    error="mermaid.ink returned empty/tiny image. Check Mermaid syntax.",
                )

            # Save to temp file
            safe_title = "".join(
                c if c.isalnum() or c in " -_" else "_" for c in title
            ).strip()[:60] or "diagram"
            temp_dir = Path(tempfile.mkdtemp())
            image_path = temp_dir / f"{safe_title}.png"
            image_path.write_bytes(image_data)

            # Queue for sending via Telegram
            self._pending_sends.append(image_path)

            size_kb = len(image_data) / 1024
            logger.info("Diagram generated: %s (%.1f KB)", safe_title, size_kb)

            return ToolResult(
                success=True,
                data=f"Diagram '{safe_title}' generated ({size_kb:.0f} KB). Will be sent.",
            )

        except aiohttp.ClientError as e:
            logger.error("mermaid.ink request failed: %s", e)
            return ToolResult(success=False, error=f"mermaid.ink unavailable: {e}")
        except Exception as e:
            logger.exception("Diagram generation failed")
            return ToolResult(success=False, error=f"Diagram error: {e}")
