"""Restore every frozen model and exercise meaningful account constraints."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from adapters import PolicyV2
from evaluate import NAMES, DATA, clocks
from ensemble import EnsemblePolicy


@pytest.fixture(scope='module')
def day():
    frame=pd.read_parquet(DATA/'pre2026_joint_context.parquet')
    return frame.loc[frame.signal_date.eq('2025-01-02')].head(12).copy()


def context(slots=2,budget=.075):
    return SimpleNamespace(current_weights={'RESERVED':.2},current_units={'RESERVED':1.},
        cash_weight=.8,available_slots=slots,available_weight=budget,
        buy_restricted_tickers=(),reserved_tickers=('RESERVED',),reserved_weights={'RESERVED':.2})


@pytest.mark.parametrize('name',NAMES)
@pytest.mark.parametrize('stage',['validation','final'])
def test_restored_models_respect_reserved_holdings_and_explicit_exits(day,name,stage):
    actor=EnsemblePolicy(name,stage) if name.startswith('ensemble_') else PolicyV2(name,stage)
    result=actor(day,context())
    assert set(result.model_decisions)==set(day.ticker)
    w=np.array(list(result.model_decisions.values()))
    assert np.isfinite(w).all() and (w>=0).all() and (w<=.1+1e-10).all()
    assert (w>1e-8).sum()<=2 and w.sum()<=.07500001
    empty=actor(day,context(0,0.))
    assert sum(empty.model_decisions.values())==0.


def test_early_close_clock():
    values=clocks(pd.DatetimeIndex(['2025-07-03','2025-12-24','2026-07-02']))
    assert values[pd.Timestamp('2025-07-03')]==pd.Timestamp('2025-07-03T17:00:00Z')
    assert values[pd.Timestamp('2025-12-24')]==pd.Timestamp('2025-12-24T18:00:00Z')
    assert values[pd.Timestamp('2026-07-02')]==pd.Timestamp('2026-07-02T20:00:00Z')
