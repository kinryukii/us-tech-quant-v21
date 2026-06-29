$ErrorActionPreference = "Stop"

python scripts/v21/v21_151_execution_overlay_forward_tracking_ledger.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.151 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_151_execution_overlay_forward_tracking_ledger.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.151 validation failed with exit code $LASTEXITCODE"
}
