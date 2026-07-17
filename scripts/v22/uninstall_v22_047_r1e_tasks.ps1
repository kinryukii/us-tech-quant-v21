[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [string]$TaskPrefix = "US-Tech-Quant-V22.047-R1E")
$ErrorActionPreference = "Stop"
$Names = @("$TaskPrefix-Service-Startup", "$TaskPrefix-Service-Logon", "$TaskPrefix-Dashboard-OnDemand")
foreach ($Name in $Names) {
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($Task) { Unregister-ScheduledTask -TaskName $Name -Confirm:$false }
}
$Output = Join-Path $RepoRoot "outputs\v22\V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
New-Item -ItemType Directory -Path $Output -Force | Out-Null
[ordered]@{schema_version=1;timestamp_utc=[DateTime]::UtcNow.ToString("o");installed=$false;tasks=$Names;live_auto_restore_allowed=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Output "autostart_state.json") -Encoding utf8
Write-Output "uninstall_status=PASS_R1E_TASKS_REMOVED"

