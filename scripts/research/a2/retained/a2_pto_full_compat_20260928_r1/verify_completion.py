"""Final exact-list, sealed-ledger and preserved-source checks. Never learn."""
from common import *
from freeze_all import verify_freeze
from datetime import datetime,timezone

def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def require(ok,reason):
    if not ok:raise RuntimeError(reason)

def require_base_final_receipt(proof,freeze):
    status='PASS_DIAGNOSTIC_FORMAL_FULL_POOL_BLOCKED'
    require(proof['status']==status,'BASE_FINAL_PREDICTION_PROOF')
    require(proof['members_verified']==len(MEMBERS)==31 and proof['prediction_files_verified']==62,'BASE_FINAL_PREDICTION_COUNTS')
    require(proof['context_keys_per_member']==62475 and proof['full_candidate_keys_per_member']==111868 and proof['original_unknown_keys_per_member']==47271,'BASE_FINAL_PREDICTION_SUPPORT')
    require(proof['unknown_promoted']==proof['fit_calls']==proof['learning_update_calls']==0,'BASE_FINAL_PREDICTION_SCOPE')
    require(proof['freeze_hashes_verified_before']==proof['freeze_hashes_verified_after']==len(freeze['artifact_sha256'])==663,'BASE_FINAL_PREDICTION_FREEZE')
    require(proof['formal_full_pool_selection_allowed'] is False and proof['evaluation_scope']=='QUALIFIED_CONTEXT_DIAGNOSTIC','BASE_FINAL_PREDICTION_FORMAL_BOUNDARY')
    require(proof['typed_interfaces_verified'] is True and proof['rank_or_quantiles_have_fabricated_mu'] is False and proof['probability_train_amplitude_mapping_verified'] is True and proof['raw_quantiles_reordered'] is False,'BASE_FINAL_TYPED_INTERFACES')
    rows=proof['member_diagnostics']
    require(len(rows)==31 and {r['member'] for r in rows}==set(MEMBERS),'BASE_FINAL_PREDICTION_MEMBER_KEYS')
    for r in rows:
        require(r['status']==status and r['context_keys']==62475 and r['full_keys']==111868,'BASE_FINAL_MEMBER_STATUS_OR_SUPPORT')
        require(r['original_unknown_keys']==47271 and r['blocked_current_unknown_keys']==47272 and r['proven_ineligible_keys']==2204 and r['qualified_full_prediction_keys']==62392 and r['holding_only_context_keys']==83,'BASE_FINAL_MEMBER_QUALIFICATION')
    files={f'predictions/base/final/{prefix}{m}.parquet' for m in MEMBERS for prefix in ['', 'fullkeys/']}
    require({name.replace('\\','/') for name in proof['prediction_output_sha256']}==files,'BASE_FINAL_PREDICTION_FILE_KEYS')

def main():
    freeze=verify_freeze();old_sources={};output_hashes={};expected={p['strategy'] for p in registry()[1]}
    for name in ['PRE_DATA_RECEIPT','TEST_DATA_RECEIPT']:
        r=read(f'data/{name}.json')
        for path,h in r['input_sha256'].items():
            if str(ROOT) not in path:old_sources[path]=h
        for file,h in r['output_sha256'].items():require(sha(ROOT/'data'/file)==h,'INPUT_OUTPUT_CHANGED:'+file)
    audit=read('audits/DATA_CONTRACT_VERIFICATION.json');old_sources.update(audit['read_only_source_sha256'])
    for stage in ['validation','final']:old_sources.update(read(f'models/rl/{stage}/TRAIN_RECEIPT.json')['source_sha256'])
    old_sources={p:h for p,h in old_sources.items() if not Path(p).resolve().is_relative_to(ROOT)}
    for path,h in old_sources.items():require(sha(path)==h,'OLD_SOURCE_CHANGED:'+path)
    account_days=0;solver_failures=0;batch_count=0
    for year in [2025,2026]:
        seen=[]
        for i in range(36):
            folder=ROOT/f'results/{year}/batch_{i:03d}';r=read(str(folder.relative_to(ROOT)/'COMPLETE.json'))
            require(r['status']=='REPLAYED','REGISTERED_BATCH_NOT_REPLAYED')
            require(r['accounts']==308 and r['new_fit_calls']==0,'REGISTERED_BATCH_CONTRACT')
            for file,key in [('metadata.json','metadata_sha256'),('SUMMARY.csv','summary_sha256')]:
                require(sha(folder/file)==r[key],'SEALED_BATCH_OUTPUT_CHANGED')
                output_hashes[str((folder/file).relative_to(ROOT))]=r[key]
            require(r['policy_sha256']==freeze['artifact_sha256']['policy.py'] and r['engine_sha256']==freeze['artifact_sha256']['batch_engine.py'],'ACCOUNT_IMPLEMENTATION_CHANGED')
            seen+=r['strategies'];account_days+=r['accounts']*r['days'];batch_count+=1
            solver_failures+=len(read(str(folder.relative_to(ROOT)/'POLICY_RECEIPT.json'))['failures'])
        require(len(seen)==11088 and len(set(seen))==11088 and set(seen)==expected,'EXACT_REGISTERED_ACCOUNT_COVERAGE_FAILED')
    iv=read('INDEPENDENT_VERIFICATION.json')
    require(iv['status']=='PASS_COMPLETE' and iv['coverage_complete'],'INDEPENDENT_ACCOUNT_PROOF_INCOMPLETE')
    for year in ['2025','2026']:require(iv['years'][year]['verified_accounts']==11088,'INDEPENDENT_ACCOUNT_COVERAGE')
    require(read('audits/RL_EVALUATION_VERIFICATION.json')['status']=='PASS','RL_ACCOUNT_PROOF')
    require(read('analysis/ANALYSIS_RECEIPT.json')['complete'],'ALL_RESULT_ANALYSIS_INCOMPLETE')
    coverage=pd.read_csv(ROOT/'analysis/COMBINATION_COVERAGE.csv')
    require(len(coverage)==22176 and not coverage.duplicated(['year','strategy']).any(),'COVERAGE_TABLE_EXACT_KEYS')
    require(not coverage.status.isin(['NOT_EXECUTED','FAILED']).any(),'UNFINISHED_REGISTERED_PATH')
    require(set(zip(coverage.year,coverage.strategy))=={(year,s) for year in [2025,2026] for s in expected},'COVERAGE_REGISTERED_YEAR_KEYS')
    formal=pd.read_csv(ROOT/'analysis/FORMAL_FULL_POOL_COVERAGE.csv')
    require(len(formal)==11088 and set(formal.strategy)==expected and formal.year.eq(2026).all(),'FORMAL_FULL_POOL_EXACT_KEYS')
    require(formal.status.eq('BLOCKED_DATA').all() and formal.current_unknown_security_days.eq(47272).all(),'FORMAL_FULL_POOL_BOUNDARY_CHANGED')
    table=pd.read_csv(ROOT/'analysis/ALL_POSITIVE_NEGATIVE_RESULTS.csv')
    require(len(table)==22176 and not table.duplicated(['year','strategy']).any(),'ALL_RESULTS_EXACT_KEYS')
    primary=['indicative_return','indicative_max_drawdown','mean_gross_exposure','mean_cash','fees','half_turnover','uncertified_days']
    require(np.isfinite(table[primary].to_numpy(float)).all(),'REGISTERED_ACCOUNT_PRIMARY_METRIC_NONFINITE')
    for year in [2025,2026]:require(set(table.loc[table.year.eq(year),'strategy'])==expected,'ALL_RESULTS_REGISTERED_KEYS')
    require(len(pd.read_csv(ROOT/'analysis/RL_RESULTS.csv'))==8,'ALL_RL_RESULTS')
    base_proof=read('predictions/base/final/VERIFICATION.json')
    require_base_final_receipt(base_proof,freeze)
    require(base_proof['verifier_sha256']==sha(ROOT/'predictions/base/verify_frozen_final.py'),'BASE_FINAL_VERIFIER_CHANGED')
    require(base_proof['coverage_sha256']==sha(ROOT/'predictions/base/final/FINAL_PREDICTION_COVERAGE.csv'),'BASE_FINAL_COVERAGE_CHANGED')
    for file,h in base_proof['prediction_output_sha256'].items():require(sha(ROOT/file)==h,'BASE_FINAL_PREDICTION_CHANGED:'+file)
    require(read('predictions/streams/final/FROZEN_FULLKEY_RECEIPT.json')['status']=='PASS_ALL75_FROZEN_STREAMS','FINAL_STREAM_COVERAGE')
    require(read('data/TEST_DATA_VERIFICATION.json')['status'].startswith('PASS'),'TEST_DATA_PROOF')
    experts=read('analysis/TARGET_FUSION_DECISION_RECEIPT.json')
    require(experts['complete'] and experts['observed_expert_rows']==experts['expected_expert_rows']==7488,'TARGET_EXPERT_COVERAGE_INCOMPLETE')
    require(experts['observed_target_account_rows']==experts['expected_target_account_rows']==576,'TARGET_ACCOUNT_COVERAGE_INCOMPLETE')
    require(experts['status']=='COMPLETE_SAME_ACCOUNT_TARGET_CONTRIBUTIONS' and experts['pending_expert_rows']==0,'TARGET_EXPERT_STATUS_INCOMPLETE')
    require(experts['completed_batches']=={'2025':36,'2026':36},'TARGET_BATCH_COVERAGE_INCOMPLETE')
    require(experts['producer_sha256']==sha(ROOT/'target_expert_analysis.py') and experts['registry_sha256']==sha(ROOT/'REGISTRY.json') and experts['freeze_sha256']==sha(ROOT/'FREEZE.json'),'TARGET_ANALYSIS_IMPLEMENTATION_CHANGED')
    require(experts['fit_calls']==experts['new_candidates']==experts['hypothetical_expert_accounts_created']==0,'TARGET_ANALYSIS_SCOPE_CHANGED')
    for file,h in experts['output_sha256'].items():require(sha(ROOT/'analysis'/file)==h,'TARGET_ANALYSIS_CHANGED:'+file)
    target_names={p['strategy'] for p in registry()[1] if p['target_fusion']!='none'}
    expert_table=pd.read_csv(ROOT/'analysis/TARGET_EXPERT_CONTRIBUTIONS.csv')
    target_table=pd.read_csv(ROOT/'analysis/TARGET_FUSION_DECISION_SUMMARY.csv')
    require(len(expert_table)==7488 and set(zip(expert_table.year,expert_table.strategy,expert_table.member))=={(y,s,m) for y in [2025,2026] for s in target_names for m in POINT},'TARGET_EXPERT_EXACT_KEYS')
    require(len(target_table)==576 and set(zip(target_table.year,target_table.strategy))=={(y,s) for y in [2025,2026] for s in target_names},'TARGET_DECISION_EXACT_KEYS')
    require(expert_table.coverage_status.eq('OBSERVED_COMPLETE_BATCH').all() and target_table.coverage_status.eq('OBSERVED_COMPLETE_BATCH').all(),'TARGET_EXPERT_PENDING_ROWS')
    quality=read('analysis/SOLVER_QUALITY_RECEIPT.json')
    require(quality['complete'] and quality['status']=='PASS_ALL22176_STRATEGIES_7488_EXPERTS','SOLVER_QUALITY_PROOF_INCOMPLETE')
    require(quality['observed_strategy_rows']==quality['registered_strategy_rows']==22176 and quality['pending_strategy_rows']==0,'SOLVER_QUALITY_STRATEGY_COVERAGE')
    require(quality['observed_target_expert_rows']==quality['registered_target_expert_rows']==7488 and quality['pending_target_expert_rows']==0,'SOLVER_QUALITY_EXPERT_COVERAGE')
    require(quality['sealed_batches_scanned']==72 and quality['strategy_exact_keys_verified'] and quality['target_expert_exact_keys_verified'],'SOLVER_QUALITY_EXACT_KEYS')
    require(quality['all_scanned_batch_policy_counts_close'] and quality['all_independent_batch_counts_close'],'SOLVER_QUALITY_COUNTS_NOT_CLOSED')
    require(quality['producer_sha256']==sha(ROOT/'solver_quality_analysis.py'),'SOLVER_QUALITY_IMPLEMENTATION_CHANGED')
    require(all(quality[field]==0 for field in ['fit_calls','learning_update_calls','tuning_calls','optimization_calls','selection_calls','performance_ranking_files_read']),'SOLVER_QUALITY_SCOPE_CHANGED')
    require(not quality['source_policy_or_engine_imported'],'SOLVER_QUALITY_IMPORTED_POLICY_OR_ENGINE')
    for file,h in quality['source_sha256'].items():require(sha(ROOT/file)==h,'SOLVER_QUALITY_SOURCE_CHANGED:'+file)
    for file,h in quality['output_sha256'].items():require(sha(ROOT/'analysis'/file)==h,'SOLVER_QUALITY_OUTPUT_CHANGED:'+file)
    qtable=pd.read_csv(ROOT/'analysis/SOLVER_QUALITY_BY_STRATEGY.csv')
    qexperts=pd.read_csv(ROOT/'analysis/SOLVER_QUALITY_BY_TARGET_EXPERT.csv')
    require(len(qtable)==22176 and set(zip(qtable.year,qtable.strategy))=={(y,s) for y in [2025,2026] for s in expected},'SOLVER_QUALITY_STRATEGY_EXACT_KEYS')
    require(len(qexperts)==7488 and set(zip(qexperts.year,qexperts.target_strategy,qexperts.expert_member))=={(y,s,m) for y in [2025,2026] for s in target_names for m in POINT},'SOLVER_QUALITY_EXPERT_EXACT_KEYS')
    require(qtable.observation_status.eq('OBSERVED_COMPLETE_BATCH').all() and qexperts.observation_status.eq('OBSERVED_COMPLETE_BATCH').all(),'SOLVER_QUALITY_PENDING_ROWS')
    require(qtable.counts_are_observed.eq(True).all() and qexperts.counts_are_observed.eq(True).all(),'SOLVER_QUALITY_UNOBSERVED_COUNT')
    effects=read('analysis/EFFECTS_SUMMARY.json')
    require(effects['status']=='COMPLETE_REGISTERED_DESCRIPTIVE_EFFECTS' and effects['analysis_rows']==effects['registered_year_strategy_keys']==22176,'EFFECTS_ANALYSIS_INCOMPLETE')
    require(effects['figure_count']==17 and effects['all_registered_methods_included'],'ALL_REGISTERED_FIGURES_INCOMPLETE')
    require(effects['producer_sha256']==sha(ROOT/'figures.py'),'FIGURE_IMPLEMENTATION_CHANGED')
    figure_stems={'all_axes_return_actual_exposure'}|{f'{prefix}_{y}_{axis}' for prefix in ['fusion_effects','risk_optimizer_effects_interactions'] for y in [2025,2026] for axis in AXES}
    figure_names={f'analysis/figures/{stem}.{suffix}' for stem in figure_stems for suffix in ['png','pdf']}
    require({str(p).replace('\\','/') for p in effects['figures']}==figure_names,'FIGURE_EXACT_REGISTERED_FILES')
    require({str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'analysis/figures').iterdir() if p.suffix in ['.png','.pdf']}==figure_names,'FIGURE_DIRECTORY_EXACT_FILES')
    require(effects['training_calls']==effects['new_strategy_calls']==effects['selection_or_tuning_calls']==0,'EFFECTS_SCOPE_CHANGED')
    for file,h in {**effects['source_sha256'],**effects['figures']}.items():require(sha(ROOT/file)==h,'EFFECTS_SOURCE_OR_FIGURE_CHANGED:'+file)
    visual=read('analysis/FIGURE_VISUAL_QA.json')
    require(visual['status']=='PASS_INSPECTED_ALL17' and visual['inspected_png_count']==17,'PRODUCTION_FIGURES_NOT_VISUALLY_INSPECTED')
    require(visual['producer_sha256']==sha(ROOT/'figures.py'),'VISUALLY_INSPECTED_FIGURE_IMPLEMENTATION_CHANGED')
    png_names={f'analysis/figures/{stem}.png' for stem in figure_stems}
    require({str(p).replace('\\','/') for p in visual['inspected_png_sha256']}==png_names,'VISUAL_QA_EXACT_PNG_FILES')
    for file,h in visual['inspected_png_sha256'].items():require(sha(ROOT/file)==h,'VISUALLY_INSPECTED_FIGURE_CHANGED:'+file)
    raw=pd.read_csv(ROOT/'analysis/RAW_PREDICTION_DIAGNOSTICS.csv')
    require(len(raw)==62 and not raw.duplicated(['year','member']).any(),'RAW_TYPED_DIAGNOSTICS_INCOMPLETE')
    require(set(zip(raw.year,raw.member))=={(y,m) for y in [2025,2026] for m in MEMBERS},'RAW_TYPED_DIAGNOSTIC_EXACT_KEYS')
    inclusive=pd.read_csv(ROOT/'analysis/RAW_PREDICTION_DIAGNOSTICS_INCLUSIVE_EXTREME_HINTS.csv')
    require(len(inclusive)==62 and set(zip(inclusive.year,inclusive.member))=={(y,m) for y in [2025,2026] for m in MEMBERS},'INCLUSIVE_RAW_TYPED_DIAGNOSTIC_EXACT_KEYS')
    streams=read('analysis/STREAM_PREDICTION_DIAGNOSTICS_RECEIPT.json')
    require(streams['status']=='PASS_ALL150_FROZEN_STREAM_DIAGNOSTICS' and streams['analysis_rows']==150,'STREAM_DIAGNOSTIC_COVERAGE_INCOMPLETE')
    require(streams['fit_calls']==streams['learning_update_calls']==streams['selection_or_tuning_calls']==streams['account_result_files_read']==0,'STREAM_DIAGNOSTIC_SCOPE_CHANGED')
    for file,h in streams['source_sha256'].items():require(sha(ROOT/file)==h,'STREAM_DIAGNOSTIC_SOURCE_CHANGED:'+file)
    for file,h in streams['output_sha256'].items():require(sha(ROOT/'analysis'/file)==h,'STREAM_DIAGNOSTIC_OUTPUT_CHANGED:'+file)
    rl_table=pd.read_csv(ROOT/'analysis/RL_RESULTS.csv')
    require(set(zip(rl_table.year,rl_table.policy))=={(y,p) for y in [2025,2026] for p in ['reinforce_updated','reinforce_zero','ppo_updated','ppo_zero']},'RL_RESULT_EXACT_KEYS')
    for axis in AXES:require((ROOT/f'analysis/COMPARISON_{axis.upper()}.md').exists(),'AXIS_REPORT_MISSING:'+axis)
    verify_freeze()
    record={'status':'COMPLETE_REGISTERED_DIAGNOSTICS_FORMAL_FULL_POOL_BLOCKED_DATA',
        'created_utc':datetime.now(timezone.utc).isoformat(),'registered_pto_paths_per_window':11088,
        'actual_pto_accounts':22176,'actual_pto_account_days':account_days,'rl_accounts':8,'sealed_pto_batches':batch_count,
        'whole_batch_frozen_before_2026_inference':True,'frozen_files_verified':len(freeze['artifact_sha256']),
        'fit_calls_on_2026':0,'added_models_seeds_horizons_weight_searches':0,'post_evaluation_retraining':0,
        'same_account_target_expert_summary_rows':7488,'target_fusion_accounts':576,'descriptive_figures':17,'production_figures_visually_inspected':17,
        'solver_quality_strategy_rows':22176,'solver_quality_expert_rows':7488,'solver_quality_independent_counts_closed':True,
        'decision_solver_failure_groups_preserved':solver_failures,'independent_account_verification':'PASS_COMPLETE',
        'formal_full_pool_status':'BLOCKED_DATA','full_2026_candidate_keys':111868,'current_qualified_keys':62392,
        'original_unknown_keys':47271,'current_unknown_keys':47272,'proven_ineligible_keys':2204,
        'certified_full_pool_signal_days':0,'2026_signal_days':181,'2026_account_days':183,
        'previous_2026_exposure_preserved':True,'blind_test_claim':False,'shareholder_total_return_certified':False,
        'old_sources_verified':len(old_sources),'old_source_sha256':old_sources,'sealed_summary_sha256':output_hashes,
        'stop_rule':'All preregistered members and paths executed; stop without additional models, seeds, horizons, weights or training.'}
    write_json(ROOT/'COMPLETION.json',record)
    print(json.dumps({k:v for k,v in record.items() if not isinstance(v,dict)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
