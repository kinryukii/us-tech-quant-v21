"""Behavioral guards on stage isolation, capacity, holdings and neural gradients."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from neural_train import FEATURES, JointPolicy, Market, execute_targets, fit_normalization, project


def tensor(values):
    return torch.tensor(values, dtype=torch.float64)


def test_stage_scaler_does_not_consume_following_year():
    frame = pd.DataFrame([{**dict.fromkeys(FEATURES, 1.), "signal_date":pd.Timestamp("2024-12-30")},
                          {**dict.fromkeys(FEATURES, 1e9), "signal_date":pd.Timestamp("2025-01-02")}])
    mean, scale, audit = fit_normalization(frame, "2025-01-01")
    np.testing.assert_equal(mean, np.ones(len(FEATURES)))
    assert audit["rows"] == 1 and audit["signal_max"] == "2024-12-30"


def test_adv_partial_fill_and_fees_enter_next_state():
    first = execute_targets(tensor([0.]), tensor(1.), tensor([100.]), torch.tensor([True]),
        tensor([.1]), torch.tensor([False]), torch.tensor([True]), tensor([1_000_000.]))
    units, cash, fees, *_ = first
    assert float(units[0]) == pytest.approx(.0001)
    assert float(cash) == pytest.approx(.98999)
    assert float(fees) == pytest.approx(.00001)
    second = execute_targets(units.detach(), cash.detach(), tensor([100.]), torch.tensor([True]),
        tensor([.1]), torch.tensor([False]), torch.tensor([True]), tensor([1_000_000.]))
    assert float(second[0][0]) == pytest.approx(.0002)
    assert float(second[1]) == pytest.approx(.97998)


def test_locked_holding_and_failed_sells_preserve_slot_limit():
    units = tensor([.025]*20+[0.])
    result = execute_targets(units, tensor(.5), tensor([1.]*21), torch.tensor([False]*20+[True]),
        tensor([0.]*20+[.1]), torch.tensor([True]+[False]*20), torch.tensor([True]*21), tensor([1e9]*21))
    assert int((result[0]>0).sum()) == 20 and float(result[0][-1]) == 0
    assert float(result[0][0]) == float(units[0]) and result[4] == 1


def test_projection_uses_residual_capacity():
    w = project(torch.ones(40), max_names=5, max_exposure=.18)
    assert int((w>0).sum()) == 5 and float(w.sum()) <= .1800001
    assert float(project(torch.ones(5), max_names=0, max_exposure=0).sum()) == 0


def miniature_market():
    market = Market.__new__(Market)
    market.tickers = ["OLD", "NEW"]; market.lookup = {"OLD":0, "NEW":1}
    def day(idx, date, fill):
        return dict(date=date, ids=torch.tensor([idx]), x=torch.zeros(1,len(FEATURES)),
            eligible=torch.tensor([True]), close=tensor([1.,1.]), signal_price_usable=torch.tensor([True,True]),
            opening=tensor([1.,1.]), ending=tensor([1.01,1.02]), fill=torch.tensor(fill),
            signal_adv_dollars=tensor([1e9,1e9]), vol=tensor([.02]))
    market.days = [day(0,"2024-01-02",[True,True]),day(1,"2024-01-03",[True,True])]
    return market


def test_future_fill_does_not_change_signal_and_direct_has_gradient():
    torch.manual_seed(5); model = JointPolicy(); market = miniature_market()
    _, before = market.episode(model)
    market.days[-1]["fill"] = torch.tensor([False,False])
    _, after = market.episode(model)
    assert before[-1]["reserved_missing_or_restricted_names"] == 1
    for key in ["target_exposure","target_names","reserved_weight"]:
        assert before[-1][key] == after[-1][key]
    initial = {k:v.clone() for k,v in model.state_dict().items()}
    info, _ = market.episode(model, torch.optim.Adam(model.parameters(),lr=.0005), "direct", 1)
    assert info["updates"] == 2
    assert any(not torch.equal(v,initial[k]) for k,v in model.state_dict().items())
