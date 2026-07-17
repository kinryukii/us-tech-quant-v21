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
$Script = Join-Path $RepoRoot "scripts\v22\v22_041_r4_enriched_etf_option_liquidity_layer_integration.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.041_R4_ENRICHED_ETF_OPTION_LIQUIDITY_LAYER_INTEGRATION"
$SummaryPath = Join-Path $OutputDir "v22_041_r4_summary.json"
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
        foreach ($Key in @(
            "final_status", "final_decision", "v22_041_final_status", "v22_041_final_decision",
            "total_raw_contract_count", "total_dte_eligible_count", "enrichment_target_count",
            "enrichment_success_count", "bid_field_mapped", "ask_field_mapped", "volume_field_mapped",
            "valid_bid_ask_count", "spread_pass_count", "volume_positive_count",
            "liquidity_candidate_count", "fallback_rows_used", "real_readonly_quote_verified",
            "broker_action_allowed", "official_adoption_allowed"
        )) {
            Write-Output "$Key=$($Summary.$Key)"
        }
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
