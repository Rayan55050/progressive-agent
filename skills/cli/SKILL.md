---
name: cli
description: "Управление приложениями и выполнение системных команд"
tools:
  - cli_exec
  - file_open
trigger_keywords:
  - команда
  - выполни
  - запусти
  - открой
  - закрой
  - убей
  - стоп
  - останови
  - сверни
  - что запущено
  - разверни
  - терминал
  - консоль
  - cmd
  - powershell
  - bash
  - процессы
  - диск
  - память
  - pip install
  - git
  - npm
  - версия
  - перезапусти
  - сколько места
  - ping
  - ipconfig
  - system info
  - корзина
  - recycle
---

# CLI — управление приложениями и команды

## Управление приложениями (file_open)

### Открыть/запустить приложение
`file_open` с `action="open"` и именем приложения:
- "запусти Discord" → `file_open(path="Discord", action="open")`
- "открой Obsidian" → `file_open(path="Obsidian", action="open")`
- "открой Telegram" → `file_open(path="Telegram", action="open")`

Приложения ищутся по ярлыкам на рабочем столе. Передавай ТОЛЬКО имя, НЕ полный путь.

### Закрыть/убить приложение
`file_open` с `action="close"` и именем:
- "закрой Discord" → `file_open(path="Discord", action="close")`
- "убей Obsidian" → `file_open(path="Obsidian", action="close")`
- "останови Opera" → `file_open(path="Opera", action="close")`

### Какие приложения запущены
`file_open` с `action="list"`:
- "что запущено?" → `file_open(path="", action="list")`
- "какие приложения на рабочем столе?" → `file_open(path="desktop", action="list")`

### Открыть файл/папку
`file_open` с `action="open"` и полным путём:
- "открой папку Documents" → `file_open(path="Documents", action="open")`

### Корзина (Recycle Bin)
`file_open` с `action="recycle_bin"`:
- "что в корзине?" → `file_open(path="check", action="recycle_bin")`
- "очисти корзину" → `file_open(path="empty", action="recycle_bin")`
- "покажи корзину" → `file_open(path="check", action="recycle_bin")`

Тул сам проверяет все диски, сам удаляет файлы напрямую, сам верифицирует результат. НЕ используй cli_exec для корзины — ТОЛЬКО file_open с action=recycle_bin.

## Системные команды (cli_exec)

### cli_exec
Запускает команду в shell и возвращает результат.
- `command` — команда для выполнения
- `working_dir` — рабочая директория (опционально)
- `shell` — "cmd" (по умолчанию), "powershell", "bash"

### Примеры
- "сколько места на диске" → `cli_exec` с `wmic logicaldisk get size,freespace,caption`
- "установи пакет X" → `cli_exec` с `pip install X`
- "git status" → `cli_exec` с `git status`
- "версия Python" → `cli_exec` с `python --version`
- "пинг google.com" → `cli_exec` с `ping google.com -n 4`
- "системная инфа" → `cli_exec` с `systeminfo`

## Правила

1. **Приложения** — для open/close/list ВСЕГДА используй `file_open`, НЕ `cli_exec`
2. **Система — Windows 11**. Используй Windows-команды (dir, tasklist, ipconfig)
3. **Для сложных запросов** используй PowerShell (shell="powershell")
4. **Таймаут** — 30 секунд. Не запускай долгие процессы
5. **Заблокировано**: format, shutdown, reboot, registry edits, деструктивные команды
6. **Вывод**: если результат длинный — покажи самое важное
7. **НЕ галлюцинируй** — если нужно что-то сделать, ОБЯЗАТЕЛЬНО вызови тул. Текстовый ответ без вызова тула = ВРАНЬЁ
8. **НИКОГДА не используй** `-ErrorAction SilentlyContinue` — это прячет ошибки и ты не узнаешь что пошло не так
9. **ПРОВЕРЯЙ РЕЗУЛЬТАТ** — после выполнения проверь что действие реально сработало:
   - Очистил корзину → проверь `(New-Object -ComObject Shell.Application).NameSpace(0xa).Items().Count` (должно быть 0)
   - Убил процесс → проверь `tasklist` что его нет
   - Удалил файл → проверь что не существует
   - Если команда вернула ошибку но могла сработать (баг Windows) — проверь фактический результат

## Известные баги Windows

- `Clear-RecycleBin -Force` — иногда кидает Win32Exception "Не удалось найти файл", даже если корзина очищена. ВСЕГДА проверяй `.Items().Count` после
- Пустой вывод от команды ≠ успех. Проверяй
