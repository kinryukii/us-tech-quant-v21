$ErrorActionPreference = "Stop"

python scripts/v21/v21_165_data_freshness_and_proxy_coverage_dashboard.py
pytest -q scripts/v21/test_v21_165_data_freshness_and_proxy_coverage_dashboard.py

$outDir = "outputs/v21/V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD"
Get-Content "$outDir/V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_report.txt"
Get-Content "$outDir/V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json"
