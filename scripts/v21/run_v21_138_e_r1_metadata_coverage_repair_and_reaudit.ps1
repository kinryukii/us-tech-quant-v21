$ErrorActionPreference = "Stop"

python scripts/v21/v21_138_e_r1_metadata_coverage_repair_and_reaudit.py
pytest -q scripts/v21/test_v21_138_e_r1_metadata_coverage_repair_and_reaudit.py
