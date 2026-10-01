"""Timing, complete-day coverage, deterministic sampling and frozen-input checks."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_contract import (
    FEATURES, INPUT, STAGE_CUTOFFS, date_balanced_quotas, key_digest,
    maturity_mask, sample_training_keys, stage_frame, load_oof_frame,
    load_eval_inputs, load_pre2026_prices, validate_latest_effective,
    active_pool_quarter,
)


def synthetic_rows():
    rows = []
    for date, count in [("2023-12-20", 1), ("2023-12-21", 9), ("2023-12-22", 8)]:
        for index in range(count):
            signal = pd.Timestamp(date)
            rows.append(dict(signal_date=signal, ticker=f"T{index:02}",
                             execution_date=signal+pd.Timedelta(days=1),
                             label_end_date=signal+pd.Timedelta(days=2),
                             label_available=True, y_next_open=index/100))
    return pd.DataFrame(rows)


def test_maturity_rejects_future_endpoint_and_bad_clock():
    frame = synthetic_rows().iloc[:3].copy().reset_index(drop=True)
    frame.loc[0, "label_end_date"] = pd.Timestamp("2024-01-01")
    frame.loc[1, "execution_date"] = frame.loc[1, "signal_date"]
    assert maturity_mask(frame, "2024-01-01").tolist() == [False, False, True]


def test_sampling_preserves_every_date_and_is_row_order_invariant():
    frame = synthetic_rows()
    a = sample_training_keys(frame, "development", budget=9)
    b = sample_training_keys(frame.sample(frac=1, random_state=4), "development", budget=9)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 9
    assert a.groupby("signal_date").size().tolist() == [1, 4, 4]
    assert np.allclose(a.groupby("signal_date").sample_weight.sum(), 3.0)
    assert np.isclose(a.sample_weight.mean(), 1.0)


def test_sampling_uses_keys_only_and_known_digest_order():
    frame = synthetic_rows()
    original = sample_training_keys(frame, "development", budget=9)
    frame.y_next_open = np.arange(len(frame)) * 1e6
    changed = sample_training_keys(frame, "development", budget=9)
    pd.testing.assert_frame_equal(original, changed)
    for date, group in frame.groupby("signal_date"):
        n = int(original.signal_date.eq(date).sum())
        expected = sorted(group.ticker, key=lambda ticker: key_digest(date, ticker))[:n]
        assert set(original.loc[original.signal_date.eq(date), "ticker"]) == set(expected)


def test_quota_budget_cannot_lose_dates():
    with pytest.raises(ValueError, match="cover every"):
        date_balanced_quotas(pd.Series([2, 2, 2]), budget=2)


def test_latest_effective_carries_old_quarter_until_activation():
    timing = pd.DataFrame({"quarter": ["2023Q3", "2023Q4"],
                           "latest_filing_date": pd.to_datetime(["2023-11-14", "2024-02-14"]),
                           "quarter_effective_date": pd.to_datetime(["2023-11-21", "2024-02-22"])})
    panel = pd.DataFrame({"signal_date": pd.to_datetime(["2024-02-21", "2024-02-22"]),
                          "quarter": ["2023Q3", "2023Q4"],
                          "latest_filing_date": pd.to_datetime(["2023-11-14", "2024-02-14"]),
                          "quarter_effective_date": pd.to_datetime(["2023-11-21", "2024-02-22"])})
    validate_latest_effective(panel, timing, quarter_column="quarter")
    panel.loc[0, "quarter"] = "2023Q4"
    with pytest.raises(ValueError, match="latest"):
        validate_latest_effective(panel, timing, quarter_column="quarter")


@pytest.fixture
def publication_timing():
    return pd.DataFrame({"quarter": ["2023Q3", "2023Q4"],
                         "latest_filing_date": pd.to_datetime(["2023-11-14", "2024-02-14"]),
                         "quarter_effective_date": pd.to_datetime(["2023-11-21", "2024-02-22"])})


def test_unpublished_new_quarter_preserves_previous_members(publication_timing):
    memberships = {"2023Q3": {"OLD_A", "OLD_B"}, "2023Q4": {"NEW_C"}}
    chosen = active_pool_quarter(publication_timing, "2024-01-02")
    assert chosen == "2023Q3"
    assert memberships[chosen] == {"OLD_A", "OLD_B"}


def test_published_but_not_fifth_session_effective_preserves_previous_pool(publication_timing):
    assert active_pool_quarter(publication_timing, "2024-02-15") == "2023Q3"
    assert active_pool_quarter(publication_timing, "2024-02-21") == "2023Q3"


def test_effective_day_switches_cohort_and_local_missing_is_unknown(publication_timing):
    assert active_pool_quarter(publication_timing, "2024-02-22") == "2023Q4"
    with pytest.raises(ValueError, match="INPUT_UNKNOWN_ALREADY_PUBLIC"):
        active_pool_quarter(publication_timing, "2024-02-22", local_available={"2023Q3": True, "2023Q4": False})


def test_early_alias_preserves_frozen_development_keys():
    if not (INPUT / "pre2026.parquet").exists():
        pytest.skip("run prepare_inputs.py before snapshot integration checks")
    pd.testing.assert_frame_equal(stage_frame("early"), stage_frame("development"))


@pytest.mark.parametrize("stage", list(STAGE_CUTOFFS))
def test_prepared_stage_covers_full_mature_date_set(stage):
    if not (INPUT / "pre2026.parquet").exists():
        pytest.skip("run prepare_inputs.py before snapshot integration checks")
    full = pd.read_parquet(INPUT / "pre2026.parquet")
    selected = stage_frame(stage)
    mature = full.loc[maturity_mask(full, STAGE_CUTOFFS[stage])]
    assert len(FEATURES) == 32
    assert len(selected) <= 30000
    assert set(selected.signal_date) == set(mature.signal_date)
    assert selected.label_end_date.lt(STAGE_CUTOFFS[stage]).all()
    assert selected.y_train.between(-.20, .20).all()
    assert np.allclose(selected.groupby("signal_date").sample_weight.sum(), selected.groupby("signal_date").sample_weight.sum().iloc[0])


def test_evaluation_is_signal_only_and_original_2026_unknowns_remain_blocked():
    if not (INPUT / "eval_2026/METADATA.json").exists():
        pytest.skip("run prepare_inputs.py before snapshot integration checks")
    p25, _, c25, o25, m25 = load_eval_inputs(2025)
    p26, _, c26, _, m26 = load_eval_inputs(2026)
    assert "y_next_open" not in p25 and "y_next_open" not in p26
    assert "target" not in p25 and "target" not in p26
    assert c25.max() == pd.Timestamp("2025-12-31") and o25.empty
    assert c26.max() == pd.Timestamp("2026-09-24")
    assert m25["available_upstream_pool_complete"]
    assert m26["formal_full_pool_test_allowed"] is False
    assert m26["unknown_candidate_rows"] == 47271
    assert m26["complete_original_pool_signal_days"] == 0
    assert not (p26.context_only_if_held & p26.new_buy_eligible).any()
    assert p26.input_conflict_warning.sum() == 1
    assert load_pre2026_prices().trade_date.lt("2026-01-01").all()


def test_oof_prediction_pool_retains_unavailable_labels():
    if not (INPUT / "pre2026.parquet").exists():
        pytest.skip("run prepare_inputs.py before snapshot integration checks")
    full = load_oof_frame(2025)
    mature = load_oof_frame(2025, mature_only=True)
    assert len(full) == 111399
    assert len(mature) < len(full)
    assert mature.oof_label_mature.all()
    assert mature.label_end_date.lt("2026-01-01").all()
