$ErrorActionPreference = "Stop"

python scripts/v21/v21_161_r1_c_r2_proxy_and_regime_repair.py
pytest -q scripts/v21/test_v21_161_r1_c_r2_proxy_and_regime_repair.py

$outDir = "outputs/v21/V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR"
Get-Content "$outDir/V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_report.txt"
Get-Content "$outDir/V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_summary.json"
