"""Joint-policy synthetic audits; no production model is fitted or selected."""
import numpy as np
import pandas as pd
import pytest
import torch
from torch import nn

try:
    from . import joint_neural as joint
except ImportError:
    import joint_neural as joint


class StateSensitive(nn.Module):
    """Known deterministic dependence lets tests distinguish a live state input."""
    def forward(self, x):
        n = len(joint.FEATURES)
        return 2 * x[:, n] + 1.5 * x[:, n + 1] + x[:, n + 2] - .5


def adapter():
    result = joint.NeuralAdapter.__new__(joint.NeuralAdapter)
    result.mean = np.zeros(len(joint.FEATURES))
    result.scale = np.ones(len(joint.FEATURES))
    result.models = [StateSensitive()]
    return result


def day_frame(n=30):
    frame = pd.DataFrame(np.zeros((n, len(joint.FEATURES))), columns=joint.FEATURES)
    frame["ticker"] = [f"A{i:02d}" for i in range(n)]
    frame["signal_date"] = pd.Timestamp("2025-01-02")
    frame["new_buy_eligible"] = True
    return frame


def synthetic_market(days=2, names=3):
    market = joint.Market.__new__(joint.Market)
    market.tickers = [f"A{i}" for i in range(names)]
    market.lookup = {t: i for i, t in enumerate(market.tickers)}
    market.days = []
    for i in range(days):
        market.days.append({
            "date": f"2025-01-0{i + 2}", "ids": torch.arange(names),
            "x": torch.zeros((names, len(joint.FEATURES)), dtype=torch.float32),
            "eligible": torch.ones(names, dtype=torch.bool),
            "close": torch.full((names,), 100., dtype=torch.float64),
            "opening": torch.full((names,), 100., dtype=torch.float64),
            "ending": torch.linspace(101., 104., names, dtype=torch.float64),
            "fill": torch.ones(names, dtype=torch.bool),
            "vol": torch.full((names,), .01, dtype=torch.float64),
        })
    return market


def fixed_trainable_model():
    model = joint.JointPolicy()
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.net[-1].bias.fill_(-.7)
    return model


def test_adapter_top20_weight_and_exposure_constraints():
    weights = adapter()(day_frame(50), {}, 1.0)
    assert len(weights) <= 20
    assert min(weights.values()) > 0
    assert max(weights.values()) <= .1 + 1e-7
    assert sum(weights.values()) <= .95 + 1e-7


def test_old_quarter_stock_cannot_get_new_or_increased_close_target():
    day = day_frame(3)
    day.loc[:1, "new_buy_eligible"] = False
    weights = adapter()(day, {"A00": .03}, .8)
    assert weights.get("A00", 0) <= .03 + 1e-7
    assert "A01" not in weights  # Ineligible and not previously held.
    assert "A02" in weights


def test_same_model_responds_to_holdings_and_cash_without_future_labels():
    day = day_frame(2)
    policy = adapter()
    empty = policy(day, {}, 1.0)
    held = policy(day, {"A00": .08}, .5)
    assert empty["A00"] != pytest.approx(held["A00"])
    only_cash_changed = policy(day, {}, .2)
    assert empty["A00"] != pytest.approx(only_cash_changed["A00"])
    poisoned = day.copy()
    poisoned["forward_return_20d"] = 1e9
    poisoned["label_end_date"] = pd.Timestamp("2099-01-01")
    poisoned["next_open"] = 1e12
    assert policy(poisoned, {"A00": .08}, .5) == held


def test_direct_objective_updates_shared_selection_and_weight_model():
    torch.manual_seed(7)
    market = synthetic_market(days=2, names=30)
    model = joint.JointPolicy()
    prior = {n: p.detach().clone() for n, p in model.named_parameters()}
    optimizer = torch.optim.Adam(model.parameters(), lr=.0005)
    info, rows = market.episode(model, optimizer=optimizer, method="direct", noise_seed=7)
    assert info["updates"] == 2
    assert any(not torch.equal(p, prior[n]) for n, p in model.named_parameters())
    assert all(r["target_names"] <= 20 for r in rows)
    assert all(r["target_exposure"] <= .95 + 1e-7 for r in rows)
    assert all(r["fees"] >= 0 for r in rows)


def test_training_rejects_unknown_end_mark_instead_of_zero_value_reward():
    market = synthetic_market(days=1)
    market.days[0]["ending"][:] = 0
    with pytest.raises((RuntimeError, AssertionError)):
        market.episode(fixed_trainable_model())


def test_training_rejects_unknown_close_for_already_held_stock():
    market = synthetic_market(days=2)
    market.days[1]["close"][:] = 0
    with pytest.raises((RuntimeError, AssertionError)):
        market.episode(fixed_trainable_model())


def test_training_ineligible_held_stock_gets_no_overnight_rebalance_purchase():
    market = synthetic_market(days=2)
    market.days[0]["ending"][:] = 50
    market.days[1]["eligible"][:] = False
    market.days[1]["opening"][:] = 50
    market.days[1]["ending"][:] = 50
    _, rows = market.episode(fixed_trainable_model())
    assert rows[0]["fees"] > 0
    # Close weight is still positive, but the next-open underweight must not
    # trigger a forbidden purchase or its associated transaction cost.
    assert rows[1]["target_exposure"] > 0
    assert rows[1]["fees"] == pytest.approx(0, abs=1e-12)


def test_market_refuses_any_2026_training_price(monkeypatch):
    panel = day_frame(1)
    prices = pd.DataFrame({"ticker": ["QQQ"], "trade_date": [pd.Timestamp("2026-01-02")],
                           "open": [100.], "close": [100.]})
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: prices.copy())
    with pytest.raises(AssertionError):
        joint.Market(panel, "2025-01-01", "2025-12-31", np.zeros(len(joint.FEATURES)), np.ones(len(joint.FEATURES)))


def test_market_future_open_changes_execution_but_not_signal_features(monkeypatch):
    panel = day_frame(1)
    calendar = pd.bdate_range("2025-01-02", periods=4)
    prices = pd.DataFrame([
        {"ticker": ticker, "trade_date": date, "open": 100. + i * 10, "close": 105. + i * 10}
        for ticker in ("A00", "QQQ") for i, date in enumerate(calendar)
    ])
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: prices.copy())
    original = joint.Market(panel, "2025-01-01", "2025-12-31", np.zeros(len(joint.FEATURES)), np.ones(len(joint.FEATURES)))
    prices.loc[prices.trade_date > calendar[0], "open"] *= 3
    changed = joint.Market(panel, "2025-01-01", "2025-12-31", np.zeros(len(joint.FEATURES)), np.ones(len(joint.FEATURES)))
    assert torch.equal(original.days[0]["x"], changed.days[0]["x"])
    assert torch.equal(original.days[0]["close"], changed.days[0]["close"])
    assert not torch.equal(original.days[0]["opening"], changed.days[0]["opening"])
