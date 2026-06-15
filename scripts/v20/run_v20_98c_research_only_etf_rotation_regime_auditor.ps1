param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_98c_research_only_etf_rotation_regime_auditor.py"

Write-Host "STAGE_NAME=V20.98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"
Write-Host "V20_107_EXECUTION_STATUS=NOT_RUN"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.98C ETF rotation regime auditor failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR") -or
        ($Output -contains "PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR_WITH_USABLE_ETF_REGIME_EVIDENCE") -or
        ($Output -contains "PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR_WITH_PARTIAL_ETF_DATA")
    if (-not $Passed) {
        throw "V20.98C ETF rotation regime auditor did not report PASS"
    }
}
catch {
    Write-Host "BLOCKED_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
