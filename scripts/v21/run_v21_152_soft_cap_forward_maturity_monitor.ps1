$ErrorActionPreference = "Stop"

python scripts/v21/v21_152_soft_cap_forward_maturity_monitor.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.152 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_152_soft_cap_forward_maturity_monitor.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.152 validation failed with exit code $LASTEXITCODE"
}
