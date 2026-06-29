param(
    [string]$RunId = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_105_r2_rebalance_gate_backtest.py"

Write-Host "STAGE=V21.105-R2_REBALANCE_GATE_BACKTEST"
Write-Host "SOURCE_V21_105_RUN_ID=20260623_122740"
Write-Host "SOURCE_V21_105_R1_RUN_ID=20260623_125503"
Write-Host "DIAGNOSTIC_ONLY=TRUE"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"

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
