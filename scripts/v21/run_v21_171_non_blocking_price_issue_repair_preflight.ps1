$ErrorActionPreference = "Stop"

python scripts/v21/v21_171_non_blocking_price_issue_repair_preflight.py
pytest -q scripts/v21/test_v21_171_non_blocking_price_issue_repair_preflight.py

$outDir = "outputs/v21/V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT"
Get-Content "$outDir/V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_report.txt"
Get-Content "$outDir/V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_summary.json"
