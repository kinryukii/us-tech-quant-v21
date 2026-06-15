param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "repair_v18_current_raw105_factor_pack.py"

Write-Host "STAGE_NAME=V18_CURRENT_RAW105_FACTOR_PACK_REPAIR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_CONNECTED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V18 current RAW105 factor pack repair failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
