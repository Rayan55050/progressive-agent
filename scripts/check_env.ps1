$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    $lines = Get-Content $envFile
    foreach ($line in $lines) {
        if ($line -match "^OPENAI_API_KEY=(.*)$") {
            $val = $matches[1].Trim()
            if ($val -eq "" -or $val -eq "sk-xxx") {
                Write-Output "OPENAI_API_KEY: EMPTY or placeholder"
            } else {
                Write-Output "OPENAI_API_KEY: SET (length $($val.Length) chars)"
            }
            exit
        }
    }
    Write-Output "OPENAI_API_KEY: NOT FOUND in .env"
} else {
    Write-Output ".env file not found"
}
