"""Behavior checks for the common policy bridge and frozen inference runner."""
from pathlib import Path
import json
import subprocess
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import pytest
import replay


def test_allocator_preserves_eligibility_slots_budget_and_zero_exit():
    day = pd.DataFrame(dict(ticker=["A", "B", "C"], new_buy_eligible=[False, True, True]))
    ctx = SimpleNamespace(buy_restricted_tickers=(), available_slots=1, available_weight=.05)
    current = np.array([.025, 0., 0.])
    scores = np.array([[0, .01, 99, 100, 101], [0, .02, .04, 10, 20], [0, -.1, -.2, -.3, -.4]])
    weights, selected, allowed = replay.allocate(day, ctx, current, scores)
    assert not allowed[0, 2:].any()
    assert np.allclose(weights, [0., .05, 0.])
    assert (weights > 0).sum() <= 1
    assert weights.sum() <= .05


def test_expert_grid_describes_cash_current_collinearity_without_clipping():
    coverage = replay.original_grid_coverage([0., .05, .1, .1], [.95, .5, .05, .3], [0., 10., 40., 60.])
    assert coverage["expert_original_grid_exact"].tolist() == [True, True, True, False]
    assert coverage["expert_original_cash_current_line_supported"].tolist() == [True, True, True, False]
    assert coverage["expert_original_state_box_outside"].tolist() == [False, False, False, True]
    assert coverage["expert_original_cash_current_line_gap"][-1] == pytest.approx(.25)


class FixedPolicy:
    kind = "M0"
    method = "M0"
    stage = "validation"

    def score_actions_with_diagnostics(self, day, current, cash, age, slots):
        n = len(day)
        scores = np.tile([0., .01, .02, -.01, -.02], (n, 1))
        self.last_features = (np.zeros((n*5, 12)), np.zeros((n*5, 4)), np.zeros((n*5, 5)))
        return scores, pd.DataFrame(dict(prediction_utility=scores.reshape(-1),
            effective_raw_hgb=np.ones(n*5), contribution_hgb=scores.reshape(-1), outside_state=np.zeros(n*5, bool)))


class OtherMeta:
    def predict(self, p, z, basis):
        return np.tile([0., -.01, -.02, -.03, -.04], len(p)//5)


def test_original_engine_next_open_and_missing_input_holds_units(tmp_path):
    calendar = pd.date_range("2025-01-02", periods=3, freq="B")
    prices = pd.DataFrame(dict(ticker=["A"]*3, trade_date=calendar,
                              open=[10., 20., 25.], close=[10., 20., 25.]))
    # The stock is present at the first signal, then absent. The original
    # engine must reserve and preserve its actual units at the second signal.
    panel = pd.DataFrame(dict(ticker=["A"], signal_date=[calendar[0]], new_buy_eligible=[True],
                              realized_vol_20d=[.02], avg_dollar_volume_20d=[1e9]))
    actor = replay.SharedDecisionAdapter(FixedPolicy(), tmp_path, OtherMeta())
    result = replay.engine_v2.run_replay(prices, calendar, panel, actor, candidate="M0",
        capacity_fraction=.01, cost_bps=10, signal_start=calendar[0], signal_end=calendar[1])
    actor.close(tmp_path)
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade.execution_date == calendar[1]
    assert trade.price == 20.
    assert trade.notional == pytest.approx(50000.)
    assert trade.transaction_cost == pytest.approx(50.)
    assert result.daily.iloc[-1].nav == pytest.approx(1012450.)
    absent = result.target_decisions.loc[result.target_decisions.signal_date.eq(calendar[1])].iloc[0]
    assert absent.order_type == "HOLD_UNITS"
    assert absent.hold_units == 2500.
    assert result.daily.iloc[-1].actual_name_count == 1
    assert replay.verify_ledger(result, 10)["status"] == "PASS"
    pair = pd.read_parquet(tmp_path / "same_account_pair.parquet")
    assert pair.M0_target.iloc[0] == .05
    assert pair.M1_target.iloc[0] == 0.
    # The hypothetical M1 target did not enter the actual M0 account.
    assert result.positions.iloc[-1].index_units == 2500.
    assert pair.diagnostic_status.iloc[0].startswith("POST_HOC_")


def test_original_engine_buy_capacity_uses_signal_adv(tmp_path):
    calendar = pd.date_range("2025-01-02", periods=2, freq="B")
    prices = pd.DataFrame(dict(ticker=["A"]*2, trade_date=calendar, open=[10., 20.], close=[10., 20.]))
    panel = pd.DataFrame(dict(ticker=["A"], signal_date=[calendar[0]], new_buy_eligible=[True],
                              realized_vol_20d=[.02], avg_dollar_volume_20d=[100000.]))
    actor = replay.SharedDecisionAdapter(FixedPolicy(), tmp_path)
    result = replay.engine_v2.run_replay(prices, calendar, panel, actor, candidate="M0",
        capacity_fraction=.01, cost_bps=25, signal_start=calendar[0], signal_end=calendar[0])
    actor.close(tmp_path)
    assert result.trades.notional.iloc[0] == pytest.approx(1000.)
    assert result.trades.transaction_cost.iloc[0] == pytest.approx(2.5)
    assert result.daily.cash.iloc[-1] == pytest.approx(998997.5)
    assert replay.verify_ledger(result, 25)["status"] == "PASS"


def test_sklearn_fit_forbidden_in_separate_process():
    script = "\n".join([
        "import sys", f"sys.path.insert(0, {str(ROOT)!r})", "import replay",
        "from sklearn.linear_model import Ridge", "guard=replay.forbid_fitting()",
        "try:", "    Ridge().fit([[0],[1]],[0,1])", "except RuntimeError as error:",
        "    assert str(error)=='FIT_FORBIDDEN_DURING_EVALUATION'", "else:",
        "    raise AssertionError('fit was permitted')", "assert guard['attempts']==1", "print('PASS')"])
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_same_immutable_source_engine_and_allocator_are_used():
    assert Path(replay.engine_v2.__file__).resolve() == replay.OLD / "engine_v2.py"
    assert Path(replay.v.__file__).resolve() == replay.OLD / "values.py"
    assert replay.v.COST == .001
    assert replay.v.RISK_AVERSION == 4.
    assert replay.v.ACTIONS.tolist() == [0., .025, .05, .075, .1]


def test_custom_fit_guard_blocks_solver_and_weighted_scaler():
    class DummyScaler:
        @classmethod
        def fit_chunks(cls, *args):
            raise AssertionError("unexpected scaler fit")
    module = SimpleNamespace(fit_meta=lambda: None, fit_scalers=lambda: None, WeightedScaler=DummyScaler)
    guard = {"attempts": 0}
    blocked = replay.forbid_custom_fitting(module, guard)
    assert set(blocked) == {"meta.fit_meta", "meta.fit_scalers", "WeightedScaler.fit_chunks"}
    for entrypoint in [module.fit_meta, module.fit_scalers, DummyScaler.fit_chunks]:
        with pytest.raises(RuntimeError, match="CUSTOM_FIT_FORBIDDEN_DURING_EVALUATION"):
            entrypoint()
    assert guard["attempts"] == 3


def test_same_account_stream_reserved_cash_zero_has_stable_float_schema(tmp_path):
    actor = replay.SharedDecisionAdapter(FixedPolicy(), tmp_path, OtherMeta())
    day = pd.DataFrame(dict(ticker=["A"], new_buy_eligible=[True], realized_vol_20d=[.02]))
    common = dict(current_weights={}, current_units={}, cash_weight=1.,
                  available_slots=20, available_weight=.95, buy_restricted_tickers=())
    for date, reserved in [(pd.Timestamp("2025-01-02"), 0), (pd.Timestamp("2025-01-03"), .02)]:
        ctx = SimpleNamespace(**common, signal_date=date, reserved_weight=reserved)
        actor(day, ctx)
    actor.close(tmp_path)
    pairs = pd.read_parquet(tmp_path / "same_account_pair.parquet")
    assert pairs.reserved_weight.tolist() == [0., .02]
    assert pairs.reserved_weight.dtype == np.dtype("float64")
