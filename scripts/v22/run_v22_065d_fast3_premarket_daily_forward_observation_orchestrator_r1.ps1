[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$RecoveryPreflight,
    [int]$RecoveryMaxPartitionsPerRun = 24,
    [double]$RecoveryMaxElapsedMinutes = 20,
    [double]$DataRefreshHardTimeoutMinutes = 45,
    [double]$DataRefreshIdleTimeoutMinutes = 12
)
$ErrorActionPreference='Stop'
if (-not $Execute -and -not $RecoveryPreflight) { throw 'The -Execute or -RecoveryPreflight flag is required.' }
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repo
if ($DataRefreshHardTimeoutMinutes -le 0 -or $DataRefreshIdleTimeoutMinutes -le 0) { throw 'Refresh timeout minutes must be positive.' }
$args=@(); if($Execute){$args+='--execute'}; if($RecoveryPreflight){$args+='--recovery-preflight'}; $args+=@('--recovery-max-partitions-per-run',$RecoveryMaxPartitionsPerRun,'--recovery-max-elapsed-minutes',$RecoveryMaxElapsedMinutes,'--data-refresh-hard-timeout-minutes',$DataRefreshHardTimeoutMinutes,'--data-refresh-idle-timeout-minutes',$DataRefreshIdleTimeoutMinutes)
& "$repo\.venv\Scripts\python.exe" "$repo\scripts\v22\v22_065d_fast3_premarket_daily_forward_observation_orchestrator_r1.py" @args
exit $LASTEXITCODE
