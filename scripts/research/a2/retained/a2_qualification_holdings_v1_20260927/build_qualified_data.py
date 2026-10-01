"""Reuse frozen values; repair only evidenced qualification in the 45-name scope.

No price fetch, feature recomputation, model fitting or universe change. Every
signal gate uses that signal day; execution dates never filter signal eligibility.
"""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data'
WS=ROOT.parent
OLD=WS/'a2_latest_effective_joint_20260927'
STAGE=WS/'a2_strict_method_retrain_20260926/test2026_stage'
EVENT=ROOT/'evidence/events'
IDENTITY=ROOT/'evidence/identity/identity_lifecycle_qualification.json'
INPUTS={}
KEY=['signal_date','ticker']
LAST_SIGNAL=pd.Timestamp('2026-09-22')
LAST_PRICE=pd.Timestamp('2026-09-24')

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def bind(p):
    p=Path(p);INPUTS[str(p)]=sha(p);return p
def readjson(p):return json.loads(bind(p).read_text(encoding='utf8'))
def pq(p):return pd.read_parquet(bind(p))
def writejson(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding='utf8')
def output(d,name):
    d.to_parquet(OUT/(name+'.parquet'),index=False)
    d.to_csv(OUT/(name+'.csv'),index=False,encoding='utf-8-sig')
def truth(s):return s.fillna(False).astype(bool)
def base_gate(g):
    old= g.final_input_gate.str.startswith('INPUT_VERIFIED')
    only_event=g.final_input_gate.eq('UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME')
    ok=pd.Series(True,index=g.index)
    corrected_dte=g.ticker.eq('DTP')&g.cusip.eq('233331107')&g.transport_used.eq('US.DTE')
    for c in ['raw_on_signal','raw_121_calendar_ready','rehab_pass','coordinate_match','lookback_121_eligible','all_features_available','has_32_finite','version_checked']:
        # These two legacy fields describe the rejected US.DTP lookup.  The
        # corrected R6 US.DTE rows already have 121-feature/version checks;
        # current raw OHLC and exact old price matching are checked below.
        ok &= truth(g[c]) | (corrected_dte if c in ['raw_on_signal','raw_121_calendar_ready'] else False)
    for c in ['proven_lifecycle_ineligible','proven_121_ineligible','multi_cusip_transport_interval_pending','unexplained_raw_jump_dependency','no_frozen_coordinate_overlap']:
        ok &= ~truth(g[c])
    # R6 independently matched original close/volume for EXAS without frozen overlap.
    independent=old & g.final_input_gate.eq('INPUT_VERIFIED_INDEPENDENT_ORIGINAL_COORDINATE') & truth(g.coordinate_gap_closure_proposed)&truth(g.other_saved_close_exact)&truth(g.other_saved_volume_exact)
    preserved=old & truth(g.has_32_finite)&truth(g.lookback_121_eligible)&(ok|independent)
    return preserved|(only_event&ok)

def main():
    OUT.mkdir(exist_ok=True)
    identity=readjson(IDENTITY);securities={s['ticker']:s for s in identity['securities']};names=set(securities)
    old=pq(OLD/'data/test_features_context.parquet');prices=pq(OLD/'data/test_prices.parquet')
    g=pq(STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
    f=pq(STAGE/'identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet')
    events=pq(EVENT/'security_day_qualification.parquet')
    calendar=pq(OLD/'data/calendar.parquet')
    joint=readjson(OLD/'data/JOINT_DATA_AUDIT.json');features=joint['features'];assert len(features)==32
    q=pd.read_csv(bind(OLD/'data/quarter_timing.csv'),parse_dates=['report_date','latest_filing_date','quarter_effective_date','next_quarter_effective_date'])
    q=q.sort_values('quarter_effective_date')
    receipts=readjson(OLD/'data/PRICE_SOURCE_RECEIPTS.json');raw_receipts={r['ticker']:r for r in receipts}
    assert len(old)==61963 and len(g)==111868 and len(events)==8235
    assert set(events.ticker)==names and len(names)==45
    assert not old.duplicated(KEY).any() and not g.duplicated(KEY).any()
    scoped_g=g.loc[g.ticker.isin(names)].copy()
    scoped_g['base_row_usable']=base_gate(scoped_g)
    for t,s in securities.items():
        assert scoped_g.loc[scoped_g.ticker.eq(t),'cusip'].eq(s['original_cusip']).all(),t
        assert s['baseline_identity_reuse_allowed']
        # All evidence source bytes remain bound; a nullable global UID is not a blocker.
        bridge=s.get('new_identity_bridge')
        if bridge:
            for ref in bridge['source_refs']:
                assert sha(bind(ref['path']))==ref['sha256'],ref['path']
    first_baseline=scoped_g.loc[scoped_g.final_input_gate.str.startswith('INPUT_VERIFIED')].groupby('ticker').signal_date.min()
    # Local raw OHLC verification only. Numeric adjusted prices are never altered.
    rawparts=[];raw_hashes=[]
    for ticker in sorted(names):
        r=raw_receipts[ticker];assert r['transport']==securities[ticker]['selected_transport']
        parts=[]
        for record in r['paths']:
            p=bind(record['path']);assert INPUTS[str(p)]==record['sha256']
            z=pd.read_parquet(p);z=z.loc[z.code.eq(r['transport'])].copy()
            z['trade_date']=pd.to_datetime(z.time_key).dt.normalize()
            z=z.loc[z.trade_date.between('2026-01-01',LAST_PRICE),['trade_date','open','close','high','low','volume']]
            parts.append(z);raw_hashes.append(record)
        z=pd.concat(parts,ignore_index=True)
        conflicts=z.groupby('trade_date')[['open','close','high','low','volume']].nunique(dropna=False).gt(1).any(axis=1)
        z=z.sort_values('trade_date').drop_duplicates('trade_date',keep='last')
        z['raw_duplicate_conflict']=z.trade_date.map(conflicts).fillna(False)
        z['ticker']=ticker
        z=z.rename(columns={c:'receipt_raw_'+c for c in ['open','close','high','low','volume']})
        rawparts.append(z)
    raw=pd.concat(rawparts,ignore_index=True)
    scope_prices=prices.loc[prices.ticker.isin(names)&prices.trade_date.ge('2026-01-01')].copy()
    scope_prices['old_price_quality_warning']=scope_prices.price_quality_warning
    scope_prices['old_unresolved_event_on_or_before']=scope_prices.unresolved_event_on_or_before
    scope_prices=scope_prices.merge(events.rename(columns={'date':'trade_date','status':'event_prefix_status','cusip':'event_cusip'}),on=['ticker','trade_date'],how='left',validate='one_to_one')
    scope_prices=scope_prices.merge(raw,on=['ticker','trade_date'],how='left',validate='one_to_one')
    anchors=[]
    anchorcols=['signal_date','quarter','cusip','title_of_class','transport_used','base_row_usable','final_input_gate']
    for ticker,ps in scope_prices.groupby('ticker',sort=True):
        ag=scoped_g.loc[scoped_g.ticker.eq(ticker),anchorcols].sort_values('signal_date').rename(columns={'signal_date':'anchor_date','quarter':'anchor_quarter','cusip':'anchor_cusip','title_of_class':'anchor_class','transport_used':'anchor_transport','final_input_gate':'anchor_gate'})
        z=pd.merge_asof(ps.sort_values('trade_date'),ag,left_on='trade_date',right_on='anchor_date',direction='backward',allow_exact_matches=True)
        anchors.append(z)
    p=pd.concat(anchors,ignore_index=True)
    p['base_coordinate_verified']=truth(p.base_row_usable)
    p['prior_baseline_identity_established']=p.trade_date.ge(p.ticker.map(first_baseline))
    p['identity_verified']=p.prior_baseline_identity_established & p.anchor_cusip.eq(p.event_cusip)&p.anchor_transport.eq(p.transport_used)
    p['bridge_clock_verified']=True
    p['effective_cusip']=p.anchor_cusip
    p['new_lifecycle_ended']=False
    for ticker,s in securities.items():
        ix=p.ticker.eq(ticker);bridge=s.get('new_identity_bridge')
        if bridge and bridge.get('effective_date'):
            applies=ix&p.trade_date.ge(bridge['effective_date'])
            opens=p.loc[applies,'trade_date'].dt.tz_localize('America/New_York')+pd.Timedelta(hours=9,minutes=30)
            p.loc[applies,'bridge_clock_verified']=opens.ge(pd.Timestamp(bridge['known_by'])).to_numpy()
            p.loc[applies,'effective_cusip']=bridge.get('to_cusip')
            if bridge['relation']=='COMMON_STOCK_CONVERTED_TO_CASH_RIGHT':p.loc[applies,'new_lifecycle_ended']=True
        if ticker=='DTP':
            p.loc[ix,'identity_verified'] &= p.loc[ix,'transport_used'].eq('US.DTE')&p.loc[ix,'event_cusip'].eq('233331107')
    rawcols=['receipt_raw_open','receipt_raw_close','receipt_raw_high','receipt_raw_low']
    p['raw_ohlc_available']=np.isfinite(p[rawcols].to_numpy(float)).all(axis=1)&p[rawcols].gt(0).all(axis=1)&~truth(p.raw_duplicate_conflict)
    p['raw_ohlc_consistent']=(p.receipt_raw_low<=p[['receipt_raw_open','receipt_raw_close']].min(axis=1))&(p.receipt_raw_high>=p[['receipt_raw_open','receipt_raw_close']].max(axis=1))
    p['saved_raw_values_exact']=np.isclose(p.raw_open,p.receipt_raw_open,atol=1e-10,rtol=0)&np.isclose(p.raw_close,p.receipt_raw_close,atol=1e-10,rtol=0)
    p['adjusted_values_available']=np.isfinite(p[['open','close']].to_numpy(float)).all(axis=1)&p[['open','close']].gt(0).all(axis=1)
    p['event_complete']=truth(p.all_consumed_events_verified)&truth(p.full_value_reconstruction_verified)&truth(p.public_clock_verified)&truth(p.identity_event_bridge_verified)
    p['lifecycle_ended']=p.lifecycle_ended|p.new_lifecycle_ended
    p['qualification_pass']=p.event_complete&p.identity_verified&p.bridge_clock_verified&p.base_coordinate_verified&p.raw_ohlc_available&p.raw_ohlc_consistent&p.saved_raw_values_exact&p.adjusted_values_available&~p.lifecycle_ended&~p.extreme_adjusted_jump
    p['unresolved_event_on_or_before']=~p.event_complete
    p['price_quality_warning']=~p.qualification_pass
    p['price_qualification_reason']=np.select([p.lifecycle_ended,~p.event_complete,~p.prior_baseline_identity_established,~p.identity_verified,~p.bridge_clock_verified,~p.base_coordinate_verified,~(p.raw_ohlc_available&p.raw_ohlc_consistent&p.saved_raw_values_exact),~p.adjusted_values_available,p.extreme_adjusted_jump],
        ['PROVEN_LIFECYCLE_END','UNKNOWN_CONSUMED_EVENT_PREFIX','NO_PRIOR_BASELINE_ACCOUNT_IDENTITY_ANCHOR','IDENTITY_NOT_MATCHED','BRIDGE_NOT_PUBLIC_BY_CONSUMPTION','BASE_COORDINATE_NOT_VERIFIED','RAW_OHLC_MISSING_CONFLICT_OR_MISMATCH','ADJUSTED_PRICE_UNAVAILABLE','EXTREME_ADJUSTED_JUMP'],default='COMPLETE_EVENT_PREFIX_IDENTITY_RAW_AND_BASE_COORDINATE_VERIFIED')
    p['price_qualification_change']=np.select([p.old_price_quality_warning&~p.price_quality_warning,~p.old_price_quality_warning&p.price_quality_warning],['RESTORED_QUALIFIED','DOWNGRADE_UNKNOWN'],default='UNCHANGED')
    # Prices before an observed same-account anchor conservatively remain unusable;
    # future candidate membership/identity does not backfill such prices.
    pcols=['ticker','trade_date','unresolved_event_on_or_before','lifecycle_ended','price_quality_warning','price_qualification_reason','price_qualification_change','effective_cusip']
    price_new=prices.drop(columns=['unresolved_event_on_or_before','lifecycle_ended','price_quality_warning']).merge(p[pcols],on=['ticker','trade_date'],how='left',validate='one_to_one')
    for c in ['unresolved_event_on_or_before','lifecycle_ended','price_quality_warning']:
        price_new[c]=price_new[c].fillna(prices[c]).astype(bool)
    price_new['price_qualification_reason']=price_new.price_qualification_reason.fillna('UNCHANGED_FROZEN_BASELINE_OUTSIDE_45_2026_SCOPE')
    price_new['price_qualification_change']=price_new.price_qualification_change.fillna('UNCHANGED')
    for c in ['open','close','raw_open','raw_close','volume']:
        assert np.array_equal(price_new[c].to_numpy(),prices[c].to_numpy(),equal_nan=True),c
    non_scope=~(prices.ticker.isin(names)&prices.trade_date.ge('2026-01-01'))
    assert price_new.loc[non_scope,prices.columns].equals(prices.loc[non_scope,prices.columns])
    # Candidate features require only SAME-DAY price evidence. No t+1 price filter.
    sigprice=p.rename(columns={'trade_date':'signal_date'})
    candidate=scoped_g.merge(sigprice[KEY+['qualification_pass','price_qualification_reason','effective_cusip','unresolved_event_keys']],on=KEY,how='left',validate='one_to_one')
    candidate['new_qualified']=candidate.base_row_usable&truth(candidate.qualification_pass)
    candidate['old_qualified']=candidate.final_input_gate.str.startswith('INPUT_VERIFIED')
    candidate['qualification_change']=np.select([~candidate.old_qualified&candidate.new_qualified,candidate.old_qualified&~candidate.new_qualified],['RESTORED_CURRENT_POOL','DOWNGRADE_UNKNOWN'],default='UNCHANGED')
    candidate['qualification_reason']=np.where(candidate.new_qualified,'ALL_CURRENT_DAY_DEPENDENCIES_VERIFIED',candidate.price_qualification_reason.fillna('SAME_DAY_PRICE_UNAVAILABLE'))
    # Required earlier checks are never superseded merely by an event pass.
    candidate.loc[~candidate.base_row_usable,'qualification_reason']='ORIGINAL_NON_EVENT_GATE_NOT_PASSED'
    chosen=candidate.loc[candidate.new_qualified].copy()
    fields=['signal_date','quarter','ticker','cusip','title_of_class','moomoo_transport_code','transport_used','final_input_gate','effective_cusip','qualification_change','qualification_reason']
    newrows=chosen[fields].merge(f[KEY+features],on=KEY,validate='one_to_one')
    newrows['final_input_gate']=np.where(newrows.qualification_change.eq('RESTORED_CURRENT_POOL'),'INPUT_VERIFIED_REUSABLE_EVENT_IDENTITY_EVIDENCE',newrows.final_input_gate)
    newrows=newrows.merge(q,on='quarter',how='left',validate='many_to_one')
    asof=pd.merge_asof(pd.DataFrame({'signal_date':sorted(calendar.loc[calendar.is_signal,'trade_date'])}),q[['quarter','quarter_effective_date']].rename(columns={'quarter':'asof_quarter'}),left_on='signal_date',right_on='quarter_effective_date',direction='backward')
    newrows=newrows.merge(asof[KEY[:1]+['asof_quarter']],on='signal_date',validate='many_to_one')
    assert newrows.quarter.eq(newrows.asof_quarter).all()
    assert newrows.signal_date.ge(newrows.quarter_effective_date).all() and newrows.signal_date.gt(newrows.latest_filing_date).all()
    newrows['new_buy_eligible']=True;newrows['context_only_if_held']=False
    newrows['pool_scope']='QUALIFIED_CURRENT_POOL_45_REPAIR_WITH_FROZEN_REMAINDER'
    newrows['universe_rule']='LATEST_PUBLISHED_AND_EFFECTIVE_13F_QUARTER'
    newrows['qualification_provenance']='R6_SAME_IDENTITY_AND_32_FEATURES_PLUS_EVENTS_V1_IDENTITY_V1_RAW_RECEIPTS'
    outside=old.loc[~old.ticker.isin(names)].copy()
    outside['context_only_if_held']=False;outside['qualification_change']='UNCHANGED'
    outside['qualification_reason']='UNCHANGED_FROZEN_NON45_BASELINE';outside['qualification_provenance']='FROZEN_LATEST_EFFECTIVE_CONTEXT'
    outside['effective_cusip']=outside.cusip
    # A prior qualified account can obtain context outside the current buy pool.
    material=f.loc[f.ticker.isin(names)&f.signal_date.le(LAST_SIGNAL)].copy()
    material=material.merge(g[KEY].assign(in_current_candidate=True),on=KEY,how='left',validate='one_to_one')
    material=material.loc[material.in_current_candidate.isna()].copy()
    finite=np.isfinite(material[features].to_numpy(float)).all(axis=1)
    material=material.loc[finite&truth(material.lookback_121_eligible)&truth(material.all_features_available)]
    held=material.merge(sigprice[KEY+['qualification_pass','anchor_quarter','anchor_cusip','anchor_class','anchor_transport','anchor_date','effective_cusip','price_qualification_reason']],on=KEY,how='left',validate='one_to_one')
    held=held.loc[truth(held.qualification_pass)].copy()
    held['quarter']=held.anchor_quarter;held['cusip']=held.anchor_cusip;held['title_of_class']=held.anchor_class
    held['transport_used']=held.anchor_transport;held['moomoo_transport_code']='US.'+held.ticker
    held=held[KEY+['quarter','cusip','title_of_class','transport_used','moomoo_transport_code','effective_cusip','anchor_date']+features]
    held=held.merge(q,on='quarter',how='left',validate='many_to_one').merge(asof[['signal_date','asof_quarter']],on='signal_date',validate='many_to_one')
    assert held.quarter.ne(held.asof_quarter).all()
    held['new_buy_eligible']=False;held['context_only_if_held']=True
    held['final_input_gate']='INPUT_VERIFIED_HOLDING_CONTEXT_ONLY'
    held['pool_scope']='EXISTING_HOLDINGS_CONTEXT_OUTSIDE_CURRENT_BUY_POOL'
    held['universe_rule']='LATEST_PUBLISHED_AND_EFFECTIVE_13F_QUARTER'
    held['qualification_change']='RESTORED_HOLDING_CONTEXT_ONLY'
    held['qualification_reason']='PRIOR_VERIFIED_ACCOUNT_IDENTITY_CURRENT_FEATURE_PRICE_EVENT_PREFIX_PASS_NO_CURRENT_MEMBERSHIP'
    held['qualification_provenance']='PAST_IDENTITY_ANCHOR_PLUS_CURRENT_MATERIALIZED_FEATURES_AND_EVENT_RAW_GATES'
    result=pd.concat([outside,newrows,held],ignore_index=True).sort_values(KEY).reset_index(drop=True)
    assert not result.duplicated(KEY).any()
    assert np.isfinite(result[features].to_numpy(float)).all()
    assert result.signal_date.max()==LAST_SIGNAL
    assert not (result.context_only_if_held&result.new_buy_eligible).any()
    featurecheck=result.merge(f[KEY+features],on=KEY,validate='one_to_one',suffixes=('','_source'))
    assert np.array_equal(featurecheck[features].to_numpy(float),featurecheck[[c+'_source' for c in features]].to_numpy(float))
    # Baseline outside scope is unchanged byte-for-value across its original columns.
    a=result.loc[~result.ticker.isin(names),old.columns].sort_values(KEY).reset_index(drop=True)
    b=old.loc[~old.ticker.isin(names)].sort_values(KEY).reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,check_dtype=False)
    result.to_parquet(OUT/'test_features_context.parquet',index=False)
    result.loc[result.new_buy_eligible].to_parquet(OUT/'test_features.parquet',index=False)
    price_new.to_parquet(OUT/'test_prices.parquet',index=False)
    output(candidate[['signal_date','quarter','ticker','cusip','final_input_gate','old_qualified','new_qualified','qualification_change','qualification_reason','effective_cusip','unresolved_event_keys']],'candidate_qualification_changes')
    output(p[['ticker','trade_date','anchor_date','anchor_quarter','anchor_cusip','event_cusip','effective_cusip','old_price_quality_warning','price_quality_warning','price_qualification_change','price_qualification_reason','event_complete','base_coordinate_verified','identity_verified','bridge_clock_verified','raw_ohlc_available','raw_ohlc_consistent','saved_raw_values_exact','lifecycle_ended','extreme_adjusted_jump','unresolved_event_keys']],'price_qualification_changes')
    output(held,'holding_context_restored')
    # Bind an operational stop to the filing; it is neither a sale fill nor cash receipt.
    exas=securities['EXAS']['new_identity_bridge'];source=next(x for x in exas['source_refs'] if x['source_id']=='exas_merger_8k')
    op=pd.DataFrame([{'ticker':'EXAS','known_at':exas['known_by'],'effective_date':exas['effective_date'],
        'reason':'COMMON_STOCK_CONVERTED_TO_UNSETTLED_CASH_RIGHT_NO_EXCHANGE_FILL_NO_CASH_CREDIT',
        'source_id':source['source_id']+':sha256:'+source['sha256']}])
    op.to_csv(OUT/'operational_exit_evidence.csv',index=False)
    last=pd.read_csv(bind(OLD/'LAST_TEST_DATE_TARGETS.csv'),dtype={'cusip':str})
    last=last.loc[last[['quarter','cusip','new_buy_eligible']].isna().any(axis=1)].copy();assert len(last)==54
    last['signal_date']=pd.to_datetime(last.signal_date)
    mapped=last[['candidate','policy','signal_date','ticker','current_weight','target_weight']].merge(result[KEY+['new_buy_eligible','context_only_if_held','qualification_change','effective_cusip']].assign(new_context_available=True),on=KEY,how='left',validate='many_to_one')
    mapped=mapped.merge(sigprice[KEY+['price_quality_warning','price_qualification_reason','unresolved_event_keys']],on=KEY,how='left',validate='many_to_one')
    mapped['new_context_available']=mapped.new_context_available.fillna(False)
    mapped['action_if_context_missing']='ENGINE_PRESERVES_EXISTING_UNITS_NO_IMPLICIT_ZERO_TARGET'
    mapped.loc[mapped.ticker.eq('EXAS'),'action_if_context_missing']='OPERATIONAL_CONVERSION_RIGHT_RETAINED_NO_EXCHANGE_FILL_OR_CASH_CREDIT'
    output(mapped,'old54_account_qualification_mapping')
    # Full candidate coverage: the 45-name correction does not finish the universe.
    coverage=g[KEY+['quarter','final_input_gate']].copy()
    coverage=coverage.merge(candidate[KEY+['new_qualified','qualification_change']],on=KEY,how='left',validate='one_to_one')
    coverage['qualified']=coverage.new_qualified.fillna(coverage.final_input_gate.str.startswith('INPUT_VERIFIED'))
    coverage['unknown']=~coverage.qualified&~coverage.final_input_gate.str.startswith('PROVEN')
    coverage['proven_ineligible']=coverage.final_input_gate.str.startswith('PROVEN')
    cov=coverage.groupby(['signal_date','quarter']).agg(original_candidates=('ticker','size'),qualified_current_pool=('qualified','sum'),unknown_candidates=('unknown','sum'),proven_ineligible=('proven_ineligible','sum')).reset_index()
    cov['context_only_names']=cov.signal_date.map(held.groupby('signal_date').size()).fillna(0).astype(int)
    cov.to_csv(OUT/'coverage.csv',index=False)
    # Independent same-day join/key checks and full frozen input immutability.
    assert int(coverage.qualified.sum())==int(result.new_buy_eligible.sum())
    assert all(sha(p)==h for p,h in INPUTS.items())
    counts=candidate.qualification_change.value_counts().to_dict()
    audit={'status':'QUALIFIED_45_REPAIR_DATA_READY','full_pool_complete':False,'full_pool_formal_test':False,
        'scope_tickers':sorted(names),'scope_note':'45 follow-up securities only; non45 baseline qualification untouched; all results remain qualified-subpool diagnostics.',
        'universe_rule':'LATEST_PUBLISHED_AND_EFFECTIVE_13F_QUARTER','feature_columns':features,
        'signals':{'old_context_rows':len(old),'new_context_rows':len(result),'new_buy_rows':int(result.new_buy_eligible.sum()),'holding_only_rows':len(held),'days':result.signal_date.nunique(),'last':str(LAST_SIGNAL.date()),'candidate_qualification_changes':counts,'restored_candidate_by_ticker':candidate.loc[candidate.qualification_change.eq('RESTORED_CURRENT_POOL')].groupby('ticker').size().to_dict(),'downgraded_candidate_by_ticker':candidate.loc[candidate.qualification_change.eq('DOWNGRADE_UNKNOWN')].groupby('ticker').size().to_dict(),'held_context_by_ticker':held.groupby('ticker').size().to_dict()},
        'full_pool':{'candidate_rows':len(g),'qualified_rows':int(coverage.qualified.sum()),'unknown_rows':int(coverage.unknown.sum()),'proven_ineligible_rows':int(coverage.proven_ineligible.sum())},
        'prices':{'rows':len(price_new),'first':str(price_new.trade_date.min().date()),'last':str(price_new.trade_date.max().date()),'numeric_values_unchanged':True,'scope_change_counts':p.price_qualification_change.value_counts().to_dict(),'downgrade_reasons':p.loc[p.price_qualification_change.eq('DOWNGRADE_UNKNOWN'),'price_qualification_reason'].value_counts().to_dict(),'no_new_price_fetch':True},
        'old54':{'rows':len(mapped),'ticker_count':mapped.ticker.nunique(),'new_context_available_rows':int(mapped.new_context_available.sum()),'new_context_available_tickers':mapped.loc[mapped.new_context_available,'ticker'].unique().tolist()},
        'training_data':{'pre2026_joint_path':str(OLD/'data/pre2026_joint.parquet'),'pre2026_context_path':str(OLD/'data/pre2026_joint_context.parquet'),'joint_audit_path':str(OLD/'data/JOINT_DATA_AUDIT.json'),'test_used_for_fitting':False},
        'calendar_path':str(OLD/'data/calendar.parquet'),'input_sha256':INPUTS,'output_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.parquet','.csv']},
        'validation':{'source_files_unchanged':True,'non45_original_context_values_unchanged':True,'non45_and_pre2026_prices_unchanged':True,'all_numeric_prices_unchanged':True,'all_32_feature_values_equal_materialized_source':True,'signals_not_selected_using_future_execution_price':True,'no_future_identity_anchor_backfill':True,'held_context_never_new_buy':True,'source_identity_bridge_hashes_verified':True,'raw_source_snapshot_hashes_verified':True,'apd_old_approval_explicitly_downgraded':True},
        'limitations':['Not full-pool complete. Unknown remains unknown; retrospective evidence availability can still create selection bias.',
            'Forward affine price-index units are not physical post-split shares or shareholder total-return accounting.',
            'Historical vendor actual receipt remains unproven; only reconstructed public-event evidence contract is qualified.',
            'Price rows before the first prior qualified R6 account identity anchor are conservatively masked in the 45-name 2026 scope.',
            'DTP legacy raw_on_signal/raw_121 fields describe rejected US.DTP lookup. Only exact 233331107/US.DTE corrected R6 rows use actual raw receipts and finite121/version evidence; no general ticker alias rewrite.',
            'No account credit for EXAS USD105 entitlement; settlement is unknown. Operational notice only.',
            'Held-only context must be filtered to names with positive current units by the execution engine.']}
    writejson(OUT/'DATA_RECEIPT.json',audit)
    writejson(OUT/'DATA_AUDIT.json',audit)
    print(json.dumps({k:audit[k] for k in ['status','signals','full_pool','prices','old54']},indent=2,ensure_ascii=False,default=str),flush=True)

if __name__=='__main__':main()
