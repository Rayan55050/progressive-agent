$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) {
    Write-Output ".env not found"
    exit
}
$lines = Get-Content $envFile
$keys = @("ANTHROPIC_API_KEY", "CLAUDE_PROXY_URL", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "DEEPL_API_KEY", "FINNHUB_API_KEY")
foreach ($key in $keys) {
    $found = $false
    foreach ($line in $lines) {
        if ($line -match "^$key=(.*)$") {
            $val = $Matches[1].Trim()
            if ($val -eq "" -or $val -eq "sk-xxx" -or $val -eq "sk-ant-xxx") {
                Write-Output "$key : EMPTY/placeholder"
            } else {
                $masked = $val.Substring(0, [Math]::Min(8, $val.Length)) + "***"
                Write-Output "$key : SET ($masked, $($val.Length) chars)"
            }
            $found = $true
            break
        }
    }
    if (-not $found) {
        Write-Output "$key : NOT IN FILE"
    }
}
