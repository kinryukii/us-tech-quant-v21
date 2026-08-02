[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RuntimeRoot = "D:\us-tech-quant-results\fast3_v22_086_overnight_strategy_freeze\agent_runtime"
$StopFlag = Join-Path $RuntimeRoot "STOP_REQUESTED.flag"
New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
Set-Content -LiteralPath $StopFlag -Value ("SAFE_STOP_REQUESTED_AT=" + (Get-Date).ToString("o")) -Encoding UTF8

Write-Host "FINAL_STATUS=SAFE_STOP_REQUESTED"
Write-Host "STOP_FLAG=$StopFlag"
Write-Host "The launcher will stop after the current Codex round finishes."
