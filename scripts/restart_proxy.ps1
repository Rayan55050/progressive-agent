# Kill existing proxy
$proxyProcs = Get-Process -Name "cli-proxy-api" -ErrorAction SilentlyContinue
if ($proxyProcs) {
    foreach ($p in $proxyProcs) {
        Write-Output "Killing cli-proxy-api PID=$($p.Id)"
        Stop-Process -Id $p.Id -Force
    }
    Start-Sleep -Seconds 2
} else {
    Write-Output "No cli-proxy-api process found"
}

# Start proxy again
$proxyDir = Join-Path $PSScriptRoot "..\CLIProxyAPI"
$proxyExe = Join-Path $proxyDir "cli-proxy-api.exe"
if (Test-Path $proxyExe) {
    Write-Output "Starting cli-proxy-api..."
    $proc = Start-Process -FilePath $proxyExe -WorkingDirectory $proxyDir -PassThru -WindowStyle Hidden
    Write-Output "Proxy started with PID=$($proc.Id)"
    Start-Sleep -Seconds 3

    # Check if alive
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/v1/models' -UseBasicParsing -TimeoutSec 5
        Write-Output "Proxy health: $($r.StatusCode)"
        Write-Output $r.Content
    } catch {
        Write-Output "Proxy health check failed: $($_.Exception.Message)"
    }
} else {
    Write-Output "ERROR: $proxyExe not found!"
}
