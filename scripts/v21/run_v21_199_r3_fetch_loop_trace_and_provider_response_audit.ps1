$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
python scripts/v21/v21_199_r3_fetch_loop_trace_and_provider_response_audit.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$SummaryPath = "outputs/v21/V21.199_R3_FETCH_LOOP_TRACE_AND_PROVIDER_RESPONSE_AUDIT/v21_199_r3_summary.json"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
Write-Output "final_status=$($Summary.final_status)"
Write-Output "final_decision=$($Summary.final_decision)"
Write-Output "broker_action_allowed=$($Summary.broker_action_allowed)"
if ($Summary.final_status -notlike "PASS*") { exit 1 }
exit 0
