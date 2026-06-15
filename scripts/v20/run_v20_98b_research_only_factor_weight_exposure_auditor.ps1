param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_98b_research_only_factor_weight_exposure_auditor.py"

Write-Host "STAGE_NAME=V20.98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE_AUDITOR"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.98B auditor failed with exit code $ExitCode"
    }
    if (-not ($Output -contains "PASS_V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE_AUDITOR")) {
        throw "V20.98B auditor did not report PASS"
    }
}
catch {
    Write-Host "BLOCKED_V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE_AUDITOR"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
