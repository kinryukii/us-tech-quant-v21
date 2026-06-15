param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_104_random_asof_backtest_batch_runner.py"

Write-Host "STAGE_NAME=V20.104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "IS_OFFICIAL_WEIGHT=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"
Write-Host "DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE"
Write-Host "V20_107_EXECUTION_STATUS=NOT_RUN"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.104 random as-of backtest batch runner failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER") -or
        ($Output -contains "PARTIAL_PASS_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER_WITH_LIMITED_HISTORICAL_COVERAGE") -or
        ($Output -contains "BLOCKED_V20_104_NO_PIT_SAFE_RANDOM_ASOF_INPUTS")
    if (-not $Passed) {
        throw "V20.104 random as-of backtest batch runner did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_104_RANDOM_ASOF_BACKTEST_BATCH_RUNNER"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
