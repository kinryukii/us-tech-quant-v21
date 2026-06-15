param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_98b_r3_research_only_base_weight_operator_acceptance_gate.py"

Write-Host "STAGE_NAME=V20.98B-R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
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
        throw "V20.98B-R3 acceptance gate failed with exit code $ExitCode"
    }
    if (-not ($Output -contains "PASS_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE")) {
        throw "V20.98B-R3 acceptance gate did not report PASS"
    }
}
catch {
    Write-Host "BLOCKED_V20_98B_R3_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_ACCEPTANCE_GATE"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
