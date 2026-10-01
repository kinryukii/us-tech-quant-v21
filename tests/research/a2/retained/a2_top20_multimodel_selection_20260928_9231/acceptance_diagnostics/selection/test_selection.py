import numpy as np
import pandas as pd
import pytest
import run_selection as s


def test_negative_scores_still_select_fixed_top20_and_ties_use_ticker():
    names=np.array([f'T{i:02}' for i in range(25)])[::-1]
    rank,top,ties=s.ranking(np.full(25,-.25),names)
    assert top.sum()==20 and (ties==25).all()
    assert names[rank==1][0]=='T00'
    assert set(names[top])=={f'T{i:02}' for i in range(20)}


def test_known_event_conflict_is_missing_without_removing_candidate():
    cal=pd.to_datetime(['2026-02-25','2026-02-26','2026-02-27','2026-03-02'])
    p=pd.DataFrame([dict(signal_date=cal[i],ticker=t,new_buy_eligible=True,**{f:.01 for f in s.vm.FEATURES})
                    for i in [0,1] for t in ['GLW','AAA']])
    px=pd.DataFrame([dict(trade_date=d,ticker=t,open=100.,close=100.,price_quality_warning=False) for d in cal for t in ['GLW','AAA']])
    result=s.label_panel(p,px,cal,2026)
    assert len(result)==4 and result.ranking_eligible.all()
    glw=result[result.ticker.eq('GLW')]
    assert glw.label_status.str.contains('KNOWN_EVENT_CONFLICT').all()
    assert glw.forward_return.isna().all() and glw.raw_forward_return.eq(0).all()
    assert result[result.signal_date.eq(cal[1])].input_conflict_day.all()
    assert result[result.ticker.eq('AAA')].label_available.all()


def test_missing_endpoint_never_becomes_zero_or_filters_ranking_pool():
    cal=pd.to_datetime(['2025-01-02','2025-01-03','2025-01-06'])
    p=pd.DataFrame([dict(signal_date=cal[0],ticker='X',new_buy_eligible=True,**{f:.01 for f in s.vm.FEATURES})])
    px=pd.DataFrame([dict(trade_date=cal[1],ticker='X',open=100.,close=100.)])
    result=s.label_panel(p,px,cal,2025)
    assert result.ranking_eligible.iloc[0]
    assert pd.isna(result.forward_return.iloc[0])
    assert 'MISSING_OR_INVALID_EXIT_OPEN' in result.label_status.iloc[0]


def test_independent_simple_period_cost_and_incomplete_labels():
    day=pd.DataFrame({'signal_date':pd.to_datetime(['2025-01-02']*3),'forward_return':[.1,.2,.3],
                      'input_conflict_day':[False]*3})
    score=np.array([3.,2.,1.]);rank=np.array([1.,2.,3.]);top=np.array([True,True,False]);ties=np.ones(3,int)
    out=s.daily_metric(day,'joint_hgb',score,rank,top,ties)
    assert out['main_simple_gross']==pytest.approx(.0475*.3)
    assert out['main_simple_net']==pytest.approx(.0475*.3-.0475*2*.002)
    day.loc[0,'forward_return']=np.nan
    out=s.daily_metric(day,'joint_hgb',score,rank,top,ties)
    assert np.isnan(out['main_simple_net']) and np.isnan(out['simple_net_if_selected_labels_complete'])
    assert out['observable_selected_gross_contribution']==pytest.approx(.0475*.2)
