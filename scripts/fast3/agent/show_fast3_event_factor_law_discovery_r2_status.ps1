[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ExternalResultsRoot = "D:\us-tech-quant-results",
    [int]$Tail = 80
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$stateRoot = Join-Path $RepoRoot "state\fast3\agent\event_factor_law_discovery_r2"
$lockPath = Join-Path $stateRoot "active.lock.json"
$base = Join-Path $ExternalResultsRoot "fast3\agent_runs\event_factor_law_discovery_r2"

if (Test-Path -LiteralPath $lockPath) {
    Write-Host "AGENT_STATE=RUNNING_OR_STALE_LOCK"
    $lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $lock | ConvertTo-Json -Depth 5
    $localRun = [string]$lock.local_run_root
    if (Test-Path -LiteralPath $localRun -PathType Container) {
        Write-Host ""
        Write-Host "--- current R2 local artifacts ---"
        Get-ChildItem -LiteralPath $localRun -File | Sort-Object LastWriteTime | Select-Object Name,Length,LastWriteTime
        $events = Join-Path $localRun "codex_events.jsonl"
        $stderr = Join-Path $localRun "codex_stderr.log"
        if (Test-Path -LiteralPath $events -PathType Leaf) {
            Write-Host ""
            Write-Host "--- codex_events.jsonl tail ---"
            Get-Content -LiteralPath $events -Encoding UTF8 -Tail $Tail
        } elseif (Test-Path -LiteralPath $stderr -PathType Leaf) {
            Write-Host ""
            Write-Host "--- codex_stderr.log tail ---"
            Get-Content -LiteralPath $stderr -Encoding UTF8 -Tail $Tail
        }
    }
} else { Write-Host "AGENT_STATE=NO_ACTIVE_LOCK" }

if (-not (Test-Path -LiteralPath $base -PathType Container)) {
    Write-Host "NO_EXTERNAL_RESULTS_DIRECTORY=$base"
    exit 0
}
$latest = Get-ChildItem -LiteralPath $base -Directory | Sort-Object Name -Descending | Select-Object -First 1
if ($null -eq $latest) { Write-Host "NO_RUN_RECORDS=true"; exit 0 }

Write-Host "LATEST_COMPLETED_OR_SYNCED_R2_RUN=$($latest.FullName)"
foreach ($item in @(
    @{Title="launcher_summary.json"; Path=(Join-Path $latest.FullName "launcher_summary.json")},
    @{Title="fast3_event_factor_r2_summary.json"; Path=(Join-Path $latest.FullName "fast3_event_factor_r2_summary.json")},
    @{Title="FAST3_CONTROL_MATCH_AUDIT.json"; Path=(Join-Path $latest.FullName "FAST3_CONTROL_MATCH_AUDIT.json")},
    @{Title="codex_final_message.md"; Path=(Join-Path $latest.FullName "codex_final_message.md")}
)) {
    if (Test-Path -LiteralPath $item.Path -PathType Leaf) {
        Write-Host ""
        Write-Host ("--- " + $item.Title + " ---")
        Get-Content -LiteralPath $item.Path -Encoding UTF8
    }
}
