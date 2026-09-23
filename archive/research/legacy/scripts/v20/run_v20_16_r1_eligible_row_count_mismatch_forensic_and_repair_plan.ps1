Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_16_r1_eligible_row_count_mismatch_forensic_and_repair_plan.py"

Write-Host "STAGE_NAME=V20.16-R1_ELIGIBLE_ROW_COUNT_MISMATCH_FORENSIC_AND_REPAIR_PLAN"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "FORENSIC_AUDIT_ONLY=TRUE"
Write-Host "PRODUCTION_OUTPUT_MUTATION_ALLOWED=FALSE"
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
        throw "V20.16-R1 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
