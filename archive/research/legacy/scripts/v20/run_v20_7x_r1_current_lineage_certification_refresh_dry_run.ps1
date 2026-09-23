Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_7x_r1_current_lineage_certification_refresh_dry_run.py"

Write-Host "STAGE_NAME=V20.7X-R1_CURRENT_LINEAGE_CERTIFICATION_REFRESH_DRY_RUN"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "DRY_RUN_ONLY=TRUE"
Write-Host "CERTIFICATION_CLAIMED=FALSE"
Write-Host "V20_7X_PRODUCTION_MUTATION_ALLOWED=FALSE"
Write-Host "V20_8_TO_V20_16_MUTATION_ALLOWED=FALSE"
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
        throw "V20.7X-R1 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
