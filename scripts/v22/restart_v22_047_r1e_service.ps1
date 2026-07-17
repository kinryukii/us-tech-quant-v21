[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
& (Join-Path $RepoRoot "scripts\v22\stop_v22_047_r1e_service.ps1") -RepoRoot $RepoRoot
Start-Sleep -Seconds 2
& (Join-Path $RepoRoot "scripts\v22\start_v22_047_r1e_service.ps1") -RepoRoot $RepoRoot
Write-Output "restart_status=PASS_R1E_RESTART_REQUESTED"

