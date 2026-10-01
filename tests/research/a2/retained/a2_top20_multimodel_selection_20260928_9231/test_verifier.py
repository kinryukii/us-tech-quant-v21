"""Exercise independent book reconstruction on a complete synthetic round trip."""
import json
import numpy as np
import pandas as pd
from engine_v2 import run_replay,HoldingAwareDecision
from evaluate import summarize,LEDGERS,write
from verify_and_report import inspect


def test_trade_reconstruction_and_drifting_preserved_units(tmp_path):
    cal=pd.bdate_range('2025-06-02',periods=5)
    prices=pd.DataFrame([dict(ticker=t,trade_date=d,open=p,close=p,price_quality_warning=False)
        for i,d in enumerate(cal) for t,p in [('A',100. if i<2 else 300.),('B',100.)]])
    # A is bought, then absent from the next model input while its price triples.
    features=pd.DataFrame([dict(signal_date=cal[0],ticker='A',new_buy_eligible=True,avg_dollar_volume_20d=1e9),
                           dict(signal_date=cal[2],ticker='B',new_buy_eligible=True,avg_dollar_volume_20d=1e9)])
    def policy(day,ctx):return HoldingAwareDecision({str(t):.1 for t in day.ticker})
    result=run_replay(prices,cal,features,policy,candidate='book',capacity_fraction=.01,
                      signal_start=cal[0],signal_end=cal[2])
    folder=tmp_path/'evaluation_2025/cost_10/book';folder.mkdir(parents=True)
    for key in LEDGERS:getattr(result,key).to_parquet(folder/f'{key}.parquet',index=False)
    write(folder/'DONE.json',summarize(result,'book',2025,10))
    import verify_and_report
    original=verify_and_report.ROOT
    try:
        verify_and_report.ROOT=tmp_path
        row=inspect(folder)
    finally:verify_and_report.ROOT=original
    assert row['status']=='PASS'
    assert row['checks']['units_rebuilt_from_trades_error']<1e-8
    held=result.target_decisions.query('order_type == "HOLD_UNITS"')
    assert held.adapted_target_weight.max()>.1
