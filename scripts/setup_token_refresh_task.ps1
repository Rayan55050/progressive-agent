# Create a Windows Scheduled Task to refresh CLIProxyAPI OAuth token every 6 hours
# This runs independently of the bot — ensures proxy stays alive even if bot is down

$taskName = "CLIProxyAPI-TokenRefresh"
$workDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = "python"  # Uses system Python from PATH. Change if needed.
$script = Join-Path $workDir "scripts\refresh_proxy_token.py"

# Remove old task if exists
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action
$action = New-ScheduledTaskAction -Execute $python -Argument "--check `"$script`"" -WorkingDirectory $workDir

# Trigger: every 6 hours
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 6)

# Settings
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Register
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Auto-refresh CLIProxyAPI OAuth token every 6 hours" -RunLevel Limited

Write-Output "Scheduled task '$taskName' created!"
Write-Output "Runs every 6 hours: $python $script --check"

# Show task info
Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State, Description
