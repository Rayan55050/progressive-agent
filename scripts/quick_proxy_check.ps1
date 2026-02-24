Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/v1/models' -UseBasicParsing -TimeoutSec 10 -Headers @{"Authorization"="Bearer progressive-agent-local"}
    Write-Output "Status: $($r.StatusCode)"
    Write-Output $r.Content
} catch {
    Write-Output "FAILED: $($_.Exception.Message)"
    # Try without auth header
    try {
        $r2 = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/v1/models' -UseBasicParsing -TimeoutSec 10
        Write-Output "Without auth: $($r2.StatusCode)"
        Write-Output $r2.Content
    } catch {
        Write-Output "Without auth also failed: $($_.Exception.Message)"
    }
}
