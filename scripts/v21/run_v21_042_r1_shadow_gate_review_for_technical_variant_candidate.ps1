$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_042_r1_shadow_gate_review_for_technical_variant_candidate.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_042_R1_SHADOW_GATE_REVIEW_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.042-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.042-R1_SHADOW_GATE_REVIEW_FOR_TECHNICAL_VARIANT_CANDIDATE"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "candidate_variant_name=$($SummaryRow.candidate_variant_name)"
Write-Output "candidate_from_v21_041=$($SummaryRow.candidate_from_v21_041)"
Write-Output "stability_review_pass=$($SummaryRow.stability_review_pass)"
Write-Output "context_stability_pass=$($SummaryRow.context_stability_pass)"
Write-Output "window_stability_pass=$($SummaryRow.window_stability_pass)"
Write-Output "rank_delta_stability_pass=$($SummaryRow.rank_delta_stability_pass)"
Write-Output "turnover_guardrail_pass=$($SummaryRow.turnover_guardrail_pass)"
Write-Output "shadow_dry_run_candidate_allowed=$($SummaryRow.shadow_dry_run_candidate_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
