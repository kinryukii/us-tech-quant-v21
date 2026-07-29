param([switch]$Execute)
$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;$p=Join-Path $r '.venv\Scripts\python.exe';$s=Join-Path $r 'scripts\v22\v22_068_fast3_compact_multifactor_model_r1.py';$t=Join-Path $r 'scripts\v22\test_v22_068_fast3_compact_multifactor_model_r1.py'
& $p -m py_compile $s;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE};& $p -m pytest $t -q;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE};if($Execute){& $p $s --execute;exit $LASTEXITCODE}
