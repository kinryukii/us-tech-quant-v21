$ErrorActionPreference = "Stop"

python scripts/v21/v21_157_e_r1_shadow_trigger_attribution_and_forward_maturity_gate.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.157 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_157_e_r1_shadow_trigger_attribution_and_forward_maturity_gate.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.157 validation failed with exit code $LASTEXITCODE"
}

Get-Content outputs/v21/V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE/V21.157_readable_report.txt
Get-Content outputs/v21/V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE/V21.157_machine_summary.json
