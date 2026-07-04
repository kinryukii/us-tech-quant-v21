Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_16_r3_current_lineage_downstream_refresh_commit.py"

Write-Host "STAGE_NAME=V20.16-R3_CURRENT_LINEAGE_DOWNSTREAM_REFRESH_COMMIT"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "CERTIFIED_SAFE_RERUN_REQUIRED=TRUE"
Write-Host "DRY_RUN_ARTIFACT_AS_FACTOR_OUTPUT_ALLOWED=FALSE"
Write-Host "OFFICIAL_ACTIVATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.16-R3 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
