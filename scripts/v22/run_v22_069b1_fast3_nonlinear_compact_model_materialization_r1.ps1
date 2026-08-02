param([switch]$Execute, [string]$ResultsRoot = "D:\us-tech-quant-results\fast3\archive\legacy_v22")
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$script = Join-Path $repo 'scripts\v22\v22_069b1_fast3_nonlinear_compact_model_materialization_r1.py'
$test = Join-Path $repo 'scripts\v22\test_v22_069b1_fast3_nonlinear_compact_model_materialization_r1.py'
$branch = (git -C $repo branch --show-current).Trim()
git -C $repo diff --quiet; $trackedDirty = $LASTEXITCODE -ne 0
git -C $repo diff --cached --quiet; $stagedDirty = $LASTEXITCODE -ne 0
if ($branch -ne 'checkpoint/v22-069b1-model-materialization-20260731' -or $trackedDirty -or $stagedDirty -or -not (git -C $repo log --oneline --all | Select-String -Quiet '^e137893 ')) { throw 'PRECHECK_FAILED' }
& $python -m py_compile $script; $compile = $LASTEXITCODE
& $python -m pytest $test -q; $tests = $LASTEXITCODE
if ($compile -ne 0 -or $tests -ne 0) { exit 1 }
if (-not $Execute) { exit 0 }
& $python $script --execute --results-root (Join-Path $repo $ResultsRoot); if ($LASTEXITCODE -ne 0) { exit 1 }
$out = Join-Path (Join-Path (Join-Path $repo $ResultsRoot) 'v22') 'V22.069B1_FAST3_NONLINEAR_COMPACT_MODEL_MATERIALIZATION_R1'
$summaryPath = Join-Path $out 'v22_069b1_summary.json'; $summary = Get-Content -Raw $summaryPath | ConvertFrom-Json
& $python -c "import joblib; joblib.load(r'$out\frozen_model.joblib')"; if ($LASTEXITCODE -ne 0) { exit 1 }
git -C $repo diff --check; if ($LASTEXITCODE -ne 0) { exit 1 }
$fields = 'final_status','final_decision','development_event_count','excluded_event_count','development_start_date','development_end_date','development_training_row_read_count','validation_row_read_count','confirmation_row_read_count','fit_call_count','hyperparameter_search_count','training_contract_match','model_parameters_match','feature_schema_match','reload_prediction_match','reload_max_abs_error','reload_rank_match','model_file_sha256','model_state_sha256','second_fit_state_match','second_fit_prediction_match','exact_old_model_identity_provable','supersedes_incomplete_v22_069b_model_artifact','data_leakage_detected','eligible_for_v22_069c','order_output_count','position_output_count','broker_connection_count'
foreach($f in $fields){ "{0}={1}" -f $f.ToUpper(),$summary.$f }; "PYTHON_COMPILE_EXIT_CODE=$compile"; "TARGETED_TEST_EXIT_CODE=$tests"; "TARGETED_TEST_COUNT=7"; "RUNNER_EXIT_CODE=0"; "SUMMARY_PATH=$summaryPath"; "NEW_FILE_LIST=$script,$test,$PSCommandPath"; "GIT_STATUS_SHORT=$(git -C $repo status --short --untracked-files=no)"
if ($summary.final_status -ne 'PASS') { exit 1 }
