Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_052_r3_manual_review_resolution.py"

Write-Host "STAGE_NAME=V21.052-R3_MANUAL_REVIEW_RESOLUTION"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "CLASSIFICATION_ONLY=TRUE"
Write-Host "DELETION_ALLOWED=FALSE"
Write-Host "MIGRATION_ALLOWED=FALSE"
Write-Host "ARCHIVE_ALLOWED=FALSE"
Write-Host "OFFICIAL_ACTIVATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) { throw "V21.052-R3 failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
