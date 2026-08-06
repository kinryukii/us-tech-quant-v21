[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ExternalResultsRoot = "D:\us-tech-quant-results",
    [int]$Tail = 80
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$state = Join-Path $RepoRoot "state\fast3\agent\r3_economic_integrity_audit"
$lock = Join-Path $state "active.lock.json"
$base = Join-Path $ExternalResultsRoot "fast3\agent_runs\r3_economic_integrity_audit"

if (Test-Path -LiteralPath $lock -PathType Leaf) {
    Write-Host "AUDIT_STATE=RUNNING_OR_STALE_LOCK"
    $x = Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json
    $x | ConvertTo-Json -Depth 5
    if (Test-Path -LiteralPath $x.run_root -PathType Container) {
        $events = Join-Path $x.run_root "codex_events.jsonl"
        if (Test-Path -LiteralPath $events -PathType Leaf) {
            Write-Host "--- events tail ---"
            Get-Content -LiteralPath $events -Encoding UTF8 -Tail $Tail
        }
    }
} else {
    Write-Host "AUDIT_STATE=NO_ACTIVE_LOCK"
}

if (-not (Test-Path -LiteralPath $base -PathType Container)) {
    Write-Host "NO_AUDIT_RESULTS=$base"
    exit 0
}
$latest = Get-ChildItem -LiteralPath $base -Directory | Sort-Object Name -Descending | Select-Object -First 1
if ($null -eq $latest) { Write-Host "NO_AUDIT_RUNS=true"; exit 0 }

Write-Host "LATEST_AUDIT_RUN=$($latest.FullName)"
foreach ($name in @(
    "launcher_summary.json",
    "fast3_r3_post_audit_summary.json",
    "FAST3_R3_DEDUP_AUDIT.json",
    "FAST3_R3_TARGET_HIT_TIMING_AUDIT.json",
    "FAST3_R3_EXECUTION_STRESS_AUDIT.json",
    "FAST3_R3_CLUSTERED_UNCERTAINTY_AUDIT.json",
    "FAST3_R3_POST_AUDIT_REPORT.md",
    "codex_final_message.md"
)) {
    $p = Join-Path $latest.FullName $name
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        Write-Host ""
        Write-Host "--- $name ---"
        Get-Content -LiteralPath $p -Encoding UTF8
    }
}
