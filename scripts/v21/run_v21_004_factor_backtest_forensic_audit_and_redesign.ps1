$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_004_factor_backtest_forensic_audit_and_redesign.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Contract = Join-Path $Root "outputs\v21\factor_backtest\V21_004_REDESIGN_CONTRACT.csv"

python $Runner | Out-Host

if (-not (Test-Path $Contract)) {
    throw "Redesign contract output not found: $Contract"
}

$ContractRow = Import-Csv $Contract | Select-Object -First 1
Write-Output "STAGE_NAME=V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_AND_REDESIGN"
Write-Output "final_verdict=$($ContractRow.final_verdict)"
Write-Output "final_status=$($ContractRow.final_status)"
Write-Output "total_snapshots=$($ContractRow.total_snapshots)"
Write-Output "usable_snapshots=$($ContractRow.usable_snapshots)"
Write-Output "total_observations=$($ContractRow.total_observations)"
Write-Output "matured_observations=$($ContractRow.matured_observations)"
Write-Output "pending_observations=$($ContractRow.pending_observations)"
Write-Output "rejected_observations=$($ContractRow.rejected_observations)"
Write-Output "data_trust_ranking_weight=$($ContractRow.data_trust_ranking_weight)"
Write-Output "official_ranking_mutation_count=$($ContractRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($ContractRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($ContractRow.official_recommendation_count)"
Write-Output "trade_action_count=$($ContractRow.trade_action_count)"
Write-Output "shadow_activation=$($ContractRow.shadow_activation)"
Write-Output "recommended_next_stage=$($ContractRow.recommended_next_stage)"
Write-Output "research_only=$($ContractRow.research_only)"
