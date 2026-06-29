$ErrorActionPreference = "Stop"

python scripts/v21/v21_158_conditional_switching_random_backtest_vs_strategies_and_qqq.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.158 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_158_conditional_switching_random_backtest_vs_strategies_and_qqq.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.158 validation failed with exit code $LASTEXITCODE"
}

Get-Content outputs/v21/V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ/V21.158_readable_report.txt
Get-Content outputs/v21/V21.158_CONDITIONAL_SWITCHING_RANDOM_BACKTEST_VS_STRATEGIES_AND_QQQ/V21.158_machine_summary.json
