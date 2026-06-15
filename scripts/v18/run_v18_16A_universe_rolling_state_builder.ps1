param(
    [string]$Root = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"

Write-Host "=== V18.16A UNIVERSE ROLLING STATE BUILDER START ==="
Write-Host "ROOT: $Root"
Write-Host "MODE: STATE_BUILDER_ONLY"
Write-Host "PRICE_UPDATE_EXECUTED: FALSE"
Write-Host "EVENT_UPDATE_EXECUTED: FALSE"
Write-Host "OFFICIAL_DECISION_IMPACT: NONE"
Write-Host "AUTO_TRADE: DISABLED"
Write-Host "AUTO_SELL: DISABLED"

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\v18\v18_16A_universe_rolling_state_builder.py"

if (-not (Test-Path $Python)) {
    $Python = "python"
}
if (-not (Test-Path $Script)) {
    throw "Missing V18.16A Python script: $Script"
}

& $Python $Script --root $Root
exit $LASTEXITCODE
