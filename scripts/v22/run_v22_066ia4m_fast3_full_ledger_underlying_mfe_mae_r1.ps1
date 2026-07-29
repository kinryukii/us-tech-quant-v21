param([switch]$Execute);$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;& "$r\.venv\Scripts\python.exe" "$r\scripts\v22\v22_066ia4m_fast3_full_ledger_underlying_mfe_mae_r1.py" --execute
