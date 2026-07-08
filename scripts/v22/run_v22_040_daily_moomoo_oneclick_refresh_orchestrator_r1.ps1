param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$TargetDate = "",
    [string]$CacheRoot = "",
    [switch]$NoNetwork
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Script = Join-Path $RepoRoot "scripts\v22\v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SummaryPath = Join-Path $RepoRoot "outputs\v22\V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1\v22_040_summary.json"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

if (-not $Execute) {
    Write-Output "V22.040 wrapper dry run. Re-run with -Execute to run the daily Moomoo one-click refresh orchestrator."
    Write-Output "final_summary_path=$SummaryPath"
    Write-Output "summary_exists=$(Test-Path $SummaryPath)"
    Write-Output "broker_action_allowed=False"
    Write-Output "official_adoption_allowed=False"
    exit 0
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($TargetDate -ne "") {
    $ArgsList += @("--target-date", $TargetDate)
}
if ($CacheRoot -ne "") {
    $ArgsList += @("--cache-root", $CacheRoot)
}
if ($NoNetwork) {
    $ArgsList += "--no-network"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

$SummaryExists = Test-Path $SummaryPath
Write-Output "final_summary_path=$SummaryPath"
Write-Output "summary_exists=$SummaryExists"
if ($SummaryExists) {
    try {
        $Summary = Get-Content -Raw -Path $SummaryPath | ConvertFrom-Json
        Write-Output "final_status=$($Summary.final_status)"
        Write-Output "final_decision=$($Summary.final_decision)"
    } catch {
        Write-Output "final_status=UNREADABLE_SUMMARY"
        Write-Output "final_decision=UNREADABLE_SUMMARY"
    }
}

Write-Output "broker_action_allowed=False"
Write-Output "official_adoption_allowed=False"
exit $PythonExit
