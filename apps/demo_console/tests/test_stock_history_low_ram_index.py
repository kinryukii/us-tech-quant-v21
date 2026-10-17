import pandas as pd
import pytest
from apps.demo_console.adapters import stock_history_reader as subject


def ranked_fixture():
    return pd.DataFrame([
        {"target_date": "2025-01-06", "ticker": "ABC", "security_id": "new", "rank": 7, "score": .25, "universe_id": "b"},
        {"target_date": "2025-01-03", "ticker": "ABC", "security_id": "old", "rank": 12, "score": .125, "universe_id": "a"},
    ])


@pytest.mark.parametrize("day,ticker,identity,rank", [
    ("2025-01-03", "ABC", "old", 12),
    ("2025-01-06", "ABC", "new", 7),
    ("2025-01-06", "ABC", "old", None),
    ("2025-01-03", "ABC", "new", None),
    ("2025-01-07", "ABC", "new", None),
    ("2025-01-03", "UNKNOWN", "old", None),
])
def test_identity_change_and_missing_dates_keep_rank_and_target_unknown(day, ticker, identity, rank):
    frame = ranked_fixture()
    before = frame.copy(deep=True)
    history = {"raw_history": {"_rank_index": subject._ranked_index(frame),
               "_raw_target_dates": set(frame.target_date)},
               "_scores": {}, "_targets": {sid: {} for sid in subject.APPLIED_IDS}}
    row = subject._strategy_row(history, day, ticker, identity)["RAW_A2"]
    assert row["model_rank"] == rank
    assert row["target_weight"] == (.05 if rank is not None else None)
    assert row["score_status"] == ("SCORED" if rank is not None else "NO_VERIFIED_SCORE")
    pd.testing.assert_frame_equal(frame, before)


def test_index_keeps_order_dtypes_and_exact_numeric_values_without_second_identity_store():
    frame = ranked_fixture()
    index = subject._ranked_index(frame)
    assert index.index.names == ["target_date", "ticker"]
    assert list(index.index) == list(zip(frame.target_date, frame.ticker))
    assert list(index.columns) == ["security_id", "rank", "score"]
    for name in index.columns:
        pd.testing.assert_series_equal(index[name].reset_index(drop=True), frame[name], check_names=False)
    raw = {"_rank_index": index}
    assert subject._rank_record(raw, "2025-01-03", "ABC")["security_id"] == "old"
    assert subject._rank_record(raw, "2025-01-07", "ABC") is None
