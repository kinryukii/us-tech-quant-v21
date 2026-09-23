param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_98c_r2_controlled_etf_price_refresh_and_cache_certification.py"

Write-Host "STAGE_NAME=V20.98C-R2_CONTROLLED_ETF_PRICE_REFRESH_AND_CACHE_CERTIFICATION"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"
Write-Host "DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE"
Write-Host "V20_107_EXECUTION_STATUS=NOT_RUN"

Push-Location $RepoRoot
try {
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $ErrorActionPreference = $PreviousErrorActionPreference
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.98C-R2 controlled ETF price refresh failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CERTIFIED") -or
        ($Output -contains "PARTIAL_PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_WITH_MISSING_DATA")
    if (-not $Passed) {
        throw "V20.98C-R2 controlled ETF price refresh did not report accepted status"
    }
}
catch {
    $ErrorActionPreference = "Stop"
    Write-Host "BLOCKED_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_AND_CACHE_CERTIFICATION"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
