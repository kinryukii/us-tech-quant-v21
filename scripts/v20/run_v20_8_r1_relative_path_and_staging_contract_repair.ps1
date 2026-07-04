Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_8_r1_relative_path_and_staging_contract_repair.py"

Write-Host "STAGE_NAME=V20.8-R1_RELATIVE_PATH_AND_STAGING_CONTRACT_REPAIR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "STAGING_SMOKE_ONLY=TRUE"
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
    if ($LASTEXITCODE -ne 0) { throw "V20.8-R1 failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
