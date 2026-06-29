param(
    [string]$RunId = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Script = Join-Path $ScriptDir "v21_104_r1_d_long_horizon_edge_decomposition.py"

Write-Host "STAGE=V21.104-R1_D_LONG_HORIZON_EDGE_DECOMPOSITION"
Write-Host "SOURCE_RUN_ID=20260623_163856"
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
