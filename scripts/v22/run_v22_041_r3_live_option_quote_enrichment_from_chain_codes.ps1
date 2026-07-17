param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441,
    [int]$MaxContracts = 1000,
    [int]$BatchSize = 100,
    [double]$MaxSpreadPct = 0.30,
    [switch]$IncludeZeroDte
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_041_r3_live_option_quote_enrichment_from_chain_codes.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.041_R3_LIVE_OPTION_QUOTE_ENRICHMENT_FROM_CHAIN_CODES"
$SummaryPath = Join-Path $OutputDir "v22_041_r3_summary.json"
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
    "--max-contracts", $MaxContracts,
    "--batch-size", $BatchSize,
    "--max-spread-pct", $MaxSpreadPct
)
if ($Execute) {
    $ArgsList += "--execute"
}
if ($IncludeZeroDte) {
    $ArgsList += "--include-zero-dte"
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
        Write-Output "enrichment_target_count=$($Summary.enrichment_target_count)"
        Write-Output "enrichment_success_count=$($Summary.enrichment_success_count)"
        Write-Output "bid_field_mapped=$($Summary.bid_field_mapped)"
        Write-Output "ask_field_mapped=$($Summary.ask_field_mapped)"
        Write-Output "volume_field_mapped=$($Summary.volume_field_mapped)"
        Write-Output "valid_bid_ask_count=$($Summary.valid_bid_ask_count)"
        Write-Output "finite_spread_pct_count=$($Summary.finite_spread_pct_count)"
        Write-Output "spread_pass_count=$($Summary.spread_pass_count)"
        Write-Output "volume_positive_count=$($Summary.volume_positive_count)"
        Write-Output "liquidity_candidate_count=$($Summary.liquidity_candidate_count)"
        Write-Output "quote_enrichment_root_cause_if_zero=$($Summary.quote_enrichment_root_cause_if_zero)"
        Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
        Write-Output "official_adoption_allowed=$($Summary.official_adoption_allowed)"
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
