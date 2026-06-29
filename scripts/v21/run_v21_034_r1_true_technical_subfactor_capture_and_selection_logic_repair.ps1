$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_034_r1_true_technical_subfactor_capture_and_selection_logic_repair.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_REPAIR_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.034-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.034-R1_TRUE_TECHNICAL_SUBFACTOR_CAPTURE_AND_SELECTION_LOGIC_REPAIR"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "upstream_issue_confirmed=$($SummaryRow.upstream_issue_confirmed)"
Write-Output "technical_subfactor_capture_ready=$($SummaryRow.technical_subfactor_capture_ready)"
Write-Output "true_subfactor_reweighting_ready=$($SummaryRow.true_subfactor_reweighting_ready)"
Write-Output "proxy_reweighting_allowed=$($SummaryRow.proxy_reweighting_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_mutation_allowed=$($SummaryRow.official_weight_mutation_allowed)"
