$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_042_r2_context_conditioned_rsi_deemphasis_repair_and_maturity_refresh.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_042_R2_CONTEXT_CONDITIONED_RSI_REPAIR_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.042-R2 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.042-R2_CONTEXT_CONDITIONED_RSI_DEEMPHASIS_REPAIR_AND_MATURITY_REFRESH"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "upstream_candidate_variant_name=$($SummaryRow.upstream_candidate_variant_name)"
Write-Output "context_conditioned_candidate_created=$($SummaryRow.context_conditioned_candidate_created)"
Write-Output "context_conditioned_candidate_name=$($SummaryRow.context_conditioned_candidate_name)"
Write-Output "context_conditioned_bucket_count=$($SummaryRow.context_conditioned_bucket_count)"
Write-Output "blocked_bucket_count=$($SummaryRow.blocked_bucket_count)"
Write-Output "edge_concentration_reduced=$($SummaryRow.edge_concentration_reduced)"
Write-Output "research_retest_allowed=$($SummaryRow.research_retest_allowed)"
Write-Output "shadow_dry_run_candidate_allowed=$($SummaryRow.shadow_dry_run_candidate_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
