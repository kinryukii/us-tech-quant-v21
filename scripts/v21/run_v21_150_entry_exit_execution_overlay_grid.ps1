$ErrorActionPreference = "Stop"

python scripts/v21/v21_150_entry_exit_execution_overlay_grid.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.150 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_150_entry_exit_execution_overlay_grid.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.150 validation failed with exit code $LASTEXITCODE"
}
