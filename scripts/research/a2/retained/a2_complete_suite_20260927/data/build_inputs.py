"""Bounded, local-only research inputs. Never upgrades the full-pool test gate.

Signals use R6 verified keys only. No future execution-price availability filter
is used to select signals. Price warnings are exported for the execution layer.
"""
from pathlib import Path
import importlib.util, sys, json, hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
STRICT=HERE.parent.parent/'a2_strict_method_retrain_20260926'
STAGE=STRICT/'test2026_stage'
OLD=HERE.parent.parent/'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1'
SOURCE=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')
PREPRICE=STRICT/'results/pre2026_original_price_coordinate.parquet'
GATE=STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet'
FEATURE=STAGE/'identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet'
RAW_AUDIT=STAGE/'identity_feature_application_r1/CONSUMED_RAW_SOURCE_AUDIT.json'
END=pd.Timestamp('2026-09-24')
LAST_SIGNAL=pd.Timestamp('2026-09-22')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m

def load_raw(code,paths):
    parts=[]
    for p in paths:
        x=pd.read_parquet(p)
        x=x.loc[x.code.astype(str).str.upper().eq(code)].copy()
        parts.append(x)
    x=pd.concat(parts,ignore_index=True)
    x['trade_date']=pd.to_datetime(x.time_key).dt.normalize()
    x=x.loc[x.trade_date.le(END)].copy()
    cols=['open','close','high','low','volume']
    for c in cols:x[c]=pd.to_numeric(x[c],errors='coerce')
    dup=x.loc[x.duplicated('trade_date',keep=False)]
    if len(dup):assert not dup.groupby('trade_date')[cols].nunique().gt(1).any().any(),f'conflicting raw:{code}'
    return x.sort_values('trade_date',kind='mergesort').drop_duplicates('trade_date',keep='last').reset_index(drop=True)

def main():
    g=pd.read_parquet(GATE); f=pd.read_parquet(FEATURE)
    features=tuple(module('suite_original_fit',STRICT/'fit.py').FEATURES)
    assert len(features)==32
    verified=g.final_input_gate.str.startswith('INPUT_VERIFIED')
    v=g.loc[verified].copy()
    assert v.has_32_finite.all() and v.lookback_121_eligible.all()
    assert not v.duplicated(['cusip','title_of_class','quarter','signal_date']).any()
    assert not v.duplicated(['signal_date','ticker']).any()
    identity=['signal_date','quarter','ticker','cusip','title_of_class','moomoo_transport_code','transport_used','final_input_gate']
    out=v[identity].merge(f[['signal_date','ticker',*features]],on=['signal_date','ticker'],validate='one_to_one')
    assert len(out)==len(v) and np.isfinite(out[list(features)].to_numpy(float)).all()

    manifest=pd.read_parquet(SOURCE/'universe/quarterly_universe_manifest.parquet')
    q=manifest.loc[manifest.quarter.isin(['2025Q3','2025Q4','2026Q1']),
        ['quarter','holdings_as_of_date','latest_actual_filing_timestamp','effective_date']].copy()
    q2binding=json.loads((STAGE/'fixed_window_binding/Q2_SOURCE_BINDING.json').read_text())
    source_map=pd.read_csv(OLD/'Q2_ORIGINAL24_SOURCE_MAP.csv')
    latest=pd.to_datetime(source_map.loc[~source_map.source_scope.str.contains('RESTAT'),'accepted_at'],utc=True).max().tz_convert(None).normalize()
    q=pd.concat([q,pd.DataFrame([{'quarter':'2026Q2','holdings_as_of_date':pd.Timestamp('2026-06-30'),
        'latest_actual_filing_timestamp':latest,'effective_date':pd.Timestamp(q2binding['initial_effective_date'])}])],ignore_index=True)
    q=q.rename(columns={'effective_date':'quarter_effective_date','latest_actual_filing_timestamp':'latest_filing_date','holdings_as_of_date':'report_date'}).sort_values('quarter_effective_date')
    for c in ['quarter_effective_date','latest_filing_date','report_date']:q[c]=pd.to_datetime(q[c])
    q['next_quarter_effective_date']=q.quarter_effective_date.shift(-1)
    out=out.merge(q,on='quarter',validate='many_to_one')
    assert out.signal_date.ge(out.quarter_effective_date).all()
    assert out.signal_date.gt(out.latest_filing_date).all()
    assert out.signal_date.gt(out.report_date).all()
    assert (out.next_quarter_effective_date.isna()|out.signal_date.lt(out.next_quarter_effective_date)).all()
    assert out.signal_date.between('2026-01-02',LAST_SIGNAL).all()
    out['pool_scope']='R6_VERIFIED_SUBSET_AVAILABILITY_DIAGNOSTIC'
    out=out.sort_values(['signal_date','ticker']).reset_index(drop=True)
    out.to_parquet(HERE/'test_features.parquet',index=False)
    q.to_csv(HERE/'quarter_timing.csv',index=False)

    cov=g.assign(verified=verified,unknown=g.final_input_gate.str.startswith('UNKNOWN'),ineligible=g.final_input_gate.str.startswith('PROVEN')).groupby(['signal_date','quarter']).agg(
        original_candidates=('ticker','size'),verified_candidates=('verified','sum'),unknown_candidates=('unknown','sum'),proven_ineligible=('ineligible','sum')).reset_index()
    cov['coverage_fraction']=cov.verified_candidates/cov.original_candidates
    cov.to_csv(HERE/'coverage.csv',index=False)
    print(f'features: {len(out)} verified rows, {out.signal_date.nunique()} days, {out.ticker.nunique()} tickers',flush=True)

    original=SOURCE/'scripts/run_rebuild.py'
    rebuild=module('suite_readonly_adjusted_builder',original)
    rebuild.END_EXCLUSIVE=END+pd.Timedelta(days=1)
    r0f1=module('suite_readonly_action_records',Path(r'D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py'))
    wolf=next(x for x in r0f1.frozen_evidence_records() if x['ticker']=='WOLF')
    rehabdirs=[Path(r'D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1')]+[OLD/n for n in
        ['REHAB_NEW_OCCUPIED_ONLY','REHAB_SUBSCRIPTION_ONLY','REHAB_AUTHORITY_ALIASES_ONLY','REHAB_OFFICIAL_COMMON_ALIASES_ONLY']]
    rehab=pd.concat([pd.read_parquet(p/'rehab_factors.parquet') for p in rehabdirs],ignore_index=True)
    assert not rehab.duplicated(['code','ex_div_date']).any()
    rehab_by={code:d for code,d in rehab.groupby('code')}
    rawsources={x['original_code']:x for x in json.loads(RAW_AUDIT.read_text())}
    codes=out[['moomoo_transport_code','transport_used','ticker']].drop_duplicates()
    assert not codes.moomoo_transport_code.duplicated().any()
    unknown_event=g.loc[g.final_input_gate.isin(['UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME','UNKNOWN_UNEXPLAINED_RAW_JUMP','UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY'])].groupby('ticker').signal_date.min().to_dict()
    lifecycle=pd.to_datetime(g.lifecycle_end_exclusive,errors='coerce')
    life=g.assign(lifecycle_date=lifecycle).groupby('ticker').lifecycle_date.min().dropna().to_dict()
    pieces=[];events=[];source_receipts=[];failures=[]
    for i,row in enumerate(codes.itertuples(index=False),1):
        try:
            receipt=rawsources[row.moomoo_transport_code]
            assert receipt['transport']==row.transport_used
            paths=[Path(p) for p in receipt['paths']]
            raw=load_raw(row.transport_used,paths)
            adjusted,ev=rebuild.adjusted_price_frame(row.transport_used,row.ticker,raw,rehab_by.get(row.transport_used,rehab.iloc[:0]),wolf)
            price=adjusted[['ticker','trade_date','open','close','volume']].merge(raw[['trade_date','open','close']],on='trade_date',suffixes=('','_raw'),validate='one_to_one')
            price=price.rename(columns={'open_raw':'raw_open','close_raw':'raw_close'})
            price=price.loc[price.trade_date.ge('2025-06-01')&price.trade_date.le(END)].copy()
            price['price_coordinate']='PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN'
            price['original_transport']=row.moomoo_transport_code;price['transport_used']=row.transport_used
            price['unresolved_event_on_or_before']=price.trade_date.ge(unknown_event[row.ticker]) if row.ticker in unknown_event else False
            price['lifecycle_ended']=price.trade_date.ge(life[row.ticker]) if row.ticker in life else False
            price['extreme_adjusted_jump']=price.close.pct_change(fill_method=None).abs().gt(0.8)
            price['price_quality_warning']=price[['unresolved_event_on_or_before','lifecycle_ended','extreme_adjusted_jump']].any(axis=1)
            pieces.append(price)
            events.extend(ev)
            source_receipts.append({'ticker':row.ticker,'original_code':row.moomoo_transport_code,'transport':row.transport_used,
                'paths':[{'path':str(p),'sha256':sha(p)} for p in paths],'saved_rows':len(price)})
        except Exception as e:
            failures.append({'ticker':row.ticker,'code':row.moomoo_transport_code,'error':f'{type(e).__name__}:{e}'})
        if i%100==0:print(f'prices {i}/{len(codes)}; failures={len(failures)}',flush=True)
    qqqparts=[]
    for year in (2025,2026):
        qp=Path(fr'D:\us-tech-quant-data\moomoo\source\prices_qfq\year={year}\prices.parquet')
        x=pd.read_parquet(qp,columns=['ticker','trade_date','open','close'])
        qqqparts.append(x.loc[x.ticker.eq('QQQ')])
    qextra=pd.read_parquet(STAGE/'qqq_2026_0715_0924_moomoo_qfq.parquet')
    qextra['ticker']='QQQ'
    qqqparts.append(qextra[['ticker','trade_date','open','close']])
    qq=pd.concat(qqqparts,ignore_index=True)
    qq['trade_date']=pd.to_datetime(qq.trade_date).dt.normalize()
    qq=qq.sort_values('trade_date').drop_duplicates('trade_date')
    qq=qq.loc[qq.trade_date.between('2025-06-01',END)].copy()
    qq['price_coordinate']='QQQ_VENDOR_QFQ_BENCHMARK';qq['price_quality_warning']=False
    for c in ['unresolved_event_on_or_before','lifecycle_ended','extreme_adjusted_jump']:qq[c]=False
    prices=pd.concat([*pieces,qq],ignore_index=True).sort_values(['ticker','trade_date']).reset_index(drop=True)
    assert not prices.duplicated(['ticker','trade_date']).any()
    assert np.isfinite(prices[['open','close']]).all().all() and prices[['open','close']].gt(0).all().all()
    prices.to_parquet(HERE/'test_prices.parquet',index=False)
    calendar=qq[['trade_date']].copy();calendar['is_test']=calendar.trade_date.ge('2026-01-01')
    calendar['is_signal']=calendar.trade_date.isin(out.signal_date.unique())
    calendar.to_parquet(HERE/'calendar.parquet',index=False)
    pd.DataFrame(events).to_parquet(HERE/'consumed_price_events.parquet',index=False)
    (HERE/'PRICE_SOURCE_RECEIPTS.json').write_text(json.dumps(source_receipts,indent=2),encoding='utf-8')
    (HERE/'PRICE_BUILD_FAILURES.json').write_text(json.dumps(failures,indent=2),encoding='utf-8')
    audit={'status':'LOCAL_VERIFIED_SUBPOOL_RESEARCH_INPUTS_READY','full_pool_formal_test':False,
        'warning':'Availability-limited subset selected using retrospective evidence completeness; selection/survivorship bias cannot be ruled out. Not a pristine blind test or full 13F pool TOP20.',
        'price_warning':'Affine forward rehabilitation index is a research coordinate, not tradable raw shares or shareholder total return. Price warnings require execution-layer handling; never exclude signals using future prices.',
        'signals':{'rows':len(out),'days':out.signal_date.nunique(),'tickers':out.ticker.nunique(),'first':str(out.signal_date.min().date()),'last':str(out.signal_date.max().date()),'all_strict_r6_verified':True,'unknown_included':0,'min_names':int(out.groupby('signal_date').size().min()),'max_names':int(out.groupby('signal_date').size().max())},
        'coverage':{'original_rows':len(g),'verified_rows':len(out),'unknown_rows':int(g.final_input_gate.str.startswith('UNKNOWN').sum()),'complete_signal_days':int(cov.unknown_candidates.eq(0).sum())},
        'prices':{'rows':len(prices),'tickers':prices.ticker.nunique(),'first':str(prices.trade_date.min().date()),'last':str(prices.trade_date.max().date()),'build_failures':failures,'warning_rows':int(prices.price_quality_warning.sum()),'signal_rows_not_filtered_by_future_execution_prices':True},
        'temporal_checks':{'report_before_signal':True,'filing_before_signal':True,'effective_before_or_on_signal':True,'latest_available_quarter_used':True,'q2_restatement_does_not_change_candidate_set':True},
        'feature_columns':features,'features_source':str(STRICT/'fit.py'),'training_matrix_path':str(SOURCE/'A2/training_matrix.parquet'),'pre2026_price_path':str(PREPRICE),
        'input_sha256':{str(p):sha(p) for p in [GATE,FEATURE,RAW_AUDIT,original,PREPRICE,SOURCE/'universe/quarterly_universe_manifest.parquet',STAGE/'fixed_window_binding/Q2_SOURCE_BINDING.json']},
        'outputs_sha256':{p.name:sha(p) for p in [HERE/'test_features.parquet',HERE/'test_prices.parquet',HERE/'calendar.parquet',HERE/'coverage.csv']},
        'network_requests':0,'model_fit_calls':0,'test_preprocessing_fit_calls':0}
    (HERE/'DATA_AUDIT.json').write_text(json.dumps(audit,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:audit[k] for k in ['status','signals','coverage','prices']},default=str),flush=True)
    from build_joint_inputs import natural_quarter_test
    print(json.dumps(natural_quarter_test(),indent=2),flush=True)

if __name__=='__main__':main()
