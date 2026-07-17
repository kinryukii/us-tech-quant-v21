[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1e_windows_service_hardening.py"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
$Runtime = Join-Path $Output "runtime"
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$Info = New-Object System.Diagnostics.ProcessStartInfo
$Info.FileName = $Python
$Info.Arguments = "`"$Main`" ui --repo-root `"$RepoRoot`""
$Info.WorkingDirectory = $RepoRoot
$Info.UseShellExecute = $true
$Info.WindowStyle = "Hidden"
$Process = [System.Diagnostics.Process]::Start($Info)
Set-Content -LiteralPath (Join-Path $Runtime "ui_launcher.pid") -Value $Process.Id -Encoding ascii
Write-Output "ui_status=PASS_R1E_DASHBOARD_V2_START_REQUESTED"
Write-Output "ui_url=http://127.0.0.1:8765"
Write-Output "engine_dependency=False"

