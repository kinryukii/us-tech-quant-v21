[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
$Runtime = Join-Path $Output "runtime"
New-Item -ItemType File -Path (Join-Path $Output "engine.stop") -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $Output "watchdog.stop") -Force | Out-Null
foreach ($Name in @("watchdog.pid", "ui.pid", "engine_launcher.pid")) {
    $PidPath = Join-Path $Runtime $Name
    if (Test-Path -LiteralPath $PidPath) {
        $TargetPid = [int](Get-Content -LiteralPath $PidPath -Raw)
        $Process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        if ($Process) {
            if ($Name -eq "engine_launcher.pid") {
                $Process | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue
                $Process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
            }
            if ($Process) { Stop-Process -Id $TargetPid -Force }
        }
        Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    }
}
Write-Output "stop_status=PASS_R1D_PROCESSES_STOPPED"
Write-Output "broker_action_called=False"

