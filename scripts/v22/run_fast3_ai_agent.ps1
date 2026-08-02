[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$MaxRounds = 64,

    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = "D:\us-tech-quant"
$DataRoot = "D:\us-tech-quant-data"
$ResultsRoot = "D:\us-tech-quant-results"

$RuntimeRoot = Join-Path $ResultsRoot "fast3_autoresearch\agent_runtime"
$SpecPath = Join-Path $RepoRoot "docs\FAST3_AUTORESEARCH_AGENT_SPEC.md"
$StopFile = Join-Path $RuntimeRoot "STOP_FAST3_AGENT"
$LockFile = Join-Path $RuntimeRoot "FAST3_AGENT.lock"
$GitSnapshot = Join-Path $RuntimeRoot "git_status_before_launch.txt"
$LauncherState = Join-Path $RuntimeRoot "launcher_state.json"

function Write-Stage {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Text
    Write-Host "============================================================"
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description does not exist: $Path"
    }
}

function Test-TerminalStatus {
    param([Parameter(Mandatory)][string]$Text)

    # PASS_CANDIDATE_READY_FOR_CONFIRMATION and
    # PASS_ROBUST_DIRECTIONAL_EDGE_FOUND are intentionally not terminal here.
    # The outer loop allows the agent to continue into the permitted
    # confirmation/prospective-shadow preparation stages.
    $terminalStatuses = @(
        "PASS_RESEARCH_PIPELINE_COMPLETE_NO_EDGE_CONFIRMED",
        "PASS_CONFIRMATION_ACCEPTED_READY_FOR_PROSPECTIVE_SHADOW",
        "FAIL_DATA_CONTRACT",
        "FAIL_LEAKAGE_DETECTED",
        "FAIL_OVERFITTING_RISK",
        "FAIL_NO_ROBUST_EDGE",
        "FAIL_COST_SENSITIVITY",
        "FAIL_DELAY_SENSITIVITY",
        "FAIL_CONFIRMATION"
    )

    foreach ($status in $terminalStatuses) {
        if ($Text -match [regex]::Escape("FINAL_STATUS=$status")) {
            return $true
        }
    }
    return $false
}

function Save-LauncherState {
    param(
        [int]$Round,
        [int]$ExitCode,
        [bool]$CanResume,
        [string]$LastMessagePath,
        [string]$EventLogPath,
        [string]$Status
    )

    $state = [ordered]@{
        updated_at = (Get-Date).ToString("o")
        launcher_pid = $PID
        round = $Round
        exit_code = $ExitCode
        can_resume = $CanResume
        status = $Status
        last_message_path = $LastMessagePath
        event_log_path = $EventLogPath
        repository = $RepoRoot
        data_root = $DataRoot
        results_root = $ResultsRoot
        broker_action_allowed = $false
    }

    $state |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $LauncherState -Encoding UTF8
}

Assert-PathExists -Path $RepoRoot -Description "Repository"
Assert-PathExists -Path (Join-Path $RepoRoot ".git") -Description "Git metadata"
Assert-PathExists -Path $DataRoot -Description "Data root"
Assert-PathExists -Path $SpecPath -Description "FAST3 agent specification"

$codexCommand = Get-Command codex -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) {
    throw "Codex CLI was not found in PATH. Re-run INSTALL_AND_RUN.ps1."
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

# Avoid starting two autonomous agents against the same working tree.
if (Test-Path -LiteralPath $LockFile) {
    $oldPidText = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    if ($oldPidText -match '^\d+$') {
        $existing = Get-Process -Id ([int]$oldPidText) -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            throw "Another FAST3 agent is already running. PID=$oldPidText"
        }
    }
    Remove-Item -LiteralPath $LockFile -Force
}

Set-Content -LiteralPath $LockFile -Value $PID -NoNewline -Encoding ASCII
Set-Location -LiteralPath $RepoRoot

& git status --short |
    Out-File -LiteralPath $GitSnapshot -Encoding UTF8

$initialPrompt = @"
Before taking any implementation action, fully read this authoritative contract:

$SpecPath

Begin actual FAST3 implementation and execution immediately.

Required behavior:
- Inspect Git status, existing FAST3/V22 code, reusable components, current
  checkpoints, registries, champions, rejected candidates and known failures.
- Treat D:\us-tech-quant-data as read-only. Never modify, rewrite, move, delete,
  rename, repartition or copy canonical source data.
- Preserve unrelated and uncommitted user work. Never run git reset, git clean,
  checkout-overwrite, force restore, destructive cleanup or mass deletion.
- Write research outputs only under
  D:\us-tech-quant-results\fast3_autoresearch.
- Never create or send real orders. Keep broker_action_allowed=False,
  live_trading_allowed=False, official_adoption_allowed=False and
  research_only=True.
- Do not merely generate another design document. Implement the highest-value
  permitted next step, run real tests and chronological randomized OOS
  research, record truthful evidence, and save a complete recoverable
  checkpoint before ending this turn.
- Never fabricate, infer, beautify or silently repair missing results.
- If a command cannot run, record the exact command, real error, current state,
  and exact resume action.
"@

$continuePrompt = @"
Continue FAST3 autonomous research from the actual repository state and latest
saved checkpoint.

First re-read:
- docs/FAST3_AUTORESEARCH_AGENT_SPEC.md
- latest checkpoint
- experiment registry
- current champion
- rejected candidates
- known failures
- last executed command and its real exit status

Do not only summarize previous work. Execute the next highest-information-value
permitted iteration: pre-register one falsifiable hypothesis, make the minimum
necessary implementation change, run required tests, run chronological
randomized OOS evaluation and stress tests appropriate for the current stage,
compare fairly with the frozen champion, accept/reject/inconclusive, update the
registry, and save a complete checkpoint.

Preserve all PIT, no-leakage, confirmation isolation, no-live-order,
canonical-data-read-only and truthful-reporting requirements. Never run git
reset or git clean. Continue until this turn reaches a genuine terminal
condition or an execution/resource boundary.
"@

$canResume = [bool]$Resume
$consecutiveFailures = 0

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFile) {
            Write-Host "STOP file detected. The launcher will not start another round."
            Save-LauncherState -Round $round -ExitCode 0 -CanResume $canResume `
                -LastMessagePath "" -EventLogPath "" -Status "STOP_FILE_DETECTED"
            break
        }

        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $roundTag = "round_{0:D3}_{1}" -f $round, $timestamp
        $EventLog = Join-Path $RuntimeRoot "$roundTag.events.jsonl"
        $StderrLog = Join-Path $RuntimeRoot "$roundTag.stderr.log"
        $LastMessage = Join-Path $RuntimeRoot "$roundTag.last_message.md"

        Write-Stage "FAST3 AUTORESEARCH ROUND $round / $MaxRounds"
        Write-Host "Repository : $RepoRoot"
        Write-Host "Results    : $ResultsRoot"
        Write-Host "Events     : $EventLog"
        Write-Host "Last reply : $LastMessage"

        $commonArgs = @(
            "exec",
            "-C", $RepoRoot,
            "--sandbox", "workspace-write",
            "-c", 'approval_policy="never"',
            "--add-dir", $ResultsRoot,
            "-c", "sandbox_workspace_write.network_access=false",
            "--json",
            "--output-last-message", $LastMessage
        )

        if ($canResume) {
            & codex @commonArgs "resume" "--last" $continuePrompt `
                2>> $StderrLog |
                Tee-Object -FilePath $EventLog
        }
        else {
            & codex @commonArgs $initialPrompt `
                2>> $StderrLog |
                Tee-Object -FilePath $EventLog
        }

        $exitCode = $LASTEXITCODE
        Write-Host ""
        Write-Host "CODEX_EXIT_CODE=$exitCode"

        if ($exitCode -eq 0) {
            $consecutiveFailures = 0
            $canResume = $true
        }
        else {
            $consecutiveFailures++
            Write-Warning "Codex process failed. Consecutive failures=$consecutiveFailures"
        }

        $lastText = ""
        if (Test-Path -LiteralPath $LastMessage) {
            $lastText = Get-Content -LiteralPath $LastMessage -Raw
        }

        $stateStatus = if ($exitCode -eq 0) { "ROUND_COMPLETED" } else { "ROUND_FAILED" }
        Save-LauncherState -Round $round -ExitCode $exitCode -CanResume $canResume `
            -LastMessagePath $LastMessage -EventLogPath $EventLog -Status $stateStatus

        if (-not [string]::IsNullOrWhiteSpace($lastText)) {
            if (Test-TerminalStatus -Text $lastText) {
                Write-Host "A genuine terminal FINAL_STATUS was reported."
                Save-LauncherState -Round $round -ExitCode $exitCode `
                    -CanResume $canResume -LastMessagePath $LastMessage `
                    -EventLogPath $EventLog -Status "TERMINAL_STATUS_REPORTED"
                break
            }
        }

        # PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED is deliberately resumable.
        if ($consecutiveFailures -ge 3) {
            Write-Warning "Stopping after three consecutive Codex process failures."
            Save-LauncherState -Round $round -ExitCode $exitCode `
                -CanResume $canResume -LastMessagePath $LastMessage `
                -EventLogPath $EventLog -Status "THREE_CONSECUTIVE_FAILURES"
            break
        }
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue

    Write-Stage "FAST3 AGENT LAUNCHER ENDED"
    Write-Host "Runtime logs:"
    Write-Host "  $RuntimeRoot"
    Write-Host ""
    Write-Host "Resume command:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\run_fast3_ai_agent.ps1`" -Resume -MaxRounds $MaxRounds"
    Write-Host ""
    Write-Host "Status command:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\show_fast3_ai_agent_status.ps1`""
    Write-Host ""
    Write-Host "Stop safely between rounds:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\stop_fast3_ai_agent.ps1`""
}
