param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [int]$LookbackMinutes = 240,
    [bool]$UseV22041Latest = $true,
    [bool]$RequireQQQConfirmation = $true,
    [bool]$RequireSPYConfirmation = $false,
    [Alias("Host")]
    [string]$MoomooHost = "127.0.0.1",
    [int]$Port = 18441
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_042_option_intraday_etf_direction_gate_r1.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.042_OPTION_INTRADAY_ETF_DIRECTION_GATE_R1\v22_042_summary.json"
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
    "--lookback-minutes", $LookbackMinutes,
    "--host", $MoomooHost,
    "--port", $Port
)
if ($Execute) {
    $ArgsList += "--execute"
}
if (-not $UseV22041Latest) {
    $ArgsList += "--no-use-v22-041-latest"
}
if (-not $RequireQQQConfirmation) {
    $ArgsList += "--no-require-qqq-confirmation"
}
if ($RequireSPYConfirmation) {
    $ArgsList += "--require-spy-confirmation"
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
            "final_status", "final_decision", "v22_041_liquidity_candidate_count",
            "intraday_data_available", "soxx_direction_label", "qqq_confirmation_label",
            "spy_confirmation_label", "final_direction_label", "promoted_candidate_count",
            "wait_state", "broker_action_allowed", "official_adoption_allowed"
        )) {
            Write-Output "$Key=$($Summary.$Key)"
        }
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

exit $PythonExit
