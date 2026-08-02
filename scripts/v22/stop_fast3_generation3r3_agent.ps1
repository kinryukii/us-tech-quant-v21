[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Runtime = "D:\us-tech-quant-results\fast3_autoresearch_generation3r3\agent_runtime"
$Stop = Join-Path $Runtime "STOP_FAST3_GENERATION3R3_AGENT"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
Set-Content -LiteralPath $Stop `
    -Value ("requested_at=" + (Get-Date).ToString("o")) `
    -Encoding ASCII

Write-Host "Generation 3R3 stop marker created:"
Write-Host "  $Stop"
