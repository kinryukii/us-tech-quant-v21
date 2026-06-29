param(
    [string]$RunId = "",
    [string]$OutputDir = "",
    [int]$MaxSamples = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_105_abcd_random_252d_monthly_rebalance_backtest.py"

Write-Host "STAGE=V21.105_ABCD_RANDOM_252D_MONTHLY_REBALANCE_BACKTEST"
Write-Host "MODE=RANDOM_252D_MONTHLY_REBALANCE"
Write-Host "REBALANCE_INTERVAL=21"
Write-Host "TRANSACTION_COST_BPS=0,10,20"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"
Write-Host "EVENT_RISK_INTEGRATED=FALSE"

$ArgsList = @($StageScript, "--root", $RepoRoot)
if ($RunId) { $ArgsList += @("--run-id", $RunId) }
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($MaxSamples -gt 0) { $ArgsList += @("--max-samples", $MaxSamples) }

Push-Location $RepoRoot
try {
    & python @ArgsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
