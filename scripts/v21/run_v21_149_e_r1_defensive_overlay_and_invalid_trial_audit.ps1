$ErrorActionPreference = "Stop"

python scripts/v21/v21_149_e_r1_defensive_overlay_and_invalid_trial_audit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.149 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_149_e_r1_defensive_overlay_and_invalid_trial_audit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.149 validation failed with exit code $LASTEXITCODE"
}
