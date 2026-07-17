param(
    [switch]$Execute,
    [switch]$StorageValidationOnly,
    [switch]$DailyPathReplayOnly,
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1")
$Storage = Get-UstqStoragePaths -RepoRoot $RepoRoot
if ($StorageValidationOnly) {
    foreach($root in @($Storage.data_root,$Storage.cache_root,$Storage.daily_root,$Storage.backtest_root,$Storage.results_root,$Storage.envs_root)){if(-not(Test-Path -LiteralPath $root)){throw "MISSING_EXTERNAL_ROOT:$root"}}
    if(-not(Test-Path -LiteralPath $Storage.python_exe)){throw "MISSING_EXTERNAL_PYTHON:$($Storage.python_exe)"}
    foreach($required in @((Join-Path $RepoRoot "scripts\v22\run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1"))){if(-not(Test-Path -LiteralPath $required)){throw "MISSING_REQUIRED_PATH:$required"}}
    $probe=Join-Path $Storage.daily_root (".storage_probe_"+[guid]::NewGuid().ToString()+".tmp"); [IO.File]::WriteAllText($probe,"probe"); Remove-Item -LiteralPath $probe -Force
    Write-Output "final_status=PASS_V22_044_STORAGE_PATH_VALIDATION"; Write-Output "broker_action_allowed=False"; Write-Output "official_adoption_allowed=False"; exit 0
}
if ($DailyPathReplayOnly) {
    $env:USTQ_OFFLINE='1';$env:USTQ_BROKER_DISABLED='1';$env:USTQ_NO_PROMOTION='1';$env:USTQ_NO_CANONICAL_WRITE='1';$env:USTQ_PATH_REPLAY='1'
    & (Join-Path $RepoRoot 'scripts\v22\run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1') -RepoRoot $RepoRoot -PathReplay -NoNetwork
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}; Write-Output 'final_status=PASS_V22_044_DAILY_PATH_REPLAY';exit 0
}
$Script = Join-Path $RepoRoot "scripts\v22\v22_044_daily_single_entrypoint_freeze_and_guard_r1.py"
$Python = $Storage.python_exe
$SummaryPath = Join-Path $Storage.daily_root "current\V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1\v22_044_summary.json"

if (-not (Test-Path $Python)) { throw "MISSING_EXTERNAL_PYTHON:$Python" }

$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($Execute) {
    $ArgsList += "--execute"
}

Set-Location $RepoRoot
& $Python @ArgsList
$PythonExit = $LASTEXITCODE

Write-Output "final_summary_path=$SummaryPath"
Write-Output "summary_exists=$(Test-Path $SummaryPath)"
exit $PythonExit
