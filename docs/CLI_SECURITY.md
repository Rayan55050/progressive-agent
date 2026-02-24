# CLI Tool Security Model

## Overview

The `cli_exec` tool allows the agent to execute system commands. This is a powerful capability that requires robust security controls to prevent command injection attacks.

**Design Philosophy:**
- **Personal Use:** Designed for a single trusted owner, not multi-tenant/public deployment
- **Universal Fallback:** Intentionally broad access (owner wants this as a "do anything" tool)
- **Defense in Depth:** Multiple validation layers catch common attack patterns
- **Audit Everything:** Full logging for security review

## Security Controls

### 1. Blocked Executables

Catastrophic/irreversible commands are blocked at the executable level:

```
format, mkfs, dd, shutdown, reboot, bcdedit, diskpart
```

**Example:**
```bash
# BLOCKED
format C:
shutdown /s /t 0
dd if=/dev/zero of=/dev/sda

# ALLOWED
echo "format" in text is fine
git add .  # contains "dd" but not the dd executable
```

### 2. Pattern-Based Blocking (Regex)

Dangerous command patterns are blocked regardless of how they're invoked:

**Destructive Operations:**
- `del /s`, `rd /s`, `rmdir /s` (recursive delete)
- `rm -rf /`, `rm -rf ~`, `rm -rf *`

**System Modifications:**
- `reg delete`, `reg add` (registry edits)
- `net user`, `net localgroup` (user management)

**Obfuscation/Encoding:**
- `powershell -encodedcommand` (base64 encoded payloads)
- `certutil -decode` (common AV bypass technique)
- `iex $variable` (runtime variable execution)

**Download-Execute Chains:**
- `curl http://... | bash`
- `wget http://... | sh`
- `Invoke-WebRequest | iex`
- `bitsadmin /transfer` (BITS admin stealth download)

**Process Injection:**
- `Invoke-Mimikatz`
- `Invoke-Shellcode`
- `Invoke-ReflectivePEInjection`

### 3. Obfuscation Heuristics

Commands that "look suspicious" are blocked even if they don't match exact patterns:

- **Long base64 strings:** 100+ chars of base64-encoded data
- **Excessive special characters:** >30% of command is `^`\`$|&;<>(){}` chars
- **Multiple encoding layers:** Many `\x` or `\u` escape sequences

### 4. Executable Extraction

The tool extracts the **actual executable** being run, handling shell wrappers:

```bash
cmd /c shutdown    → extracts "shutdown" → BLOCKED
powershell -Command format  → extracts "format" → BLOCKED
bash -c "echo format"  → extracts "echo" → ALLOWED
```

This prevents bypasses like:
```bash
# Old vulnerability: substring "dd" blocked "Add-Content"
# New approach: extracts "add-content" → ALLOWED

# Old vulnerability: "format" blocked "echo format in text"
# New approach: extracts "echo" → ALLOWED
```

### 5. Timeout Protection

All commands have a **30-second timeout** to prevent:
- Denial of service via infinite loops
- Resource exhaustion
- Accidental long-running processes

### 6. Audit Logging

**All commands are logged:**

```python
# Allowed commands
logger.info("CLI exec: %s (shell=%s, cwd=%s)", command, shell, working_dir)

# Blocked commands (FULL audit log)
logger.warning(
    "CLI BLOCKED: %s\nFull command: %s\nShell: %s\nCwd: %s",
    blocked_reason, command, shell, working_dir,
)
```

This creates a security audit trail for review.

## Known Limitations

### Static Analysis Only

The filter operates on **static text**, not runtime behavior. It cannot detect:

1. **String concatenation at runtime:**
   ```powershell
   $cmd = 'shut' + 'down'; & $cmd /s
   ```

2. **Environment variable indirection:**
   ```powershell
   $env:COMSPEC /c shutdown /s
   ```

3. **File-based payload staging:**
   ```bash
   echo "shutdown /s" > payload.bat
   payload.bat
   ```

**Mitigation:**
- Trust model: Owner is trusted, LLM is prompted not to generate such commands
- Audit logs: Post-incident review can catch these patterns
- Layered defense: Even if command executes, OS-level protections (UAC, permissions) may block it

### Legitimate Use Cases May Be Blocked

Some legitimate commands might trigger false positives:

```bash
# Might be blocked if it contains a blocked pattern
powershell -Command "Get-ChildItem | ForEach-Object { ... }"
```

**Mitigation:**
- Owner can review logs and request pattern adjustments
- Use alternative syntax that doesn't trigger patterns
- For trusted scripts, stage them as files instead of inline commands

### Not a Sandbox

This is **not** a full sandbox or VM isolation. It relies on:
- Blocklists (can have bypasses)
- OS permissions (Windows UAC, file permissions)
- Owner trust model

**For enterprise/public use**, consider:
- Full containerization (Docker, Firecracker)
- Mandatory Access Control (AppArmor, SELinux)
- Process-level sandboxing (bubblewrap, firejail)

## Testing

Comprehensive security test suite in `tests/test_cli_security.py`:

```bash
pytest tests/test_cli_security.py -v
```

**Test coverage:**
- 17 legitimate commands (should pass)
- 9 blocked executables (format, shutdown, etc.)
- 6 destructive patterns (rm -rf, del /s, etc.)
- 4 registry/system modifications
- 11 obfuscation/encoding bypasses
- 3 process injection tools
- Executable extraction logic
- Obfuscation heuristics
- Async execution tests

**All 64 tests pass** as of 2026-02-20.

## Recommendations

### For Owner

1. **Review audit logs** periodically:
   ```bash
   grep "CLI BLOCKED" data/logs/agent.log
   grep "CLI exec" data/logs/agent.log
   ```

2. **Monitor for suspicious patterns:**
   - Many blocked commands in short time
   - Unusual executables or paths
   - Commands with encoding/obfuscation

3. **Keep patterns updated:**
   - Add new attack patterns as they're discovered
   - Review security advisories for new bypass techniques

### For Future Maintainers

1. **Don't weaken the blocklist** without careful review
2. **Add tests for new patterns** before deploying
3. **Log everything** — audit trail is critical
4. **Consider allowlist** if threat model changes (e.g., public deployment)

## Security vs. Usability Trade-off

Current design prioritizes **usability for trusted owner** over paranoid security:

✅ **Pros:**
- Broad access (universal fallback tool)
- Simple to use (no complex approval flows)
- Catches common attacks (format, shutdown, encoded payloads)
- Full audit trail

❌ **Cons:**
- Not suitable for public/multi-tenant deployment
- Can't catch runtime string manipulation
- Relies on LLM not generating malicious commands
- No process isolation

**This is intentional** — owner wants a "just works" agent, not a locked-down enterprise system.

## Changelog

### 2026-02-20: Security Overhaul
- **Replaced substring blocklist** with executable extraction + pattern matching
- **Added 20+ regex patterns** for common attack vectors
- **Added obfuscation heuristics** (base64, special chars, encoding)
- **Improved audit logging** (full command text in blocked logs)
- **Added comprehensive test suite** (64 tests, all passing)
- **Documented security model** and known limitations

### Previous (Vulnerable)
- Simple substring matching in `BLOCKED_COMMANDS`
- Easily bypassed (e.g., "format" blocked "echo format is ok")
- No protection against encoding/obfuscation
- No audit logging for blocked commands

## References

- OWASP Command Injection: https://owasp.org/www-community/attacks/Command_Injection
- PowerShell Attack Patterns: https://attack.mitre.org/techniques/T1059/001/
- Living Off The Land Binaries (LOLBins): https://lolbas-project.github.io/
