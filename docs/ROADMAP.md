# Roadmap

## v1.0 — Core Agent (Current)

The foundation is built and running in production daily.

- **63+ tools** — file management, CLI, email, browser, crypto, finance, media, and more
- **18 skills** — markdown-based instruction sets that shape LLM behavior per domain
- **10 monitors** — background jobs that proactively push notifications (crypto, news, subscriptions, morning briefings)
- **Hybrid memory** — SQLite + vector search + FTS5 keyword search + temporal decay
- **6-level fallback chain** — Claude proxy, Gemini, Mistral, Cloudflare, OpenAI, Claude API
- **Telegram interface** — streaming responses, voice messages, draft updates, whitelist security
- **Self-healing** — watchdog, heartbeat, auto-restart on failure

## v1.1 — Web Dashboard

- FastAPI backend exposing agent metrics, memory, and configuration
- React admin panel for monitoring conversations, tool usage, and costs
- Real-time log viewer and memory browser
- Configuration editor (skills, monitors, tools) without touching files

## v1.2 — Plugin System

- Standardized plugin format for community tools and skills
- Plugin registry and discovery (local and remote)
- Hot-reload: install plugins without restarting the agent
- Community marketplace for sharing tools, skills, and monitors

## v1.3 — Multi-Channel

- Discord bot (same agent, different interface)
- Slack integration for workspace use
- Web UI (standalone chat interface, self-hosted)
- Unified message queue across all channels

## v2.0 — Multi-Agent Orchestration

- Multiple specialized agents coordinating on complex tasks
- Autonomous goal pursuit with planning and reflection loops
- Long-running background tasks with progress reporting
- Agent-to-agent communication protocol

---

## Community Wishlist

Have an idea? Open an issue or PR. Priority areas we'd love contributions in:

- New tool integrations (especially free APIs)
- Skills for new domains (health, education, home automation)
- Language support beyond Russian/English
- Mobile companion app
- Voice-first interaction mode
- Calendar and task management integrations
