"""
Scheduler Tool — reminders and recurring tasks.

Exposes APScheduler as a tool so the agent can create, list,
and remove scheduled reminders. Persists tasks to JSON for
restart survival.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

DATA_FILE = Path("data/scheduled_tasks.json")

# Repeat interval mapping → APScheduler kwargs
REPEAT_MAP: dict[str, dict[str, int]] = {
    "every_5_min": {"minutes": 5},
    "every_15_min": {"minutes": 15},
    "every_30_min": {"minutes": 30},
    "hourly": {"hours": 1},
    "every_2_hours": {"hours": 2},
    "every_4_hours": {"hours": 4},
    "every_6_hours": {"hours": 6},
    "every_12_hours": {"hours": 12},
    "daily": {"days": 1},
    "weekly": {"weeks": 1},
}

# Cron presets → APScheduler CronTrigger kwargs
CRON_PRESETS: dict[str, dict[str, str]] = {
    "weekdays_9am": {"day_of_week": "mon-fri", "hour": "9", "minute": "0"},
    "weekdays_18pm": {"day_of_week": "mon-fri", "hour": "18", "minute": "0"},
    "weekends_10am": {"day_of_week": "sat,sun", "hour": "10", "minute": "0"},
    "monday_9am": {"day_of_week": "mon", "hour": "9", "minute": "0"},
    "friday_17pm": {"day_of_week": "fri", "hour": "17", "minute": "0"},
    "first_of_month": {"day": "1", "hour": "9", "minute": "0"},
    "every_night_23": {"hour": "23", "minute": "0"},
    "every_morning_8": {"hour": "8", "minute": "0"},
}


class SchedulerService:
    """Manages user-created scheduled reminders with persistence."""

    def __init__(
        self,
        scheduler: Any,  # src.core.scheduler.Scheduler
        notify: Callable[[str, str], Awaitable[None]],
        user_id: str,
    ) -> None:
        self._scheduler = scheduler
        self._notify = notify
        self._user_id = user_id
        self._tasks: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load persisted tasks from JSON."""
        if DATA_FILE.exists():
            try:
                self._tasks = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                logger.info("Loaded %d scheduled tasks from disk", len(self._tasks))
            except Exception as e:
                logger.error("Failed to load scheduled tasks: %s", e)
                self._tasks = {}

    def _save(self) -> None:
        """Persist tasks to JSON."""
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(
            json.dumps(self._tasks, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def restore_jobs(self) -> int:
        """Re-register persisted tasks with the scheduler after restart.

        Returns number of restored jobs.
        """
        restored = 0
        expired = []

        for task_id, task in self._tasks.items():
            repeat = task.get("repeat")

            if repeat and repeat in CRON_PRESETS:
                # Cron-style task
                self._scheduler.add_job(
                    self._make_callback(task_id),
                    trigger="cron",
                    name=f"reminder_{task_id[:8]}",
                    **CRON_PRESETS[repeat],
                )
                restored += 1
            elif repeat and repeat in REPEAT_MAP:
                # Recurring task — always restore
                self._scheduler.add_job(
                    self._make_callback(task_id),
                    trigger="interval",
                    name=f"reminder_{task_id[:8]}",
                    **REPEAT_MAP[repeat],
                )
                restored += 1
            else:
                # One-shot — check if still in the future
                run_at = datetime.fromisoformat(task["run_at"])
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=timezone.utc)
                if run_at > datetime.now(timezone.utc):
                    self._scheduler.add_job(
                        self._make_callback(task_id),
                        trigger="date",
                        run_date=run_at,
                        name=f"reminder_{task_id[:8]}",
                    )
                    restored += 1
                else:
                    expired.append(task_id)

        # Clean up expired one-shot tasks
        for tid in expired:
            del self._tasks[tid]
        if expired:
            self._save()
            logger.info("Cleaned %d expired reminders", len(expired))

        return restored

    async def add_task(
        self,
        message: str,
        run_at: str,
        repeat: str | None = None,
    ) -> tuple[str, str]:
        """Add a new scheduled task.

        Args:
            message: What to remind about.
            run_at: ISO datetime for first/only execution.
            repeat: Optional repeat interval (daily, hourly, etc.)

        Returns:
            (task_id, human-readable confirmation)
        """
        task_id = str(uuid.uuid4())[:8]

        try:
            run_datetime = datetime.fromisoformat(run_at)
            # If naive (no timezone), assume UTC
            if run_datetime.tzinfo is None:
                run_datetime = run_datetime.replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError(
                f"Invalid datetime format: {run_at}. Use ISO format: YYYY-MM-DDTHH:MM:SS"
            )

        # Store task data
        self._tasks[task_id] = {
            "message": message,
            "run_at": run_at,
            "repeat": repeat,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

        # Register with scheduler
        callback = self._make_callback(task_id)

        if repeat and repeat in CRON_PRESETS:
            # Cron-style scheduling
            cron_kwargs = CRON_PRESETS[repeat]
            self._scheduler.add_job(
                callback,
                trigger="cron",
                name=f"reminder_{task_id}",
                **cron_kwargs,
            )
            repeat_label = repeat.replace("_", " ")
            confirm = f"Cron reminder set ({repeat_label})"
        elif repeat and repeat in REPEAT_MAP:
            self._scheduler.add_job(
                callback,
                trigger="interval",
                name=f"reminder_{task_id}",
                next_run_time=run_datetime,
                **REPEAT_MAP[repeat],
            )
            repeat_label = repeat.replace("_", " ")
            confirm = f"Recurring reminder set ({repeat_label}), starting {run_at}"
        else:
            if run_datetime <= datetime.now(timezone.utc):
                # Immediate execution
                await callback()
                confirm = f"Reminder sent immediately (time was in the past)"
            else:
                self._scheduler.add_job(
                    callback,
                    trigger="date",
                    run_date=run_datetime,
                    name=f"reminder_{task_id}",
                )
                confirm = f"Reminder set for {run_at}"

        return task_id, confirm

    async def remove_task(self, task_id: str) -> bool:
        """Remove a scheduled task."""
        if task_id not in self._tasks:
            return False

        del self._tasks[task_id]
        self._save()

        # Try to remove from scheduler (may already have fired)
        try:
            jobs = self._scheduler.list_jobs()
            for job in jobs:
                if task_id in job.name:
                    self._scheduler.remove_job(job.id)
                    break
        except Exception:
            pass

        return True

    def list_tasks(self) -> list[dict[str, Any]]:
        """List all scheduled tasks."""
        result = []
        for task_id, task in self._tasks.items():
            result.append({
                "id": task_id,
                "message": task["message"],
                "run_at": task["run_at"],
                "repeat": task.get("repeat", "one-shot"),
                "created": task.get("created", ""),
            })
        return result

    def _make_callback(self, task_id: str) -> Callable[[], Awaitable[None]]:
        """Create async callback for when a reminder fires."""

        async def _fire() -> None:
            task = self._tasks.get(task_id)
            if not task:
                return

            msg = f"⏰ Напоминание: {task['message']}"
            try:
                await self._notify(self._user_id, msg)
            except Exception as e:
                logger.error("Failed to send reminder %s: %s", task_id, e)

            # Remove one-shot tasks after firing
            if not task.get("repeat"):
                self._tasks.pop(task_id, None)
                self._save()

        return _fire


# --- Tool classes ---


class SchedulerAddTool:
    """Add a reminder or recurring task."""

    def __init__(self, service: SchedulerService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        all_repeats = list(REPEAT_MAP.keys()) + list(CRON_PRESETS.keys())
        return ToolDefinition(
            name="schedule_add",
            description=(
                "Schedule a reminder or recurring task. The agent will send "
                "a notification at the specified time. "
                "Supports intervals (hourly, daily, weekly) and cron presets "
                "(weekdays_9am, weekends_10am, first_of_month, etc.)."
            ),
            parameters=[
                ToolParameter(
                    name="message",
                    type="string",
                    description="What to remind about",
                    required=True,
                ),
                ToolParameter(
                    name="run_at",
                    type="string",
                    description="When to fire (ISO format: 2026-02-21T09:00:00). For cron presets, can be any future date.",
                    required=True,
                ),
                ToolParameter(
                    name="repeat",
                    type="string",
                    description=(
                        "Repeat: intervals (every_5_min, every_15_min, every_30_min, hourly, "
                        "every_2_hours, every_4_hours, every_6_hours, every_12_hours, daily, weekly) "
                        "or cron presets (weekdays_9am, weekdays_18pm, weekends_10am, monday_9am, "
                        "friday_17pm, first_of_month, every_night_23, every_morning_8). "
                        "Leave empty for one-shot."
                    ),
                    required=False,
                    enum=all_repeats,
                ),
            ],
        )

    async def execute(self, message: str, run_at: str, repeat: str | None = None, **kwargs: Any) -> ToolResult:
        try:
            task_id, confirm = await self._service.add_task(message, run_at, repeat)
            return ToolResult(success=True, data=f"[{task_id}] {confirm}")
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Scheduling failed: {e}")


class SchedulerListTool:
    """List all scheduled reminders."""

    def __init__(self, service: SchedulerService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="schedule_list",
            description="List all active scheduled reminders and recurring tasks.",
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        tasks = self._service.list_tasks()
        if not tasks:
            return ToolResult(success=True, data="No scheduled reminders.")

        lines = [f"📋 Scheduled tasks ({len(tasks)}):"]
        for t in tasks:
            repeat_tag = f" [{t['repeat']}]" if t["repeat"] != "one-shot" else ""
            lines.append(f"  [{t['id']}] {t['message']} → {t['run_at']}{repeat_tag}")

        return ToolResult(success=True, data="\n".join(lines))


class SchedulerRemoveTool:
    """Remove a scheduled reminder."""

    def __init__(self, service: SchedulerService) -> None:
        self._service = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="schedule_remove",
            description="Remove a scheduled reminder by its ID.",
            parameters=[
                ToolParameter(
                    name="task_id",
                    type="string",
                    description="Task ID to remove (from schedule_list)",
                    required=True,
                ),
            ],
        )

    async def execute(self, task_id: str, **kwargs: Any) -> ToolResult:
        removed = await self._service.remove_task(task_id)
        if removed:
            return ToolResult(success=True, data=f"Reminder [{task_id}] removed.")
        return ToolResult(success=False, error=f"Reminder [{task_id}] not found.")
