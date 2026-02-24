# Phase 1 — Чеклист

## Статус: В РАБОТЕ
Последнее обновление: 2026-02-18

---

## Шаг 0: Скелет проекта (Окно 0)
- [x] Создать структуру папок
- [x] Создать `CLAUDE.md`
- [x] Создать `docs/ARCHITECTURE.md`
- [x] Создать `docs/PHASE1_CHECKLIST.md` (этот файл)
- [x] Создать `docs/STATUS.md`
- [x] Создать `pyproject.toml`
- [x] Создать `.env.example`
- [x] Создать `src/channels/base.py` (Protocol)
- [x] Создать `src/core/tools.py` (Protocol)
- [x] Создать `tests/test_smoke.py`
- [x] Git init + первый коммит
- **Проверка:** `ls src/core/ src/memory/ src/channels/ src/skills/ src/tools/` — все папки на месте

---

## Шаг 1: LLM Provider + Core (Окно 1)
- [ ] `src/core/config.py` — загрузка TOML + .env
  - **Проверка:** `python -c "from src.core.config import load_config; c = load_config(); print(c)"`
- [ ] `src/core/llm.py` — Claude API провайдер
  - **Проверка:** `python -c "from src.core.llm import ClaudeProvider; p = ClaudeProvider(); print(p.capabilities)"`
- [ ] `src/core/reliable.py` — retry wrapper
  - **Проверка:** тест в `tests/test_core.py` — ретрай при 429
- [ ] `src/core/router.py` — роутинг запросов
  - **Проверка:** тест — keyword matching для скиллов
- [ ] `src/core/dispatcher.py` — dual dispatcher
  - **Проверка:** тест — NativeDispatcher парсит tool_use
- [ ] `src/core/cost_tracker.py` — трекер расходов
  - **Проверка:** тест — daily/monthly limits
- [ ] `src/core/agent.py` — Builder + основной цикл
  - **Проверка:** `python -c "from src.core.agent import Agent; a = Agent.builder().build(); print(a)"`
- [ ] `tests/test_core.py` — все тесты проходят
  - **Проверка:** `pytest tests/test_core.py -v`

---

## Шаг 2: Memory System (Окно 2)
- [ ] `src/memory/sqlite_store.py` — SQLite хранилище
  - **Проверка:** тест — CRUD операции
- [ ] `src/memory/embeddings.py` — генерация эмбеддингов
  - **Проверка:** тест — embedding вектор правильной размерности
- [ ] `src/memory/vector_search.py` — sqlite-vec поиск
  - **Проверка:** тест — поиск по вектору возвращает релевантные результаты
- [ ] `src/memory/keyword_search.py` — FTS5 поиск
  - **Проверка:** тест — полнотекстовый поиск находит по ключевым словам
- [ ] `src/memory/hybrid.py` — гибридный поиск
  - **Проверка:** тест — hybrid_search комбинирует vector + keyword + decay
- [ ] `src/memory/manager.py` — центральный менеджер
  - **Проверка:** `python -c "from src.memory.manager import MemoryManager"`
- [ ] `tests/test_memory.py` — все тесты проходят
  - **Проверка:** `pytest tests/test_memory.py -v`

---

## Шаг 3: Telegram Channel (Окно 3)
- [ ] `src/channels/telegram.py` — aiogram 3 бот
  - **Проверка:** бот стартует без ошибок (с фейковым токеном — проверка инициализации)
- [ ] Текстовые сообщения
  - **Проверка:** тест — handler принимает текст, кладёт в Queue
- [ ] Голосовые сообщения
  - **Проверка:** тест — handler принимает voice, скачивает файл
- [ ] Draft/progressive updates
  - **Проверка:** тест — edit_message вызывается при стриминге
- [ ] Deny-by-default whitelist
  - **Проверка:** тест — сообщение от чужого user_id игнорируется
- [ ] `src/tools/stt_tool.py` — Whisper API
  - **Проверка:** тест — мок Whisper API, возвращает текст
- [ ] `src/main.py` — точка входа
  - **Проверка:** `python -m src.main --help` или сухой запуск
- [ ] `tests/test_telegram.py` — все тесты проходят
  - **Проверка:** `pytest tests/test_telegram.py -v`

---

## Шаг 4: Skills System (Окно 4)
- [ ] `src/skills/loader.py` — парсинг SKILL.md
  - **Проверка:** тест — парсинг YAML frontmatter + body
- [ ] `src/skills/registry.py` — реестр скиллов + hot-reload
  - **Проверка:** тест — загрузка скиллов из директории
- [ ] `src/skills/executor.py` — исполнение скилла
  - **Проверка:** тест — скилл передаёт инструкции в agent prompt
- [ ] `skills/web_search/SKILL.md` — первый скилл
  - **Проверка:** файл парсится loader'ом без ошибок
- [ ] `src/tools/search_tool.py` — Tavily API
  - **Проверка:** тест — мок Tavily, возвращает результаты
- [ ] `tests/test_skills.py` — все тесты проходят
  - **Проверка:** `pytest tests/test_skills.py -v`

---

## Шаг 5: Soul + Config (Окно 5)
- [ ] `soul/SOUL.md` — личность агента
  - **Проверка:** файл читается, не пустой
- [ ] `soul/OWNER.md` — профиль владельца
  - **Проверка:** файл читается, не пустой
- [ ] `soul/RULES.md` — правила поведения
  - **Проверка:** файл читается, не пустой
- [ ] `soul/traits/` — 10 файлов качеств
  - **Проверка:** 10 файлов существуют
- [ ] `src/core/scheduler.py` — APScheduler
  - **Проверка:** тест — scheduler стартует, можно добавить job
- [ ] `config/agent.toml` — основной конфиг
  - **Проверка:** `python -c "import tomli; print(tomli.loads(open('config/agent.toml').read()))"`
- [ ] `config/services.toml` — сервисы
  - **Проверка:** файл парсится без ошибок
- [ ] `tests/test_config.py` — все тесты проходят
  - **Проверка:** `pytest tests/test_config.py -v`

---

## Шаг 6: Интеграция (Окно 0)
- [ ] Все модули импортируются без ошибок
  - **Проверка:** `python -c "from src.core.agent import Agent; from src.memory.manager import MemoryManager; from src.channels.telegram import TelegramChannel; from src.skills.registry import SkillRegistry"`
- [ ] Все тесты проходят
  - **Проверка:** `pytest tests/ -v`
- [ ] Интеграционный тест: бот стартует
  - **Проверка:** `python -m src.main` — нет ошибок при старте (с реальным TELEGRAM_BOT_TOKEN)
- [ ] Интеграционный тест: текстовое сообщение
  - **Проверка:** написать боту в Telegram → получить ответ от Claude
- [ ] Интеграционный тест: голосовое сообщение
  - **Проверка:** отправить войс → получить текстовый ответ
- [ ] Интеграционный тест: веб-поиск
  - **Проверка:** "найди последние новости про AI" → структурированный ответ
- [ ] Обновить `docs/STATUS.md`
- [ ] Git коммит: "Phase 1 complete — MVP working"
