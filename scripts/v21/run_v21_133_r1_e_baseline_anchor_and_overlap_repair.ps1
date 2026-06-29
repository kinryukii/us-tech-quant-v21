$ErrorActionPreference = "Stop"

python scripts/v21/v21_133_r1_e_baseline_anchor_and_overlap_repair.py
pytest -q scripts/v21/test_v21_133_r1_e_baseline_anchor_and_overlap_repair.py
