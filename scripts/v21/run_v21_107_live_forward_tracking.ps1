param(
    [string]$RunId = "",
    [string]$OutputDir = "",
    [switch]$RepairMode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_107_live_forward_tracking.py"

Write-Host "STAGE=V21.107_LIVE_FORWARD_TRACKING_FOR_D_TOP20_HOLD_AND_D_TOP50_QUARTERLY"
Write-Host "LIVE_FORWARD_RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_ADOPTION_ALLOWED=FALSE"
Write-Host "BROKER_ACTION_ALLOWED=FALSE"

$ArgsList = @($StageScript, "--root", $RepoRoot)
if ($RunId) { $ArgsList += @("--run-id", $RunId) }
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($RepairMode) { $ArgsList += "--repair-mode" }

Push-Location $RepoRoot
try {
    & python @ArgsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
