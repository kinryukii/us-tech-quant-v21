$ErrorActionPreference = "Stop"

python scripts/v21/v21_155_conditional_strategy_switching_state_machine_and_d_reentry_gate.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.155 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_155_conditional_strategy_switching_state_machine_and_d_reentry_gate.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.155 validation failed with exit code $LASTEXITCODE"
}

Get-Content outputs/v21/V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE/V21.155_readable_report.txt
Get-Content outputs/v21/V21.155_CONDITIONAL_STRATEGY_SWITCHING_STATE_MACHINE_AND_D_REENTRY_GATE/V21.155_machine_summary.json
