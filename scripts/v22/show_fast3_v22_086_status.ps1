[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$StageRoot = "D:\us-tech-quant-results\fast3_v22_086_overnight_strategy_freeze"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$GlobalDoneFlag = Join-Path $StageRoot "V22_086_GLOBAL_DONE.flag"
$CandidateFrozenFlag = Join-Path $StageRoot "V22_086_CANDIDATE_FROZEN.flag"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$Budget = Join-Path $StageRoot "autopilot_budget.json"
$Checkpoint = Join-Path $StageRoot "v22_086_checkpoint.json"
$Summary = Join-Path $StageRoot "v22_086_summary.json"
$SummaryText = Join-Path $StageRoot "v22_086_morning_summary.txt"
$Report = Join-Path $StageRoot "v22_086_report.md"
$ExperimentRegistry = Join-Path $StageRoot "experiment_registry.jsonl"
$GenerationRegistry = Join-Path $StageRoot "generation_registry.jsonl"
$UsageLedger = Join-Path $StageRoot "historical_usage_ledger.json"
$Candidate = Join-Path $StageRoot "fast3_v1_candidate_config.json"
$CandidateCard = Join-Path $StageRoot "fast3_v1_candidate_card.md"
$ForwardProtocol = Join-Path $StageRoot "forward_validation_protocol.json"
$ShadowRunner = "D:\us-tech-quant\scripts\v22\run_v22_086_daily_shadow.ps1"
$Stress = Join-Path $StageRoot "candidate_stress_test_summary.json"
$SelectionBias = Join-Path $StageRoot "selection_bias_diagnostics.json"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_086_AGENT.lock"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"

Write-Host "FAST3_V22_086_STAGE_ROOT=$StageRoot"
Write-Host "GLOBAL_DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $GlobalDoneFlag)"
Write-Host "CANDIDATE_FROZEN_FLAG_EXISTS=$(Test-Path -LiteralPath $CandidateFrozenFlag)"
Write-Host "AGENT_LOCK_EXISTS=$(Test-Path -LiteralPath $LockFile)"
Write-Host "STOP_REQUESTED=$(Test-Path -LiteralPath $StopFlag)"
Write-Host "DAILY_SHADOW_RUNNER_EXISTS=$(Test-Path -LiteralPath $ShadowRunner)"

foreach ($path in @($Budget, $LauncherState, $UsageLedger, $Checkpoint, $Summary, $Candidate, $ForwardProtocol, $Stress, $SelectionBias)) {
    if (Test-Path -LiteralPath $path) {
        Write-Host ""
        Write-Host "===== $path ====="
        Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $GenerationRegistry) {
    $n = (Get-Content -LiteralPath $GenerationRegistry -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    Write-Host "GENERATION_REGISTRY=$GenerationRegistry"
    Write-Host "GENERATION_RECORD_COUNT=$n"
} else { Write-Host "GENERATION_REGISTRY=NOT_CREATED_YET" }

if (Test-Path -LiteralPath $ExperimentRegistry) {
    $n = (Get-Content -LiteralPath $ExperimentRegistry -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    Write-Host "EXPERIMENT_REGISTRY=$ExperimentRegistry"
    Write-Host "EXPERIMENT_RECORD_COUNT=$n"
} else { Write-Host "EXPERIMENT_REGISTRY=NOT_CREATED_YET" }

foreach ($path in @($SummaryText, $Report, $CandidateCard, $ShadowRunner)) {
    if (Test-Path -LiteralPath $path) { Write-Host "ARTIFACT_PATH=$path" }
}

$latestLogs = Get-ChildItem -LiteralPath $RuntimeRoot -Filter "v22_086_*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 5
if ($latestLogs) {
    Write-Host ""
    Write-Host "===== LATEST CODEX LOGS ====="
    $latestLogs | Select-Object LastWriteTime, Length, FullName | Format-Table -AutoSize
}

Write-Host ""
Write-Host 'RESUME_COMMAND=powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_086_agent.ps1" -Resume -MaxRounds 256 -MaxGenerations 16 -ExperimentsPerGeneration 64 -MaxTotalExperiments 1024 -MorningHour 10 -MinimumRegisteredExperiments 240 -MinimumGenerations 6'
if (Test-Path -LiteralPath $ShadowRunner) {
    Write-Host 'DAILY_SHADOW_COMMAND=powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_v22_086_daily_shadow.ps1" -Execute'
}
