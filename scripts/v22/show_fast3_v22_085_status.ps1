[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$StageRoot = "D:\us-tech-quant-results\fast3_v22_085_aggressive_bounded_search"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$GlobalDoneFlag = Join-Path $StageRoot "V22_085_GLOBAL_DONE.flag"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$Budget = Join-Path $StageRoot "autopilot_budget.json"
$Checkpoint = Join-Path $StageRoot "v22_085_checkpoint.json"
$Summary = Join-Path $StageRoot "v22_085_summary.json"
$SummaryText = Join-Path $StageRoot "v22_085_summary.txt"
$LatestGeneration = Join-Path $StageRoot "latest_generation_summary.json"
$GenerationRegistry = Join-Path $StageRoot "generation_registry.jsonl"
$ExperimentRegistry = Join-Path $StageRoot "experiment_registry.jsonl"
$Champion = Join-Path $StageRoot "champion_config.json"
$Report = Join-Path $StageRoot "v22_085_report.md"
$SplitManifest = Join-Path $StageRoot "frozen_split_manifest.json"
$Eligibility = Join-Path $StageRoot "data_eligibility_contract.json"
$PowerAudit = Join-Path $StageRoot "statistical_power_feasibility_audit.json"
$Funnel = Join-Path $StageRoot "candidate_funnel_summary.json"
$LongShort = Join-Path $StageRoot "aggressive_search_diagnostic.json"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_085_AGENT.lock"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"

Write-Host "FAST3_V22_085_STAGE_ROOT=$StageRoot"
Write-Host "GLOBAL_DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $GlobalDoneFlag)"
Write-Host "AGENT_LOCK_EXISTS=$(Test-Path -LiteralPath $LockFile)"
Write-Host "STOP_REQUESTED=$(Test-Path -LiteralPath $StopFlag)"

foreach ($path in @($Budget, $LauncherState, $Eligibility, $PowerAudit, $Funnel, $SplitManifest, $Checkpoint, $LatestGeneration, $Summary, $Champion, $LongShort)) {
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

$latestLogs = Get-ChildItem -LiteralPath $RuntimeRoot -Filter "v22_085_round_*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3

if ($latestLogs) {
    Write-Host ""
    Write-Host "===== LATEST CODEX ROUND LOGS ====="
    $latestLogs | Select-Object LastWriteTime, Length, FullName | Format-Table -AutoSize
}

Write-Host ""
Write-Host 'RESUME_COMMAND=powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_085_agent.ps1" -Resume -MaxRounds 160 -MaxGenerations 8 -ExperimentsPerGeneration 40 -MaxTotalExperiments 320'
