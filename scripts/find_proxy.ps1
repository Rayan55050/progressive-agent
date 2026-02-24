# Find process listening on port 8317
$connections = Get-NetTCPConnection -LocalPort 8317 -ErrorAction SilentlyContinue
if ($connections) {
    foreach ($conn in $connections) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
            Write-Output "PID: $($proc.Id)"
            Write-Output "Name: $($proc.ProcessName)"
            Write-Output "CMD: $cmdLine"
            Write-Output "---"
        }
    }
} else {
    Write-Output "Nothing listening on port 8317"
}
