$ErrorActionPreference = "Stop"

python scripts/v21/v21_156_conditional_strategy_switching_shadow_simulation.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.156 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_156_conditional_strategy_switching_shadow_simulation.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.156 validation failed with exit code $LASTEXITCODE"
}

Get-Content outputs/v21/V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION/V21.156_readable_report.txt
Get-Content outputs/v21/V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION/V21.156_machine_summary.json
