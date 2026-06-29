$ErrorActionPreference = "Stop"

python scripts/v21/v21_158_r1_switching_backtest_result_decomposition.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.158 R1 producer failed with exit code $LASTEXITCODE"
}

pytest -q scripts/v21/test_v21_158_r1_switching_backtest_result_decomposition.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.158 R1 validation failed with exit code $LASTEXITCODE"
}

Get-Content outputs/v21/V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION/V21.158_R1_readable_report.txt
Get-Content outputs/v21/V21.158_R1_SWITCHING_BACKTEST_RESULT_DECOMPOSITION/V21.158_R1_machine_summary.json
