"""Joint portfolio-training rows using the latest publicly effective 13F pool."""
from pathlib import Path
import argparse, json, hashlib, importlib.util, os, shutil, sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
SAVED=HERE.parent.parent/'a2_complete_suite_20260927'/'data'
STRICT=HERE.parent.parent/'a2_strict_method_retrain_20260926'
SOURCE=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def latest_effective_mask(frame, timing, quarter_column):
    """Validate each row against the most recent quarter effective by signal close."""
    needed={'quarter','latest_filing_date','quarter_effective_date'}
    if not needed.issubset(timing.columns):raise ValueError(f'missing timing columns: {needed-set(timing.columns)}')
    q=timing[['quarter','latest_filing_date','quarter_effective_date']].drop_duplicates().copy()
    for col in ['latest_filing_date','quarter_effective_date']:q[col]=pd.to_datetime(q[col])
    if q.isna().any().any() or q.quarter.duplicated().any() or q.quarter_effective_date.duplicated().any():
        raise ValueError('missing or duplicate 13F quarter timing')
    if not q.quarter_effective_date.gt(q.latest_filing_date).all():
        raise ValueError('13F quarter effective before public filing')
    q=q.sort_values('quarter_effective_date')
    dates=pd.DataFrame({'signal_date':pd.DatetimeIndex(pd.to_datetime(frame.signal_date).unique()).sort_values()})
    expected=pd.merge_asof(dates,q[['quarter','quarter_effective_date']],
        left_on='signal_date',right_on='quarter_effective_date',direction='backward')
    expected=expected.set_index('signal_date').quarter
    actual=frame[quarter_column].astype(str)
    matched=actual.eq(frame.signal_date.map(expected).astype(str))
    row_timing=frame[[quarter_column,'signal_date']].merge(
        q.rename(columns={'quarter':quarter_column}),on=quarter_column,how='left',validate='many_to_one')
    public=row_timing.signal_date.gt(row_timing.latest_filing_date)
    effective=row_timing.signal_date.ge(row_timing.quarter_effective_date)
    allowed=(matched.to_numpy() & public.to_numpy() & effective.to_numpy())
    if not allowed.all():
        bad=frame.loc[~allowed,['signal_date',quarter_column]].head(5).to_dict('records')
        raise ValueError(f'13F latest-effective source mismatch: {bad}')
    return pd.Series(allowed,index=frame.index,dtype=bool)


def rebind_saved_context(output_dir):
    """Write a new input batch from saved context; preserve all prior artifacts."""
    output_dir=Path(output_dir).resolve()
    if output_dir==SAVED.resolve():
        raise ValueError('cannot write to the original input batch')
    names=['pre2026_joint.parquet','pre2026_joint_context.parquet','test_features.parquet','test_features_context.parquet',
        'pre2026_joint_coverage.csv','coverage.csv','test_prices.parquet','calendar.parquet','quarter_timing.csv',
        'DATA_AUDIT.json','JOINT_DATA_AUDIT.json','LATEST_EFFECTIVE_INPUT_AUDIT.json']
    if any((output_dir/name).exists() for name in names):
        raise FileExistsError('new input output already exists; never overwrite a first result')
    old_test_audit=json.loads((SAVED/'DATA_AUDIT.json').read_text(encoding='utf-8'))
    old_pre_audit=json.loads((SAVED/'JOINT_DATA_AUDIT.json').read_text(encoding='utf-8'))
    checked={'test_features_context.parquet':old_test_audit,'test_prices.parquet':old_test_audit,
        'calendar.parquet':old_test_audit,'coverage.csv':old_test_audit,
        'pre2026_joint_context.parquet':old_pre_audit}
    for name,source_audit in checked.items():
        if sha(SAVED/name)!=source_audit['outputs_sha256'][name]:
            raise ValueError(f'saved source receipt hash mismatch: {name}')
    pre=pd.read_parquet(SAVED/'pre2026_joint_context.parquet')
    test=pd.read_parquet(SAVED/'test_features_context.parquet')
    pre_timing=pre[['active_13f_quarter','latest_filing_date','quarter_effective_date']].drop_duplicates().rename(columns={'active_13f_quarter':'quarter'})
    test_timing=pd.read_csv(SAVED/'quarter_timing.csv',parse_dates=['latest_filing_date','quarter_effective_date'])
    pre['new_buy_eligible']=latest_effective_mask(pre,pre_timing,'active_13f_quarter')
    test['new_buy_eligible']=latest_effective_mask(test,test_timing,'quarter')
    pre=pre.drop(columns=['required_report_quarter'],errors='ignore')
    test=test.drop(columns=['required_report_quarter'],errors='ignore')
    pre_cov=pre.groupby('signal_date').agg(context_names=('ticker','size'),new_buy_names=('new_buy_eligible','sum'),available_labels=('label_available','sum')).reset_index()
    cov=pd.read_csv(SAVED/'coverage.csv',parse_dates=['signal_date'])
    cov=cov.drop(columns=['strict_previous_natural_quarter_buy_names','cash_only_for_new_buys'],errors='ignore')
    count=test.groupby('signal_date').size()
    cov['latest_effective_buy_names']=cov.signal_date.map(count).fillna(0).astype(int)
    output_dir.mkdir(parents=True,exist_ok=True)
    outputs={'pre2026_joint.parquet':pre,'test_features.parquet':test,
        'pre2026_joint_coverage.csv':pre_cov,'coverage.csv':cov}
    for name,value in outputs.items():
        dest=output_dir/name
        if dest.suffix=='.csv':value.to_csv(dest,index=False)
        else:value.to_parquet(dest,index=False)
    # The whole saved context is now eligible. Hardlinks avoid a second 114 MB
    # parquet copy while all four inputs remain immutable within this batch.
    os.link(output_dir/'pre2026_joint.parquet',output_dir/'pre2026_joint_context.parquet')
    os.link(output_dir/'test_features.parquet',output_dir/'test_features_context.parquet')
    for name in ['test_prices.parquet','calendar.parquet','quarter_timing.csv']:
        shutil.copy2(SAVED/name,output_dir/name)
        if sha(SAVED/name)!=sha(output_dir/name):raise ValueError(f'copy verification failed: {name}')
    test_audit=dict(old_test_audit)
    test_audit.pop('previous_natural_quarter_rule',None)
    test_audit.pop('signals_before_natural_quarter_filter',None)
    test_audit['buy_pool_rule']='latest publicly filed and effective 13F quarter at signal close; previous effective quarter persists until successor effective'
    test_audit['signals']={'rows':len(test),'days':test.signal_date.nunique(),'tickers':test.ticker.nunique(),
        'first':str(test.signal_date.min().date()),'last':str(test.signal_date.max().date()),
        'all_strict_r6_verified':True,'unknown_included':0,
        'min_names':int(test.groupby('signal_date').size().min()),'max_names':int(test.groupby('signal_date').size().max())}
    test_audit['outputs_sha256']={name:sha(output_dir/name) for name in
        ['test_features.parquet','test_features_context.parquet','test_prices.parquet','calendar.parquet','coverage.csv']}
    test_audit['source_audit_sha256']=sha(SAVED/'DATA_AUDIT.json')
    (output_dir/'DATA_AUDIT.json').write_text(json.dumps(test_audit,indent=2,default=str),encoding='utf-8')
    pre_audit=dict(old_pre_audit)
    for name in ['strict_previous_natural_quarter','strict_buy_rows','strict_buy_days','strict_buy_available_labels']:
        pre_audit.pop(name,None)
    pre_audit['latest_publicly_effective_quarter']=True
    pre_audit['buy_rows']=len(pre)
    pre_audit['buy_days']=pre.signal_date.nunique()
    pre_audit['buy_available_labels']=int(pre.label_available.sum())
    pre_audit['empty_new_buy_days']=0
    pre_audit['outputs_sha256']={name:sha(output_dir/name) for name in
        ['pre2026_joint.parquet','pre2026_joint_context.parquet','pre2026_joint_coverage.csv']}
    pre_audit['source_audit_sha256']=sha(SAVED/'JOINT_DATA_AUDIT.json')
    (output_dir/'JOINT_DATA_AUDIT.json').write_text(json.dumps(pre_audit,indent=2,default=str),encoding='utf-8')
    audit={'rule':'latest publicly filed and effective 13F quarter at each signal close; prior effective quarter remains until successor effective',
        'source_context_sha256':{p.name:sha(p) for p in [SAVED/'pre2026_joint_context.parquet',SAVED/'test_features_context.parquet',SAVED/'quarter_timing.csv']},
        'pre2026_rows':len(pre),'pre2026_days':pre.signal_date.nunique(),
        'test_verified_subset_rows':len(test),'test_days':test.signal_date.nunique(),
        'full_2026_pool_test':False,'model_fit_calls':0,'preprocessing_fit_calls':0,
        'outputs_sha256':{name:sha(output_dir/name) for name in names if name!='LATEST_EFFECTIVE_INPUT_AUDIT.json'}}
    (output_dir/'LATEST_EFFECTIVE_INPUT_AUDIT.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    return audit

def build_joint():
    spec=importlib.util.spec_from_file_location('joint_source_fit',STRICT/'fit.py')
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    features=list(m.FEATURES)
    scorepath=SOURCE/'A/score_rank_ledger.parquet'
    memberpath=SOURCE/'universe/daily_eligible_universe_membership.parquet'
    pricepath=STRICT/'results/pre2026_original_price_coordinate.parquet'
    matrixpath=SOURCE/'A2/training_matrix.parquet'
    x=pd.read_parquet(scorepath,columns=['signal_date','ticker','close',*features])
    x=x.loc[x.signal_date.dt.year.isin([2023,2024,2025])].copy()
    member=pd.read_parquet(memberpath,columns=['signal_date','ticker','active_13f_quarter','moomoo_transport_code','cusip'])
    x=x.merge(member,on=['signal_date','ticker'],validate='one_to_one')
    q=pd.read_parquet(SOURCE/'universe/quarterly_universe_manifest.parquet',columns=['quarter','holdings_as_of_date','latest_actual_filing_timestamp','effective_date'])
    q=q.rename(columns={'quarter':'active_13f_quarter','holdings_as_of_date':'report_date','latest_actual_filing_timestamp':'latest_filing_date','effective_date':'quarter_effective_date'})
    x=x.merge(q,on='active_13f_quarter',validate='many_to_one')
    x['new_buy_eligible']=latest_effective_mask(x,q.rename(columns={'active_13f_quarter':'quarter'}),'active_13f_quarter')
    p=pd.read_parquet(pricepath,columns=['ticker','trade_date','open','close'])
    assert p.trade_date.lt('2026-01-01').all()
    calendar=pd.DatetimeIndex(p.loc[p.ticker.eq('QQQ'),'trade_date']).sort_values().unique()
    cmap=pd.DataFrame({'signal_date':calendar,'execution_date':pd.Series(calendar).shift(-1),'label_end_date':pd.Series(calendar).shift(-2)})
    x=x.merge(cmap,on='signal_date',validate='many_to_one')
    x=x.merge(p[['ticker','trade_date','open']].rename(columns={'trade_date':'execution_date','open':'next_open'}),on=['ticker','execution_date'],how='left',validate='many_to_one')
    x=x.merge(p[['ticker','trade_date','open']].rename(columns={'trade_date':'label_end_date','open':'following_open'}),on=['ticker','label_end_date'],how='left',validate='many_to_one')
    x['y_next_open']=x.following_open/x.next_open-1
    x['label_available']=np.isfinite(x.y_next_open)&x.next_open.gt(0)&x.following_open.gt(0)&x.label_end_date.lt('2026-01-01')
    x['label_price_warning']=x.y_next_open.abs().gt(0.8)
    targets=pd.read_parquet(matrixpath,columns=['signal_date','ticker','target','target_end_date'])
    x=x.merge(targets,on=['signal_date','ticker'],how='left',validate='one_to_one')
    x['target_context_available']=x.target.notna()&x.target_end_date.lt('2026-01-01')
    x['price_coordinate']='PIT_FORWARD_REHAB_AFFINE_INDEX_NOT_SHAREHOLDER_RETURN'
    x=x.sort_values(['signal_date','ticker']).reset_index(drop=True)
    assert len(x)==313668 and not x.duplicated(['signal_date','ticker']).any()
    assert np.isfinite(x[features]).all().all()
    assert x.loc[x.label_available,'label_end_date'].lt('2026-01-01').all()
    assert x.loc[x.target_context_available,'target_end_date'].lt('2026-01-01').all()
    x.to_parquet(HERE/'pre2026_joint_context.parquet',index=False)
    # The effective buy pool retains unavailable one-step labels, explicitly marked;
    # model training must mask label_available, inference must not require it.
    buy=x.loc[x.new_buy_eligible].copy()
    buy.to_parquet(HERE/'pre2026_joint.parquet',index=False)
    daily=x.groupby('signal_date').agg(context_names=('ticker','size'),new_buy_names=('new_buy_eligible','sum'),available_labels=('label_available','sum')).reset_index()
    daily.to_csv(HERE/'pre2026_joint_coverage.csv',index=False)
    summary={'status':'PRE2026_JOINT_INPUTS_READY','definition':'signal close features; next QQQ-session open execution; following QQQ-session open mark; y_next_open is uncosted one-session index return. Cost belongs in portfolio utility.',
        'latest_publicly_effective_quarter':True,'context_rows':len(x),'buy_rows':len(buy),'context_days':x.signal_date.nunique(),'buy_days':buy.signal_date.nunique(),'empty_new_buy_days':int(daily.new_buy_names.eq(0).sum()),
        'training_years':[2023,2024],'validation_year':2025,'final_fit_years':[2023,2024,2025],
        'max_feature_date':str(x.signal_date.max().date()),'max_available_label_end':str(x.loc[x.label_available,'label_end_date'].max().date()),'non_pre2026_valid_labels':int(x.loc[x.label_available,'label_end_date'].ge('2026-01-01').sum()),
        'context_available_labels':int(x.label_available.sum()),'buy_available_labels':int(buy.label_available.sum()),'unavailable_labels_retained':int((~x.label_available).sum()),'extreme_index_return_labels_flagged':int(x.label_price_warning.sum()),
        'target_context_note':'Original 3/5/10/20-session mean excess target only where matured by 2025-12-31; not an input feature for an action policy.',
        'target_context_rows':int(x.target_context_available.sum()),'max_target_end':str(x.target_end_date.max().date()),'features':features,'pre2026_price_path':str(pricepath),
        'price_note':'Research affine adjusted coordinate; not shareholder total return. Missing/extraneous outcomes are marked, not used to prefilter prediction candidates.',
        'test_data_used_for_pre2026_rows_or_filters':False,'network_requests':0,'fit_calls':0,
        'input_sha256':{str(p):sha(p) for p in [scorepath,memberpath,pricepath,matrixpath]},
        'outputs_sha256':{p.name:sha(p) for p in [HERE/'pre2026_joint.parquet',HERE/'pre2026_joint_context.parquet',HERE/'pre2026_joint_coverage.csv']}}
    (HERE/'JOINT_DATA_AUDIT.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--rebind-saved-context',required=True,type=Path,metavar='NEW_OUTPUT_DIR',
        help='write this new batch from the saved verified context without raw rebuild or model fit')
    args=parser.parse_args()
    print(json.dumps(rebind_saved_context(args.rebind_saved_context),indent=2))
