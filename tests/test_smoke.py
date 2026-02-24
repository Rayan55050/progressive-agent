"""
Smoke-тесты Progressive Agent.

Запускаются после каждого изменения для проверки целостности.
Не требуют API-ключей или внешних сервисов.

Запуск: pytest tests/test_smoke.py -v
"""

from pathlib import Path

import pytest

# Корень проекта
PROJECT_ROOT = Path(__file__).parent.parent


class TestProjectStructure:
    """Проверка структуры проекта."""

    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()

    def test_src_packages_exist(self):
        packages = ["src", "src/core", "src/memory", "src/channels", "src/skills", "src/tools", "src/monitors"]
        for pkg in packages:
            pkg_path = PROJECT_ROOT / pkg
            assert pkg_path.exists(), f"Package {pkg} not found"
            assert (pkg_path / "__init__.py").exists(), f"{pkg}/__init__.py not found"

    def test_docs_exist(self):
        docs = ["docs/ARCHITECTURE.md", "docs/PHASE1_CHECKLIST.md", "docs/STATUS.md"]
        for doc in docs:
            assert (PROJECT_ROOT / doc).exists(), f"{doc} not found"

    def test_claude_md_exists(self):
        assert (PROJECT_ROOT / "CLAUDE.md").exists()

    def test_pyproject_toml_exists(self):
        assert (PROJECT_ROOT / "pyproject.toml").exists()

    def test_env_example_exists(self):
        assert (PROJECT_ROOT / ".env.example").exists()


class TestBaseProtocols:
    """Проверка базовых интерфейсов."""

    def test_channel_protocol_imports(self):
        from src.channels.base import Channel, IncomingMessage, OutgoingMessage
        assert Channel is not None
        assert IncomingMessage is not None
        assert OutgoingMessage is not None

    def test_tool_protocol_imports(self):
        from src.core.tools import Tool, ToolDefinition, ToolRegistry, ToolResult
        assert Tool is not None
        assert ToolDefinition is not None
        assert ToolRegistry is not None
        assert ToolResult is not None

    def test_tool_registry_basic(self):
        from src.core.tools import ToolRegistry
        registry = ToolRegistry()
        assert len(registry.list_tools()) == 0

    def test_tool_definition_to_schema(self):
        from src.core.tools import ToolDefinition, ToolParameter
        defn = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters=[
                ToolParameter(name="query", type="string", description="Search query"),
            ],
        )
        schema = defn.to_anthropic_schema()
        assert schema["name"] == "test_tool"
        assert "query" in schema["input_schema"]["properties"]

    def test_incoming_message_creation(self):
        from src.channels.base import IncomingMessage
        msg = IncomingMessage(user_id="123", text="hello")
        assert msg.user_id == "123"
        assert msg.text == "hello"
        assert msg.voice_file_path is None
        assert msg.channel == "telegram"


class TestConfigFiles:
    """Проверка конфигурационных файлов."""

    def test_soul_directory_exists(self):
        assert (PROJECT_ROOT / "soul").exists()

    def test_skills_directory_exists(self):
        assert (PROJECT_ROOT / "skills").exists()

    def test_config_directory_exists(self):
        assert (PROJECT_ROOT / "config").exists()

    def test_data_directory_exists(self):
        assert (PROJECT_ROOT / "data").exists()
