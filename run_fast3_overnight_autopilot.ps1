Write-Warning 'Deprecated root launcher. Use fast3/compatibility/run_fast3_overnight_autopilot.ps1.'
$target = Join-Path $PSScriptRoot 'fast3\compatibility\run_fast3_overnight_autopilot.ps1'
& $target @args
exit $LASTEXITCODE
