[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
$R1DOutput = Join-Path $RepoRoot "outputs\v22\V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
$Runtime = Join-Path $Output "runtime"
New-Item -ItemType Directory -Path $Output -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $Output "service.stop") -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $Output "watchdog.stop") -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $R1DOutput "engine.stop") -Force | Out-Null
$R1FOutput = Join-Path $RepoRoot "outputs\v22\V22.047_R1F_V8_REFERENCE_ROTATION_FRACTIONAL_RTH_PROTECTED_SLEEVE_SHADOW"
New-Item -ItemType Directory -Path $R1FOutput -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $R1FOutput "r1f.stop") -Force | Out-Null
$R1GOutput = Join-Path $RepoRoot "outputs\v22\V22.047_R1G_SHADOW_FRACTIONAL_ASSUMPTION_AND_EXECUTION_ARMING"
New-Item -ItemType Directory -Path $R1GOutput -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $R1GOutput "r1g.stop") -Force | Out-Null
$UiState = Join-Path $Output "ui_state.json"
if (Test-Path -LiteralPath $UiState) {
    $State = Get-Content -LiteralPath $UiState -Raw | ConvertFrom-Json
    $State.desired_running = $false
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $UiState -Encoding utf8
}
Start-Sleep -Seconds 3
foreach ($File in @("ui_launcher.pid", "watchdog.pid", "r1g.pid", "r1f.pid", "engine_launcher.pid", "service_launcher.pid", "service.pid")) {
    $Path = Join-Path $Runtime $File
    if (Test-Path -LiteralPath $Path) {
        $TargetPid = [int](Get-Content -LiteralPath $Path -Raw)
        $Process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        if ($Process) {
            $Process | Wait-Process -Timeout 8 -ErrorAction SilentlyContinue
            if (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) { Stop-Process -Id $TargetPid -Force }
        }
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
}
Write-Output "stop_status=PASS_R1E_SERVICE_ENGINE_WATCHDOG_UI_STOPPED"
Write-Output "broker_action_allowed=False"
Write-Output "trade_api_called=False"
