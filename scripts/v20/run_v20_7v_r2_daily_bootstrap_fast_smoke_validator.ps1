Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_7v_r2_daily_bootstrap_fast_smoke_validator.py"

Write-Host "STAGE_NAME=V20.7V-R2_DAILY_BOOTSTRAP_FAST_SMOKE_VALIDATOR"
Write-Host "VALIDATION_ONLY=TRUE"
Write-Host "FULL_DAILY_OPERATOR_RUN=FALSE"
Write-Host "LONG_BOOTSTRAP_SEQUENCE_RUN=FALSE"
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
        throw "V20.7V-R2 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
