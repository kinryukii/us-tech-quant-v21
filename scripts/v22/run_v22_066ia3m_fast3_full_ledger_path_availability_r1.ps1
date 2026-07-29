param([switch]$Execute);$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;& "$r\.venv\Scripts\python.exe" "$r\scripts\v22\v22_066ia3m_fast3_full_ledger_path_availability_r1.py" --execute
