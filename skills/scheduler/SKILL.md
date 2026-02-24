---
name: scheduler
description: "Напоминания и запланированные задачи"
tools:
  - schedule_add
  - schedule_list
  - schedule_remove
trigger_keywords:
  - напомни
  - reminder
  - напоминание
  - напоминалка
  - через час
  - через минут
  - завтра в
  - каждый день
  - каждое утро
  - recurring
  - schedule
  - запланируй
  - будильник
---

# Scheduler Skill

## Tools

### `schedule_add`
Create a reminder (one-shot or recurring).
- `message` — what to remind about
- `run_at` — ISO datetime: `2026-02-21T09:00:00`
- `repeat` (optional) — `hourly`, `daily`, `weekly`, `every_30_min`, `every_2_hours`, `every_12_hours`

### `schedule_list`
Show all active reminders.

### `schedule_remove`
Remove a reminder by ID (get IDs from `schedule_list`).

## Rules
1. Convert user's natural language time to ISO format. User's timezone is Europe/Kiev (UTC+2 winter, UTC+3 summer).
2. "через 2 часа" → calculate current time + 2 hours → ISO datetime
3. "завтра в 9" → tomorrow at 09:00:00 → ISO datetime
4. "каждый день в 8 утра" → use `repeat: daily` with `run_at` set to next 08:00
5. "через 30 минут" → calculate current time + 30 minutes
6. After adding a reminder, confirm what was set and when it will fire
7. If time is ambiguous, ask for clarification
