$ErrorActionPreference = "Stop"

python scripts/v21/v21_144_fair_baseline_extended_strategy_retest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.144 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_144_fair_baseline_extended_strategy_retest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.144 validation failed with exit code $LASTEXITCODE"
}
