$ErrorActionPreference = "Stop"

python scripts/v21/v21_180_dram_intraday_confirmation_snapshot_runner.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest scripts/v21/test_v21_180_dram_intraday_confirmation_snapshot_runner.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "outputs/v21/V21.180_DRAM_INTRADAY_CONFIRMATION_SNAPSHOT_RUNNER/V21.180_readable_report.txt"
Get-Content "outputs/v21/V21.180_DRAM_INTRADAY_CONFIRMATION_SNAPSHOT_RUNNER/manifest.json"
