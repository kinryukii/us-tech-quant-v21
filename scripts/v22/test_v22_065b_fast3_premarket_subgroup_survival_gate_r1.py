import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
import v22_065b_fast3_premarket_subgroup_survival_gate_r1 as m
def test_metric_failure_conditions():
 x=pd.DataFrame({'account_return':[.01,-.02],'two':[.01,-.02]})
 assert m.metrics(x,'account_return')['profit_factor'] < 1.2
 assert m.metrics(pd.DataFrame({'account_return':[]}), 'account_return')['trade_count'] != 20
def test_no_cross_dimensions_declared():
    assert set(m.DIM) == {'direction','instrument','signal_time','consensus','strength','volatility','gap_regime'}

def frame():
    rows=[]
    for period,n in zip(m.PER,[20,40]):
        for i in range(n): rows.append({'direction':'LONG','study_period':period,'account_return':.002 if i%3 else -.001,'entry_price':100.,'exit_price':100.3 if i%3 else 99.9,'position_weight':.2,'calendar_year':2023+i%3})
    return pd.DataFrame(rows)

def failures(x): return m.gate_row('direction','LONG',x)[0]['failed_gate_names']
def test_all_required_gate_failures_are_rejected():
    x=frame(); assert 'TRADE_COUNT' not in failures(x)
    y=x.iloc[1:].copy(); assert 'TRADE_COUNT' in failures(y)
    y=frame(); y.loc[y.study_period==m.PER[1],'account_return']=-.001; assert 'MEAN_RETURN' in failures(y)
    y=frame(); y.loc[y.study_period==m.PER[0],'account_return']=-.001; assert 'MEDIAN_RETURN' in failures(y)
    y=frame(); y.loc[y.study_period==m.PER[0],'account_return']=[.001]*10+[-.002]*10; assert 'BASELINE_PF' in failures(y)
    y=frame(); y.loc[y.study_period==m.PER[0],'exit_price']=99.; assert 'COST_2X_PF' in failures(y)
    y=frame(); y.loc[y.index[0],'account_return']=10.; assert 'TOP1_CONCENTRATION' in failures(y)
    y=frame(); y.loc[y.study_period==m.PER[0],'account_return']=float('nan'); assert 'MISSING_REQUIRED_METRIC' in failures(y)
