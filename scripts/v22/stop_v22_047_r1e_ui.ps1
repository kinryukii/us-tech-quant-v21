[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
$StatePath = Join-Path $Output "ui_state.json"
$UiProcessId = 0
if (Test-Path -LiteralPath $StatePath) {
    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    $UiProcessId = [int]$State.pid
    $State.desired_running = $false
    $State.actual_running = $false
    $State.pid = $null
    $State | Add-Member -NotePropertyName stopped_at_utc -NotePropertyValue ([DateTime]::UtcNow.ToString("o")) -Force
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatePath -Encoding utf8
}
if ($UiProcessId -gt 0 -and (Get-Process -Id $UiProcessId -ErrorAction SilentlyContinue)) { Stop-Process -Id $UiProcessId -Force }
Write-Output "ui_stop_status=PASS_R1E_UI_STOPPED_ENGINE_UNCHANGED"
