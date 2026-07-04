Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_7x_r2_current_lineage_certification_refresh_commit.py"

Write-Host "STAGE_NAME=V20.7X-R2_CURRENT_LINEAGE_CERTIFICATION_REFRESH_COMMIT"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "V20_7X_ONLY_MUTATION=TRUE"
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
    if ($LASTEXITCODE -ne 0) { throw "V20.7X-R2 failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
