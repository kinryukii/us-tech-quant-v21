$ErrorActionPreference = "Stop"

python scripts/v21/v21_153_r2_softcap_return_vs_risk_attribution.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.153 R2 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_153_r2_softcap_return_vs_risk_attribution.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.153 R2 validation failed with exit code $LASTEXITCODE"
}
