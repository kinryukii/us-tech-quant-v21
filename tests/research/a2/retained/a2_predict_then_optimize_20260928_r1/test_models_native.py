"""Meaningful synthetic checks; never open evaluation data or fit real rows."""
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd
import pytest

import models_native as m
from train_models import verify_design


def synthetic_frame(n=96, p=32):
    rng = np.random.default_rng(75)
    x = rng.normal(size=(n, p))
    y = np.clip(.015*x[:, 0]-.01*x[:, 1]+rng.normal(scale=.02, size=n), -.2, .2)
    columns = [f"x{i}" for i in range(p)]
    return pd.DataFrame(x, columns=columns), y, np.ones(n), columns


def test_contract_roster_and_fixed_factory_specs():
    contract, _ = verify_design()
    assert tuple(contract["models"]) == m.MODEL_IDS
    for provider in m.MODEL_IDS:
        model = m.estimator(provider, .5) if provider in m.QUANTILE_IDS else m.estimator(provider)
        if model is not None:
            assert hasattr(model, "fit")
    assert m.estimator("mlp").max_iter == 20
    assert m.estimator("mlp_cls").n_iter_no_change == 21
    assert m.estimator("hgb_q", .1).early_stopping is False
    assert m.estimator("ngboost").tol == 0.


def test_probability_not_interpreted_as_return():
    amplitude = m.probability_amplitudes(np.array([.02, .04, -.10, -.06]), np.ones(4))
    mu, sigma = m.probability_to_moments(np.array([.8, .5, .2]), amplitude)
    np.testing.assert_allclose(mu, [.008, -.025, -.058])
    assert (sigma > 0).all() and np.all(mu < np.array([.8, .5, .2]))
    with pytest.raises(ValueError):
        m.probability_to_moments(np.array([1.1]), amplitude)


def test_quantile_crossings_rearranged_and_offset_explicit():
    q, mu, sigma = m.quantile_to_moments([[.08, -.03, .01]], offset=.005)
    np.testing.assert_allclose(q, [[-.03, .01, .08]])
    np.testing.assert_allclose(mu, [.024])
    assert sigma[0] > 0
    with pytest.raises(ValueError):
        m.quantile_to_moments([1., 2., 3.])


def test_rank_relevance_is_within_date_and_ties_match():
    dates = pd.to_datetime(["2023-01-03"]*5+["2023-01-04"]*5)
    y = np.array([-3, -2, -1, 0, 1, 100, 100, 100, 101, 102])
    relevance = m.relevance_for_dates(y, dates)
    assert (relevance >= 0).all() and (relevance <= 4).all()
    assert relevance[5] == relevance[6] == relevance[7]
    np.testing.assert_array_equal(m.group_lengths(dates), [5, 5])
    with pytest.raises(ValueError):
        m.group_lengths(dates[::-1])


@pytest.mark.parametrize("provider", ["ridge", "huber", "logistic", "hgb_q", "resnet", "fttransformer", "mlp_q", "mlp_dist"])
def test_roundtrip_feature_only_inference_and_native_shape(provider, tmp_path):
    frame, y, weights, features = synthetic_frame()
    bundle = m.NativeBundle.fit(provider, frame, y, weights, features)
    before = bundle.predict(frame.iloc[:7])
    assert np.isfinite(before[["mu", "sigma"]].to_numpy()).all()
    assert before.sigma.gt(0).all()
    if m.kind_for(provider) == "distribution":
        assert before.p_up.between(0, 1).all()
        assert before.q10.le(before.q50).all() and before.q50.le(before.q90).all()
    path = tmp_path / f"{provider}.joblib"
    bundle.save(path)
    restored = m.NativeBundle.load(path)
    contaminated = frame.iloc[:7].copy()
    contaminated["y_next_open"] = 99999.
    contaminated["future_target"] = -99999.
    after = restored.predict(contaminated)
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    if provider == "huber":
        corrected = bundle.predict(frame).mu.to_numpy()
        assert abs(np.mean(y-corrected)) < 1e-10
    if provider in ["resnet", "fttransformer", "mlp_q", "mlp_dist"]:
        assert bundle.fit_receipt["epochs"] == 12
        assert len(bundle.fit_receipt["loss_by_epoch"]) == 12


@pytest.mark.parametrize("provider", ["ebm", "linear_q", "xgb_cls", "lgb_cls", "cat_cls", "xgb_q", "lgb_q", "cat_q", "ngboost", "cat_uncertainty", "xgb_rank", "lgb_rank", "mlp", "mlp_cls"])
def test_external_native_implementations_not_substituted(provider, tmp_path):
    frame, y, weights, features = synthetic_frame(n=128)
    dates = pd.to_datetime(["2023-01-03"]*64+["2023-01-04"]*64)
    relevance = m.relevance_for_dates(y, dates)
    bundle = m.NativeBundle.fit(provider, frame, y, weights, features, dates=dates, rank_relevance=relevance)
    before = bundle.predict(frame.iloc[:11])
    assert np.isfinite(before[["mu", "sigma"]]).all().all()
    if provider.endswith("_rank"):
        assert "in-sample" in bundle.adapter["semantics"]
        assert "native_rank_score" in before
    if provider in ["mlp", "mlp_cls"]:
        assert bundle.fit_receipt["observed_iterations"] == [20]
    if provider == "ngboost":
        assert bundle.fit_receipt["boosting_rounds_completed"] == 100
    path = tmp_path / (provider+".joblib")
    bundle.save(path)
    pd.testing.assert_frame_equal(before, m.NativeBundle.load(path).predict(frame.iloc[:11]), check_exact=True)


def test_invalid_training_shape_target_and_features_rejected():
    frame, y, weights, features = synthetic_frame()
    with pytest.raises(ValueError, match="PRECLIPPED"):
        m.NativeBundle.fit("ridge", frame, y+1., weights, features)
    weights[0] = 0
    with pytest.raises(ValueError, match="TRAINING_DATA"):
        m.NativeBundle.fit("ridge", frame, y, weights, features)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    result = pytest.main([str(Path(__file__).resolve()), "-q", "-o", "faulthandler_timeout=60"])
    from common import write, sha
    write(root / "models/NATIVE_TEST_RECEIPT.json", dict(status="PASS" if result == 0 else "FAILED",
        pytest_exit_code=result, models_native_sha256=sha(root / "models_native.py"),
        tests_sha256=sha(Path(__file__)), test_scope="synthetic only; no evaluation reads or real training"))
    raise SystemExit(result)
