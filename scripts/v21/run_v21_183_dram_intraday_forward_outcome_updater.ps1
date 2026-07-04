$ErrorActionPreference = "Stop"

python scripts/v21/v21_183_dram_intraday_forward_outcome_updater.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest scripts/v21/test_v21_183_dram_intraday_forward_outcome_updater.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "outputs/v21/V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER/V21.183_readable_report.txt"
Get-Content "outputs/v21/V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER/manifest.json"
