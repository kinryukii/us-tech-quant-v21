import importlib.util
from pathlib import Path

import pandas as pd


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_cleanroom_r1_preholdout.py"
SPEC = importlib.util.spec_from_file_location("cleanroom_r1", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def frame(rows, start="2024-01-02 09:00"):
    timestamp = pd.date_range(start, periods=len(rows), freq="min", tz="America/New_York")
    return pd.DataFrame({"timestamp_et": timestamp, "timestamp_utc": timestamp.tz_convert("UTC"), "session": "REGULAR_TRADING_HOURS",
                         "open": [row[0] for row in rows], "high": [row[1] for row in rows], "low": [row[2] for row in rows],
                         "close": [row[3] for row in rows], "volume": 100.0, "session_code": 2, "valid": True})


def test_cleanroom_contract_has_exactly_ten_fixed_features():
    contract = MODULE.frozen_contract()
    assert contract["feature_count"] == 10
    assert tuple(contract["features"]) == MODULE.FEATURES
    assert contract["primary_model"]["name"] == "HistGradientBoostingClassifier"


def test_same_bar_dual_touch_is_excluded_from_labelled_candidates():
    rows = [(100, 100, 100, 100)] * 61 + [(100, 102, 98, 100)] + [(100, 100, 100, 100)] * 1440
    candidates, audit = MODULE.candidate_features(frame(rows), "QQQ", include_labels=True)
    assert audit["ambiguous_label_count"] >= 1
    assert candidates.empty or not candidates["first_touch_label"].eq("AMBIGUOUS").any()


def test_holdout_feature_ledger_has_no_labels_or_probabilities():
    rows = [(100, 100, 100, 100)] * 70
    candidates, _ = MODULE.candidate_features(frame(rows, "2025-02-03 09:00"), "SOXX", include_labels=False)
    assert "target_first" not in candidates
    assert "first_touch_label" not in candidates
    assert "horizon_timestamp_utc" not in candidates
    assert candidates["feature_information_available"].all()


def test_first_cross_finds_earliest_matching_bar():
    tree, size = MODULE.build_tree(pd.Series([100.0, 100.5, 101.0, 102.0]).to_numpy(), True)
    assert MODULE.first_cross(tree, size, 0, 3, 101.0, True) == 2


def fold_rows():
    decision = pd.to_datetime([
        "2024-01-01 09:00",  # safely more than 24 clock hours before validation
        "2024-01-01 10:00",  # label end exactly 24 hours before validation
        "2024-01-02 09:00",  # label end overlaps the 24-hour embargo boundary
        "2024-01-03 10:00",  # first actual validation candidate
    ]).tz_localize("America/New_York")
    horizon = decision + pd.Timedelta(hours=24)
    return pd.DataFrame({
        "decision_timestamp_et": decision,
        "decision_timestamp_utc": decision.tz_convert("UTC"),
        "horizon_timestamp_utc": horizon.tz_convert("UTC"),
        "target_first": [0, 1, 0, 1],
    })


def test_purge_excludes_training_label_that_reaches_embargo_boundary():
    train, validation, audit = MODULE.construct_purged_fold(fold_rows(), "TEST", "2024-01-03", "2024-01-03 23:59:59")
    assert len(validation) == 1
    assert list(train.decision_timestamp_et.dt.strftime("%Y-%m-%d %H:%M")) == ["2024-01-01 09:00"]
    assert audit["purge_pass"] is True
    assert audit["embargo_pass"] is True


def test_purge_keeps_training_label_safely_outside_24_clock_hours():
    train, _, audit = MODULE.construct_purged_fold(fold_rows(), "TEST", "2024-01-03", "2024-01-03 23:59:59")
    assert train.horizon_timestamp_utc.max() < pd.Timestamp("2024-01-02 15:00", tz="UTC")
    assert audit["purge_gap_hours"] > audit["required_embargo_hours"]


def test_exact_24_hour_label_information_boundary_is_strictly_excluded():
    train, _, _ = MODULE.construct_purged_fold(fold_rows(), "TEST", "2024-01-03", "2024-01-03 23:59:59")
    assert not train.decision_timestamp_et.eq(pd.Timestamp("2024-01-01 10:00", tz="America/New_York")).any()
