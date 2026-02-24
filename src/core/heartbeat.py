"""
Heartbeat Engine — autonomous task execution.

Reads HEARTBEAT.md from the project root and executes each task
through the agent pipeline at a configured interval.

This is NOT a replacement for monitors — monitors are Python code
with specific APIs. Heartbeat is for flexible, LLM-driven tasks
that the owner can add/remove by editing a markdown file.

Example HEARTBEAT.md:
    - Check if there are new GitHub issues on my repos
    - Summarize any important emails from the last hour
    - Check system disk space and alert if below 10%
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Project root (resolved relative to this file: src/core/heartbeat.py → project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# State file to track last run times and results
STATE_FILE = _PROJECT_ROOT / "data" / "heartbeat_state.json"

# Heartbeat file location
HEARTBEAT_FILE = _PROJECT_ROOT / "HEARTBEAT.md"

# System prompt prefix for heartbeat tasks
HEARTBEAT_SYSTEM_PREFIX = (
    "You are executing an autonomous HEARTBEAT task. "
    "The owner set up this periodic task. Execute it efficiently:\n"
    "- Use your tools to gather real data (don't make up results)\n"
    "- CRITICAL: If everything is OK — respond with EXACTLY 'ALL_OK' and nothing else\n"
    "- Only report PROBLEMS: low disk space, high CPU/RAM, overheating, no internet, errors\n"
    "- Do NOT report 'всё хорошо', 'диск в порядке', 'интернет работает' — just say ALL_OK\n"
    "- If there IS a problem — describe it concisely in Russian\n"
    "- The owner does NOT want to see reports when everything is fine\n\n"
    "Task to execute:\n"
)

# Marker for "everything is fine" — used to filter out non-critical results
ALL_OK_MARKER = "ALL_OK"


# Callback type: send notification to owner
NotifyCallback = Callable[[str, str], Coroutine[Any, Any, None]]

# Agent process callback: run a prompt through the agent and return response
AgentCallback = Callable[[str], Coroutine[Any, Any, str]]


def parse_heartbeat_file(path: Path | None = None) -> list[str]:
    """Parse HEARTBEAT.md and return list of task strings.

    Supports:
    - Lines starting with '- ' (markdown list)
    - Lines starting with '* '
    - Lines starting with a number '1. '
    - Ignores empty lines, comments (#), and headers (##)

    Args:
        path: Path to heartbeat file. Defaults to HEARTBEAT.md.

    Returns:
        List of task description strings.
    """
    hb_path = path or HEARTBEAT_FILE
    if not hb_path.exists():
        return []

    try:
        content = hb_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to read %s: %s", hb_path, e)
        return []

    tasks: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        # Skip empty, comments, headers
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Strip list markers
        if line.startswith("- "):
            line = line[2:].strip()
        elif line.startswith("* "):
            line = line[2:].strip()
        elif len(line) > 2 and line[0].isdigit() and ". " in line[:5]:
            line = line.split(". ", 1)[1].strip()
        else:
            # Non-list line — treat as task if it has content
            pass

        if line:
            tasks.append(line)

    return tasks


class HeartbeatState:
    """Persistent state for heartbeat execution tracking."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self._path = path
        self._data: dict[str, Any] = {
            "last_run": None,
            "run_count": 0,
            "task_results": {},  # task_hash -> {last_run, success, error}
        }
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load heartbeat state: %s", e)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Failed to save heartbeat state: %s", e)

    @property
    def last_run(self) -> str | None:
        return self._data.get("last_run")

    @property
    def run_count(self) -> int:
        return self._data.get("run_count", 0)

    def record_run(self) -> None:
        self._data["last_run"] = datetime.now().isoformat()
        self._data["run_count"] = self._data.get("run_count", 0) + 1

    def record_task(self, task: str, success: bool, error: str | None = None) -> None:
        task_key = task[:80]  # Use first 80 chars as key
        self._data.setdefault("task_results", {})[task_key] = {
            "last_run": datetime.now().isoformat(),
            "success": success,
            "error": error,
        }


class HeartbeatEngine:
    """Executes HEARTBEAT.md tasks through the agent pipeline.

    Usage:
        engine = HeartbeatEngine(
            agent_callback=run_agent_prompt,
            notify_callback=send_to_telegram,
            user_id="YOUR_TELEGRAM_ID",
        )

        # Register with scheduler:
        scheduler.add_job(engine.run, trigger="interval", minutes=30)
    """

    def __init__(
        self,
        agent_callback: AgentCallback,
        notify_callback: NotifyCallback,
        user_id: str,
        heartbeat_path: Path | None = None,
        notify_on_error: bool = True,
        notify_on_results: bool = True,
    ) -> None:
        self._agent = agent_callback
        self._notify = notify_callback
        self._user_id = user_id
        self._heartbeat_path = heartbeat_path or HEARTBEAT_FILE
        self._notify_on_error = notify_on_error
        self._notify_on_results = notify_on_results
        self._state = HeartbeatState()
        self._running = False

    @property
    def state(self) -> HeartbeatState:
        return self._state

    @property
    def running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Execute all tasks from HEARTBEAT.md.

        Called by the scheduler at configured intervals.
        Each task is run through the agent and results are collected.
        """
        if self._running:
            logger.warning("Heartbeat already running, skipping")
            return

        self._running = True
        start = time.monotonic()

        try:
            tasks = parse_heartbeat_file(self._heartbeat_path)
            if not tasks:
                logger.debug("No heartbeat tasks found")
                return

            logger.info("Heartbeat: executing %d tasks", len(tasks))
            self._state.record_run()

            results: list[str] = []
            errors: list[str] = []

            for task in tasks:
                try:
                    logger.info("Heartbeat task: %s", task[:80])
                    prompt = HEARTBEAT_SYSTEM_PREFIX + task
                    response = await self._agent(prompt)

                    # Only collect PROBLEMS — skip ALL_OK responses
                    if response and response.strip():
                        cleaned = response.strip()
                        is_ok = (
                            ALL_OK_MARKER in cleaned.upper()
                            or "всё в порядке" in cleaned.lower()
                            or "всё ок" in cleaned.lower()
                            or "все в порядке" in cleaned.lower()
                            or "в порядке" in cleaned.lower() and len(cleaned) < 100
                            or "нет результатов" in cleaned.lower()
                            or "работает" in cleaned.lower() and len(cleaned) < 60
                        )
                        if not is_ok:
                            results.append(f"**{task}**\n{response}")
                        else:
                            logger.info("Heartbeat task OK (silent): %s", task[:50])

                    self._state.record_task(task, success=True)

                except Exception as e:
                    error_msg = f"Task '{task[:50]}' failed: {e}"
                    logger.error("Heartbeat task error: %s", error_msg)
                    errors.append(error_msg)
                    self._state.record_task(task, success=False, error=str(e))

            # Send ONLY if there are actual problems
            if results and self._notify_on_results:
                digest = "⚠️ **Heartbeat Alert**\n\n" + "\n\n---\n\n".join(results)
                # Truncate if too long for Telegram (4096 char limit)
                if len(digest) > 4000:
                    digest = digest[:3950] + "\n\n... (обрезано)"
                await self._notify(self._user_id, digest)

            if errors and self._notify_on_error:
                error_report = "⚠️ **Heartbeat Errors**\n\n" + "\n".join(f"• {e}" for e in errors)
                await self._notify(self._user_id, error_report)

            self._state.save()

            elapsed = time.monotonic() - start
            logger.info(
                "Heartbeat complete: %d tasks, %d results, %d errors (%.1fs)",
                len(tasks), len(results), len(errors), elapsed,
            )

        except Exception as e:
            logger.error("Heartbeat engine failed: %s", e, exc_info=True)
        finally:
            self._running = False

    async def run_single(self, task: str) -> str:
        """Run a single heartbeat task and return the result.

        Useful for testing or on-demand execution.
        """
        prompt = HEARTBEAT_SYSTEM_PREFIX + task
        return await self._agent(prompt)
