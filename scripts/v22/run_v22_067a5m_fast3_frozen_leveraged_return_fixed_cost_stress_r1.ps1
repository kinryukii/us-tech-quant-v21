param([switch]$Execute)
$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;$p=Join-Path $r '.venv\Scripts\python.exe'
& $p -m py_compile (Join-Path $r 'scripts\v22\v22_067a5m_fast3_frozen_leveraged_return_fixed_cost_stress_r1.py') 2>$null;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE}
& $p -m pytest (Join-Path $r 'scripts\v22\test_v22_067a5m_fast3_frozen_leveraged_return_fixed_cost_stress_r1.py') -q *> $null;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE}
if($Execute){& $p (Join-Path $r 'scripts\v22\v22_067a5m_fast3_frozen_leveraged_return_fixed_cost_stress_r1.py') --execute;exit $LASTEXITCODE}
