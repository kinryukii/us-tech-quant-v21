param([switch]$Execute)
$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$p=Join-Path $r '.venv\Scripts\python.exe';$m=Join-Path $r 'scripts\v22\v22_069b_fast3_nonlinear_compact_development_r1.py';$t=Join-Path $r 'scripts\v22\test_v22_069b_fast3_nonlinear_compact_development_r1.py'
& $p -m py_compile $m;if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& $p -m pytest $t -q;if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
if($Execute){& $p $m --execute;$code=$LASTEXITCODE;if($code -ne 0){exit $code};$summary=Get-Content -Raw (Join-Path $r '.local_results\v22\V22.069B_FAST3_NONLINEAR_COMPACT_DEVELOPMENT_R1\summary.json')|ConvertFrom-Json;if($summary.final_status -ne 'PASS'){exit 1}}
