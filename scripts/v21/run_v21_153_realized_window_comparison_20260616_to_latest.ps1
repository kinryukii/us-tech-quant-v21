$ErrorActionPreference = "Stop"

python scripts/v21/v21_153_realized_window_comparison_20260616_to_latest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.153 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_153_realized_window_comparison_20260616_to_latest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.153 validation failed with exit code $LASTEXITCODE"
}
