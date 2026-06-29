$ErrorActionPreference = "Stop"

python scripts/v21/v21_170_data_quality_blocker_decomposition_and_repair_plan.py
pytest -q scripts/v21/test_v21_170_data_quality_blocker_decomposition_and_repair_plan.py

$outDir = "outputs/v21/V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN"
Get-Content "$outDir/V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_report.txt"
Get-Content "$outDir/V21.170_DATA_QUALITY_BLOCKER_DECOMPOSITION_AND_REPAIR_PLAN_summary.json"
