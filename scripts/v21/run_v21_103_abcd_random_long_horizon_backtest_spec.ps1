param(
    [string]$OutputDir = "",
    [string]$RunId = "",
    [int]$SeedCount = 30,
    [int]$DatesPerSeed = 100,
    [int]$MaxSamples = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_103_abcd_random_long_horizon_backtest_spec.py"

Write-Host "STAGE=V21.103_ABCD_RANDOM_LONG_HORIZON_BACKTEST_SPEC"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_OR_TRADING_ACTION_ALLOWED=FALSE"
Write-Host "EVENT_RISK_INTEGRATED=FALSE"

$ArgsList = @($StageScript, "--root", $RepoRoot, "--seed-count", $SeedCount, "--dates-per-seed", $DatesPerSeed)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($RunId) { $ArgsList += @("--run-id", $RunId) }
if ($MaxSamples -gt 0) { $ArgsList += @("--max-samples", $MaxSamples) }

Push-Location $RepoRoot
try {
    & python @ArgsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
