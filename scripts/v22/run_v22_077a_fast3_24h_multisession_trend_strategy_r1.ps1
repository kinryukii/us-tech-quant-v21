$ErrorActionPreference='Stop'
$root=(Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root
$branch=git branch --show-current
if($branch -ne 'checkpoint/v22-077a-24h-multisession-trend-strategy-20260731'){throw "BRANCH_MISMATCH=$branch"}
if(-not (git log --format='%H' -1 03b88cb)){throw 'BASELINE_03b88cb_MISSING'}
if(git status --short){throw 'WORKTREE_NOT_CLEAN'}
python -m py_compile scripts/v22/v22_077a_fast3_24h_multisession_trend_strategy_r1.py; $compile=$LASTEXITCODE
$tmp=Join-Path $env:TEMP 'v22_077a_pytest'; python -m pytest scripts/v22/test_v22_077a_fast3_24h_multisession_trend_strategy_r1.py -q --basetemp $tmp; $test=$LASTEXITCODE
if($test -ne 0){throw "TARGETED_TEST_EXIT_CODE=$test"}
python scripts/v22/v22_077a_fast3_24h_multisession_trend_strategy_r1.py; $run=$LASTEXITCODE
$out='D:\us-tech-quant-results\fast3\archive\legacy_v22\V22.077A_FAST3_24H_MULTI_SESSION_TREND_STRATEGY_R1'; $s=Get-Content (Join-Path $out 'v22_077a_summary.json') -Raw | ConvertFrom-Json
"FINAL_STATUS=$($s.final_status)"; "FINAL_DECISION=$($s.final_decision)"; "PYTHON_COMPILE_EXIT_CODE=$compile"; "TARGETED_TEST_EXIT_CODE=$test"; 'TARGETED_TEST_COUNT=13'; "RUNNER_EXIT_CODE=$run"; "RESEARCH_TRADING_DATE_COUNT=$($s.research_trading_date_count)"; "SESSION_CONTRACT_SOURCE=$($s.session_contract_source)"; "TRADING_DATE_MAPPING_SOURCE=$($s.trading_date_mapping_source)"; "CANDIDATE_COUNT=$($s.candidate_count)"; "VALID_FOLD_COUNT=$($s.valid_fold_count)"; "INVALID_FOLD_COUNT=$($s.invalid_fold_count)"; "TIME_ORDER_VIOLATION_COUNT=$($s.time_order_violation_count)"
foreach($c in 'S1_E1','S1_E2','S2_E1','S2_E2','S3_E1','S3_E2'){foreach($k in 'trade_count','mean_net_return_at_25bps','profit_factor_at_25bps','maximum_drawdown_at_25bps'){"${c}_$($k.ToUpper())=$($s.($c+'_'+$k))"}}
"BEST_CANDIDATE=$($s.best_candidate)"; "SELECTED_SIGNAL_STRATEGY=$($s.selected_signal_strategy)"; "SELECTED_EXIT_STRATEGY=$($s.selected_exit_strategy)"; "NEXT_FREEZE_STAGE_ALLOWED=$($s.next_freeze_stage_allowed)"; "FAST3_24H_RESEARCH_STOPPED=$($s.fast3_24h_research_stopped)"; "CONFIRMATION_REMAINS_SEALED=$($s.confirmation_remains_sealed)"; "CONFIRMATION_ROW_READ_COUNT=$($s.confirmation_row_read_count)"; "MODEL_FIT_CALL_COUNT=$($s.model_fit_call_count)"; "HYPERPARAMETER_SEARCH_COUNT=$($s.hyperparameter_search_count)"; "FINAL_FROZEN_MODEL_OUTPUT_COUNT=$($s.final_frozen_model_output_count)"; "DATA_LEAKAGE_DETECTED=$($s.data_leakage_detected)"; "ORDER_OUTPUT_COUNT=$($s.order_output_count)"; "SUMMARY_PATH=$(Join-Path $out 'v22_077a_summary.json')"; 'NEW_FILE_LIST=scripts/v22/v22_077a_fast3_24h_multisession_trend_strategy_r1.py,scripts/v22/test_v22_077a_fast3_24h_multisession_trend_strategy_r1.py,scripts/v22/run_v22_077a_fast3_24h_multisession_trend_strategy_r1.ps1'; 'GIT_STATUS_SHORT='; git status --short
