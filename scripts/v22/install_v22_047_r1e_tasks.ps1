[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [string]$TaskPrefix = "US-Tech-Quant-V22.047-R1E")
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1e_windows_service_hardening.py"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path -LiteralPath $Main)) { throw "R1E module not found: $Main" }
New-Item -ItemType Directory -Path $Output -Force | Out-Null
& $Python -m py_compile $Main
if ($LASTEXITCODE -ne 0) { throw "R1E compile check failed" }

$ServiceArgs = "`"$Main`" service --repo-root `"$RepoRoot`" --wait-seconds 1800"
$UiArgs = "`"$Main`" ui --repo-root `"$RepoRoot`""
$ServiceAction = New-ScheduledTaskAction -Execute $Python -Argument $ServiceArgs -WorkingDirectory $RepoRoot
$UiAction = New-ScheduledTaskAction -Execute $Python -Argument $UiArgs -WorkingDirectory $RepoRoot
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)

$StartupTrigger = New-ScheduledTaskTrigger -AtStartup
$StartupTrigger.Delay = "PT30S"
$SystemPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$StartupTask = New-ScheduledTask -Action $ServiceAction -Trigger $StartupTrigger -Settings $Settings -Principal $SystemPrincipal -Description "R1E shadow-only service; waits for network, OpenD 18441 and quote API."
$StartupInstalled = $false
$StartupError = ""
try {
    Register-ScheduledTask -TaskName "$TaskPrefix-Service-Startup" -InputObject $StartupTask -Force -ErrorAction Stop | Out-Null
    $StartupInstalled = $null -ne (Get-ScheduledTask -TaskName "$TaskPrefix-Service-Startup" -ErrorAction SilentlyContinue)
} catch {
    $StartupError = $_.Exception.Message
}

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$UserPrincipal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
$LogonTask = New-ScheduledTask -Action $ServiceAction -Trigger $LogonTrigger -Settings $Settings -Principal $UserPrincipal -Description "R1E logon fallback; duplicate service start is rejected by the single-instance lock."
Register-ScheduledTask -TaskName "$TaskPrefix-Service-Logon" -InputObject $LogonTask -Force -ErrorAction Stop | Out-Null
$LogonInstalled = $null -ne (Get-ScheduledTask -TaskName "$TaskPrefix-Service-Logon" -ErrorAction SilentlyContinue)

$UiTask = New-ScheduledTask -Action $UiAction -Settings $Settings -Principal $UserPrincipal -Description "R1E Dashboard V2 on-demand only; not required by Engine."
Register-ScheduledTask -TaskName "$TaskPrefix-Dashboard-OnDemand" -InputObject $UiTask -Force -ErrorAction Stop | Out-Null
$DashboardInstalled = $null -ne (Get-ScheduledTask -TaskName "$TaskPrefix-Dashboard-OnDemand" -ErrorAction SilentlyContinue)

$State = [ordered]@{
    schema_version = 1
    timestamp_utc = [DateTime]::UtcNow.ToString("o")
    installed = ($StartupInstalled -or $LogonInstalled)
    startup_task_installed = $StartupInstalled
    startup_task_error = $StartupError
    logon_task_installed = $LogonInstalled
    dashboard_task_installed = $DashboardInstalled
    startup_task = "$TaskPrefix-Service-Startup"
    logon_task = "$TaskPrefix-Service-Logon"
    dashboard_task = "$TaskPrefix-Dashboard-OnDemand"
    network_wait_enabled = $true
    opend_wait_endpoint = "127.0.0.1:18441"
    quote_probe_required = $true
    default_mode = "SHADOW"
    live_auto_restore_allowed = $false
    paper_available = $false
    live_available = $false
}
$State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Output "autostart_state.json") -Encoding utf8
if ($StartupInstalled -and $LogonInstalled -and $DashboardInstalled) {
    Write-Output "install_status=PASS_R1E_ALL_TASKS_INSTALLED"
} elseif ($LogonInstalled -and $DashboardInstalled) {
    Write-Output "install_status=PASS_R1E_LOGON_AUTOSTART_AND_DASHBOARD_INSTALLED_STARTUP_TASK_PERMISSION_BLOCKED"
    Write-Warning "SYSTEM startup task not installed: $StartupError"
} else {
    throw "R1E autostart task installation incomplete"
}
Get-ScheduledTask -TaskName "$TaskPrefix-*" | Select-Object TaskName,State | Format-Table -AutoSize
