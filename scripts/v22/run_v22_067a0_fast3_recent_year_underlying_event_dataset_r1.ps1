param([switch]$Execute);$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;& "$r\.venv\Scripts\python.exe" "$r\scripts\v22\v22_067a0_fast3_recent_year_underlying_event_dataset_r1.py" --execute
