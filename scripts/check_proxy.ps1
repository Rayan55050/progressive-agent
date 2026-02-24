try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8317/v1/models' -UseBasicParsing -TimeoutSec 5
    Write-Output "Proxy status: $($r.StatusCode)"
    Write-Output $r.Content
} catch {
    Write-Output "Proxy error: $($_.Exception.Message)"
}
