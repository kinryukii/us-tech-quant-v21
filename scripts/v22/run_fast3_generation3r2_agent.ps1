[CmdletBinding()]
param(
    [ValidateRange(1,1000)]
    [int]$MaxRounds = 64,
    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Global -ErrorAction SilentlyContinue

$RepoRoot = "D:\us-tech-quant"
$DataRoot = "D:\us-tech-quant-data"
$ResultsRoot = "D:\us-tech-quant-results"
$RunRoot = Join-Path $ResultsRoot "fast3_autoresearch_generation3r2"
$RuntimeRoot = Join-Path $RunRoot "agent_runtime"
$Authorization = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\generation\FAST3_GENERATION3R2_AUTHORIZATION.md"
$LockFile = Join-Path $RuntimeRoot "FAST3_GENERATION3R2_AGENT.lock"
$StopFile = Join-Path $RuntimeRoot "STOP_FAST3_GENERATION3R2_AGENT"
$StateFile = Join-Path $RuntimeRoot "launcher_state.json"

function Save-State {
    param([int]$Round,[int]$ExitCode,[string]$Status,[string]$Events,[string]$Last,[bool]$CanResume)
    [ordered]@{
        updated_at=(Get-Date).ToString("o")
        launcher_pid=$PID
        round=$Round
        exit_code=$ExitCode
        status=$Status
        can_resume=$CanResume
        event_log=$Events
        last_message=$Last
        output_root=$RunRoot
        broker_action_allowed=$false
        live_trading_allowed=$false
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StateFile -Encoding UTF8
}

function Find-TerminalCheckpoint {
    if (-not (Test-Path -LiteralPath $RunRoot)) { return $null }
    $file = Get-ChildItem -LiteralPath $RunRoot -Filter "generation3r2_final_checkpoint.json" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if ($null -eq $file) { return $null }
    try { $obj = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json } catch { return $null }
    $status = [string]$obj.current_status
    $resume = [string]$obj.exact_resume_command
    if ($status -match "^(PASS_|FAIL_)" -or $resume -match "^NONE_") {
        return [pscustomobject]@{Path=$file.FullName;Status=$status;Resume=$resume}
    }
    return $null
}

function Is-TerminalText {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    if ($Text -match "(?m)^FINAL_STATUS=(PASS_|FAIL_)") { return $true }
    if ($Text -match "NONE_FAST3_GENERATION3R2_RESEARCH_STOPPED") { return $true }
    return $false
}

if (-not (Test-Path -LiteralPath $RepoRoot)) { throw "Repository missing: $RepoRoot" }
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) { throw "Git metadata missing." }
if (-not (Test-Path -LiteralPath $DataRoot)) { throw "Data root missing: $DataRoot" }
if (-not (Test-Path -LiteralPath $Authorization)) { throw "Authorization missing: $Authorization" }
if ($null -eq (Get-Command codex -ErrorAction SilentlyContinue)) { throw "Codex CLI not found." }

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $LockFile) {
    $old = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    if ($old -match "^\d+$") {
        $proc = Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue
        if ($null -ne $proc) { throw "Generation 3R2 already running. PID=$old" }
    }
    Remove-Item -LiteralPath $LockFile -Force
}

Set-Content -LiteralPath $LockFile -Value $PID -Encoding ASCII -NoNewline
Set-Location -LiteralPath $RepoRoot

$initial = @"
Read FAST3_GENERATION3R2_AUTHORIZATION.md completely before doing anything.

This is a new, separately authorized Generation 3R2. Generation 1, 2, and 3
remain immutable historical evidence, but their terminal checkpoints do not
prohibit this new generation.

Use the existing local three-year minute data. Do not wait for more data and do
not redownload the three-year history unless a real local coverage audit shows
missing partitions.

Begin actual implementation and execution now:
- audit six-symbol common coverage;
- freeze the exact 2023-03 through 2026-07 contract;
- implement three-layer opportunity/direction/execution labels;
- implement PIT feature families;
- run nested chronological Development walk-forward;
- run at least 100 continuous randomized as-of windows;
- freeze finalists;
- open Validation once;
- open Confirmation once only if legal;
- materialize complete output contracts and checkpoint.

Treat D:\us-tech-quant-data as read-only.
Write only under D:\us-tech-quant-results\fast3_autoresearch_generation3r2.
Never create broker orders.
Preserve unrelated user work.
Do not merely summarize the authorization.

A terminal response must contain an exact FINAL_STATUS= line. A resource-limit
response must use FINAL_STATUS=PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED and
include a real exact resume command.
"@

$continuation = @"
Continue FAST3 Generation 3R2 from its actual latest 3R2 checkpoint.

Read FAST3_GENERATION3R2_AUTHORIZATION.md, the split contract, feature/label
contracts, candidate registry, completed commands, tests, metrics, rejected
candidates, and exact resume action.

Do not reopen Generation 1, 2, or 3. Do not repeat completed experiments. Do not
retune after Validation. Keep Confirmation unread unless one frozen champion
passes every Validation gate.

Execute the next legal high-information-value action and save a recoverable
checkpoint. A terminal response must print an exact FINAL_STATUS= line and a
terminal checkpoint with NONE_FAST3_GENERATION3R2_RESEARCH_STOPPED.
"@

$canResume = [bool]$Resume
$consecutiveFailures = 0

try {
    for ($round=1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFile) {
            Save-State $round 0 "STOP_FILE_DETECTED" "" "" $canResume
            Write-Host "STOP file detected."
            break
        }

        $terminal = Find-TerminalCheckpoint
        if ($null -ne $terminal) {
            Write-Host "Terminal checkpoint already exists:"
            Write-Host "  $($terminal.Path)"
            Write-Host "  status=$($terminal.Status)"
            Save-State $round 0 "TERMINAL_CHECKPOINT_DETECTED" "" "" $false
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $tag = "gen3r2_round_{0:D3}_{1}" -f $round,$stamp
        $events = Join-Path $RuntimeRoot "$tag.events.jsonl"
        $stderr = Join-Path $RuntimeRoot "$tag.stderr.log"
        $last = Join-Path $RuntimeRoot "$tag.last_message.md"

        Write-Host ""
        Write-Host "============================================================"
        Write-Host "FAST3 GENERATION 3R2 ROUND $round / $MaxRounds"
        Write-Host "============================================================"
        Write-Host "Events     : $events"
        Write-Host "Last reply : $last"

        $args = @(
            "exec",
            "-C",$RepoRoot,
            "--sandbox","workspace-write",
            "--add-dir",$ResultsRoot,
            "-c",'approval_policy="never"',
            "-c","sandbox_workspace_write.network_access=false",
            "--json",
            "--output-last-message",$last
        )

        if ($canResume) {
            & codex @args "resume" "--last" $continuation 2>> $stderr | Tee-Object -FilePath $events
        } else {
            & codex @args $initial 2>> $stderr | Tee-Object -FilePath $events
        }

        $exit = $LASTEXITCODE
        Write-Host "CODEX_EXIT_CODE=$exit"

        $text = ""
        if (Test-Path -LiteralPath $last) { $text = Get-Content -LiteralPath $last -Raw }

        if ($exit -eq 0) {
            $consecutiveFailures = 0
            $canResume = $true
        } else {
            $consecutiveFailures++
        }

        Save-State $round $exit $(if($exit -eq 0){"ROUND_COMPLETED"}else{"ROUND_FAILED"}) $events $last $canResume

        if (Is-TerminalText $text) {
            Write-Host "Generation 3R2 terminal response detected."
            Save-State $round $exit "TERMINAL_RESPONSE_DETECTED" $events $last $false
            break
        }

        $terminal = Find-TerminalCheckpoint
        if ($null -ne $terminal) {
            Write-Host "Generation 3R2 terminal checkpoint detected."
            Save-State $round $exit "TERMINAL_CHECKPOINT_DETECTED" $events $last $false
            break
        }

        if ($consecutiveFailures -ge 2) {
            Write-Warning "Stopped after two consecutive Codex process failures."
            Save-State $round $exit "TWO_CONSECUTIVE_FAILURES" $events $last $canResume
            break
        }
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Generation 3R2 runtime logs:"
    Write-Host "  $RuntimeRoot"
    Write-Host ""
    Write-Host "Status:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\show_fast3_generation3r2_status.ps1`""
}
