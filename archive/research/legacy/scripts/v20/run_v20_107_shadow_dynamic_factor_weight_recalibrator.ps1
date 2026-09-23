param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_107_shadow_dynamic_factor_weight_recalibrator.py"

Write-Host "STAGE_NAME=V20.107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "IS_OFFICIAL_WEIGHT=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"
Write-Host "DYNAMIC_FACTOR_WEIGHT_CREATED=TRUE"
Write-Host "DYNAMIC_FACTOR_WEIGHT_SCOPE=RESEARCH_ONLY_SHADOW_FACTOR_FAMILY"
Write-Host "V20_107_EXECUTION_STATUS=RUN_SHADOW_ONLY"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.107 shadow dynamic factor weight recalibrator failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR") -or
        ($Output -contains "PARTIAL_PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_WITH_LIMITED_FACTOR_GRANULARITY") -or
        ($Output -contains "PARTIAL_PASS_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR_WITH_LIMITED_EVIDENCE")
    if (-not $Passed) {
        throw "V20.107 shadow dynamic factor weight recalibrator did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_107_SHADOW_DYNAMIC_FACTOR_WEIGHT_RECALIBRATOR"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
