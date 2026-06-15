param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_88_certified_benchmark_comparison_evidence_export.py"

Write-Host "STAGE_NAME=V20.88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATED=FALSE"
Write-Host "PORTFOLIO_MUTATION_CREATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    $Allowed = @(
        "PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE",
        "PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE",
        "BLOCKED_V20_88_MISSING_REQUIRED_UPSTREAM_EVIDENCE",
        "BLOCKED_V20_88_UNSAFE_UPSTREAM_GUARDRAIL"
    )
    $DetectedStatus = ($Output | Where-Object { $Allowed -contains $_ } | Select-Object -Last 1)
    if (-not $DetectedStatus) {
        throw "V20.88 did not report an allowed final status"
    }
    if ($ExitCode -ne 0 -and $DetectedStatus -like "PASS_*") {
        throw "V20.88 reported pass status with non-zero exit code $ExitCode"
    }
    Write-Host $DetectedStatus
    if ($DetectedStatus -like "BLOCKED_*") {
        exit 1
    }
}
catch {
    Write-Host "BLOCKED_V20_88_MISSING_REQUIRED_UPSTREAM_EVIDENCE"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
