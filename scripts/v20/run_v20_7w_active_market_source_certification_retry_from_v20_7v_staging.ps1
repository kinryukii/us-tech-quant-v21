Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host "PATCH_VERSION: V20.7W"
Write-Host "PATCH_NAME: ACTIVE_MARKET_SOURCE_CERTIFICATION_RETRY_FROM_V20_7V_STAGING"
Write-Host "REPORTING_ONLY: TRUE"
Write-Host "CERTIFICATION_RETRY_ONLY: TRUE"
Write-Host "CREATES_NORMALIZED_ROWS: FALSE"
Write-Host "CREATES_TRADING_SIGNALS: FALSE"
Write-Host "BROKER_API_USED: FALSE"
Write-Host "ORDER_EXECUTION_USED: FALSE"
Write-Host "V20_8_OUTPUTS_CREATED: FALSE"

python scripts/v20/v20_7w_active_market_source_certification_retry_from_v20_7v_staging.py
