[CmdletBinding()]
param(
    [ValidateRange(1, 1000)]
    [int]$MaxRounds = 64
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$RepoRoot    = "D:\us-tech-quant"
$ResultsRoot = "D:\us-tech-quant-results"
$Gen2Root    = Join-Path $ResultsRoot "fast3_autoresearch_generation2"
$RuntimeRoot = Join-Path $Gen2Root "agent_runtime"
$PromptPath  = Join-Path $RepoRoot "fast3\docs\authorizations\legacy\generation\FAST3_GENERATION2_AUTHORIZATION.md"
$StopFile    = Join-Path $RuntimeRoot "STOP_GENERATION2_AGENT"
$LockFile    = Join-Path $RuntimeRoot "GENERATION2_AGENT.lock"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $LockFile) {
    $oldPid = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    if ($oldPid -match "^\d+$") {
        $existing = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            throw "Generation 2 agent is already running. PID=$oldPid"
        }
    }
    Remove-Item -LiteralPath $LockFile -Force
}

Set-Content -LiteralPath $LockFile -Value $PID -Encoding ASCII
Set-Location -LiteralPath $RepoRoot

$continuePrompt = @"
Continue FAST3 Generation 2 from its actual Generation 2 checkpoint and registry.

Read FAST3_GENERATION2_AUTHORIZATION.md first.

Do not reopen or resume the rejected Generation 1 research chain. Do not repeat
a completed or rejected experiment without new evidence.

Execute the next highest-information-value permitted Generation 2 iteration:
one pre-registered hypothesis, minimum implementation change, required tests,
chronological randomized OOS evaluation, robustness comparison, decision,
registry update and recoverable checkpoint.

If Generation 2 has a genuine terminal state, print an exact line beginning:
FINAL_STATUS=

If there is no legal next experiment, print:
FINAL_STATUS=FAIL_NO_ROBUST_EDGE

If independent data are insufficient, print:
FINAL_STATUS=FAIL_INSUFFICIENT_UNEXPOSED_DATA_FOR_GENERATION2
"@

$terminalPattern = '(?m)^FINAL_STATUS=(PASS_|FAIL_|PARTIAL_)'

try {
    for ($round = 1; $round -le $MaxRounds; $round++) {
        if (Test-Path -LiteralPath $StopFile) {
            Write-Host "Generation 2 STOP file detected."
            break
        }

        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $tag = "gen2_round_{0:D3}_{1}" -f $round, $stamp
        $events = Join-Path $RuntimeRoot "$tag.events.jsonl"
        $stderr = Join-Path $RuntimeRoot "$tag.stderr.log"
        $last   = Join-Path $RuntimeRoot "$tag.last_message.md"

        Write-Host ""
        Write-Host "============================================================"
        Write-Host "FAST3 GENERATION 2 ROUND $round / $MaxRounds"
        Write-Host "============================================================"
        Write-Host "Events     : $events"
        Write-Host "Last reply : $last"

        $common = @(
            "exec",
            "-C", $RepoRoot,
            "--sandbox", "workspace-write",
            "--add-dir", $ResultsRoot,
            "-c", 'approval_policy="never"',
            "-c", "sandbox_workspace_write.network_access=false",
            "--json",
            "--output-last-message", $last
        )

        if ($round -eq 1) {
            $initialPrompt = Get-Content -LiteralPath $PromptPath -Raw
            & codex @common $initialPrompt 2>> $stderr |
                Tee-Object -FilePath $events
        }
        else {
            & codex @common "resume" "--last" $continuePrompt 2>> $stderr |
                Tee-Object -FilePath $events
        }

        $exitCode = $LASTEXITCODE
        Write-Host "CODEX_EXIT_CODE=$exitCode"

        if ($exitCode -ne 0) {
            Write-Warning "Codex process failed. Generation 2 stopped."
            break
        }

        if (Test-Path -LiteralPath $last) {
            $text = Get-Content -LiteralPath $last -Raw

            if ($text -match $terminalPattern) {
                Write-Host "Generation 2 terminal FINAL_STATUS detected."
                break
            }

            if (
                $text -match 'NONE_FAST3_RESEARCH_STOPPED' -or
                $text -match 'No permitted continuation exists' -or
                $text -match 'no valid continuation exists'
            ) {
                Write-Warning "No-op/old-chain response detected; stopping instead of burning rounds."
                break
            }
        }
    }
}
finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Generation 2 runtime logs:"
    Write-Host "  $RuntimeRoot"
}
