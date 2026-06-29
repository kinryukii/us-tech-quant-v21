$ErrorActionPreference = "Stop"

python scripts/v21/v21_169_decision_boundary_and_action_guardrail.py
pytest -q scripts/v21/test_v21_169_decision_boundary_and_action_guardrail.py

$outDir = "outputs/v21/V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL"
Get-Content "$outDir/V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_report.txt"
Get-Content "$outDir/V21.169_DECISION_BOUNDARY_AND_ACTION_GUARDRAIL_summary.json"
