"""
Multi-Agent Orchestrator — parallel sub-agents for complex tasks.

Spawns N parallel LLM calls through the Claude proxy (subscription-based,
no per-token cost). Each sub-agent gets its own task and system prompt.
Results are collected and optionally synthesized.

Key constraint: ONLY uses the Claude subscription proxy — no paid API fallbacks.
This is safe because the subscription is flat-rate (unlimited).

Usage:
    orchestrator = MultiAgentOrchestrator(provider=proxy_provider)
    result = await orchestrator.run(tasks=[...], synthesis_prompt="...")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.core.llm import LLMProvider, LLMResponse, FallbackProvider

logger = logging.getLogger(__name__)

# Maximum parallel agents to prevent proxy overload
MAX_PARALLEL_AGENTS = 5

# Max tokens for sub-agent responses (keep it focused)
SUB_AGENT_MAX_TOKENS = 4096

# System prompt prefix for sub-agents
SUB_AGENT_SYSTEM = (
    "You are a specialized research sub-agent. "
    "You have been assigned a specific task as part of a larger request.\n"
    "- Focus ONLY on your assigned task\n"
    "- Be concise and factual\n"
    "- Structure your findings clearly\n"
    "- If you can't find information, say so explicitly\n"
    "- Language: use the same language as the task\n\n"
    "Your role: {role}\n"
    "Your task:\n"
)


@dataclass
class SubAgentTask:
    """A task for a single sub-agent."""
    role: str  # e.g., "researcher", "analyst", "reviewer"
    prompt: str  # the specific task
    system: str | None = None  # optional custom system prompt


@dataclass
class SubAgentResult:
    """Result from a single sub-agent."""
    role: str
    prompt: str
    response: str
    success: bool
    elapsed_sec: float
    error: str | None = None


@dataclass
class OrchestratorResult:
    """Combined result from all sub-agents."""
    results: list[SubAgentResult]
    synthesis: str | None = None
    total_elapsed_sec: float = 0.0


def _get_proxy_provider(provider: LLMProvider) -> LLMProvider:
    """Extract the proxy-only provider from FallbackProvider.

    This ensures we ONLY use the subscription proxy (no paid API calls).
    If the provider is already a direct provider, return it as-is.
    """
    if isinstance(provider, FallbackProvider):
        return provider._primary  # ClaudeSubscriptionProvider
    return provider


class MultiAgentOrchestrator:
    """Run multiple LLM calls in parallel through the Claude proxy.

    All calls go through the subscription proxy — zero additional cost.
    """

    def __init__(
        self,
        provider: LLMProvider,
        max_parallel: int = MAX_PARALLEL_AGENTS,
    ) -> None:
        self._provider = _get_proxy_provider(provider)
        self._max_parallel = max_parallel
        logger.info(
            "MultiAgentOrchestrator initialized: provider=%s, max_parallel=%d",
            self._provider.name,
            max_parallel,
        )

    async def run(
        self,
        tasks: list[SubAgentTask],
        synthesis_prompt: str | None = None,
    ) -> OrchestratorResult:
        """Execute multiple sub-agent tasks in parallel.

        Args:
            tasks: List of tasks to execute.
            synthesis_prompt: Optional prompt to synthesize all results.

        Returns:
            OrchestratorResult with all sub-agent results + optional synthesis.
        """
        if not tasks:
            return OrchestratorResult(results=[])

        # Limit parallel agents
        tasks = tasks[:self._max_parallel]
        start = time.monotonic()

        logger.info("Orchestrator: launching %d parallel sub-agents", len(tasks))

        # Run all tasks in parallel
        coros = [self._run_single(task) for task in tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Process results
        agent_results: list[SubAgentResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                agent_results.append(SubAgentResult(
                    role=tasks[i].role,
                    prompt=tasks[i].prompt[:200],
                    response="",
                    success=False,
                    elapsed_sec=0.0,
                    error=str(result),
                ))
            else:
                agent_results.append(result)

        total_elapsed = time.monotonic() - start
        success_count = sum(1 for r in agent_results if r.success)
        logger.info(
            "Orchestrator: %d/%d agents succeeded (%.1fs total)",
            success_count, len(agent_results), total_elapsed,
        )

        # Optional synthesis step
        synthesis = None
        if synthesis_prompt and success_count > 0:
            synthesis = await self._synthesize(agent_results, synthesis_prompt)

        return OrchestratorResult(
            results=agent_results,
            synthesis=synthesis,
            total_elapsed_sec=total_elapsed,
        )

    async def _run_single(self, task: SubAgentTask) -> SubAgentResult:
        """Execute a single sub-agent task."""
        start = time.monotonic()

        system = task.system or SUB_AGENT_SYSTEM.format(role=task.role)
        messages = [{"role": "user", "content": task.prompt}]

        try:
            response: LLMResponse = await self._provider.complete(
                messages=messages,
                tools=None,  # Sub-agents don't get tools (focused research)
                stream=False,
                system=system,
            )

            elapsed = time.monotonic() - start
            logger.debug(
                "Sub-agent '%s' completed in %.1fs (%d chars)",
                task.role, elapsed, len(response.content),
            )

            return SubAgentResult(
                role=task.role,
                prompt=task.prompt[:200],
                response=response.content,
                success=True,
                elapsed_sec=elapsed,
            )

        except Exception as e:
            elapsed = time.monotonic() - start
            logger.warning("Sub-agent '%s' failed: %s", task.role, e)
            return SubAgentResult(
                role=task.role,
                prompt=task.prompt[:200],
                response="",
                success=False,
                elapsed_sec=elapsed,
                error=str(e)[:500],
            )

    async def _synthesize(
        self,
        results: list[SubAgentResult],
        synthesis_prompt: str,
    ) -> str | None:
        """Combine sub-agent results into a final synthesis."""
        # Build context from all successful results
        parts: list[str] = []
        for r in results:
            if r.success and r.response:
                parts.append(f"=== {r.role.upper()} ===\n{r.response}\n")

        if not parts:
            return None

        context = "\n".join(parts)
        # Truncate if too long
        if len(context) > 30000:
            context = context[:30000] + "\n\n... (truncated)"

        system = (
            "You are a synthesis agent. Multiple research agents have gathered "
            "information on different aspects of a question. Your job is to combine "
            "their findings into a coherent, well-structured answer.\n"
            "- Merge overlapping information\n"
            "- Highlight key findings from each agent\n"
            "- Resolve contradictions if any\n"
            "- Be concise but comprehensive\n"
            "- Language: use the same language as the input\n"
        )

        messages = [{
            "role": "user",
            "content": f"{synthesis_prompt}\n\n--- RESEARCH RESULTS ---\n{context}",
        }]

        try:
            response = await self._provider.complete(
                messages=messages,
                tools=None,
                stream=False,
                system=system,
            )
            logger.info("Synthesis completed (%d chars)", len(response.content))
            return response.content
        except Exception as e:
            logger.warning("Synthesis failed: %s", e)
            return None
