[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$MaxRounds = 96,

    [ValidateRange(1, 12)]
    [int]$MaxGenerations = 4,

    [ValidateRange(1, 200)]
    [int]$ExperimentsPerGeneration = 40,

    [ValidateRange(1, 2000)]
    [int]$MaxTotalExperiments = 160,

    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Global -ErrorAction SilentlyContinue

$RepoRoot = "D:\us-tech-quant"
$ResultsRoot = "D:\us-tech-quant-results"
$StageRoot = Join-Path $ResultsRoot "fast3_v22_083_delay_robust_sparse_event"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$PromptPath = Join-Path $RepoRoot "fast3\docs\prompts\legacy\CODEX_FAST3_V22_083_PROMPT.txt"
$AuthorizationPath = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\FAST3_V22_083_AUTHORIZATION.md"
$GlobalDoneFlag = Join-Path $StageRoot "V22_083_GLOBAL_DONE.flag"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_083_AGENT.lock"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$BudgetPath = Join-Path $StageRoot "autopilot_budget.json"
$GlobalCheckpoint = Join-Path $StageRoot "v22_083_checkpoint.json"

function Write-JsonFile {
    param([string]$Path, [hashtable]$Value)
    $Value | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-UsageLimit {
    param([string]$Text)
    return $Text -match '(?i)usage limit|rate limit|quota|credits exhausted|weekly limit|too many requests|insufficient credits'
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

if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
    throw "Repository not found: $RepoRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "Not a Git repository: $RepoRoot"
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI is not available in PATH."
}
if (-not (Test-Path -LiteralPath $PromptPath -PathType Leaf)) {
    throw "Prompt not found: $PromptPath"
}
if (-not (Test-Path -LiteralPath $AuthorizationPath -PathType Leaf)) {
    throw "Authorization not found: $AuthorizationPath"
}

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null

if (Test-Path -LiteralPath $LockFile) {
    $oldPidText = Get-Content -LiteralPath $LockFile -Raw -ErrorAction SilentlyContinue
    $oldPid = 0
    [void][int]::TryParse(($oldPidText -replace '[^0-9]', ''), [ref]$oldPid)
    if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        throw "FAST3 V22.083 agent is already running. PID=$oldPid"
    }
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $GlobalDoneFlag) {
    Write-Host "FINAL_STATUS=V22_083_ALREADY_GLOBALLY_TERMINAL"
    Write-Host "GLOBAL_DONE_FLAG=$GlobalDoneFlag"
    Write-Host "Use the status command to inspect the final result."
    exit 0
}

$existingState = (Test-Path -LiteralPath $GlobalCheckpoint) -or (Test-Path -LiteralPath $LauncherState)
$effectiveResume = $Resume -or $existingState
Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue

Write-JsonFile -Path $BudgetPath -Value @{
    stage = "V22.083_FAST3_DELAY_ROBUST_SPARSE_EVENT_ENGINE_R1"
    written_at = (Get-Date).ToString("o")
    max_codex_rounds = $MaxRounds
    max_generations = $MaxGenerations
    experiments_per_generation = $ExperimentsPerGeneration
    max_total_experiments = $MaxTotalExperiments
    max_active_candidates = 3
    max_model_families = 2
    max_active_features = 25
    no_trade_rate_target_min = 0.70
    no_trade_rate_target_max = 0.95
    delay_minutes = @(1, 3, 5)
    cost_bps = @(5, 10, 20, 30)
    aggregate_validation_max_drawdown = 0.20
    single_validation_fold_max_drawdown = 0.25
    confirmation_max_drawdown = 0.20
    consecutive_generation_no_improvement_stop = 2
    same_primary_failure_without_new_hypothesis_stop = 2
    paper_trading_allowed = $false
    shadow_allowed = $false
    broker_action_allowed = $false
    official_adoption_allowed = $false
}

Set-Content -LiteralPath $LockFile -Value $PID -Encoding ASCII
Set-Location -LiteralPath $RepoRoot

$startedAt = Get-Date
$lastExit = 0
$stopReason = "MAX_CODEX_ROUNDS_REACHED"

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.083 DELAY-ROBUST SPARSE EVENT AUTOPILOT"
Write-Host "============================================================"
Write-Host "Repository                : $RepoRoot"
Write-Host "Results                   : $StageRoot"
Write-Host "Max Codex rounds          : $MaxRounds"
Write-Host "Max generations           : $MaxGenerations"
Write-Host "Experiments per generation: $ExperimentsPerGeneration"
Write-Host "Max total experiments     : $MaxTotalExperiments"
Write-Host "Resume                    : $effectiveResume"
Write-Host ""

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFlag) {
            $stopReason = "SAFE_STOP_REQUESTED"
            break
        }
        if (Test-Path -LiteralPath $GlobalDoneFlag) {
            $stopReason = "V22_083_GLOBAL_DONE_FLAG_CREATED"
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $events = Join-Path $RuntimeRoot ("v22_083_round_{0:D3}_{1}.log" -f $round, $stamp)
        $stderr = Join-Path $RuntimeRoot ("v22_083_round_{0:D3}_{1}.stderr.log" -f $round, $stamp)

        Write-Host ""
        Write-Host "============================================================"
        Write-Host ("FAST3 V22.083 CODEX ROUND {0} / {1}" -f $round, $MaxRounds)
        Write-Host "============================================================"
        Write-Host "Log    : $events"
        Write-Host "Errors : $stderr"

        $useResume = $effectiveResume -or $round -gt 1
        if ($useResume) {
            $followUp = @"
Resume V22.083_FAST3_DELAY_ROBUST_SPARSE_EVENT_ENGINE_R1 from persisted code,
registries, frozen split manifest, checkpoint, and prior run artifacts. This is
launcher Codex round $round. Budgets are frozen in:
$BudgetPath

Continue the first unfinished high-value action. Run real code and tests; do not
only describe a plan. A generation-level FAIL_VALIDATION or FAIL_CONFIRMATION
closes only that generation. If an untouched predeclared fold remains and no global
stop rule applies, classify the failure, record bounded mutations, and continue to
the next generation. Never reopen a consumed holdout and never retune against the
Global Final Holdout.

Primary objective: delay-robust sparse SOXL/SOXS events. Champion selection must
use conservative 1/3/5-minute execution-delay performance, 20bps resilience,
hard drawdown gates, profit-concentration checks, and NO_TRADE. Keep at most two
model families, 25 active features, and three active candidates. Do not create
V22.083A/B/C/R2/R3 or duplicate architecture. Preserve V22.081/V22.082 results.
Create V22_083_GLOBAL_DONE.flag only for a legal global terminal condition in the
authorization contract, never merely because one candidate or generation failed.
"@
            $lastExit = Invoke-ResumeCodexTurn -Instruction $followUp -EventsPath $events -StderrPath $stderr

            if ($lastExit -ne 0) {
                $resumeText = ((Get-Content -LiteralPath $events -Raw -ErrorAction SilentlyContinue) + "`n" +
                    (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue))
                if ($resumeText -match '(?i)no session|no previous|not found|resume.*failed') {
                    Write-Host "Resume session unavailable; starting a new Codex turn from persisted files."
                    $lastExit = Invoke-NewCodexTurn -EventsPath $events -StderrPath $stderr
                }
            }
        }
        else {
            $lastExit = Invoke-NewCodexTurn -EventsPath $events -StderrPath $stderr
        }

        $combined = ((Get-Content -LiteralPath $events -Raw -ErrorAction SilentlyContinue) + "`n" +
            (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue))

        Write-Host "CODEX_EXIT_CODE=$lastExit"

        Write-JsonFile -Path $LauncherState -Value @{
            stage = "V22.083_FAST3_DELAY_ROBUST_SPARSE_EVENT_ENGINE_R1"
            updated_at = (Get-Date).ToString("o")
            launcher_pid = $PID
            current_codex_round = $round
            max_codex_rounds = $MaxRounds
            max_generations = $MaxGenerations
            experiments_per_generation = $ExperimentsPerGeneration
            max_total_experiments = $MaxTotalExperiments
            last_codex_exit_code = $lastExit
            last_log = $events
            last_stderr = $stderr
            global_done_flag_exists = (Test-Path -LiteralPath $GlobalDoneFlag)
            stop_requested = (Test-Path -LiteralPath $StopFlag)
        }

        if (Test-Path -LiteralPath $GlobalDoneFlag) {
            $stopReason = "V22_083_GLOBAL_DONE_FLAG_CREATED"
            break
        }
        if (Test-UsageLimit -Text $combined) {
            $stopReason = "CODEX_USAGE_OR_RATE_LIMIT"
            break
        }

        if ($lastExit -ne 0) {
            Start-Sleep -Seconds 20
        }
        else {
            Start-Sleep -Seconds 5
        }
        $effectiveResume = $true
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $GlobalDoneFlag) {
    $stopReason = "V22_083_GLOBAL_DONE_FLAG_CREATED"
}

Write-JsonFile -Path $LauncherState -Value @{
    stage = "V22.083_FAST3_DELAY_ROBUST_SPARSE_EVENT_ENGINE_R1"
    updated_at = (Get-Date).ToString("o")
    launcher_pid = $PID
    started_at = $startedAt.ToString("o")
    ended_at = (Get-Date).ToString("o")
    max_codex_rounds = $MaxRounds
    max_generations = $MaxGenerations
    experiments_per_generation = $ExperimentsPerGeneration
    max_total_experiments = $MaxTotalExperiments
    last_codex_exit_code = $lastExit
    launcher_stop_reason = $stopReason
    global_done_flag_exists = (Test-Path -LiteralPath $GlobalDoneFlag)
    resume_command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_083_agent.ps1" -Resume -MaxRounds 96 -MaxGenerations 4 -ExperimentsPerGeneration 40 -MaxTotalExperiments 160'
}

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.083 LAUNCHER ENDED"
Write-Host "============================================================"
Write-Host "LAUNCHER_STOP_REASON=$stopReason"
Write-Host "GLOBAL_DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $GlobalDoneFlag)"
Write-Host "Runtime logs: $RuntimeRoot"
Write-Host ""
Write-Host "Resume:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_083_agent.ps1" -Resume -MaxRounds 96 -MaxGenerations 4 -ExperimentsPerGeneration 40 -MaxTotalExperiments 160'
Write-Host ""
Write-Host "Status:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\show_fast3_v22_083_status.ps1"'
Write-Host ""
Write-Host "Safe stop between Codex rounds:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\stop_fast3_v22_083_agent.ps1"'
