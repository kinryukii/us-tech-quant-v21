$ErrorActionPreference = "Stop"

python scripts/v21/v21_167_r1_active_600usd_small_account_overlay_recheck.py
pytest -q scripts/v21/test_v21_167_r1_active_600usd_small_account_overlay_recheck.py

$outDir = "outputs/v21/V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK"
Get-Content "$outDir/V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_report.txt"
Get-Content "$outDir/V21.167_R1_ACTIVE_600USD_SMALL_ACCOUNT_OVERLAY_RECHECK_summary.json"
