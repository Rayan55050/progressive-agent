"""
Tests for skills system:
- SkillLoader.load_file() (parse YAML frontmatter + markdown body)
- SkillLoader.load_file() (malformed files)
- SkillRegistry.load() (load from directory)
- SkillRegistry.find_by_keyword() (keyword matching)
- SkillExecutor.execute() (prompt building)
- SearchTool.definition (schema)
- SearchTool.execute() (mock Tavily)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.tools import ToolDefinition, ToolResult
from src.skills.executor import SkillExecutor
from src.skills.loader import Skill, SkillLoader
from src.skills.registry import SkillRegistry
from src.tools.search_tool import SearchTool


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def valid_skill_md(tmp_path: Path) -> Path:
    """Create a valid SKILL.md file."""
    skill_dir = tmp_path / "web_search"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """\
---
name: web_search
description: Search the web for information
tools:
  - web_search
trigger_keywords:
  - search
  - find
  - look up
---

# Web Search

Use the web_search tool to find information on the internet.

## Instructions
1. Parse the user query
2. Call web_search
3. Summarize results
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def malformed_skill_no_frontmatter(tmp_path: Path) -> Path:
    """Create a SKILL.md file without frontmatter delimiters."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("No frontmatter here, just text.", encoding="utf-8")
    return skill_file


@pytest.fixture
def malformed_skill_no_closing_delimiter(tmp_path: Path) -> Path:
    """Create a SKILL.md file with opening but no closing ---."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """\
---
name: broken
description: This is broken
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def malformed_skill_no_name(tmp_path: Path) -> Path:
    """Create a SKILL.md file without required 'name' field."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """\
---
description: Missing name field
tools: []
---

Body text here.
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def malformed_skill_invalid_yaml(tmp_path: Path) -> Path:
    """Create a SKILL.md file with invalid YAML in frontmatter."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """\
---
name: [broken yaml
  invalid: : colon
---

Body text.
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def skills_directory(tmp_path: Path) -> Path:
    """Create a skills directory structure with multiple skills."""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()

    # Skill 1: web_search
    ws_dir = skills_root / "web_search"
    ws_dir.mkdir()
    (ws_dir / "SKILL.md").write_text(
        """\
---
name: web_search
description: Search the web
tools:
  - web_search
trigger_keywords:
  - search
  - find
---

Search instructions here.
""",
        encoding="utf-8",
    )

    # Skill 2: code_review
    cr_dir = skills_root / "code_review"
    cr_dir.mkdir()
    (cr_dir / "SKILL.md").write_text(
        """\
---
name: code_review
description: Review code
tools:
  - read_file
trigger_keywords:
  - review
  - check code
---

Code review instructions.
""",
        encoding="utf-8",
    )

    # Directory without SKILL.md (should be skipped)
    empty_dir = skills_root / "empty_skill"
    empty_dir.mkdir()

    # A regular file (not a directory, should be skipped)
    (skills_root / "README.md").write_text("# Skills", encoding="utf-8")

    return skills_root


@pytest.fixture
def sample_skill() -> Skill:
    """Create a sample Skill object."""
    return Skill(
        name="web_search",
        description="Search the web for information",
        tools=["web_search"],
        trigger_keywords=["search", "find", "look up"],
        instructions="Use the web_search tool to find information.",
    )


# =========================================================================
# Tests: SkillLoader.load_file()
# =========================================================================


class TestSkillLoader:
    """Tests for SkillLoader."""

    @pytest.mark.asyncio
    async def test_load_file_valid(self, valid_skill_md: Path) -> None:
        """load_file() correctly parses a valid SKILL.md."""
        loader = SkillLoader()
        skill = await loader.load_file(valid_skill_md)

        assert skill.name == "web_search"
        assert skill.description == "Search the web for information"
        assert skill.tools == ["web_search"]
        assert "search" in skill.trigger_keywords
        assert "find" in skill.trigger_keywords
        assert "look up" in skill.trigger_keywords
        assert "# Web Search" in skill.instructions
        assert "web_search" in skill.instructions

    @pytest.mark.asyncio
    async def test_load_file_not_found(self, tmp_path: Path) -> None:
        """load_file() raises FileNotFoundError for missing file."""
        loader = SkillLoader()
        with pytest.raises(FileNotFoundError):
            await loader.load_file(tmp_path / "nonexistent" / "SKILL.md")

    @pytest.mark.asyncio
    async def test_load_file_no_frontmatter(
        self, malformed_skill_no_frontmatter: Path
    ) -> None:
        """load_file() raises ValueError when file lacks frontmatter."""
        loader = SkillLoader()
        with pytest.raises(ValueError, match="must start with"):
            await loader.load_file(malformed_skill_no_frontmatter)

    @pytest.mark.asyncio
    async def test_load_file_no_closing_delimiter(
        self, malformed_skill_no_closing_delimiter: Path
    ) -> None:
        """load_file() raises ValueError when closing --- is missing."""
        loader = SkillLoader()
        with pytest.raises(ValueError, match="missing closing"):
            await loader.load_file(malformed_skill_no_closing_delimiter)

    @pytest.mark.asyncio
    async def test_load_file_no_name(self, malformed_skill_no_name: Path) -> None:
        """load_file() raises ValueError when 'name' field is missing."""
        loader = SkillLoader()
        with pytest.raises(ValueError, match="missing required 'name'"):
            await loader.load_file(malformed_skill_no_name)

    @pytest.mark.asyncio
    async def test_load_file_invalid_yaml(
        self, malformed_skill_invalid_yaml: Path
    ) -> None:
        """load_file() raises ValueError for invalid YAML."""
        loader = SkillLoader()
        with pytest.raises(ValueError, match="Invalid YAML"):
            await loader.load_file(malformed_skill_invalid_yaml)

    @pytest.mark.asyncio
    async def test_load_directory(self, skills_directory: Path) -> None:
        """load_directory() loads all SKILL.md files from subdirectories."""
        loader = SkillLoader()
        skills = await loader.load_directory(skills_directory)

        assert len(skills) == 2
        names = {s.name for s in skills}
        assert "web_search" in names
        assert "code_review" in names

    @pytest.mark.asyncio
    async def test_load_directory_nonexistent(self, tmp_path: Path) -> None:
        """load_directory() returns empty list for non-existent directory."""
        loader = SkillLoader()
        result = await loader.load_directory(tmp_path / "nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_file_tools_as_string(self, tmp_path: Path) -> None:
        """load_file() handles tools as a single string (not list)."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            """\
---
name: single_tool
description: Test
tools: web_search
trigger_keywords: search
---

Body.
""",
            encoding="utf-8",
        )
        loader = SkillLoader()
        skill = await loader.load_file(skill_file)
        assert skill.tools == ["web_search"]
        assert skill.trigger_keywords == ["search"]


# =========================================================================
# Tests: SkillRegistry
# =========================================================================


class TestSkillRegistry:
    """Tests for SkillRegistry."""

    @pytest.mark.asyncio
    async def test_load(self, skills_directory: Path) -> None:
        """SkillRegistry.load() loads skills from directory."""
        registry = SkillRegistry(skills_dir=str(skills_directory))
        await registry.load()

        skills = registry.list_skills()
        assert len(skills) == 2

    @pytest.mark.asyncio
    async def test_get_skill(self, skills_directory: Path) -> None:
        """SkillRegistry.get() returns skill by name."""
        registry = SkillRegistry(skills_dir=str(skills_directory))
        await registry.load()

        skill = registry.get("web_search")
        assert skill is not None
        assert skill.name == "web_search"

        assert registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_find_by_keyword(self, skills_directory: Path) -> None:
        """SkillRegistry.find_by_keyword() matches skill by keyword in text."""
        registry = SkillRegistry(skills_dir=str(skills_directory))
        await registry.load()

        # Should match web_search
        skill = registry.find_by_keyword("please search for Python tutorials")
        assert skill is not None
        assert skill.name == "web_search"

        # Should match code_review
        skill = registry.find_by_keyword("review my code please")
        assert skill is not None
        assert skill.name == "code_review"

    @pytest.mark.asyncio
    async def test_find_by_keyword_no_match(self, skills_directory: Path) -> None:
        """find_by_keyword() returns None when no keywords match."""
        registry = SkillRegistry(skills_dir=str(skills_directory))
        await registry.load()

        skill = registry.find_by_keyword("hello, how are you?")
        assert skill is None

    @pytest.mark.asyncio
    async def test_find_by_keyword_case_insensitive(
        self, skills_directory: Path
    ) -> None:
        """find_by_keyword() is case-insensitive."""
        registry = SkillRegistry(skills_dir=str(skills_directory))
        await registry.load()

        skill = registry.find_by_keyword("SEARCH for something")
        assert skill is not None
        assert skill.name == "web_search"

    @pytest.mark.asyncio
    async def test_reload(self, skills_directory: Path) -> None:
        """SkillRegistry.reload() reloads all skills."""
        registry = SkillRegistry(skills_dir=str(skills_directory))
        await registry.load()
        assert len(registry.list_skills()) == 2

        await registry.reload()
        assert len(registry.list_skills()) == 2


# =========================================================================
# Tests: SkillExecutor
# =========================================================================


class TestSkillExecutor:
    """Tests for SkillExecutor."""

    @pytest.mark.asyncio
    async def test_execute_builds_prompt(self, sample_skill: Skill) -> None:
        """execute() builds a prompt with skill info and user message."""
        executor = SkillExecutor()
        prompt = await executor.execute(
            skill=sample_skill,
            user_message="Find Python tutorials",
        )

        assert "## Skill: web_search" in prompt
        assert "Search the web for information" in prompt
        assert "### Instructions" in prompt
        assert "Use the web_search tool" in prompt
        assert "### User Message" in prompt
        assert "Find Python tutorials" in prompt

    @pytest.mark.asyncio
    async def test_execute_with_tool_results(self, sample_skill: Skill) -> None:
        """execute() includes tool results in prompt."""
        executor = SkillExecutor()
        prompt = await executor.execute(
            skill=sample_skill,
            user_message="Find Python tutorials",
            tool_results={"web_search": "Result 1, Result 2"},
        )

        assert "### Tool Results" in prompt
        assert "**web_search:**" in prompt
        assert "Result 1, Result 2" in prompt

    @pytest.mark.asyncio
    async def test_execute_without_tool_results(self, sample_skill: Skill) -> None:
        """execute() omits tool results section when None."""
        executor = SkillExecutor()
        prompt = await executor.execute(
            skill=sample_skill,
            user_message="Hello",
        )

        assert "### Tool Results" not in prompt


# =========================================================================
# Tests: SearchTool
# =========================================================================


class TestSearchTool:
    """Tests for SearchTool (multi-provider)."""

    def test_definition_schema(self) -> None:
        """SearchTool.definition returns correct ToolDefinition."""
        tool = SearchTool(tavily_key="tvly-test")
        defn = tool.definition

        assert isinstance(defn, ToolDefinition)
        assert defn.name == "web_search"
        assert "search" in defn.description.lower()

        param_names = [p.name for p in defn.parameters]
        assert "query" in param_names
        assert "max_results" in param_names
        assert "provider" in param_names

    def test_definition_to_anthropic_schema(self) -> None:
        """SearchTool definition produces valid Anthropic schema."""
        tool = SearchTool(tavily_key="tvly-test")
        schema = tool.definition.to_anthropic_schema()

        assert schema["name"] == "web_search"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"
        assert "query" in schema["input_schema"]["properties"]
        assert "query" in schema["input_schema"]["required"]

    @pytest.mark.asyncio
    async def test_execute_empty_query(self) -> None:
        """execute() returns error for empty query."""
        tool = SearchTool(tavily_key="tvly-test")
        result = await tool.execute(query="")

        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_no_api_key(self) -> None:
        """execute() returns error when no API keys are set."""
        tool = SearchTool(tavily_key="", serpapi_key="", jina_key="", firecrawl_key="")
        result = await tool.execute(query="test query")

        assert result.success is False
        assert "No search API keys" in result.error

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        """execute() calls Tavily API and returns formatted results."""
        tool = SearchTool(tavily_key="tvly-test")

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Python Tutorial",
                    "url": "https://python.org/tutorial",
                    "content": "Learn Python step by step.",
                },
                {
                    "title": "Advanced Python",
                    "url": "https://advanced.python.org",
                    "content": "Advanced topics in Python.",
                },
            ]
        }
        tool._tavily_client = mock_client

        result = await tool.execute(query="Python tutorials", max_results=5, provider="tavily")

        assert result.success is True
        assert isinstance(result.data, dict)
        assert "results" in result.data
        assert "answer" in result.data
        assert len(result.data["results"]) == 2
        assert result.data["results"][0]["title"] == "Python Tutorial"
        assert result.data["results"][0]["url"] == "https://python.org/tutorial"
        assert result.data["results"][0]["source"] == "tavily"

    @pytest.mark.asyncio
    async def test_execute_api_error(self) -> None:
        """execute() handles Tavily API errors gracefully."""
        tool = SearchTool(tavily_key="tvly-test")

        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("API timeout")
        tool._tavily_client = mock_client

        result = await tool.execute(query="test", provider="tavily")

        assert result.success is False
        assert "failed" in result.error.lower()

    def test_available_providers(self) -> None:
        """available_providers returns only providers with keys."""
        tool = SearchTool(
            tavily_key="tvly-test",
            serpapi_key="",
            jina_key="jina-test",
            firecrawl_key="",
        )
        assert tool.available_providers == ["tavily", "jina"]

    @pytest.mark.asyncio
    async def test_execute_default_max_results(self) -> None:
        """execute() uses default max_results=5 when not specified."""
        tool = SearchTool(tavily_key="tvly-test")

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        tool._tavily_client = mock_client

        await tool.execute(query="test", provider="tavily")

        mock_client.search.assert_called_once_with(
            query="test",
            max_results=5,
            search_depth="advanced",
            include_answer=True,
            topic="general",
        )
