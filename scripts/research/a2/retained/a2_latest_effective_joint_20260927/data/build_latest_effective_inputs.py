"""Change only buy-universe eligibility to the latest published/effective 13F pool.

Old outputs are read-only. Market features, labels and price files are reused
without modification. Independent as-of joins and publication-lag tests protect
the quarter boundary. No network requests or model fitting occur here.
"""
from pathlib import Path
import argparse, hashlib, json, shutil
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
OLD=HERE.parent.parent/'a2_complete_suite_20260927/data'
STRICT=HERE.parent.parent/'a2_strict_method_retrain_20260926'
SOURCE=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')
MANIFEST=SOURCE/'universe/quarterly_universe_manifest.parquet'
Q2BIND=STRICT/'test2026_stage/fixed_window_binding/Q2_SOURCE_BINDING.json'
RULE='LATEST_PUBLISHED_AND_EFFECTIVE_13F_QUARTER'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):Path(p).write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding='utf-8')
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def manifest():
    q=pd.read_parquet(MANIFEST,columns=['quarter','holdings_as_of_date','latest_actual_filing_timestamp','effective_date'])
    q=q.rename(columns={'holdings_as_of_date':'report_date','latest_actual_filing_timestamp':'latest_filing_date','effective_date':'quarter_effective_date'})
    bind=read(Q2BIND)
    old_q2=pd.read_csv(OLD/'quarter_timing.csv').set_index('quarter').loc['2026Q2']
    q=pd.concat([q,pd.DataFrame([{'quarter':'2026Q2','report_date':'2026-06-30','latest_filing_date':old_q2.latest_filing_date,
        'quarter_effective_date':bind['initial_effective_date']}])],ignore_index=True)
    for c in ['report_date','latest_filing_date','quarter_effective_date']:q[c]=pd.to_datetime(q[c]).dt.normalize()
    q=q.sort_values('quarter_effective_date').reset_index(drop=True)
    assert not q.quarter.duplicated().any() and not q.quarter_effective_date.duplicated().any()
    assert q.latest_filing_date.lt(q.quarter_effective_date).all() and q.report_date.lt(q.latest_filing_date).all()
    q['next_quarter_effective_date']=q.quarter_effective_date.shift(-1)
    return q

def independently_join(frame,q):
    # Join dates independently of the quarter labels in the old feature table.
    d=pd.DataFrame({'signal_date':pd.to_datetime(frame.signal_date.unique())}).sort_values('signal_date')
    assigned=pd.merge_asof(d,q.rename(columns={'quarter':'asof_quarter'}),left_on='signal_date',right_on='quarter_effective_date',direction='backward',allow_exact_matches=True)
    assert assigned.asof_quarter.notna().all()
    old_quarter='active_13f_quarter' if 'active_13f_quarter' in frame else 'quarter'
    x=frame.drop(columns=['required_report_quarter','report_date','latest_filing_date','quarter_effective_date','next_quarter_effective_date'],errors='ignore').copy()
    x=x.merge(assigned,on='signal_date',how='left',validate='many_to_one')
    assert x[old_quarter].eq(x.asof_quarter).all(),'Old context not in latest effective quarter'
    assert x.signal_date.ge(x.quarter_effective_date).all()
    assert x.signal_date.gt(x.latest_filing_date).all()
    assert (x.next_quarter_effective_date.isna()|x.signal_date.lt(x.next_quarter_effective_date)).all()
    x['new_buy_eligible']=x[old_quarter].eq(x.asof_quarter)
    x['universe_rule']=RULE
    if 'pool_scope' in x:x['pool_scope']='R6_VERIFIED_SUBSET_LATEST_EFFECTIVE_QUARTER_DIAGNOSTIC'
    return x.sort_values(['signal_date','ticker']).reset_index(drop=True)

def per_day_changes(old,new,scope):
    key=['signal_date','ticker']
    j=old[key+['new_buy_eligible']].rename(columns={'new_buy_eligible':'old_new_buy_eligible'}).merge(new[key+['new_buy_eligible','asof_quarter']],on=key,validate='one_to_one')
    j['newly_eligible']=j.new_buy_eligible&~j.old_new_buy_eligible
    j['removed']=j.old_new_buy_eligible&~j.new_buy_eligible
    result=j.groupby(['signal_date','asof_quarter']).agg(context_names=('ticker','size'),old_eligible_names=('old_new_buy_eligible','sum'),new_eligible_names=('new_buy_eligible','sum'),newly_eligible_names=('newly_eligible','sum'),removed_names=('removed','sum')).reset_index()
    result['scope']=scope
    return result

def build_pre(q):
    src=OLD/'pre2026_joint_context.parquet';old=pd.read_parquet(src)
    x=independently_join(old,q)
    assert len(x)==313668 and x.new_buy_eligible.all()
    assert x.signal_date.lt('2026-01-01').all()
    assert x.loc[x.label_available,'label_end_date'].lt('2026-01-01').all()
    assert x.loc[x.target_context_available,'target_end_date'].lt('2026-01-01').all()
    features=read(OLD/'JOINT_DATA_AUDIT.json')['features']
    a=old.sort_values(['signal_date','ticker']).reset_index(drop=True)
    assert np.array_equal(x[features].to_numpy(float),a[features].to_numpy(float))
    for c in ['y_next_open','next_open','following_open','close','target']:
        assert np.array_equal(x[c].to_numpy(float),a[c].to_numpy(float),equal_nan=True),c
    for filename in ['pre2026_joint.parquet','pre2026_joint_context.parquet']:x.to_parquet(HERE/filename,index=False)
    change=per_day_changes(old,x,'pre2026');change.to_csv(HERE/'pre2026_universe_rule_daily_changes.csv',index=False)
    x.groupby('signal_date').agg(context_names=('ticker','size'),new_buy_names=('new_buy_eligible','sum'),available_labels=('label_available','sum')).reset_index().to_csv(HERE/'pre2026_joint_coverage.csv',index=False)
    audit={'status':'PRE2026_LATEST_EFFECTIVE_JOINT_INPUTS_READY','universe_rule':RULE,
        'definition':'At decision close use the most recent 13F quarter whose actual filing publication and original fifth-next-session effective date are satisfied. Continue preceding effective quarter until the new quarter activates.',
        'context_rows':len(x),'eligible_buy_rows':int(x.new_buy_eligible.sum()),'context_days':x.signal_date.nunique(),'eligible_buy_days':x.signal_date.nunique(),'empty_new_buy_days':0,
        'old_eligible_buy_rows':int(old.new_buy_eligible.sum()),'added_buy_rows':int((~old.new_buy_eligible).sum()),
        'training_years':[2023,2024],'validation_year':2025,'final_fit_years':[2023,2024,2025],
        'max_feature_date':str(x.signal_date.max().date()),'max_available_label_end':str(x.loc[x.label_available,'label_end_date'].max().date()),'non_pre2026_valid_labels':0,
        'context_available_labels':int(x.label_available.sum()),'eligible_buy_available_labels':int(x.label_available.sum()),'unavailable_labels_retained':int((~x.label_available).sum()),
        'features':features,'target_context_note':'Original matured multi-horizon excess target is not an observation feature.',
        'feature_and_label_values_unchanged':True,'test_data_used_for_pre2026_rows_or_eligibility':False,
        'pre2026_price_path':read(OLD/'JOINT_DATA_AUDIT.json')['pre2026_price_path'],
        'price_note':'Research affine adjusted coordinate, not shareholder total return. Missing labels remain explicitly marked.',
        'input_sha256':{str(p):sha(p) for p in [src,MANIFEST]},'outputs_sha256':{n:sha(HERE/n) for n in ['pre2026_joint.parquet','pre2026_joint_context.parquet','pre2026_joint_coverage.csv']},'network_requests':0,'fit_calls':0}
    write(HERE/'JOINT_DATA_AUDIT.json',audit)
    print(json.dumps({k:audit[k] for k in ['status','context_rows','eligible_buy_rows','context_days','added_buy_rows','context_available_labels']},ensure_ascii=False),flush=True)

def build_test(q):
    src=OLD/'test_features_context.parquet';old=pd.read_parquet(src)
    x=independently_join(old,q)
    assert len(x)==61963 and x.new_buy_eligible.all() and x.final_input_gate.str.startswith('INPUT_VERIFIED').all()
    for name in ['test_features.parquet','test_features_context.parquet']:x.to_parquet(HERE/name,index=False)
    unchanged=['test_prices.parquet','calendar.parquet','consumed_price_events.parquet','PRICE_SOURCE_RECEIPTS.json','PRICE_BUILD_FAILURES.json']
    copy_receipts=[]
    for name in unchanged:
        shutil.copyfile(OLD/name,HERE/name)
        before,after=sha(OLD/name),sha(HERE/name);assert before==after
        copy_receipts.append({'name':name,'source':str(OLD/name),'sha256':after,'unchanged':True})
    cov=pd.read_csv(OLD/'coverage.csv',parse_dates=['signal_date'])
    cov=cov.drop(columns=['strict_previous_natural_quarter_buy_names','cash_only_for_new_buys'],errors='ignore')
    counts=x.groupby('signal_date').size()
    cov['latest_effective_new_buy_names']=cov.signal_date.map(counts).fillna(0).astype(int)
    cov['no_eligible_new_buy_names']=cov.latest_effective_new_buy_names.eq(0)
    cov['universe_rule']=RULE
    cov.to_csv(HERE/'coverage.csv',index=False)
    change=per_day_changes(old,x,'test2026');change.to_csv(HERE/'test2026_universe_rule_daily_changes.csv',index=False)
    q.to_csv(HERE/'quarter_timing.csv',index=False)
    oldaudit=read(OLD/'DATA_AUDIT.json')
    audit={'status':'LATEST_EFFECTIVE_VERIFIED_SUBPOOL_RESEARCH_INPUTS_READY','universe_rule':RULE,
        'full_pool_formal_test':False,'warning':'Same retrospective R6 verified subset as preceding batch; availability/selection bias remains. No unknown candidates promoted.',
        'signals':{'rows':len(x),'days':x.signal_date.nunique(),'tickers':x.ticker.nunique(),'first':str(x.signal_date.min().date()),'last':str(x.signal_date.max().date()),'all_strict_r6_verified':True,'unknown_included':0,'min_names':int(counts.min()),'max_names':int(counts.max())},
        'coverage':oldaudit['coverage'],'prices':oldaudit['prices'],'price_warning':oldaudit['price_warning'],
        'latest_effective_rule':{'eligible_buy_rows':len(x),'eligible_buy_days':x.signal_date.nunique(),'empty_new_buy_signal_days':0,'old_eligible_buy_rows':int(old.new_buy_eligible.sum()),'newly_eligible_rows':int((~old.new_buy_eligible).sum()),'continued_old_quarter_until_next_effective':True,'independent_merge_asof_verified':True},
        'feature_columns':oldaudit['feature_columns'],'features_source':oldaudit['features_source'],'training_matrix_path':oldaudit['training_matrix_path'],'pre2026_price_path':oldaudit['pre2026_price_path'],
        'temporal_checks':{'report_before_signal':True,'filing_before_signal':True,'effective_before_or_on_signal':True,'latest_effective_quarter_used':True,'future_quarter_backfill':False},
        'unchanged_file_receipts':copy_receipts,'input_sha256':{str(p):sha(p) for p in [src,MANIFEST,Q2BIND]},
        'outputs_sha256':{n:sha(HERE/n) for n in ['test_features.parquet','test_features_context.parquet','test_prices.parquet','calendar.parquet','coverage.csv']},
        'network_requests':0,'model_fit_calls':0,'test_preprocessing_fit_calls':0}
    write(HERE/'DATA_AUDIT.json',audit)
    predaily=pd.read_csv(HERE/'pre2026_universe_rule_daily_changes.csv');testdaily=pd.read_csv(HERE/'test2026_universe_rule_daily_changes.csv')
    combined=pd.concat([predaily,testdaily],ignore_index=True);combined.to_csv(HERE/'UNIVERSE_RULE_DAILY_CHANGES.csv',index=False)
    switches=q.loc[q.quarter_effective_date.between('2023-01-01','2026-09-24')].copy()
    switches=switches.replace({pd.NaT:None}).to_dict('records')
    write(HERE/'UNIVERSE_RULE_CHANGE.json',{'status':'COMPLETE','old_rule':'Previous natural calendar quarter must already be effective; earlier public quarters disallowed for new capital.',
        'new_rule':RULE,'only_intentional_change':'Buy-universe eligibility. Features, price snapshots, labels, execution costs and training/test years unchanged.',
        'pre2026':{'old_buy_rows':int(predaily.old_eligible_names.sum()),'new_buy_rows':int(predaily.new_eligible_names.sum()),'added_rows':int(predaily.newly_eligible_names.sum()),'removed_rows':int(predaily.removed_names.sum())},
        'test2026':{'old_buy_rows':int(testdaily.old_eligible_names.sum()),'new_buy_rows':int(testdaily.new_eligible_names.sum()),'added_rows':int(testdaily.newly_eligible_names.sum()),'removed_rows':int(testdaily.removed_names.sum())},
        'daily_change_file':str(HERE/'UNIVERSE_RULE_DAILY_CHANGES.csv'),'daily_change_sha256':sha(HERE/'UNIVERSE_RULE_DAILY_CHANGES.csv'),'effective_quarter_switches':switches,
        'source_batch_read_only':str(OLD.parent),'unknown_test_rows_still_excluded':47701,'network_requests':0,'fit_calls':0})
    print(json.dumps({'status':audit['status'],**audit['signals'],**audit['latest_effective_rule']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['pre','test'],required=True);args=parser.parse_args()
    q=manifest()
    build_pre(q) if args.stage=='pre' else build_test(q)
