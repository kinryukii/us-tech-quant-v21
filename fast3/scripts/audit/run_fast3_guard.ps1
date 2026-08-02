$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
& python (Join-Path $PSScriptRoot 'run_fast3_guard.py') @args
exit $LASTEXITCODE
