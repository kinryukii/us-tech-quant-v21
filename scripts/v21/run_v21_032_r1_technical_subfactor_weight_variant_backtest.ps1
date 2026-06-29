$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_032_r1_technical_subfactor_weight_variant_backtest.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.032-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.032-R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "best_shadow_variant_name=$($SummaryRow.best_shadow_variant_name)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_mutation_allowed=$($SummaryRow.official_weight_mutation_allowed)"
Write-Output "official_ranking_mutation_allowed=$($SummaryRow.official_ranking_mutation_allowed)"
Write-Output "trade_action_allowed=$($SummaryRow.trade_action_allowed)"
