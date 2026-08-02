[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$Root = "D:\us-tech-quant-results\fast3_autoresearch_generation3r3"
$Runtime = Join-Path $Root "agent_runtime"
$State = Join-Path $Runtime "launcher_state.json"

Write-Host "============================================================"
Write-Host "FAST3 GENERATION 3R3 STATUS"
Write-Host "============================================================"

if (Test-Path -LiteralPath $State) {
    Write-Host ""
    Write-Host "Launcher state:"
    Get-Content -LiteralPath $State -Raw
}
else {
    Write-Host ""
    Write-Host "No launcher state found."
}

$checkpoint = Get-ChildItem -LiteralPath $Root `
    -Filter "generation3r3_checkpoint.json" `
    -File -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1

if ($null -ne $checkpoint) {
    Write-Host ""
    Write-Host "Latest checkpoint:"
    Write-Host "  $($checkpoint.FullName)"
    Get-Content -LiteralPath $checkpoint.FullName -Raw
}

$summary = Get-ChildItem -LiteralPath $Root `
    -Filter "generation3r3_final_summary.json" `
    -File -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1

if ($null -ne $summary) {
    Write-Host ""
    Write-Host "Final summary:"
    Write-Host "  $($summary.FullName)"
    Get-Content -LiteralPath $summary.FullName -Raw
}

Write-Host ""
Write-Host "Recent replies:"
Get-ChildItem -LiteralPath $Runtime `
    -Filter "*.last_message.md" `
    -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 5 FullName, Length, LastWriteTime
