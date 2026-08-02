Write-Warning 'Deprecated root launcher. Use fast3/compatibility/start_codex_fast3_full_chain.ps1.'
$target = Join-Path $PSScriptRoot 'fast3\compatibility\start_codex_fast3_full_chain.ps1'
& $target @args
exit $LASTEXITCODE
