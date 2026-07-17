param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_041_r1a_etf_option_moomoo_readonly_quote_and_log_permission_repair.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $RepoRoot "outputs\v22\V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"
$SummaryPath = Join-Path $OutputDir "v22_041_r1a_summary.json"
$SafeLogDir = Join-Path $OutputDir "provider_logs"
$SafeEnvRoot = Join-Path $OutputDir "provider_env"
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
    "--port", $Port
)
if ($Execute) {
    $ArgsList += "--execute"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

Write-Output "final_summary_path=$SummaryPath"
Write-Output "safe_log_dir_path=$SafeLogDir"
$SummaryExists = Test-Path $SummaryPath
Write-Output "summary_exists=$SummaryExists"
if ($SummaryExists) {
    try {
        $Summary = Get-Content -Raw -Path $SummaryPath | ConvertFrom-Json
        Write-Output "final_status=$($Summary.final_status)"
        Write-Output "final_decision=$($Summary.final_decision)"
        Write-Output "quote_access_status=$($Summary.quote_access_status)"
        Write-Output "real_readonly_quote_verified=$($Summary.real_readonly_quote_verified)"
        Write-Output "fallback_rows_used=$($Summary.fallback_rows_used)"
        Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
        Write-Output "official_adoption_allowed=$($Summary.official_adoption_allowed)"
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
