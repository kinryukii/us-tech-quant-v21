param([switch]$Execute)
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;$py=Join-Path $root '.venv\Scripts\python.exe'
$script=Join-Path $root 'scripts\v22\v22_067_fast3_multifactor_feature_atlas_r1.py';$test=Join-Path $root 'scripts\v22\test_v22_067_fast3_multifactor_feature_atlas_r1.py'
& $py -m py_compile $script;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE};& $py -m pytest $test -q;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE};if($Execute){& $py $script --execute;exit $LASTEXITCODE}
