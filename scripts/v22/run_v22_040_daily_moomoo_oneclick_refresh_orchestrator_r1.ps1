param(
    [switch]$Execute,
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$TargetDate = "",
    [string]$CacheRoot = "",
    [switch]$NoNetwork,
    [switch]$PathReplay
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$ModuleRepo = if(Test-Path (Join-Path $RepoRoot "scripts\common\storage_paths.ps1")){$RepoRoot}else{(Resolve-Path (Join-Path $PSScriptRoot "..\.."))}
. (Join-Path $ModuleRepo "scripts\common\storage_paths.ps1")
$Storage=Get-UstqStoragePaths -RepoRoot $ModuleRepo
$Script = Join-Path $RepoRoot "scripts\v22\v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py"
$Python = $Storage.python_exe
$SummaryPath = Join-Path $Storage.daily_root "current\V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1\v22_040_summary.json"

if (-not (Test-Path $Python)) { throw "MISSING_EXTERNAL_PYTHON:$Python" }

if (-not $Execute -and -not $PathReplay) {
    Write-Output "V22.040 wrapper dry run. Re-run with -Execute to run the daily Moomoo one-click refresh orchestrator."
    Write-Output "final_summary_path=$SummaryPath"
    Write-Output "summary_exists=$(Test-Path $SummaryPath)"
    Write-Output "broker_action_allowed=False"
    Write-Output "official_adoption_allowed=False"
    exit 0
}

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($PathReplay) { $ArgsList += "--path-replay" }
if ($TargetDate -ne "") {
    $ArgsList += @("--target-date", $TargetDate)
}
if ($CacheRoot -ne "") {
    $ArgsList += @("--cache-root", $CacheRoot)
}
if ($NoNetwork) {
    $ArgsList += "--no-network"
}
if ($env:USTQ_DAILY_RUN_ID) { $ArgsList += @("--run-id", $env:USTQ_DAILY_RUN_ID) }

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
