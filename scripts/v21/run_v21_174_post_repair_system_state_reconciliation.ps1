$ErrorActionPreference = "Stop"

python scripts/v21/v21_174_post_repair_system_state_reconciliation.py
pytest -q scripts/v21/test_v21_174_post_repair_system_state_reconciliation.py

$outDir = "outputs/v21/V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION"
Get-Content "$outDir/V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_report.txt"
Get-Content "$outDir/V21.174_POST_REPAIR_SYSTEM_STATE_RECONCILIATION_summary.json"
