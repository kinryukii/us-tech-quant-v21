$ErrorActionPreference = "Stop"

python scripts/v21/v21_166_realistic_execution_constraint_simulator.py
pytest -q scripts/v21/test_v21_166_realistic_execution_constraint_simulator.py

$outDir = "outputs/v21/V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR"
Get-Content "$outDir/V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_report.txt"
Get-Content "$outDir/V21.166_REALISTIC_EXECUTION_CONSTRAINT_SIMULATOR_summary.json"
