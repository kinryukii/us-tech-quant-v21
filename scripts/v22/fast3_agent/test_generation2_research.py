import importlib.util
from pathlib import Path

import pandas as pd


SPEC = importlib.util.spec_from_file_location("generation2", Path(__file__).with_name("generation2_research.py"))
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_prior_exposure_classification_respects_registered_windows():
    assert MOD.prior_status_for_day(pd.Timestamp("2023-06-30", tz="America/New_York")) == "PREVIOUSLY_USED_DEVELOPMENT"
    assert MOD.prior_status_for_day(pd.Timestamp("2024-06-01", tz="America/New_York")) == "PREVIOUSLY_USED_RANDOMIZED_SELECTION"
    assert MOD.prior_status_for_day(pd.Timestamp("2025-01-15", tz="America/New_York")) == "PREVIOUSLY_USED_VALIDATION"
    assert MOD.prior_status_for_day(pd.Timestamp("2025-02-10", tz="America/New_York")) == "PREVIOUSLY_UNREAD_ELIGIBLE"


def test_frozen_contract_uses_month_embargo_and_zero_confirmation_reads():
    dates = pd.date_range("2025-02-03", "2026-07-31", freq="B", tz="America/New_York")
    contract = MOD.freeze_contract(dates)
    assert contract["confirmation_read_count"] == 0
    assert pd.Timestamp(contract["development_end"]) < pd.Timestamp(contract["first_embargo_start"])
    assert pd.Timestamp(contract["validation_end"]) < pd.Timestamp(contract["second_embargo_start"])
    assert pd.Timestamp(contract["validation_end"]) < pd.Timestamp(contract["confirmation_start"])


def test_insufficient_unexposed_months_fails_closed():
    dates = pd.date_range("2025-02-03", "2025-09-30", freq="B", tz="America/New_York")
    try:
        MOD.freeze_contract(dates)
    except RuntimeError as error:
        assert str(error) == "FAIL_INSUFFICIENT_UNEXPOSED_DATA_FOR_GENERATION2"
    else:
        raise AssertionError("expected fail-closed insufficient-data decision")


def test_execution_mapping_fails_closed_on_abnormal_leveraged_return():
    utc = pd.date_range("2026-01-02 14:31:00+00:00", periods=62, freq="min")
    etf = pd.DataFrame({"timestamp_utc": utc, "open": [10.0] * 60 + [50.0, 50.0], "high": [10.0] * 60 + [50.0, 50.0], "low": [10.0] * 60 + [50.0, 50.0], "close": [10.0] * 60 + [50.0, 50.0], "volume": 1.0, "valid": True})
    sample = pd.DataFrame({"decision_timestamp_et": [pd.Timestamp("2026-01-02 09:30:00", tz="America/New_York")], "entry_timestamp_utc": [utc[0]], "calendar_date": [pd.Timestamp("2026-01-02", tz="America/New_York")], "split": ["VALIDATION"]})
    result = MOD.mapped_execution(sample, etf, etf, probabilities=[.9])
    assert result.execution_status.iloc[0] == "ABNORMAL_RETURN_DATA_QUALITY_GATE"
    assert pd.isna(result.gross_return.iloc[0])


def test_epoch_conversion_is_resolution_independent_nanoseconds():
    timestamps = pd.Series(pd.date_range("2026-01-02 14:31:00+00:00", periods=2, freq="min"))
    converted = MOD.utc_epoch_ns(timestamps)
    assert converted[1] - converted[0] == 60 * 1_000_000_000


def test_vix_prior_day_features_require_strictly_prior_information_cutoff(tmp_path):
    path = tmp_path / "vix.parquet"
    pd.DataFrame({
        "trade_date": [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")],
        "feature_information_cutoff": [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-06")],
        "vix_prev_day_return": [.01, .02],
        "vix_pctl_252_prior": [.5, .6],
        "vix_long_regime_allowed_p80": [True, True],
        "vix_short_regime_elevated_p50": [False, True],
    }).to_parquet(path, index=False)
    contract = {"development_start": "2026-01-01T00:00:00-05:00", "validation_end": "2026-01-31T23:59:59-05:00"}
    try:
        MOD.load_vix_prior_day_features(path, contract)
    except RuntimeError as error:
        assert str(error) == "VIX_PRIOR_DAY_PIT_VIOLATION"
    else:
        raise AssertionError("expected strict prior-day VIX cutoff failure")
