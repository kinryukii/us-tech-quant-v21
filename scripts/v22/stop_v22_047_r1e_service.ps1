[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')
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
$R1HOutput = Join-Path $RepoRoot "outputs\v22\V22.047_R1H_PAPER_EXECUTION_ORDER_LIFECYCLE_AND_RECONCILIATION"
New-Item -ItemType Directory -Path $R1HOutput -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $R1HOutput "r1h.stop") -Force | Out-Null
$R1IOutput = Join-Path $RepoRoot "outputs\v22\V22.047_R1I_PAPER_SOAK_REPLAY_FAULT_INJECTION_AND_LIVE_READINESS_GATE"
New-Item -ItemType Directory -Path $R1IOutput -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $R1IOutput "r1i.stop") -Force | Out-Null
$UiState = Join-Path $Output "ui_state.json"
if (Test-Path -LiteralPath $UiState) {
    $State = Get-Content -LiteralPath $UiState -Raw | ConvertFrom-Json
    $State.desired_running = $false
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $UiState -Encoding utf8
}
Start-Sleep -Seconds 3
$R1EEntry = "v22_047_r1e_windows_service_hardening.py"
$Entries = [ordered]@{
    "ui_launcher.pid" = @($R1EEntry, "ui")
    "watchdog.pid" = @($R1EEntry, "watchdog")
    "r1i.pid" = @("v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py", "--service")
    "r1h.pid" = @("v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py", "--service")
    "r1g.pid" = @("v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py", "--service")
    "r1f.pid" = @("v22_047_r1f_fractional_protected_sleeve.py", "--service")
    "engine_launcher.pid" = @("v22_047_r1d_live_market_account_bridge.py", "engine")
    "service_launcher.pid" = @($R1EEntry, "service")
    "service.pid" = @($R1EEntry, "service")
}
function Test-WorkerIdentity($Identity, $Entry) {
    if (-not $Identity -or -not $Identity.CommandLine -or -not $Identity.CreationDate) { return $false }
    $Parts = @([regex]::Matches($Identity.CommandLine, '"[^"]*"|[^\s"]+') | ForEach-Object { $_.Value.Trim('"') })
    if ($Parts.Count -lt 5 -or [IO.Path]::GetFileName($Parts[0]) -notmatch '^pythonw?\.exe$') { return $false }
    $Index = 1
    while ($Index -lt $Parts.Count -and $Parts[$Index] -in @('-B', '-u')) { $Index++ }
    $Script = Join-Path $RepoRoot ("scripts\v22\" + $Entry[0])
    if ($Index + 1 -ge $Parts.Count -or -not [IO.Path]::IsPathRooted($Parts[$Index]) -or
        [IO.Path]::GetFullPath($Parts[$Index]) -ine $Script -or $Parts[$Index + 1] -ine $Entry[1]) { return $false }
    $RootArgs = @($Parts | Where-Object { $_ -eq '--repo-root' })
    $RootIndex = [array]::IndexOf($Parts, '--repo-root')
    return $RootArgs.Count -eq 1 -and $RootIndex + 1 -lt $Parts.Count -and
        [IO.Path]::IsPathRooted($Parts[$RootIndex + 1]) -and
        [IO.Path]::GetFullPath($Parts[$RootIndex + 1]).TrimEnd('\') -ieq $RepoRoot
}
$Failures = @()
foreach ($File in $Entries.Keys) {
    $Path = Join-Path $Runtime $File
    if (Test-Path -LiteralPath $Path) {
        try {
            $TargetPid = [int](Get-Content -LiteralPath $Path -Raw)
            if ($TargetPid -le 0) { throw "INVALID_PID" }
            $Identity = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetPid"
            $Process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
            if ($Process) {
                if (-not (Test-WorkerIdentity $Identity $Entries[$File])) { throw "IDENTITY_NOT_CONFIRMED" }
                $Process | Wait-Process -Timeout 8 -ErrorAction SilentlyContinue
                $Process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
                if ($Process) {
                    # Bind the process handle, then recheck identity before forcing exit.
                    $null = $Process.Handle
                    $Current = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetPid"
                    if (-not (Test-WorkerIdentity $Current $Entries[$File]) -or
                        $Current.CreationDate -ne $Identity.CreationDate) { throw "IDENTITY_NOT_CONFIRMED" }
                    Stop-Process -InputObject $Process -Force
                    $Process | Wait-Process -Timeout 5 -ErrorAction Stop
                }
            }
            Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        } catch {
            $Failures += "${File}:$($_.Exception.Message)"
        }
    }
}
if ($Failures.Count) {
    Write-Output ("stop_status=FAILED:" + ($Failures -join ';'))
    Write-Output "broker_action_allowed=False"
    Write-Output "trade_api_called=False"
    exit 1
}
Write-Output "stop_status=PASS_R1E_SERVICE_ENGINE_WATCHDOG_UI_STOPPED"
Write-Output "broker_action_allowed=False"
Write-Output "trade_api_called=False"
