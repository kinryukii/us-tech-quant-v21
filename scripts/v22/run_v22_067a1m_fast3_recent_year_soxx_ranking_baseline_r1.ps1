param([switch]$Execute)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m py_compile (Join-Path $root 'scripts\v22\v22_067a1m_fast3_recent_year_soxx_ranking_baseline_r1.py') 2>$null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pytest (Join-Path $root 'scripts\v22\test_v22_067a1m_fast3_recent_year_soxx_ranking_baseline_r1.py') -q *> $null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Execute) { & $python (Join-Path $root 'scripts\v22\v22_067a1m_fast3_recent_year_soxx_ranking_baseline_r1.py') --execute; exit $LASTEXITCODE }
