# Design Philosophy

## "Just call the tool, don't narrate"

The agent should act, not describe what it's about to do. When asked to check Bitcoin price, it calls the CoinGecko tool — it doesn't write a paragraph about how it's going to check the price. System prompt instructions enforce this behavior. The LLM is prompted to execute first, explain after.

## Skills are instructions, not code

Skills are markdown files (`skills/*/SKILL.md`) that get injected into the system prompt. They tell the LLM *how* to behave in a domain — what tools to prefer, what format to use, what tone to take. They are not Python modules with business logic. This means anyone can create a skill by writing a markdown file. No coding required.

## Simplicity over complexity

Three-layer validation chains, guard rails on guard rails, and "nudge" systems that second-guess the LLM — these add complexity that confuses the model and breaks in unexpected ways. A clear system prompt with direct instructions beats an elaborate code-based control system every time. When in doubt, delete code.

## Self-healing over manual intervention

The agent runs 24/7. Things will break. The answer is not "restart it manually" — the answer is watchdogs, heartbeats, fallback providers, auto-recovery, and graceful degradation. If the primary LLM is down, the fallback chain kicks in. If the process crashes, the watchdog restarts it. If memory is corrupted, it rebuilds from SQLite.

## Specialized tools over generic search

When a user asks about a movie, use TMDB. When they ask about crypto, use CoinGecko. When they ask about a Wikipedia topic, use the Wikipedia tool. Web search is the fallback, not the default. Specialized tools are faster, more accurate, and more reliable than asking a search engine and parsing the results.

## The agent works for the owner

This is a personal assistant, not a public service. It knows its owner, their preferences, their contacts, their schedule. It speaks their language, matches their tone, and prioritizes their needs. Configuration lives in soul files, not in code.

## Memory is identity

An assistant that forgets everything between sessions is just a fancy autocomplete. Progressive Agent remembers conversations, learns preferences, and builds context over time. Hybrid search (vector + keyword + temporal decay) ensures that relevant memories surface when they matter. The longer you use it, the more useful it becomes.

These principles aren't theoretical — they emerged from building and running the agent daily. Every design choice reflects real usage.
