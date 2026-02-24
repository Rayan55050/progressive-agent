"""
Self-Improving Agent — learns from errors and saves lessons to AGENTS.md.

Pattern inspired by OpenClaw/ZeroClaw: after each tool failure or user correction,
the agent can save a lesson. These lessons are injected into the system prompt
on every restart, making the agent progressively smarter.

The AGENTS.md file is a markdown file with sections for different lesson types.
Lessons are appended under the appropriate section header.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_FILE = PROJECT_ROOT / "AGENTS.md"

# Max file size to prevent runaway growth (50KB)
MAX_FILE_SIZE = 50_000

# Sections in AGENTS.md
VALID_SECTIONS = [
    "Tool Usage Lessons",
    "Error Patterns",
    "User Preferences",
    "API Quirks",
    "Performance Notes",
]


class SelfImproveTool:
    """Save and recall agent learnings for self-improvement.

    This tool allows the agent to:
    - Save lessons learned from errors or discoveries
    - Read all current learnings
    - Remove outdated lessons

    Lessons are stored in AGENTS.md and injected into the system prompt.
    """

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learn",
            description=(
                "Save or read agent learnings (self-improvement). "
                "Actions: 'save' — save a lesson learned (from an error, user feedback, discovery); "
                "'read' — show all current learnings; "
                "'remove' — remove an outdated lesson by its text. "
                "Sections: 'tools', 'errors', 'preferences', 'api', 'performance'. "
                "Use this when you make a mistake, discover something, or get user feedback."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'save', 'read', or 'remove'",
                    required=True,
                    enum=["save", "read", "remove"],
                ),
                ToolParameter(
                    name="section",
                    type="string",
                    description="Section: 'tools', 'errors', 'preferences', 'api', 'performance'",
                    required=False,
                    enum=["tools", "errors", "preferences", "api", "performance"],
                ),
                ToolParameter(
                    name="lesson",
                    type="string",
                    description="The lesson text to save or remove",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()

        try:
            if action == "save":
                return self._save_lesson(kwargs)
            elif action == "read":
                return self._read_lessons()
            elif action == "remove":
                return self._remove_lesson(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("Self-improve error: %s", e)
            return ToolResult(success=False, error=f"Self-improve error: {e}")

    def _section_name(self, short: str) -> str:
        """Map short section name to full header."""
        mapping = {
            "tools": "Tool Usage Lessons",
            "errors": "Error Patterns",
            "preferences": "User Preferences",
            "api": "API Quirks",
            "performance": "Performance Notes",
        }
        return mapping.get(short, "Tool Usage Lessons")

    def _save_lesson(self, kwargs: dict) -> ToolResult:
        section_key = kwargs.get("section", "tools").strip().lower()
        lesson = kwargs.get("lesson", "").strip()

        if not lesson:
            return ToolResult(success=False, error="No lesson text provided")

        section_header = self._section_name(section_key)
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{timestamp}] {lesson}"

        # Read current file
        content = ""
        if AGENTS_FILE.exists():
            content = AGENTS_FILE.read_text(encoding="utf-8")

        # Check size limit
        if len(content) > MAX_FILE_SIZE:
            return ToolResult(
                success=False,
                error=f"AGENTS.md is too large ({len(content)} chars). Remove old lessons first.",
            )

        # Check if this lesson already exists (dedup)
        if lesson.lower() in content.lower():
            return ToolResult(success=True, data="Lesson already exists, skipping duplicate.")

        # Find the section and append after the comment line
        section_pattern = rf"(## {re.escape(section_header)}\n<!-- .+? -->)"
        match = re.search(section_pattern, content)

        if match:
            insert_pos = match.end()
            new_content = content[:insert_pos] + f"\n{entry}" + content[insert_pos:]
        else:
            # Section not found, append at end
            new_content = content.rstrip() + f"\n\n## {section_header}\n{entry}\n"

        AGENTS_FILE.write_text(new_content, encoding="utf-8")
        logger.info("Saved lesson to %s: %s", section_header, lesson[:80])
        return ToolResult(success=True, data=f"Lesson saved to '{section_header}':\n{entry}")

    def _read_lessons(self) -> ToolResult:
        if not AGENTS_FILE.exists():
            return ToolResult(success=True, data="No learnings yet (AGENTS.md not found)")

        content = AGENTS_FILE.read_text(encoding="utf-8")

        # Count lessons (lines starting with '- [')
        lesson_count = len(re.findall(r"^- \[", content, re.MULTILINE))

        if lesson_count == 0:
            return ToolResult(success=True, data="No lessons saved yet.")

        return ToolResult(
            success=True,
            data=f"Agent learnings ({lesson_count} lessons, {len(content)} chars):\n\n{content}",
        )

    def _remove_lesson(self, kwargs: dict) -> ToolResult:
        lesson = kwargs.get("lesson", "").strip()
        if not lesson:
            return ToolResult(success=False, error="No lesson text to remove")

        if not AGENTS_FILE.exists():
            return ToolResult(success=False, error="AGENTS.md not found")

        content = AGENTS_FILE.read_text(encoding="utf-8")
        lines = content.split("\n")
        new_lines = []
        removed = False

        for line in lines:
            if lesson.lower() in line.lower() and line.strip().startswith("- ["):
                removed = True
                continue
            new_lines.append(line)

        if not removed:
            return ToolResult(success=False, error=f"Lesson not found: {lesson[:80]}")

        AGENTS_FILE.write_text("\n".join(new_lines), encoding="utf-8")
        logger.info("Removed lesson: %s", lesson[:80])
        return ToolResult(success=True, data=f"Lesson removed: {lesson[:80]}")


def load_agents_md() -> str:
    """Load AGENTS.md content for injection into system prompt.

    Returns empty string if file doesn't exist or has no lessons.
    Called during agent startup.
    """
    if not AGENTS_FILE.exists():
        return ""

    try:
        content = AGENTS_FILE.read_text(encoding="utf-8")
        # Only include if there are actual lessons
        if not re.search(r"^- \[", content, re.MULTILINE):
            return ""
        return content
    except OSError:
        return ""
