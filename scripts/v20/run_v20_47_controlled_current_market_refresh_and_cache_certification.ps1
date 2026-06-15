param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_47_controlled_current_market_refresh_and_cache_certification.py"

Write-Host "STAGE_NAME=V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"
Write-Host "CONTROLLED_PROVIDER_REFRESH_STAGE=TRUE"
Write-Host "WRAPPER_PROVIDER_IMPORT_USED=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_USED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_TRADING_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "DYNAMIC_WEIGHTING_MUTATED=FALSE"
Write-Host "RETURNS_CALCULATED=FALSE"
Write-Host "SCORES_RECOMPUTED=FALSE"
Write-Host "RANKINGS_RECOMPUTED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.47 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "FINAL_STATUS=PASS_V20_47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"
}
finally {
    Pop-Location
}
