[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$MaxRounds = 64,

    [ValidateRange(1, 500)]
    [int]$MaxExperiments = 50,

    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Global -ErrorAction SilentlyContinue

$RepoRoot = "D:\us-tech-quant"
$ResultsRoot = "D:\us-tech-quant-results"
$StageRoot = Join-Path $ResultsRoot "fast3_v22_081_bounded_self_improvement"
$RuntimeRoot = Join-Path $StageRoot "agent_runtime"
$PromptPath = Join-Path $RepoRoot "fast3\docs\prompts\legacy\CODEX_FAST3_V22_081_PROMPT.txt"
$AuthorizationPath = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\FAST3_V22_081_AUTHORIZATION.md"
$DoneFlag = Join-Path $StageRoot "V22_081_DONE.flag"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"
$LockFile = Join-Path $RuntimeRoot "FAST3_V22_081_AGENT.lock"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"

function Write-JsonFile {
    param([string]$Path, [hashtable]$Value)
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-UsageLimit {
    param([string]$Text)
    return $Text -match '(?i)usage limit|rate limit|quota|credits exhausted|weekly limit|too many requests'
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
        throw "FAST3 V22.081 agent is already running. PID=$oldPid"
    }
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $DoneFlag) {
    Write-Host "FINAL_STATUS=V22_081_ALREADY_TERMINAL"
    Write-Host "DONE_FLAG=$DoneFlag"
    Write-Host "Use the status command to inspect the final result."
    exit 0
}

if (-not $Resume) {
    Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue
}

Set-Content -LiteralPath $LockFile -Value $PID -Encoding ASCII
Set-Location -LiteralPath $RepoRoot

$startedAt = Get-Date
$lastExit = 0
$stopReason = "MAX_ROUNDS_REACHED"

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.081 BOUNDED SELF-IMPROVEMENT AGENT"
Write-Host "============================================================"
Write-Host "Repository      : $RepoRoot"
Write-Host "Results         : $StageRoot"
Write-Host "Max Codex rounds: $MaxRounds"
Write-Host "Max experiments : $MaxExperiments"
Write-Host "Resume          : $Resume"
Write-Host ""

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFlag) {
            $stopReason = "SAFE_STOP_REQUESTED"
            break
        }
        if (Test-Path -LiteralPath $DoneFlag) {
            $stopReason = "V22_081_DONE_FLAG_CREATED"
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $events = Join-Path $RuntimeRoot ("v22_081_round_{0:D3}_{1}.log" -f $round, $stamp)
        $stderr = Join-Path $RuntimeRoot ("v22_081_round_{0:D3}_{1}.stderr.log" -f $round, $stamp)

        Write-Host ""
        Write-Host "============================================================"
        Write-Host ("FAST3 V22.081 ROUND {0} / {1}" -f $round, $MaxRounds)
        Write-Host "============================================================"
        Write-Host "Log    : $events"
        Write-Host "Errors : $stderr"

        $useResume = $Resume -or $round -gt 1
        if ($useResume) {
            $followUp = @"
Resume the authorized V22.081_FAST3_BOUNDED_SELF_IMPROVEMENT_ENGINE_R1 from its
existing files, experiment registry, and checkpoint. This is launcher round $round.
The overall experiment ceiling is $MaxExperiments. Do not restart design and do not
create a new generation or version. Inspect completed experiment IDs and continue
from the first unfinished high-value action. Candidate failure is not terminal while
Development experiment budget remains. Continue real randomized contiguous-window
training and inner OOS backtesting, bounded candidate mutation, tests, and registry
updates. Validation and Confirmation remain one-time non-adaptive holdouts. Do not
create V22_081_DONE.flag unless a legal terminal condition in
FAST3_V22_081_AUTHORIZATION.md has actually been reached and final outputs validate.
"@
            $lastExit = Invoke-ResumeCodexTurn -Instruction $followUp -EventsPath $events -StderrPath $stderr

            if ($lastExit -ne 0) {
                $resumeText = ((Get-Content -LiteralPath $events -Raw -ErrorAction SilentlyContinue) + "`n" +
                    (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue))
                if ($resumeText -match '(?i)no session|no previous|not found|resume.*failed') {
                    Write-Host "Resume session unavailable; starting a new turn from the persisted checkpoint."
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
            stage = "V22.081_FAST3_BOUNDED_SELF_IMPROVEMENT_ENGINE_R1"
            updated_at = (Get-Date).ToString("o")
            launcher_pid = $PID
            current_round = $round
            max_rounds = $MaxRounds
            max_experiments = $MaxExperiments
            last_codex_exit_code = $lastExit
            last_log = $events
            done_flag_exists = (Test-Path -LiteralPath $DoneFlag)
            stop_requested = (Test-Path -LiteralPath $StopFlag)
        }

        if (Test-Path -LiteralPath $DoneFlag) {
            $stopReason = "V22_081_DONE_FLAG_CREATED"
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
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $DoneFlag) {
    $stopReason = "V22_081_DONE_FLAG_CREATED"
}

Write-JsonFile -Path $LauncherState -Value @{
    stage = "V22.081_FAST3_BOUNDED_SELF_IMPROVEMENT_ENGINE_R1"
    updated_at = (Get-Date).ToString("o")
    launcher_pid = $PID
    started_at = $startedAt.ToString("o")
    ended_at = (Get-Date).ToString("o")
    max_rounds = $MaxRounds
    max_experiments = $MaxExperiments
    last_codex_exit_code = $lastExit
    launcher_stop_reason = $stopReason
    done_flag_exists = (Test-Path -LiteralPath $DoneFlag)
    resume_command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_081_agent.ps1" -Resume -MaxRounds 64 -MaxExperiments 50'
}

Write-Host ""
Write-Host "============================================================"
Write-Host "FAST3 V22.081 LAUNCHER ENDED"
Write-Host "============================================================"
Write-Host "LAUNCHER_STOP_REASON=$stopReason"
Write-Host "DONE_FLAG_EXISTS=$(Test-Path -LiteralPath $DoneFlag)"
Write-Host "Runtime logs: $RuntimeRoot"
Write-Host ""
Write-Host "Resume:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\run_fast3_v22_081_agent.ps1" -Resume -MaxRounds 64 -MaxExperiments 50'
Write-Host ""
Write-Host "Status:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\show_fast3_v22_081_status.ps1"'
Write-Host ""
Write-Host "Safe stop between rounds:"
Write-Host 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\us-tech-quant\scripts\v22\stop_fast3_v22_081_agent.ps1"'
