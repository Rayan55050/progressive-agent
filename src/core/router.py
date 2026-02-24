"""
Message router — selects the appropriate skill and model for each message.

Uses keyword matching first, then falls back to LLM classification (stub).
Also selects the appropriate model tier: simple queries go to Haiku,
complex ones to Sonnet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill protocol (defined here to avoid circular imports with skills module)
# ---------------------------------------------------------------------------


@runtime_checkable
class Skill(Protocol):
    """Minimal skill interface used by the Router.

    The full Skill implementation lives in src/skills/ and is loaded
    from SKILL.md files. The Router only needs these fields.
    """

    @property
    def name(self) -> str:
        """Unique skill name."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    def trigger_keywords(self) -> list[str]:
        """Keywords that trigger this skill."""
        ...

    @property
    def tools(self) -> list[str]:
        """Tool names required by this skill."""
        ...

    @property
    def instructions(self) -> str:
        """Full skill instructions (markdown body)."""
        ...


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RoutingResult:
    """Result of routing a message to a skill and model."""

    skill: Skill | None = None
    model: str = ""
    confidence: float = 0.0


@dataclass
class SkillMatch:
    """Internal: a skill matched by keyword with its score."""

    skill: Skill
    score: float
    matched_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Complexity heuristics
# ---------------------------------------------------------------------------

# Keywords/patterns that suggest a complex query needing Sonnet
COMPLEX_INDICATORS: list[str] = [
    "analyze",
    "explain",
    "compare",
    "summarize",
    "write",
    "create",
    "plan",
    "design",
    "review",
    "debug",
    "refactor",
    "анализ",
    "объясни",
    "сравни",
    "напиши",
    "создай",
    "план",
    "спроектируй",
]


def _estimate_complexity(text: str) -> str:
    """Estimate message complexity to select model tier.

    Simple heuristic: check for complex indicators and message length.

    Args:
        text: User message text.

    Returns:
        'simple' or 'complex'.
    """
    text_lower = text.lower()

    # Long messages are likely complex
    if len(text) > 200:
        return "complex"

    # Check for complexity indicator words
    for indicator in COMPLEX_INDICATORS:
        if indicator in text_lower:
            return "complex"

    return "simple"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class Router:
    """Routes incoming messages to skills and selects model tier.

    Strategy:
    1. Try keyword matching against skill trigger_keywords.
    2. If no match or low confidence, use LLM classification (stub for now).
    3. Select model: simple queries -> haiku, complex -> sonnet.
    """

    def __init__(
        self,
        default_model: str = "claude-sonnet-4-5-20250929",
        fast_model: str = "claude-haiku-4-5-20251001",
        keyword_confidence_threshold: float = 0.5,
    ) -> None:
        self._default_model = default_model
        self._fast_model = fast_model
        self._keyword_confidence_threshold = keyword_confidence_threshold

        logger.info(
            "Router initialized: default_model=%s, fast_model=%s",
            default_model,
            fast_model,
        )

    async def route(
        self,
        message: str,
        available_skills: list[Any],
    ) -> RoutingResult:
        """Route a message to the best skill and model.

        Args:
            message: User message text.
            available_skills: List of available Skill objects.

        Returns:
            RoutingResult with matched skill, selected model, and confidence.
        """
        if not message or not message.strip():
            model = self._select_model(message or "")
            logger.debug("Empty message, no skill matched, model=%s", model)
            return RoutingResult(skill=None, model=model, confidence=0.0)

        # Step 1: Keyword matching
        match = self._keyword_match(message, available_skills)

        if match is not None and match.score >= self._keyword_confidence_threshold:
            model = self._select_model(message)
            logger.info(
                "Keyword match: skill=%s, confidence=%.2f, keywords=%s, model=%s",
                match.skill.name,
                match.score,
                match.matched_keywords,
                model,
            )
            return RoutingResult(
                skill=match.skill,
                model=model,
                confidence=match.score,
            )

        # Step 2: LLM classification (stub — returns default)
        result = await self._llm_classify(message, available_skills)
        logger.info(
            "LLM classify (stub): skill=%s, model=%s, confidence=%.2f",
            result.skill.name if result.skill else None,
            result.model,
            result.confidence,
        )
        return result

    def _keyword_match(
        self,
        message: str,
        skills: list[Any],
    ) -> SkillMatch | None:
        """Match message against skill trigger keywords.

        Scores each skill by how many of its keywords appear in the message.
        Returns the best match or None if no keywords match.

        Args:
            message: User message text.
            skills: Available skills.

        Returns:
            Best SkillMatch or None.
        """
        message_lower = message.lower()
        best_match: SkillMatch | None = None
        best_score = 0.0

        for skill in skills:
            if not hasattr(skill, "trigger_keywords"):
                continue

            keywords = skill.trigger_keywords
            if not keywords:
                continue

            matched: list[str] = []
            for kw in keywords:
                if kw.lower() in message_lower:
                    matched.append(kw)

            if not matched:
                continue

            # Score based on number of matches (not fraction of total keywords).
            # 1 match = 0.5, 2 matches = 0.7, 3+ matches = 0.9
            # This avoids penalizing skills with many trigger keywords.
            if len(matched) >= 3:
                score = 0.9
            elif len(matched) == 2:
                score = 0.7
            else:
                score = 0.5

            if score > best_score:
                best_score = score
                best_match = SkillMatch(
                    skill=skill,
                    score=score,
                    matched_keywords=matched,
                )

        return best_match

    async def _llm_classify(
        self,
        message: str,
        skills: list[Any],
    ) -> RoutingResult:
        """Classify message using LLM (stub implementation).

        In Phase 2+, this will send the message and skill descriptions
        to a fast model (Haiku) for classification. For now, returns
        default routing with no skill.

        Args:
            message: User message text.
            skills: Available skills.

        Returns:
            RoutingResult with default model and no skill.
        """
        # Stub: return default model, no specific skill
        model = self._select_model(message)
        return RoutingResult(
            skill=None,
            model=model,
            confidence=0.3,  # Low confidence since this is a stub
        )

    def _select_model(self, message: str) -> str:
        """Select model tier based on message complexity.

        Currently always returns default_model (Opus 4.6).
        Multi-model routing will be enabled in Phase 2 when the
        LLM classifier replaces the stub.

        Args:
            message: User message text.

        Returns:
            Model identifier string.
        """
        # TODO: re-enable multi-model routing when LLM classifier is ready
        # complexity = _estimate_complexity(message)
        # if complexity == "simple":
        #     return self._fast_model
        return self._default_model
