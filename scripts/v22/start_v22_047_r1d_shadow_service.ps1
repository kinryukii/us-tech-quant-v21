[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [int]$IntervalSeconds = 10)
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1d_live_market_account_bridge.py"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
$Runtime = Join-Path $Output "runtime"
$Logs = Join-Path $Output "logs"
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
New-Item -ItemType Directory -Path $Logs -Force | Out-Null
Remove-Item -LiteralPath (Join-Path $Output "engine.stop") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $Output "watchdog.stop") -Force -ErrorAction SilentlyContinue
$EngineLock = Join-Path $Runtime "engine.lock"
if (Test-Path -LiteralPath $EngineLock) {
    $ExistingPid = [int](Get-Content -LiteralPath $EngineLock -Raw)
    if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) { throw "R1D engine already running: PID $ExistingPid" }
    Remove-Item -LiteralPath $EngineLock -Force
}
$EngineInfo = New-Object System.Diagnostics.ProcessStartInfo
$EngineInfo.FileName = $Python
$EngineInfo.Arguments = "`"$Main`" engine --repo-root `"$RepoRoot`" --interval $IntervalSeconds"
$EngineInfo.WorkingDirectory = $RepoRoot
$EngineInfo.UseShellExecute = $true
$EngineInfo.WindowStyle = "Hidden"
$Engine = [System.Diagnostics.Process]::Start($EngineInfo)
Set-Content -LiteralPath (Join-Path $Runtime "engine_launcher.pid") -Value $Engine.Id -Encoding ascii
$WatchdogInfo = New-Object System.Diagnostics.ProcessStartInfo
$WatchdogInfo.FileName = $Python
$WatchdogInfo.Arguments = "`"$Main`" watchdog --repo-root `"$RepoRoot`""
$WatchdogInfo.WorkingDirectory = $RepoRoot
$WatchdogInfo.UseShellExecute = $true
$WatchdogInfo.WindowStyle = "Hidden"
$Watchdog = [System.Diagnostics.Process]::Start($WatchdogInfo)
Set-Content -LiteralPath (Join-Path $Runtime "watchdog.pid") -Value $Watchdog.Id -Encoding ascii
Write-Output "start_status=PASS_R1D_BACKGROUND_STARTED"
Write-Output "engine_pid=$($Engine.Id)"
Write-Output "watchdog_pid=$($Watchdog.Id)"
Write-Output "effective_execution_mode=SHADOW_ONLY"
