$ErrorActionPreference = "Stop"

python scripts/v21/v21_141_extended_2020_multi_strategy_random_backtest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.141 producer failed with exit code $LASTEXITCODE"
}
pytest -q scripts/v21/test_v21_141_extended_2020_multi_strategy_random_backtest.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.141 validation failed with exit code $LASTEXITCODE"
}
