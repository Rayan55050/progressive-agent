# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in Progressive Agent, please report it responsibly:

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Open a **private security advisory** via GitHub's Security tab, or email the maintainers directly.
3. Include a clear description of the vulnerability, steps to reproduce, and potential impact.
4. We will acknowledge receipt within 48 hours and provide a fix timeline.

## Security Features

Progressive Agent includes several security measures:

### Access Control
- **Deny-by-default**: Only whitelisted Telegram user IDs can interact with the bot. Unknown users receive no tool or memory access.
- **Auto-onboarding**: The first `/start` command registers the owner. Subsequent unknown users are rejected.

### CLI Execution Safety
- **Command blocklist**: The CLI tool uses executable extraction with 20+ regex patterns to block dangerous commands.
- **Obfuscation detection**: Heuristics detect attempts to bypass the blocklist via encoding, variable expansion, or pipe chains.

### File System Protection
- **Source validation**: File copy operations validate source paths to prevent exfiltration of sensitive files (`.ssh`, `.env`, system directories).
- **Path traversal prevention**: File tools validate paths against allowed directories.

### Browser Safety
- **Localhost-only JS evaluation**: The `eval_js` function in the browser tool only executes JavaScript on localhost URLs, preventing XSS on external sites.

### Cost Protection
- **Daily and monthly spending limits**: Configurable thresholds with automatic warnings.
- **Cost tracking**: Every LLM API call is tracked and logged.

### Data Privacy
- **Local-only storage**: All data (memory, conversations, embeddings) is stored locally in SQLite.
- **No telemetry**: The bot sends no analytics or usage data anywhere.
- **Secrets in .env**: API keys are stored in `.env` (gitignored), never in code or config files.
