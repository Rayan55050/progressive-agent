"""
Clipboard tool — read/write system clipboard.

Uses pyperclip for cross-platform clipboard access.
On Windows uses win32 API internally.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ClipboardTool:
    """Read from or write to the system clipboard."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="clipboard",
            description=(
                "Read or write the system clipboard. "
                "Actions: 'read' — get current clipboard content; "
                "'write' — set clipboard to given text. "
                "Useful for copying results, pasting user data, etc."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'read' or 'write'",
                    required=True,
                    enum=["read", "write"],
                ),
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to write to clipboard (required for 'write' action)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()

        try:
            import pyperclip
        except ImportError:
            return ToolResult(
                success=False,
                error="pyperclip not installed. Run: pip install pyperclip",
            )

        try:
            if action == "read":
                content = pyperclip.paste()
                if not content:
                    return ToolResult(success=True, data="Clipboard is empty.")
                # Truncate if very long
                if len(content) > 5000:
                    return ToolResult(
                        success=True,
                        data=f"Clipboard ({len(content)} chars, truncated):\n{content[:5000]}...",
                    )
                return ToolResult(success=True, data=f"Clipboard:\n{content}")

            elif action == "write":
                text = kwargs.get("text", "")
                if not text:
                    return ToolResult(success=False, error="No text provided for write")
                pyperclip.copy(str(text))
                logger.info("Clipboard write: %d chars", len(text))
                return ToolResult(
                    success=True,
                    data=f"Copied to clipboard ({len(text)} chars)",
                )

            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")

        except Exception as e:
            logger.error("Clipboard error: %s", e)
            return ToolResult(success=False, error=f"Clipboard error: {e}")
