$ErrorActionPreference = "Stop"

python scripts/v21/v21_146_e_r1_pit_missing_inputs_decomposition.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.146 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_146_e_r1_pit_missing_inputs_decomposition.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.146 validation failed with exit code $LASTEXITCODE"
}
