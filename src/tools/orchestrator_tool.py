"""
Multi-Agent Orchestrator Tool — spawn parallel sub-agents for complex tasks.

The agent calls this tool when a task benefits from parallel research.
Example: "Compare iPhone 16 vs Samsung S25" -> 2 parallel agents, each
researching one phone, then synthesis combines both.

All sub-agents use the Claude subscription proxy — zero additional cost.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.orchestrator import MultiAgentOrchestrator, SubAgentTask
from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class OrchestratorTool:
    """Tool for spawning parallel sub-agents."""

    def __init__(self, orchestrator: MultiAgentOrchestrator) -> None:
        self._orchestrator = orchestrator

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="multi_agent",
            description=(
                "Запуск параллельных sub-агентов для сложных задач. "
                "Каждый агент получает свою роль и задачу, работает независимо, "
                "результаты объединяются в финальный ответ. "
                "Max 5 агентов параллельно. Все через подписку Claude — бесплатно. "
                "Используй когда: 'сравни X vs Y', 'проанализируй с разных сторон', "
                "'исследуй несколько вариантов', 'собери инфо из нескольких источников'. "
                "НЕ используй для простых запросов — только для задач, где параллельность даёт выигрыш."
            ),
            parameters=[
                ToolParameter(
                    name="tasks",
                    type="string",
                    description=(
                        "JSON array of tasks. Each task: {\"role\": \"researcher/analyst/...\", "
                        "\"prompt\": \"specific task description\"}. "
                        "Example: [{\"role\": \"iPhone researcher\", \"prompt\": \"Find specs, price, reviews of iPhone 16\"}, "
                        "{\"role\": \"Samsung researcher\", \"prompt\": \"Find specs, price, reviews of Samsung S25\"}]"
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="synthesis_prompt",
                    type="string",
                    description=(
                        "Optional: prompt for combining results. "
                        "Example: 'Compare both phones and recommend the best one for a power user.'"
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        tasks_json = kwargs.get("tasks", "")
        synthesis_prompt = kwargs.get("synthesis_prompt", "")

        if not tasks_json:
            return ToolResult(success=False, error="tasks parameter is required (JSON array)")

        # Parse tasks
        try:
            if isinstance(tasks_json, str):
                tasks_data = json.loads(tasks_json)
            else:
                tasks_data = tasks_json
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON in tasks: {e}")

        if not isinstance(tasks_data, list) or not tasks_data:
            return ToolResult(success=False, error="tasks must be a non-empty JSON array")

        if len(tasks_data) > 5:
            return ToolResult(success=False, error="Maximum 5 parallel agents allowed")

        # Convert to SubAgentTask objects
        sub_tasks: list[SubAgentTask] = []
        for i, t in enumerate(tasks_data):
            if not isinstance(t, dict):
                return ToolResult(success=False, error=f"Task #{i+1} must be a JSON object")
            role = t.get("role", f"agent_{i+1}")
            prompt = t.get("prompt", "")
            if not prompt:
                return ToolResult(success=False, error=f"Task #{i+1} missing 'prompt' field")
            sub_tasks.append(SubAgentTask(role=role, prompt=prompt))

        # Execute
        try:
            logger.info("Orchestrator tool: launching %d sub-agents", len(sub_tasks))
            result = await self._orchestrator.run(
                tasks=sub_tasks,
                synthesis_prompt=synthesis_prompt or None,
            )
        except Exception as e:
            logger.exception("Orchestrator tool error")
            return ToolResult(success=False, error=f"Orchestration failed: {e}")

        # Format results
        lines: list[str] = []
        success_count = sum(1 for r in result.results if r.success)
        lines.append(
            f"Multi-Agent Results: {success_count}/{len(result.results)} agents succeeded "
            f"({result.total_elapsed_sec:.1f}s total)\n"
        )

        for r in result.results:
            status = "OK" if r.success else "FAILED"
            lines.append(f"--- {r.role.upper()} [{status}, {r.elapsed_sec:.1f}s] ---")
            if r.success:
                # Truncate long responses
                text = r.response[:2000] if len(r.response) > 2000 else r.response
                lines.append(text)
            else:
                lines.append(f"Error: {r.error}")
            lines.append("")

        if result.synthesis:
            lines.append("=== SYNTHESIS ===")
            synthesis_text = result.synthesis[:3000] if len(result.synthesis) > 3000 else result.synthesis
            lines.append(synthesis_text)

        answer = "\n".join(lines)
        # Hard limit to avoid tool result truncation
        if len(answer) > 15000:
            answer = answer[:14500] + "\n\n... (truncated)"

        return ToolResult(success=True, data={
            "answer": answer,
            "agents_total": len(result.results),
            "agents_succeeded": success_count,
            "elapsed_sec": result.total_elapsed_sec,
            "has_synthesis": result.synthesis is not None,
        })
