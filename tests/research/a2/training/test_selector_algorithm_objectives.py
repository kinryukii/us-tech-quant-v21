"""Synthetic tests only: objective math, dispatch, fixed capacities and persistence.

No research parquet, outcome, account or 2026 observation is read.
Most backend fits are spies. Small synthetic MLPs validate each new neural loss
branch; three tiny native ranker fits validate frozen backend objective support.
These are development checks, never research trials or business data fits.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace
import warnings

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import selector_algorithm_objectives as obj


class SpyEstimator:
    def __init__(self):
        self.calls = []
        self.bad = None

    def fit(self, x, y, **kwargs):
        self.calls.append((np.asarray(x), np.asarray(y), kwargs))
        return self

    def predict_proba(self, x):
        if self.bad == "nan":
            return np.full((len(x), 2), np.nan)
        return np.tile([.25, .75], (len(x), 1))

    def decision_function(self, x):
        return np.asarray(x)[:, 0] if self.bad != "shape" else np.zeros((len(x), 1))

    def predict(self, x):
        return np.asarray(x)[:, 0]


@pytest.fixture
def pred():
    def parameters(name):
        assert name == "logistic"
        return {**obj._CAPACITIES["logistic"], "convergence_extension_max_iter": 1200}

    def rank_training_data(x, y, dates):
        f = pd.DataFrame(dict(date=dates, y=y, index=np.arange(len(y))))
        f = f.sort_values(["date", "index"], kind="stable")
        relevance = np.minimum(np.floor(f.groupby("date")["y"].rank(
            method="average", pct=True).to_numpy() * 5), 4).astype(int)
        return (x[f["index"].to_numpy()],
                relevance, f.groupby("date", sort=False).size().to_numpy())

    return SimpleNamespace(
        TREE_RF=copy.deepcopy(obj._CAPACITIES["rf"]),
        TREE_HGB=copy.deepcopy(obj._CAPACITIES["hgb"]),
        TREE_XGB=copy.deepcopy(obj._CAPACITIES["xgb"]),
        TREE_LGB=copy.deepcopy(obj._CAPACITIES["lgb"]),
        TREE_CAT=copy.deepcopy(obj._CAPACITIES["cat"]),
        hyperparameters=parameters, rank_training_data=rank_training_data,
    )


@pytest.fixture
def rows():
    x = np.arange(12*32, dtype=float).reshape(12, 32) / 100
    y = np.tile([-3., -2., -1., 1., 2., 3.], 2)
    dates = pd.to_datetime(["2024-01-02"]*6 + ["2024-01-03"]*6)
    boundary = np.tile([1., 0., 1., 0., 1., 0.], 2)
    return x, y, dates, boundary


def test_exact_frozen_roles_and_independent_copy():
    specs = obj.role_specs()
    assert tuple(specs) == obj.ROLE_IDS and len(specs) == 18
    assert sum(s["objective_family"] == "BOUNDARY" for s in specs.values()) == 8
    assert sum(s["objective_family"] == "PAIRWISE" for s in specs.values()) == 4
    assert sum(s["objective_family"] == "LISTWISE" for s in specs.values()) == 3
    assert sum(s["objective_family"] == "RANK" for s in specs.values()) == 3
    assert all(s["seed"] == 20260928 and s["configurations"] == 1
               and s["scientific_retry"] == 0 and s["feature_count"] == 32
               and s["target_stat_estimation"] == 0 for s in specs.values())
    counts = pd.Series([s["family"] for s in specs.values()]).value_counts()
    assert counts.max() == 3
    specs["BOUNDARY_RF"]["capacity"]["n_estimators"] = 1
    assert obj.role_specs()["BOUNDARY_RF"]["capacity"]["n_estimators"] == 64
    assert specs["RANK_CAT_YETIRANK"]["permutations"] == 10


def test_pairs_are_date_local_distinct_seeded_and_future_append_invariant(rows):
    _, _, dates, _ = rows
    pairs = obj.pair_plan(dates)
    assert np.array_equal(pairs, obj.pair_plan(dates))
    for anchor, partner in enumerate(pairs):
        assert len(np.unique(partner)) == 4 and anchor not in partner
        assert all(dates[j] == dates[anchor] for j in partner)
    later = dates.append(pd.DatetimeIndex(["2024-01-04"]*7))
    assert np.array_equal(obj.pair_plan(later)[:len(dates)], pairs)
    with pytest.raises(ValueError, match="SEED"):
        obj.pair_plan(dates, seed=1)


def test_singleton_pair_groups_keep_zero_loss_rows():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-03"])
    plan = obj.pair_plan(dates)
    assert np.all(plan[0] == -1)
    assert plan[1, 0] == 2 and plan[2, 0] == 1
    assert np.all(plan[1:, 1:] == -1)


def test_pair_rows_normalize_anchor_and_retain_tie_identity(rows):
    x, y, dates, _ = rows
    y[:3] = 0
    plan = obj.pair_plan(dates)
    differences, label, weights, metadata = obj.pair_rows(x, y, plan)
    r, c = np.nonzero(plan >= 0)
    other = plan[r, c]
    sign = np.sign(y[r] - y[other])
    keep = sign != 0
    assert np.array_equal(differences, (x[r]-x[other])[keep])
    assert np.array_equal(label, (sign[keep] > 0).astype(int))
    assert np.all(weights == .25)
    assert metadata["tied_pairs"] > 0
    assert metadata["external_rows_dropped"] == 0
    assert metadata["training_input_rows"] == len(x)


@pytest.mark.parametrize("role", [r for r in obj.ROLE_IDS
                                  if r not in ("BOUNDARY_MLP", "PAIRWISE_MLP", "PAIRWISE_RESNET",
                                               "PAIRWISE_FT", "LISTWISE_MLP", "LISTWISE_RESNET",
                                               "LISTWISE_FT")])
def test_native_dispatch_one_fit_and_frozen_labels(role, pred, rows, monkeypatch):
    x, y, dates, boundary = rows
    spy = SpyEstimator()
    monkeypatch.setattr(obj, "_native_factory", lambda role_id, runtime: spy)
    monkeypatch.setattr(obj, "_version_for", lambda estimator: dict(module="synthetic_spy", version="0"))
    entered = []
    fitted = obj.fit(role, x, y, dates, boundary, runtime=pred, on_fit_call=entered.append)
    assert entered == [dict(operation="estimator_fit", role=role)]
    assert len(spy.calls) == 1
    fit_x, fit_y, kwargs = spy.calls[0]
    assert fitted.metadata["estimator_fit_calls"] == 1
    assert fitted.metadata["scaler_fit_calls"] == 0
    if role.startswith("BOUNDARY"):
        assert np.array_equal(fit_x, x) and np.array_equal(fit_y, boundary)
        assert not np.array_equal(boundary, y > 0)  # Caller full-pool label is honored.
        assert kwargs == {}
    elif role == "PAIRWISE_LINEAR":
        assert "sample_weight" in kwargs and set(np.unique(fit_y)) == {0, 1}
    else:
        expected_x, expected_y, sizes = pred.rank_training_data(x, y, dates)
        assert np.array_equal(fit_x, expected_x) and np.array_equal(fit_y, expected_y)
        assert fit_y.max() == 4
        if role == "RANK_CAT_YETIRANK":
            assert np.array_equal(kwargs["group_id"], np.repeat(np.arange(2), sizes))
        else:
            assert np.array_equal(kwargs["group"], sizes)
    score = obj.predict(fitted, x)
    assert score.shape == (len(x),) and np.isfinite(score).all()


@pytest.mark.parametrize("role", ["BOUNDARY_MLP", "PAIRWISE_MLP", "PAIRWISE_RESNET",
                                  "PAIRWISE_FT", "LISTWISE_MLP", "LISTWISE_RESNET", "LISTWISE_FT"])
def test_neural_dispatch_one_estimator_fit(role, pred, rows, monkeypatch):
    calls = []
    def fake_fit(*args, on_fit_call=None):
        calls.append(args)
        if on_fit_call is not None:
            on_fit_call(dict(operation="estimator_fit", role=args[0]))
        return object(), dict(epochs=10, updates=10, backend={"module": "synthetic_spy"})
    monkeypatch.setattr(obj, "_fit_neural", fake_fit)
    entered = []
    fitted = obj.fit(role, *rows, runtime=pred, on_fit_call=entered.append)
    assert entered == [dict(operation="estimator_fit", role=role)]
    assert fitted.neural is True and len(calls) == 1
    assert fitted.metadata["epochs"] == 10 and fitted.metadata["estimator_fit_calls"] == 1


@pytest.mark.parametrize("bad", ["features", "target", "boundary", "clock"])
def test_bad_input_precedes_any_fit(bad, rows, monkeypatch):
    x, y, dates, boundary = [a.copy() for a in rows]
    if bad == "features":
        x[0, 0] = np.nan
    elif bad == "target":
        y[0] = np.inf
    elif bad == "boundary":
        boundary[0] = .5
    else:
        dates = pd.DatetimeIndex([pd.NaT]*len(x))
    monkeypatch.setattr(obj, "_predictors", lambda runtime: pytest.fail("Fit runtime must not load"))
    with pytest.raises(ValueError):
        obj.fit("BOUNDARY_RF", x, y, dates, boundary)


def test_single_class_boundary_fails_without_estimator_fit(pred, rows, monkeypatch):
    x, y, dates, _ = rows
    monkeypatch.setattr(obj, "_native_factory", lambda *a: pytest.fail("No class substitution"))
    with pytest.raises(ValueError, match="BOTH_CLASSES"):
        obj.fit("BOUNDARY_RF", x, y, dates, np.zeros(len(x)), runtime=pred)


def test_unknown_role_capacity_change_and_convergence_never_retry(pred, rows, monkeypatch):
    with pytest.raises(ValueError, match="UNKNOWN"):
        obj.fit("UNREGISTERED", *rows, runtime=pred)
    changed = copy.deepcopy(pred)
    changed.TREE_RF["n_estimators"] += 1
    with pytest.raises(ValueError, match="CAPACITY_CHANGED"):
        obj.fit("BOUNDARY_RF", *rows, runtime=changed)
    from sklearn.exceptions import ConvergenceWarning
    spy = SpyEstimator()
    def unconverged(x, y, **kwargs):
        spy.calls.append((x, y, kwargs))
        warnings.warn("Synthetic nonconvergence", ConvergenceWarning)
        return spy
    spy.fit = unconverged
    monkeypatch.setattr(obj, "_native_factory", lambda *a: spy)
    with pytest.raises(RuntimeError, match="NO_RETRY"):
        obj.fit("BOUNDARY_LOGISTIC", *rows, runtime=pred)
    assert len(spy.calls) == 1


def test_prediction_preserves_rows_and_rejects_nonfinite_shape(rows):
    x = rows[0]
    spy = SpyEstimator()
    fit = obj.FittedObjective("BOUNDARY_RF", spy, {})
    assert obj.predict(fit, x).shape == (len(x),)
    assert obj.predict(fit, x[:0]).shape == (0,)
    spy.bad = "nan"
    with pytest.raises(ValueError, match="NONFINITE"):
        obj.predict(fit, x)
    spy.bad = "shape"
    with pytest.raises(ValueError, match="SHAPE"):
        obj.predict(obj.FittedObjective("PAIRWISE_LINEAR", spy, {}), x)


@pytest.fixture(scope="module")
def actual_pred():
    # Source-only reuse bootstrap; no experiment input or outputs.
    return obj._predictors(None)


def test_pairwise_loss_is_row_equivalent_and_all_ties_zero(actual_pred):
    import torch
    dates = pd.to_datetime(["2024-01-02"]*3 + ["2024-01-03"])
    plan = obj.pair_plan(dates)
    score = torch.zeros(4, requires_grad=True)
    target = torch.tensor([1., 2., 3., 7.])
    expected = np.log(2) * 3/4
    loss = obj.pairwise_loss(score, target, plan)
    assert float(loss.detach()) == pytest.approx(expected)
    tie_loss = obj.pairwise_loss(score, torch.ones(4), plan)
    assert float(tie_loss.detach()) == 0
    tie_loss.backward()
    assert torch.equal(score.grad, torch.zeros(4))


def test_listwise_zero_group_retained_and_row_weighting(actual_pred):
    import torch
    score = torch.tensor([0., 1., 2., 3., 4.], requires_grad=True)
    labels = torch.tensor([1., 0., 1., 0., 0.])
    groups = [np.arange(3), np.arange(3, 5)]
    expected = -(torch.log_softmax(score[:3], 0)[[0, 2]].mean()) * 3/5
    loss = obj.listwise_loss(score, labels, groups)
    assert float(loss.detach()) == pytest.approx(float(expected.detach()))
    loss.backward()
    assert torch.equal(score.grad[3:], torch.zeros(2))
    zero = obj.listwise_loss(score, torch.zeros(5), groups)
    assert float(zero.detach()) == 0


def test_whole_group_batching_never_splits():
    groups = [np.arange(300), np.arange(300, 600), np.arange(600, 1700), np.arange(1700, 1703)]
    batches = list(obj._group_batches(groups, [0, 1, 2, 3]))
    assert [sum(map(len, b)) for b in batches] == [300, 300, 1100, 3]
    assert [id(g) for b in batches for g in b] == [id(g) for g in groups]


def test_actual_small_synthetic_mlp_fixed_epochs_and_joblib_roundtrip(actual_pred, tmp_path):
    import joblib
    rng = np.random.default_rng(123)
    x = rng.normal(size=(48, 32))
    y = rng.normal(size=48)
    dates = pd.to_datetime(["2024-01-02"]*24 + ["2024-01-03"]*24)
    boundary = np.tile([0., 1.], 24)
    entered = []
    fit = obj.fit("BOUNDARY_MLP", x, y, dates, boundary, runtime=actual_pred, on_fit_call=entered.append)
    assert entered == [dict(operation="estimator_fit", role="BOUNDARY_MLP")]
    assert fit.metadata["epochs"] == 10 and fit.metadata["updates"] == 10
    assert fit.metadata["target_stat_estimation"] == 0
    assert fit.metadata["training_rows"] == 48
    score = obj.predict(fit, x)
    path = tmp_path / "synthetic_weights.joblib"
    joblib.dump(fit, path)
    loaded = joblib.load(path)
    assert np.array_equal(score, obj.predict(loaded, x))
    assert loaded.estimator.architecture == "MLP"


def test_fit_telemetry_constructor_failure_zero_and_fit_exception_one(pred, rows, monkeypatch):
    entered = []
    def constructor_failure(*args):
        raise RuntimeError("Synthetic constructor failure")
    monkeypatch.setattr(obj, "_native_factory", constructor_failure)
    with pytest.raises(RuntimeError, match="constructor"):
        obj.fit("BOUNDARY_RF", *rows, runtime=pred, on_fit_call=entered.append)
    assert entered == []
    spy = SpyEstimator()
    def fit_failure(x, y, **kwargs):
        spy.calls.append((x, y, kwargs))
        raise RuntimeError("Synthetic fit failure")
    spy.fit = fit_failure
    monkeypatch.setattr(obj, "_native_factory", lambda *args: spy)
    with pytest.raises(RuntimeError, match="fit failure"):
        obj.fit("BOUNDARY_RF", *rows, runtime=pred, on_fit_call=entered.append)
    assert entered == [dict(operation="estimator_fit", role="BOUNDARY_RF")]
    assert len(spy.calls) == 1


@pytest.mark.parametrize("role", [r for r in obj.ROLE_IDS if r not in (
    "BOUNDARY_MLP", "PAIRWISE_MLP", "PAIRWISE_RESNET", "PAIRWISE_FT",
    "LISTWISE_MLP", "LISTWISE_RESNET", "LISTWISE_FT")])
def test_real_native_constructors_preserve_capacity_no_fit(actual_pred, role):
    estimator = obj._native_factory(role, actual_pred)
    params = estimator.get_params()
    if role == "PAIRWISE_LINEAR":
        assert params["fit_intercept"] is False and params["C"] == .3
    if role.startswith("RANK"):
        expected = obj.role_specs()[role]["native_params"]
        assert all(params[key] == value for key, value in expected.items())
    if role.endswith(("RF", "EXTRA", "XGB")) or role == "RANK_XGB_NDCG":
        assert params["n_estimators"] == 64 and params["max_depth"] == 3


@pytest.mark.parametrize("role", ["RANK_XGB_NDCG", "RANK_LGB_XENDCG", "RANK_CAT_YETIRANK"])
def test_real_tiny_synthetic_native_objective_smoke(actual_pred, role):
    rng = np.random.default_rng(321)
    x = rng.normal(size=(24, 32))
    y = rng.normal(size=24)
    dates = pd.to_datetime(["2024-01-02"]*12 + ["2024-01-03"]*12)
    boundary = np.tile([0., 1.], 12)
    entered = []
    fitted = obj.fit(role, x, y, dates, boundary, runtime=actual_pred,
                     on_fit_call=entered.append)
    assert entered == [dict(operation="estimator_fit", role=role)]
    assert fitted.metadata["backend"]["version"]
    assert fitted.metadata["estimator_fit_calls"] == 1
    assert np.isfinite(obj.predict(fitted, x)).all()


@pytest.mark.parametrize("role", ["PAIRWISE_MLP", "LISTWISE_MLP"])
def test_actual_small_synthetic_neural_loss_branches_preserve_empty_groups(actual_pred, role, tmp_path):
    import joblib
    rng = np.random.default_rng(456)
    x = rng.normal(size=(49, 32))
    y = np.concatenate([np.ones(24), rng.normal(size=24), [7.]])
    dates = pd.to_datetime(["2024-01-02"]*24 + ["2024-01-03"]*24 + ["2024-01-04"])
    boundary = np.concatenate([np.tile([0., 1.], 12), np.zeros(25)])
    entered = []
    fitted = obj.fit(role, x, y, dates, boundary, runtime=actual_pred,
                     on_fit_call=entered.append)
    assert entered == [dict(operation="estimator_fit", role=role)]
    assert fitted.metadata["epochs"] == 10 and fitted.metadata["training_rows"] == 49
    assert fitted.metadata["singleton_group_rows"] == 1
    if role == "LISTWISE_MLP":
        assert fitted.metadata["listwise_zero_positive_groups"] == 2
        assert isinstance(fitted.metadata["listwise_zero_positive_groups"], int)
    else:
        assert fitted.metadata["tied_pairs"] >= 96
        assert fitted.metadata["no_partner_rows"] == 1
        assert fitted.metadata["external_rows_dropped"] == 0
    score = obj.predict(fitted, x)
    assert np.isfinite(score).all() and score.shape == (49,)
    path = tmp_path / "synthetic_neural_objective.joblib"
    joblib.dump(fitted, path)
    assert np.array_equal(score, obj.predict(joblib.load(path), x))
