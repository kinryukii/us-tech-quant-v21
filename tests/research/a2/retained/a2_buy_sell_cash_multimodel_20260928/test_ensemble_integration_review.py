"""Independent behavioral checks for shared-account ensemble integration."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

from ensemble_policy import EnsemblePolicy, MEMBERS, risk_scale
from engine_v2 import HoldingAwareDecision, run_replay


class Opinion:
    def __init__(self, mapping):
        self.mapping = mapping
        self.seen = []

    def __call__(self, day, ctx):
        self.seen.append(ctx)
        return HoldingAwareDecision({t:w for t,w in self.mapping.items() if t in set(day.ticker)})


class DiagonalRisk:
    def __init__(self):
        self.requested_names = []

    def covariance_for(self, names):
        self.requested_names.append(list(names))
        return np.eye(len(names)) * .04


def policy(mappings, risk=None):
    actor = EnsemblePolicy.__new__(EnsemblePolicy)
    actor.name = "ensemble_consensus_risk" if risk else "ensemble_equal"
    actor.stage = "validation"
    actor.members = [Opinion(mapping) for mapping in mappings]
    actor.coefficients = np.ones(len(MEMBERS))/len(MEMBERS)
    actor.risk = risk
    return actor


def context(weights=None):
    weights = weights or {}
    return SimpleNamespace(current_weights=weights, current_units={t:1. for t in weights},
        cash_weight=1-sum(weights.values()), reserved_tickers=(), reserved_weights={},
        available_slots=20, available_weight=.95, planned_operational_exits={})


def test_members_receive_identical_current_account_and_opinions_are_fused():
    actor = policy([{"A":.1,"B":0.}]*3 + [{"A":0.,"B":.1}]*3)
    ctx = context({"A":.03})
    result = actor(pd.DataFrame({"ticker":["A","B"]}), ctx)
    assert all(member.seen == [ctx] for member in actor.members)
    assert result.model_decisions == pytest.approx({"A":.05,"B":.05})
    assert result.raw_model_outputs["A"]["member_targets"] == [.1,.1,.1,0.,0.,0.]


def test_locked_alone_over_limit_is_zero_even_if_active_can_hedge():
    # The contract explicitly disallows new active exposure when locked risk
    # already exceeds the cap; a negative covariance cannot bypass that rule.
    covariance = np.array([[.04,-.04],[-.04,.04]])
    assert risk_scale([.1],[.1],covariance) == 0.


def test_member_omission_of_held_name_enters_risk_reservation():
    risk = DiagonalRisk()
    actor = policy([{"OLD":.02,"NEW":.1}]*5 + [{"NEW":.1}], risk)
    result = actor(pd.DataFrame({"ticker":["OLD","NEW"]}), context({"OLD":.2}))
    assert "OLD" not in result.model_decisions
    assert "OLD" in risk.requested_names[-1]
    assert result.model_decisions["NEW"] == 0.


def test_missing_opinion_keeps_held_units_in_actual_ledger():
    calendar = pd.date_range("2025-01-02", periods=3, freq="B")
    prices = pd.DataFrame([dict(ticker=t,trade_date=d,open=100.,close=100.)
        for d in calendar for t in ("OLD","NEW")])
    features = pd.DataFrame([dict(ticker=t,signal_date=calendar[0],new_buy_eligible=True,
        avg_dollar_volume_20d=1e9) for t in ("OLD","NEW")])
    actor = policy([{"OLD":0.,"NEW":.1}]*5 + [{"NEW":.1}])
    result = run_replay(prices,calendar,features,actor,initial_cash=90_000.,
        initial_positions={"OLD":100.},signal_start=calendar[0],signal_end=calendar[0],
        cost_bps=10,capacity_fraction=.01)
    old = result.positions[result.positions.ticker.eq("OLD")]
    np.testing.assert_allclose(old.index_units.to_numpy(float), 100.)
    decision = result.target_decisions[result.target_decisions.ticker.eq("OLD")].iloc[0]
    assert decision.decision_semantic == "MODEL_NO_DECISION"
    assert decision.order_type == "HOLD_UNITS"
    assert not result.trades.ticker.eq("OLD").any()


def test_future_open_change_cannot_change_ensemble_signal():
    calendar = pd.date_range("2025-01-02",periods=3,freq="B")
    features = pd.DataFrame([dict(ticker="A",signal_date=calendar[0],new_buy_eligible=True,
                                  avg_dollar_volume_20d=1e9)])
    outputs = []
    for future_open in (100.,500.):
        prices = pd.DataFrame([dict(ticker="A",trade_date=d,open=future_open if i else 100.,close=100.)
                               for i,d in enumerate(calendar)])
        result = run_replay(prices,calendar,features,policy([{"A":.1}]*6),
            initial_cash=100_000.,signal_start=calendar[0],signal_end=calendar[0],cost_bps=10)
        outputs.append(result.raw_model_outputs.iloc[0].model_decisions_json)
    assert outputs[0] == outputs[1]


def test_meta_h1_selection_ignores_h2_returns_and_order_matches_policy():
    from ensemble_train import METHODS, complete_case_returns
    assert METHODS == MEMBERS
    dates = pd.to_datetime(["2025-01-02","2025-01-03","2025-01-06","2025-06-30","2025-07-01"])
    nav = np.array([100.,101.,102.,103.,104.])
    frame = pd.DataFrame(dict(date=dates,certified_nav=nav,valuation_status="certified",
                               net_return=np.r_[np.nan,nav[1:]/nav[:-1]-1]))
    base, _, audit = complete_case_returns({name:frame for name in METHODS}, "2025-07-01")
    changed = frame.copy()
    changed.loc[4,"certified_nav"] = 1e9
    changed.loc[4,"net_return"] = 1e9/103-1
    after, _, _ = complete_case_returns({name:changed for name in METHODS}, "2025-07-01")
    pd.testing.assert_frame_equal(base,after)
    assert audit["last_return"] == "2025-06-30"


def test_meta_excludes_uncertified_date_and_following_return_for_every_member():
    from ensemble_train import METHODS, complete_case_returns
    dates = pd.date_range("2025-01-02", periods=6, freq="B")
    nav = np.arange(100.,106.)
    frame = pd.DataFrame(dict(date=dates,certified_nav=nav,valuation_status="certified",
                               net_return=np.r_[np.nan,nav[1:]/nav[:-1]-1]))
    frames = {name:frame.copy() for name in METHODS}
    frames[METHODS[0]].loc[2,"valuation_status"] = "stale"
    selected, _, _ = complete_case_returns(frames,"2025-07-01")
    assert dates[2] not in selected.index and dates[3] not in selected.index
    assert list(selected.columns) == METHODS
