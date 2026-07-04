$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
python scripts/v21/v21_198_moomoo_data_backbone_and_health_check.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$SummaryPath = "outputs/v21/V21.198_MOOMOO_DATA_BACKBONE_AND_HEALTH_CHECK/v21_198_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*") { exit 1 }
exit 0
