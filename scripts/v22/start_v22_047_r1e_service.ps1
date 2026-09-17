[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant",
      [switch]$StartupCheckOnly,
      [ValidateRange(0, 86400)][double]$WaitSeconds = 1800,
      [string]$StartupCheckOutput = "")
$ErrorActionPreference = "Stop"
. (Join-Path $RepoRoot "scripts\common\storage_paths.ps1")
$Storage = Get-UstqStoragePaths -RepoRoot $RepoRoot
$Python = $Storage.python_exe
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python not found: $Python" }
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1e_windows_service_hardening.py"
$WaitText = $WaitSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
if ($StartupCheckOnly) {
    $CheckArgs = @($Main, 'service', '--repo-root', $RepoRoot, '--wait-seconds', $WaitText, '--startup-check-only')
    if ($StartupCheckOutput) { $CheckArgs += @('--startup-check-output', $StartupCheckOutput) }
    & $Python -B @CheckArgs
    if ($LASTEXITCODE -ne 0) { throw "R1E startup prerequisite check failed (exit $LASTEXITCODE)" }
    Write-Output "startup_check_status=STARTUP_PREREQUISITES_READY"
    return
}
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
$Info.Arguments = "`"$Main`" service --repo-root `"$RepoRoot`" --wait-seconds $WaitText"
$Info.WorkingDirectory = $RepoRoot
$Info.UseShellExecute = $true
$Info.WindowStyle = "Hidden"
$Process = [System.Diagnostics.Process]::Start($Info)
Set-Content -LiteralPath (Join-Path $Runtime "service_launcher.pid") -Value $Process.Id -Encoding ascii
Write-Output "start_status=PASS_R1E_SERVICE_START_REQUESTED"
Write-Output "service_pid=$($Process.Id)"
Write-Output "default_mode=SHADOW"
Write-Output "effective_execution_mode=SHADOW_ONLY"

