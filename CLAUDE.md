# Progressive Agent

## Что это
Персональный AI-агент для Telegram. Open-source проект, вдохновлённый OpenClaw и ZeroClaw.
Open-source проект от Progressive AI Community.

## Текущая фаза: v1.0.0 — Open Source Release
- **Роадмап:** `ROADMAP.md` — план развития проекта
- **Архитектура:** `ARCHITECTURE.md` — компоненты, интерфейсы, потоки данных
- **API:** `API_DOCUMENTATION.md` — как создать свой тул или скилл
- **Статус:** `docs/STATUS.md` — что работает, текущий прогресс

## Стек
- Python 3.11+, uv (пакетный менеджер)
- aiogram 3 (Telegram бот)
- anthropic SDK (LLM — Claude API)
- SQLite + sqlite-vec (память, vector search)
- SQLite FTS5 (полнотекстовый поиск)
- OpenAI API (embeddings text-embedding-3-small, Whisper STT, DALL-E 3)
- Tavily API (веб-поиск)
- APScheduler (фоновые задачи)
- TOML (конфигурация)

## Ключевые архитектурные решения
1. **Skills = Markdown файлы** (`skills/*/SKILL.md`) — не код, а инструкции для LLM
2. **SOUL/OWNER/RULES** (`soul/*.md`) — личность агента в отдельных файлах
3. **Builder-паттерн** для Agent (`src/core/agent.py`)
4. **asyncio.Queue pipeline** — все каналы пушат в одну очередь
5. **Гибридный поиск** в памяти: vector + FTS5 keyword + temporal decay
6. **Deny-by-default** — бот отвечает только пользователям из whitelist
7. **Draft updates** — стриминг через edit_message в Telegram
8. **Dual dispatcher** — native tool_use + XML fallback
9. **Reliable wrapper** — ретраи, backoff, rate-limit handling

## Правила для разработки

### ОБЯЗАТЕЛЬНО
- Перед началом работы — читай `docs/STATUS.md`
- После завершения задачи — обнови `docs/STATUS.md`
- Пиши тесты для каждого модуля
- Используй type hints везде
- Используй async/await (проект полностью асинхронный)
- Все конфиги через TOML файлы (`config/*.toml`), секреты через `.env`
- Логирование через `logging` (не print)

### ЗАПРЕЩЕНО
- Трогать файлы за пределами своей зоны ответственности (см. карту ниже)
- Ломать то, что уже работает
- Хардкодить API-ключи, токены, пароли
- Использовать sync-код в async-контексте
- Добавлять зависимости без необходимости

## Карта зон ответственности (параллельная разработка)

```
Окно 0 (основное): CLAUDE.md, docs/, pyproject.toml, .env.example,
                    src/channels/base.py, src/core/tools.py, tests/test_smoke.py
Окно 1 (Core):     src/core/{agent,llm,reliable,config,router,dispatcher,cost_tracker}.py
                    tests/test_core.py
Окно 2 (Memory):   src/memory/*.py, tests/test_memory.py
Окно 3 (Telegram): src/channels/telegram.py, src/tools/stt_tool.py, src/main.py
                    tests/test_telegram.py
Окно 4 (Skills):   src/skills/*.py, src/tools/search_tool.py, skills/**
                    tests/test_skills.py
Окно 5 (Soul):     soul/**, src/core/scheduler.py, config/*.toml
                    tests/test_config.py
```

**ВАЖНО:** Не редактируй файлы из чужих зон! Если тебе нужен интерфейс из другого модуля — используй Protocol/ABC из `src/channels/base.py` или `src/core/tools.py`.

## Интерфейсы (для стыковки модулей)

### Channel Protocol (`src/channels/base.py`)
```python
class Channel(Protocol):
    async def send(self, user_id: str, message: str) -> None: ...
    async def send_file(self, user_id: str, file_path: Path) -> None: ...
    async def listen(self) -> AsyncIterator[IncomingMessage]: ...
    async def draft_update(self, user_id: str, msg_id: str, text: str) -> None: ...
```

### Tool Protocol (`src/core/tools.py`)
```python
class Tool(Protocol):
    name: str
    description: str
    async def execute(self, **kwargs) -> ToolResult: ...
```

### IncomingMessage
```python
@dataclass
class IncomingMessage:
    user_id: str
    text: str | None
    voice_file_path: Path | None
    channel: str  # "telegram", "web"
    timestamp: datetime
    message_id: str
```

### ToolResult
```python
@dataclass
class ToolResult:
    success: bool
    data: Any
    error: str | None = None
```

## Зависимости (pyproject.toml)
```
anthropic, aiogram>=3.0, openai, tavily-python,
sqlite-vec, apscheduler, tomli, pydantic,
python-dotenv, aiohttp, aiofiles
```

## Как запустить
```bash
# Установка
uv sync

# Скопировать конфиг
cp .env.example .env
# Заполнить .env: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, TAVILY_API_KEY

# Запуск
uv run python -m src.main

# Тесты
uv run pytest tests/ -v
```

## Структура конфигов

### `.env` (секреты — НЕ коммитить)
```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC...
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

### `config/agent.toml` (основные настройки)
```toml
[agent]
name = "Progressive Agent"
default_model = "claude-opus-4-6"
max_tokens = 16384

[telegram]
# Auto-detected on first /start — leave empty for auto-setup
allowed_users = []

[memory]
db_path = "data/memory.db"
embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```
