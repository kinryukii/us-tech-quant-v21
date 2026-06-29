$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_040_r4_context_bucket_consolidation_and_retest_eligibility_gate.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.040-R4 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.040-R4_CONTEXT_BUCKET_CONSOLIDATION_AND_RETEST_ELIGIBILITY_GATE"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "r3_ledger_rows=$($SummaryRow.r3_ledger_rows)"
Write-Output "r4_ledger_rows=$($SummaryRow.r4_ledger_rows)"
Write-Output "r3_distinct_context_labels=$($SummaryRow.r3_distinct_context_labels)"
Write-Output "r4_distinct_context_buckets=$($SummaryRow.r4_distinct_context_buckets)"
Write-Output "missing_context_count=$($SummaryRow.missing_context_count)"
Write-Output "overbroadcast_context_count=$($SummaryRow.overbroadcast_context_count)"
Write-Output "too_narrow_context_count_before=$($SummaryRow.too_narrow_context_count_before)"
Write-Output "too_narrow_context_count_after=$($SummaryRow.too_narrow_context_count_after)"
Write-Output "low_maturity_context_count_before=$($SummaryRow.low_maturity_context_count_before)"
Write-Output "low_maturity_context_count_after=$($SummaryRow.low_maturity_context_count_after)"
Write-Output "canonical_bucket_count_interpretable=$($SummaryRow.canonical_bucket_count_interpretable)"
Write-Output "technical_reweighting_retest_allowed=$($SummaryRow.technical_reweighting_retest_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
