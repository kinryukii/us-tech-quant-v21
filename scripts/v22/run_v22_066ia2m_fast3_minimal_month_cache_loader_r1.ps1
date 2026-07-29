param([switch]$Execute);$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;& "$r\.venv\Scripts\python.exe" "$r\scripts\v22\v22_066ia2m_fast3_minimal_month_cache_loader_r1.py" --execute
