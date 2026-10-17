"""Independent checks of materialized dataset timing, eligibility and one-step labels."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from build_joint_inputs import latest_effective_mask

HERE=Path(__file__).resolve().parent
SAVED=HERE.parent.parent/'a2_complete_suite_20260927'/'data'

def input_path(name):
    local=HERE/name
    return local if local.exists() else SAVED/name

def main():
    joint=pd.read_parquet(input_path('pre2026_joint_context.parquet'))
    buy=pd.read_parquet(HERE/'pre2026_joint.parquet')
    test=pd.read_parquet(HERE/'test_features.parquet')
    context=pd.read_parquet(input_path('test_features_context.parquet'))
    price=pd.read_parquet(input_path('test_prices.parquet'))
    cal=pd.read_parquet(input_path('calendar.parquet'))
    features=json.loads(input_path('JOINT_DATA_AUDIT.json').read_text())['features']
    assert len(joint)==313668 and len(context)==61963
    for frame in [joint,buy,test,context]:
        assert not frame.duplicated(['signal_date','ticker']).any()
        assert np.isfinite(frame[features].to_numpy(float)).all()
    assert buy.new_buy_eligible.all() and test.new_buy_eligible.all()
    pre_timing=joint[['active_13f_quarter','latest_filing_date','quarter_effective_date']].drop_duplicates().rename(columns={'active_13f_quarter':'quarter'})
    test_timing=pd.read_csv(input_path('quarter_timing.csv'),parse_dates=['latest_filing_date','quarter_effective_date'])
    assert latest_effective_mask(buy,pre_timing,'active_13f_quarter').all()
    assert latest_effective_mask(test,test_timing,'quarter').all()
    assert len(buy)==len(joint) and len(test)==len(context)
    assert buy[['signal_date','ticker']].reset_index(drop=True).equals(joint[['signal_date','ticker']].reset_index(drop=True))
    assert test[['signal_date','ticker']].reset_index(drop=True).equals(context[['signal_date','ticker']].reset_index(drop=True))
    assert test.signal_date.ge(test.quarter_effective_date).all() and test.signal_date.gt(test.latest_filing_date).all()
    assert not test.duplicated(['cusip','title_of_class','quarter','signal_date']).any()
    assert test.final_input_gate.str.startswith('INPUT_VERIFIED').all()
    assert joint.signal_date.lt('2026-01-01').all()
    valid=joint.loc[joint.label_available]
    assert valid.label_end_date.lt('2026-01-01').all()
    assert valid.execution_date.gt(valid.signal_date).all()
    assert valid.label_end_date.gt(valid.execution_date).all()
    delta=np.abs(valid.y_next_open-(valid.following_open/valid.next_open-1))
    assert delta.max()==0
    assert cal.trade_date.is_monotonic_increasing and not cal.trade_date.duplicated().any()
    assert cal.trade_date.max()==pd.Timestamp('2026-09-24')
    assert test.signal_date.max()<=pd.Timestamp('2026-09-22')
    assert price.trade_date.max()==pd.Timestamp('2026-09-24')
    assert not price.duplicated(['ticker','trade_date']).any()
    assert price[['open','close']].gt(0).all().all()
    # Verify the chosen next opens against original source prices independently.
    original=pd.read_parquet(json.loads(input_path('JOINT_DATA_AUDIT.json').read_text())['pre2026_price_path'])
    opens=original.set_index(['ticker','trade_date']).open
    sample=valid.iloc[::max(1,len(valid)//1000)]
    actual_next=opens.reindex(pd.MultiIndex.from_frame(sample[['ticker','execution_date']])).to_numpy()
    actual_end=opens.reindex(pd.MultiIndex.from_frame(sample[['ticker','label_end_date']])).to_numpy()
    assert np.array_equal(actual_next,sample.next_open.to_numpy())
    assert np.array_equal(actual_end,sample.following_open.to_numpy())
    # Missing prospective prices stay visible; they never alter signal rows.
    dates=pd.DatetimeIndex(cal.trade_date)
    follow=pd.Series(dates[1:],index=dates[:-1]);later=pd.Series(dates[2:],index=dates[:-2])
    check=test[['signal_date','ticker']].copy()
    check['execution_date']=check.signal_date.map(follow)
    check['valuation_date']=check.signal_date.map(later)
    piv=price.set_index(['ticker','trade_date'])
    for c in ['execution_date','valuation_date']:
        idx=pd.MultiIndex.from_frame(check[['ticker',c]])
        check[c+'_missing']=piv.open.reindex(idx).isna().to_numpy()
        check[c+'_warning']=piv.price_quality_warning.reindex(idx).fillna(True).to_numpy()
    qqq=price.loc[price.ticker.eq('QQQ')].sort_values('trade_date')
    output={'status':'PASS','checks':'keys, finite features, latest publicly effective quarter, maturity, exact one-step-return arithmetic, 1000 source-price samples, complete test calendar',
        'pre2026_context_rows':len(joint),'pre2026_buy_rows':len(buy),'test_verified_context_rows':len(context),'test_buy_rows':len(test),
        'test_buy_dates':test.signal_date.nunique(),'test_context_dates':context.signal_date.nunique(),'test_calendar_dates':int(cal.is_test.sum()),
        'one_step_return_max_arithmetic_error':float(delta.max()),'sample_source_price_rows_checked':len(sample),
        'prospective_price_diagnostics':{c:int(check[c].sum()) for c in check.columns if c.endswith('_missing') or c.endswith('_warning')},
        'qqq_max_abs_adjacent_open_return':float(qqq.open.pct_change().abs().max()),
        'buy_date_counts_by_quarter':test.groupby('quarter').signal_date.nunique().to_dict(),
        'price_warning_rows':int(price.price_quality_warning.sum()),'not_proven':['full original candidate pool completeness','absence of retrospective availability selection bias','true shareholder total return']}
    (HERE/'INPUT_VALIDATION.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))

if __name__=='__main__':main()
