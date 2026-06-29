param(
    [string]$RunId = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_104_abcd_random_252d_hold_backtest_full_run.py"

Write-Host "STAGE=V21.104_ABCD_RANDOM_252D_HOLD_BACKTEST_FULL_RUN"
Write-Host "MODE=RANDOM_252D_HOLD_ONLY"
Write-Host "SEED_COUNT=30"
Write-Host "DATES_PER_SEED=100"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"
Write-Host "EVENT_RISK_INTEGRATED=FALSE"

$ArgsList = @($StageScript, "--root", $RepoRoot)
if ($RunId) { $ArgsList += @("--run-id", $RunId) }
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }

Push-Location $RepoRoot
try {
    & python @ArgsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
