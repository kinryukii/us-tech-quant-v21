$ErrorActionPreference = 'Stop'
python "$PSScriptRoot\r10b4_a_rawscore_real_forward_stability_ledger.py" --update-and-report
exit $LASTEXITCODE
