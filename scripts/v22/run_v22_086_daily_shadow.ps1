[CmdletBinding()]
param([switch]$Execute, [string]$StageRoot = 'D:\us-tech-quant-results\fast3_v22_086_overnight_strategy_freeze')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = $StageRoot
$Candidate = Join-Path $Root 'fast3_v1_candidate_config.json'
$Out = Join-Path $Root 'daily_shadow_decisions.jsonl'
if (-not $Execute) { Write-Host 'NO_ORDER_SHADOW_RUNNER. Use -Execute only after a candidate has been hash-frozen.'; exit 0 }
if (-not (Test-Path -LiteralPath $Candidate)) { Write-Host 'FAIL_CLOSED=NO_HASH_FROZEN_CANDIDATE'; exit 2 }
$c = Get-Content -LiteralPath $Candidate -Raw | ConvertFrom-Json
$key = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:00:00Z')
if (Test-Path -LiteralPath $Out) { if (Select-String -LiteralPath $Out -Pattern ('"decision_key":"' + $key + '"') -Quiet) { Write-Host 'IDEMPOTENT_NO_DUPLICATE_DECISION'; exit 0 } }
# This runner intentionally fails closed: live as-of feature construction must be
# implemented from the canonical ingestion pipeline before any shadow decision.
$record = @{decision_key=$key; decision='NO_TRADE'; reason_code='FAIL_CLOSED_LIVE_ASOF_PIPELINE_NOT_CONFIGURED'; prediction_timestamp=$key; data_as_of_timestamp=$null; candidate_hash=$c.candidate_config_sha256; model_hash=$c.model_sha256; feature_hash=$c.feature_contract_sha256; probabilities_or_scores=$null; entry_policy='NO_ENTRY_FAIL_CLOSED'; expected_maturity_timestamp=$null; broker_action_allowed=$false; paper_trading_allowed=$false; official_adoption_allowed=$false} | ConvertTo-Json -Compress
Add-Content -LiteralPath $Out -Value $record -Encoding utf8
Write-Host 'DECISION=NO_TRADE'; Write-Host 'REASON=FAIL_CLOSED_LIVE_ASOF_PIPELINE_NOT_CONFIGURED'
