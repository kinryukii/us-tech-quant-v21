[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$MaxRounds = 64,

    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Global -ErrorAction SilentlyContinue

$RepoRoot = "D:\us-tech-quant"
$DataRoot = "D:\us-tech-quant-data"
$ResultsRoot = "D:\us-tech-quant-results"
$Gen3Root = Join-Path $ResultsRoot "fast3_autoresearch_generation3"
$RuntimeRoot = Join-Path $Gen3Root "agent_runtime"
$AuthorizationPath = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\generation\FAST3_GENERATION3_AUTHORIZATION.md"
$LockFile = Join-Path $RuntimeRoot "FAST3_GENERATION3_AGENT.lock"
$StopFile = Join-Path $RuntimeRoot "STOP_FAST3_GENERATION3_AGENT"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"
$GitSnapshot = Join-Path $RuntimeRoot "git_status_before_launch.txt"

function Write-Stage {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Text
    Write-Host "============================================================"
}

function Assert-Exists {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description does not exist: $Path"
    }
}

function Get-TextHash {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Save-State {
    param(
        [int]$Round,
        [int]$ExitCode,
        [string]$Status,
        [string]$EventLog,
        [string]$LastMessage,
        [bool]$CanResume
    )
    [ordered]@{
        updated_at = (Get-Date).ToString("o")
        launcher_pid = $PID
        round = $Round
        exit_code = $ExitCode
        status = $Status
        can_resume = $CanResume
        event_log_path = $EventLog
        last_message_path = $LastMessage
        repository = $RepoRoot
        data_root = $DataRoot
        results_root = $Gen3Root
        broker_action_allowed = $false
        live_trading_allowed = $false
    } | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $LauncherState -Encoding UTF8
}

function Test-TerminalText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $false
    }

    $terminal = @(
        "PASS_GENERATION3_PROSPECTIVE_SHADOW_DEPLOYED_AWAITING_SAMPLE",
        "PASS_GENERATION3_CONFIRMATION_ACCEPTED",
        "PASS_GENERATION3_PIPELINE_COMPLETE_NO_EDGE_CONFIRMED",
        "FAIL_DATA_CONTRACT",
        "FAIL_LEAKAGE_DETECTED",
        "FAIL_INSUFFICIENT_INDEPENDENT_DATA",
        "FAIL_OVERFITTING_RISK",
        "FAIL_NO_ROBUST_EDGE",
        "FAIL_COST_SENSITIVITY",
        "FAIL_DELAY_SENSITIVITY",
        "FAIL_CONFIRMATION"
    )

    foreach ($status in $terminal) {
        if ($Text -match [regex]::Escape("FINAL_STATUS=$status")) {
            return $true
        }
    }

    $noOpPatterns = @(
        "NONE_FAST3_GENERATION3_RESEARCH_STOPPED",
        "no permitted Generation 3 continuation",
        "Generation 3 is terminal",
        "Generation 3 has no permitted next action"
    )
    foreach ($pattern in $noOpPatterns) {
        if ($Text -match [regex]::Escape($pattern)) {
            return $true
        }
    }

    return $false
}

function Get-TerminalCheckpoint {
    if (-not (Test-Path -LiteralPath $Gen3Root)) {
        return $null
    }

    $checkpoint = Get-ChildItem -LiteralPath $Gen3Root `
        -Filter "generation3_final_checkpoint.json" `
        -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if ($null -eq $checkpoint) {
        return $null
    }

    try {
        $value = Get-Content -LiteralPath $checkpoint.FullName -Raw |
            ConvertFrom-Json
    }
    catch {
        Write-Warning "Unable to parse final checkpoint: $($checkpoint.FullName)"
        return $null
    }

    $resume = [string]$value.exact_resume_command
    $status = [string]$value.current_status

    if ($resume -match "^NONE_" -or $status -match "^(PASS_|FAIL_)") {
        return [pscustomobject]@{
            Path = $checkpoint.FullName
            CurrentStatus = $status
            ExactResumeCommand = $resume
        }
    }

    return $null
}

Assert-Exists -Path $RepoRoot -Description "Repository"
Assert-Exists -Path (Join-Path $RepoRoot ".git") -Description "Git metadata"
Assert-Exists -Path $DataRoot -Description "Data root"
Assert-Exists -Path $AuthorizationPath -Description "Generation 3 authorization"

if ($null -eq (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI was not found. Re-run INSTALL_AND_RUN_GEN3.ps1."
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $LockFile) {
    $oldPidText = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    if ($oldPidText -match "^\d+$") {
        $existing = Get-Process -Id ([int]$oldPidText) -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            throw "Another Generation 3 agent is already running. PID=$oldPidText"
        }
    }
    Remove-Item -LiteralPath $LockFile -Force
}

Set-Content -LiteralPath $LockFile -Value $PID -NoNewline -Encoding ASCII
Set-Location -LiteralPath $RepoRoot
& git status --short 2>&1 | Out-File -LiteralPath $GitSnapshot -Encoding UTF8

$initialPrompt = @"
Before editing or executing research, fully read:

$AuthorizationPath

Then read:
- AGENTS.md
- docs/FAST3_AUTORESEARCH_AGENT_SPEC.md, if present
- CODEX_GOAL.md
- CODEX_PLAN.md
- CODEX_STATUS.md
- Generation 1 and Generation 2 final summaries, checkpoints, split contracts,
  exposure ledgers, experiment registries and randomized-window records

This is a separately authorized FAST3 Generation 3. Generation 1 and Generation
2 terminal checkpoints remain immutable but do not prohibit the new generation.

Begin actual repository work now. Do not merely propose a design. Audit prior
exposure, freeze the deterministic Generation 3 split before economic results,
implement the nonlinear three-layer opportunity/direction/execution pipeline,
run real tests and bounded chronological research, and save a recoverable
checkpoint.

Treat D:\us-tech-quant-data as read-only. Preserve unrelated user work. Never
run git reset, git clean, destructive restore, mass deletion or remote push.
Write outputs only below
D:\us-tech-quant-results\fast3_autoresearch_generation3.

Keep broker_action_allowed=False, paper_broker_order_allowed=False,
live_trading_allowed=False, official_adoption_allowed=False and
research_only=True.

A terminal response must include an exact FINAL_STATUS= line from the authorized
Generation 3 status list. A resource-boundary response must use
FINAL_STATUS=PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED and include a real exact
resume command.
"@

$continuePrompt = @"
Continue FAST3 Generation 3 from the actual Generation 3 checkpoint.

First re-read:
- FAST3_GENERATION3_AUTHORIZATION.md
- the latest Generation 3 checkpoint
- split and feature contracts
- candidate registry
- completed tests/backtests
- rejected candidates
- the exact last command and exit status

Do not resume or reopen Generation 1 or Generation 2. Do not repeat a completed
experiment or burn a turn only restating a terminal checkpoint.

Execute the next permitted high-information-value Generation 3 action. Preserve
the deterministic split, Development-only selection, one-time frozen
Validation candidate set, Confirmation zero-read guard, canonical read-only
rule, no-order rule and truthful reporting.

When Generation 3 is genuinely terminal, print an exact FINAL_STATUS= line and
write a final checkpoint whose exact_resume_command begins with NONE_.
"@

$canResume = [bool]$Resume
$consecutiveFailures = 0
$previousReplyHash = ""
$duplicateReplyCount = 0

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFile) {
            Write-Host "STOP file detected. No new round will start."
            Save-State -Round $round -ExitCode 0 -Status "STOP_FILE_DETECTED" `
                -EventLog "" -LastMessage "" -CanResume $canResume
            break
        }

        $terminalCheckpoint = Get-TerminalCheckpoint
        if ($null -ne $terminalCheckpoint) {
            Write-Host "Terminal Generation 3 checkpoint already exists:"
            Write-Host "  $($terminalCheckpoint.Path)"
            Write-Host "  status=$($terminalCheckpoint.CurrentStatus)"
            Write-Host "  resume=$($terminalCheckpoint.ExactResumeCommand)"
            Save-State -Round $round -ExitCode 0 -Status "TERMINAL_CHECKPOINT_DETECTED" `
                -EventLog "" -LastMessage "" -CanResume $false
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $tag = "gen3_round_{0:D3}_{1}" -f $round, $stamp
        $eventLog = Join-Path $RuntimeRoot "$tag.events.jsonl"
        $stderrLog = Join-Path $RuntimeRoot "$tag.stderr.log"
        $lastMessage = Join-Path $RuntimeRoot "$tag.last_message.md"

        Write-Stage "FAST3 GENERATION 3 ROUND $round / $MaxRounds"
        Write-Host "Repository : $RepoRoot"
        Write-Host "Results    : $Gen3Root"
        Write-Host "Events     : $eventLog"
        Write-Host "Last reply : $lastMessage"

        $commonArgs = @(
            "exec",
            "-C", $RepoRoot,
            "--sandbox", "workspace-write",
            "--add-dir", $ResultsRoot,
            "-c", 'approval_policy="never"',
            "-c", "sandbox_workspace_write.network_access=false",
            "--json",
            "--output-last-message", $lastMessage
        )

        if ($canResume) {
            & codex @commonArgs "resume" "--last" $continuePrompt `
                2>> $stderrLog |
                Tee-Object -FilePath $eventLog
        }
        else {
            & codex @commonArgs $initialPrompt `
                2>> $stderrLog |
                Tee-Object -FilePath $eventLog
        }

        $exitCode = $LASTEXITCODE
        Write-Host ""
        Write-Host "CODEX_EXIT_CODE=$exitCode"

        $lastText = ""
        if (Test-Path -LiteralPath $lastMessage) {
            $lastText = Get-Content -LiteralPath $lastMessage -Raw
        }

        if ($exitCode -eq 0) {
            $consecutiveFailures = 0
            $canResume = $true
        }
        else {
            $consecutiveFailures++
            Write-Warning "Codex process exit code=$exitCode; consecutive failures=$consecutiveFailures"
        }

        Save-State -Round $round -ExitCode $exitCode `
            -Status $(if ($exitCode -eq 0) { "ROUND_COMPLETED" } else { "ROUND_FAILED" }) `
            -EventLog $eventLog -LastMessage $lastMessage -CanResume $canResume

        if (Test-TerminalText -Text $lastText) {
            Write-Host "Generation 3 terminal response detected."
            Save-State -Round $round -ExitCode $exitCode `
                -Status "TERMINAL_RESPONSE_DETECTED" `
                -EventLog $eventLog -LastMessage $lastMessage -CanResume $false
            break
        }

        $terminalCheckpoint = Get-TerminalCheckpoint
        if ($null -ne $terminalCheckpoint) {
            Write-Host "Generation 3 terminal checkpoint detected after the round."
            Write-Host "  $($terminalCheckpoint.Path)"
            Save-State -Round $round -ExitCode $exitCode `
                -Status "TERMINAL_CHECKPOINT_DETECTED" `
                -EventLog $eventLog -LastMessage $lastMessage -CanResume $false
            break
        }

        $replyHash = Get-TextHash -Text $lastText
        if (-not [string]::IsNullOrWhiteSpace($replyHash) -and $replyHash -eq $previousReplyHash) {
            $duplicateReplyCount++
        }
        else {
            $duplicateReplyCount = 0
        }
        $previousReplyHash = $replyHash

        if ($duplicateReplyCount -ge 1) {
            Write-Warning "Identical no-progress reply repeated twice; stopping to prevent quota burn."
            Save-State -Round $round -ExitCode $exitCode `
                -Status "DUPLICATE_REPLY_GUARD" `
                -EventLog $eventLog -LastMessage $lastMessage -CanResume $false
            break
        }

        if ($consecutiveFailures -ge 2) {
            Write-Warning "Stopping after two consecutive Codex process failures."
            Save-State -Round $round -ExitCode $exitCode `
                -Status "TWO_CONSECUTIVE_FAILURES" `
                -EventLog $eventLog -LastMessage $lastMessage -CanResume $canResume
            break
        }
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue

    Write-Stage "FAST3 GENERATION 3 LAUNCHER ENDED"
    Write-Host "Runtime logs:"
    Write-Host "  $RuntimeRoot"
    Write-Host ""
    Write-Host "Status command:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\show_fast3_generation3_status.ps1`""
    Write-Host ""
    Write-Host "Safe stop command:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\stop_fast3_generation3_agent.ps1`""
    Write-Host ""
    Write-Host "Resume only after PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\run_fast3_generation3_agent.ps1`" -Resume -MaxRounds $MaxRounds"
}
