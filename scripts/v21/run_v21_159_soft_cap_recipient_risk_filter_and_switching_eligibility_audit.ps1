$ErrorActionPreference = "Stop"

python scripts/v21/v21_159_soft_cap_recipient_risk_filter_and_switching_eligibility_audit.py
pytest -q scripts/v21/test_v21_159_soft_cap_recipient_risk_filter_and_switching_eligibility_audit.py

$outDir = "outputs/v21/V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT"
Get-Content "$outDir/V21.159_readable_report.txt"
Get-Content "$outDir/V21.159_machine_summary.json"
