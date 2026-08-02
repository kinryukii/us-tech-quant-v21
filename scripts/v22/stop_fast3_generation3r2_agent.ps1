[CmdletBinding()]
param()

$Runtime="D:\us-tech-quant-results\fast3_autoresearch_generation3r2\agent_runtime"
$Stop=Join-Path $Runtime "STOP_FAST3_GENERATION3R2_AGENT"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
Set-Content -LiteralPath $Stop -Value ("requested_at="+(Get-Date).ToString("o")) -Encoding ASCII
Write-Host "Stop marker created: $Stop"
