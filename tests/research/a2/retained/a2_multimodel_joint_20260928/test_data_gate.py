import pandas as pd
import numpy as np
from data_gate import quarantine
from engine_v2 import run_replay,HoldingAwareDecision

def test_conflicted_feature_and_price_are_blocked_without_touching_raw_values():
    cal=pd.bdate_range('2026-02-25',periods=4)
    px=pd.DataFrame([dict(ticker=t,trade_date=d,open=100.,close=100.,price_quality_warning=False)
                     for d in cal for t in ['GLW','SAFE']])
    panel=pd.DataFrame([dict(ticker=t,signal_date=d,new_buy_eligible=True,avg_dollar_volume_20d=1e9)
                        for d in cal[:-1] for t in ['GLW','SAFE']])
    clean,prices,feature_evidence,price_evidence=quarantine(panel,px)
    assert len(feature_evidence)==len(price_evidence)==1
    assert not px.price_quality_warning.any()
    assert prices.price_quality_warning.sum()==1
    result=run_replay(prices,cal,clean,lambda day,ctx:HoldingAwareDecision({str(t):.1 for t in day.ticker}),
                      signal_start='2026-02-25',signal_end='2026-02-27')
    bad=result.trades.ticker.eq('GLW')&result.trades.execution_date.eq('2026-02-26')
    assert not bad.any()
    seen=[]
    def hold(day,ctx):
        if ctx.signal_date==pd.Timestamp('2026-02-26'):
            assert 'GLW' in ctx.reserved_tickers
            assert 'GLW' not in set(day.ticker)
            seen.append(True)
        return HoldingAwareDecision({str(t):.1 for t in day.ticker})
    r=run_replay(prices,cal,clean,hold,initial_cash=900000.,initial_positions={'GLW':1000.},
                 signal_start='2026-02-25',signal_end='2026-02-27')
    assert seen
    glw=r.positions.loc[r.positions.ticker.eq('GLW')&r.positions.date.eq('2026-02-26')]
    assert glw.index_units.eq(1000).all()
    assert r.daily.loc[r.daily.date.eq('2026-02-26'),'certified_nav'].isna().all()
