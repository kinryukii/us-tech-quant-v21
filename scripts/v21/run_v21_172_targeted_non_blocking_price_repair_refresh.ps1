$ErrorActionPreference = "Stop"

python scripts/v21/v21_172_targeted_non_blocking_price_repair_refresh.py
pytest -q scripts/v21/test_v21_172_targeted_non_blocking_price_repair_refresh.py

$outDir = "outputs/v21/V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH"
Get-Content "$outDir/V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_report.txt"
Get-Content "$outDir/V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_summary.json"
