[CmdletBinding()]
param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$ExternalResultsRoot = "D:\us-tech-quant-results",
    [int]$Tail = 80
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$stateRoot = Join-Path $RepoRoot "state\fast3\agent\minimal_empirical_validation"
$lockPath = Join-Path $stateRoot "active.lock.json"
$base = Join-Path $ExternalResultsRoot "fast3\agent_runs\minimal_empirical_validation"

if (Test-Path -LiteralPath $lockPath) {
    Write-Host "AGENT_STATE=RUNNING_OR_STALE_LOCK"
    Get-Content -LiteralPath $lockPath -Encoding UTF8
} else {
    Write-Host "AGENT_STATE=NO_ACTIVE_LOCK"
}

if (-not (Test-Path -LiteralPath $base -PathType Container)) {
    Write-Host "NO_EXTERNAL_RESULTS_DIRECTORY=$base"
    exit 0
}

$latest = Get-ChildItem -LiteralPath $base -Directory | Sort-Object Name -Descending | Select-Object -First 1
if ($null -eq $latest) {
    Write-Host "NO_RUN_RECORDS=true"
    exit 0
}

Write-Host "LATEST_RUN=$($latest.FullName)"
$summary = Join-Path $latest.FullName "launcher_summary.json"
$final = Join-Path $latest.FullName "codex_final_message.md"
$stderr = Join-Path $latest.FullName "codex_stderr.log"

if (Test-Path -LiteralPath $summary) {
    Write-Host ""
    Write-Host "--- launcher_summary.json ---"
    Get-Content -LiteralPath $summary -Encoding UTF8
}
if (Test-Path -LiteralPath $final) {
    Write-Host ""
    Write-Host "--- codex_final_message.md ---"
    Get-Content -LiteralPath $final -Encoding UTF8
} elseif (Test-Path -LiteralPath $stderr) {
    Write-Host ""
    Write-Host "--- codex_stderr.log tail ---"
    Get-Content -LiteralPath $stderr -Encoding UTF8 -Tail $Tail
}
