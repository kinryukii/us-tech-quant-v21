$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_040_r1_matured_forward_return_extension_and_context_alignment.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_040_R1_MATURED_FORWARD_CONTEXT_ALIGNMENT_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.040-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.040-R1_MATURED_FORWARD_RETURN_EXTENSION_AND_CONTEXT_ALIGNMENT"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "forward_return_source_count=$($SummaryRow.forward_return_source_count)"
Write-Output "total_candidate_observations=$($SummaryRow.total_candidate_observations)"
Write-Output "total_matured_observations=$($SummaryRow.total_matured_observations)"
Write-Output "total_pending_observations=$($SummaryRow.total_pending_observations)"
Write-Output "context_selectivity_ready=$($SummaryRow.context_selectivity_ready)"
Write-Output "context_overbroadcast_detected=$($SummaryRow.context_overbroadcast_detected)"
Write-Output "technical_reweighting_retest_allowed=$($SummaryRow.technical_reweighting_retest_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
