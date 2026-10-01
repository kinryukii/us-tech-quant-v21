"""Read-only acceptance evidence. No models are loaded/fitted, no replay is run."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUT = Path(__file__).resolve().parent
BATCH = OUT.parents[1]
WS = BATCH.parent
OLD = WS / 'a2_latest_effective_joint_20260927/data'
QUAL = WS / 'a2_qualification_holdings_v1_20260927'
STRICT = WS / 'a2_strict_method_retrain_20260926'
STAGE = STRICT / 'test2026_stage'
SOURCE = Path(r'D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1')
IDENTITY = Path(r'D:/us-tech-quant-results/13f_pit_v1/data/universe/security_identity_v17c_transport.parquet')
PRICE = STRICT / 'results/pre2026_original_price_coordinate.parquet'
SEEN = {}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bind(path):
    path = Path(path)
    if str(path) not in SEEN:
        SEEN[str(path)] = sha(path)
    return path


def par(path, columns=None):
    return pd.read_parquet(bind(path), columns=columns)


def js(path):
    return json.loads(bind(path).read_text(encoding='utf-8'))


def save_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str,
                                      allow_nan=False), encoding='utf-8')


def table(name, frame, csv=True):
    frame.to_parquet(OUT / f'{name}.parquet', index=False)
    if csv:
        frame.to_csv(OUT / f'{name}.csv', index=False, encoding='utf-8-sig')


def boundary_and_labels(pre, prices):
    rows = []
    meta = js(BATCH / 'ensemble_artifacts/validation_TRAIN_RECEIPT.json')
    oof = par(BATCH / 'ensemble_artifacts/oof_2024.parquet')
    rows.append(dict(component='2025_stacking_meta', signal_max=oof.signal_date.max(),
                     label_max=oof.label_end_date.max(), cutoff='2025-01-01',
                     actual_rows=len(oof), status='PASS_BOUNDARY_ONLY',
                     source=str(BATCH/'ensemble_artifacts/oof_2024.parquet')))
    assert set(oof.signal_date.dt.year) == {2024}
    assert oof.label_end_date.lt('2025-01-01').all()
    assert pd.to_datetime(oof.base_fit_cutoff).eq('2024-01-01').all()
    assert meta['oof_years'] == [2024] and meta['label_end_max'] < '2025-01-01'
    for folder, stage, cutoff in [('development_value_artifacts', 'development', '2024-01-01'),
                                  ('value_artifacts', 'validation', '2025-01-01')]:
        receipt = js(BATCH/folder/'FIT_RECEIPT.json')
        for fit in receipt['fits']:
            if fit['stage'] != stage:
                continue
            assert fit['train_label_end_max'] < cutoff
            rows.append(dict(component=f'{stage}_{fit["name"]}', signal_max=fit['train_signal_max'],
                label_max=fit['train_label_end_max'], cutoff=cutoff, actual_rows=fit['train_rows'],
                status='PASS_RECEIPT_AND_BOUND_FILE', source=str(BATCH/folder/'FIT_RECEIPT.json')))
    for path in sorted((BATCH/'neural_artifacts').glob('validation_*last_train_episode.parquet')):
        ep = par(path)
        assert ep.reward_end_date.max() < '2025-01-01'
        rows.append(dict(component=path.stem, signal_max=ep.signal_date.max(),
            label_max=ep.reward_end_date.max(), cutoff='2025-01-01', actual_rows=len(ep),
            status='PASS_ACTUAL_EPISODE_CLOCK', source=str(path)))
    ep = par(BATCH/'development_neural_artifacts/development_direct_20260928_last_train_episode.parquet')
    assert ep.reward_end_date.max() < '2024-01-01'
    boundary=pd.DataFrame(rows)
    for col in ['signal_max','label_max','cutoff']:boundary[col]=pd.to_datetime(boundary[col])
    table('META_2025_AND_BASE_BOUNDARIES', boundary)

    known = pre.loc[pre.label_available].copy()
    open_map = prices.set_index(['ticker', 'trade_date']).open
    first = open_map.reindex(pd.MultiIndex.from_arrays([known.ticker, known.execution_date])).to_numpy()
    last = open_map.reindex(pd.MultiIndex.from_arrays([known.ticker, known.label_end_date])).to_numpy()
    rebuilt = last / first - 1
    error = np.abs(rebuilt - known.y_next_open.to_numpy())
    mismatch = known.loc[error > 1e-12, ['signal_date','ticker','execution_date','label_end_date','y_next_open']].copy()
    mismatch['reconstructed_return'] = rebuilt[error > 1e-12]
    table('PRE_LABEL_RECONSTRUCTION_MISMATCH', mismatch)
    missing = pre.loc[~pre.label_available, ['signal_date','ticker','execution_date','label_end_date','next_open','following_open']].copy()
    missing['reason'] = np.select([missing.label_end_date.isna(), missing.execution_date.isna(),
                                   missing.next_open.isna(), missing.following_open.isna()],
                                  ['END_OF_PHYSICAL_PRE2026_CALENDAR','EXECUTION_CLOCK_MISSING',
                                   'EXECUTION_OPEN_MISSING','FOLLOWING_OPEN_MISSING'], default='OTHER_INVALID_LABEL')
    table('PRE_UNAVAILABLE_LABELS', missing)
    maturity = []
    for cutoff in ['2024-01-01','2025-01-01','2026-01-01']:
        prior = pre.loc[pre.signal_date.lt(cutoff)]
        good = prior.label_available & prior.label_end_date.lt(cutoff)
        maturity.append({'cutoff':cutoff,'candidate_rows':len(prior),'mature_rows':int(good.sum()),
                         'excluded_for_maturity':int((~good).sum())})
    report = {'status':'PASS_INTERNAL_RECONSTRUCTION_ONLY','checked_mature_rows':len(known),
        'maximum_absolute_return_difference':float(error.max()),'mismatch_rows':len(mismatch),
        'unavailable_labels':len(missing),'missing_reasons':missing.reason.value_counts().to_dict(),
        'fold_maturity':maturity,
        'meaning':'Only verifies exact reconstruction from the same frozen adjusted price file; does not verify issuer actions, historical vendor arrival, identity, or shareholder returns.'}
    save_json('PRE_LABEL_RECONSTRUCTION.json', report)
    return report


def timing(pre, test, prices):
    q = pd.read_csv(bind(OLD/'quarter_timing.csv'), parse_dates=['quarter_effective_date','latest_filing_date'])
    q = q.sort_values('quarter_effective_date').reset_index(drop=True)
    cal = pd.DatetimeIndex(sorted(set(prices.loc[prices.ticker.eq('QQQ'),'trade_date']) |
                                 set(par(OLD/'calendar.parquet').trade_date)))
    original = par(SOURCE/'universe/quarterly_universe_manifest.parquet')
    filing = par(SOURCE/'audit/manager_quarter_source_evidence.parquet')
    filing['filing_timestamp'] = pd.to_datetime(filing.filing_timestamp)
    actual = filing.groupby('quarter').filing_timestamp.max()
    out = []
    for row in q.itertuples():
        future = cal[cal > row.latest_filing_date]
        fifth = future[4] if len(future) >= 5 else pd.NaT
        prior = original.loc[original.quarter.eq(row.quarter)]
        source_match = bool(len(prior) and pd.Timestamp(prior.latest_actual_filing_timestamp.iloc[0]).normalize() == row.latest_filing_date)
        out.append({'quarter':row.quarter,'latest_filing_date':row.latest_filing_date,
            'effective_date':row.quarter_effective_date,'fifth_next_session':fifth,
            'fifth_session_matches':fifth == row.quarter_effective_date,
            'original_manifest_filing_matches':source_match if len(prior) else None,
            'actual_24_manager_filing_max':actual.get(row.quarter,pd.NaT),
            'manager_evidence_rows':int(filing.quarter.eq(row.quarter).sum()),
            'granularity':'SEC_FILING_DATE_DAILY; not accepted-at intraday',
            'special_source': 'Q2_SOURCE_BINDING.json plus original24 accepted_at map' if row.quarter == '2026Q2' else ''})
    table('13F_QUARTER_CLOCKS',pd.DataFrame(out))
    checks = {}
    for name,frame,qcol in [('pre2026',pre,'active_13f_quarter'),('test2026_new_buy',test.loc[test.new_buy_eligible],'quarter')]:
        pos=np.searchsorted(q.quarter_effective_date.to_numpy(),frame.signal_date.to_numpy(),side='right')-1
        mismatch=frame[qcol].to_numpy()!=q.quarter.to_numpy()[pos]
        checks[name]={'rows':len(frame),'mismatches':int(mismatch.sum()),
            'filing_not_before_signal':int(frame.signal_date.le(frame.latest_filing_date).sum()),
            'premature_effective':int(frame.signal_date.lt(frame.quarter_effective_date).sum())}
        assert not mismatch.any()
    checks['qualification']='PASS_ASOF_QUARTER_CLOCK; stable manager set/identity/current source availability remain separate unresolved PIT questions'
    checks['rule']='All 24 original managers pooled by quarter; latest daily filing date + fifth following trading session; preceding quarter persists until successor effective.'
    save_json('13F_ASOF_CHECKS.json',checks)
    return checks


def universe(pre, prices):
    selected=par(SOURCE/'universe/selected_top100_24_manager.parquet')
    members=par(SOURCE/'universe/quarterly_universe_members.parquet')
    identity=par(IDENTITY)
    active=par(SOURCE/'universe/daily_active_quarter_ledger.parquet')
    active=active.loc[active.signal_date.between('2023-01-01','2025-12-31')]
    raw=selected[['quarter','cusip','issuer_name','title_of_class']].drop_duplicates(['quarter','cusip'])
    raw=raw.loc[raw.quarter.isin(active.active_13f_quarter)]
    static=raw.merge(members[['quarter','cusip']].assign(in_frozen_quarter_pool=True),on=['quarter','cusip'],how='left')
    fields=['cusip','ticker','mapping_status','mapping_source','mapping_confidence','moomoo_transport_code','transport_static_validated','transport_interval_status']
    static=static.merge(identity[fields].drop_duplicates('cusip'),on='cusip',how='left',validate='many_to_one')
    excluded=static.loc[static.in_frozen_quarter_pool.isna()].copy()
    excluded['classification']=np.select([excluded.mapping_status.isna(),excluded.mapping_status.ne('RESOLVED'),
        ~excluded.transport_static_validated.fillna(False).astype(bool),excluded.ticker.fillna('').eq(''),
        excluded.moomoo_transport_code.fillna('').eq('')],['STATIC_IDENTITY_RECORD_ABSENT','STATIC_IDENTITY_UNRESOLVED',
        'STATIC_TRANSPORT_NOT_VALIDATED','STATIC_TICKER_MISSING','STATIC_TRANSPORT_MISSING'],
        default='RESOLVED_BUT_QUARTER_DEDUP_OR_CAP_EXCLUSION_NOT_SEPARATELY_PROVEN')
    table('PRE_STATIC_QUARTER_EXCLUSIONS',excluded)
    allrows=active[['signal_date','active_13f_quarter']].merge(members[['quarter','ticker','cusip','moomoo_transport_code']],
        left_on='active_13f_quarter',right_on='quarter',how='left').drop(columns='quarter')
    calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ'),'trade_date'].unique()))
    calpos=pd.Series(np.arange(len(calendar)),index=calendar)
    status=prices[['ticker','trade_date']].sort_values(['ticker','trade_date']).copy()
    status['observations']=status.groupby('ticker').cumcount()+1
    status['calendar_position']=status.trade_date.map(calpos)
    status['prior120_position']=status.groupby('ticker').calendar_position.shift(120)
    status['price_row_present']=True
    status['reconstructed_121_ready']=status.observations.ge(121)&status.calendar_position.sub(status.prior120_position).eq(120)
    allrows=allrows.merge(status.rename(columns={'trade_date':'signal_date'}),on=['signal_date','ticker'],how='left')
    allrows=allrows.merge(pre[['signal_date','ticker']].assign(in_training_context=True),on=['signal_date','ticker'],how='left')
    allrows['classification']=np.select([allrows.in_training_context.fillna(False).astype(bool),allrows.price_row_present.isna(),
        ~allrows.reconstructed_121_ready.fillna(False).astype(bool)],['IN_FROZEN_TRAIN_CONTEXT','NO_FROZEN_PRICE_ON_SIGNAL',
        'INSUFFICIENT_OR_NONCONTIGUOUS_121_PRICE_HISTORY'],default='121_PRICES_PRESENT_BUT_FEATURE_OR_ORIGINAL_INPUT_EXCLUSION_UNKNOWN')
    absent=allrows.loc[allrows.classification.ne('IN_FROZEN_TRAIN_CONTEXT')]
    table('PRE_DAILY_EXCLUDED_MEMBERS',absent,csv=False)
    actual=par(SOURCE/'universe/daily_eligible_universe_ledger.parquet')
    actual=actual.loc[actual.signal_date.between('2023-01-01','2025-12-31')]
    summary=allrows.groupby('signal_date').classification.value_counts().unstack(fill_value=0).reset_index()
    table('PRE_DAILY_POOL_COUNTS',summary)
    report={'selected_top100_quarter_cusip_rows':len(raw),'static_removed_quarter_cusip_rows':len(excluded),
        'static_removal_categories':excluded.classification.value_counts().to_dict(),
        'frozen_quarter_member_security_days':len(allrows),'context_rows':len(pre),
        'daily_exclusion_categories':absent.classification.value_counts().to_dict(),
        'original_daily_totals':{c:int(actual[c].sum()) for c in ['raw_13f_count','price_eligible_count','corporate_action_eligible_count','lookback_eligible_count','final_U_t_count']},
        'conclusion':'CONFIRMED_PRE2026_TRAINING_SAMPLE_SELECTION_EFFECT. Static identity/transport resolution and presently saved price availability precede the 121-day rule. This is not solely a 2026 evaluation limitation.',
        'unproven':'Historical dates when static identity mapping, manager-list selection and vendor histories became available; unresolved records cannot be declared retrospectively ineligible or survivor-bias-free.'}
    save_json('PRE_UNIVERSE_SELECTION.json',report)
    return report


def consumption(pre):
    extreme=pre.loc[pre.y_next_open.abs().gt(.8),['signal_date','ticker','execution_date','label_end_date','y_next_open','label_available']].copy()
    for stage,folder in [('development','development_value_artifacts'),('validation','value_artifacts'),('final','value_artifacts')]:
        path=BATCH/folder/f'sample_keys_{stage}.parquet'
        if not path.exists() and stage=='development':
            choices=list((BATCH/folder).glob('*sample*parquet'));path=choices[0]
        sample=par(path,columns=['signal_date','ticker'])
        keys=set(zip(sample.signal_date,sample.ticker))
        extreme[f'value_{stage}_sampled']=[(d,t) in keys for d,t in zip(extreme.signal_date,extreme.ticker)]
    for year in [2024,2025]:
        sample=par(BATCH/f'ensemble_artifacts/oof_{year}.parquet',columns=['signal_date','ticker']).drop_duplicates()
        keys=set(zip(sample.signal_date,sample.ticker))
        extreme[f'meta_oof_{year}_sampled']=[(d,t) in keys for d,t in zip(extreme.signal_date,extreme.ticker)]
    for stage,cutoff in [('development','2024-01-01'),('validation','2025-01-01'),('final','2026-01-01')]:
        extreme[f'neural_{stage}_feature_environment_included']=extreme.label_available&extreme.signal_date.lt(cutoff)&extreme.label_end_date.lt(cutoff)
    extreme['value_and_meta_target_treatment']='clip source one-session return to [-0.2,0.2] before counterfactual utility'
    extreme['neural_stock_reward_attribution']='UNKNOWN: saved training episodes contain aggregate cash/exposure/reward only, not security positions; no training rerun permitted'
    extreme['is_numeric_error_proven']=False
    table('PRE_EXTREME_LABEL_CONSUMPTION',extreme)
    return {'extreme_labels':len(extreme),'actually_sampled_value':{s:int(extreme[f'value_{s}_sampled'].sum()) for s in ['development','validation','final']},
            'actually_sampled_meta':{str(y):int(extreme[f'meta_oof_{y}_sampled'].sum()) for y in [2024,2025]},
            'large_return_is_not_proof_of_error':True,'neural_security_reward_attribution':'UNKNOWN'}


def pre_events(pre, prices):
    events=par(SOURCE/'audit/corporate_action_event_audit.parquet')
    events=events.loc[events.event_date.lt('2026-01-01')].copy()
    risk_names={}
    for stage in ['validation','final']:
        path=bind(BATCH/f'risk_artifacts/{stage}/frozen_covariance.npz')
        with np.load(path,allow_pickle=False) as z:risk_names[stage]=set(z['tickers'].tolist())
    by={t:g.sort_values('trade_date') for t,g in prices.groupby('ticker')}
    groups={t:g for t,g in pre.groupby('ticker')}
    details=[];flags=[]
    for i,event in enumerate(events.itertuples()):
        p=groups.get(event.ticker,pre.iloc[:0]);px=by.get(event.ticker,prices.iloc[:0])
        ed=pd.Timestamp(event.event_date)
        dates=pd.DatetimeIndex(px.trade_date)
        after=dates.searchsorted(ed,side='left')
        bound=dates[min(after+120,len(dates)-1)] if len(dates) else pd.NaT
        feature=p.signal_date.ge(ed)&p.signal_date.le(bound)
        cross=p.label_available&p.execution_date.lt(ed)&p.label_end_date.ge(ed)
        eventid=f'pre_event_{i:05d}_{event.ticker}_{ed.date()}'
        details.append({'event_id':eventid,'ticker':event.ticker,'code':event.code,'event_date':ed,
            'source_event_date':event.source_event_date,'audit_kind':event.audit_kind,'factor_a':event.factor_a,
            'factor_b':event.factor_b,'manual_wolf':event.manual_wolf,'raw_jump':event.raw_jump,
            'event_in_120_observation_feature_window_rows':int(feature.sum()),
            'one_step_labels_crossing_event':int(cross.sum()),'any_ticker_training_context_rows':len(p),
            'validation_risk_security_present':event.ticker in risk_names['validation'],
            'final_risk_security_present':event.ticker in risk_names['final'],
            'historical_vendor_arrival':'UNKNOWN_NOT_RECORDED_IN_THIS_EVENT_AUDIT',
            'numeric_error':'UNKNOWN; applied action or large raw jump alone is not proof of an error',
            'classification':'CONFIRMED_PRE2026_INPUT_DEPENDENCY' if feature.any() or cross.any() else
                ('RISK_INPUT_SECURITY_PRESENT_ACTION_WINDOW_NEEDS_SEPARATE_CHECK' if event.ticker in risk_names['final'] else 'NO_DIRECT_FEATURE_LABEL_OVERLAP_IN_THIS_BATCH')})
        if event.audit_kind!='APPLIED_CORPORATE_ACTION' or event.manual_wolf:
            selected=p.loc[feature|cross,['signal_date','ticker','execution_date','label_end_date','y_next_open','label_available']].copy()
            selected['event_id']=eventid;selected['event_date']=ed;selected['audit_kind']=event.audit_kind
            selected['feature_window_dependency']=feature.loc[selected.index].to_numpy()
            selected['label_crossing_event']=cross.loc[selected.index].to_numpy()
            flags.append(selected)
    details=pd.DataFrame(details)
    table('PRE_CORPORATE_ACTION_AND_RAW_JUMP_DEPENDENCIES',details)
    table('PRE_LARGE_MOVE_EXACT_CONTEXT_ROWS',pd.concat(flags,ignore_index=True) if flags else pd.DataFrame(),csv=False)
    return {'applied_events':int(events.audit_kind.eq('APPLIED_CORPORATE_ACTION').sum()),
        'large_raw_moves_without_vendor_event':int(events.audit_kind.ne('APPLIED_CORPORATE_ACTION').sum()),
        'events_with_direct_context_dependency':int(details.classification.eq('CONFIRMED_PRE2026_INPUT_DEPENDENCY').sum()),
        'raw_moves_with_direct_context_dependency':int((details.audit_kind.ne('APPLIED_CORPORATE_ACTION')&details.classification.eq('CONFIRMED_PRE2026_INPUT_DEPENDENCY')).sum()),
        'wolf_records':details.loc[details.manual_wolf].replace({np.nan:None}).to_dict('records'),
        'qualification':'CONFIRMED_DEPENDENCIES; independent corporate-action truth and historical factor arrival remain UNKNOWN'}


def candidates_and_2026_events(pre,test):
    gate=par(STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
    changes=par(QUAL/'data/candidate_qualification_changes.parquet')
    gate=gate.merge(changes[['signal_date','ticker','new_qualified','qualification_reason','unresolved_event_keys']],
                    on=['signal_date','ticker'],how='left',validate='one_to_one')
    final=set(zip(test.loc[test.new_buy_eligible,'signal_date'],test.loc[test.new_buy_eligible,'ticker']))
    gate['in_current_frozen_test_pool']=[(d,t) in final for d,t in zip(gate.signal_date,gate.ticker)]
    gate['acceptance_category']=np.select([gate.in_current_frozen_test_pool,gate.final_input_gate.str.startswith('PROVEN'),
        gate.new_qualified.eq(False)],['QUALIFIED_SUBPOOL','PROVEN_INELIGIBLE','UNKNOWN_45_SCOPE_QUALIFICATION'],default='UNKNOWN_ORIGINAL_GATE')
    gate['acceptance_detail']=np.where(gate.new_qualified.eq(False),gate.qualification_reason,gate.final_input_gate)
    fields=['signal_date','quarter','ticker','cusip','title_of_class','moomoo_transport_code','transport_used',
        'acceptance_category','acceptance_detail','in_current_frozen_test_pool','final_input_gate','qualification_reason',
        'unresolved_event_keys','coordinate_evidence_class','first_consumed_2026_event','first_unexplained_2026_jump',
        'raw_on_signal','raw_121_calendar_ready','rehab_pass','coordinate_match','has_32_finite','version_checked']
    table('TEST2026_FULL_CANDIDATE_CLASSIFICATION',gate[fields],csv=False)
    counts=gate.groupby(['acceptance_category','acceptance_detail'],dropna=False).agg(rows=('ticker','size'),tickers=('ticker','nunique'),first=('signal_date','min'),last=('signal_date','max')).reset_index()
    table('TEST2026_CANDIDATE_GAP_COUNTS',counts)
    events=par(QUAL/'evidence/events/event_qualification.parquet')
    events['pre2026_same_ticker_rows']=events.ticker.map(pre.groupby('ticker').size()).fillna(0).astype(int)
    events['this_event_classification']=np.where(events.event_date.ge('2026-01-01'),'CONFIRMED_2026_EVENT_ONLY_NOT_PRE2026_NUMERIC_INPUT','UNKNOWN')
    events['reason_for_pre2026_exclusion']='Event applies no earlier than 2026; source pre2026 builder truncates raw rows and applies events only within retained raw date range. Same ticker historical events are separately audited.'
    events['same_ticker_prior_history_certified']=False
    table('TEST2026_EVENT_TRAINING_CLASSIFICATION',events)
    return gate,events,{'candidate_rows':len(gate),'categories':gate.acceptance_category.value_counts().to_dict(),
        'event_rows':len(events),'event_status':events.status.value_counts().to_dict(),
        'complete_days':int(gate.groupby('signal_date').acceptance_category.apply(lambda s:~s.str.startswith('UNKNOWN').any()).sum())}


def positions_and_events(events,test_prices):
    price_flags=test_prices[['ticker','trade_date','price_quality_warning','unresolved_event_on_or_before','lifecycle_ended','price_qualification_reason']].rename(columns={'trade_date':'date'})
    uncertified=[];overview=[];event_positions=[];glw_positions=[];glw_targets=[];glw_trades=[];cost10_positions=[]
    keys=par(QUAL/'evidence/events/security_day_qualification.parquet',columns=['ticker','date','unresolved_event_keys','status'])
    for year in [2025,2026]:
        for cost in ([10] if year==2025 else [5,10,25]):
            for folder in sorted((BATCH/f'evaluation_{year}/cost_{cost}').iterdir()):
                if not folder.is_dir() or not (folder/'positions.parquet').exists():continue
                p=par(folder/'positions.parquet');daily=par(folder/'daily.parquet')
                p['year']=year;p['cost_bps']=cost;p['policy']=folder.name
                if year==2026:
                    p=p.merge(price_flags,on=['ticker','date'],how='left',validate='many_to_one').merge(keys,on=['ticker','date'],how='left',validate='many_to_one')
                else:
                    p['price_quality_warning']=False;p['price_qualification_reason']='PRE2026_PRICE_FILE_HAS_NO_INDEPENDENT_EVENT_PIT_QUALIFICATION'
                    p['unresolved_event_keys']='';p['status']='NOT_AUDITED_BY_2026_EVENT_GATE'
                p['ledger_uncertified_position']=p.stale.astype(bool)|p.unknown.astype(bool)
                p['glw_event_date_conflict']=p.ticker.eq('GLW')&p.date.between('2026-02-26','2026-02-27')
                bad=p.loc[p.ledger_uncertified_position|p.price_quality_warning.fillna(False).astype(bool)|p.glw_event_date_conflict].copy()
                bad['acceptance_interpretation']=np.where(bad.glw_event_date_conflict,
                    'EXACT_GLW_EVENT_DATE_CONFLICT_OLD_GATE_MAY_HAVE_PASSED','UNUSABLE_OR_MISSING_CURRENT_PRICE; stale mark is bookkeeping, not certified current value')
                uncertified.append(bad)
                overview.append({'year':year,'cost_bps':cost,'policy':folder.name,'position_rows':len(p),
                    'ledger_uncertified_position_rows':int(p.ledger_uncertified_position.sum()),
                    'ledger_uncertified_nav_days':int(daily.certified_nav.isna().sum()),
                    'unknown_names':int(bad.ticker.nunique()),'price_gate_complete_days':int(daily.certified_nav.notna().sum()),
                    'acceptance_return_certification':'NOT_CERTIFIED_SHAREHOLDER_RETURN_OR_FULL_PIT; price-gate-only even when certified_nav is populated'})
                glw_positions.append(p.loc[p.ticker.eq('GLW')&p.date.ge('2026-02-26')].copy())
                if cost==10:
                    cost10_positions.append(p)
                    if year==2026:
                        linked=p.merge(events[['event_key','ticker','event_date','event_type','status','reason']].rename(columns={'status':'event_status','reason':'event_reason'}),on='ticker',how='inner')
                        linked=linked.loc[linked.date.ge(linked.event_date)].copy()
                        linked['link_meaning']='Held after event effective date; dependency linkage, not proof event error or incremental P&L causation'
                        event_positions.append(linked)
                if year==2026:
                    target=par(folder/'target_decisions.parquet',columns=['signal_date','execution_date','ticker','model_input_row_present','decision_semantic','current_units','current_weight','raw_model_weight','target_weight','status'])
                    target=target.loc[target.ticker.eq('GLW')&target.signal_date.between('2026-02-25','2026-02-27')].copy()
                    target['policy']=folder.name;target['cost_bps']=cost;target['year']=year;glw_targets.append(target)
                    trades=par(folder/'trades.parquet')
                    if len(trades):
                        trades=trades.loc[trades.ticker.eq('GLW')&trades.execution_date.ge('2026-02-26')].copy()
                        trades['policy']=folder.name;trades['cost_bps']=cost;trades['year']=year;glw_trades.append(trades)
    allbad=pd.concat(uncertified,ignore_index=True)
    table('ALL76_UNCERTIFIED_OR_CONFLICT_POSITIONS',allbad)
    table('ALL76_VALUATION_EVIDENCE_BY_PATH',pd.DataFrame(overview))
    table('ALL76_GLW_POSITION_DEPENDENCIES',pd.concat(glw_positions,ignore_index=True))
    table('ALL57_2026_GLW_DECISIONS',pd.concat(glw_targets,ignore_index=True))
    table('ALL57_2026_GLW_TRADES',pd.concat(glw_trades,ignore_index=True) if glw_trades else pd.DataFrame())
    linked=pd.concat(event_positions,ignore_index=True)
    table('COST10_EVENT_TO_ACTUAL_POSITION_LINKS',linked,csv=False)
    summary=linked.groupby(['event_key','ticker','event_date','event_status','event_reason'],dropna=False).agg(
        position_rows=('policy','size'),strategies=('policy','nunique'),first_held=('date','min'),last_held=('date','max'),
        uncertified_position_rows=('ledger_uncertified_position','sum')).reset_index()
    summary=events[['event_key','ticker','event_date','status','reason']].merge(summary,on=['event_key','ticker','event_date'],how='left')
    for c in ['position_rows','strategies','uncertified_position_rows']:summary[c]=summary[c].fillna(0).astype(int)
    table('COST10_EACH_EVENT_HOLDING_IMPACT',summary)
    byreason=allbad.groupby(['year','cost_bps','policy','ticker','current_close_reason','price_qualification_reason'],dropna=False).agg(
        rows=('date','size'),first=('date','min'),last=('date','max'),earliest_mark=('mark_date','min'),latest_mark=('mark_date','max')).reset_index()
    table('ALL76_UNCERTIFIED_POSITION_RANGES',byreason)
    return {'paths':len(overview),'uncertified_or_conflict_position_rows':len(allbad),
        'securities':sorted(allbad.ticker.unique().tolist()),'event_actual_position_links_cost10':len(linked),
        'glw_20260226_model_input_rows':int(pd.concat(glw_targets).query("signal_date == '2026-02-26'").model_input_row_present.sum()),
        'certified_nav_does_not_certify_input_PIT_or_corporate_actions':True}


def vendor_evidence():
    files=[Path(r'D:/us-tech-quant-cache/13f_pit_v1/a_a2_quarterly_13f_r1/rehab_factors.parquet'),
           Path(r'D:/us-tech-quant-cache/13f_pit_v1/a_a2_quarterly_13f_r1/rehab_status.csv'),IDENTITY,
           SOURCE/'audit/corporate_action_event_audit.parquet']
    records=[]
    for path in files:
        bind(path)
        columns=pq.ParquetFile(path).schema.names if path.suffix=='.parquet' else list(pd.read_csv(path,nrows=1).columns)
        records.append({'path':str(path),'sha256':SEEN[str(path)],'columns_json':json.dumps(columns),
            'file_mtime_utc':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
            'historical_vendor_actual_arrival_proven':False,
            'verdict':'UNKNOWN: trade/ex_date/source snapshot/request time or current filesystem mtime is not a per-observation contemporaneous vendor arrival and revision history'})
    table('VENDOR_AND_STATIC_SOURCE_TIMESTAMPS',pd.DataFrame(records))
    prior=STAGE/'r4_coordinate/PRIOR_EVENT_94_CODE_INITIAL_CHAIN_STATUS.csv'
    report=STAGE/'r4_coordinate/PRIOR_EVENT_INITIAL_CHAIN_REPORT.json'
    if prior.exists():
        mapping=pd.read_csv(bind(prior));table('KNOWN_PRIOR_CHAIN_94_SOURCE_GAPS',mapping)
    return {'status':'UNKNOWN_HISTORICAL_VENDOR_ARRIVAL','inspected_sources':len(records),
        'known_prior_event_gap_report':str(report),'known_prior_gap_scope':'94 no-overlap securities,1090 historical events; do not automatically attribute all these to pre2026 training without key overlap'}


def main():
    if (OUT/'EVIDENCE_SUMMARY.json').exists():raise RuntimeError('Completed evidence retained; do not overwrite')
    OUT.mkdir(parents=True,exist_ok=True)
    pre=par(OLD/'pre2026_joint_context.parquet')
    test=par(QUAL/'data/test_features_context.parquet')
    prices=par(PRICE);prices['trade_date']=pd.to_datetime(prices.trade_date)
    testprices=par(QUAL/'data/test_prices.parquet')
    summary={'created_utc':datetime.now(timezone.utc).isoformat(),'fit_calls':0,'model_predict_calls':0,'replay_calls':0,
             'source_files_modified':False,'contract_sha256':sha(bind(OUT.parent/'DIAGNOSTIC_CONTRACT.md'))}
    summary['boundaries_and_label_reconstruction']=boundary_and_labels(pre,prices)
    summary['13f_clock']=timing(pre,test,prices)
    summary['pre2026_universe_selection']=universe(pre,prices)
    summary['extreme_label_consumption']=consumption(pre)
    summary['pre2026_events']=pre_events(pre,prices)
    gate,events,summary['test2026_candidates_events']=candidates_and_2026_events(pre,test)
    summary['actual_position_impacts']=positions_and_events(events,testprices)
    summary['historical_vendor_evidence']=vendor_evidence()
    summary['status']='COMPLETE_WITH_CONFIRMED_PRE2026_SELECTION_AND_INPUT_DEPENDENCIES_AND_UNRESOLVED_PIT_EVIDENCE'
    save_json('EVIDENCE_SUMMARY.json',summary)
    unchanged={path:sha(path)==before for path,before in SEEN.items()}
    save_json('INPUT_PRESERVATION.json',{'status':'PASS' if all(unchanged.values()) else 'FAIL',
        'input_sha256':SEEN,'unchanged':unchanged,'meaning':'hashes prove this audit did not modify inputs, not their economic correctness'})
    print(json.dumps(summary,indent=2,ensure_ascii=False,default=str))


if __name__=='__main__':main()
