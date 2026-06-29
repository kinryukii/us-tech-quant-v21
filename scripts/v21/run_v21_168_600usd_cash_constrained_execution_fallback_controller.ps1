$ErrorActionPreference = "Stop"

python scripts/v21/v21_168_600usd_cash_constrained_execution_fallback_controller.py
pytest -q scripts/v21/test_v21_168_600usd_cash_constrained_execution_fallback_controller.py

$outDir = "outputs/v21/V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER"
Get-Content "$outDir/V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_report.txt"
Get-Content "$outDir/V21.168_600USD_CASH_CONSTRAINED_EXECUTION_FALLBACK_CONTROLLER_summary.json"
