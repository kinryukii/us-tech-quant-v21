[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$RunTests,
    [string]$RepoRoot = "",
    [string]$R2EOutputDir = "",
    [string]$DirectionSummaryPath = "",
    [double]$MaxDirectionPanelGapMinutes = 180.0,
    [double]$MaxPanelAgeMinutes = 30.0,
    [double]$MinTimeToExpiryMinutes = 15.0,
    [int]$TopNPerUnderlyingBucket = 3
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

$MainScript = Join-Path $RepoRoot "scripts\v22\v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py"
$TestScript = Join-Path $RepoRoot "scripts\v22\test_v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.037_R2F_DIRECTION_AWARE_LIQUID_OPTION_CONTRACT_RANKING_AND_NO_TRADE_GATE_RESEARCH_ONLY"

if (-not (Test-Path $MainScript)) {
    throw "Main script not found: $MainScript"
}

$LocalTemp = Join-Path $RepoRoot ".tmp\v22_037_r2f"
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
        throw "V22.037 R2F tests failed with exit code $LASTEXITCODE"
    }
}

if (-not $Execute) {
    Write-Host "Dry guard only. Add -Execute to build the research-only direction-aware ranking and no-trade audit." -ForegroundColor Yellow
    Write-Host "No broker action is implemented or allowed." -ForegroundColor Yellow
    exit 0
}

$Arguments = @(
    $MainScript,
    "--repo-root", $RepoRoot,
    "--output-dir", $OutputDir,
    "--max-direction-panel-gap-minutes", $MaxDirectionPanelGapMinutes,
    "--max-panel-age-minutes", $MaxPanelAgeMinutes,
    "--min-time-to-expiry-minutes", $MinTimeToExpiryMinutes,
    "--top-n-per-underlying-bucket", $TopNPerUnderlyingBucket,
    "--execute"
)
if (-not [string]::IsNullOrWhiteSpace($R2EOutputDir)) {
    $Arguments += @("--r2e-output-dir", $R2EOutputDir)
}
if (-not [string]::IsNullOrWhiteSpace($DirectionSummaryPath)) {
    $Arguments += @("--direction-summary-path", $DirectionSummaryPath)
}

& $Python @Arguments
$ExitCode = $LASTEXITCODE

$SummaryPath = Join-Path $OutputDir "v22_037_r2f_summary.json"
if (Test-Path $SummaryPath) {
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "=== V22.037 R2F STATUS ===" -ForegroundColor Cyan
    $Summary | Select-Object `
        final_status,
        final_decision,
        source_r2e_output_dir,
        source_direction_summary_path,
        panel_row_count,
        underlying_count,
        underlyings,
        direction_gate_mode_count,
        panel_reference_time_utc,
        panel_age_minutes,
        panel_fresh,
        direction_source_time_utc,
        direction_panel_time_gap_minutes,
        direction_source_fresh,
        strict_official_wait_state,
        strict_official_direction_label,
        primary_wait_reason_code,
        secondary_wait_reason_code,
        shadow_direction_label,
        direction_compatible_ranking_row_count,
        selected_contract_count,
        strict_official_selected_contract_count,
        shadow_selected_contract_count,
        no_trade_audit_row_count,
        no_trade_active_count,
        research_only,
        official_adoption_allowed,
        broker_action_allowed,
        error_message |
        Format-List
    Write-Host "summary_path=$SummaryPath" -ForegroundColor Green
    if ($Summary.output_files) {
        Write-Host "ranking_path=$($Summary.output_files.ranking)" -ForegroundColor Green
        Write-Host "top_contract_path=$($Summary.output_files.top_contract)" -ForegroundColor Green
        Write-Host "no_trade_audit_path=$($Summary.output_files.no_trade_audit)" -ForegroundColor Green
        Write-Host "direction_provenance_path=$($Summary.output_files.direction_provenance)" -ForegroundColor Green
    }
} else {
    Write-Warning "R2F summary was not created: $SummaryPath"
}

exit $ExitCode
