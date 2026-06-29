$ErrorActionPreference = "Stop"

python scripts/v21/v21_135_abcde_same_date_forward_alignment.py
pytest -q scripts/v21/test_v21_135_abcde_same_date_forward_alignment.py
