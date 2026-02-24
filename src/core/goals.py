"""
Autonomous Goal Pursuit — long-running background goals.

The owner says "find me an apartment under $30k" and the agent
monitors, searches, filters, and reports findings over days/weeks.

Follows the HeartbeatEngine + CryptoMonitor patterns:
- Persistent JSON state
- Scheduler-driven periodic checks
- Agent callback for LLM-powered research
- Notify callback for Telegram updates

Goal lifecycle: active -> monitoring (periodic checks) -> completed/paused/cancelled
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_FILE = _PROJECT_ROOT / "data" / "goals_state.json"

# Callback types (same as HeartbeatEngine)
NotifyCallback = Callable[[str, str], Coroutine[Any, Any, None]]
AgentCallback = Callable[[str], Coroutine[Any, Any, str]]

# System prompt for goal checks
GOAL_CHECK_PROMPT = (
    "You are executing an AUTONOMOUS GOAL check. The owner set this goal and you "
    "must actively work toward it using your tools.\n\n"
    "GOAL: {description}\n"
    "SUCCESS CRITERIA: {criteria}\n"
    "PREVIOUS FINDINGS ({findings_count} total):\n{recent_findings}\n\n"
    "INSTRUCTIONS:\n"
    "- Use web_search, browser, and any relevant tools to find NEW information\n"
    "- Do NOT repeat old findings — look for FRESH data\n"
    "- If you find something matching the criteria — report it clearly\n"
    "- If nothing new — respond with EXACTLY 'NO_NEW_FINDINGS'\n"
    "- Be specific: prices, links, dates, details\n"
    "- Language: Russian\n"
)

NO_FINDINGS_MARKER = "NO_NEW_FINDINGS"


@dataclass
class Goal:
    """A single autonomous goal."""
    id: str
    description: str
    criteria: str
    status: str  # active, paused, completed, cancelled
    check_interval_minutes: int
    created_at: str
    last_checked: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    max_checks: int = 500  # safety limit (~1 week at 30min intervals)
    checks_done: int = 0

    @staticmethod
    def create(
        description: str,
        criteria: str,
        check_interval_minutes: int = 60,
        max_checks: int = 500,
    ) -> Goal:
        return Goal(
            id=uuid.uuid4().hex[:8],
            description=description,
            criteria=criteria,
            status="active",
            check_interval_minutes=check_interval_minutes,
            created_at=datetime.now().isoformat(),
            max_checks=max_checks,
        )


class GoalStore:
    """Persistent JSON storage for goals."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self._path = path
        self._goals: dict[str, Goal] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for g in data.get("goals", []):
                    goal = Goal(**g)
                    self._goals[goal.id] = goal
                logger.info("Loaded %d goals from %s", len(self._goals), self._path)
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logger.warning("Failed to load goals state: %s", e)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"goals": [asdict(g) for g in self._goals.values()]}
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Failed to save goals state: %s", e)

    def add(self, goal: Goal) -> None:
        self._goals[goal.id] = goal
        self.save()

    def get(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    def remove(self, goal_id: str) -> bool:
        if goal_id in self._goals:
            del self._goals[goal_id]
            self.save()
            return True
        return False

    def list_all(self) -> list[Goal]:
        return list(self._goals.values())

    def list_active(self) -> list[Goal]:
        return [g for g in self._goals.values() if g.status == "active"]

    def update(self, goal: Goal) -> None:
        self._goals[goal.id] = goal
        self.save()


class GoalEngine:
    """Executes autonomous goal checks through the agent pipeline.

    Usage:
        engine = GoalEngine(
            agent_callback=run_agent_prompt,
            notify_callback=send_to_telegram,
            user_id="YOUR_TELEGRAM_ID",
        )
        scheduler.add_job(engine.check, trigger="interval", minutes=15)
    """

    def __init__(
        self,
        agent_callback: AgentCallback,
        notify_callback: NotifyCallback,
        user_id: str,
        store: GoalStore | None = None,
    ) -> None:
        self._agent = agent_callback
        self._notify = notify_callback
        self._user_id = user_id
        self._store = store or GoalStore()
        self._running = False

    @property
    def store(self) -> GoalStore:
        return self._store

    @property
    def running(self) -> bool:
        return self._running

    async def check(self) -> None:
        """Check all active goals. Called by scheduler."""
        if self._running:
            logger.debug("Goal engine already running, skipping")
            return

        self._running = True
        start = time.monotonic()

        try:
            active = self._store.list_active()
            if not active:
                return

            now = datetime.now()
            checked = 0

            for goal in active:
                # Check if it's time (respect per-goal interval)
                if goal.last_checked:
                    try:
                        last = datetime.fromisoformat(goal.last_checked)
                        elapsed_min = (now - last).total_seconds() / 60
                        if elapsed_min < goal.check_interval_minutes:
                            continue
                    except (ValueError, TypeError):
                        pass

                # Safety: max checks reached
                if goal.checks_done >= goal.max_checks:
                    goal.status = "paused"
                    self._store.update(goal)
                    await self._notify(
                        self._user_id,
                        f"Goal paused (max checks reached): {goal.description[:100]}",
                    )
                    continue

                # Execute the check
                try:
                    await self._check_single_goal(goal)
                    checked += 1
                except Exception as e:
                    logger.error("Goal check failed for %s: %s", goal.id, e)

            elapsed = time.monotonic() - start
            if checked:
                logger.info("Goal engine: checked %d/%d goals (%.1fs)", checked, len(active), elapsed)

        except Exception as e:
            logger.error("Goal engine failed: %s", e, exc_info=True)
        finally:
            self._running = False

    async def _check_single_goal(self, goal: Goal) -> None:
        """Run a single goal check through the agent."""
        # Build recent findings summary (last 5)
        recent = goal.findings[-5:] if goal.findings else []
        if recent:
            findings_text = "\n".join(
                f"  [{f.get('timestamp', '?')[:16]}] {f.get('text', '')[:200]}"
                for f in recent
            )
        else:
            findings_text = "  (no previous findings)"

        prompt = GOAL_CHECK_PROMPT.format(
            description=goal.description,
            criteria=goal.criteria,
            findings_count=len(goal.findings),
            recent_findings=findings_text,
        )

        logger.info("Checking goal %s: %s", goal.id, goal.description[:60])
        response = await self._agent(prompt)

        # Update goal state
        goal.last_checked = datetime.now().isoformat()
        goal.checks_done += 1

        # Check if there are new findings
        if response and response.strip():
            cleaned = response.strip()
            is_empty = (
                NO_FINDINGS_MARKER in cleaned.upper()
                or "no_new_findings" in cleaned.lower()
                or "ничего нового" in cleaned.lower() and len(cleaned) < 100
                or "новых данных нет" in cleaned.lower() and len(cleaned) < 100
            )

            if not is_empty:
                # New finding!
                finding = {
                    "timestamp": datetime.now().isoformat(),
                    "text": cleaned[:2000],
                    "check_number": goal.checks_done,
                }
                goal.findings.append(finding)

                # Notify user
                msg = (
                    f"🎯 **Goal Update** (#{goal.checks_done})\n"
                    f"**Goal:** {goal.description[:100]}\n\n"
                    f"{cleaned[:3500]}"
                )
                await self._notify(self._user_id, msg)
                logger.info("Goal %s: new finding (check #%d)", goal.id, goal.checks_done)
            else:
                logger.debug("Goal %s: no new findings (check #%d)", goal.id, goal.checks_done)

        self._store.update(goal)

    async def run_single(self, goal_id: str) -> str | None:
        """Run a single goal check on demand. Returns response or None."""
        goal = self._store.get(goal_id)
        if not goal:
            return None
        await self._check_single_goal(goal)
        return goal.findings[-1]["text"] if goal.findings else "No findings"
