param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_49_operator_review_acceptance_gate.py"

Write-Host "STAGE_NAME=V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
Write-Host "OPERATOR_REVIEW_GATE=TRUE"
Write-Host "REPORT_REVIEW_ONLY=TRUE"
Write-Host "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_49=FALSE"
Write-Host "YFINANCE_IMPORT_USED_IN_V20_49=FALSE"
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
        throw "V20.49 stage failed with exit code $LASTEXITCODE"
    }
    $SummaryPath = Join-Path $RepoRoot "outputs\v20\consolidation\V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
    $status = "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
    if (Test-Path $SummaryPath) {
        $summary = Import-Csv $SummaryPath | Select-Object -First 1
        if ($summary -and $summary.research_only_gate_status -eq "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" -and $summary.official_promotion_gate_status -ne "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE") {
            $status = "WARN_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"
        }
    }
    Write-Host "FINAL_STATUS=$status"
}
finally {
    Pop-Location
}
