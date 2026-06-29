$ErrorActionPreference = "Stop"

python scripts/v21/v21_140_extend_historical_price_panel_to_2020.py
pytest -q scripts/v21/test_v21_140_extend_historical_price_panel_to_2020.py
