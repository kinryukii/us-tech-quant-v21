$ErrorActionPreference = "Stop"

python scripts/v21/v21_139_multi_strategy_random_asof_backtest.py
pytest -q scripts/v21/test_v21_139_multi_strategy_random_asof_backtest.py
