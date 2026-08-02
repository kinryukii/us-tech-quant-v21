Write-Warning 'Deprecated root launcher. Use fast3/compatibility/start_codex_v22_080a.ps1.'
$target = Join-Path $PSScriptRoot 'fast3\compatibility\start_codex_v22_080a.ps1'
& $target @args
exit $LASTEXITCODE
