param(
    [string]$RunId = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Script = Join-Path $ScriptDir "v21_104_r2_holdings_persistence_and_ticker_contribution_replay.py"

Write-Host "STAGE=V21.104-R2_HOLDINGS_PERSISTENCE_AND_TICKER_CONTRIBUTION_REPLAY"
Write-Host "SOURCE_V21_104_RUN_ID=20260623_163856"
Write-Host "SOURCE_V21_104_R1_RUN_ID=20260623_165210"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"

$ArgsList = @($Script, "--root", $RepoRoot)
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
