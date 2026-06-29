$ErrorActionPreference = "Stop"

python scripts/v21/v21_163_c_r2_ai_bottleneck_switch_controller.py
pytest -q scripts/v21/test_v21_163_c_r2_ai_bottleneck_switch_controller.py

$outDir = "outputs/v21/V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER"
Get-Content "$outDir/V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_report.txt"
Get-Content "$outDir/V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER_summary.json"
