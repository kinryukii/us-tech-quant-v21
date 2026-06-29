$ErrorActionPreference = "Stop"

python scripts/v21/v21_151_r2_overheat_breadth_policy_audit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.151 R2 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_151_r2_overheat_breadth_policy_audit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.151 R2 validation failed with exit code $LASTEXITCODE"
}
