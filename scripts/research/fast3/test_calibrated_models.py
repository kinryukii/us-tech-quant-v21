"""Actual-library synthetic fits, separately counted from historical research."""
from collections import Counter
import json
from types import SimpleNamespace
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
import pytest

try:
    from scripts.research.fast3 import calibrated_models as models
except ImportError:
    import calibrated_models as models


@pytest.fixture(scope="module")
def synthetic_data():
    rng = np.random.default_rng(104729)
    dates = np.repeat(pd.bdate_range("2022-01-03", periods=190).strftime("%Y-%m-%d"), 2)
    signal = rng.normal(size=len(dates))
    X = pd.DataFrame({"pm_signal": signal, "pm_missing": rng.normal(size=len(dates)),
                      "pit_empty": np.nan})
    X.loc[np.arange(len(X)) % 5 == 0, "pm_missing"] = np.nan
    X.loc[240:, "pit_empty"] = 12345.0
    y = (signal > 0).astype(int)
    maturity = pd.to_datetime(pd.Series(dates) + " 12:31").dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    return X, y, dates, maturity


@pytest.fixture(scope="module")
def fit_events(tmp_path_factory, record_testsuite_property):
    events = []
    yield events
    counts = Counter((e["kind"], e["status"]) for e in events)
    report = {"identity": "SYNTHETIC_INTERFACE_TESTS_ONLY",
              "counts": {f"{kind}_{status.lower()}": n for (kind, status), n in counts.items()},
              "events": events}
    output = tmp_path_factory.getbasetemp() / "synthetic_model_fit_counts.json"
    output.write_text(json.dumps(report, indent=2, allow_nan=False, default=str), encoding="utf-8")
    for kind in ("base", "calibration"):
        record_testsuite_property(f"synthetic_{kind}_fit_calls", counts[(kind, "STARTED")])


@pytest.fixture(scope="module")
def fitted(synthetic_data, fit_events):
    X, y, dates, maturity = synthetic_data
    bundles = {}
    for spec_id in (*models.SPEC_ORDER, "B2"):
        spec = models.make_spec(spec_id, "A", list(X.columns))
        if spec["status"] == "SKIPPED_DEPENDENCY":
            continue
        base = models.fit_base(spec, X.iloc[:240], y[:240], dates[:240],
            label_available_at=maturity.iloc[:240], on_fit=fit_events.append)
        # Any second base fit or learned preprocessing fit would invalidate C.
        with patch.object(base.estimator, "fit", side_effect=AssertionError("base refit on C")) as base_fit:
            if hasattr(base.estimator, "named_steps"):
                with patch.object(base.estimator.named_steps["imputer"], "fit",
                                  side_effect=AssertionError("imputer refit on C")) as imputer_fit:
                    bundle = models.fit_calibrator(base, X.iloc[240:360], y[240:360], dates[240:360],
                        label_available_at=maturity.iloc[240:360], on_fit=fit_events.append)
                    assert imputer_fit.call_count == 0
            else:
                bundle = models.fit_calibrator(base, X.iloc[240:360], y[240:360], dates[240:360],
                    label_available_at=maturity.iloc[240:360], on_fit=fit_events.append)
            assert base_fit.call_count == 0
        bundles[spec_id] = bundle
    return bundles


def test_fixed_factory_defaults_and_dependency_priority():
    dependencies = models.dependency_record()
    expected = next((name for name in ("catboost", "xgboost", "lightgbm")
                     if dependencies["optional_dependencies"][name]["available"]), None)
    assert dependencies["optional_booster"] == expected
    for spec_id in (*models.SPEC_ORDER, "B2"):
        spec = models.make_spec(spec_id, "B", ["pm_a", "opening_b"])
        if spec["status"] != "EXECUTABLE":
            continue
        estimator = models.factory(spec)
        core = estimator.steps[-1][1] if hasattr(estimator, "steps") else estimator
        params = core.get_params()
        assert params.get("class_weight") is None
        if spec_id == "H1":
            assert params["early_stopping"] is False
            assert params["max_iter"] == 150
        if spec_id == "S1":
            assert params["probability"] is False
            assert params["kernel"] == "rbf"
            assert params["max_iter"] == 100000
        if spec_id in ("C1", "C2") and expected == "catboost":
            assert params["has_time"] is True
            assert params["use_best_model"] is False
            assert params["allow_writing_files"] is False
            assert params["thread_count"] == 2
        assert spec["calibration"]["cv"] == "one_deterministic_score_fold_empty_train_all_C_test"


def test_tampered_spec_rejected_before_fit():
    spec = models.make_spec("S1", "A", ["pm_a"])
    spec["parameters"]["probability"] = True
    with pytest.raises(ValueError, match="specification mismatch"):
        models.factory(spec)


def test_date_weights_mean_one_and_equal_daily_total():
    dates = ["2022-01-03", "2022-01-03", "2022-01-04"]
    weight = models.date_weights(dates)
    assert np.allclose(weight, [0.75, 0.75, 1.5])
    assert weight.mean() == 1.0
    assert weight[:2].sum() == weight[2]


def test_native_hgb_empty_bins_preserve_missing_column_and_restore():
    spec = models.make_spec("H1", "A", ["pm_a"])
    original = models.hgb_binning._find_binning_thresholds
    records = []
    with models._native_empty_hgb_bins(spec, records):
        function = models.hgb_binning._find_binning_thresholds
        assert function(np.array([np.nan, np.nan]), 255).size == 0
        assert function(np.array([10., np.nan]), 255, sample_weight=np.array([0., 1.])).size == 0
        # Constant and nonconstant numeric columns must remain byte-equivalent.
        for values in (np.array([3., 3., np.nan]), np.array([1., 3., np.nan, 5.])):
            weights = np.ones(len(values))
            np.testing.assert_array_equal(function(values, 255, weights), original(values, 255, weights))
        mapper = models.hgb_binning._BinMapper(n_bins=256, n_threads=1)
        matrix = np.array([[np.nan], [np.nan]])
        mapper.fit(matrix)
        assert len(mapper.bin_thresholds_) == 1
        assert mapper.bin_thresholds_[0].size == 0
        assert np.all(mapper.transform(matrix) == mapper.missing_values_bin_idx_)
        assert mapper.transform(np.array([[123.]]))[0, 0] == 0
    assert models.hgb_binning._find_binning_thresholds is original
    assert len(records) == 3


def test_all_actual_libraries_fit_calibrate_and_predict(fitted, synthetic_data):
    X = synthetic_data[0].iloc[360:]
    for bundle in fitted.values():
        prediction = models.predict(bundle, X)
        assert set(prediction) == {"raw_score", "p_raw", "p_up", "p_not_up", "predicted_up"}
        assert np.isfinite(prediction["raw_score"]).all()
        assert np.isfinite(prediction["p_up"]).all()
        assert np.allclose(prediction["p_up"] + prediction["p_not_up"], 1)
        assert np.array_equal(prediction["predicted_up"], prediction["p_up"] >= 0.5)
        assert bundle.base.metadata["dates"] == 120
        assert bundle.metadata["dates"] == 60
        assert len(bundle.metadata["optimizer"]) == 1
        assert bundle.metadata["optimizer"][0]["success"]
        assert len(bundle.calibrator.cv) == 1
        assert len(bundle.calibrator.cv[0][0]) == 0
        assert np.array_equal(bundle.calibrator.cv[0][1], np.arange(120))
        assert bundle.calibrator.calibrated_classifiers_[0].estimator.estimator is bundle.base.estimator
    hgb = fitted["H1"].base
    assert hgb.estimator.n_features_in_ == 3
    assert hgb.estimator._bin_mapper.bin_thresholds_[2].size == 0
    assert len(hgb.metadata["numerical_compatibility"]) == 1


def test_svc_margin_is_not_probability(fitted, synthetic_data):
    prediction = models.predict(fitted["S1"], synthetic_data[0].iloc[360:])
    assert np.isnan(prediction["p_raw"]).all()
    assert fitted["S1"].metadata["score_kind"] == "decision_margin"
    assert fitted["S1"].base.estimator.named_steps["model"].probability is False


def test_preprocessing_remains_T_only_including_empty_columns(fitted, synthetic_data):
    X = synthetic_data[0]
    for spec_id in ("E1", "E2", "S1", "B2"):
        pipeline = fitted[spec_id].base.estimator
        imputer = pipeline.named_steps["imputer"]
        assert np.allclose(imputer.statistics_[:2], X.iloc[:240, :2].median().to_numpy())
        assert imputer.statistics_[2] == 0.0
        assert 2 in imputer.indicator_.features_
        if "scale" in pipeline.named_steps:
            expected = imputer.transform(X.iloc[:240]).mean(axis=0)
            assert np.allclose(pipeline.named_steps["scale"].mean_, expected)


def test_saved_model_replay_within_tolerance(fitted, synthetic_data, tmp_path):
    X = synthetic_data[0].iloc[360:]
    for spec_id, bundle in fitted.items():
        path = tmp_path / f"synthetic_{spec_id}.joblib"
        joblib.dump(bundle, path)
        replay = models.predict(joblib.load(path), X)
        expected = models.predict(bundle, X)
        for key in expected:
            if key == "predicted_up":
                np.testing.assert_array_equal(replay[key], expected[key])
            else:
                # Parallel tree summation may differ at floating-point roundoff.
                # This validates saved-state replay, not bitwise CPU scheduling.
                np.testing.assert_allclose(replay[key], expected[key], rtol=0,
                                           atol=1e-12, equal_nan=True)


def test_calibration_direction_reversal_is_recorded(fitted, synthetic_data, fit_events):
    X, y, dates, maturity = synthetic_data
    flipped = models.fit_calibrator(fitted["H1"].base, X.iloc[240:360], 1-y[240:360], dates[240:360],
        label_available_at=maturity.iloc[240:360], on_fit=fit_events.append)
    assert flipped.metadata["direction_reversal"] is True
    assert flipped.metadata["effective_score_slope"] < 0


def test_calibration_optimizer_failure_is_not_silently_accepted(fitted, synthetic_data, fit_events):
    X, y, dates, maturity = synthetic_data
    failure = SimpleNamespace(success=False, status=2, message="injected optimizer failure",
                              nit=0, fun=1.0, x=np.array([0.0, 0.0]))
    original = models.calibration_api.minimize
    with patch.object(models.calibration_api, "minimize", return_value=failure):
        with pytest.raises(models.FitFailure, match="CALIBRATION_OPTIMIZER_FAILED"):
            models.fit_calibrator(fitted["H1"].base, X.iloc[240:360], y[240:360], dates[240:360],
                label_available_at=maturity.iloc[240:360], on_fit=fit_events.append)
    assert models.calibration_api.minimize is original


@pytest.mark.parametrize("kind", ["T", "C"])
def test_single_class_rejected_before_fit(kind, fitted, synthetic_data):
    X, y, dates, maturity = synthetic_data
    events = []
    with pytest.raises(models.FitFailure, match="SINGLE_CLASS"):
        if kind == "T":
            models.fit_base(fitted["H1"].base.spec, X.iloc[:240], np.zeros(240), dates[:240],
                label_available_at=maturity.iloc[:240], on_fit=events.append)
        else:
            models.fit_calibrator(fitted["H1"].base, X.iloc[240:360], np.zeros(120), dates[240:360],
                label_available_at=maturity.iloc[240:360], on_fit=events.append)
    assert events == []


def test_pre2026_boundary_and_TC_overlap(fitted, synthetic_data):
    X, y, dates, maturity = synthetic_data
    invalid = maturity.iloc[:240].copy()
    invalid.iloc[-1] = pd.Timestamp("2026-01-01T00:00:00Z")
    with pytest.raises(models.FitFailure, match="PRE2026"):
        models.fit_base(fitted["H1"].base.spec, X.iloc[:240], y[:240], dates[:240], label_available_at=invalid)
    with pytest.raises(models.FitFailure, match="T_C_OVERLAP"):
        models.fit_calibrator(fitted["H1"].base, X.iloc[:120], y[:120], dates[:120],
            label_available_at=maturity.iloc[:120])


def test_TC_size_and_sort_rules(fitted, synthetic_data):
    X, y, dates, maturity = synthetic_data
    with pytest.raises(models.FitFailure, match="DATE_COUNT_T"):
        models.fit_base(fitted["H1"].base.spec, X.iloc[:238], y[:238], dates[:238],
            label_available_at=maturity.iloc[:238])
    with pytest.raises(models.FitFailure, match="DATE_COUNT_C"):
        models.fit_calibrator(fitted["H1"].base, X.iloc[240:358], y[240:358], dates[240:358],
            label_available_at=maturity.iloc[240:358])
    with pytest.raises(models.FitFailure, match="NONCHRONOLOGICAL"):
        models.fit_base(fitted["H1"].base.spec, X.iloc[:240], y[:240], dates[:240][::-1],
            label_available_at=maturity.iloc[:240])
