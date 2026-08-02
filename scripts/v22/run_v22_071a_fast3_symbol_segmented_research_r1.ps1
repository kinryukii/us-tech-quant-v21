param([switch]$Execute,[string]$ResultsRoot='D:\us-tech-quant-results\fast3\archive\legacy_v22')
$ErrorActionPreference='Stop'
$r=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$p=Join-Path $r '.venv\Scripts\python.exe'
$m=Join-Path $r 'scripts\v22\v22_071a_fast3_symbol_segmented_research_r1.py'
$t=Join-Path $r 'scripts\v22\test_v22_071a_fast3_symbol_segmented_research_r1.py'
if((git -C $r branch --show-current).Trim() -ne 'checkpoint/v22-071a-symbol-segmented-research-20260731'){throw 'BRANCH_MISMATCH'}
$allowed=@('?? scripts/v22/v22_071a_fast3_symbol_segmented_research_r1.py','?? scripts/v22/test_v22_071a_fast3_symbol_segmented_research_r1.py','?? scripts/v22/run_v22_071a_fast3_symbol_segmented_research_r1.ps1')
$initial=@(git -C $r status --short);if(@($initial|Where-Object {$_ -notin $allowed}).Count){throw 'WORKTREE_NOT_CLEAN'}
& $p -m py_compile $m; $compile=$LASTEXITCODE; "PYTHON_COMPILE_EXIT_CODE=$compile"; if($compile){exit $compile}
& $p -m pytest $t -q; $tests=$LASTEXITCODE; "TARGETED_TEST_EXIT_CODE=$tests"; "TARGETED_TEST_COUNT=9"; if($tests){exit $tests}
if(-not $Execute){exit 0}
& $p $m --execute --results-root (Join-Path $r $ResultsRoot); $run=$LASTEXITCODE; "RUNNER_EXIT_CODE=$run"; if($run){exit $run}
$out=Join-Path (Join-Path (Join-Path $r $ResultsRoot) 'v22') 'V22.071A_FAST3_SYMBOL_SEGMENTED_RESEARCH_R1'
foreach($f in 'v22_071a_summary.json','model_scorecard.csv','symbol_scorecard.csv','fold_scorecard.csv','research_contract.json'){if(-not (Test-Path (Join-Path $out $f))){throw "MISSING_OUTPUT:$f"}}
$s=Get-Content -Raw (Join-Path $out 'v22_071a_summary.json') | ConvertFrom-Json
if($s.confirmation_row_read_count -ne 0 -or $s.final_frozen_model_output_count -ne 0 -or $s.order_output_count -ne 0 -or $s.data_leakage_detected -or $s.time_order_violation_count -ne 0){throw 'INTEGRITY_CHECK_FAILED'}
foreach($k in 'final_status','final_decision','research_event_count','former_development_event_count','former_validation_event_count','valid_fold_count','invalid_fold_count','time_order_violation_count','pooled_best_model','pooled_best_oof_spearman_ic','pooled_best_net_spread_10bps','segmented_best_model','segmented_best_oof_spearman_ic','segmented_best_net_spread_10bps','positive_symbol_count','negative_symbol_count','single_symbol_contribution_ratio','selected_structure','selected_model','next_freeze_stage_allowed','hyperparameter_search_count','research_fit_call_count','final_frozen_model_output_count','confirmation_remains_sealed','confirmation_row_read_count','data_leakage_detected','order_output_count'){"$($k.ToUpper())=$($s.$k)"}
"SUMMARY_PATH=$(Join-Path $out 'v22_071a_summary.json')"
"NEW_FILE_LIST=scripts/v22/v22_071a_fast3_symbol_segmented_research_r1.py;scripts/v22/test_v22_071a_fast3_symbol_segmented_research_r1.py;scripts/v22/run_v22_071a_fast3_symbol_segmented_research_r1.ps1"
git -C $r diff --check; if($LASTEXITCODE){exit 1}
$old=$ErrorActionPreference;$ErrorActionPreference='Continue';$status=git -C $r status --short 2>&1;$ErrorActionPreference=$old;"GIT_STATUS_SHORT=$($status -join '; ')"
