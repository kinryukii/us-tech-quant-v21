Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_16_r3a_safe_rerun_execution_failure_forensic_and_wrapper_plan.py"

Write-Host "STAGE_NAME=V20.16-R3A_SAFE_RERUN_EXECUTION_FAILURE_FORENSIC_AND_WRAPPER_PLAN"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "FORENSIC_ONLY=TRUE"
Write-Host "PRODUCTION_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_ACTIVATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) { throw "V20.16-R3A failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
