"""
Agent Control tool — restart, update, and manage the bot itself.

Allows the agent to restart itself or trigger a self-update
(git pull + restart) via special exit codes that the watchdog handles.

Exit codes:
- 42: restart (watchdog restarts immediately, no crash counter)
- 43: self-update (watchdog does git pull + restart)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WATCHDOG_STATE = PROJECT_ROOT / "data" / "watchdog_state.json"


class AgentControlTool:
    """Control the agent process: restart, update, health status."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="agent_control",
            description=(
                "Control the bot itself. Actions: "
                "'restart' — restart the bot (instant, via watchdog). "
                "'update' — git pull + restart (self-update via watchdog). "
                "'health' — show watchdog health state (uptime, crashes, status). "
                "IMPORTANT: restart/update will STOP the current conversation. "
                "Only use when the owner explicitly asks to restart or update."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'restart', 'update', or 'health'",
                    required=True,
                    enum=["restart", "update", "health"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()

        if action == "health":
            return self._get_health()
        elif action == "restart":
            return self._do_restart()
        elif action == "update":
            return self._do_update()
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _get_health(self) -> ToolResult:
        """Read watchdog state file."""
        if not WATCHDOG_STATE.exists():
            return ToolResult(
                success=True,
                data="Watchdog state not found. Bot may be running without watchdog.",
            )

        try:
            state = json.loads(WATCHDOG_STATE.read_text(encoding="utf-8"))
            parts = [
                f"Status: {state.get('status', 'unknown')}",
                f"Started: {state.get('started_at', 'unknown')}",
                f"Last bot start: {state.get('last_bot_start', 'unknown')}",
                f"Total restarts: {state.get('total_restarts', 0)}",
                f"Consecutive crashes: {state.get('consecutive_crashes', 0)}",
                f"Last crash: {state.get('last_crash', 'none')}",
                f"Bot PID: {state.get('pid', 'unknown')}",
            ]
            return ToolResult(success=True, data="\n".join(parts))
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read state: {e}")

    def _do_restart(self) -> ToolResult:
        """Trigger bot restart via exit code 42."""
        logger.warning("Agent restart requested — exiting with code 42")
        # Schedule the exit after returning the result
        # We need to actually exit the process for watchdog to restart it
        import asyncio
        import threading

        def _exit_later():
            import os
            import time
            time.sleep(2)  # Give time to send response
            os._exit(42)  # Force exit from any thread (sys.exit only works in main thread)

        threading.Thread(target=_exit_later, daemon=True).start()
        return ToolResult(
            success=True,
            data="Перезапуск инициирован. Бот перезапустится через несколько секунд.",
        )

    def _do_update(self) -> ToolResult:
        """Trigger self-update via exit code 43."""
        logger.warning("Self-update requested — exiting with code 43")
        import threading

        def _exit_later():
            import os
            import time
            time.sleep(2)  # Give time to send response
            os._exit(43)  # Force exit from any thread

        threading.Thread(target=_exit_later, daemon=True).start()
        return ToolResult(
            success=True,
            data="Обновление инициировано. Бот сделает git pull и перезапустится.",
        )
