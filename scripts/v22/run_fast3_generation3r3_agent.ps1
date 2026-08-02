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
$RunRoot = Join-Path $ResultsRoot "fast3_autoresearch_generation3r3"
$RuntimeRoot = Join-Path $RunRoot "agent_runtime"
$Authorization = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\generation\FAST3_GENERATION3R3_AUTHORIZATION.md"
$LockFile = Join-Path $RuntimeRoot "FAST3_GENERATION3R3_AGENT.lock"
$StopFile = Join-Path $RuntimeRoot "STOP_FAST3_GENERATION3R3_AGENT"
$StateFile = Join-Path $RuntimeRoot "launcher_state.json"

$env:LOKY_MAX_CPU_COUNT = [Environment]::ProcessorCount.ToString()
$env:PYTHONUNBUFFERED = "1"

function Write-Stage {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Text
    Write-Host "============================================================"
}

function Save-State {
    param(
        [int]$Round,
        [int]$ExitCode,
        [string]$Status,
        [string]$Events,
        [string]$Last,
        [bool]$CanResume
    )
    [ordered]@{
        updated_at = (Get-Date).ToString("o")
        launcher_pid = $PID
        round = $Round
        exit_code = $ExitCode
        status = $Status
        can_resume = $CanResume
        event_log = $Events
        last_message = $Last
        output_root = $RunRoot
        broker_action_allowed = $false
        live_trading_allowed = $false
    } | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $StateFile -Encoding UTF8
}

function Find-TerminalCheckpoint {
    if (-not (Test-Path -LiteralPath $RunRoot)) {
        return $null
    }

    $file = Get-ChildItem -LiteralPath $RunRoot `
        -Filter "generation3r3_final_checkpoint.json" `
        -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if ($null -eq $file) {
        return $null
    }

    try {
        $obj = Get-Content -LiteralPath $file.FullName -Raw |
            ConvertFrom-Json
    }
    catch {
        return $null
    }

    $status = [string]$obj.current_status
    $resume = [string]$obj.exact_resume_command

    if ($status -match "^(PASS_|FAIL_)" -or $resume -match "^NONE_") {
        return [pscustomobject]@{
            Path = $file.FullName
            Status = $status
            Resume = $resume
        }
    }

    return $null
}

function Test-TerminalText {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $false
    }

    if ($Text -match "(?m)^FINAL_STATUS=(PASS_|FAIL_)") {
        return $true
    }

    if ($Text -match "NONE_FAST3_GENERATION3R3_RESEARCH_STOPPED") {
        return $true
    }

    return $false
}

function Get-ReplyHash {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repository missing: $RepoRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git"))) {
    throw "Git metadata missing."
}
if (-not (Test-Path -LiteralPath $DataRoot)) {
    throw "Data root missing: $DataRoot"
}
if (-not (Test-Path -LiteralPath $Authorization)) {
    throw "Authorization missing: $Authorization"
}
if ($null -eq (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI not found."
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $LockFile) {
    $old = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    if ($old -match "^\d+$") {
        $proc = Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            throw "Generation 3R3 is already running. PID=$old"
        }
    }
    Remove-Item -LiteralPath $LockFile -Force
}

Set-Content -LiteralPath $LockFile -Value $PID -Encoding ASCII -NoNewline
Set-Location -LiteralPath $RepoRoot

$initialPrompt = @"
Read FAST3_GENERATION3R3_AUTHORIZATION.md completely before acting.

This is a separately authorized Generation 3R3. Prior generations remain
immutable historical evidence but do not block this new Development-only
diagnostic and repair program.

Start actual work now. Reuse the relevant Generation 3R2 implementation and
artifacts instead of rebuilding everything.

Immediate priorities:
1. freeze the 3R3 contract;
2. instrument the complete C1-C6 sample funnel;
3. reproduce and explain why C3/C4/C5/C6 produced zero trades;
4. distinguish implementation defects from valid threshold/model behavior;
5. run compact Development-only staged repairs;
6. run nested chronological walk-forward and at least 100 continuous as-of
   windows;
7. freeze finalists before opening Validation once;
8. preserve Confirmation zero-read until legal.

Use targeted commands and concise summaries. Do not dump large files or logs.
Do not recursively reread the whole repository each turn. Do not create
unnecessary version/file/test proliferation.

Treat D:\us-tech-quant-data as read-only.
Write only under:
D:\us-tech-quant-results\fast3_autoresearch_generation3r3

Keep all broker and live-trading permissions false.

A terminal response must contain an exact FINAL_STATUS= line. A resource-limit
response must use FINAL_STATUS=PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED and
include a real exact resume command.

Do not merely propose a plan. Implement, test, execute, register, and checkpoint.
"@

$continuePrompt = @"
Continue FAST3 Generation 3R3 from its actual latest 3R3 checkpoint.

Read only the relevant authorization, checkpoint, registry, concise metric
summaries, and the exact previous command/result. Do not reread large immutable
logs or the whole repository.

Execute the next distinct legal high-information action:
- complete funnel instrumentation;
- fix a verified implementation defect;
- run one registered Development-only threshold/calibration/model/overlap
  hypothesis;
- run required focused tests and actual backtest;
- update registry and checkpoint;
- freeze finalists and open Validation once only when legal.

Do not repeat completed experiments, retune on Validation, read Confirmation
early, lower gates after seeing results, or restate a terminal checkpoint.

A terminal response must print an exact FINAL_STATUS= line and write a terminal
checkpoint with:
NONE_FAST3_GENERATION3R3_RESEARCH_STOPPED
"@

$canResume = [bool]$Resume
$consecutiveFailures = 0
$lastHash = ""
$duplicateCount = 0

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFile) {
            Write-Host "STOP marker detected."
            Save-State $round 0 "STOP_FILE_DETECTED" "" "" $canResume
            break
        }

        $terminal = Find-TerminalCheckpoint
        if ($null -ne $terminal) {
            Write-Host "Terminal Generation 3R3 checkpoint already exists:"
            Write-Host "  $($terminal.Path)"
            Write-Host "  status=$($terminal.Status)"
            Save-State $round 0 "TERMINAL_CHECKPOINT_DETECTED" "" "" $false
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $tag = "gen3r3_round_{0:D3}_{1}" -f $round, $stamp
        $events = Join-Path $RuntimeRoot "$tag.events.jsonl"
        $stderr = Join-Path $RuntimeRoot "$tag.stderr.log"
        $last = Join-Path $RuntimeRoot "$tag.last_message.md"

        Write-Stage "FAST3 GENERATION 3R3 ROUND $round / $MaxRounds"
        Write-Host "Events     : $events"
        Write-Host "Last reply : $last"

        $args = @(
            "exec",
            "-C", $RepoRoot,
            "--sandbox", "workspace-write",
            "--add-dir", $ResultsRoot,
            "-c", 'approval_policy="never"',
            "-c", "sandbox_workspace_write.network_access=false",
            "--json",
            "--output-last-message", $last
        )

        if ($canResume) {
            & codex @args "resume" "--last" $continuePrompt `
                2>> $stderr |
                Tee-Object -FilePath $events
        }
        else {
            & codex @args $initialPrompt `
                2>> $stderr |
                Tee-Object -FilePath $events
        }

        $exitCode = $LASTEXITCODE
        Write-Host "CODEX_EXIT_CODE=$exitCode"

        $text = ""
        if (Test-Path -LiteralPath $last) {
            $text = Get-Content -LiteralPath $last -Raw
        }

        if ($exitCode -eq 0) {
            $consecutiveFailures = 0
            $canResume = $true
        }
        else {
            $consecutiveFailures++
        }

        Save-State $round $exitCode `
            $(if ($exitCode -eq 0) { "ROUND_COMPLETED" } else { "ROUND_FAILED" }) `
            $events $last $canResume

        if (Test-TerminalText $text) {
            Write-Host "Generation 3R3 terminal response detected."
            Save-State $round $exitCode "TERMINAL_RESPONSE_DETECTED" `
                $events $last $false
            break
        }

        $terminal = Find-TerminalCheckpoint
        if ($null -ne $terminal) {
            Write-Host "Generation 3R3 terminal checkpoint detected."
            Save-State $round $exitCode "TERMINAL_CHECKPOINT_DETECTED" `
                $events $last $false
            break
        }

        $hash = Get-ReplyHash $text
        if (-not [string]::IsNullOrWhiteSpace($hash) -and $hash -eq $lastHash) {
            $duplicateCount++
        }
        else {
            $duplicateCount = 0
        }
        $lastHash = $hash

        if ($duplicateCount -ge 1) {
            Write-Warning "Identical no-progress response repeated; stopping."
            Save-State $round $exitCode "DUPLICATE_REPLY_GUARD" `
                $events $last $false
            break
        }

        if ($consecutiveFailures -ge 2) {
            Write-Warning "Two consecutive Codex process failures; stopping."
            Save-State $round $exitCode "TWO_CONSECUTIVE_FAILURES" `
                $events $last $canResume
            break
        }
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue

    Write-Stage "FAST3 GENERATION 3R3 LAUNCHER ENDED"
    Write-Host "Runtime logs:"
    Write-Host "  $RuntimeRoot"
    Write-Host ""
    Write-Host "Status:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\show_fast3_generation3r3_status.ps1`""
    Write-Host ""
    Write-Host "Safe stop:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\stop_fast3_generation3r3_agent.ps1`""
    Write-Host ""
    Write-Host "Resume only after PARTIAL_RESOURCE_LIMIT_CHECKPOINT_SAVED:"
    Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\v22\run_fast3_generation3r3_agent.ps1`" -Resume -MaxRounds $MaxRounds"
}
