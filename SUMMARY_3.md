# Progressive Agent -- Community and Contributing

This document covers how to contribute to Progressive Agent, the project's governance model, and the roadmap for future development.

## How to Contribute

We welcome contributions of all kinds: new tools, skills, monitors, bug fixes, documentation improvements, and test coverage.

### Getting Started

1. **Fork the repository** on GitHub and clone your fork locally.
2. **Set up the environment** following the instructions in `CONTRIBUTING.md`.
3. **Create a feature branch** with a descriptive name: `feature/weather-tool`, `fix/memory-leak`, `docs/setup-guide`.
4. **Make your changes**, following the code style and architecture guidelines below.
5. **Run the test suite** to make sure nothing is broken: `uv run pytest tests/ -v`.
6. **Submit a pull request** against the `main` branch with a clear description of what you changed and why.

### Code Style Requirements

- **Python 3.11+** with type hints on all function signatures.
- **async/await everywhere** -- the entire project is asynchronous. Never use blocking calls in async context.
- **Logging** via the `logging` module. No `print()` statements.
- **Configuration** in TOML files (`config/*.toml`). Secrets in `.env` (never committed).
- **No hardcoded credentials** -- API keys, tokens, and passwords must come from environment variables.

### Writing a New Tool

Tools are Python classes in `src/tools/` that implement the `Tool` protocol:

1. Create `src/tools/your_tool.py`.
2. Implement the `definition` property (returns a `ToolDefinition` with JSON schema for the LLM).
3. Implement the `async execute(**kwargs) -> ToolResult` method.
4. Register the tool in `src/core/agent.py`.
5. Write tests in `tests/test_your_tool.py`.

### Writing a New Skill

Skills are Markdown files in `skills/your_skill/SKILL.md`:

1. Create the directory and `SKILL.md` file.
2. Add YAML frontmatter with `name`, `description`, `tools`, and `trigger_keywords`.
3. Write clear instructions for the LLM in the Markdown body.
4. Skills are automatically picked up by the Router -- no code changes needed.

### Writing a New Monitor

Monitors are background jobs in `src/monitors/`:

1. Create `src/monitors/your_monitor.py`.
2. Implement a class with a scheduler job method that runs on a fixed interval.
3. Use persistent state (JSON file in `data/`) to track what has already been reported.
4. Push notifications via the Telegram channel.
5. Register the monitor in `src/core/agent.py` or `src/main.py`.

## Project Governance

Progressive Agent is maintained by the Progressive AI Community under the MIT License. The project follows a simple governance model:

- **Maintainers** review and merge pull requests, manage releases, and set the project direction.
- **Contributors** submit issues and pull requests. All contributions are reviewed before merging.
- **Discussions** happen in GitHub Issues and Discussions. We encourage open dialogue about features, architecture decisions, and roadmap priorities.

The project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). We are committed to providing a welcoming and inclusive environment for everyone.

## Roadmap

The project is organized into phases. Current status is tracked in `docs/STATUS.md`.

### Completed

- **Phase 1 -- Core MVP**: Agent loop, LLM provider, memory (vector + FTS5 hybrid), Telegram channel, web search, STT, router, dispatcher, cost tracker, soul system.
- **Phase 2 -- Daily Utility**: Email tools and monitor, file management (9 tools), CLI execution, crypto monitor, Monobank integration, Obsidian integration, browser automation, security hardening.
- **Phase 3 -- Monitoring and Content**: Subscription monitor, news radar (crypto + AI digest), Twitch monitor, YouTube monitor and tools.
- **Phase 4 -- Content and Media**: Vision and document parsing, video notes, forwarded message support, watchdog (auto-restart), git tool, agent control, heartbeat engine, exchange rates, system monitoring, media downloads, morning briefing.

### In Progress and Planned

- **Extended crypto analytics** -- TradingView levels, RSI, volume analysis, arbitrary token tracking.
- **Content engine** -- research-to-article pipeline with SEO optimization and multi-platform publishing.
- **Image generation** -- DALL-E 3 integration for content creation.
- **Web dashboard** -- FastAPI + React admin panel for monitoring and configuration.
- **Cloud hosting** -- Oracle Cloud Free Tier deployment for 24/7 availability.
- **Skill self-creation** -- the agent creates and modifies its own skills at runtime.

## Community Resources

- **GitHub Repository**: [progressive-ai-community/progressive-agent](https://github.com/progressive-ai-community/progressive-agent)
- **Issues**: Report bugs and request features via GitHub Issues.
- **Discussions**: Ask questions and share ideas via GitHub Discussions.
- **License**: MIT -- use it, modify it, share it.

## Acknowledgments

Progressive Agent is inspired by [OpenClaw](https://github.com/nicepkg/openclaw) and [ZeroClaw](https://github.com/nicepkg/zeroclaw), two open-source personal AI assistant projects that pioneered many of the patterns used here: skills as Markdown, soul system, builder pattern, dual dispatcher, and reliable wrapper.
