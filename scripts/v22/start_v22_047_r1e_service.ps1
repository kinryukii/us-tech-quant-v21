[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1e_windows_service_hardening.py"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
$Runtime = Join-Path $Output "runtime"
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$Lock = Join-Path $Runtime "service.lock"
if (Test-Path -LiteralPath $Lock) {
    $ExistingPid = [int](Get-Content -LiteralPath $Lock -Raw)
    if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) { throw "R1E service already running; duplicate rejected: PID $ExistingPid" }
    Remove-Item -LiteralPath $Lock -Force
}
Remove-Item -LiteralPath (Join-Path $Output "service.stop") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $Output "watchdog.stop") -Force -ErrorAction SilentlyContinue
$Info = New-Object System.Diagnostics.ProcessStartInfo
$Info.FileName = $Python
$Info.Arguments = "`"$Main`" service --repo-root `"$RepoRoot`" --wait-seconds 1800"
$Info.WorkingDirectory = $RepoRoot
$Info.UseShellExecute = $true
$Info.WindowStyle = "Hidden"
$Process = [System.Diagnostics.Process]::Start($Info)
Set-Content -LiteralPath (Join-Path $Runtime "service_launcher.pid") -Value $Process.Id -Encoding ascii
Write-Output "start_status=PASS_R1E_SERVICE_START_REQUESTED"
Write-Output "service_pid=$($Process.Id)"
Write-Output "default_mode=SHADOW"
Write-Output "effective_execution_mode=SHADOW_ONLY"

