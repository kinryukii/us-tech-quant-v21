param([switch]$Execute)
$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path;$p=Join-Path $r '.venv\Scripts\python.exe'
& $p -m py_compile (Join-Path $r 'scripts\v22\v22_067b1a_fast3_soxx_long_0p50_economic_gate_consistency_audit_r1.py');if($LASTEXITCODE-ne 0){exit $LASTEXITCODE}
& $p -m pytest (Join-Path $r 'scripts\v22\test_v22_067b1a_fast3_soxx_long_0p50_economic_gate_consistency_audit_r1.py') -q;if($LASTEXITCODE-ne 0){exit $LASTEXITCODE}
if($Execute){& $p (Join-Path $r 'scripts\v22\v22_067b1a_fast3_soxx_long_0p50_economic_gate_consistency_audit_r1.py') --execute}
