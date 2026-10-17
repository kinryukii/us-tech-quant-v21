"""Independent publication/effectiveness and unchanged-market-data tests."""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
OLD=HERE.parent.parent/'a2_complete_suite_20260927/data'
SOURCE=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')
STRICT=HERE.parent.parent/'a2_strict_method_retrain_20260926'
OTHER=HERE.parent.parent/'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    # Independent original metadata reconstruction; do not trust new eligibility flags.
    m=pd.read_parquet(SOURCE/'universe/quarterly_universe_manifest.parquet')
    q2source=pd.read_csv(OTHER/'Q2_ORIGINAL24_SOURCE_MAP.csv')
    initial=q2source.loc[~q2source.source_scope.str.contains('RESTAT')]
    assert len(initial)==24
    lastq2=pd.to_datetime(initial.accepted_at,utc=True).max().tz_convert(None).normalize()
    q2bind=read(STRICT/'test2026_stage/fixed_window_binding/Q2_SOURCE_BINDING.json')
    m=pd.concat([m,pd.DataFrame([{'quarter':'2026Q2','holdings_as_of_date':pd.Timestamp('2026-06-30'),
        'latest_actual_filing_timestamp':lastq2,'effective_date':pd.Timestamp(q2bind['initial_effective_date'])}])],ignore_index=True)
    for c in ['holdings_as_of_date','latest_actual_filing_timestamp','effective_date']:m[c]=pd.to_datetime(m[c])
    m=m.sort_values('effective_date').reset_index(drop=True)
    preprice=Path(read(HERE/'JOINT_DATA_AUDIT.json')['pre2026_price_path'])
    pp=pd.read_parquet(preprice,columns=['ticker','trade_date'])
    calpre=pd.to_datetime(pp.loc[pp.ticker.eq('QQQ'),'trade_date'])
    caltest=pd.read_parquet(HERE/'calendar.parquet').trade_date
    calendar=pd.DatetimeIndex(pd.concat([calpre,caltest])).unique().sort_values()
    lagchecks=[]
    for row in m.itertuples(index=False):
        after=calendar[calendar>row.latest_actual_filing_timestamp]
        assert len(after)>=5 and after[4]==row.effective_date,(row.quarter,row.effective_date,after[:5])
        lagchecks.append({'quarter':row.quarter,'latest_filing_date':str(row.latest_actual_filing_timestamp.date()),'effective_date':str(row.effective_date.date()),'fifth_next_session_match':True})
    def active(dates):
        dates=pd.DatetimeIndex(dates)
        indices=np.searchsorted(m.effective_date.to_numpy(),dates.to_numpy(),side='right')-1
        assert (indices>=0).all()
        return m.iloc[indices].quarter.to_numpy()
    boundaries=[]
    for i in range(1,len(m)):
        effective=m.effective_date.iloc[i]
        if not pd.Timestamp('2023-01-01')<=effective<=pd.Timestamp('2026-09-24'):continue
        pos=calendar.get_loc(effective);before=calendar[pos-1];after=calendar[pos+1]
        got=active([before,effective,after]);want=[m.quarter.iloc[i-1],m.quarter.iloc[i],m.quarter.iloc[i]]
        assert list(got)==want
        boundaries.append({'previous_session':str(before.date()),'before_quarter':got[0],'effective_date':str(effective.date()),'effective_quarter':got[1],'following_session':str(after.date())})
    examples={'2026-01-02':'2025Q3','2026-02-24':'2025Q3','2026-02-25':'2025Q4','2026-04-01':'2025Q4',
        '2026-05-21':'2025Q4','2026-05-22':'2026Q1','2026-07-01':'2026Q1','2026-08-20':'2026Q1','2026-08-21':'2026Q2'}
    assert dict(zip(examples,active(list(examples))))==examples
    features=read(HERE/'JOINT_DATA_AUDIT.json')['features']
    rows={}
    for scope,filename,qcol in [('pre2026','pre2026_joint_context.parquet','active_13f_quarter'),('test2026','test_features_context.parquet','quarter')]:
        old=pd.read_parquet(OLD/filename).sort_values(['signal_date','ticker']).reset_index(drop=True)
        new=pd.read_parquet(HERE/filename).sort_values(['signal_date','ticker']).reset_index(drop=True)
        assert len(old)==len(new) and not new.duplicated(['signal_date','ticker']).any()
        assert old[['signal_date','ticker']].equals(new[['signal_date','ticker']])
        expected=active(new.signal_date)
        assert np.array_equal(new[qcol].to_numpy(),expected)
        assert np.array_equal(new.asof_quarter.to_numpy(),expected)
        assert new.new_buy_eligible.all()
        assert new.signal_date.ge(new.quarter_effective_date).all() and new.signal_date.gt(new.latest_filing_date).all()
        assert 'required_report_quarter' not in new
        assert np.array_equal(old[features].to_numpy(),new[features].to_numpy())
        mainfile=HERE/('pre2026_joint.parquet' if scope=='pre2026' else 'test_features.parquet')
        assert sha(mainfile)==sha(HERE/filename)
        if scope=='pre2026':
            for c in ['close','next_open','following_open','y_next_open','target']:
                assert np.array_equal(old[c].to_numpy(),new[c].to_numpy(),equal_nan=True)
            assert new.signal_date.lt('2026-01-01').all()
            assert new.loc[new.label_available,'label_end_date'].lt('2026-01-01').all()
            assert new.loc[new.target_context_available,'target_end_date'].lt('2026-01-01').all()
            members=pd.read_parquet(SOURCE/'universe/daily_eligible_universe_membership.parquet',columns=['signal_date','ticker','active_13f_quarter','cusip'])
            joined=new[['signal_date','ticker','active_13f_quarter','cusip']].merge(members,on=['signal_date','ticker'],validate='one_to_one',suffixes=('_new','_source'))
            assert len(joined)==len(new)
            assert joined.active_13f_quarter_new.eq(joined.active_13f_quarter_source).all() and joined.cusip_new.eq(joined.cusip_source).all()
        else:
            gate=pd.read_parquet(STRICT/'test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
            keys=['signal_date','quarter','ticker','cusip','title_of_class']
            verified=gate.loc[gate.final_input_gate.str.startswith('INPUT_VERIFIED'),keys]
            assert len(new)==len(verified) and len(new.merge(verified,on=keys,validate='one_to_one'))==len(new)
        rows[scope]={'rows':len(new),'dates':new.signal_date.nunique(),'old_eligible_rows':int(old.new_buy_eligible.sum()),'new_eligible_rows':int(new.new_buy_eligible.sum()),'added_rows':int((~old.new_buy_eligible).sum()),'removed_rows':0,'unchanged_features':True}
    unchanged={}
    for name in ['test_prices.parquet','calendar.parquet','consumed_price_events.parquet','PRICE_SOURCE_RECEIPTS.json','PRICE_BUILD_FAILURES.json']:
        assert sha(OLD/name)==sha(HERE/name);unchanged[name]=sha(HERE/name)
    changes=pd.read_csv(HERE/'UNIVERSE_RULE_DAILY_CHANGES.csv')
    assert changes.removed_names.eq(0).all()
    for scope in rows:
        c=changes.loc[changes.scope.eq(scope)]
        assert int(c.newly_eligible_names.sum())==rows[scope]['added_rows']
        assert c.new_eligible_names.gt(0).all()
    result={'status':'PASS','rule':'LATEST_PUBLISHED_AND_EFFECTIVE_13F_QUARTER','independent_method':'searchsorted on original effective-date manifest, independent of builder merge_asof',
        'scope_counts':rows,'publication_lag_fifth_session_checks':len(lagchecks),'quarter_switch_boundary_tests':len(boundaries),'quarter_switch_checks':boundaries,'calendar_quarter_rollover_checks':examples,
        'publication_lag_checks':lagchecks,'unchanged_source_copy_sha256':unchanged,'all_training_labels_before':'2026-01-01','future_quarter_backfill_rows':0,'unknown_test_rows_promoted':0,'network_requests':0,'model_fit_calls':0,
        'limitations_unchanged':['retrospective verified test subset, not full 13F pool','price-index return, not shareholder total return','price quality warnings and missing values still require execution-time gates']}
    (HERE/'INPUT_VALIDATION.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','scope_counts','publication_lag_fifth_session_checks','quarter_switch_boundary_tests','future_quarter_backfill_rows']},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
