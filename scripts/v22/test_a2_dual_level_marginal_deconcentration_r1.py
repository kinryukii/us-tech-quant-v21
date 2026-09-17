from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import a2_dual_level_marginal_deconcentration_r1 as audit


def _day() -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": [f"T{i:02d}" for i in range(20)],
        "a2_prediction": np.linspace(1, 0, 20),
        "ff12": ["A"] * 8 + ["B"] * 6 + ["C"] * 6,
        "ff48": ["A1"] * 4 + ["A2"] * 4 + ["B1"] * 3 + ["B2"] * 3 + ["C1"] * 3 + ["C2"] * 3,
    })


def test_delta_hhi48_arithmetic() -> None:
    assert audit.delta_hhi48(0.20, 0.05) == pytest.approx(2 * 0.20 * 0.05 + 0.05**2)


def test_s1_independent_formula() -> None:
    day = _day()
    weights = audit.s1_independent_weights(day)
    assert len(weights) == 20
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)
    observed = day.assign(weight=day.ticker.map(weights)).groupby("ff12").weight.sum().sort_index()
    counts = day.groupby("ff12").ticker.count().astype(float)
    expected = (counts / counts.sum()).pow(0.75)
    expected /= expected.sum()
    np.testing.assert_allclose(observed, expected.sort_index(), atol=1e-12, rtol=0)


def test_r48_zero_selects_same_full_top20_and_weights() -> None:
    day = _day()
    weights = audit.s1_independent_weights(day)
    order = audit.sequential_order(
        day.rename(columns={"a2_prediction": "base_utility"})[["ticker", "base_utility", "ff48"]],
        20, 0.0, weights,
    )
    assert set(order) == set(day.ticker)
    assert len(order) == 20


def test_sequential_state_is_dynamic_not_static_shortcut() -> None:
    frame = pd.DataFrame({
        "ticker": ["A", "B", "C"], "base_utility": [1.0, 0.9, 0.9], "ff48": ["X", "X", "Y"],
    })
    order = audit.sequential_order(frame, 2, 0.3, {"A": 0.5, "B": 0.5, "C": 0.5})
    assert order == ["A", "C"]


def test_concentration_selector_rejects_economic_columns() -> None:
    frame = pd.DataFrame(columns=[
        "session_date", "r48", "ff12_hhi", "ff48_hhi", "ff48_max_weight", "feasible_top20", "sharpe",
    ])
    with pytest.raises(audit.GateFailure, match="ECONOMIC_COLUMN_VISIBLE"):
        audit.concentration_only_selection(frame)


def test_empty_pre2023_support_selects_nothing() -> None:
    frame = pd.DataFrame(columns=["session_date", "r48", "ff12_hhi", "ff48_hhi", "ff48_max_weight", "feasible_top20"])
    selected, table = audit.concentration_only_selection(frame)
    assert selected is None
    assert list(table.r48) == [0.0, 0.1, 0.2, 0.3]
    assert table.support_session_count.eq(0).all()
    assert not table.selection_used_economic_outcomes.any()


def test_frozen_hashes_and_support_boundaries() -> None:
    assert audit.sha256_file(audit.TAXONOMY) == audit.EXPECTED_TAXONOMY_FILE_SHA256
    assert audit.sha256_file(audit.UPSTREAM_MODEL) == audit.EXPECTED_RIDGE_SHA256
    taxonomy = pd.read_parquet(audit.TAXONOMY, columns=["signal_date"])
    top20 = pd.read_parquet(audit.TOP20, columns=["signal_date", "ticker"])
    assert pd.to_datetime(taxonomy.signal_date).min() == pd.Timestamp("2023-01-03")
    assert pd.to_datetime(top20.signal_date).min() == pd.Timestamp("2023-01-03")
    assert top20.groupby("signal_date").ticker.nunique().eq(20).all()


def test_completed_artifacts_if_present() -> None:
    if not audit.OUT.exists():
        pytest.skip("runner has not emitted artifacts yet")
    assert len(list(audit.OUT.iterdir())) <= 7
    classification = json.loads((audit.OUT / "classification.json").read_text(encoding="utf-8"))
    assert classification["2026_outcome_used"] is False
    assert classification["2026_leakage_count"] == 0
    assert classification["model_fit_count"] == 0
    assert classification["r48_selected"] is None
