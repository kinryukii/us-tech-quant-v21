$ErrorActionPreference = "Stop"

python scripts/v21/v21_182_dram_intraday_forward_tracking_ledger.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest scripts/v21/test_v21_182_dram_intraday_forward_tracking_ledger.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "outputs/v21/V21.182_DRAM_INTRADAY_FORWARD_TRACKING_LEDGER/V21.182_readable_report.txt"
Get-Content "outputs/v21/V21.182_DRAM_INTRADAY_FORWARD_TRACKING_LEDGER/manifest.json"
