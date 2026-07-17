[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$RunTests,
    [string]$RepoRoot = "",
    [string]$R2DRunDir = "",
    [double]$MinDte = 0.0,
    [double]$MaxDte = 45.0,
    [double]$MaxAbsLogMoneyness = 0.08,
    [double]$MaxSpreadRatio = 0.15,
    [double]$MaxSpreadAbsolute = 0.50,
    [double]$MinOptionMarketPrice = 0.10,
    [double]$MinBid = 0.05,
    [double]$MinAbsDelta = 0.15,
    [double]$MaxAbsDelta = 0.85,
    [double]$MinVolume = 1.0,
    [double]$MinOpenInterest = 10.0,
    [switch]$RequireActivity,
    [int]$TopNPerUnderlying = 20
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

$MainScript = Join-Path $RepoRoot "scripts\v22\v22_037_r2e_iv_greeks_eligibility_attribution_and_liquid_contract_panel_research_only.py"
$TestScript = Join-Path $RepoRoot "scripts\v22\test_v22_037_r2e_iv_greeks_eligibility_attribution_and_liquid_contract_panel_research_only.py"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.037_R2E_IV_GREEKS_ELIGIBILITY_ATTRIBUTION_AND_LIQUID_CONTRACT_PANEL_RESEARCH_ONLY"

if (-not (Test-Path $MainScript)) {
    throw "Main script not found: $MainScript"
}

$LocalTemp = Join-Path $RepoRoot ".tmp\v22_037_r2e"
New-Item -ItemType Directory -Force -Path $LocalTemp | Out-Null
$env:TEMP = $LocalTemp
$env:TMP = $LocalTemp
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

if ($RunTests) {
    if (-not (Test-Path $TestScript)) {
        throw "Test script not found: $TestScript"
    }
    & $Python -m pytest $TestScript -q -p no:cacheprovider --basetemp (Join-Path $LocalTemp "pytest")
    if ($LASTEXITCODE -ne 0) {
        throw "V22.037 R2E tests failed with exit code $LASTEXITCODE"
    }
}

if (-not $Execute) {
    Write-Host "Dry guard only. Add -Execute to build the research-only eligibility attribution and liquid contract panel." -ForegroundColor Yellow
    Write-Host "No broker action is implemented or allowed." -ForegroundColor Yellow
    exit 0
}

$Arguments = @(
    $MainScript,
    "--repo-root", $RepoRoot,
    "--output-dir", $OutputDir,
    "--min-dte", $MinDte,
    "--max-dte", $MaxDte,
    "--max-abs-log-moneyness", $MaxAbsLogMoneyness,
    "--max-spread-ratio", $MaxSpreadRatio,
    "--max-spread-absolute", $MaxSpreadAbsolute,
    "--min-option-market-price", $MinOptionMarketPrice,
    "--min-bid", $MinBid,
    "--min-abs-delta", $MinAbsDelta,
    "--max-abs-delta", $MaxAbsDelta,
    "--min-volume", $MinVolume,
    "--min-open-interest", $MinOpenInterest,
    "--top-n-per-underlying", $TopNPerUnderlying,
    "--execute"
)
if (-not [string]::IsNullOrWhiteSpace($R2DRunDir)) {
    $Arguments += @("--r2d-run-dir", $R2DRunDir)
}
if ($RequireActivity) {
    $Arguments += "--require-activity"
}

& $Python @Arguments
$ExitCode = $LASTEXITCODE

$SummaryPath = Join-Path $OutputDir "v22_037_r2e_summary.json"
if (Test-Path $SummaryPath) {
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "=== V22.037 R2E STATUS ===" -ForegroundColor Cyan
    $Summary | Select-Object `
        final_status,
        final_decision,
        source_r2d_run_dir,
        input_row_count,
        underlying_count,
        underlyings,
        timestamp_alignment_pass_count,
        timestamp_alignment_pass_ratio,
        base_research_eligible_count,
        base_research_eligible_ratio,
        zero_dte_base_eligible_count,
        zero_dte_base_eligible_ratio,
        nonzero_dte_base_eligible_count,
        liquid_panel_count,
        liquid_panel_ratio,
        liquid_panel_conversion_ratio_from_base_eligible,
        liquid_panel_zero_dte_count,
        liquid_panel_zero_dte_ratio,
        underlying_with_liquid_panel_count,
        underlyings_with_liquid_panel,
        topn_panel_count,
        quality_tier_a_count,
        quality_tier_b_count,
        quality_tier_c_count,
        quality_rejected_count,
        activity_data_available_count,
        activity_data_partial_count,
        activity_data_missing_count,
        research_only,
        official_adoption_allowed,
        broker_action_allowed,
        error_message |
        Format-List
    Write-Host "summary_path=$SummaryPath" -ForegroundColor Green
    Write-Host "liquid_panel_path=$($Summary.output_files.liquid_panel)" -ForegroundColor Green
    Write-Host "topn_panel_path=$($Summary.output_files.topn_panel)" -ForegroundColor Green
    Write-Host "attribution_path=$($Summary.output_files.attribution)" -ForegroundColor Green
} else {
    Write-Warning "R2E summary was not created: $SummaryPath"
}

exit $ExitCode
