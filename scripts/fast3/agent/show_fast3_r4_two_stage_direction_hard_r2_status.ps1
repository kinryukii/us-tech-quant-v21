[CmdletBinding()]
param(
    [string]$ResultsRoot = "D:\us-tech-quant-results",
    [int]$Tail = 80
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$lock = Join-Path $ResultsRoot "runtime\fast3\r4_two_stage_direction\state\active_hard_r2.lock.json"
if (Test-Path -LiteralPath $lock -PathType Leaf) {
    Write-Host "R4_HARD_AGENT_STATE=RUNNING_OR_STALE_LOCK"
    $state = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json
    $state | ConvertTo-Json -Depth 8
    foreach ($name in @(
        "implementation_codex_stdout.jsonl",
        "implementation_codex_stderr.log",
        "pytest_stdout.log",
        "pytest_stderr.log",
        "research_stdout.log",
        "research_stderr.log"
    )) {
        $p = Join-Path $state.runtime_root $name
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            Write-Host ""
            Write-Host "--- $name ---"
            Get-Content -LiteralPath $p -Encoding UTF8 -Tail $Tail
        }
    }
} else {
    Write-Host "R4_HARD_AGENT_STATE=NO_ACTIVE_LOCK"
}

$frozenBase = Join-Path $ResultsRoot "frozen\fast3\r4_two_stage_direction"
if (-not (Test-Path -LiteralPath $frozenBase -PathType Container)) {
    Write-Host "NO_R4_FROZEN_RESULTS=true"
    exit 0
}
$latest = Get-ChildItem -LiteralPath $frozenBase -Directory |
    Sort-Object Name -Descending | Select-Object -First 1
if ($null -eq $latest) {
    Write-Host "NO_R4_FROZEN_RUNS=true"
    exit 0
}
Write-Host "LATEST_R4_FROZEN_RUN=$($latest.FullName)"

foreach ($name in @(
    "FAST3_R4_HARD_STORAGE_LAUNCHER_SUMMARY.json",
    "FAST3_R4_HARD_STORAGE_LAUNCHER_AUDIT.json",
    "fast3_r4_two_stage_direction_summary.json",
    "FAST3_R4_DEV_COMPARISON.json",
    "FAST3_R4_INTERNAL_HOLDOUT_COMPARISON.json",
    "FAST3_R4_PROSPECTIVE_FREEZE.json",
    "FAST3_R4_ARCHIVE_POINTER.json",
    "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md"
)) {
    $p = Join-Path $latest.FullName $name
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        Write-Host ""
        Write-Host "--- $name ---"
        Get-Content -LiteralPath $p -Encoding UTF8
    }
}
