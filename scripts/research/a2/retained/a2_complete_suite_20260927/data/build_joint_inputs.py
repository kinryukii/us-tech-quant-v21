"""Joint portfolio-training rows and strict previous-calendar-quarter buy eligibility."""
from pathlib import Path
import json, hashlib, importlib.util, sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
STRICT=HERE.parent.parent/'a2_strict_method_retrain_20260926'
SOURCE=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def natural_quarter_test():
    original=HERE/'test_features.parquet'
    context=HERE/'test_features_context.parquet'
    x=pd.read_parquet(context if context.exists() else original)
    x['required_report_quarter']=(x.signal_date.dt.to_period('Q')-1).astype(str)
    x['new_buy_eligible']=x.quarter.eq(x.required_report_quarter)
    x.to_parquet(context,index=False)
    filtered=x.loc[x.new_buy_eligible].copy()
    filtered.to_parquet(original,index=False)
    cov=pd.read_csv(HERE/'coverage.csv',parse_dates=['signal_date'])
    count=filtered.groupby('signal_date').size()
    cov['strict_previous_natural_quarter_buy_names']=cov.signal_date.map(count).fillna(0).astype(int)
    cov['cash_only_for_new_buys']=cov.strict_previous_natural_quarter_buy_names.eq(0)
    cov.to_csv(HERE/'coverage.csv',index=False)
    auditpath=HERE/'DATA_AUDIT.json'
    audit=json.loads(auditpath.read_text())
    audit['previous_natural_quarter_rule']={'required':True,'definition':'report quarter must equal signal calendar quarter minus one; also public and effective by signal close','original_verified_context_rows':len(x),'strict_buy_rows':len(filtered),'strict_buy_signal_days':filtered.signal_date.nunique(),'empty_new_buy_signal_days':int(cov.cash_only_for_new_buys.sum()),'context_file':str(context),'holding_exit_context_kept':True}
    audit['signals_before_natural_quarter_filter']=audit['signals']
    audit['signals']={'rows':len(filtered),'days':filtered.signal_date.nunique(),'tickers':filtered.ticker.nunique(),'first':str(filtered.signal_date.min().date()),'last':str(filtered.signal_date.max().date()),'all_strict_r6_verified':True,'unknown_included':0,'min_names_on_buy_days':int(filtered.groupby('signal_date').size().min()),'calendar_preserves_empty_days':True}
    audit['outputs_sha256'].update({p.name:sha(p) for p in [original,context,HERE/'coverage.csv']})
    auditpath.write_text(json.dumps(audit,indent=2),encoding='utf-8')
    return audit['previous_natural_quarter_rule']

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
    x['required_report_quarter']=(x.signal_date.dt.to_period('Q')-1).astype(str)
    x['new_buy_eligible']=x.active_13f_quarter.eq(x.required_report_quarter)&x.signal_date.ge(x.quarter_effective_date)&x.signal_date.gt(x.latest_filing_date)
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
    # The strict buy pool retains unavailable one-step labels, explicitly marked;
    # model training must mask label_available, inference must not require it.
    strict=x.loc[x.new_buy_eligible].copy()
    strict.to_parquet(HERE/'pre2026_joint.parquet',index=False)
    daily=x.groupby('signal_date').agg(context_names=('ticker','size'),new_buy_names=('new_buy_eligible','sum'),available_labels=('label_available','sum')).reset_index()
    daily.to_csv(HERE/'pre2026_joint_coverage.csv',index=False)
    summary={'status':'PRE2026_JOINT_INPUTS_READY','definition':'signal close features; next QQQ-session open execution; following QQQ-session open mark; y_next_open is uncosted one-session index return. Cost belongs in portfolio utility.',
        'strict_previous_natural_quarter':True,'context_rows':len(x),'strict_buy_rows':len(strict),'context_days':x.signal_date.nunique(),'strict_buy_days':strict.signal_date.nunique(),'empty_new_buy_days':int(daily.new_buy_names.eq(0).sum()),
        'training_years':[2023,2024],'validation_year':2025,'final_fit_years':[2023,2024,2025],
        'max_feature_date':str(x.signal_date.max().date()),'max_available_label_end':str(x.loc[x.label_available,'label_end_date'].max().date()),'non_pre2026_valid_labels':int(x.loc[x.label_available,'label_end_date'].ge('2026-01-01').sum()),
        'context_available_labels':int(x.label_available.sum()),'strict_buy_available_labels':int(strict.label_available.sum()),'unavailable_labels_retained':int((~x.label_available).sum()),'extreme_index_return_labels_flagged':int(x.label_price_warning.sum()),
        'target_context_note':'Original 3/5/10/20-session mean excess target only where matured by 2025-12-31; not an input feature for an action policy.',
        'target_context_rows':int(x.target_context_available.sum()),'max_target_end':str(x.target_end_date.max().date()),'features':features,'pre2026_price_path':str(pricepath),
        'price_note':'Research affine adjusted coordinate; not shareholder total return. Missing/extraneous outcomes are marked, not used to prefilter prediction candidates.',
        'test_data_used_for_pre2026_rows_or_filters':False,'network_requests':0,'fit_calls':0,
        'input_sha256':{str(p):sha(p) for p in [scorepath,memberpath,pricepath,matrixpath]},
        'outputs_sha256':{p.name:sha(p) for p in [HERE/'pre2026_joint.parquet',HERE/'pre2026_joint_context.parquet',HERE/'pre2026_joint_coverage.csv']}}
    (HERE/'JOINT_DATA_AUDIT.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary

if __name__=='__main__':
    print(json.dumps(build_joint(),indent=2))
    if (HERE/'DATA_AUDIT.json').exists():print(json.dumps(natural_quarter_test(),indent=2))
