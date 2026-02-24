"""
Goal Pursuit Tool — manage autonomous long-running goals.

The agent can create, list, check, pause, resume, complete, and delete goals.
Goals run in the background via scheduler, but can also be checked on demand.

Example: "Find me an apartment under $30k" — the agent creates
a goal and monitors real estate sites periodically, reporting findings.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.goals import Goal, GoalEngine
from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class GoalTool:
    """Tool for managing autonomous goals."""

    def __init__(self, engine: GoalEngine) -> None:
        self._engine = engine

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="goal",
            description=(
                "Управление автономными целями. Агент создаёт цель — и она мониторится "
                "в фоне днями/неделями, пока не будет достигнута. "
                "Actions: 'create' — создать новую цель с критериями; "
                "'list' — показать все цели и их статус; "
                "'check' — проверить цель прямо сейчас (не ждать scheduler); "
                "'pause' — приостановить мониторинг цели; "
                "'resume' — возобновить приостановленную цель; "
                "'complete' — отметить цель как достигнутую; "
                "'delete' — удалить цель навсегда; "
                "'findings' — показать все находки по цели. "
                "Используй когда: 'найди мне квартиру', 'мониторь цену BTC до $90k', "
                "'следи за вакансиями Python senior', 'ищи авто до $15k'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: create, list, check, pause, resume, complete, delete, findings",
                    required=True,
                    enum=["create", "list", "check", "pause", "resume", "complete", "delete", "findings"],
                ),
                ToolParameter(
                    name="goal_id",
                    type="string",
                    description="Goal ID (for check/pause/resume/complete/delete/findings)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Goal description in natural language (for 'create')",
                    required=False,
                ),
                ToolParameter(
                    name="criteria",
                    type="string",
                    description="Success criteria — when is the goal achieved? (for 'create')",
                    required=False,
                ),
                ToolParameter(
                    name="interval_minutes",
                    type="integer",
                    description="Check interval in minutes (default 60, min 15, max 1440)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "list")

        try:
            if action == "create":
                return self._create(kwargs)
            elif action == "list":
                return self._list()
            elif action == "check":
                return await self._check(kwargs)
            elif action == "pause":
                return self._set_status(kwargs, "paused")
            elif action == "resume":
                return self._set_status(kwargs, "active")
            elif action == "complete":
                return self._set_status(kwargs, "completed")
            elif action == "delete":
                return self._delete(kwargs)
            elif action == "findings":
                return self._findings(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("Goal tool error")
            return ToolResult(success=False, error=f"Goal error: {e}")

    def _create(self, kwargs: dict) -> ToolResult:
        desc = kwargs.get("description", "")
        criteria = kwargs.get("criteria", "")
        if not desc:
            return ToolResult(success=False, error="description is required for 'create'")
        if not criteria:
            return ToolResult(success=False, error="criteria is required for 'create'")

        interval = max(15, min(1440, int(kwargs.get("interval_minutes", 60))))

        goal = Goal.create(
            description=desc,
            criteria=criteria,
            check_interval_minutes=interval,
        )
        self._engine.store.add(goal)

        return ToolResult(success=True, data={
            "answer": (
                f"Goal created!\n"
                f"ID: {goal.id}\n"
                f"Description: {goal.description}\n"
                f"Criteria: {goal.criteria}\n"
                f"Check interval: every {interval} min\n"
                f"Status: active\n\n"
                f"The goal will be checked automatically in the background. "
                f"You'll get notifications when new findings appear."
            ),
            "goal_id": goal.id,
        })

    def _list(self) -> ToolResult:
        goals = self._engine.store.list_all()
        if not goals:
            return ToolResult(success=True, data={
                "answer": "No goals set. Create one with action='create'.",
            })

        lines = [f"Goals ({len(goals)} total):\n"]
        for g in goals:
            status_icon = {
                "active": "🟢",
                "paused": "⏸️",
                "completed": "✅",
                "cancelled": "❌",
            }.get(g.status, "❓")

            lines.append(
                f"{status_icon} **{g.id}** — {g.description[:80]}\n"
                f"   Status: {g.status} | Checks: {g.checks_done}/{g.max_checks} | "
                f"Findings: {len(g.findings)} | Interval: {g.check_interval_minutes}m\n"
                f"   Last checked: {g.last_checked or 'never'}"
            )

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "count": len(goals),
        })

    async def _check(self, kwargs: dict) -> ToolResult:
        goal_id = kwargs.get("goal_id", "")
        if not goal_id:
            return ToolResult(success=False, error="goal_id is required for 'check'")

        result = await self._engine.run_single(goal_id)
        if result is None:
            return ToolResult(success=False, error=f"Goal not found: {goal_id}")

        return ToolResult(success=True, data={
            "answer": f"Goal check completed.\n\nResult:\n{result[:3000]}",
        })

    def _set_status(self, kwargs: dict, status: str) -> ToolResult:
        goal_id = kwargs.get("goal_id", "")
        if not goal_id:
            return ToolResult(success=False, error="goal_id is required")

        goal = self._engine.store.get(goal_id)
        if not goal:
            return ToolResult(success=False, error=f"Goal not found: {goal_id}")

        old_status = goal.status
        goal.status = status
        self._engine.store.update(goal)

        return ToolResult(success=True, data={
            "answer": f"Goal {goal_id} status: {old_status} -> {status}",
        })

    def _delete(self, kwargs: dict) -> ToolResult:
        goal_id = kwargs.get("goal_id", "")
        if not goal_id:
            return ToolResult(success=False, error="goal_id is required for 'delete'")

        if self._engine.store.remove(goal_id):
            return ToolResult(success=True, data={
                "answer": f"Goal {goal_id} deleted.",
            })
        return ToolResult(success=False, error=f"Goal not found: {goal_id}")

    def _findings(self, kwargs: dict) -> ToolResult:
        goal_id = kwargs.get("goal_id", "")
        if not goal_id:
            return ToolResult(success=False, error="goal_id is required for 'findings'")

        goal = self._engine.store.get(goal_id)
        if not goal:
            return ToolResult(success=False, error=f"Goal not found: {goal_id}")

        if not goal.findings:
            return ToolResult(success=True, data={
                "answer": f"Goal {goal_id}: no findings yet ({goal.checks_done} checks done).",
            })

        lines = [f"Findings for goal '{goal.description[:60]}' ({len(goal.findings)} total):\n"]
        for i, f in enumerate(goal.findings, 1):
            ts = f.get("timestamp", "?")[:16]
            text = f.get("text", "")[:300]
            lines.append(f"--- Finding #{i} ({ts}) ---\n{text}\n")

        answer = "\n".join(lines)
        if len(answer) > 4000:
            answer = answer[:3950] + "\n\n... (truncated)"

        return ToolResult(success=True, data={
            "answer": answer,
            "count": len(goal.findings),
        })
