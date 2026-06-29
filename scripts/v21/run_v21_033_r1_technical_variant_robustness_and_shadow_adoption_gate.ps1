$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_033_r1_technical_variant_robustness_and_shadow_adoption_gate.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.033-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.033-R1_TECHNICAL_VARIANT_ROBUSTNESS_AND_SHADOW_ADOPTION_GATE"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "candidate_variant_name=$($SummaryRow.candidate_variant_name)"
Write-Output "shadow_adoption_allowed=$($SummaryRow.shadow_adoption_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_mutation_allowed=$($SummaryRow.official_weight_mutation_allowed)"
Write-Output "official_ranking_mutation_allowed=$($SummaryRow.official_ranking_mutation_allowed)"
Write-Output "trade_action_allowed=$($SummaryRow.trade_action_allowed)"
