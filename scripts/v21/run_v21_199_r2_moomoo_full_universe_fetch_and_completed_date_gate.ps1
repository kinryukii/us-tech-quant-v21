$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
python scripts/v21/v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$SummaryPath = "outputs/v21/V21.199_R2_MOOMOO_FULL_UNIVERSE_FETCH_AND_COMPLETED_DATE_GATE/v21_199_r2_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "latest_moomoo_broad_honest_date=$($Summary.latest_moomoo_broad_honest_date)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*") { exit 1 }
exit 0
