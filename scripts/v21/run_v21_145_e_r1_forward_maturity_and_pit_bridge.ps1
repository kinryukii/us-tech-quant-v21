$ErrorActionPreference = "Stop"

python scripts/v21/v21_145_e_r1_forward_maturity_and_pit_bridge.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.145 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_145_e_r1_forward_maturity_and_pit_bridge.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.145 validation failed with exit code $LASTEXITCODE"
}
