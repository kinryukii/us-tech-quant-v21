$ErrorActionPreference = "Stop"

python scripts/v21/v21_133_e_conservative_adaptive_momentum_r1.py
pytest -q scripts/v21/test_v21_133_e_conservative_adaptive_momentum_r1.py
