[CmdletBinding()]
param(
    [ValidateRange(1, 2000)]
    [int]$MaxRounds = 256,

    [ValidateRange(1, 32)]
    [int]$MaxGenerations = 16,

    [ValidateRange(1, 256)]
    [int]$ExperimentsPerGeneration = 64,

    [ValidateRange(1, 10000)]
    [int]$MaxTotalExperiments = 1024,

    [ValidateRange(0, 23)]
    [int]$MorningHour = 10,

    [ValidateRange(1, 5000)]
    [int]$MinimumRegisteredExperiments = 240,

    [ValidateRange(1, 32)]
    [int]$MinimumGenerations = 6,

    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Global -ErrorAction SilentlyContinue

$RepoRoot = "D:\us-tech-quant"
$ResultsRoot = "D:\us-tech-quant-results"
$StageRoot = Join-Path $ResultsRoot "fast3_v22_086_overnight_strategy_freeze"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$PromptPath = Join-Path $RepoRoot "fast3\docs\prompts\legacy\CODEX_FAST3_V22_086_PROMPT.txt"
$AuthorizationPath = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\FAST3_V22_086_AUTHORIZATION.md"
$GlobalDoneFlag = Join-Path $StageRoot "V22_086_GLOBAL_DONE.flag"
$CandidateFrozenFlag = Join-Path $StageRoot "V22_086_CANDIDATE_FROZEN.flag"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_086_AGENT.lock"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$BudgetPath = Join-Path $StageRoot "autopilot_budget.json"
$GlobalCheckpoint = Join-Path $StageRoot "v22_086_checkpoint.json"
$SummaryPath = Join-Path $StageRoot "v22_086_summary.json"
$ExperimentRegistry = Join-Path $StageRoot "experiment_registry.jsonl"
$GenerationRegistry = Join-Path $StageRoot "generation_registry.jsonl"

$SleepBlockEnabled = $false
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class Fast3PowerState {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@ -ErrorAction Stop
    [void][Fast3PowerState]::SetThreadExecutionState(0x80000001)
    $SleepBlockEnabled = $true
}
catch {
    Write-Host "WARNING=COULD_NOT_BLOCK_WINDOWS_SLEEP"
    Write-Host "SLEEP_BLOCK_ERROR=$($_.Exception.Message)"
}

function Write-JsonFile {
    param([string]$Path, [hashtable]$Value)
    $Value | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-LineCount {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 0 }
    return (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
}

function Test-UsageLimit {
    param([string]$Text)
    return $Text -match '(?i)usage limit|rate limit|quota|credits exhausted|weekly limit|too many requests|insufficient credits|context window exceeded'
}

function Get-SummaryClass {
    if (-not (Test-Path -LiteralPath $SummaryPath -PathType Leaf)) { return "" }
    try {
        $s = Get-Content -LiteralPath $SummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($name in @('CONCLUSION_CLASS','conclusion_class','FINAL_STATUS','final_status','FINAL_DECISION','final_decision')) {
            if ($null -ne $s.$name) { return [string]$s.$name }
        }
    }
    catch { return "" }
    return ""
}

function Test-LegalGlobalDone {
    param([datetime]$Deadline)
    if (-not (Test-Path -LiteralPath $GlobalDoneFlag -PathType Leaf)) { return $false }
    $expCount = Get-LineCount $ExperimentRegistry
    $genCount = Get-LineCount $GenerationRegistry
    $summaryClass = Get-SummaryClass
    $fatal = $summaryClass -match '(?i)FATAL|DATA_CONTRACT_FAILURE|LEAKAGE|USAGE_LIMIT|RATE_LIMIT'
    $deadlineReached = (Get-Date) -ge $Deadline
    if ($fatal -or $deadlineReached -or (($expCount -ge $MinimumRegisteredExperiments) -and ($genCount -ge $MinimumGenerations))) {
        return $true
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $quarantine = Join-Path $RuntimeRoot ("PREMATURE_GLOBAL_DONE_{0}.flag" -f $stamp)
    Move-Item -LiteralPath $GlobalDoneFlag -Destination $quarantine -Force -ErrorAction SilentlyContinue
    Write-Host "WARNING=PREMATURE_GLOBAL_DONE_QUARANTINED"
    Write-Host "QUARANTINED_FLAG=$quarantine"
    Write-Host "EXPERIMENT_RECORD_COUNT=$expCount"
    Write-Host "GENERATION_RECORD_COUNT=$genCount"
    Write-Host "SUMMARY_CLASS=$summaryClass"
    return $false
}

function Invoke-NewCodexTurn {
    param([string]$EventsPath, [string]$StderrPath)
    Get-Content -LiteralPath $PromptPath -Raw -Encoding UTF8 |
        & codex exec - 2>> $StderrPath |
        Tee-Object -FilePath $EventsPath |
        Out-Host
    return $LASTEXITCODE
}

function Invoke-ResumeCodexTurn {
    param([string]$Instruction, [string]$EventsPath, [string]$StderrPath)
    & codex exec resume --last $Instruction 2>> $StderrPath |
        Tee-Object -FilePath $EventsPath |
        Out-Host
    return $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) { throw "Repository not found: $RepoRoot" }
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) { throw "Not a Git repository: $RepoRoot" }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw "Codex CLI is not available in PATH." }
if (-not (Test-Path -LiteralPath $PromptPath -PathType Leaf)) { throw "Prompt not found: $PromptPath" }
if (-not (Test-Path -LiteralPath $AuthorizationPath -PathType Leaf)) { throw "Authorization not found: $AuthorizationPath" }

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null

if (Test-Path -LiteralPath $LockFile) {
    $oldPidText = Get-Content -LiteralPath $LockFile -Raw -ErrorAction SilentlyContinue
    $oldPid = 0
    [void][int]::TryParse(($oldPidText -replace '[^0-9]', ''), [ref]$oldPid)
    if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        throw "FAST3 V22.086 agent is already running. PID=$oldPid"
    }
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

$now = Get-Date
$Deadline = $now.Date.AddHours($MorningHour)
if ($Deadline -le $now.AddMinutes(5)) { $Deadline = $Deadline.AddDays(1) }

if (Test-LegalGlobalDone -Deadline $Deadline) {
    Write-Host "FINAL_STATUS=V22_086_ALREADY_GLOBALLY_TERMINAL"
    Write-Host "GLOBAL_DONE_FLAG=$GlobalDoneFlag"
    Write-Host "Use the status command to inspect the final result."
    exit 0
}

$existingState = (Test-Path -LiteralPath $GlobalCheckpoint) -or (Test-Path -LiteralPath $LauncherState)
$effectiveResume = $Resume -or $existingState
Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue

Write-JsonFile -Path $BudgetPath -Value @{
    stage = "V22.086_FAST3_OVERNIGHT_STRATEGY_DISCOVERY_AND_FREEZE_R1"
    written_at = (Get-Date).ToString("o")
    morning_deadline = $Deadline.ToString("o")
    max_codex_rounds = $MaxRounds
    max_generations = $MaxGenerations
    experiments_per_generation = $ExperimentsPerGeneration
    max_total_experiments = $MaxTotalExperiments
    minimum_registered_experiments_before_ordinary_terminal = $MinimumRegisteredExperiments
    minimum_generations_before_ordinary_terminal = $MinimumGenerations
    max_active_candidates = 5
    max_saved_model_files = 6
    max_model_families = 4
    max_active_features = 32
    max_label_families = 6
    model_families = @("elastic_net_logistic", "hist_gradient_boosting", "bounded_shallow_boosting_if_installed", "auditable_rule_ranker")
    label_horizons_minutes = @(15, 30, 60, 120, 180, 390)
    delay_minutes = @(1, 3, 5)
    cost_bps = @(5, 10, 20, 30)
    minimum_internal_oos_trades_for_primary_candidate = 100
    minimum_internal_oos_unique_days_for_primary_candidate = 60
    minimum_shadow_only_trades = 60
    minimum_shadow_only_unique_days = 40
    positive_fold_rate_target = 0.65
    aggregate_max_drawdown = 0.20
    shadow_only_max_drawdown = 0.25
    trial_aware_selection_required = $true
    nested_purged_walk_forward_required = $true
    block_bootstrap_required = $true
    pbo_or_equivalent_required = $true
    deflated_sharpe_or_equivalent_required = $true
    separate_soxl_soxs_models = $true
    allow_single_side_candidate = $true
    candidate_freeze_required = $true
    daily_shadow_runner_required = $true
    candidate_may_be_ready_for_forward_validation = $true
    paper_trading_allowed = $false
    broker_action_allowed = $false
    official_adoption_allowed = $false
}
Set-Content -LiteralPath $LockFile -Value $PID -Encoding ASCII
Set-Location -LiteralPath $RepoRoot

$startedAt = Get-Date
$lastExit = 0
$stopReason = "MAX_CODEX_ROUNDS_REACHED"
$usageLimited = $false

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.086 OVERNIGHT STRATEGY DISCOVERY + FREEZE AUTOPILOT"
Write-Host "============================================================"
Write-Host "Repository                : $RepoRoot"
Write-Host "Results                   : $StageRoot"
Write-Host "Morning deadline          : $($Deadline.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
Write-Host "Max Codex rounds          : $MaxRounds"
Write-Host "Max generations           : $MaxGenerations"
Write-Host "Experiments per generation: $ExperimentsPerGeneration"
Write-Host "Max total experiments     : $MaxTotalExperiments"
Write-Host "Minimum experiments       : $MinimumRegisteredExperiments"
Write-Host "Minimum generations       : $MinimumGenerations"
Write-Host "Resume                    : $effectiveResume"
Write-Host ""

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFlag) { $stopReason = "SAFE_STOP_REQUESTED"; break }
        if (Test-LegalGlobalDone -Deadline $Deadline) { $stopReason = "V22_086_GLOBAL_DONE_FLAG_CREATED"; break }
        if ((Get-Date) -ge $Deadline) { $stopReason = "MORNING_DEADLINE_REACHED"; break }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $events = Join-Path $RuntimeRoot ("v22_086_round_{0:D3}_{1}.log" -f $round, $stamp)
        $stderr = Join-Path $RuntimeRoot ("v22_086_round_{0:D3}_{1}.stderr.log" -f $round, $stamp)

        Write-Host ""
        Write-Host "============================================================"
        Write-Host ("FAST3 V22.086 CODEX ROUND {0} / {1}" -f $round, $MaxRounds)
        Write-Host "============================================================"
        Write-Host "Log    : $events"
        Write-Host "Errors : $stderr"

        $useResume = $effectiveResume -or $round -gt 1
        if ($useResume) {
            $followUp = @"
Resume V22.086_FAST3_OVERNIGHT_STRATEGY_DISCOVERY_AND_FREEZE_R1 from all persisted
code, registries, checkpoint, candidate files, frozen manifests, and diagnostics.
This is launcher Codex round $round. The frozen budget and morning deadline are in:
$BudgetPath

Continue real implementation, testing, experiments, stress testing, or candidate
freeze. Do not merely describe a plan. Do not terminate merely because one proposed
untouched partition is underpowered. First build a full historical usage ledger,
then use all legally available history as Development under nested purged chronological
walk-forward with trial-aware selection penalties. Truly untouched history, if any,
remains one-read final evidence; consumed periods may never be called unseen again.

Ordinary terminal completion is illegal before both $MinimumRegisteredExperiments
registered candidates and $MinimumGenerations generations, unless the morning deadline,
a fatal leakage/data defect, user stop, or Codex usage limit occurs. If a candidate
has already been frozen, do not retune it. Use remaining time for adversarial stress
tests, bootstrap uncertainty, PBO/selection-bias diagnostics, challenger research,
and completion/testing of the daily no-order shadow runner.

The required morning product is either: (1) a hash-frozen FAST3_V1 candidate marked
READY_FOR_FORWARD_VALIDATION, (2) a clearly weaker SHADOW_ONLY_EXPERIMENTAL_CANDIDATE,
or (3) truthful NO_SAFE_CANDIDATE. Never guarantee profitability or label an
underpowered candidate accurate. Broker actions and official adoption stay false.
"@
            $lastExit = Invoke-ResumeCodexTurn -Instruction $followUp -EventsPath $events -StderrPath $stderr
        }
        else {
            $lastExit = Invoke-NewCodexTurn -EventsPath $events -StderrPath $stderr
        }

        $stderrText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue } else { "" }
        $eventsText = if (Test-Path -LiteralPath $events) { Get-Content -LiteralPath $events -Raw -ErrorAction SilentlyContinue } else { "" }
        $expCount = Get-LineCount $ExperimentRegistry
        $genCount = Get-LineCount $GenerationRegistry

        Write-JsonFile -Path $LauncherState -Value @{
            stage = "V22.086_FAST3_OVERNIGHT_STRATEGY_DISCOVERY_AND_FREEZE_R1"
            updated_at = (Get-Date).ToString("o")
            started_at = $startedAt.ToString("o")
            morning_deadline = $Deadline.ToString("o")
            last_round = $round
            last_exit_code = $lastExit
            experiment_record_count = $expCount
            generation_record_count = $genCount
            candidate_frozen = (Test-Path -LiteralPath $CandidateFrozenFlag)
            global_done = (Test-Path -LiteralPath $GlobalDoneFlag)
            last_log = $events
            last_stderr = $stderr
        }

        Write-Host "CODEX_EXIT_CODE=$lastExit"
        Write-Host "EXPERIMENT_RECORD_COUNT=$expCount"
        Write-Host "GENERATION_RECORD_COUNT=$genCount"
        Write-Host "CANDIDATE_FROZEN=$(Test-Path -LiteralPath $CandidateFrozenFlag)"

        if (Test-UsageLimit ($stderrText + "`n" + $eventsText)) {
            $usageLimited = $true
            $stopReason = "CODEX_USAGE_OR_RATE_LIMIT"
            break
        }

        $effectiveResume = $true
        Start-Sleep -Seconds 3
    }

    if (($stopReason -eq "MORNING_DEADLINE_REACHED" -or (Get-Date) -ge $Deadline) -and -not $usageLimited -and -not (Test-Path -LiteralPath $StopFlag)) {
        if (-not (Test-LegalGlobalDone -Deadline $Deadline)) {
            $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $events = Join-Path $RuntimeRoot ("v22_086_morning_finalize_{0}.log" -f $stamp)
            $stderr = Join-Path $RuntimeRoot ("v22_086_morning_finalize_{0}.stderr.log" -f $stamp)
            Write-Host ""
            Write-Host "============================================================"
            Write-Host "FAST3 V22.086 MORNING FINALIZATION"
            Write-Host "============================================================"
            Write-Host "Log    : $events"
            Write-Host "Errors : $stderr"
            $finalInstruction = @"
The frozen morning deadline has been reached. Stop starting new candidate searches.
Checkpoint all work. Truthfully select and hash-freeze the best legal candidate that
meets the predeclared historical robustness floor, or at most a clearly labeled
SHADOW_ONLY_EXPERIMENTAL_CANDIDATE if it meets the weaker safety floor. If neither
exists, output NO_SAFE_CANDIDATE. Never relax gates after seeing results.

Finish and test the no-order daily shadow signal runner, candidate card, forward
validation protocol, morning summary, registries, and exact next command. Set
shadow_allowed=true only for a legally frozen candidate intended solely to accumulate
future evidence. paper_trading_allowed=false, broker_action_allowed=false, and
official_adoption_allowed=false. Create V22_086_GLOBAL_DONE.flag only after outputs
are internally consistent and output-contract tests pass.
"@
            $lastExit = Invoke-ResumeCodexTurn -Instruction $finalInstruction -EventsPath $events -StderrPath $stderr
            Write-Host "MORNING_FINALIZATION_EXIT_CODE=$lastExit"
        }
    }
}
finally {
    if ($SleepBlockEnabled) {
        try { [void][Fast3PowerState]::SetThreadExecutionState(0x80000000) } catch { }
    }
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.086 LAUNCHER ENDED"
Write-Host "============================================================"
Write-Host "LAUNCHER_STOP_REASON=$stopReason"
Write-Host "GLOBAL_DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $GlobalDoneFlag)"
Write-Host "CANDIDATE_FROZEN_FLAG_EXISTS=$(Test-Path -LiteralPath $CandidateFrozenFlag)"
Write-Host "Runtime logs: $RuntimeRoot"
Write-Host ""
Write-Host "Resume:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_086_agent.ps1" -Resume -MaxRounds 256 -MaxGenerations 16 -ExperimentsPerGeneration 64 -MaxTotalExperiments 1024 -MorningHour 10 -MinimumRegisteredExperiments 240 -MinimumGenerations 6'
Write-Host ""
Write-Host "Status:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\show_fast3_v22_086_status.ps1"'
Write-Host ""
Write-Host "Safe stop between Codex rounds:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\stop_fast3_v22_086_agent.ps1"'

exit $lastExit
