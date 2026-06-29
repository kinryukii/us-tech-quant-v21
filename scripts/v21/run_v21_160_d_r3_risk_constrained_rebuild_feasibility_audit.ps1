$ErrorActionPreference = "Stop"

python scripts/v21/v21_160_d_r3_risk_constrained_rebuild_feasibility_audit.py
pytest -q scripts/v21/test_v21_160_d_r3_risk_constrained_rebuild_feasibility_audit.py

$outDir = "outputs/v21/V21.160_D_R3_RISK_CONSTRAINED_REBUILD_FEASIBILITY_AUDIT"
Get-Content "$outDir/V21.160_readable_report.txt"
Get-Content "$outDir/V21.160_machine_summary.json"
