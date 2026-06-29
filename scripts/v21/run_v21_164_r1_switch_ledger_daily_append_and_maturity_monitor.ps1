$ErrorActionPreference = "Stop"

python scripts/v21/v21_164_r1_switch_ledger_daily_append_and_maturity_monitor.py
pytest -q scripts/v21/test_v21_164_r1_switch_ledger_daily_append_and_maturity_monitor.py

$outDir = "outputs/v21/V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR"
Get-Content "$outDir/V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_report.txt"
Get-Content "$outDir/V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
