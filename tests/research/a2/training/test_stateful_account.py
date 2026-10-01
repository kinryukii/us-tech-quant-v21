"""Only synthetic policy contexts; no market, model or economic-artifact reads."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scripts.research.a2.training.stateful_account import StatefulOverlay


def context(*, held=True):
    units=np.array([[10.,10.]]) if held else np.zeros((1,2))
    weights=np.array([[.4,.4]]) if held else np.zeros((1,2))
    return SimpleNamespace(path_ids=("case",),signal_date=pd.Timestamp("2023-01-03"),
        tickers=("AAA","BBB"),max_positions=20,current_units=units,current_weights=weights,
        cash=np.array([600. if held else 3000.]),nav=np.array([3000.]),
        available_budget=np.array([1.]),decision_mask=np.ones((1,2),bool),
        buy_allowed=np.ones((1,2),bool),holding_age=np.ones((1,2),int),
        entry_date=np.full((1,2),np.datetime64("2023-01-02")),
        entry_price=np.ones((1,2)),entry_execution_open=np.ones((1,2)))


def overlay(mu,risk_provider=None):
    packet={"mu":np.asarray([mu],float),"sigma":np.array([.01]),"lineage":np.array(["SYNTHETIC"])}
    return StatefulOverlay([{"candidate_id":"case","value_model":"synthetic","action":"stateful",
        "gross":"volatility_targeting","control":"none","risk":"diag"}],
        {"synthetic":packet},np.ones((1,2),bool),np.ones((1,2),bool),
        np.full((1,2),.1),risk_provider=risk_provider)


def test_missing_forecast_held_keeps_exact_hold_under_volatility_gross():
    ctx=context();original=ctx.current_units.copy()
    decision=overlay([np.nan,.2])(0,ctx)
    assert not decision.explicit_mask[0,0]
    assert np.array_equal(ctx.current_units,original)


def test_healthy_action_hold_can_reduce_under_explicit_gross_policy():
    ctx=context();decision=overlay([.2,.2])(0,ctx)
    assert decision.explicit_mask.all()
    assert (decision.weights[0]<ctx.current_weights[0]).all()
    assert (decision.weights[0]>=0).all()


def test_empty_selected_risk_provider_is_never_called():
    def forbidden(*args):
        raise AssertionError("Empty selected set must not call a risk provider")
    ctx=context(held=False);decision=overlay([-.2,-.2],forbidden)(0,ctx)
    assert not decision.explicit_mask.any()
    assert np.array_equal(decision.weights,np.zeros((1,2)))
