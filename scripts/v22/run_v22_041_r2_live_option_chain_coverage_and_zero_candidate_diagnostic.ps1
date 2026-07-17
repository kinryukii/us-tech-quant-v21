param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441,
    [int]$MinDte = 1,
    [int]$MaxDte = 21,
    [double]$MaxSpreadPct = 0.30,
    [double]$RelaxedMaxSpreadPct = 1.00
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_041_r2_live_option_chain_coverage_and_zero_candidate_diagnostic.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.041_R2_LIVE_OPTION_CHAIN_COVERAGE_AND_ZERO_CANDIDATE_DIAGNOSTIC"
$SummaryPath = Join-Path $OutputDir "v22_041_r2_summary.json"
$SafeOutputDir = Join-Path $RepoRoot "outputs\v22\V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"
$SafeLogDir = Join-Path $SafeOutputDir "provider_logs"
$SafeEnvRoot = Join-Path $SafeOutputDir "provider_env"
$SafeUserProfile = Join-Path $SafeEnvRoot "userprofile"
$SafeAppData = Join-Path $SafeEnvRoot "AppData\Roaming"
$SafeLocalAppData = Join-Path $SafeEnvRoot "AppData\Local"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

New-Item -ItemType Directory -Force -Path $SafeLogDir, $SafeUserProfile, $SafeAppData, $SafeLocalAppData | Out-Null
$env:FUTU_OPEND_LOG_DIR = $SafeLogDir
$env:MOOMOO_LOG_DIR = $SafeLogDir
$env:FUTU_LOG_DIR = $SafeLogDir
$env:FutuOpenD_LogDir = $SafeLogDir
$env:TMP = $SafeLogDir
$env:TEMP = $SafeLogDir
$env:USERPROFILE = $SafeUserProfile
$env:APPDATA = $SafeAppData
$env:LOCALAPPDATA = $SafeLocalAppData

$ArgsList = @(
    $Script,
    "--repo-root", $RepoRoot,
    "--host", $MoomooHost,
    "--port", $Port,
    "--min-dte", $MinDte,
    "--max-dte", $MaxDte,
    "--max-spread-pct", $MaxSpreadPct,
    "--relaxed-max-spread-pct", $RelaxedMaxSpreadPct
)
if ($Execute) {
    $ArgsList += "--execute"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

Write-Output "final_summary_path=$SummaryPath"
$SummaryExists = Test-Path $SummaryPath
Write-Output "summary_exists=$SummaryExists"
if ($SummaryExists) {
    try {
        $Summary = Get-Content -Raw -Path $SummaryPath | ConvertFrom-Json
        Write-Output "final_status=$($Summary.final_status)"
        Write-Output "final_decision=$($Summary.final_decision)"
        Write-Output "total_raw_contract_count=$($Summary.total_raw_contract_count)"
        Write-Output "total_dte_eligible_count=$($Summary.total_dte_eligible_count)"
        Write-Output "total_valid_bid_count=$($Summary.total_valid_bid_count)"
        Write-Output "total_valid_ask_gt_bid_count=$($Summary.total_valid_ask_gt_bid_count)"
        Write-Output "total_finite_spread_pct_count=$($Summary.total_finite_spread_pct_count)"
        Write-Output "total_spread_pass_count=$($Summary.total_spread_pass_count)"
        Write-Output "total_volume_positive_count=$($Summary.total_volume_positive_count)"
        Write-Output "liquidity_candidate_count=$($Summary.liquidity_candidate_count)"
        Write-Output "zero_candidate_root_cause_primary=$($Summary.zero_candidate_root_cause_primary)"
        Write-Output "field_mapping_issue_detected=$($Summary.field_mapping_issue_detected)"
        Write-Output "missing_volume_field_all_rows=$($Summary.missing_volume_field_all_rows)"
        Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
        Write-Output "official_adoption_allowed=$($Summary.official_adoption_allowed)"
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
