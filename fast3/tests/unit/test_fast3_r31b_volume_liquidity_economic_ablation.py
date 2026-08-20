import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r31b_volume_liquidity_economic_ablation.py"
SPEC = importlib.util.spec_from_file_location("fast3_r31b", SOURCE)
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def bars(days=24):
    rows = []
    for day in pd.date_range("2024-01-02", periods=days, freq="B"):
        for minute in range(65):
            stamp = pd.Timestamp(day.date(), tz="America/New_York") + pd.Timedelta(hours=9, minutes=30 + minute)
            n = len(rows) + 1
            rows.append({"timestamp_et": stamp, "timestamp_utc": stamp.tz_convert("UTC"),
                         "broker_trade_date": str(day.date()), "session": "RTH",
                         "open": 100+n*.001, "high": 100.1+n*.001, "low": 99.9+n*.001,
                         "close": 100+n*.001, "volume": 1000+n, "turnover": (1000+n)*(100+n*.001)})
    return pd.DataFrame(rows)


def test_authoritative_identities_and_bar_close_semantics():
    assert R.file_sha256(R.R31A_PREREGISTRATION) == R.R31A_PREREGISTRATION_SHA256
    assert R.file_sha256(R.R30B_MANIFEST) == R.BASELINE_FEATURE_MANIFEST_SHA256
    assert R.file_sha256(R.TARGET_CONTRACT) == R.TARGET_CONTRACT_SHA256
    proof = R.verify_bar_timestamp_semantics()
    assert proof["BAR_TIMESTAMP_SEMANTICS"] == "BAR_CLOSE_TIMESTAMP"
    assert proof["BAR_INTERVAL"] == "1 minute"
    assert proof["USE_COMPLETED_BARS_ONLY"] and not proof["CURRENT_PARTIAL_BAR_ALLOWED"]


def test_all_four_formulas_use_frozen_lookbacks_and_sessions():
    frame = bars()
    out = R.construct_features(frame)
    turnover = frame["turnover"].astype(float)
    x = np.log1p(turnover)
    i = 100
    expected_f1 = (x.iloc[i] - x.iloc[i-60:i].mean()) / x.iloc[i-60:i].std()
    assert np.isclose(out.loc[i, R.NEW_FEATURES[0]], expected_f1)
    same_session = frame.loc[:i]
    expected_vwap = same_session.loc[same_session.broker_trade_date.eq(frame.loc[i, "broker_trade_date"]), "turnover"].sum() / same_session.loc[same_session.broker_trade_date.eq(frame.loc[i, "broker_trade_date"]), "volume"].sum()
    assert np.isclose(out.loc[i, R.NEW_FEATURES[1]], frame.loc[i, "close"] / expected_vwap - 1)
    returns = np.log(frame.close).diff()
    expected_illiq = returns.abs().iloc[i-19:i+1].sum() / turnover.iloc[i-19:i+1].sum()
    assert np.isclose(out.loc[i, R.NEW_FEATURES[2]], expected_illiq)
    late = out.index[-1]
    minute = frame.loc[late, "timestamp_et"].strftime("%H:%M")
    current_day = frame.loc[late, "broker_trade_date"]
    current_cum = frame.loc[(frame.broker_trade_date.eq(current_day)) & (frame.timestamp_et.dt.strftime("%H:%M") <= minute), "turnover"].sum()
    prior = []
    for day in sorted(frame.broker_trade_date.unique())[-21:-1]:
        prior.append(frame.loc[(frame.broker_trade_date.eq(day)) & (frame.timestamp_et.dt.strftime("%H:%M") <= minute), "turnover"].sum())
    assert np.isclose(out.loc[late, R.NEW_FEATURES[3]], current_cum / np.mean(prior) - 1)


def test_future_and_current_partial_mutation_cannot_change_decision_features():
    frame = bars(); decision_i = len(frame) - 66; decision = frame.loc[decision_i, "timestamp_utc"]
    before = R.construct_features(frame).set_index("timestamp_utc").loc[decision, list(R.NEW_FEATURES)]
    changed = frame.copy(); mask = changed.timestamp_utc > decision
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        changed.loc[mask, col] = changed.loc[mask, col] * 99 + 7
    after = R.construct_features(changed).set_index("timestamp_utc").loc[decision, list(R.NEW_FEATURES)]
    np.testing.assert_allclose(before.astype(float), after.astype(float), rtol=1e-12, atol=1e-15, equal_nan=True)


def test_profile_reference_excludes_current_and_future_session():
    frame = bars(); out = R.construct_features(frame)
    decision_i = len(frame) - 66; decision_day = frame.loc[decision_i, "broker_trade_date"]
    changed = frame.copy(); changed.loc[changed.broker_trade_date >= decision_day, "turnover"] *= 3
    # A prior-day value cannot change when the current/future sessions change.
    prior_i = frame.index[frame.broker_trade_date < decision_day][-1]
    assert np.isclose(out.loc[prior_i, R.NEW_FEATURES[3]], R.construct_features(changed).loc[prior_i, R.NEW_FEATURES[3]], equal_nan=True)


def test_arm_target_split_model_and_baseline_contracts_are_exact():
    manifest = R.read_json(R.R30B_MANIFEST); prereg = R.read_json(R.R31A_PREREGISTRATION)
    assert len(manifest["arms"]["ARM_ALL"]) == 29
    assert set(prereg["APPROVED_FEATURE_DEFINITIONS"]) == set(R.NEW_FEATURES)
    assert prereg["TARGETS"] == ["T1", "T2"] and not prereg["HYPERPARAMETER_SEARCH_ALLOWED"] and not prereg["LOOKBACK_SEARCH_ALLOWED"]
    summary = R.read_json(R.R30B_SUMMARY)
    assert summary["ALL_T1_AUC"] == R.EXPECTED_BASELINE["T1_ROC_AUC"]
    assert summary["ALL_T2_SPEARMAN"] == R.EXPECTED_BASELINE["T2_Spearman_vs_raw_net20"]


def test_manifest_freezes_before_fit_and_no_forward_or_future_fill():
    source = SOURCE.read_text(encoding="utf-8")
    assert source.index("manifest_sha = freeze_manifest") < source.index("train_arm(\"ARM_0\"")
    assert "merge_asof" not in source and ".bfill(" not in source and "backfill(" not in source
    assert '"ECONOMIC_OUTCOME_COLUMN_READ_COUNT_DURING_FEATURE_BUILD": 0' in source
    assert source.index("build_feature_ledger(") < source.index("targets = pd.read_parquet")


def test_storage_holdout_and_anti_bloat_contract():
    source = SOURCE.read_text(encoding="utf-8")
    assert '"FINAL_CONFIRMATION_DATA_USED": False' in source
    assert '"FINAL_CONFIRMATION_DATA_INSPECTED": False' in source
    assert '"DATA_ROOT_WRITE_COUNT": 0' in source
    assert '"ANTI_BLOAT_STATUS": "PASS"' in source
    assert not list((Path(__file__).parents[2] / "scripts" / "run").glob("*r31b*helper*"))
