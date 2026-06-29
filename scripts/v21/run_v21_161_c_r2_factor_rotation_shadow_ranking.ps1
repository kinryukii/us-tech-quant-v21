$ErrorActionPreference = "Stop"

python scripts/v21/v21_161_c_r2_factor_rotation_shadow_ranking.py
pytest -q scripts/v21/test_v21_161_c_r2_factor_rotation_shadow_ranking.py

$outDir = "outputs/v21/V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING"
Get-Content "$outDir/V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING_report.txt"
Get-Content "$outDir/V21.161_C_R2_FACTOR_ROTATION_SHADOW_RANKING_summary.json"
