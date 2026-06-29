$ErrorActionPreference = "Stop"

python scripts/v21/v21_151_r3_soft_cap_forward_tracking_update.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.151 R3 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_151_r3_soft_cap_forward_tracking_update.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.151 R3 validation failed with exit code $LASTEXITCODE"
}
