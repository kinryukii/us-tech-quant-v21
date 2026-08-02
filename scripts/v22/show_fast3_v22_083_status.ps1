[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$StageRoot = "D:\us-tech-quant-results\fast3_v22_083_delay_robust_sparse_event"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$GlobalDoneFlag = Join-Path $StageRoot "V22_083_GLOBAL_DONE.flag"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$Budget = Join-Path $StageRoot "autopilot_budget.json"
$Checkpoint = Join-Path $StageRoot "v22_083_checkpoint.json"
$Summary = Join-Path $StageRoot "v22_083_summary.json"
$SummaryText = Join-Path $StageRoot "v22_083_summary.txt"
$LatestGeneration = Join-Path $StageRoot "latest_generation_summary.json"
$GenerationRegistry = Join-Path $StageRoot "generation_registry.jsonl"
$ExperimentRegistry = Join-Path $StageRoot "experiment_registry.jsonl"
$Champion = Join-Path $StageRoot "champion_config.json"
$Report = Join-Path $StageRoot "v22_083_report.md"
$SplitManifest = Join-Path $StageRoot "frozen_split_manifest.json"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_083_AGENT.lock"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"

Write-Host "FAST3_V22_083_STAGE_ROOT=$StageRoot"
Write-Host "GLOBAL_DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $GlobalDoneFlag)"
Write-Host "AGENT_LOCK_EXISTS=$(Test-Path -LiteralPath $LockFile)"
Write-Host "STOP_REQUESTED=$(Test-Path -LiteralPath $StopFlag)"

foreach ($path in @($Budget, $LauncherState, $SplitManifest, $Checkpoint, $LatestGeneration, $Summary, $Champion)) {
    if (Test-Path -LiteralPath $path) {
        Write-Host ""
        Write-Host "===== $path ====="
        Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $GenerationRegistry) {
    $generationCount = (Get-Content -LiteralPath $GenerationRegistry -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    Write-Host "GENERATION_REGISTRY=$GenerationRegistry"
    Write-Host "GENERATION_RECORD_COUNT=$generationCount"
}
else {
    Write-Host "GENERATION_REGISTRY=NOT_CREATED_YET"
}

if (Test-Path -LiteralPath $ExperimentRegistry) {
    $experimentCount = (Get-Content -LiteralPath $ExperimentRegistry -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    Write-Host "EXPERIMENT_REGISTRY=$ExperimentRegistry"
    Write-Host "EXPERIMENT_RECORD_COUNT=$experimentCount"
}
else {
    Write-Host "EXPERIMENT_REGISTRY=NOT_CREATED_YET"
}

foreach ($path in @($SummaryText, $Report)) {
    if (Test-Path -LiteralPath $path) {
        Write-Host "ARTIFACT_PATH=$path"
    }
}

$latestLogs = Get-ChildItem -LiteralPath $RuntimeRoot -Filter "v22_083_round_*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3

if ($latestLogs) {
    Write-Host ""
    Write-Host "===== LATEST CODEX ROUND LOGS ====="
    $latestLogs | Select-Object LastWriteTime, Length, FullName | Format-Table -AutoSize
}

Write-Host ""
Write-Host 'RESUME_COMMAND=powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_083_agent.ps1" -Resume -MaxRounds 96 -MaxGenerations 4 -ExperimentsPerGeneration 40 -MaxTotalExperiments 160'
