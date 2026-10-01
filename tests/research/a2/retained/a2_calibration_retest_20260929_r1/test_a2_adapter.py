"""Synthetic checks only: exact coverage, legal clocks, numeric and seal guards."""
import sys
sys.dont_write_bytecode = True

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import a2_adapter as ad


def common_frame():
    return pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-03", "2024-01-02", "2024-01-02"]),
        "ticker": ["C", "B", "A"],
        "label_end_date": pd.to_datetime(["2024-01-05", "2024-01-04", "2024-01-04"]),
        "y_next_open": [.004, -.002, .001],
    })


def raw_frame(common=None):
    common = common_frame() if common is None else common
    result = common[ad.KEYS].copy()
    result["a2_prediction"] = np.arange(len(result), dtype=float) * .01 - .03
    return result


def direct_old_sample(frame):
    # Independent reference of the frozen procedure, not a call to new helpers.
    ordered = frame.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    generator = np.random.default_rng(20260928)
    quota = max(1, 40000 // ordered.signal_date.nunique())
    chosen = []
    for _, group in ordered.groupby("signal_date", sort=True):
        chosen.extend(sorted(generator.choice(group.index, min(quota, len(group)), replace=False)))
    if len(chosen) > 40000:
        chosen = sorted(generator.choice(chosen, 40000, replace=False))
    return ordered.loc[chosen].reset_index(drop=True)


def direct_old_weights(dates):
    dates = pd.Series(dates)
    counts = dates.map(dates.value_counts()).to_numpy(float)
    weights = 1. / counts
    return weights / weights.mean()


def synthetic_history(counts):
    dates = pd.bdate_range("2024-02-01", periods=len(counts))
    rows = [(date, f"S{stock:05d}", day_index)
            for day_index, (date, count) in enumerate(zip(dates, counts))
            for stock in range(count)]
    result = pd.DataFrame(rows, columns=["signal_date", "ticker", "date_number"])
    row_number = np.arange(len(result), dtype=float)
    result["raw_a2_score"] = np.sin(row_number * .017) * .06 + result.date_number * .0001
    result["y_next_open"] = (.0017 + .037 * result.raw_a2_score
                            + np.cos(row_number * .031) * .002
                            + result.date_number * .000003)
    result["label_end_date"] = result.signal_date + pd.offsets.BDay(2)
    return result.drop(columns="date_number").iloc[::-1].reset_index(drop=True)


def test_exact_keys_reorder_scores_and_preserve_common_targets():
    common = common_frame()
    scores = raw_frame(common)
    original_common, original_scores = common.copy(deep=True), scores.copy(deep=True)
    aligned = ad.align_history(scores.iloc[[2, 0, 1]], common, "2025-01-01")
    pd.testing.assert_frame_equal(aligned[common.columns], common, check_exact=True)
    np.testing.assert_array_equal(aligned.raw_a2_score, scores.a2_prediction)
    assert aligned.attrs["unused_original_oof_keys"] == 0
    pd.testing.assert_frame_equal(common, original_common, check_exact=True)
    pd.testing.assert_frame_equal(scores, original_scores, check_exact=True)


def test_original_superset_is_explicit_but_required_keys_cannot_disappear():
    common = common_frame()
    scores = raw_frame(common)
    extra = scores.iloc[[0]].copy()
    extra["ticker"] = "UNUSED"
    superset = pd.concat([scores, extra], ignore_index=True)
    with pytest.raises(ValueError, match="KEY_SETS_DIFFER"):
        ad.align_history(superset, common, "2025-01-01")
    aligned = ad.align_history(superset, common, "2025-01-01", require_same_keys=False)
    assert len(aligned) == len(common)
    assert aligned.attrs["unused_original_oof_keys"] == 1
    np.testing.assert_array_equal(aligned.raw_a2_score, scores.a2_prediction)
    with pytest.raises(ValueError, match="MISSING_SCORE_KEYS"):
        ad.align_history(superset.iloc[1:], common, "2025-01-01", require_same_keys=False)


@pytest.mark.parametrize("side", ["original", "common"])
def test_duplicate_keys_fail_even_with_superset_permitted(side):
    common, scores = common_frame(), raw_frame()
    if side == "original":
        scores = pd.concat([scores, scores.iloc[[0]]], ignore_index=True)
    else:
        common = pd.concat([common, common.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="DUPLICATE_KEYS"):
        ad.align_history(scores, common, "2025-01-01", require_same_keys=False)


@pytest.mark.parametrize("defect", ["signal_at_cutoff", "label_at_cutoff", "label_before_signal",
                                  "missing_label", "cutoff_after_2026"])
def test_clock_boundary_is_exclusive_and_labels_must_mature(defect):
    common = common_frame()
    cutoff = "2025-01-01"
    if defect == "signal_at_cutoff":
        common.loc[0, "signal_date"] = pd.Timestamp(cutoff)
        common.loc[0, "label_end_date"] = pd.Timestamp("2025-01-03")
    elif defect == "label_at_cutoff":
        common.loc[0, "label_end_date"] = pd.Timestamp(cutoff)
    elif defect == "label_before_signal":
        common.loc[0, "label_end_date"] = pd.Timestamp("2024-01-02")
    elif defect == "missing_label":
        common.loc[0, "label_end_date"] = pd.NaT
    else:
        cutoff = "2026-01-02"
    with pytest.raises(ValueError, match="CLOCK|CUTOFF"):
        ad.align_history(raw_frame(common), common, cutoff)


@pytest.mark.parametrize("column,value", [("a2_prediction", np.nan), ("a2_prediction", np.inf),
                                          ("y_next_open", np.nan), ("y_next_open", -np.inf)])
def test_nonfinite_score_or_one_day_label_is_not_a_row_filter(column, value):
    common, scores = common_frame(), raw_frame()
    (scores if column == "a2_prediction" else common).loc[0, column] = value
    with pytest.raises(ValueError, match="NONFINITE"):
        ad.align_history(scores, common, "2025-01-01")


def test_old_seed_and_40000_sampling_match_independent_reference():
    history = synthetic_history([1500] * 40)
    original = history.copy(deep=True)
    actual = ad.sample(history)
    expected = direct_old_sample(history)
    assert len(actual) == 40000
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    pd.testing.assert_frame_equal(history, original, check_exact=True)
    pd.testing.assert_frame_equal(ad.sample(history.iloc[::-1]), expected, check_exact=True)


def test_date_weights_give_equal_date_mass_despite_unequal_cross_sections():
    history = synthetic_history([3, 7, 2])
    actual = ad.date_weights(history.signal_date)
    np.testing.assert_array_equal(actual, direct_old_weights(history.signal_date))
    sums = pd.Series(actual).groupby(history.signal_date).sum().to_numpy()
    np.testing.assert_allclose(sums, np.full(3, len(history) / 3), rtol=0, atol=1e-14)
    assert np.mean(actual) == pytest.approx(1., abs=1e-15)


@pytest.mark.parametrize("counts", [[1500] * 40, [3, 7, 2]])
def test_scaler_ridge100_and_residual_match_direct_old_numeric_method(counts, monkeypatch):
    history = synthetic_history(counts)
    base_load = Mock(side_effect=AssertionError("base model cannot be loaded for calibration"))
    base_fit = Mock(side_effect=AssertionError("base model cannot be fitted"))
    monkeypatch.setattr(ad.joblib, "load", base_load)
    monkeypatch.setattr(ad.HistGradientBoostingRegressor, "fit", base_fit)
    fitted, receipt = ad.fit_adapter(history, "2025-01-01")
    selected = direct_old_sample(history)
    x = selected[["raw_a2_score"]].to_numpy(float)
    y = selected.y_next_open.to_numpy(float)
    weights = direct_old_weights(selected.signal_date)
    with threadpool_limits(limits=1):
        scaler = StandardScaler().fit(x, sample_weight=weights)
        transformed = scaler.transform(x)
        model = Ridge(alpha=100.).fit(transformed, y, sample_weight=weights)
        mu = model.predict(transformed)
    rms = float(np.sqrt(np.average((y - mu) ** 2, weights=weights)))
    for name in ["mean_", "var_", "scale_"]:
        np.testing.assert_array_equal(getattr(fitted["scaler"], name), getattr(scaler, name))
    np.testing.assert_array_equal(fitted["model"].coef_, model.coef_)
    assert fitted["model"].intercept_ == model.intercept_
    np.testing.assert_array_equal(ad.predict_adapter(fitted, selected.raw_a2_score), mu)
    assert fitted["residual_rms"] == max(rms, 1e-6)
    assert receipt["sampled_rows"] == len(selected)
    assert receipt["full_history_rows"] == len(history)
    assert receipt["fit_cutoff_exclusive"] == "2025-01-01"
    assert receipt["fit_2026_rows"] == receipt["base_model_fit_calls"] == 0
    assert receipt["new_calibrator_fit_calls"] == receipt["new_standardizer_fit_calls"] == 1
    base_load.assert_not_called()
    base_fit.assert_not_called()


@pytest.mark.parametrize("column", ["raw_a2_score", "y_next_open"])
def test_invalid_unsampled_row_fails_before_any_calibration_fit(column, monkeypatch):
    history = synthetic_history([1500] * 40)
    selected = direct_old_sample(history)
    chosen = set(selected[ad.KEYS].itertuples(index=False, name=None))
    bad_index = next(index for index, row in history[ad.KEYS].iterrows()
                     if tuple(row) not in chosen)
    history.loc[bad_index, column] = np.nan
    scaler_fit = Mock(side_effect=AssertionError("invalid history reached fitting"))
    monkeypatch.setattr(ad.StandardScaler, "fit", scaler_fit)
    with pytest.raises(ValueError, match="NONFINITE"):
        ad.fit_adapter(history, "2025-01-01")
    scaler_fit.assert_not_called()


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_adapter_inference_rejects_nonfinite_score_before_model_call(value):
    scaler = Mock()
    model = Mock()
    with pytest.raises(ValueError, match="NONFINITE_SCORE"):
        ad.predict_adapter({"scaler": scaler, "model": model}, [0., value])
    scaler.transform.assert_not_called()
    model.predict.assert_not_called()


def test_2026_without_new_seal_performs_no_reads_loads_or_predictions(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "ROOT", tmp_path)
    blockers = {}
    for target, name in [(ad, "read"), (ad.pd, "read_parquet"), (ad.joblib, "load"),
                         (ad, "_old_runtime"), (ad, "predict_original"), (ad, "predict_adapter")]:
        blocker = Mock(side_effect=AssertionError("unsealed 2026 operation:" + name))
        monkeypatch.setattr(target, name, blocker)
        blockers[name] = blocker
    with pytest.raises(RuntimeError, match="NEW_BATCH_FREEZE_REQUIRED"):
        ad.make_a2_predictions(2026)
    for blocker in blockers.values():
        blocker.assert_not_called()


def test_present_but_invalid_seal_also_precedes_all_prediction_io(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "ROOT", tmp_path)
    (tmp_path / "FROZEN_BEFORE_2026.json").write_text("{}", encoding="utf-8")
    integrity = SimpleNamespace(__file__=str(tmp_path / "integrity.py"),
                                verify_freeze=Mock(side_effect=RuntimeError("FROZEN_SOURCE_CHANGED:synthetic")))
    monkeypatch.setattr(ad.importlib, "import_module", Mock(return_value=integrity))
    reads = Mock(side_effect=AssertionError("invalid seal reached status or data"))
    base = Mock(side_effect=AssertionError("invalid seal reached original predictor"))
    monkeypatch.setattr(ad, "read", reads)
    monkeypatch.setattr(ad, "predict_original", base)
    with pytest.raises(RuntimeError, match="FROZEN_SOURCE_CHANGED"):
        ad.make_a2_predictions(2026)
    integrity.verify_freeze.assert_called_once_with()
    reads.assert_not_called()
    base.assert_not_called()


def test_preparation_is_forbidden_after_seal_before_source_access(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "ROOT", tmp_path)
    (tmp_path / "FROZEN_BEFORE_2026.json").write_text("{}", encoding="utf-8")
    check = Mock(side_effect=AssertionError("frozen prepare accessed source"))
    monkeypatch.setattr(ad, "_assert_hash", check)
    with pytest.raises(RuntimeError, match="PREPARE_FORBIDDEN_AFTER_NEW_FREEZE"):
        ad.prepare_a2_adapter("validation")
    check.assert_not_called()


class FrozenBaseSpy:
    n_features_in_ = 32

    def __init__(self, on_predict=None):
        self.fit_calls = 0
        self.predict_calls = 0
        self.on_predict = on_predict
        self.seen_x = None

    def fit(self, *args, **kwargs):
        self.fit_calls += 1
        raise AssertionError("original estimator must never fit")

    def predict(self, x):
        self.predict_calls += 1
        self.seen_x = x.copy()
        if self.on_predict is not None:
            self.on_predict()
        return x @ np.arange(1., 33.)


def synthetic_feature_input():
    order = [f"f{index:02d}" for index in range(32)]
    values = np.arange(64, dtype=float).reshape(2, 32) / 100.
    return pd.DataFrame(values, columns=order)[order[::-1]], order, values


def test_original_base_inference_uses_exact_feature_order_without_fit_or_byte_change(tmp_path, monkeypatch):
    artifact = tmp_path / "synthetic_frozen_base.joblib"
    artifact.write_bytes(b"synthetic frozen original identity")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    frame, order, expected_x = synthetic_feature_input()
    base = FrozenBaseSpy()
    load = Mock(return_value=base)
    monkeypatch.setattr(ad.joblib, "load", load)
    score = ad.predict_original(frame, artifact, digest, feature_order=order)
    load.assert_called_once_with(artifact)
    assert base.fit_calls == 0 and base.predict_calls == 1
    np.testing.assert_array_equal(base.seen_x, expected_x)
    np.testing.assert_array_equal(score, expected_x @ np.arange(1., 33.))
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == digest


def test_wrong_base_hash_blocks_deserialization(tmp_path, monkeypatch):
    artifact = tmp_path / "synthetic_base.joblib"
    artifact.write_bytes(b"original identity")
    frame, order, _ = synthetic_feature_input()
    load = Mock(side_effect=AssertionError("wrong hash reached deserialization"))
    monkeypatch.setattr(ad.joblib, "load", load)
    with pytest.raises(RuntimeError, match="SOURCE_OR_ARTIFACT_CHANGED"):
        ad.predict_original(frame, artifact, "0" * 64, feature_order=order)
    load.assert_not_called()


def test_base_byte_mutation_during_inference_is_detected(tmp_path, monkeypatch):
    artifact = tmp_path / "synthetic_base.joblib"
    artifact.write_bytes(b"original identity")
    digest = ad.sha(artifact)
    frame, order, _ = synthetic_feature_input()
    base = FrozenBaseSpy(on_predict=lambda: artifact.write_bytes(b"changed identity"))
    monkeypatch.setattr(ad.joblib, "load", Mock(return_value=base))
    with pytest.raises(RuntimeError, match="SOURCE_OR_ARTIFACT_CHANGED"):
        ad.predict_original(frame, artifact, digest, feature_order=order)
    assert base.fit_calls == 0


def test_base_fit_is_prohibited_even_inside_deserialization_context(tmp_path, monkeypatch):
    artifact = tmp_path / "synthetic_base.joblib"
    artifact.write_bytes(b"original identity")
    frame, order, _ = synthetic_feature_input()
    original_fit = ad.HistGradientBoostingRegressor.fit

    def attempted_refit(path):
        ad.HistGradientBoostingRegressor().fit(np.zeros((2, 32)), np.zeros(2))
        raise AssertionError("base refit unexpectedly returned")

    monkeypatch.setattr(ad.joblib, "load", attempted_refit)
    with pytest.raises(RuntimeError, match="ORIGINAL_A2_BASE_FIT_FORBIDDEN"):
        ad.predict_original(frame, artifact, ad.sha(artifact), feature_order=order)
    assert ad.HistGradientBoostingRegressor.fit is original_fit


@pytest.mark.parametrize("defect", ["nonfinite_feature", "missing_feature", "invalid_feature_count"])
def test_invalid_original_features_fail_before_deserialization(defect, tmp_path, monkeypatch):
    artifact = tmp_path / "synthetic_base.joblib"
    artifact.write_bytes(b"original identity")
    frame, order, _ = synthetic_feature_input()
    if defect == "nonfinite_feature":
        frame.loc[0, order[0]] = np.nan
    elif defect == "missing_feature":
        frame = frame.drop(columns=order[0])
    else:
        order = order[:-1]
    load = Mock(side_effect=AssertionError("invalid features reached base"))
    monkeypatch.setattr(ad.joblib, "load", load)
    with pytest.raises(ValueError, match="FEATURES"):
        ad.predict_original(frame, artifact, ad.sha(artifact), feature_order=order)
    load.assert_not_called()


@pytest.mark.parametrize("defect", [None, "common_before_base_cutoff", "original_label_at_prediction",
                                  "original_signal_at_prediction", "original_wrong_stage", "original_count"])
def test_prepare_synthetic_saved_oof_never_loads_or_fits_base_and_preserves_source_hashes(tmp_path, monkeypatch, defect):
    monkeypatch.setattr(ad, "ROOT", tmp_path)
    old = tmp_path / "old"
    monkeypatch.setattr(ad, "OLD", old)
    model_path, oof_path = tmp_path / "original_model", tmp_path / "original_oof"
    model_path.write_bytes(b"synthetic original frozen model")
    oof_path.write_bytes(b"synthetic original complete OOF")
    model_hash, oof_hash = ad.sha(model_path), ad.sha(oof_path)
    monkeypatch.setattr(ad, "MODEL", model_path)
    monkeypatch.setattr(ad, "OOF", oof_path)
    monkeypatch.setattr(ad, "MODEL_SHA256", model_hash)
    monkeypatch.setattr(ad, "OOF_SHA256", oof_hash)
    original_root = tmp_path / "original"
    training_path = original_root / "A2/training_matrix.parquet"
    training_path.parent.mkdir(parents=True)
    training_path.write_bytes(b"synthetic preserved original training matrix")
    monkeypatch.setattr(ad, "ORIGINAL", original_root)
    monkeypatch.setattr(ad, "TRAINING_MATRIX_SHA256", ad.sha(training_path))
    feature_order = [f"f{index:02d}" for index in range(32)]
    monkeypatch.setattr(ad, "_feature_order", lambda: feature_order)
    sources = {str(model_path): model_hash, str(oof_path): oof_hash,
               str(training_path): ad.sha(training_path)}
    monkeypatch.setattr(ad, "_preparation_sources", lambda stage: sources.copy())
    common_2023 = common_frame().copy()
    common_2023.signal_date -= pd.DateOffset(years=1)
    common_2023.label_end_date -= pd.DateOffset(years=1)
    common_2024 = common_frame()
    common = pd.concat([common_2023, common_2024], ignore_index=True)
    original = raw_frame(common)
    original["split"] = original.signal_date.dt.year.map({2023: "DEVELOPMENT", 2024: "CONFIRMATION"})
    vintage_rows = [
        {"stage": "DEVELOPMENT", "prediction_rows": len(common_2023),
         "training_target_end_last": "2022-12-31", "training_signal_last": "2022-12-01"},
        {"stage": "CONFIRMATION", "prediction_rows": len(common_2024),
         "training_target_end_last": "2023-12-31", "training_signal_last": "2023-12-01"},
    ]
    if defect == "original_label_at_prediction":
        vintage_rows[0]["training_target_end_last"] = str(common_2023.signal_date.min().date())
    elif defect == "original_signal_at_prediction":
        vintage_rows[0]["training_signal_last"] = str(common_2023.signal_date.min().date())
    elif defect == "original_count":
        vintage_rows[0]["prediction_rows"] += 1
    elif defect == "original_wrong_stage":
        original.loc[0, "split"] = "FINAL"

    def fake_read(path):
        path = Path(path)
        if path.name == "A2_REUSE_AUDIT.json":
            return {"original_raw_a2": {"feature_order": feature_order,
                                        "original_oof_stages": vintage_rows}}
        if path.name == "raw_oof_2023H2_receipt.json":
            return {"base_fit_cutoff_exclusive": "2023-01-04" if defect == "common_before_base_cutoff" else "2023-01-01"}
        if path.name == "raw_oof_2024_receipt.json":
            return {"base_fit_cutoff_exclusive": "2024-01-01"}
        raise AssertionError("unexpected metadata read:" + str(path))

    def fake_parquet(path, columns=None):
        path = Path(path)
        if path == oof_path:
            frame = original
        elif path.name == "raw_oof_2023H2.parquet":
            frame = common_2023
        elif path.name == "raw_oof_2024.parquet":
            frame = common_2024
        else:
            raise AssertionError("unexpected frame read:" + str(path))
        return frame[columns].copy() if columns is not None else frame.copy()

    monkeypatch.setattr(ad, "read", fake_read)
    monkeypatch.setattr(ad.pd, "read_parquet", fake_parquet)
    base_load = Mock(side_effect=AssertionError("saved OOF preparation loaded base"))
    base_fit = Mock(side_effect=AssertionError("saved OOF preparation fitted base"))
    base_predict = Mock(side_effect=AssertionError("saved OOF preparation backpredicted"))
    monkeypatch.setattr(ad.joblib, "load", base_load)
    monkeypatch.setattr(ad.HistGradientBoostingRegressor, "fit", base_fit)
    monkeypatch.setattr(ad, "predict_original", base_predict)
    if defect is not None:
        adapter_fit = Mock(side_effect=AssertionError("invalid source reached adapter fitting"))
        monkeypatch.setattr(ad.StandardScaler, "fit", adapter_fit)
        with pytest.raises(RuntimeError, match="CLOCK|BEFORE_BASE_FIT|STAGE_YEAR"):
            ad.prepare_a2_adapter("validation")
        adapter_fit.assert_not_called()
        base_load.assert_not_called()
        base_fit.assert_not_called()
        base_predict.assert_not_called()
        assert all(ad.sha(path) == digest for path, digest in sources.items())
        assert not list((tmp_path / "models").glob("*.joblib"))
        return
    receipt = ad.prepare_a2_adapter("validation")
    assert receipt["status"] == "TRAINED"
    assert receipt["full_history_rows"] == len(common)
    assert receipt["source_bindings"] == sources
    assert receipt["base_model_fit_calls"] == receipt["fit_2026_rows"] == 0
    assert ad.sha(model_path) == model_hash and ad.sha(oof_path) == oof_hash
    assert all(ad.sha(path) == digest for path, digest in receipt["artifacts"].items())
    base_load.assert_not_called()
    base_fit.assert_not_called()
    base_predict.assert_not_called()
