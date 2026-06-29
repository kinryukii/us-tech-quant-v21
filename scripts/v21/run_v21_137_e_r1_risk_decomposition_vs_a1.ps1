$ErrorActionPreference = "Stop"

python scripts/v21/v21_137_e_r1_risk_decomposition_vs_a1.py
pytest -q scripts/v21/test_v21_137_e_r1_risk_decomposition_vs_a1.py
