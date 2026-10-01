"""Meaningful clock, maturity and full-candidate tests, without test price values."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

import build_inputs as inputs

ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def bindings():
    return json.loads((ROOT / "input_paths.json").read_text(encoding="utf-8"))


def test_physical_pre2026_boundary_and_raw_scale_target(bindings):
    panel = pd.read_parquet(bindings["pre_panel"])
    assert len(panel) == 313668
    assert panel.signal_date.lt("2026-01-01").all()
    assert panel.loc[panel.label_available, "label_end_date"].lt("2026-01-01").all()
    assert int((~panel.label_available).sum()) == 961
    assert panel.new_buy_eligible.all()
    assert not panel.duplicated(inputs.KEY).any()
    assert np.isfinite(panel[inputs.FEATURES].to_numpy(float)).all()
    assert panel.loc[~panel.label_available, "y_abs_next_open"].isna().all()
    np.testing.assert_array_equal(panel.loc[panel.label_available, "y_abs_next_open"],
                                  panel.loc[panel.label_available, "y_next_open"].abs())
    expected = {"2024-01-01": 96442, "2025-01-01": 201385, "2026-01-01": 312707}
    for cutoff, rows in expected.items():
        mature = panel.signal_date.lt(cutoff) & panel.label_end_date.lt(cutoff) & panel.label_available
        assert int(mature.sum()) == rows


def test_next_open_target_uses_next_two_sessions(bindings):
    panel = pd.read_parquet(bindings["pre_panel"])
    prices = pd.read_parquet(bindings["pre_prices"])
    result = inputs.check_next_open_labels(panel, prices)
    assert result["maximum_absolute_reconstruction_error"] == 0
    assert result["available_labels"] == 312707


def test_full_candidate_keys_and_unknowns_remain_explicit(bindings):
    full = pd.read_parquet(bindings["full_gate"], columns=inputs.KEY + ["quarter", "current_frozen_status", "current_reason"])
    available = pd.read_parquet(bindings["full_availability"])
    candidates = pd.read_parquet(bindings["test_candidates"], columns=inputs.KEY + ["new_buy_eligible", "known_input_conflict"])
    context = pd.read_parquet(bindings["test_panel"], columns=inputs.KEY + ["new_buy_eligible", "context_only_if_held"])
    assert len(full) == 111868 and len(candidates) == 62393 and len(context) == 62476
    assert full.current_frozen_status.value_counts().to_dict() == {"QUALIFIED": 62393, "UNKNOWN": 47271, "PROVEN_INELIGIBLE": 2204}
    assert not available.loc[available.current_frozen_status.ne("QUALIFIED"), "prediction_available"].any()
    assert available.loc[available.current_frozen_status.ne("QUALIFIED"), "unavailable_reason"].str.len().gt(0).all()
    assert context.loc[~context.new_buy_eligible, "context_only_if_held"].all()
    pd.testing.assert_frame_equal(full.loc[full.current_frozen_status.eq("QUALIFIED"), inputs.KEY].sort_values(inputs.KEY).reset_index(drop=True),
                                  candidates[inputs.KEY].sort_values(inputs.KEY).reset_index(drop=True), check_dtype=False)
    assert candidates.known_input_conflict.sum() == 1
    coverage = pd.read_csv(bindings["coverage"])
    assert coverage.UNKNOWN.gt(0).all()
    assert bindings["full_pool_formal_status"] == "BLOCKED_DATA"


def test_all_candidate_clocks_and_stale_pool_rejection(bindings):
    timing = pd.read_csv(bindings["quarter_timing"], parse_dates=["latest_filing_date", "quarter_effective_date"])
    full = pd.read_parquet(bindings["full_gate"], columns=inputs.KEY + ["quarter"])
    assert inputs.check_latest_effective(full, timing, "quarter")["quarter_mismatches"] == 0
    wrong = full.head(1).copy()
    wrong.loc[:, "quarter"] = "2026Q2"
    with pytest.raises(ValueError, match="NOT_LATEST_PUBLIC_EFFECTIVE"):
        inputs.check_latest_effective(wrong, timing, "quarter")


def test_unpublished_and_not_yet_effective_quarters_carry_last_pool():
    timing = pd.DataFrame({
        "quarter": ["2025Q1", "2025Q2", "2026Q1"],
        "latest_filing_date": pd.to_datetime(["2025-05-15", "2025-08-15", "2026-05-15"]),
        "quarter_effective_date": pd.to_datetime(["2025-05-22", "2025-08-22", "2026-05-22"]),
    })
    # Before publication, after publication but before effectiveness, and across
    # multiple absent quarterly publications, new buys stay in the old pool.
    frame = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-08-14", "2025-08-18", "2025-08-22", "2026-03-31", "2026-05-21", "2026-05-22"]),
        "quarter": ["2025Q1", "2025Q1", "2025Q2", "2025Q2", "2025Q2", "2026Q1"],
        "new_buy_eligible": [True] * 6,
    })
    assert inputs.check_latest_effective(frame, timing, "quarter")["quarter_mismatches"] == 0
    assert frame.new_buy_eligible.all()
    premature = frame.iloc[[1]].copy()
    premature.loc[:, "quarter"] = "2025Q2"
    with pytest.raises(ValueError, match="NOT_LATEST_PUBLIC_EFFECTIVE"):
        inputs.check_latest_effective(premature, timing, "quarter")


def test_test_prices_are_metadata_only_and_source_bound(bindings):
    assert pq.ParquetFile(bindings["test_prices"]).metadata.num_rows == 211482
    audit = json.loads(Path(bindings["input_audit"]).read_text(encoding="utf-8"))
    assert audit["numeric_2026_price_columns_read"] is False
    assert audit["account_result_files_read"] is False
    assert audit["test2026"]["unknown_promoted"] == 0
    assert audit["test2026"]["blind_test"] is False
    for path in [bindings["pre_panel"], bindings["pre_prices"], bindings["test_panel"], bindings["test_prices"], bindings["full_gate"]]:
        assert inputs.sha(Path(path)) == bindings["output_sha256"][path]
