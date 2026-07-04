$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
python scripts/v21/v21_201_dram_moomoo_r4_date_alignment_and_plan_refresh.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$SummaryPath = "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/v21_201_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "latest_plan_date=$($Summary.latest_plan_date)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*") { exit 1 }
exit 0
