[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RuntimeRoot = "D:\us-tech-quant-results\fast3_autoresearch\agent_runtime"
$StopFile = Join-Path $RuntimeRoot "STOP_FAST3_AGENT"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
New-Item -ItemType File -Force -Path $StopFile | Out-Null

Write-Host "STOP request created:"
Write-Host "  $StopFile"
Write-Host ""
Write-Host "The current Codex round is not force-killed."
Write-Host "The launcher will stop safely before starting the next round."
