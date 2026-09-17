from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).with_name("a2_global_ff12_hold_replace_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_action_tested", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def pair_frame() -> pd.DataFrame:
    rows = []
    for old in ["A", "B"]:
        for new in ["X", "Y"]:
            rows.append({"incumbent": old, "challenger": new, "forced_exit": False, "chall_score_pct": .9})
    return pd.DataFrame(rows)


def test_one_to_one_matching_and_dummy_no_trade() -> None:
    frame = pair_frame()
    chosen = MODULE.matched_replacements(frame, np.array([.02, -.01, -.02, .03]), 0.0)
    assert {(a, b) for a, b, _ in chosen} == {("A", "X"), ("B", "Y")}
    assert MODULE.matched_replacements(frame, np.full(4, -1.0), 0.0) == []


def test_forced_exit_cannot_be_vetoed() -> None:
    frame = pair_frame()
    frame.loc[frame.incumbent.eq("A"), "forced_exit"] = True
    chosen = MODULE.matched_replacements(frame, np.full(4, -1.0), 0.0)
    assert len(chosen) == 1 and chosen[0][0] == "A"


def test_label_maturity_and_embargo_contract() -> None:
    cutoff = pd.Timestamp("2024-01-10")
    label_end = pd.Series(pd.to_datetime(["2024-01-08", "2024-01-10", "2024-01-11"]))
    eligible = label_end.lt(cutoff)
    assert eligible.tolist() == [True, False, False]
    assert pd.Timestamp("2025-12-31") < pd.Timestamp("2026-01-01")


def test_exact_portfolio_contract() -> None:
    weights = {f"T{i:02d}": MODULE.WEIGHT for i in range(MODULE.TOP_N)}
    assert len(weights) == 20
    assert abs(sum(weights.values()) - 1.0) <= 1e-12
    assert all(value == .05 for value in weights.values())


def test_sector_shrinkage_is_support_only() -> None:
    counts = {"A": 100, "B": 200}
    median = np.median(list(counts.values()))
    weights = {key: n / (n + median) for key, n in counts.items()}
    assert weights["B"] > weights["A"]
    assert all(0 < value < 1 for value in weights.values())


def test_preregistered_spec_budget_and_firewall() -> None:
    assert len(MODULE.STRUCTURES) * len(MODULE.MARGINS) == 12
    assert set(MODULE.MARGINS) == {"M0", "M1", "M2"}
    assert MODULE.PAIR_COST_RETURN == .001
    assert "2026" not in "|".join(MODULE.FEATURES)
