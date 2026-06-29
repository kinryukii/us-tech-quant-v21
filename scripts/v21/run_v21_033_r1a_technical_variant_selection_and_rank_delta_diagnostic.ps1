$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_033_r1a_technical_variant_selection_and_rank_delta_diagnostic.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_033_R1A_TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.033-R1A summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.033-R1A_TECHNICAL_VARIANT_SELECTION_AND_RANK_DELTA_DIAGNOSTIC"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "diagnostic_variant_name=$($SummaryRow.diagnostic_variant_name)"
Write-Output "probable_issue_type=$($SummaryRow.probable_issue_type)"
Write-Output "zero_excess_detected=$($SummaryRow.zero_excess_detected)"
Write-Output "variant_score_changed=$($SummaryRow.variant_score_changed)"
Write-Output "variant_rank_changed=$($SummaryRow.variant_rank_changed)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_mutation_allowed=$($SummaryRow.official_weight_mutation_allowed)"
