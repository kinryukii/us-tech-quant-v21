from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).with_name("abcde_compact_v1_redundancy_audit_r1.py")
SPEC = importlib.util.spec_from_file_location("abcde_redundancy_audit_r1", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


def synthetic_frame(reverse_b: bool = False, duplicate: bool = False) -> pd.DataFrame:
    rows = []
    tickers = [f"T{i:03d}" for i in range(1, 31)]
    for strategy_index, strategy in enumerate(audit.STRATEGIES):
        ranks = list(range(1, 31))
        if reverse_b and strategy == "B_STATIC_MOMENTUM":
            ranks = list(reversed(ranks))
        for ticker, rank in zip(tickers, ranks, strict=True):
            rows.append({"signal_date": pd.Timestamp("2026-01-02"), "strategy_name": strategy, "ticker": ticker, "raw_score": float(31 - rank + strategy_index * 0.01), "rank": rank, "universe_size": 30, "model_version": "ABCDE_COMPACT_V1", "schema_version": audit.SOURCE_DATASET})
    if duplicate:
        rows.append(dict(rows[0]))
    return pd.DataFrame(rows)


def test_identical_strategies_are_high_redundancy():
    daily = audit.build_pairwise_daily_metrics(synthetic_frame())
    aggregate = audit.aggregate_pairwise(daily).set_index("pair_code")
    assert aggregate.loc["A_B", "median_spearman"] == pytest.approx(1.0)
    assert aggregate.loc["A_B", "median_top20_overlap"] == pytest.approx(1.0)
    assert aggregate.loc["A_B", "redundancy_classification"] == "HIGH_REDUNDANCY"


def test_reversed_ranking_has_negative_spearman():
    daily = audit.build_pairwise_daily_metrics(synthetic_frame(reverse_b=True))
    value = daily.set_index("pair_code").loc["A_B", "spearman_rank_correlation"]
    assert value == pytest.approx(-1.0)


def test_duplicate_key_fails_closed():
    with pytest.raises(audit.AuditError, match="duplicate"):
        audit.validate_frame(synthetic_frame(duplicate=True))


def test_normalized_rank_pca_construction_is_deterministic():
    frame = synthetic_frame()
    dates, _, _ = audit.comparable_date_summary(frame)
    first = audit.normalized_rank_observations(frame, dates)
    second = audit.normalized_rank_observations(frame, dates)
    assert np.array_equal(first, second)
    assert first[0, 0] == pytest.approx(1.0)
    assert first[-1, 0] == pytest.approx(0.0)


def test_rerun_aggregate_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    frame = synthetic_frame()
    monkeypatch.setattr(audit, "discover_sources", lambda _: ([], []))
    monkeypatch.setattr(audit, "load_and_validate", lambda _: frame)
    monkeypatch.setattr(audit, "sha256", lambda _: "fixed")
    first_root, second_root = tmp_path / "one", tmp_path / "two"
    audit.run_audit(tmp_path, first_root)
    audit.run_audit(tmp_path, second_root)
    assert (first_root / "abcde_pairwise_aggregate.csv").read_bytes() == (second_root / "abcde_pairwise_aggregate.csv").read_bytes()
