Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_054_r1_post_migration_source_isolation_recheck.py"

Write-Host "STAGE_NAME=V21.054-R1_POST_MIGRATION_SOURCE_ISOLATION_RECHECK"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "RECHECK_ONLY=TRUE"
Write-Host "DELETION_ALLOWED=FALSE"
Write-Host "ARCHIVE_ALLOWED=FALSE"
Write-Host "MIGRATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_ACTIVATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) { throw "V21.054-R1 failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
