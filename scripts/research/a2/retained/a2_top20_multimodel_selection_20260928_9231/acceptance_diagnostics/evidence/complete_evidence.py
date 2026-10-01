"""Supplement precise dependency consumption and adjudicate acceptance findings."""
from pathlib import Path
from datetime import datetime, timezone
import json
import numpy as np
import pandas as pd
import accept_evidence as a

OUT=a.OUT;BATCH=a.BATCH;WS=a.WS


def main():
    pre=a.par(a.OLD/'pre2026_joint_context.parquet')
    prices=a.par(a.PRICE)
    source_events=a.par(a.SOURCE/'audit/corporate_action_event_audit.parquet')
    groups={t:g for t,g in pre.groupby('ticker')}
    pricegroups={t:pd.DatetimeIndex(g.trade_date.sort_values()) for t,g in prices.groupby('ticker')}
    samples={}
    for stage,folder in [('development','development_value_artifacts'),('validation','value_artifacts'),('final','value_artifacts')]:
        path=BATCH/folder/f'sample_keys_{stage}.parquet'
        if not path.exists():path=next((BATCH/folder).glob('*sample*parquet'))
        z=a.par(path,columns=['signal_date','ticker'])
        samples[f'value_{stage}']=set(zip(z.signal_date,z.ticker))
    for year in [2024,2025]:
        z=a.par(BATCH/f'ensemble_artifacts/oof_{year}.parquet',columns=['signal_date','ticker']).drop_duplicates()
        samples[f'oof_{year}']=set(zip(z.signal_date,z.ticker))
    issues=[]
    for n,r in enumerate(source_events.loc[source_events.audit_kind.ne('APPLIED_CORPORATE_ACTION')].itertuples()):
        issues.append({'issue_id':f'raw_jump_{n:03d}_{r.ticker}_{pd.Timestamp(r.event_date).date()}',
                       'issue_kind':'RAW_MOVE_WITHOUT_VENDOR_EVENT','ticker':r.ticker,
                       'window_start':pd.Timestamp(r.event_date),'window_anchor':pd.Timestamp(r.event_date)})
    for n,r in enumerate(pre.loc[pre.y_next_open.abs().gt(.8)].itertuples()):
        issues.append({'issue_id':f'extreme_label_{n:02d}_{r.ticker}_{r.signal_date.date()}',
                       'issue_kind':'EXISTING_LABEL_PRICE_WARNING_ABS_RETURN_OVER_80PCT','ticker':r.ticker,
                       'window_start':r.execution_date,'window_anchor':r.label_end_date,
                       'label_signal_date':r.signal_date,'label_return':r.y_next_open})
    detail=[];summary=[]
    for issue in issues:
        dates=pricegroups.get(issue['ticker'],pd.DatetimeIndex([]))
        pos=dates.searchsorted(issue['window_anchor'],side='left')
        end=dates[min(pos+120,len(dates)-1)] if len(dates) else pd.NaT
        frame=groups.get(issue['ticker'],pre.iloc[:0])
        frame=frame.loc[frame.signal_date.ge(issue['window_start'])&frame.signal_date.le(end),
                        ['signal_date','ticker','execution_date','label_end_date','label_available']].copy()
        frame['issue_id']=issue['issue_id'];frame['issue_kind']=issue['issue_kind']
        frame['window_start']=issue['window_start'];frame['window_end']=end
        for name,keys in samples.items():frame[name+'_actual_sample']=[(d,t) in keys for d,t in zip(frame.signal_date,frame.ticker)]
        for stage,cutoff in [('development','2024-01-01'),('validation','2025-01-01'),('final','2026-01-01')]:
            frame['neural_'+stage+'_feature_input']=frame.label_available&frame.signal_date.lt(cutoff)&frame.label_end_date.lt(cutoff)
        frame['interpretation']='Dependency-window overlap, not proof of a wrong price/event or numerical change in every feature; later level-coordinate effects may extend beyond this window.'
        detail.append(frame)
        summary.append({**issue,'window_end':end,'context_rows':len(frame),
            **{name+'_actual_sample_rows':int(frame[name+'_actual_sample'].sum()) for name in samples},
            **{'neural_'+stage+'_feature_rows':int(frame['neural_'+stage+'_feature_input'].sum()) for stage in ['development','validation','final']}})
    detail=pd.concat(detail,ignore_index=True);summary=pd.DataFrame(summary)
    a.table('PRE_121_WINDOW_ACTUAL_TRAINING_CONSUMPTION',detail,csv=False)
    a.table('PRE_121_WINDOW_CONSUMPTION_BY_ISSUE',summary)
    aggregate=[]
    for kind,g in detail.groupby('issue_kind'):
        unique=g.drop_duplicates(['signal_date','ticker'])
        aggregate.append({'issue_kind':kind,'issue_count':int(summary.issue_kind.eq(kind).sum()),
            'unique_context_keys':len(unique),**{name+'_actual_sample_keys':int(unique[name+'_actual_sample'].sum()) for name in samples}})
    a.table('PRE_121_WINDOW_CONSUMPTION_SUMMARY',pd.DataFrame(aggregate))

    static=a.par(OUT/'PRE_STATIC_QUARTER_EXCLUSIONS.parquet')
    members=a.par(a.SOURCE/'universe/quarterly_universe_members.parquet')
    collision=[]
    for r in static.loc[static.classification.str.startswith('RESOLVED_BUT')].itertuples():
        same=members.loc[members.quarter.eq(r.quarter)&(members.ticker.eq(r.ticker)|members.moomoo_transport_code.eq(r.moomoo_transport_code))]
        collision.append({'quarter':r.quarter,'excluded_cusip':r.cusip,'ticker':r.ticker,'transport':r.moomoo_transport_code,
            'kept_cusips':'|'.join(same.cusip.astype(str)),'kept_tickers':'|'.join(same.ticker.astype(str)),
            'classification':'CONFIRMED_QUARTER_TICKER_OR_TRANSPORT_DEDUP_COLLISION' if len(same) else 'UNKNOWN_CAP_OR_OTHER_EXCLUSION',
            'historical_identity_interval_correctness':'UNKNOWN: static CUSIP mapping lacks historical arrival/interval proof'})
    collision=pd.DataFrame(collision);a.table('PRE_STATIC_RESOLVED_EXCLUSION_ADJUDICATION',collision)

    prior=OUT/'KNOWN_PRIOR_CHAIN_94_SOURCE_GAPS.parquet'
    prior_overlap=[]
    if prior.exists():
        prior=a.par(prior)
        for r in prior.itertuples():
            g=pre.loc[pre.moomoo_transport_code.eq(r.original_code)]
            prior_overlap.append({'original_code':r.original_code,'prior_events':r.prior_events,
                'pre2026_context_rows':len(g),'pre2026_tickers':'|'.join(sorted(g.ticker.unique())),
                'classification':'NO_SAME_CODE_PRE2026_CONTEXT_OVERLAP' if not len(g) else 'CONFIRMED_PRIOR_CHAIN_GAP_CODE_USED_IN_PRE2026_CONTEXT_SOURCE_IDENTITY_REQUIRES_REVIEW'})
        a.table('PRIOR94_CHAIN_PRE2026_CODE_OVERLAP',pd.DataFrame(prior_overlap))

    # Independently inspect 2026Q2 real accepted-at sources; restatements are not initial activation.
    qpath=WS/'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1/Q2_ORIGINAL24_SOURCE_MAP.csv'
    q=pd.read_csv(a.bind(qpath),dtype={'original_cik':str,'source_cik':str})
    q['accepted_at']=pd.to_datetime(q.accepted_at,utc=True)
    initial=q.loc[~q.source_scope.str.contains('RESTAT',case=False)].copy()
    bind=a.js(a.STAGE/'fixed_window_binding/Q2_SOURCE_BINDING.json')
    clock={'initial_source_rows':len(initial),'original_managers':int(initial.original_manager_id.nunique()),
        'max_initial_accepted_at_utc':initial.accepted_at.max(),'max_initial_accepted_at_new_york':initial.accepted_at.max().tz_convert('America/New_York'),
        'bound_initial_effective':bind['initial_effective_date'],'bound_restatement_effective':bind['citadel_restatement_effective_date'],
        'source_identity_binding_scope':bind['status'],'not_certified_by_binding':bind['not_certified_by_this_receipt']}
    a.table('Q2_2026_INITIAL_ACCEPTED_AT_SOURCES',initial);a.save_json('Q2_2026_ACCEPTED_CLOCK.json',clock)

    # Exact GLW conflict has no pre2026 dates; same-ticker historic actions remain a separate question.
    old=WS/'a2_complete_suite_nearest_effective_20260927/continuation_account_repair_r1'
    conflict=a.js(old/'next_proof/ROUND2_GLW_ADJUDICATION.json')
    glw=a.par(OUT/'ALL57_2026_GLW_DECISIONS.parquet');glw['signal_date']=pd.to_datetime(glw.signal_date)
    exact=glw.loc[glw.signal_date.eq('2026-02-26')]
    glwp=a.par(OUT/'ALL76_GLW_POSITION_DEPENDENCIES.parquet')
    glwt=a.par(OUT/'ALL57_2026_GLW_TRADES.parquet')
    raw=[]
    for cost in [5,10,25]:
        for folder in sorted((BATCH/f'evaluation_2026/cost_{cost}').iterdir()):
            path=folder/'raw_model_outputs.parquet'
            if not path.exists():continue
            frame=a.par(path)
            frame=frame.loc[pd.to_datetime(frame.signal_date).eq('2026-02-26')]
            for r in frame.itertuples():
                outputs=json.loads(r.raw_model_outputs_json)
                raw.append({'policy':folder.name,'cost_bps':cost,'signal_date':'2026-02-26',
                    'glw_in_original_input':'GLW' in json.loads(r.original_input_tickers_json),
                    'glw_in_decision_input':'GLW' in json.loads(r.decision_input_tickers_json),
                    'glw_raw_model_output_present':'GLW' in outputs,
                    'glw_raw_model_output_json':json.dumps(outputs.get('GLW'),ensure_ascii=False)})
    raw=pd.DataFrame(raw);a.table('ALL57_GLW_CONFLICT_EXACT_MODEL_OUTPUTS',raw)
    glwcase={'classification':'CONFIRMED_THIS_EVENT_2026_EVALUATION_ONLY; input-score dependency remains despite zero positions',
        'known_conflict_source':str(old/'next_proof/ROUND2_GLW_ADJUDICATION.json'),
        'issuer_ex_date':conflict['issuer']['issuer_dividend_history_ex_date'],
        'vendor_ex_date':conflict['original_vendor']['saved_get_rehab_ex_div_date'],
        'exact_decision_rows':len(exact),'engine_model_input_rows':int(exact.model_input_row_present.sum()),
        'noncash_raw_scored_paths':int(raw.glw_raw_model_output_present.sum()),
        'nonzero_targets':int(exact.target_weight.gt(0).sum()),'nonzero_current_units':int(exact.current_units.gt(0).sum()),
        'positions_from_conflict_date':len(glwp),'trades_from_conflict_date':len(glwt),
        'other_orders_counterfactual_impact':'UNKNOWN: cross-sectional ranking/MLP projection/ensemble rank consumes GLW; zero weight is an output, not proof of no portfolio influence',
        'pre2026_same_ticker_context_rows':int(pre.ticker.eq('GLW').sum()),
        'pre2026_this_event_numeric_consumption':0,
        'prior_draft_count_correction':'Earlier EVIDENCE_SUMMARY glw_20260226_model_input_rows=0 came from object/string date equality; this exact normalized-date check supersedes that draft number.'}
    a.save_json('GLW_EXACT_EVENT_ADJUDICATION.json',glwcase)

    # WOLF is absent from the equity panel but present in both risk covariance universes.
    wolf=[]
    wp=prices.loc[prices.ticker.eq('WOLF')].sort_values('trade_date').set_index('trade_date')
    for stage in ['validation','final']:
        receipt=a.js(BATCH/f'risk_artifacts/{stage}/TRAIN_RECEIPT.json')
        with np.load(a.bind(BATCH/f'risk_artifacts/{stage}/frozen_covariance.npz'),allow_pickle=False) as x:present='WOLF' in x['tickers']
        risk_dates=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.lt(receipt['cutoff_exclusive']),'trade_date'].unique()))[-253:]
        returns=wp.close.reindex(risk_dates).pct_change(fill_method=None).iloc[1:]
        date=pd.Timestamp('2025-09-29')
        wolf.append({'stage':stage,'security_in_covariance_artifact':present,'risk_window_first':returns.index.min(),
            'risk_window_last':returns.index.max(),'manual_event_date':date,'event_return_in_fit':bool(present and date in returns.index and pd.notna(returns.get(date,np.nan))),
            'event_adjusted_return_before_risk_clip':float(returns.loc[date]) if date in returns.index else None,
            'risk_return_clip':receipt['risk_only_return_clip'],'direct_equity_training_rows':int(pre.ticker.eq('WOLF').sum()),
            'interpretation':'CONFIRMED_FINAL_RISK_INPUT_DEPENDENCY for final, not direct equity labels; does not certify bankruptcy conversion as shareholder total return'})
    a.table('WOLF_MANUAL_ACTION_RISK_TRAINING_DEPENDENCY',pd.DataFrame(wolf))

    # Damaged legacy BYND metadata: demonstrate exact fields and absence from current builder dependencies.
    approvals=pd.read_csv(a.bind(old/'replay/inputs/APPROVED_PRICE_FIELDS_V8.csv'),dtype=str)
    approvals=approvals.loc[approvals.ticker.eq('BYND')]
    a.table('LEGACY_BYND_DAMAGED_APPROVAL_METADATA',approvals)
    current_identity=a.js(a.QUAL/'evidence/identity/identity_lifecycle_qualification.json')
    bynd=next(x for x in current_identity['securities'] if x['ticker']=='BYND')
    builder=a.bind(a.QUAL/'build_qualified_data.py').read_text(encoding='utf-8')
    byndcase={'classification':'LEGACY_EXPORT_METADATA_DEFECT_NOT_CONSUMED_BY_CURRENT_INPUT_BUILDER',
        'damaged_legacy_rows':len(approvals),'pre_split_cusip_values':sorted(approvals.pre_split_cusip.dropna().unique().tolist()),
        'post_split_cusip_values':sorted(approvals.post_split_cusip.dropna().unique().tolist()),
        'current_identity_original_cusip':bynd['original_cusip'],'current_identity_bridge':bynd.get('new_identity_bridge'),
        'current_builder_contains_approved_price_fields_reference':'APPROVED_PRICE_FIELDS' in builder,
        'current_model_features_exclude_cusip_metadata':True,
        'scope_limit':'Only this damaged approval-column defect is excluded. BYND 2025 large-price-move feature windows and historical arrival uncertainty remain separately recorded.'}
    a.save_json('BYND_LEGACY_METADATA_ADJUDICATION.json',byndcase)

    summary0=a.js(OUT/'EVIDENCE_SUMMARY.json')
    summary0['actual_position_impacts']['glw_20260226_model_input_rows']=glwcase['engine_model_input_rows']
    summary0['supplement_created_utc']=datetime.now(timezone.utc).isoformat()
    summary0['dependency_window_consumption']=aggregate
    summary0['static_resolved_exclusion_adjudication']=collision.classification.value_counts().to_dict()
    summary0['prior94_codes_in_pre2026']=sum(r['pre2026_context_rows']>0 for r in prior_overlap)
    summary0['glw_exact_event']=glwcase
    summary0['wolf_risk_dependency']=wolf
    summary0['old_return_label_downgrade']='certified_retrospective_return / certified_nav means price-gate-only accounting coverage, not full historical source-PIT, full universe or certified shareholder total return'
    summary0['fit_calls']=0;summary0['model_predict_calls']=0;summary0['replay_calls']=0
    a.save_json('FINAL_EVIDENCE_SUMMARY.json',summary0)
    a.save_json('SUPPLEMENT_INPUT_PRESERVATION.json',{'status':'PASS' if all(a.sha(p)==h for p,h in a.SEEN.items()) else 'FAIL',
                'input_sha256':a.SEEN,'no_source_mutation':True})
    print(json.dumps({'dependency_window_consumption':aggregate,'glw':glwcase,'wolf':wolf,
                      'static':summary0['static_resolved_exclusion_adjudication'],
                      'prior94_codes_in_pre2026':summary0['prior94_codes_in_pre2026']},indent=2,default=str))


if __name__=='__main__':main()
