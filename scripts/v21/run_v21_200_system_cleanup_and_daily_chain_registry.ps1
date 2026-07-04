$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
python scripts/v21/v21_200_system_cleanup_and_daily_chain_registry.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$SummaryPath = "outputs/v21/V21.200_SYSTEM_CLEANUP_AND_DAILY_CHAIN_REGISTRY/v21_200_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "files_deleted=$($Summary.files_deleted)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*") { exit 1 }
exit 0
