$ErrorActionPreference = "Stop"

python scripts/v21/v21_167_small_account_overlay_closure_controller.py
pytest -q scripts/v21/test_v21_167_small_account_overlay_closure_controller.py

$outDir = "outputs/v21/V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER"
Get-Content "$outDir/V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_report.txt"
Get-Content "$outDir/V21.167_SMALL_ACCOUNT_OVERLAY_CLOSURE_CONTROLLER_summary.json"
