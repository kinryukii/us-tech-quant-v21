$ErrorActionPreference='Stop'
$py='D:\us-tech-quant\.venv\Scripts\python.exe'; if(-not(Test-Path $py)){$py='python'}
& $py "$PSScriptRoot\v22_048_real_abcde_source_provenance_and_persistence.py" --execute
exit $LASTEXITCODE
