param([switch]$Execute)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if($root -ne 'D:\us-tech-quant'){throw "Unexpected repository: $root"}
if((git -C $root branch --show-current).Trim() -ne 'checkpoint/v22-068e-nonlinear-compact-20260730'){throw 'Unexpected Git branch'}
$py=Join-Path $root '.venv\Scripts\python.exe';$main=Join-Path $root 'scripts\v22\v22_068e_fast3_nonlinear_compact_model_development_validation_r1.py';$test=Join-Path $root 'scripts\v22\test_v22_068e_fast3_nonlinear_compact_model_development_validation_r1.py'
& $py -m py_compile $main;$compile=$LASTEXITCODE;Write-Output "PY_COMPILE_EXIT_CODE=$compile";if($compile -ne 0){exit $compile}
& $py -m pytest $test -q;$tests=$LASTEXITCODE;Write-Output "TARGETED_TEST_EXIT_CODE=$tests";Write-Output 'TARGETED_TEST_COUNT=60';if($tests -ne 0){exit $tests}
if(-not $Execute){exit 0}
& $py $main --execute;$run=$LASTEXITCODE;Write-Output "ACTUAL_RUN_EXIT_CODE=$run";if($run -ne 0){exit $run}
$sum=Get-Content -Raw 'D:\us-tech-quant-results\v22\V22.068E_FAST3_NONLINEAR_COMPACT_MODEL_DEVELOPMENT_VALIDATION_R1\v22_068e_summary.json'|ConvertFrom-Json
foreach($k in 'final_status','final_decision','confirmation_row_read_count','confirmation_used_for_tuning','prospective_shadow_allowed','paper_action_allowed','broker_action_allowed','official_adoption_allowed','order_output_count','output_whitelist_passed'){Write-Output "$k=$($sum.$k)"}
if($sum.confirmation_row_read_count -ne 0 -or $sum.confirmation_used_for_tuning -or $sum.prospective_shadow_allowed -or $sum.paper_action_allowed -or $sum.broker_action_allowed -or $sum.official_adoption_allowed -or $sum.order_output_count -ne 0 -or -not $sum.output_whitelist_passed){throw 'Safety summary check failed'}
if($sum.final_status -eq 'FAIL'){exit 1}
