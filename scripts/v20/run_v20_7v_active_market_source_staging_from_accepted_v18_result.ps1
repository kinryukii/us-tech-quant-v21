Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host "PATCH_VERSION: V20.7V"
Write-Host "PATCH_NAME: ACTIVE_MARKET_SOURCE_STAGING_FROM_ACCEPTED_V18_RESULT"
Write-Host "STAGING_ONLY: TRUE"
Write-Host "CERTIFIES_FINAL_SOURCE: FALSE"
Write-Host "CREATES_TRADING_SIGNALS: FALSE"
Write-Host "BROKER_API_USED: FALSE"
Write-Host "ORDER_EXECUTION_USED: FALSE"

python scripts/v20/v20_7v_active_market_source_staging_from_accepted_v18_result.py
