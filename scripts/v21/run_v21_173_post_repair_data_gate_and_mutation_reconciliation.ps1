$ErrorActionPreference = "Stop"

python scripts/v21/v21_173_post_repair_data_gate_and_mutation_reconciliation.py
pytest -q scripts/v21/test_v21_173_post_repair_data_gate_and_mutation_reconciliation.py

$outDir = "outputs/v21/V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION"
Get-Content "$outDir/V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_report.txt"
Get-Content "$outDir/V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_summary.json"
