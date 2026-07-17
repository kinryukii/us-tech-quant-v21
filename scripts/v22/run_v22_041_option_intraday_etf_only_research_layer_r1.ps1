param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$InputCsv = "",
    [int]$MinDte = 1,
    [int]$MaxDte = 21,
    [switch]$Allow0Dte,
    [double]$MaxSpreadPct = 0.30,
    [int]$MaxContracts = 1000,
    [int]$BatchSize = 100,
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441,
    [switch]$AllowFallbackRows
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_041_option_intraday_etf_only_research_layer_r1.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1\v22_041_summary.json"
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
    "--min-dte", $MinDte,
    "--max-dte", $MaxDte,
    "--max-spread-pct", $MaxSpreadPct,
    "--max-contracts", $MaxContracts,
    "--batch-size", $BatchSize,
    "--host", $MoomooHost,
    "--port", $Port
)
if ($Execute) {
    $ArgsList += "--execute"
}
if ($InputCsv -ne "") {
    $ArgsList += @("--input-csv", $InputCsv)
}
if ($Allow0Dte) {
    $ArgsList += "--allow-0dte"
}
if ($AllowFallbackRows) {
    $ArgsList += "--allow-fallback-rows"
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
        Write-Output "liquidity_candidate_count=$($Summary.liquidity_candidate_count)"
        Write-Output "quote_access_status=$($Summary.quote_access_status)"
        Write-Output "fallback_rows_used=$($Summary.fallback_rows_used)"
        Write-Output "real_readonly_quote_verified=$($Summary.real_readonly_quote_verified)"
        Write-Output "safe_log_dir_path=$($Summary.safe_log_dir_path)"
        Write-Output "single_stock_blocked_count=$($Summary.single_stock_blocked_count)"
        Write-Output "research_only=$($Summary.research_only)"
        Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
        Write-Output "official_adoption_allowed=$($Summary.official_adoption_allowed)"
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
