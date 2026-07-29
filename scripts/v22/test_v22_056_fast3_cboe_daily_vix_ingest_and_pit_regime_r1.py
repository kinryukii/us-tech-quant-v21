from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

import v22_056_fast3_cboe_daily_vix_ingest_and_pit_regime_r1 as mod


def valid_055():
    return {
        "final_status": "BLOCKED",
        "final_decision": "VIX_MINUTE_DATA_REQUIRED_OR_INVALID",
        "v22_054_validated": True,
        "etf_data_ready": True,
        "vix_source_found": False,
        "vix_data_ready": False,
        "data_ready_for_multifactor_backtest": False,
        "multifactor_backtest_executed": False,
        "parameter_sweep_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def test_validate_055_accepts():
    mod.validate_v22_055(valid_055())


def test_validate_055_rejects():
    payload = valid_055()
    payload["etf_data_ready"] = False
    with pytest.raises(mod.IngestError):
        mod.validate_v22_055(payload)


def make_csv(rows=8000):
    dates = pd.bdate_range("1990-01-02", periods=rows)
    close = 15.0 + np.arange(rows) * 0.001
    frame = pd.DataFrame(
        {
            "DATE": dates.strftime("%m/%d/%Y"),
            "OPEN": close,
            "HIGH": close + 1.0,
            "LOW": close - 1.0,
            "CLOSE": close,
        }
    )
    return frame.to_csv(index=False).encode("utf-8")


def test_normalize_csv():
    frame = mod.normalize_vix_csv(make_csv())
    assert list(frame.columns) == ["DATE", "OPEN", "HIGH", "LOW", "CLOSE"]
    assert frame["DATE"].is_monotonic_increasing
    assert len(frame) == 8000


def test_duplicate_date_rejected():
    data = pd.read_csv(io.BytesIO(make_csv()))
    data = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    with pytest.raises(mod.IngestError):
        mod.normalize_vix_csv(data.to_csv(index=False).encode())


def test_invalid_ohlc_rejected():
    data = pd.read_csv(io.BytesIO(make_csv()))
    data.loc[10, "LOW"] = data.loc[10, "HIGH"] + 1
    with pytest.raises(mod.IngestError):
        mod.normalize_vix_csv(data.to_csv(index=False).encode())


def test_rolling_percentile_warmup():
    values = pd.Series(np.arange(300, dtype=float) + 10)
    pctl = mod.rolling_prior_percentile(values, 252)
    assert pctl.iloc[:252].isna().all()
    assert pctl.iloc[252] == pytest.approx(1.0)


def test_rolling_percentile_uses_prior_close_only():
    values = pd.Series(np.ones(253))
    values.iloc[-1] = 9999.0
    pctl = mod.rolling_prior_percentile(values, 252)
    assert pctl.iloc[-1] == pytest.approx(1.0)


def test_build_features_shift():
    daily = mod.normalize_vix_csv(make_csv())
    features = mod.build_pit_features(daily)
    assert np.isnan(features["vix_prev_close"].iloc[0])
    assert features["vix_prev_close"].iloc[1] == pytest.approx(
        daily["CLOSE"].iloc[0]
    )


def test_assert_pit_features():
    daily = mod.normalize_vix_csv(make_csv())
    features = mod.build_pit_features(daily)
    mod.assert_pit_features(daily, features)


def test_feature_percentile_range():
    daily = mod.normalize_vix_csv(make_csv())
    features = mod.build_pit_features(daily)
    values = features["vix_pctl_252_prior"].dropna()
    assert values.between(0, 1).all()


def test_long_regime_is_boolean():
    daily = mod.normalize_vix_csv(make_csv())
    features = mod.build_pit_features(daily)
    assert features["vix_long_regime_allowed_p80"].dtype == bool


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.055_FAST3_MULTIFACT" in args.v22_055_summary
    assert "vix_cboe_daily" in args.data_root
    assert "V22.056_FAST3_CBOE" in args.result_dir


def test_official_source_url():
    assert mod.SOURCE_URL.startswith("https://cdn.cboe.com/")
    assert mod.SOURCE_URL.endswith("VIX_History.csv")


def test_policy_constants():
    assert mod.ROLLING_DAYS == 252
    assert mod.MIN_REQUIRED_DATE == pd.Timestamp("2018-07-01")
