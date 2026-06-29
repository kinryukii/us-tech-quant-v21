$ErrorActionPreference = "Stop"

python scripts/v21/v21_134_e_r1_forward_tracking_ledger.py
pytest -q scripts/v21/test_v21_134_e_r1_forward_tracking_ledger.py
