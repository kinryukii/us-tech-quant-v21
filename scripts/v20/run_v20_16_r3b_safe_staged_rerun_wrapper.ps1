Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_16_r3b_safe_staged_rerun_wrapper.py"

Write-Host "STAGE_NAME=V20.16-R3B_SAFE_STAGED_RERUN_WRAPPER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "STAGING_ONLY=TRUE"
Write-Host "PRODUCTION_MUTATION_ALLOWED=FALSE"
Write-Host "CERTIFIED_V20_7X_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_ACTIVATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"
Write-Host "TRADE_ACTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    python $StageScript
    if ($LASTEXITCODE -ne 0) { throw "V20.16-R3B failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
