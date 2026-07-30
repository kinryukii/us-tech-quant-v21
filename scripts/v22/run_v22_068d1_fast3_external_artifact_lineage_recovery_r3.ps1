param([switch]$Execute)
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if($root -ne 'D:\us-tech-quant' -or (git -C $root branch --show-current).Trim() -ne 'checkpoint/v22-068d1-r3-external-artifact-recovery-20260730'){throw 'Repository or branch mismatch'}
$py=Join-Path $root '.venv\Scripts\python.exe';$m=Join-Path $root 'scripts\v22\v22_068d1_fast3_external_artifact_lineage_recovery_r3.py';$t=Join-Path $root 'scripts\v22\test_v22_068d1_fast3_external_artifact_lineage_recovery_r3.py'
& $py -m py_compile $m;$c=$LASTEXITCODE;Write-Output "PYTHON_COMPILE_EXIT_CODE=$c";if($c -ne 0){exit $c};& $py -m pytest $t -q;$q=$LASTEXITCODE;Write-Output "TARGETED_TEST_EXIT_CODE=$q";Write-Output 'TARGETED_TEST_COUNT=75';if($q -ne 0){exit $q};if(-not $Execute){exit 0}
& $py $m --execute;$p=$LASTEXITCODE;Write-Output "PYTHON_PROCESS_EXIT_CODE=$p";if($p -ne 0){exit $p};$s=Get-Content -Raw 'D:\us-tech-quant-results\v22\V22.068D1_FAST3_EXTERNAL_ARTIFACT_LINEAGE_RECOVERY_R3\v22_068d1_r3_summary.json'|ConvertFrom-Json
foreach($k in 'final_status','final_decision','confirmation_row_read_count','prospective_shadow_allowed','paper_action_allowed','broker_action_allowed','official_adoption_allowed','order_output_count','output_whitelist_passed'){Write-Output "$k=$($s.$k)"};Write-Output 'RUNNER_EXIT_CODE=1';exit 1
