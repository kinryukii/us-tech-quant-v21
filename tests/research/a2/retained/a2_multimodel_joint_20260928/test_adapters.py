"""Artifact integration tests: identical residual account constraints for every model."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from adapters import PolicyV2
from evaluate import DATA, NAMES, clocks

@pytest.fixture(scope='module')
def day():
    panel=pd.read_parquet(DATA/'pre2026_joint_context.parquet')
    return panel.loc[panel.signal_date.eq('2025-01-02')].head(12).copy()

def context(slots=2,budget=.075):
    return SimpleNamespace(current_weights={'RESERVED':.2},current_units={'RESERVED':1.},
        cash_weight=.8,available_slots=slots,available_weight=budget,
        buy_restricted_tickers=(),reserved_tickers=('RESERVED',),reserved_weights={'RESERVED':.2})

@pytest.mark.parametrize('stage',['validation','final'])
@pytest.mark.parametrize('name',NAMES)
def test_fitted_policy_respects_reserved_holdings(day,name,stage):
    actor=PolicyV2(name,stage)
    r=actor(day,context());w=np.array(list(r.model_decisions.values()))
    assert set(r.model_decisions)==set(day.ticker)
    assert np.isfinite(w).all() and (w>=0).all() and (w<=.1+1e-8).all()
    assert (w>1e-8).sum()<=2 and w.sum()<=.07500001
    r=actor(day,context(0,0.))
    assert sum(r.model_decisions.values())==0
    if name=='cash_control':assert w.sum()==0

@pytest.mark.parametrize('name',NAMES)
def test_held_only_cannot_create_new_buy(day,name):
    actor=PolicyV2(name,'final')
    restricted=day.copy();restricted['new_buy_eligible']=False
    empty=actor(restricted,context())
    assert not empty.model_decisions
    held=str(day.ticker.iloc[0]);ctx=context()
    ctx.current_weights[held]=.025;ctx.current_units[held]=1.
    r=actor(restricted,ctx)
    assert set(r.model_decisions)=={held}
    assert r.model_decisions[held]<=.025+1e-8

def test_early_close_clock():
    c=clocks(pd.DatetimeIndex(['2025-07-03','2025-12-24','2026-07-02']))
    assert c[pd.Timestamp('2025-07-03')]==pd.Timestamp('2025-07-03T17:00:00Z')
    assert c[pd.Timestamp('2025-12-24')]==pd.Timestamp('2025-12-24T18:00:00Z')
    assert c[pd.Timestamp('2026-07-02')]==pd.Timestamp('2026-07-02T20:00:00Z')
