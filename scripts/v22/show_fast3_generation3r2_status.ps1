[CmdletBinding()]
param()

$Root="D:\us-tech-quant-results\fast3_autoresearch_generation3r2"
$Runtime=Join-Path $Root "agent_runtime"
$State=Join-Path $Runtime "launcher_state.json"

Write-Host "============================================================"
Write-Host "FAST3 GENERATION 3R2 STATUS"
Write-Host "============================================================"

if (Test-Path -LiteralPath $State) {
    Get-Content -LiteralPath $State -Raw
} else {
    Write-Host "No launcher state found."
}

Get-ChildItem -LiteralPath $Root -Filter "generation3r2_final_summary.json" -File -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 |
    ForEach-Object {
        Write-Host ""
        Write-Host "Final summary: $($_.FullName)"
        Get-Content -LiteralPath $_.FullName -Raw
    }

Get-ChildItem -LiteralPath $Runtime -Filter "*.last_message.md" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
