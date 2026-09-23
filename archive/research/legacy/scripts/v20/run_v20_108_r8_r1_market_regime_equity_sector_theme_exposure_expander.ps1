param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r8_r1_market_regime_equity_sector_theme_exposure_expander.py"

Write-Host "STAGE_NAME=V20.108-R8-R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "IS_OFFICIAL_RANKING=FALSE"
Write-Host "IS_OFFICIAL_WEIGHT=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.108-R8-R1 exposure expander failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER_WITH_PARTIAL_COVERAGE") -or
        ($Output -contains "BLOCKED_V20_108_R8_R1_NO_SAFE_EQUITY_EXPOSURE_SOURCE_FOUND")
    if (-not $Passed) {
        throw "V20.108-R8-R1 did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
