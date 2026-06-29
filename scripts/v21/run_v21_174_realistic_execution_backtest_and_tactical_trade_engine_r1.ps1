$ErrorActionPreference = "Stop"

python scripts/v21/v21_174_realistic_execution_backtest_and_tactical_trade_engine_r1.py
python -m pytest scripts/v21/test_v21_174_realistic_execution_backtest_and_tactical_trade_engine_r1.py -q

$outDir = "outputs/v21/V21.174_REALISTIC_EXECUTION_BACKTEST_AND_TACTICAL_TRADE_ENGINE_R1"
Get-Content "$outDir/V21.174_readable_report.txt"
Get-Content "$outDir/V21.174_execution_summary.json"
