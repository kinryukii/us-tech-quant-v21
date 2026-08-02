[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$MaxRounds = 96,

    [ValidateRange(1, 20)]
    [int]$MaxGenerations = 6,

    [ValidateRange(1, 500)]
    [int]$ExperimentsPerGeneration = 50,

    [ValidateRange(1, 5000)]
    [int]$MaxTotalExperiments = 300,

    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Global -ErrorAction SilentlyContinue

$RepoRoot = "D:\us-tech-quant"
$ResultsRoot = "D:\us-tech-quant-results"
$StageRoot = Join-Path $ResultsRoot "fast3_v22_082_multigeneration_autopilot"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$PromptPath = Join-Path $RepoRoot "fast3\docs\prompts\legacy\CODEX_FAST3_V22_082_PROMPT.txt"
$AuthorizationPath = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\FAST3_V22_082_AUTHORIZATION.md"
$GlobalDoneFlag = Join-Path $StageRoot "V22_082_GLOBAL_DONE.flag"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_082_AGENT.lock"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$BudgetPath = Join-Path $StageRoot "autopilot_budget.json"
$GlobalCheckpoint = Join-Path $StageRoot "v22_082_global_checkpoint.json"

function Write-JsonFile {
    param([string]$Path, [hashtable]$Value)
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
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
        throw "FAST3 V22.082 agent is already running. PID=$oldPid"
    }
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $GlobalDoneFlag) {
    Write-Host "FINAL_STATUS=V22_082_ALREADY_GLOBALLY_TERMINAL"
    Write-Host "GLOBAL_DONE_FLAG=$GlobalDoneFlag"
    Write-Host "Use the status command to inspect the final result."
    exit 0
}

$existingState = (Test-Path -LiteralPath $GlobalCheckpoint) -or (Test-Path -LiteralPath $LauncherState)
$effectiveResume = $Resume -or $existingState
Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue

Write-JsonFile -Path $BudgetPath -Value @{
    stage = "V22.082_FAST3_BOUNDED_MULTIGENERATION_AUTOPILOT_R1"
    written_at = (Get-Date).ToString("o")
    max_codex_rounds = $MaxRounds
    max_generations = $MaxGenerations
    experiments_per_generation = $ExperimentsPerGeneration
    max_total_experiments = $MaxTotalExperiments
    max_active_candidates = 3
    max_model_families = 5
    max_active_features = 40
    consecutive_generation_no_improvement_stop = 3
    same_confirmation_failure_class_stop = 3
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
Write-Host "FAST3 V22.082 BOUNDED MULTI-GENERATION AUTOPILOT"
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
            $stopReason = "V22_082_GLOBAL_DONE_FLAG_CREATED"
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $events = Join-Path $RuntimeRoot ("v22_082_round_{0:D3}_{1}.log" -f $round, $stamp)
        $stderr = Join-Path $RuntimeRoot ("v22_082_round_{0:D3}_{1}.stderr.log" -f $round, $stamp)

        Write-Host ""
        Write-Host "============================================================"
        Write-Host ("FAST3 V22.082 CODEX ROUND {0} / {1}" -f $round, $MaxRounds)
        Write-Host "============================================================"
        Write-Host "Log    : $events"
        Write-Host "Errors : $stderr"

        $useResume = $effectiveResume -or $round -gt 1
        if ($useResume) {
            $followUp = @"
Resume V22.082_FAST3_BOUNDED_MULTIGENERATION_AUTOPILOT_R1 from the persisted global
checkpoint, generation registry, experiment registry, and implementation files.
This is launcher Codex round $round. Budgets are frozen in:
$BudgetPath

Critical behavior: a generation-level FAIL_VALIDATION or FAIL_CONFIRMATION closes
only that generation. It is NOT a global terminal condition. After truthfully
recording and freezing the failed generation, automatically classify the failure,
consume that holdout exactly once, advance to the next predeclared untouched outer
fold, generate a bounded next-generation hypothesis, and continue training unless a
global stop rule has been reached. Never reopen or retune against a consumed holdout.

Do not restart architecture, duplicate files, or create V22.082A/B/C/R2/R3. Continue
from the first unfinished high-value action. Run real code, tests, randomized
contiguous-time training, Development-internal OOS backtests, and one-time holdout
gates. Keep the global registries current. Create V22_082_GLOBAL_DONE.flag only for a
legal GLOBAL terminal condition in FAST3_V22_082_AUTHORIZATION.md, never merely
because the current generation ended.
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
            stage = "V22.082_FAST3_BOUNDED_MULTIGENERATION_AUTOPILOT_R1"
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
            $stopReason = "V22_082_GLOBAL_DONE_FLAG_CREATED"
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
    $stopReason = "V22_082_GLOBAL_DONE_FLAG_CREATED"
}

Write-JsonFile -Path $LauncherState -Value @{
    stage = "V22.082_FAST3_BOUNDED_MULTIGENERATION_AUTOPILOT_R1"
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
    resume_command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_082_agent.ps1" -Resume -MaxRounds 96 -MaxGenerations 6 -ExperimentsPerGeneration 50 -MaxTotalExperiments 300'
}

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.082 LAUNCHER ENDED"
Write-Host "============================================================"
Write-Host "LAUNCHER_STOP_REASON=$stopReason"
Write-Host "GLOBAL_DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $GlobalDoneFlag)"
Write-Host "Runtime logs: $RuntimeRoot"
Write-Host ""
Write-Host "Resume:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_082_agent.ps1" -Resume -MaxRounds 96 -MaxGenerations 6 -ExperimentsPerGeneration 50 -MaxTotalExperiments 300'
Write-Host ""
Write-Host "Status:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\show_fast3_v22_082_status.ps1"'
Write-Host ""
Write-Host "Safe stop between Codex rounds:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\stop_fast3_v22_082_agent.ps1"'
