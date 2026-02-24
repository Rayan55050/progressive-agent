"""
CLI tool — execute system commands from Telegram.

Allows the agent to run shell commands on the host machine.

Security Model:
- Blocklist with robust validation (checks actual executable, not substrings)
- Anti-obfuscation: blocks base64, encoded commands, download-and-execute patterns
- 30-second timeout to prevent DoS
- Full audit logging of all commands and blocks
- Designed for personal use by trusted owner, not public/multi-tenant environment

Blocked: format, shutdown, registry edits, disk tools, user management, fork bombs,
         encoded/obfuscated payloads, download-execute chains
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Exact executables that are ALWAYS blocked (catastrophic/irreversible)
BLOCKED_EXECUTABLES = {
    "format", "format.com",
    "mkfs", "mkfs.ext4", "mkfs.ntfs",
    "dd", "dd.exe",
    "shutdown", "shutdown.exe",
    "reboot", "halt",
    "bcdedit", "bcdedit.exe",
    "diskpart", "diskpart.exe",
}

# Command patterns that are blocked (regex patterns)
BLOCKED_PATTERNS = [
    # Destructive delete operations
    r"del\s+.*\/s",  # del /s (recursive delete)
    r"rd\s+.*\/s",   # rd /s (recursive remove directory)
    r"rmdir\s+.*\/s",
    r"rm\s+-rf\s+[/~*]",  # rm -rf dangerous paths

    # Registry modifications
    r"reg\s+(delete|add)",

    # User/group management
    r"net\s+(user|localgroup)",

    # Fork bomb
    r":\(\)\{:\|:&\};:",

    # PowerShell/cmd obfuscation and encoding
    r"-enc(oded)?(command)?",  # powershell -encodedcommand
    r"-e\s+[A-Za-z0-9+/=]{20,}",  # base64 blob after -e flag
    r"frombase64string",
    r"invoke-expression.*\$",  # iex with variables (common in malware)
    r"iex\s+\$",  # iex $variable pattern
    r"iex\s*\(.*http",  # iex(wget/curl) pattern

    # Download and execute patterns
    r"(wget|curl|invoke-webrequest).*\|\s*(iex|powershell|cmd|bash|sh)",
    r"certutil.*-decode",  # certutil used for base64 decode to bypass AV
    r"bitsadmin.*\/transfer",  # BITS admin for stealth download

    # Process injection / memory manipulation
    r"invoke-mimikatz",
    r"invoke-shellcode",
    r"invoke-reflective",
    r"reflectiveloader",
]

MAX_OUTPUT_LENGTH = 5000
DEFAULT_TIMEOUT = 30  # seconds


class CliExecTool:
    """Execute a system command and return output."""

    def __init__(
        self,
        allowed_dirs: list[str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._allowed_dirs = allowed_dirs or []
        self._timeout = timeout

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="cli_exec",
            description=(
                "Execute a system command (shell/cmd/powershell) and return output. "
                "Use for: checking disk space, listing processes, running scripts, "
                "pip install, git commands, system info, network checks, etc. "
                "\n\n"
                "SECURITY BLOCKS (will reject command):\n"
                "- Destructive: format, shutdown, reboot, dd, mkfs, del /s, rm -rf\n"
                "- System config: registry edits (reg delete/add), bcdedit, diskpart\n"
                "- User management: net user, net localgroup\n"
                "- Obfuscation: base64 encoded commands, -encodedcommand, certutil decode\n"
                "- Download-execute chains: curl|iex, wget|bash, invoke-webrequest|iex\n"
                "- Process injection: mimikatz, shellcode, reflective loaders\n"
                "\n"
                "Timeout: 30 seconds max. All commands are logged for audit.\n"
                "\n"
                "IMPORTANT: Exit code 0 does NOT guarantee the action succeeded. "
                "If output is empty or stderr contains warnings — DO NOT claim success. "
                "Verify the result before telling the user it's done. "
                "NEVER use -ErrorAction SilentlyContinue in PowerShell commands."
            ),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="Command to execute (e.g. 'dir', 'python --version', 'git status')",
                    required=True,
                ),
                ToolParameter(
                    name="working_dir",
                    type="string",
                    description="Working directory for the command (optional, defaults to home)",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="shell",
                    type="string",
                    description="Shell to use: 'cmd' (default on Windows), 'powershell', 'bash'",
                    required=False,
                    default="cmd",
                ),
            ],
        )

    def _is_blocked(self, command: str) -> str | None:
        """
        Check if command is blocked. Returns reason or None.

        Validation strategy:
        1. Extract actual executable from command (handle shell wrappers)
        2. Check executable against blocklist
        3. Check full command against dangerous patterns (regex)
        4. Flag obfuscation/encoding attempts
        """
        cmd_lower = command.lower().strip()

        # Extract executable name (handle powershell -c, cmd /c, bash -c)
        executable = self._extract_executable(cmd_lower)

        # Check if executable itself is blocked
        if executable in BLOCKED_EXECUTABLES:
            return f"Заблокировано: исполняемый файл '{executable}' запрещён"

        # Check against dangerous patterns (regex)
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, cmd_lower, re.IGNORECASE):
                return f"Заблокировано: команда соответствует опасному паттерну '{pattern}'"

        # Additional heuristics for obfuscation
        if self._looks_obfuscated(command):
            return "Заблокировано: команда выглядит как обфусцированная/закодированная"

        return None

    def _extract_executable(self, command: str) -> str:
        """
        Extract the actual executable being run from a command string.
        Handles: cmd /c foo, powershell -Command bar, bash -c baz
        Returns the base executable name without path or extension.
        """
        cmd = command.strip()

        # Try to parse with shlex (may fail on Windows paths with spaces)
        try:
            tokens = shlex.split(cmd, posix=False)
        except ValueError:
            # Fallback: simple split
            tokens = cmd.split()

        if not tokens:
            return ""

        executable = tokens[0].lower()

        # Strip common shell prefixes
        # cmd /c, powershell -Command, bash -c, etc.
        shell_wrappers = {
            "cmd": ["/c", "/k"],
            "cmd.exe": ["/c", "/k"],
            "powershell": ["-command", "-c", "-encodedcommand", "-e", "-enc"],
            "powershell.exe": ["-command", "-c", "-encodedcommand", "-e", "-enc"],
            "bash": ["-c"],
            "sh": ["-c"],
        }

        if executable in shell_wrappers and len(tokens) > 2:
            # Check if second token is a flag
            if tokens[1].lower() in shell_wrappers[executable]:
                # Real command is third token (or later)
                if len(tokens) > 2:
                    real_cmd = tokens[2].lower()
                    # Extract just the executable name
                    executable = real_cmd.split()[0] if " " in real_cmd else real_cmd

        # Strip path and extension
        executable = executable.split("\\")[-1].split("/")[-1]

        return executable

    def _looks_obfuscated(self, command: str) -> bool:
        """
        Heuristic check for obfuscated/encoded commands.
        Returns True if command looks suspicious.
        """
        # Long base64-looking strings (common in encoded payloads)
        if re.search(r"[A-Za-z0-9+/=]{100,}", command):
            return True

        # Excessive special characters (common in obfuscation)
        special_char_count = sum(1 for c in command if c in "^`$|&;<>(){}")
        if special_char_count > len(command) * 0.3:  # More than 30% special chars
            return True

        # Multiple layers of encoding/escaping
        if command.count("\\x") > 5 or command.count("\\u") > 5:
            return True

        return False

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "").strip()
        working_dir = kwargs.get("working_dir", "").strip()
        shell = kwargs.get("shell", "cmd").strip().lower()

        if not command:
            return ToolResult(success=False, error="command is required")

        # Safety check
        blocked_reason = self._is_blocked(command)
        if blocked_reason:
            # Full audit log for security — log entire command
            logger.warning(
                "CLI BLOCKED: %s\nFull command: %s\nShell: %s\nCwd: %s",
                blocked_reason, command, shell, working_dir,
            )
            return ToolResult(success=False, error=blocked_reason)

        # Default working directory
        if not working_dir:
            import os
            working_dir = os.path.expanduser("~")

        # Build shell command
        if shell == "powershell":
            args = ["powershell", "-NoProfile", "-Command", command]
        elif shell == "bash":
            args = ["bash", "-c", command]
        else:
            # cmd (Windows default)
            args = ["cmd", "/c", command]

        logger.info("CLI exec: %s (shell=%s, cwd=%s)", command[:100], shell, working_dir)

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return ToolResult(
                    success=False,
                    error=f"Команда превысила таймаут ({self._timeout} сек) и была убита.",
                )

            # Decode output
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            # Truncate if too long
            if len(out) > MAX_OUTPUT_LENGTH:
                out = out[:MAX_OUTPUT_LENGTH] + f"\n\n... (обрезано, всего {len(stdout)} байт)"
            if len(err) > MAX_OUTPUT_LENGTH:
                err = err[:MAX_OUTPUT_LENGTH] + f"\n\n... (обрезано)"

            exit_code = process.returncode

            # Format result
            parts = [f"Exit code: {exit_code}"]
            if out:
                parts.append(f"Output:\n{out}")
            if err:
                parts.append(f"Stderr:\n{err}")

            # Detect suspicious results — warn the LLM
            warnings: list[str] = []
            if exit_code == 0 and not out and not err:
                warnings.append(
                    "⚠️ Команда завершилась без вывода. "
                    "Это НЕ гарантирует, что действие выполнено. "
                    "Проверь результат перед тем как сообщать пользователю об успехе."
                )
            if exit_code == 0 and err:
                warnings.append(
                    "⚠️ Команда вернула exit code 0, но есть вывод в stderr. "
                    "Возможно что-то пошло не так. Прочитай stderr внимательно."
                )
            if warnings:
                parts.append("WARNINGS:\n" + "\n".join(warnings))

            result_text = "\n\n".join(parts)

            logger.info(
                "CLI result: exit=%d, stdout=%d bytes, stderr=%d bytes",
                exit_code, len(out), len(err),
            )

            return ToolResult(
                success=(exit_code == 0),
                data=result_text,
                error=f"Command failed (exit code {exit_code})" if exit_code != 0 else None,
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Shell '{shell}' not found. Try another shell.",
            )
        except Exception as e:
            logger.error("CLI exec failed: %s", e)
            return ToolResult(success=False, error=f"Ошибка выполнения: {e}")
