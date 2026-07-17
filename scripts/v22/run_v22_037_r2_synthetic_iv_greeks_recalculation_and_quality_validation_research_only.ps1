[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$RunTests,
    [string]$RepoRoot = "",
    [string]$InputPath = "",
    [double]$RiskFreeRate = 0.043,
    [double]$DividendYield = 0.0,
    [double]$MaxSpreadRatio = 0.50,
    [double]$MaxAlignmentSeconds = 900.0,
    [double]$PassIvCoverageRatio = 0.80,
    [double]$PassRankingEligibleRatio = 0.60,
    [string]$ValuationTimeEt = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$MainScript = Join-Path $RepoRoot "scripts\v22\v22_037_r2_synthetic_iv_greeks_recalculation_and_quality_validation_research_only.py"
$TestScript = Join-Path $RepoRoot "scripts\v22\test_v22_037_r2_synthetic_iv_greeks_recalculation_and_quality_validation_research_only.py"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.037_R2_SYNTHETIC_IV_GREEKS_RECALCULATION_AND_QUALITY_VALIDATION_RESEARCH_ONLY"

if (-not (Test-Path $MainScript)) {
    throw "Main script not found: $MainScript"
}

# Use a repo-local temp directory to avoid Windows Temp ACL failures observed in prior pytest runs.
$LocalTemp = Join-Path $RepoRoot ".tmp\v22_037_r2"
New-Item -ItemType Directory -Force -Path $LocalTemp | Out-Null
$env:TEMP = $LocalTemp
$env:TMP = $LocalTemp
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

if ($RunTests) {
    if (-not (Test-Path $TestScript)) {
        throw "Test script not found: $TestScript"
    }
    & $Python -m pytest $TestScript -q --basetemp (Join-Path $LocalTemp "pytest")
    if ($LASTEXITCODE -ne 0) {
        throw "V22.037 R2 tests failed with exit code $LASTEXITCODE"
    }
}

if (-not $Execute) {
    Write-Host "Dry guard only. Add -Execute to run the research-only recalculation." -ForegroundColor Yellow
    Write-Host "No broker action is implemented or allowed." -ForegroundColor Yellow
    exit 0
}

$Arguments = @(
    $MainScript,
    "--repo-root", $RepoRoot,
    "--output-dir", $OutputDir,
    "--risk-free-rate", $RiskFreeRate,
    "--dividend-yield", $DividendYield,
    "--max-spread-ratio", $MaxSpreadRatio,
    "--max-alignment-seconds", $MaxAlignmentSeconds,
    "--pass-iv-coverage-ratio", $PassIvCoverageRatio,
    "--pass-ranking-eligible-ratio", $PassRankingEligibleRatio,
    "--execute"
)
if (-not [string]::IsNullOrWhiteSpace($InputPath)) {
    $Arguments += @("--input", $InputPath)
}
if (-not [string]::IsNullOrWhiteSpace($ValuationTimeEt)) {
    $Arguments += @("--valuation-time-et", $ValuationTimeEt)
}

& $Python @Arguments
$ExitCode = $LASTEXITCODE

$SummaryPath = Join-Path $OutputDir "v22_037_r2_summary.json"
if (Test-Path $SummaryPath) {
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "=== V22.037 R2 STATUS ===" -ForegroundColor Cyan
    $Summary | Select-Object `
        final_status,
        final_decision,
        source_input_path,
        input_row_count,
        underlying_price_valid_count,
        synthetic_iv_solved_count,
        synthetic_iv_coverage_ratio,
        greeks_valid_count,
        research_ranking_eligible_count,
        research_ranking_eligible_ratio,
        quality_tier_a_count,
        quality_tier_b_count,
        quality_tier_c_count,
        quality_rejected_count,
        put_call_parity_pair_count,
        validation_error_failure_count,
        validation_warning_failure_count,
        research_only,
        official_adoption_allowed,
        broker_action_allowed |
        Format-List
    Write-Host "summary_path=$SummaryPath" -ForegroundColor Green
} else {
    Write-Warning "Summary was not created: $SummaryPath"
}

exit $ExitCode
