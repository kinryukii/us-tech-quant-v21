$ErrorActionPreference = "Stop"

python scripts/v21/v21_143_random_universe_and_survivorship_artifact_audit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.143 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_143_random_universe_and_survivorship_artifact_audit.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.143 validation failed with exit code $LASTEXITCODE"
}
