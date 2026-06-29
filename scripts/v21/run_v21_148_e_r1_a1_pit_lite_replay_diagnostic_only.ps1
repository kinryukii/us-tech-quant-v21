$ErrorActionPreference = "Stop"

python scripts/v21/v21_148_e_r1_a1_pit_lite_replay_diagnostic_only.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.148 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_148_e_r1_a1_pit_lite_replay_diagnostic_only.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.148 validation failed with exit code $LASTEXITCODE"
}
