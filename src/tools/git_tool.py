"""
Git tool — first-class git operations for the agent.

Instead of going through cli_exec for every git command,
this tool provides safe, structured git operations with
proper output parsing and safety checks.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Default repo path (this project)
DEFAULT_REPO = str(Path(__file__).resolve().parent.parent.parent)

# Maximum output length
MAX_OUTPUT = 5000

# Timeout for git operations (seconds)
GIT_TIMEOUT = 30

# Operations that are always safe (read-only)
SAFE_OPS = {"status", "diff", "log", "branch", "remote", "stash_list", "show", "blame"}

# Operations that modify state (need care but are fine)
WRITE_OPS = {"add", "commit", "stash", "stash_pop", "checkout", "pull", "fetch", "tag"}

# Operations that are dangerous (push to remote, reset, etc.)
DANGEROUS_OPS = {"push", "reset", "clean", "rebase"}

# Blocked operations (destructive, no undo)
BLOCKED_OPS = {"push --force", "reset --hard HEAD~", "clean -fd", "filter-branch"}


async def _run_git(args: list[str], cwd: str, timeout: int = GIT_TIMEOUT) -> tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    cmd = ["git"] + args
    logger.info("Git: %s (cwd=%s)", " ".join(cmd), cwd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", f"Git command timed out after {timeout}s"

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        return proc.returncode or 0, out, err

    except FileNotFoundError:
        return -1, "", "git not found in PATH"
    except Exception as e:
        return -1, "", str(e)


def _truncate(text: str, max_len: int = MAX_OUTPUT) -> str:
    """Truncate text if too long."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n... (truncated, {len(text)} chars total)"


class GitTool:
    """Git operations tool — status, diff, log, commit, push, pull, etc."""

    def __init__(self, default_repo: str = DEFAULT_REPO) -> None:
        self._default_repo = default_repo

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git",
            description=(
                "Execute git operations on a repository. "
                "Supports: status, diff, log, add, commit, push, pull, fetch, "
                "checkout, branch, remote, stash, stash_pop, stash_list, show, blame, tag, "
                "reset, clone. "
                "Default repo: this project (Progressive Agent). "
                "For safe read ops (status, diff, log) — just call. "
                "For write ops (commit, push) — include a clear message/reason."
            ),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description=(
                        "Git operation: status, diff, log, add, commit, push, pull, "
                        "fetch, checkout, branch, remote, stash, stash_pop, stash_list, "
                        "show, blame, tag, reset, clone"
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="args",
                    type="string",
                    description=(
                        "Arguments for the operation. Examples: "
                        "commit: 'Fix bug in email monitor' (commit message), "
                        "add: '.' or 'src/tools/git_tool.py', "
                        "checkout: 'main' or '-b new-feature', "
                        "log: '--oneline -10', "
                        "diff: '--staged' or 'src/main.py', "
                        "push: 'origin main', "
                        "clone: 'https://github.com/user/repo.git', "
                        "branch: '-a' or 'new-branch', "
                        "show: 'HEAD' or 'abc1234', "
                        "blame: 'src/main.py', "
                        "tag: 'v1.0.0' or '-l', "
                        "reset: '--soft HEAD~1'"
                    ),
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="repo_path",
                    type="string",
                    description="Path to git repository (default: this project)",
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation", "").strip().lower()
        args_str = kwargs.get("args", "").strip()
        repo_path = kwargs.get("repo_path", "").strip() or self._default_repo

        if not operation:
            return ToolResult(success=False, error="operation is required")

        # Route to handler
        handler = getattr(self, f"_op_{operation}", None)
        if handler is None:
            return ToolResult(
                success=False,
                error=f"Unknown git operation: '{operation}'. "
                      f"Supported: status, diff, log, add, commit, push, pull, fetch, "
                      f"checkout, branch, remote, stash, stash_pop, stash_list, show, blame, tag, reset, clone",
            )

        try:
            return await handler(args_str, repo_path)
        except Exception as e:
            logger.error("Git %s failed: %s", operation, e, exc_info=True)
            return ToolResult(success=False, error=f"Git {operation} failed: {e}")

    # --- Read-only operations ---

    async def _op_status(self, args: str, repo: str) -> ToolResult:
        """git status"""
        git_args = ["status", "--short", "--branch"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git status failed (code {code})")
        return ToolResult(success=True, data=out or "Working tree clean")

    async def _op_diff(self, args: str, repo: str) -> ToolResult:
        """git diff"""
        git_args = ["diff"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git diff failed (code {code})")
        return ToolResult(success=True, data=_truncate(out) or "No differences")

    async def _op_log(self, args: str, repo: str) -> ToolResult:
        """git log"""
        git_args = ["log", "--oneline", "-20"]
        if args:
            git_args = ["log"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git log failed (code {code})")
        return ToolResult(success=True, data=_truncate(out) or "No commits")

    async def _op_show(self, args: str, repo: str) -> ToolResult:
        """git show"""
        git_args = ["show", "--stat"]
        if args:
            git_args = ["show"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git show failed (code {code})")
        return ToolResult(success=True, data=_truncate(out))

    async def _op_blame(self, args: str, repo: str) -> ToolResult:
        """git blame"""
        if not args:
            return ToolResult(success=False, error="blame requires a file path")
        git_args = ["blame"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git blame failed (code {code})")
        return ToolResult(success=True, data=_truncate(out))

    async def _op_branch(self, args: str, repo: str) -> ToolResult:
        """git branch"""
        git_args = ["branch"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git branch failed (code {code})")
        return ToolResult(success=True, data=out or "No branches")

    async def _op_remote(self, args: str, repo: str) -> ToolResult:
        """git remote"""
        git_args = ["remote", "-v"]
        if args:
            git_args = ["remote"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git remote failed (code {code})")
        return ToolResult(success=True, data=out or "No remotes")

    async def _op_stash_list(self, args: str, repo: str) -> ToolResult:
        """git stash list"""
        code, out, err = await _run_git(["stash", "list"], repo)
        if code != 0:
            return ToolResult(success=False, error=err)
        return ToolResult(success=True, data=out or "No stashes")

    # --- Write operations ---

    async def _op_add(self, args: str, repo: str) -> ToolResult:
        """git add"""
        if not args:
            return ToolResult(success=False, error="add requires file path(s). Use '.' for all.")
        git_args = ["add"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git add failed (code {code})")
        # Show what was staged
        _, status, _ = await _run_git(["status", "--short"], repo)
        return ToolResult(success=True, data=f"Added. Current status:\n{status}")

    async def _op_commit(self, args: str, repo: str) -> ToolResult:
        """git commit -m <message>"""
        if not args:
            return ToolResult(success=False, error="commit requires a message")
        # args = commit message
        git_args = ["commit", "-m", args]
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git commit failed (code {code})")
        return ToolResult(success=True, data=out)

    async def _op_pull(self, args: str, repo: str) -> ToolResult:
        """git pull"""
        git_args = ["pull"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo, timeout=60)
        if code != 0:
            return ToolResult(success=False, error=err or f"git pull failed (code {code})")
        return ToolResult(success=True, data=out or "Already up to date")

    async def _op_fetch(self, args: str, repo: str) -> ToolResult:
        """git fetch"""
        git_args = ["fetch"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo, timeout=60)
        if code != 0:
            return ToolResult(success=False, error=err or f"git fetch failed (code {code})")
        return ToolResult(success=True, data=out or err or "Fetched (no new changes)")

    async def _op_checkout(self, args: str, repo: str) -> ToolResult:
        """git checkout"""
        if not args:
            return ToolResult(success=False, error="checkout requires a branch or file path")
        git_args = ["checkout"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git checkout failed (code {code})")
        return ToolResult(success=True, data=out or err or "Checked out successfully")

    async def _op_stash(self, args: str, repo: str) -> ToolResult:
        """git stash"""
        git_args = ["stash"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git stash failed (code {code})")
        return ToolResult(success=True, data=out or "Stashed")

    async def _op_stash_pop(self, args: str, repo: str) -> ToolResult:
        """git stash pop"""
        code, out, err = await _run_git(["stash", "pop"], repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git stash pop failed (code {code})")
        return ToolResult(success=True, data=out)

    async def _op_tag(self, args: str, repo: str) -> ToolResult:
        """git tag"""
        git_args = ["tag"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git tag failed (code {code})")
        return ToolResult(success=True, data=out or "No tags")

    # --- Dangerous operations ---

    async def _op_push(self, args: str, repo: str) -> ToolResult:
        """git push"""
        # Block force push
        if "--force" in args or "-f" in args.split():
            return ToolResult(success=False, error="Force push is blocked for safety. Use regular push.")
        git_args = ["push"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo, timeout=60)
        if code != 0:
            return ToolResult(success=False, error=err or f"git push failed (code {code})")
        return ToolResult(success=True, data=out or err or "Pushed successfully")

    async def _op_reset(self, args: str, repo: str) -> ToolResult:
        """git reset (--hard is blocked)"""
        if "--hard" in args:
            return ToolResult(
                success=False,
                error="git reset --hard is blocked for safety. Use --soft or --mixed.",
            )
        git_args = ["reset"]
        if args:
            git_args.extend(args.split())
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git reset failed (code {code})")
        return ToolResult(success=True, data=out or "Reset done")

    async def _op_clone(self, args: str, repo: str) -> ToolResult:
        """git clone"""
        if not args:
            return ToolResult(success=False, error="clone requires a URL")
        git_args = ["clone"] + args.split()
        code, out, err = await _run_git(git_args, repo, timeout=120)
        if code != 0:
            return ToolResult(success=False, error=err or f"git clone failed (code {code})")
        return ToolResult(success=True, data=out or err or "Cloned successfully")

    async def _op_clean(self, args: str, repo: str) -> ToolResult:
        """git clean — dry run only by default."""
        if "-f" in args.split() and "-n" not in args:
            return ToolResult(
                success=False,
                error="git clean -f is blocked. Use 'clean -n' (dry run) first to review.",
            )
        git_args = ["clean", "-n"]  # Always dry run
        if args:
            git_args = ["clean"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err)
        return ToolResult(success=True, data=out or "Nothing to clean")

    async def _op_rebase(self, args: str, repo: str) -> ToolResult:
        """git rebase (non-interactive only)."""
        if "-i" in args.split():
            return ToolResult(success=False, error="Interactive rebase not supported (requires TTY)")
        if not args:
            return ToolResult(success=False, error="rebase requires a target branch")
        git_args = ["rebase"] + args.split()
        code, out, err = await _run_git(git_args, repo)
        if code != 0:
            return ToolResult(success=False, error=err or f"git rebase failed (code {code})")
        return ToolResult(success=True, data=out or "Rebased successfully")
