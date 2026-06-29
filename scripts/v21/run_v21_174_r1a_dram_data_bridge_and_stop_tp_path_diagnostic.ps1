$ErrorActionPreference = "Stop"

python scripts/v21/v21_174_r1a_dram_data_bridge_and_stop_tp_path_diagnostic.py
python -m pytest scripts/v21/test_v21_174_r1a_dram_data_bridge_and_stop_tp_path_diagnostic.py -q

$outDir = "outputs/v21/V21.174_R1A_DRAM_DATA_BRIDGE_AND_STOP_TP_PATH_DIAGNOSTIC"
Get-Content "$outDir/V21.174_R1A_readable_report.txt"
Get-Content "$outDir/V21.174_R1A_summary.json"
