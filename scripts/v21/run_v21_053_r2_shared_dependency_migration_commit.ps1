Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_053_r2_shared_dependency_migration_commit.py"

Write-Host "STAGE_NAME=V21.053-R2_SHARED_DEPENDENCY_MIGRATION_COMMIT"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "MIGRATION_COMMIT_ALLOWED=TRUE"
Write-Host "DELETION_ALLOWED=FALSE"
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
    if ($LASTEXITCODE -ne 0) { throw "V21.053-R2 failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
