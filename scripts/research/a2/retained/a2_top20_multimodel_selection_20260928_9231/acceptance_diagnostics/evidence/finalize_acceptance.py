"""Final read-only evidence adjudication; no fit, prediction, or replay."""
from datetime import datetime, timezone
import json
import numpy as np
import pandas as pd
import accept_evidence as a


def q2_membership():
    folder=a.WS/'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1'
    initial=a.par(folder/'Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet')
    top=a.par(folder/'Q2_ORIGINAL24_INITIAL_TOP100.parquet')
    source=pd.read_csv(a.bind(folder/'Q2_ORIGINAL24_SOURCE_MAP.csv'),dtype=str)
    binding=a.js(a.STAGE/'fixed_window_binding/Q2_SOURCE_BINDING.json')
    versioned=a.bind(folder/'Q2_ORIGINAL24_VERSIONED_ROWS.parquet')
    assert a.sha(versioned)==binding['q2_versioned_rows_sha256']
    actual=a.par(a.STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
    actual=actual.loc[actual.quarter.eq('2026Q2')].copy()
    newbuy=a.par(a.QUAL/'data/test_features_context.parquet')
    newbuy=newbuy.loc[newbuy.quarter.eq('2026Q2')&newbuy.new_buy_eligible].copy()
    key=['ticker','cusip','moomoo_transport_code']
    original=set(map(tuple,initial[key].to_numpy()))
    detail=[]
    for label,frame in [('FULL_SAVED_R6_CANDIDATES',actual),('ACTUAL_NEW_BUY_MODEL_INPUT',newbuy)]:
        for day,g in frame.groupby('signal_date'):
            pairs=set(map(tuple,g[key].to_numpy()))
            detail.append({'scope':label,'signal_date':day,'rows':len(g),
                'initial_member_key_overlap':len(pairs&original),
                'non_initial_member_keys':len(pairs-original),
                'missing_initial_member_keys':len(original-pairs),
                'phase':'BEFORE_RESTATEMENT_EFFECTIVE' if day<pd.Timestamp(binding['citadel_restatement_effective_date']) else 'AFTER_RESTATEMENT_EFFECTIVE',
                'membership_state':'EXACT_INITIAL_MEMBER_SET' if pairs==original else 'INITIAL_SET_SUBSET' if pairs<=original else 'NOT_INITIAL_SET_SUBSET'})
    detail=pd.DataFrame(detail);a.table('Q2_2026_ACTUAL_MEMBER_VERSION_CHECK',detail)
    # Check actual top100 source accession keys, not merely the quarter string.
    def canon(series):return series.astype(str).str.replace('-','',regex=False).str.lstrip('0')
    init_sources=source.loc[~source.source_scope.str.contains('RESTAT',case=False)]
    rest_sources=source.loc[source.source_scope.str.contains('RESTAT',case=False)]
    source_accession='accession' if 'accession' in source else 'source_accession'
    rest_keys=set(canon(rest_sources[source_accession]));init_keys=set(canon(init_sources[source_accession]))
    top_keys=canon(top.accession_key)
    top_audit=top[['manager_id','cusip','accession_key','manager_rank']].copy()
    top_audit['initial_source_accession']=top_keys.isin(init_keys)
    top_audit['restatement_source_accession']=top_keys.isin(rest_keys)
    a.table('Q2_2026_INITIAL_TOP100_ACCESSION_CHECK',top_audit)
    features=a.js(a.OLD/'JOINT_DATA_AUDIT.json')['features']
    result={'initial_member_keys':len(original),'full_q2_candidate_rows':len(actual),
        'actual_q2_new_buy_rows':len(newbuy),'initial_top100_rows':len(top),
        'top100_initial_accession_rows':int(top_audit.initial_source_accession.sum()),
        'top100_restatement_accession_rows':int(top_audit.restatement_source_accession.sum()),
        'non_initial_member_keys_all_q2_rows':int(detail.non_initial_member_keys.sum()),
        'all_full_candidate_dates_exact_initial_members':bool(detail.loc[detail.scope.eq('FULL_SAVED_R6_CANDIDATES'),'membership_state'].eq('EXACT_INITIAL_MEMBER_SET').all()),
        'before_restatement_dates':int(detail.loc[detail.scope.eq('FULL_SAVED_R6_CANDIDATES')&detail.phase.eq('BEFORE_RESTATEMENT_EFFECTIVE'),'signal_date'].nunique()),
        'after_restatement_dates':int(detail.loc[detail.scope.eq('FULL_SAVED_R6_CANDIDATES')&detail.phase.eq('AFTER_RESTATEMENT_EFFECTIVE'),'signal_date'].nunique()),
        'actual_feature_names':features,
        'quarter_timing_represents_restatement':False,
        'before_restatement_verdict':'PASS_SAVED_INITIAL_MEMBERSHIP_AND_INITIAL_TOP100_ACCESSION_ONLY',
        'after_restatement_verdict':'INITIAL_POOL_PERSISTS; latest-amended top100/member-pool compliance is UNKNOWN because no amended member universe is bound or consumed by these inputs',
        'source_pit_scope':'Public filing/acceptance clock and actual member-key matches do not establish historical supplier arrival, complete identity intervals or revised-pool correctness.'}
    assert result['top100_restatement_accession_rows']==0
    assert result['top100_initial_accession_rows']==len(top)
    assert result['non_initial_member_keys_all_q2_rows']==0
    a.save_json('Q2_2026_MEMBERSHIP_VERSION_ADJUDICATION.json',result)
    return result


def outside_scope_trace():
    positions=a.par(a.OUT/'ALL76_UNCERTIFIED_OR_CONFLICT_POSITIONS.parquet')
    outside=positions.loc[positions.price_qualification_reason.eq('UNCHANGED_FROZEN_BASELINE_OUTSIDE_45_2026_SCOPE')].copy()
    gate=a.par(a.STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
    categories=['UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME','UNKNOWN_UNEXPLAINED_RAW_JUMP','UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY']
    unknown=gate.loc[gate.final_input_gate.isin(categories)].sort_values(['signal_date','ticker'])
    first=unknown.drop_duplicates('ticker')
    cols=['ticker','signal_date','cusip','moomoo_transport_code','transport_used','final_input_gate','first_consumed_2026_event','first_unexplained_2026_jump']
    first=first[cols].rename(columns={'signal_date':'original_warning_from_signal_date','final_input_gate':'original_warning_gate'})
    detail=outside.merge(first,on='ticker',how='left',validate='many_to_one')
    detail['warning_clock_matches_original_builder']=detail.date.ge(detail.original_warning_from_signal_date)
    prices=a.par(a.OLD/'test_prices.parquet')
    prices=prices.sort_values(['ticker','trade_date'])
    prices['saved_adjusted_close_return']=prices.groupby('ticker').close.pct_change(fill_method=None)
    price_fields=prices[['ticker','trade_date','extreme_adjusted_jump','saved_adjusted_close_return']].rename(columns={'trade_date':'date'})
    detail=detail.merge(price_fields,on=['ticker','date'],how='left',validate='many_to_one')
    detail['exact_warning_source']=np.where(detail.warning_clock_matches_original_builder,'ORIGINAL_R6_UNRESOLVED_PREFIX',np.where(detail.extreme_adjusted_jump.fillna(False),'SAVED_ABS_CLOSE_RETURN_OVER_80PCT','UNKNOWN_WARNING_SOURCE'))
    detail['warning_source_traced']=detail.exact_warning_source.ne('UNKNOWN_WARNING_SOURCE')
    detail['historical_vendor_event_arrival']='UNKNOWN'
    detail['pre2026_effect_of_this_2026_warning']='NONE_BY_EVENT_DATE; same-ticker earlier actions require separate evidence'
    a.table('ALL76_OUTSIDE45_WARNING_SOURCE_TRACE',detail,csv=False)
    events=a.par(a.OLD/'consumed_price_events.parquet')
    events=events.loc[events.ticker.isin(outside.ticker.unique())&pd.to_datetime(events.event_date).ge('2026-01-01')].copy()
    events['interpretation']='Saved numeric corporate-action dependency, not individual proof that the event is wrong or historically available'
    a.table('OUTSIDE45_SAVED_2026_EVENT_RECORDS',events)
    ranges=detail.groupby(['ticker','original_warning_from_signal_date','original_warning_gate','exact_warning_source'],dropna=False).agg(
        position_rows=('ticker','size'),first_position=('date','min'),last_position=('date','max'),
        strategies=('policy','nunique'),cost_paths=('cost_bps','nunique'),
        all_sources_traced=('warning_source_traced','all')).reset_index()
    a.table('OUTSIDE45_WARNING_SOURCE_RANGES',ranges)
    return {'positions':len(detail),'securities':int(detail.ticker.nunique()),
        'all_original_warning_sources_traced':bool(detail.warning_source_traced.all()),
        'warning_source_counts':detail.exact_warning_source.value_counts().to_dict(),
        'original_source':str(a.WS/'a2_complete_suite_20260927/data/build_inputs.py'),
        'source_logic':'Min signal date with one of three unresolved R6 gate states creates a persistent price warning; FLYX and MRNA instead have one-day abs adjusted-close return >80% warnings. Neither warning proves a wrong numeric price.',
        'source_event_rows':len(events)}


def main():
    q2=q2_membership();outside=outside_scope_trace()
    final=a.js(a.OUT/'FINAL_EVIDENCE_SUMMARY.json')
    final['pre2026_universe_selection']['static_removal_categories']={
        'STATIC_IDENTITY_UNRESOLVED':124,'CONFIRMED_QUARTER_TICKER_OR_TRANSPORT_DEDUP_COLLISION':24}
    for r in final['pre2026_events']['wolf_records']:
        r['classification']='CONFIRMED_FINAL_RISK_INPUT_EVENT_DEPENDENCY; NOT_IN_VALIDATION_EVENT_WINDOW; NO_DIRECT_EQUITY_CONTEXT'
        r['validation_risk_event_return_in_fit']=False
        r['final_risk_event_return_in_fit']=True
        r['final_event_return_after_risk_clip']=-0.5
        r['validation_retroactive_revision_effect']='UNKNOWN_HISTORICAL_VENDOR_VERSIONS_NOT_PROVEN'
    for r in final['wolf_risk_dependency']:
        r['event_adjusted_return_after_risk_clip']=-0.5 if r['stage']=='final' else None
        r['interpretation']='CONFIRMED_FINAL_LW_AND_PCA_INPUT_DEPENDENCY; no direct equity-context rows' if r['stage']=='final' else 'THIS_2025_EVENT_NOT_IN_VALIDATION_WINDOW; effects of later historic vendor revisions remain UNKNOWN'
    final['13f_clock']['qualification']='PASS_QUARTER_DATE_AND_SAVED_INITIAL_Q2_MEMBERSHIP_ONLY; amended-pool compliance after 2026-09-10, historical manager/identity/supplier PIT remain UNKNOWN'
    final['13f_clock']['q2_membership_version_adjudication']=q2
    final['actual_position_impacts']['outside45_warning_trace']=outside
    rebuild_path=a.bind(a.SOURCE/'scripts/run_rebuild.py')
    evaluate_path=a.bind(a.STRICT/'evaluate.py')
    rebuild=rebuild_path.read_text(encoding='utf-8');evaluate=evaluate_path.read_text(encoding='utf-8')
    assert 'END_EXCLUSIVE = pd.Timestamp("2026-01-01")' in rebuild
    assert 'part = part.loc[part.ex_div_date < END_EXCLUSIVE]' in rebuild
    assert 'raw = raw.loc[raw.trade_date.lt(rebuild.END_EXCLUSIVE)]' in evaluate
    cutoff={'status':'EXPLICIT_EVENT_AND_RAW_DATE_CUTOFF_CONFIRMED',
        'event_filter_source':str(rebuild_path),'event_filter_lines':[42,364,375,379],
        'price_builder_source':str(evaluate_path),'price_builder_lines':[44,47],
        'specific_2026_event_numeric_application_to_pre2026':False,
        'meaning':'The builder excludes 2026 rehab dates and applies retained events forward in date order. This establishes no application of the specific 2026 GLW event to pre2026 output, but cannot exclude vendor later revisions to earlier raw prices or pre2026 factor records.'}
    a.save_json('PRE2026_EVENT_CUTOFF_SOURCE_PROOF.json',cutoff)
    final['glw_exact_event']['pre2026_event_exclusion_source_proof']=cutoff
    final['glw_exact_event']['earlier_vendor_history_revision_effect']='UNKNOWN'
    final['extreme_label_consumption']['original_warning_filter']='values.mature_rows checks label_available and maturity but does not reject label_price_warning; these 13 warnings were already saved, not newly proven numeric errors.'
    final['finalized_utc']=datetime.now(timezone.utc).isoformat()
    a.save_json('FINAL_EVIDENCE_SUMMARY.json',final)
    # Audit totals, per-key uniqueness, boundary and original bytes without fitting anything.
    checks={}
    checks['pre_daily_partition']=sum(final['pre2026_universe_selection']['daily_exclusion_categories'].values())+313668==479163
    checks['test_daily_partition']=sum(final['test2026_candidates_events']['categories'].values())==111868
    bounds=a.par(a.OUT/'META_2025_AND_BASE_BOUNDARIES.parquet')
    checks['all_actual_or_receipt_labels_before_cutoff']=bool((bounds.label_max<bounds.cutoff).all())
    pos=a.par(a.OUT/'ALL76_UNCERTIFIED_OR_CONFLICT_POSITIONS.parquet')
    paths=a.par(a.OUT/'ALL76_VALUATION_EVIDENCE_BY_PATH.parquet')
    checks['all76_paths_covered']=len(paths)==76 and len(paths[['year','cost_bps','policy']].drop_duplicates())==76
    checks['position_keys_unique']=not pos.duplicated(['year','cost_bps','policy','date','ticker']).any()
    checks['glw_exact_input_rows']=final['glw_exact_event']['engine_model_input_rows']==57
    checks['all312707_mature_labels_reconstructed']=final['boundaries_and_label_reconstruction']['checked_mature_rows']==312707 and final['boundaries_and_label_reconstruction']['mismatch_rows']==0
    historical={}
    for name in ['INPUT_PRESERVATION.json','SUPPLEMENT_INPUT_PRESERVATION.json']:
        receipt=json.loads((a.OUT/name).read_text(encoding='utf-8'))
        hashes=receipt.get('input_sha256',receipt.get('inputs_sha256',{}))
        # New evidence outputs can legitimately receive final adjudication; original inputs cannot.
        historical.update({p:h for p,h in hashes.items() if not str(a.OUT).replace('\\','/').lower() in p.replace('\\','/').lower()})
    changed=[p for p,h in historical.items() if a.sha(p)!=h]
    checks['all_preexisting_source_hashes_unchanged']=not changed
    checks['q2_initial_accessions_no_restated_rows']=q2['top100_restatement_accession_rows']==0
    checks['outside45_all_warning_sources_traced']=outside['all_original_warning_sources_traced']
    a.save_json('FINAL_EVIDENCE_VERIFICATION.json',{'status':'PASS' if all(checks.values()) else 'FAIL',
        'checks':checks,'preexisting_source_hashes_verified':len(historical),'changed_sources':changed,
        'fit_calls':0,'model_predict_calls':0,'replay_calls':0,'meaning':'PASS denotes these bounded audit checks only, not source-PIT or corporate-action certification.'})
    assert all(checks.values()),checks
    print(json.dumps({'q2':q2,'outside45':outside,'checks':checks},indent=2,ensure_ascii=False,default=str))


if __name__=='__main__':main()
