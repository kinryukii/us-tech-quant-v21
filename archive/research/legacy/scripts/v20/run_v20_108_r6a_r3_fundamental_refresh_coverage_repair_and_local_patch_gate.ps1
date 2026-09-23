param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r6a_r3_fundamental_refresh_coverage_repair_and_local_patch_gate.py"

Write-Host "STAGE_NAME=V20.108-R6A-R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AND_LOCAL_PATCH_GATE"
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
        throw "V20.108-R6A-R3 coverage repair and local patch gate failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_GATE") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R6A_R3_WAITING_FOR_LOCAL_PATCH") -or
        ($Output -contains "PASS_V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE_APPROVED") -or
        ($Output -contains "BLOCKED_V20_108_R6A_R3_INSUFFICIENT_CERTIFIED_FUNDAMENTAL_COVERAGE")
    if (-not $Passed) {
        throw "V20.108-R6A-R3 did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AND_LOCAL_PATCH_GATE"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
