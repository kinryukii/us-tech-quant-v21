from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE = Path(__file__).with_name("a2_canonical_attribution_and_winner_loser_learnability_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_tail_combined_r1", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_rank_buckets_are_fixed() -> None:
    ranks = pd.Series([1, 5, 6, 10, 11, 15, 16, 20, 21, 25, 26, 30, 31, 40, 41])
    assert MODULE.rank_bucket(ranks).tolist() == (
        ["RANK_1_5"] * 2 + ["RANK_6_10"] * 2 + ["RANK_11_15"] * 2
        + ["RANK_16_20"] * 2 + ["RANK_21_25"] * 2 + ["RANK_26_30"] * 2
        + ["RANK_31_40"] * 2 + ["RANK_GT_40"]
    )


def test_existing_top_one_percent_uses_ceil_and_stable_order() -> None:
    frame = pd.DataFrame({"signal_date": [pd.Timestamp("2025-01-02")] * 101,
                          "ticker": [f"T{i:03d}" for i in range(101)],
                          "target": np.arange(101, dtype=float)})
    got = MODULE.mark_top_fraction(frame, "target", .01, "winner")
    assert got.winner.sum() == 2
    assert set(got.loc[got.winner, "ticker"]) == {"T099", "T100"}


def test_probability_metrics_and_lift() -> None:
    frame = pd.DataFrame({"event": [0, 0, 1, 1], "probability": [.1, .2, .8, .9]})
    metrics = MODULE.binary_metrics(frame, "event", "probability")
    assert metrics["base_rate"] == .5
    assert metrics["average_precision"] == 1
    assert metrics["ap_lift"] == 2
    assert metrics["auroc"] == 1


def test_probability_diagnostics_boolean_selection() -> None:
    frame = pd.DataFrame({"signal_date": [pd.Timestamp("2024-01-02")] * 10,
                          "ticker": [f"T{i}" for i in range(10)], "event": [0] * 8 + [1, 1],
                          "probability": np.linspace(.05, .95, 10), "fold": ["F1"] * 10})
    rows = []
    got = MODULE.add_probability_diagnostics(rows, frame, "event", "probability", "TEST", "fold")
    assert got["top_decile_rate"] == 1
    assert any(item["metric"] == "PRECISION" for item in rows)


def test_pre2026_firewall_and_no_portfolio_simulation() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert 'BOUNDARY = pd.Timestamp("2026-01-01")' in text
    assert '"post_2025_outcome_used": False' in text
    assert "simulate_portfolio" not in text
    assert "moomoo_api" not in text.lower()
    assert "requests.get" not in text


def test_authoritative_rank_observation_row_contract() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert 'row_type.eq("RANK_WINNER_OBSERVATION")' in text
    assert "pd.to_datetime(rank_rows.signal_date)" in text


def test_unmatched_tail_events_are_explicit_booleans() -> None:
    frame = pd.DataFrame({"winner": [True, np.nan], "extreme_loser": [np.nan, False]})
    converted = frame[["winner", "extreme_loser"]].fillna(False).astype(bool)
    assert converted.dtypes.eq(bool).all()
    assert converted.to_numpy().tolist() == [[True, False], [False, False]]


def test_integer_event_labels_are_not_used_as_loc_indexers() -> None:
    frame = pd.DataFrame({"event": [0, 1, 0, 1], "ticker": ["A", "B", "C", "D"]})
    events = frame.loc[frame.event.astype(bool)]
    assert events.ticker.tolist() == ["B", "D"]
    source_text = SOURCE.read_text(encoding="utf-8")
    assert "loser_mask = oos.extreme_loser.astype(bool)" in source_text


def test_winner_recall_uses_canonical_checkpoint_rank_only() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert 'top20 = oos.canonical_raw_rank.le(20)' in text
    assert '"RAW_A2_GT40_RANK_NOT_AUTHORITATIVELY_AVAILABLE"' in text
    assert 'top20 = oos["rank"].le(20)' not in text
