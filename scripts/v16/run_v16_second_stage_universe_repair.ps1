param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "repair_v16_second_stage_universe.py"

Write-Host "STAGE_NAME=V16_SECOND_STAGE_UNIVERSE_REPAIR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_CONNECTED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V16 second-stage universe repair failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
