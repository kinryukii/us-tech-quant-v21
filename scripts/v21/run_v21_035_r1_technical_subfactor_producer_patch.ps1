$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_035_r1_technical_subfactor_producer_patch.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.035-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.035-R1_TECHNICAL_SUBFACTOR_PRODUCER_PATCH"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "local_price_source_found=$($SummaryRow.local_price_source_found)"
Write-Output "total_subfactor_rows_produced=$($SummaryRow.total_subfactor_rows_produced)"
Write-Output "true_subfactor_capture_ready=$($SummaryRow.true_subfactor_capture_ready)"
Write-Output "true_reweighting_ready=$($SummaryRow.true_reweighting_ready)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_mutation_allowed=$($SummaryRow.official_weight_mutation_allowed)"
