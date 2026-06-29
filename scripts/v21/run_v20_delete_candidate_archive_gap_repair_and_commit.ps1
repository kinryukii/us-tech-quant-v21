Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_delete_candidate_archive_gap_repair_and_commit.py"

Write-Host "STAGE_NAME=V20_DELETE_CANDIDATE_ARCHIVE_GAP_REPAIR_AND_COMMIT"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "DELETE_COMMIT_ALLOWED_FOR_EXACT_QUEUE=TRUE"
Write-Host "QUEUE_BOUNDARY_COUNT=117"
Write-Host "OFFICIAL_ACTIVATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) { throw "V20 delete candidate archive gap repair and commit failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
