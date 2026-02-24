$ErrorActionPreference = 'SilentlyContinue'

# Find and kill any running bot processes
$pythonProcs = Get-Process python -ErrorAction SilentlyContinue
foreach ($proc in $pythonProcs) {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
        if ($cmdLine -like '*src.main*' -or $cmdLine -like '*progressive-agent*') {
            Write-Output "Killing bot process PID=$($proc.Id): $cmdLine"
            Stop-Process -Id $proc.Id -Force
        }
    } catch {}
}

# Also kill watchdog if running
foreach ($proc in $pythonProcs) {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
        if ($cmdLine -like '*watchdog*') {
            Write-Output "Killing watchdog PID=$($proc.Id)"
            Stop-Process -Id $proc.Id -Force
        }
    } catch {}
}

Start-Sleep -Seconds 2

# Start bot in background
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "python"  # Uses system Python from PATH. Change if needed.

Write-Output "Starting bot..."
$proc = Start-Process -FilePath $python -ArgumentList "-m", "src.main" -WorkingDirectory $projectDir -PassThru -WindowStyle Hidden -RedirectStandardOutput "$projectDir\databot_output.log" -RedirectStandardError "$projectDir\databot_startup.log"
Write-Output "Bot started with PID=$($proc.Id)"

Start-Sleep -Seconds 3

# Check if still running
$check = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
if ($check) {
    Write-Output "Bot is running (PID=$($proc.Id))"
} else {
    Write-Output "Bot process died! Check logs:"
    Get-Content "$projectDir\databot_startup.log" -Tail 20
}
