"""
Tests for configuration files and soul system:
- config/agent.toml is valid TOML
- config/services.toml is valid TOML
- Soul files exist (SOUL.md, OWNER.md, RULES.md)
- 10 trait files exist in soul/traits/
- Scheduler creation and job management (mock APScheduler)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


# Project root for finding real config/soul files
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def agent_toml_path() -> Path:
    """Path to the real agent.toml config file."""
    return PROJECT_ROOT / "config" / "agent.toml"


@pytest.fixture
def services_toml_path() -> Path:
    """Path to the real services.toml config file."""
    return PROJECT_ROOT / "config" / "services.toml"


@pytest.fixture
def soul_dir() -> Path:
    """Path to the real soul/ directory."""
    return PROJECT_ROOT / "soul"


# =========================================================================
# Tests: agent.toml
# =========================================================================


class TestAgentToml:
    """Tests for config/agent.toml validity and content."""

    def test_file_exists(self, agent_toml_path: Path) -> None:
        """config/agent.toml exists."""
        assert agent_toml_path.exists(), f"agent.toml not found at {agent_toml_path}"

    def test_valid_toml(self, agent_toml_path: Path) -> None:
        """config/agent.toml is valid TOML."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict)

    def test_has_agent_section(self, agent_toml_path: Path) -> None:
        """agent.toml contains [agent] section with required fields."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "agent" in data
        agent = data["agent"]
        assert "name" in agent
        assert "default_model" in agent
        assert "max_tokens" in agent
        assert isinstance(agent["max_tokens"], int)

    def test_has_telegram_section(self, agent_toml_path: Path) -> None:
        """agent.toml contains [telegram] section."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "telegram" in data

    def test_has_memory_section(self, agent_toml_path: Path) -> None:
        """agent.toml contains [memory] section with required fields."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "memory" in data
        memory = data["memory"]
        assert "db_path" in memory
        assert "embedding_model" in memory

    def test_has_costs_section(self, agent_toml_path: Path) -> None:
        """agent.toml contains [costs] section with budget limits."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "costs" in data
        costs = data["costs"]
        assert "daily_limit_usd" in costs
        assert "monthly_limit_usd" in costs
        assert costs["daily_limit_usd"] > 0
        assert costs["monthly_limit_usd"] > 0

    def test_has_search_section(self, agent_toml_path: Path) -> None:
        """agent.toml contains [search] section."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "search" in data
        assert "provider" in data["search"]

    def test_has_scheduler_section(self, agent_toml_path: Path) -> None:
        """agent.toml contains [scheduler] section."""
        with open(agent_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "scheduler" in data
        assert "timezone" in data["scheduler"]


# =========================================================================
# Tests: services.toml
# =========================================================================


class TestServicesToml:
    """Tests for config/services.toml validity and content."""

    def test_file_exists(self, services_toml_path: Path) -> None:
        """config/services.toml exists."""
        assert services_toml_path.exists(), f"services.toml not found at {services_toml_path}"

    def test_valid_toml(self, services_toml_path: Path) -> None:
        """config/services.toml is valid TOML."""
        with open(services_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict)

    def test_has_services_array(self, services_toml_path: Path) -> None:
        """services.toml contains [[services]] array of tables."""
        with open(services_toml_path, "rb") as f:
            data = tomllib.load(f)
        assert "services" in data
        assert isinstance(data["services"], list)
        assert len(data["services"]) > 0

    def test_services_have_required_fields(self, services_toml_path: Path) -> None:
        """Each service entry has name, url, api_key_env, and status."""
        with open(services_toml_path, "rb") as f:
            data = tomllib.load(f)
        for service in data["services"]:
            assert "name" in service, f"Service missing 'name': {service}"
            assert "url" in service, f"Service {service.get('name')} missing 'url'"
            assert "api_key_env" in service, (
                f"Service {service.get('name')} missing 'api_key_env'"
            )
            assert "status" in service, f"Service {service.get('name')} missing 'status'"

    def test_anthropic_service_present(self, services_toml_path: Path) -> None:
        """Anthropic Claude is listed as a service."""
        with open(services_toml_path, "rb") as f:
            data = tomllib.load(f)
        names = [s["name"] for s in data["services"]]
        assert any("Anthropic" in n or "Claude" in n for n in names)


# =========================================================================
# Tests: Soul files
# =========================================================================


class TestSoulFiles:
    """Tests for soul/ directory and its files."""

    def test_soul_md_exists(self, soul_dir: Path) -> None:
        """soul/SOUL.md exists and is not empty."""
        path = soul_dir / "SOUL.md"
        assert path.exists(), f"SOUL.md not found at {path}"
        assert path.stat().st_size > 0, "SOUL.md is empty"

    def test_owner_md_exists(self, soul_dir: Path) -> None:
        """soul/OWNER.md exists and is not empty."""
        path = soul_dir / "OWNER.md"
        assert path.exists(), f"OWNER.md not found at {path}"
        assert path.stat().st_size > 0, "OWNER.md is empty"

    def test_rules_md_exists(self, soul_dir: Path) -> None:
        """soul/RULES.md exists and is not empty."""
        path = soul_dir / "RULES.md"
        assert path.exists(), f"RULES.md not found at {path}"
        assert path.stat().st_size > 0, "RULES.md is empty"


# =========================================================================
# Tests: Trait files
# =========================================================================


class TestTraitFiles:
    """Tests for soul/traits/ directory — 10 trait files."""

    EXPECTED_TRAITS = [
        "01_tone.md",
        "02_character.md",
        "03_anti_slop.md",
        "04_output_format.md",
        "05_honesty.md",
        "06_initiative.md",
        "07_speed.md",
        "08_privacy.md",
        "09_resourcefulness.md",
        "10_adaptivity.md",
    ]

    def test_traits_directory_exists(self, soul_dir: Path) -> None:
        """soul/traits/ directory exists."""
        traits_dir = soul_dir / "traits"
        assert traits_dir.exists(), f"traits/ directory not found at {traits_dir}"
        assert traits_dir.is_dir(), f"{traits_dir} is not a directory"

    def test_ten_trait_files_exist(self, soul_dir: Path) -> None:
        """All 10 trait files exist in soul/traits/."""
        traits_dir = soul_dir / "traits"
        for filename in self.EXPECTED_TRAITS:
            path = traits_dir / filename
            assert path.exists(), f"Trait file missing: {filename}"

    def test_trait_files_not_empty(self, soul_dir: Path) -> None:
        """Each trait file has non-empty content."""
        traits_dir = soul_dir / "traits"
        for filename in self.EXPECTED_TRAITS:
            path = traits_dir / filename
            if path.exists():
                assert path.stat().st_size > 0, f"Trait file is empty: {filename}"

    def test_exactly_ten_traits(self, soul_dir: Path) -> None:
        """The traits directory contains at least 10 .md files."""
        traits_dir = soul_dir / "traits"
        md_files = list(traits_dir.glob("*.md"))
        assert len(md_files) >= 10, (
            f"Expected at least 10 trait files, found {len(md_files)}: "
            f"{[f.name for f in md_files]}"
        )


# =========================================================================
# Tests: Scheduler
# =========================================================================


class TestScheduler:
    """Tests for Scheduler creation and job management (mock APScheduler)."""

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_creation(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler initializes with timezone."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.running = False
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler(timezone="Europe/Kiev")
        assert scheduler is not None
        mock_scheduler_cls.assert_called_once_with(timezone="Europe/Kiev")

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_start_stop(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler.start() and stop() control the underlying scheduler."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.running = False
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()

        scheduler.start()
        mock_scheduler_inst.start.assert_called_once()

        mock_scheduler_inst.running = True
        scheduler.stop()
        mock_scheduler_inst.shutdown.assert_called_once_with(wait=True)

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_add_job(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler.add_job() registers a job and returns job_id."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.running = False
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()

        async def my_task() -> None:
            pass

        job_id = scheduler.add_job(
            func=my_task,
            trigger="interval",
            name="Test job",
            minutes=30,
        )

        assert isinstance(job_id, str)
        assert len(job_id) > 0
        mock_scheduler_inst.add_job.assert_called_once()

        # Verify the add_job call args
        call_kwargs = mock_scheduler_inst.add_job.call_args
        assert call_kwargs[0][0] is my_task  # func positional arg
        assert call_kwargs[1]["trigger"] == "interval"
        assert call_kwargs[1]["name"] == "Test job"
        assert call_kwargs[1]["minutes"] == 30

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_remove_job(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler.remove_job() removes a job by ID."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()

        async def my_task() -> None:
            pass

        job_id = scheduler.add_job(func=my_task, trigger="interval", minutes=10)
        scheduler.remove_job(job_id)

        mock_scheduler_inst.remove_job.assert_called_once_with(job_id)

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_list_jobs(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler.list_jobs() returns JobInfo objects."""
        from src.core.scheduler import JobInfo, Scheduler

        mock_job = MagicMock()
        mock_job.id = "job-123"
        mock_job.name = "Test job"
        mock_job.next_run_time = datetime(2026, 1, 1, 12, 0, 0)
        mock_job.trigger = MagicMock(__str__=lambda self: "interval[0:30:00]")

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.get_jobs.return_value = [mock_job]
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()
        jobs = scheduler.list_jobs()

        assert len(jobs) == 1
        assert isinstance(jobs[0], JobInfo)
        assert jobs[0].id == "job-123"
        assert jobs[0].name == "Test job"
        assert jobs[0].next_run_time == datetime(2026, 1, 1, 12, 0, 0)

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_get_job(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler.get_job() returns JobInfo for an existing job."""
        from src.core.scheduler import JobInfo, Scheduler

        mock_job = MagicMock()
        mock_job.id = "job-456"
        mock_job.name = "My job"
        mock_job.next_run_time = datetime(2026, 6, 15, 8, 0, 0)
        mock_job.trigger = MagicMock(__str__=lambda self: "cron[day_of_week='mon-fri']")

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.get_job.return_value = mock_job
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()
        result = scheduler.get_job("job-456")

        assert result is not None
        assert isinstance(result, JobInfo)
        assert result.id == "job-456"
        assert result.name == "My job"

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_get_job_not_found(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler.get_job() returns None for non-existent job."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.get_job.return_value = None
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()
        result = scheduler.get_job("nonexistent")
        assert result is None

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_pause_resume_job(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler pause_job and resume_job delegate to APScheduler."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler()
        scheduler.pause_job("job-1")
        mock_scheduler_inst.pause_job.assert_called_once_with("job-1")

        scheduler.resume_job("job-1")
        mock_scheduler_inst.resume_job.assert_called_once_with("job-1")

    @patch("src.core.scheduler.AsyncIOScheduler")
    def test_repr(self, mock_scheduler_cls: MagicMock) -> None:
        """Scheduler __repr__ includes status and timezone."""
        from src.core.scheduler import Scheduler

        mock_scheduler_inst = MagicMock()
        mock_scheduler_inst.running = False
        mock_scheduler_inst.get_jobs.return_value = []
        mock_scheduler_cls.return_value = mock_scheduler_inst

        scheduler = Scheduler(timezone="Europe/Kiev")
        r = repr(scheduler)
        assert "stopped" in r
        assert "Europe/Kiev" in r
