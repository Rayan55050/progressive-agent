# Contributing to Progressive Agent

Thank you for your interest in contributing! This guide will help you get started.

## How to Contribute

### 1. Fork and Clone

```bash
git clone https://github.com/YOUR_USERNAME/progressive-agent.git
cd progressive-agent
```

### 2. Create a Branch

```bash
git checkout -b feature/your-feature-name
```

Use descriptive branch names: `feature/weather-tool`, `fix/memory-leak`, `docs/setup-guide`.

### 3. Set Up the Environment

```bash
# Install dependencies
uv sync

# Copy and fill in config
cp .env.example .env
# Edit .env with your API keys

# Run the bot
uv run python -m src.main

# Run tests
uv run pytest tests/ -v
```

### 4. Make Your Changes

Follow the code style and architecture guidelines below, then commit your work.

### 5. Submit a Pull Request

Push your branch and open a PR against `main`. Describe what you changed and why.

## Code Style

- **Python 3.11+** with full type hints on all function signatures.
- **async/await everywhere.** Never use synchronous blocking calls in async context.
- **Logging** via the `logging` module. No `print()` statements.
- **Configuration** goes in TOML files (`config/*.toml`). Secrets go in `.env` (never committed).
- **No hardcoded credentials.** API keys, tokens, and passwords must come from environment variables.

## Architecture: Tools vs Skills

This project has a clear separation between **tools** and **skills**:

| Concept | What it is | Where it lives |
|---------|-----------|----------------|
| **Tool** | Python code that executes an action (API call, file op, etc.) | `src/tools/*.py` |
| **Skill** | Markdown instructions that teach the LLM how to use tools | `skills/*/SKILL.md` |

### Writing a New Tool

1. Create `src/tools/your_tool.py`.
2. Implement the `Tool` protocol from `src/core/tools.py`:
   - `name: str` and `description: str` properties.
   - `definition` property returning a `ToolDefinition`.
   - `async execute(**kwargs) -> ToolResult` method.
3. Register the tool in `src/core/agent.py`.
4. Write tests in `tests/test_your_tool.py`.

### Writing a New Skill

1. Create `skills/your_skill/SKILL.md`.
2. Write clear Markdown instructions for the LLM: when to activate, which tools to use, expected behavior.
3. Skills are automatically loaded by the router based on the user's message context.

## Testing

- Use `pytest` for all tests.
- Every new tool must have corresponding tests.
- Run the full suite before submitting a PR:

```bash
uv run pytest tests/ -v
```

## Commit Messages

Use clear, descriptive commit messages:

```
Add weather tool with OpenWeatherMap integration
Fix memory race condition in history manager
Update crypto skill with DeFi tool references
```

## Reporting Bugs

Open a GitHub Issue with:

- Steps to reproduce.
- Expected vs actual behavior.
- Python version and OS.
- Relevant log output.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold a welcoming and inclusive environment.

## Questions?

Open a Discussion on GitHub or reach out via the project's communication channels. We are happy to help newcomers get started.
