param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r3_candidate_factor_family_score_materialization_plan.py"

Write-Host "STAGE_NAME=V20.108-R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN"
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
        throw "V20.108-R3 materialization plan failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_CREATED") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_WITH_BLOCKERS") -or
        ($Output -contains "BLOCKED_V20_108_R3_NO_SAFE_MATERIALIZATION_PATHS_FOUND")
    if (-not $Passed) {
        throw "V20.108-R3 materialization plan did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
