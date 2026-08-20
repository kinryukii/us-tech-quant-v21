from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r30a_economic_target_baseline_training.py"
SPEC = importlib.util.spec_from_file_location("fast3_r30a", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_t1_formula_is_strictly_greater_than_zero():
    ledger = pd.read_csv(R.ECONOMIC_LEDGER)
    targets, audit = R.make_targets(ledger)
    assert targets.loc[targets.raw_net20.eq(0), "T1_POSITIVE_NET20"].eq(0).all()
    assert targets.T1_POSITIVE_NET20.equals((targets.raw_net20 > 0).astype(int))
    assert audit["valid_target_row_count"] == 1197


def test_t2_is_exact_natural_signed_log1p_without_clipping():
    values = pd.Series([-2.0, -0.5, 0.0, 0.5, 2.0])
    expected = np.sign(values) * np.log1p(np.abs(values))
    assert np.allclose(expected, [-np.log(3), -np.log(1.5), 0, np.log(1.5), np.log(3)])
    ledger = pd.read_csv(R.ECONOMIC_LEDGER)
    targets, _ = R.make_targets(ledger)
    assert np.array_equal(targets.T2_ROBUST_NET20.to_numpy(),
                          (np.sign(targets.raw_net20) * np.log1p(np.abs(targets.raw_net20))).to_numpy())


def test_target_uses_corporate_action_corrected_source_and_excludes_preentry():
    ledger = pd.read_csv(R.ECONOMIC_LEDGER)
    targets, audit = R.make_targets(ledger)
    assert "corrected_net20" in ledger
    assert audit["pre_entry_noncapturable_excluded_count"] == 1
    assert audit["silent_drop_count"] == 0
    assert not targets.pre_entry_touch.any()
    assert np.isclose(targets.raw_net20.mean(), R.EXPECTED["RAW_MEAN"])


def test_contract_freezes_before_fit_and_mutation_fails_closed(tmp_path):
    path = tmp_path / "contract.json"
    digest = R.freeze_target_contract(path, "2026-08-09T00:00:00+00:00")
    R.guard_frozen_contract(path, digest)
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(R.R30AStop, match="STOP_TARGET_CONTRACT_MUTATED_AFTER_FREEZE"):
        R.guard_frozen_contract(path, digest)


def test_contract_exact_semantics_and_no_final_holdout():
    contract = R.target_contract("fixed")
    assert contract["PRIMARY_TARGET"]["COMPARATOR"] == ">"
    assert contract["SECONDARY_TARGET"]["T2_TRANSFORMATION"] == "SIGNED_LOG1P"
    assert contract["TRANSACTION_COST_DECIMAL"] == 0.002
    assert contract["FINAL_CONFIRMATION_DATA_USED"] is False
    assert contract["PRE_ENTRY_EVENT_POLICY"].startswith("PRE_ENTRY_TOUCH_NOT_CAPTURABLE")


def test_feature_manifest_is_unchanged_and_exact():
    assert R.file_sha256(R.R28_FEATURE_MANIFEST) == R.EXPECTED["FEATURE_MANIFEST_SHA256"]
    identity = R.read_json(R.R28_MODEL_IDENTITY)
    assert identity["features"] == list(R.FEATURES)
    assert identity["feature_count"] == 14


def test_future_feature_timestamp_fails_closed():
    frame = pd.DataFrame({"decision_timestamp_utc": pd.to_datetime(["2024-01-01T00:00Z"]),
                          "max_feature_timestamp_utc": pd.to_datetime(["2024-01-01T00:01Z"])})
    with pytest.raises(R.R30AStop, match="STOP_FUTURE_FEATURE_TIMESTAMP"):
        R.assert_feature_pit(frame)


def test_split_identity_reuses_time_order_and_1440_minute_purge_embargo():
    assert R.file_sha256(R.R28_SPLIT_CONTRACT) == R.EXPECTED["SPLIT_CONTRACT_SHA256"]
    assert R.PURGE_EMBARGO == pd.Timedelta(minutes=1440)
    assert R.ECONOMIC_FOLDS == R.ORIGINAL_FOLDS[1:]
    rows = pd.DataFrame({
        "decision_timestamp_utc": pd.to_datetime(["2020-01-01T00:00Z", "2021-01-01T00:00Z"]),
        "label_information_end_utc": pd.to_datetime(["2020-01-02T00:00Z", "2021-01-02T00:00Z"]),
    })
    train, valid, audit = R.construct_economic_fold(rows, R.ECONOMIC_FOLDS[0])
    assert len(train) == len(valid) == 1
    assert audit["time_order_pass"] and audit["purge_pass"] and audit["embargo_pass"]
    assert audit["overlapping_label_contamination_count"] == 0


def test_hgb_parameters_are_authoritative_and_no_preprocessing_or_search():
    classifier, regressor = R.model_parameters()
    assert classifier["random_state"] == regressor["random_state"] == 1729
    assert classifier["min_samples_leaf"] == regressor["min_samples_leaf"] == 200
    source = SCRIPT.read_text(encoding="utf-8")
    assert "GridSearchCV" not in source and "RandomizedSearchCV" not in source and "Optuna" not in source
    assert "StandardScaler" not in source and "SimpleImputer" not in source
    assert set(R.SELECTED_R28_ADDITIONS).issubset(R.FEATURES)


def sample_scored_frame(n=100):
    raw = np.linspace(-0.1, 0.1, n)
    return pd.DataFrame({
        "candidate_id": [f"c{i:03}" for i in range(n)],
        "decision_timestamp_utc": pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
        "raw_net20": raw,
        "T1_POSITIVE_NET20": (raw > 0).astype(int),
        "T2_ROBUST_NET20": np.sign(raw) * np.log1p(np.abs(raw)),
        "pred_t1": np.arange(n) / n,
        "pred_t2": raw,
        "t1_fold_train_base_rate": 0.5,
    })


def test_naive_t1_and_t2_baselines_are_reportable():
    frame = sample_scored_frame()
    t1 = R.t1_metrics(frame.T1_POSITIVE_NET20, np.full(len(frame), frame.T1_POSITIVE_NET20.mean()))
    t2mean = R.t2_metrics(frame.T2_ROBUST_NET20, np.full(len(frame), frame.T2_ROBUST_NET20.mean()), frame.raw_net20)
    t2median = R.t2_metrics(frame.T2_ROBUST_NET20, np.full(len(frame), frame.T2_ROBUST_NET20.median()), frame.raw_net20)
    assert set(t1) == {"ROC_AUC", "PR_AUC", "Brier", "LogLoss"}
    assert t2mean["MAE"] is not None and t2median["RMSE"] is not None


def test_fixed_ranking_buckets_are_top20_10_5_1_with_ceil_counts():
    frame = sample_scored_frame(101)
    t1 = R.t1_ranking_metrics(frame)
    t2 = R.t2_ranking_metrics(frame)
    assert t1.bucket_percent.tolist() == t2.bucket_percent.tolist() == [20, 10, 5, 1]
    assert t1.trade_count.tolist() == [21, 11, 6, 2]
    assert t2.trade_count.tolist() == [21, 11, 6, 2]


def test_deciles_are_fixed_and_monotonic_metrics_available():
    frame = sample_scored_frame(103)
    deciles = R.fixed_deciles(frame, "pred_t1", "ALL")
    assert deciles.prediction_decile.tolist() == list(range(1, 11))
    assert R.safe_spearman(deciles.prediction_decile, deciles.actual_positive_rate) > 0
    assert R.safe_spearman(deciles.prediction_decile, deciles.actual_raw_net20_mean) > 0


def test_data_root_has_no_write_calls_and_outputs_are_external():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'DATA_ROOT / "runtime"' not in source
    assert '(DATA_ROOT /' not in source
    assert str(R.RESULTS_ROOT).startswith(r"D:\us-tech-quant-results")
    assert not (R.SOURCE_ROOT / "results").exists()


def test_authoritative_ledger_and_contract_hashes_are_stable():
    assert hashlib.sha256(R.ECONOMIC_LEDGER.read_bytes()).hexdigest() == R.EXPECTED["ECONOMIC_LEDGER_SHA256"]
    assert R.TRUE_HOLDOUT_START == pd.Timestamp("2025-02-01T05:00:00Z")
