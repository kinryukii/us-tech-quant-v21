param([switch]$Execute)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $root 'scripts\v22\v22_067b3p_fast3_soxx_long_0p50_prospective_shadow_r1.py'
$test = Join-Path $root 'scripts\v22\test_v22_067b3p_fast3_soxx_long_0p50_prospective_shadow_r1.py'
& $python -m py_compile $script 2>$null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pytest $test -q *> $null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Execute) { & $python $script --execute; exit $LASTEXITCODE }
