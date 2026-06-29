$ErrorActionPreference = "Stop"

python scripts/v21/v21_147_e_r1_a1_pit_lite_replay_manifest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.147 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_147_e_r1_a1_pit_lite_replay_manifest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.147 validation failed with exit code $LASTEXITCODE"
}
