"""
Speed Test tool — measure internet speed (download, upload, ping).

Uses speedtest-cli library (Ookla Speedtest servers).
Runs in thread pool to avoid blocking asyncio.

pip install speedtest-cli
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class SpeedTestTool:
    """Measure internet connection speed using Ookla Speedtest."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="speedtest",
            description=(
                "Measure internet connection speed: download, upload, and ping. "
                "Uses Ookla Speedtest servers. Takes 15-30 seconds. "
                "Use when user asks: 'скорость интернета', 'спидтест', "
                "'speedtest', 'проверь скорость', 'пинг'."
            ),
            parameters=[
                ToolParameter(
                    name="simple",
                    type="boolean",
                    description="If true, only test download speed (faster, ~10s). Default: false (full test)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        simple = kwargs.get("simple", False)

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._run_test, simple)
            return result
        except Exception as e:
            logger.exception("Speed test failed")
            return ToolResult(success=False, error=f"Speed test failed: {e}")

    @staticmethod
    def _run_test(simple: bool) -> ToolResult:
        """Synchronous speed test (runs in thread pool)."""
        import speedtest

        st = speedtest.Speedtest()
        st.get_best_server()

        server = st.best
        server_name = server.get("sponsor", "?")
        server_location = server.get("name", "?")
        ping_ms = server.get("latency", 0)

        # Download
        dl_bps = st.download()
        dl_mbps = dl_bps / 1_000_000

        ul_mbps = 0.0
        if not simple:
            ul_bps = st.upload()
            ul_mbps = ul_bps / 1_000_000

        logger.info(
            "Speed test: DL=%.1f Mbps, UL=%.1f Mbps, Ping=%.0f ms, Server=%s",
            dl_mbps, ul_mbps, ping_ms, server_name,
        )

        data = {
            "download_mbps": round(dl_mbps, 1),
            "upload_mbps": round(ul_mbps, 1),
            "ping_ms": round(ping_ms, 1),
            "server": server_name,
            "server_location": server_location,
        }

        lines = [
            f"Download: {dl_mbps:.1f} Mbps",
        ]
        if not simple:
            lines.append(f"Upload: {ul_mbps:.1f} Mbps")
        lines.extend([
            f"Ping: {ping_ms:.0f} ms",
            f"Server: {server_name} ({server_location})",
        ])

        data["answer"] = "\n".join(lines)
        return ToolResult(success=True, data=data)
