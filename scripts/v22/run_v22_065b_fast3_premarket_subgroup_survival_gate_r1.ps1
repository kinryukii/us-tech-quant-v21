param([switch]$Execute)
$ErrorActionPreference='Stop'; Set-Location 'D:\us-tech-quant'
if(-not $Execute){throw 'The -Execute flag is required.'}
$p='.\.venv\Scripts\python.exe'; $s='.\scripts\v22\v22_065b_fast3_premarket_subgroup_survival_gate_r1.py'; $t='.\scripts\v22\test_v22_065b_fast3_premarket_subgroup_survival_gate_r1.py'
& $p -m py_compile $s $t; if($LASTEXITCODE -ne 0){throw 'PY_COMPILE failed'}
& $p -m pytest $t -q -p no:cacheprovider; if($LASTEXITCODE -ne 0){throw 'TEST failed'}
& $p $s --execute; if($LASTEXITCODE -ne 0){throw 'GATE failed'}
