param([switch]$Execute)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop';$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if($root -ne 'D:\us-tech-quant'){throw 'Unexpected repository'};if((git -C $root branch --show-current).Trim() -ne 'checkpoint/v22-068d1-contract-and-v22-068e-r2-20260730'){throw 'Unexpected branch'}
$py=Join-Path $root '.venv\Scripts\python.exe';$main=Join-Path $root 'scripts\v22\v22_068d1_fast3_frozen_input_contract_builder_r1.py';$test=Join-Path $root 'scripts\v22\test_v22_068d1_fast3_frozen_input_contract_builder_r1.py'
& $py -m py_compile $main;$c=$LASTEXITCODE;Write-Output "PYTHON_COMPILE_EXIT_CODE=$c";if($c -ne 0){exit $c}
& $py -m pytest $test -q;$t=$LASTEXITCODE;Write-Output "TARGETED_TEST_EXIT_CODE=$t";Write-Output 'TARGETED_TEST_COUNT=55';if($t -ne 0){exit $t};if(-not $Execute){exit 0}
& $py $main --execute;$pp=$LASTEXITCODE;Write-Output "PYTHON_PROCESS_EXIT_CODE=$pp";if($pp -ne 0){exit $pp}
$s=Get-Content -Raw 'D:\us-tech-quant-results\v22\V22.068D1_FAST3_FROZEN_INPUT_CONTRACT_BUILDER_R1\v22_068d1_summary.json'|ConvertFrom-Json
foreach($k in 'final_status','final_decision','confirmation_row_read_count','prospective_shadow_allowed','paper_action_allowed','broker_action_allowed','official_adoption_allowed','order_output_count','output_whitelist_passed'){Write-Output "$k=$($s.$k)"}
if($s.confirmation_row_read_count -ne 0 -or $s.prospective_shadow_allowed -or $s.paper_action_allowed -or $s.broker_action_allowed -or $s.official_adoption_allowed -or $s.order_output_count -ne 0 -or -not $s.output_whitelist_passed){throw 'Safety check failed'}
Write-Output 'RUNNER_EXIT_CODE=1';exit 1
