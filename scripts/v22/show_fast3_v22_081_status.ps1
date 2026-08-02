[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$StageRoot = "D:\us-tech-quant-results\fast3_v22_081_bounded_self_improvement"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$DoneFlag = Join-Path $StageRoot "V22_081_DONE.flag"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$Checkpoint = Join-Path $StageRoot "v22_081_checkpoint.json"
$Status = Join-Path $StageRoot "v22_081_status.json"
$Summary = Join-Path $StageRoot "v22_081_summary.json"
$Report = Join-Path $StageRoot "v22_081_report.md"
$RegistryJsonl = Join-Path $StageRoot "experiment_registry.jsonl"
$RegistryParquet = Join-Path $StageRoot "experiment_registry.parquet"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_081_AGENT.lock"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"

Write-Host "FAST3_V22_081_STAGE_ROOT=$StageRoot"
Write-Host "DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $DoneFlag)"
Write-Host "AGENT_LOCK_EXISTS=$(Test-Path -LiteralPath $LockFile)"
Write-Host "STOP_REQUESTED=$(Test-Path -LiteralPath $StopFlag)"

foreach ($path in @($LauncherState, $Status, $Checkpoint, $Summary)) {
    if (Test-Path -LiteralPath $path) {
        Write-Host ""
        Write-Host "===== $path ====="
        Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $RegistryJsonl) {
    $count = (Get-Content -LiteralPath $RegistryJsonl -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    Write-Host "EXPERIMENT_REGISTRY=$RegistryJsonl"
    Write-Host "EXPERIMENT_RECORD_COUNT=$count"
}
elseif (Test-Path -LiteralPath $RegistryParquet) {
    Write-Host "EXPERIMENT_REGISTRY=$RegistryParquet"
}
else {
    Write-Host "EXPERIMENT_REGISTRY=NOT_CREATED_YET"
}

if (Test-Path -LiteralPath $Report) {
    Write-Host "REPORT_PATH=$Report"
}

$latestLogs = Get-ChildItem -LiteralPath $RuntimeRoot -Filter "v22_081_round_*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3

if ($latestLogs) {
    Write-Host ""
    Write-Host "===== LATEST ROUND LOGS ====="
    $latestLogs | Select-Object LastWriteTime, Length, FullName | Format-Table -AutoSize
}

Write-Host ""
Write-Host 'RESUME_COMMAND=powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_081_agent.ps1" -Resume -MaxRounds 64 -MaxExperiments 50'
