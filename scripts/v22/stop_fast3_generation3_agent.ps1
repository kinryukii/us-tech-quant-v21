[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Runtime = "D:\us-tech-quant-results\fast3_autoresearch_generation3\agent_runtime"
$StopFile = Join-Path $Runtime "STOP_FAST3_GENERATION3_AGENT"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
Set-Content -LiteralPath $StopFile `
    -Value ("requested_at=" + (Get-Date).ToString("o")) `
    -Encoding ASCII

Write-Host "Generation 3 stop marker created:"
Write-Host "  $StopFile"
Write-Host "The launcher will stop safely before the next round."
