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


def friction(bps):
    return {"kind": "FIXED_ADVERSE_OPEN_SLIPPAGE", "scenario_id": f"synthetic_{bps}",
            "one_way_bps": bps, "fee_bps": 0., "benchmark": "NEXT_RAW_OPEN",
            "authority": "HYPOTHETICAL_RESEARCH_SCENARIO"}


def action_overlay(mu, *, bps, mode, gross="fixed"):
    packet = {"mu": np.asarray([mu], float), "sigma": np.array([0.]),
              "lineage": np.array(["SYNTHETIC"])}
    return StatefulOverlay([{"candidate_id": "case", "value_model": "synthetic",
        "action": "stateful", "gross": gross, "control": "none", "risk": "diag",
        "action_cost_mode": mode, "execution_friction": friction(bps)}],
        {"synthetic": packet}, np.array([[False, True]]), np.ones((1, 2), bool),
        np.zeros((1, 2)))


def replacement_context():
    ctx = context()
    ctx.max_positions = 1
    ctx.current_units = np.array([[10., 0.]])
    ctx.current_weights = np.array([[.8, 0.]])
    return ctx


def test_friction_zero_aware_and_blind_preserve_same_original_decision():
    ctx = replacement_context()
    blind = action_overlay([.003, .0045], bps=0, mode="blind")(0, ctx)
    aware = action_overlay([.003, .0045], bps=0, mode="aware")(0, ctx)
    assert np.array_equal(blind.weights, aware.weights)
    assert np.array_equal(blind.explicit_mask, aware.explicit_mask)
    assert blind.explicit_mask[0, 0] and blind.weights[0, 1] > 0


def test_friction_two_legs_suppress_replacement_without_state_or_forecast_mutation():
    ctx = replacement_context()
    original_units = ctx.current_units.copy()
    blind_model = action_overlay([.003, .0045], bps=10, mode="blind")
    aware_model = action_overlay([.003, .0045], bps=10, mode="aware")
    original_forecast = aware_model.values["synthetic"]["mu"].copy()
    blind, aware = blind_model(0, ctx), aware_model(0, ctx)
    assert blind.explicit_mask[0, 0] and blind.weights[0, 1] > 0
    assert not aware.explicit_mask.any()  # KEEP means exact actual units.
    assert np.array_equal(ctx.current_units, original_units)
    assert np.array_equal(aware_model.values["synthetic"]["mu"], original_forecast)


def test_friction_missing_forecast_still_holds_exact_units():
    ctx = replacement_context()
    decision = action_overlay([np.nan, .02], bps=10, mode="aware")(0, ctx)
    assert not decision.explicit_mask[0, 0]
    assert not decision.explicit_mask[0, 1]  # Missing held forecast reserves the only slot.


def test_friction_gross_consumes_original_forecast_not_avoid_exit_bonus():
    from scripts.research.a2.training.stateful_account import exposure_budget
    ctx = context(held=False)
    model = action_overlay([.02, .02], bps=10, mode="aware", gross="dynamic")
    model.vol5[:] = .1
    decision = model(0, ctx)
    expected = exposure_budget("dynamic", np.array([1.]), np.array([.02]), 0.,
                               np.array([[.01]]))
    assert np.isclose(decision.weights.sum(), expected)
    assert model.audit[0]["gross_uses_action_friction_bonus"] is False


def test_friction_quote_unequal_notional_partial_changes_and_keep_are_separate():
    from scripts.research.a2.training.stateful_account import quote_transition_cost
    quote = quote_transition_cost(np.array([.4, .2, .1]), np.array([0., .5, 0.]),
                                  np.array([True, True, False]), 3000., friction(10))
    assert np.isclose(quote["planned_sell_notional_usd"], 1200.)
    assert np.isclose(quote["planned_buy_notional_usd"], 900.)
    assert np.isclose(quote["planned_slippage_usd"], 2.1)
    assert quote["planned_fee_usd"] == 0 and quote["future_open_used"] is False
    kept = quote_transition_cost(np.array([.4]), np.array([0.]), np.array([False]),
                                 3000., friction(20))
    assert kept["planned_friction_usd"] == 0


def test_friction_signal_time_function_has_no_future_price_input_and_invalid_rates_fail():
    import pytest
    from scripts.research.a2.training.stateful_account import action_friction_overlay
    original = np.array([.003, .0045, np.nan])
    held, entrants = np.array([True, False, False]), np.array([False, True, False])
    adjusted = action_friction_overlay(original, held, entrants, friction(10), mode="aware")
    assert np.allclose(adjusted[:2], [.004, .0035])
    assert np.isnan(adjusted[2]) and np.allclose(original[:2], [.003, .0045])
    for invalid in (-1, np.nan, np.inf, True):
        with pytest.raises(ValueError):
            action_friction_overlay(original, held, entrants, friction(invalid), mode="aware")
    with pytest.raises(ValueError):
        action_friction_overlay(original, held, entrants, None, mode="aware")


def test_friction_missing_rate_never_silently_becomes_zero_and_quote_time_is_scoped():
    import pytest
    from scripts.research.a2.training.stateful_account import action_friction_overlay, quote_transition_cost
    missing = friction(10)
    del missing["one_way_bps"]
    with pytest.raises(ValueError):
        action_friction_overlay(np.array([.01]), np.array([False]), np.array([True]),
                                missing, mode="aware")
    quote = quote_transition_cost(np.array([0.]), np.array([.1]), np.array([True]),
                                  3000., friction(10))
    assert quote["input_time_qualification_verified"] is False
    assert quote["signal_mark_authority"] == "CALLER_SIGNAL_STATE_NOT_VERIFIED_BY_THIS_QUOTER"
