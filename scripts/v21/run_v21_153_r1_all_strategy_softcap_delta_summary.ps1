$ErrorActionPreference = "Stop"

python scripts/v21/v21_153_r1_all_strategy_softcap_delta_summary.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.153 R1 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_153_r1_all_strategy_softcap_delta_summary.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.153 R1 validation failed with exit code $LASTEXITCODE"
}
