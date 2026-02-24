# Stop existing proxy
$proxyProcs = Get-Process -Name "cli-proxy-api" -ErrorAction SilentlyContinue
if ($proxyProcs) {
    foreach ($p in $proxyProcs) {
        Write-Output "Stopping proxy PID=$($p.Id)"
        Stop-Process -Id $p.Id -Force
    }
    Start-Sleep -Seconds 2
}

# Run claude-login (opens browser for OAuth)
$proxyDir = Join-Path $PSScriptRoot "..\CLIProxyAPI"
Write-Output "Starting Claude OAuth login..."
Write-Output "(Browser will open for authentication)"
Start-Process -FilePath "$proxyDir\cli-proxy-api.exe" -ArgumentList "-claude-login" -WorkingDirectory $proxyDir -Wait -NoNewWindow

Write-Output ""
Write-Output "Login complete. Starting proxy..."
$proc = Start-Process -FilePath "$proxyDir\cli-proxy-api.exe" -WorkingDirectory $proxyDir -PassThru -WindowStyle Hidden
Write-Output "Proxy started PID=$($proc.Id)"

Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/v1/models' -UseBasicParsing -TimeoutSec 5
    Write-Output "Proxy health: OK ($($r.StatusCode))"
} catch {
    Write-Output "Proxy health: FAILED - $($_.Exception.Message)"
}
