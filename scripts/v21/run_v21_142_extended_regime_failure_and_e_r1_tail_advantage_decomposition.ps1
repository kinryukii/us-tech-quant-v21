$ErrorActionPreference = "Stop"

python scripts/v21/v21_142_extended_regime_failure_and_e_r1_tail_advantage_decomposition.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.142 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_142_extended_regime_failure_and_e_r1_tail_advantage_decomposition.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.142 validation failed with exit code $LASTEXITCODE"
}
