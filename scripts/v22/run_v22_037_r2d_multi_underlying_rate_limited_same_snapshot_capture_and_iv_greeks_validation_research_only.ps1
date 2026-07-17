[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$RunTests,
    [switch]$CaptureOnly,
    [string]$RepoRoot = "",
    [string]$Underlyings = "QQQ",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 18441,
    [int]$MinDte = 0,
    [int]$MaxDte = 14,
    [int]$MaxContractsPerUnderlying = 399,
    [int]$SnapshotOptionBatchSize = 399,
    [double]$MaxAlignmentSeconds = 15.0,
    [double]$MinAlignmentPassRatio = 0.80,
    [double]$RiskFreeRate = 0.043,
    [double]$DividendYield = 0.0,
    [double]$MaxSpreadRatio = 0.50,
    [double]$ChildPassIvCoverageRatio = 0.80,
    [double]$ChildPassRankingEligibleRatio = 0.20,
    [int]$OptionChainRateLimitCalls = 9,
    [double]$OptionChainRateLimitWindowSeconds = 30.0,
    [int]$OptionChainMaxAttempts = 2,
    [double]$OptionChainRetrySeconds = 31.0
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

$MainScript = Join-Path $RepoRoot "scripts\v22\v22_037_r2d_multi_underlying_rate_limited_same_snapshot_capture_and_iv_greeks_validation_research_only.py"
$TestScript = Join-Path $RepoRoot "scripts\v22\test_v22_037_r2d_multi_underlying_rate_limited_same_snapshot_capture_and_iv_greeks_validation_research_only.py"
$R2BChild = Join-Path $RepoRoot "scripts\v22\v22_037_r2b_synthetic_iv_greeks_timestamp_provenance_repair_and_quality_validation_research_only.py"
$OutputRoot = Join-Path $RepoRoot "outputs\v22\V22.037_R2D_MULTI_UNDERLYING_RATE_LIMITED_SAME_SNAPSHOT_CAPTURE_AND_IV_GREEKS_VALIDATION_RESEARCH_ONLY"

if (-not (Test-Path $MainScript)) {
    throw "Main script not found: $MainScript"
}
if (-not $CaptureOnly -and -not (Test-Path $R2BChild)) {
    throw "Required V22.037 R2B child script not found: $R2BChild"
}

$LocalTemp = Join-Path $RepoRoot ".tmp\v22_037_r2d"
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
        throw "V22.037 R2D tests failed with exit code $LASTEXITCODE"
    }
}

if (-not $Execute) {
    Write-Host "Dry guard only. Add -Execute to run the read-only multi-underlying capture." -ForegroundColor Yellow
    Write-Host "No broker action is implemented or allowed." -ForegroundColor Yellow
    exit 0
}

$Arguments = @(
    $MainScript,
    "--repo-root", $RepoRoot,
    "--output-dir", $OutputRoot,
    "--underlyings", $Underlyings,
    "--host", $HostAddress,
    "--port", $Port,
    "--min-dte", $MinDte,
    "--max-dte", $MaxDte,
    "--max-contracts-per-underlying", $MaxContractsPerUnderlying,
    "--snapshot-option-batch-size", $SnapshotOptionBatchSize,
    "--max-alignment-seconds", $MaxAlignmentSeconds,
    "--min-alignment-pass-ratio", $MinAlignmentPassRatio,
    "--risk-free-rate", $RiskFreeRate,
    "--dividend-yield", $DividendYield,
    "--max-spread-ratio", $MaxSpreadRatio,
    "--child-pass-iv-coverage-ratio", $ChildPassIvCoverageRatio,
    "--child-pass-ranking-eligible-ratio", $ChildPassRankingEligibleRatio,
    "--option-chain-rate-limit-calls", $OptionChainRateLimitCalls,
    "--option-chain-rate-limit-window-seconds", $OptionChainRateLimitWindowSeconds,
    "--option-chain-max-attempts", $OptionChainMaxAttempts,
    "--option-chain-retry-seconds", $OptionChainRetrySeconds,
    "--execute"
)
if ($CaptureOnly) {
    $Arguments += "--capture-only"
}

& $Python @Arguments
$ExitCode = $LASTEXITCODE

$LatestPointer = Join-Path $OutputRoot "latest_run.json"
if (Test-Path $LatestPointer) {
    $Pointer = Get-Content $LatestPointer -Raw | ConvertFrom-Json
    $SummaryPath = [string]$Pointer.summary_path
    if (Test-Path $SummaryPath) {
        $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
        Write-Host ""
        Write-Host "=== V22.037 R2D STATUS ===" -ForegroundColor Cyan
        $Summary | Select-Object `
            final_status,
            final_decision,
            run_id,
            underlyings_requested,
            underlying_count,
            underlying_success_count,
            underlying_failure_count,
            expiration_count,
            option_chain_request_count,
            rate_limit_retry_count,
            option_chain_static_row_count,
            selected_contract_count,
            snapshot_batch_count,
            captured_option_row_count,
            same_snapshot_request_count,
            explicit_option_quote_timestamp_count,
            explicit_underlying_quote_timestamp_count,
            timestamp_alignment_pass_count,
            timestamp_alignment_pass_ratio,
            regular_session_clock_pass,
            iv_child_final_status,
            synthetic_iv_solved_count,
            synthetic_iv_coverage_ratio,
            greeks_valid_count,
            research_ranking_eligible_count,
            research_ranking_eligible_ratio,
            quality_tier_a_count,
            quality_tier_b_count,
            quality_tier_c_count,
            quality_rejected_count,
            research_only,
            official_adoption_allowed,
            broker_action_allowed,
            error_message |
            Format-List
        Write-Host "summary_path=$SummaryPath" -ForegroundColor Green
        Write-Host "underlying_audit_path=$($Summary.underlying_audit_path)" -ForegroundColor Green
    } else {
        Write-Warning "Latest summary was not created: $SummaryPath"
    }
} else {
    Write-Warning "Latest-run pointer was not created: $LatestPointer"
}

exit $ExitCode
