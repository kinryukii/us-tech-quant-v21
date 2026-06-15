param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r4_real_candidate_factor_family_score_materializer.py"

Write-Host "STAGE_NAME=V20.108-R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER"
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
        throw "V20.108-R4 materializer failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER_WITH_PARTIAL_FAMILY_COVERAGE") -or
        ($Output -contains "BLOCKED_V20_108_R4_NO_REAL_MATERIALIZABLE_CANDIDATE_FACTOR_SCORES")
    if (-not $Passed) {
        throw "V20.108-R4 materializer did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
