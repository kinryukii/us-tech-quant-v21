$ErrorActionPreference = "Stop"

python scripts/v21/v21_164_switch_state_forward_tracking_ledger.py
pytest -q scripts/v21/test_v21_164_switch_state_forward_tracking_ledger.py

$outDir = "outputs/v21/V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"
Get-Content "$outDir/V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER_report.txt"
Get-Content "$outDir/V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER_summary.json"
