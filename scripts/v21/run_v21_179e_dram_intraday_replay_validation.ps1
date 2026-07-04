$ErrorActionPreference = "Stop"

python scripts/v21/v21_179e_dram_intraday_replay_validation.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest scripts/v21/test_v21_179e_dram_intraday_replay_validation.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Get-Content "outputs/v21/V21.179E_DRAM_INTRADAY_REPLAY_VALIDATION/V21.179E_readable_report.txt"
Get-Content "outputs/v21/V21.179E_DRAM_INTRADAY_REPLAY_VALIDATION/manifest.json"
