import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from engine_cached import run_replay,PreparedInputs
from engine_v2 import run_replay as original,HoldingAwareDecision

def inputs():
    cal=pd.bdate_range('2025-01-02',periods=8)
    rows=[dict(ticker=t,trade_date=d,open=10+i+(.3 if t=='BBB' else 0),close=10.2+i,
       price_quality_warning=(t=='AAA' and i==3)) for i,d in enumerate(cal) for t in ['AAA','BBB','CCC'] if not (t=='BBB' and i==4)]
    f=pd.DataFrame([dict(signal_date=d,ticker=t,new_buy_eligible=True,avg_dollar_volume_20d=5e6)
       for i,d in enumerate(cal[:-2]) for t in ['AAA','BBB','CCC'] if not (i==2 and t=='AAA')])
    return pd.DataFrame(rows),cal,f

def test_prepared_input_changes_no_account_semantics():
    px,cal,f=inputs();prepared=PreparedInputs(px,cal,f)
    def policy(day,ctx):
        names=list(day.ticker);chosen=names[:ctx.available_slots]
        decisions={t:0. for t in names if t in ctx.current_units}
        decisions.update({t:min(.1,ctx.available_weight/max(1,len(chosen))) for t in chosen})
        return HoldingAwareDecision(model_decisions=decisions,raw_model_outputs={'same':True})
    kwargs=dict(candidate='same',capacity_fraction=.01,signal_end=f.signal_date.max())
    a=original(px,cal,f,policy,**kwargs);b=run_replay(px,cal,f,policy,prepared_inputs=prepared,**kwargs)
    for key in ['daily','positions','trades','target_decisions','execution_results','diagnostics','signal_contexts','raw_model_outputs','operational_actions','valuation_intervals']:
        assert_frame_equal(getattr(a,key),getattr(b,key))
    assert a.metadata==b.metadata
    c=run_replay(px,cal,f,policy,prepared_inputs=prepared,**kwargs)
    assert_frame_equal(c.daily,b.daily)

def test_cache_cannot_be_silently_rebound():
    import pytest
    px,cal,f=inputs();p=PreparedInputs(px,cal,f)
    with pytest.raises(ValueError,match='IDENTITY_MISMATCH'):
        run_replay(px.copy(),cal,f,lambda day,ctx:HoldingAwareDecision(),prepared_inputs=p)
