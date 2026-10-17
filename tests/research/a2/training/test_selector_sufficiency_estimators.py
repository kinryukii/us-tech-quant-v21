"""C10 consumer validation uses only synthetic arrays and estimator spies.

No production fit, archive reader, old-result read or provider call is used.
Two explicitly test-only neural probes use seven artificial rows and one epoch.
"""
from types import SimpleNamespace
import copy
import json

import joblib
import numpy as np
import pandas as pd
import pytest
import torch

from scripts.research.a2.training import selector_algorithm_objectives as obj
from scripts.research.a2.training import selector_sufficiency_estimators as est


class SpyEstimator:
    def __init__(self, **params):
        self.params = params
        self.calls = []
        self.fail = False

    def get_params(self, deep=False):
        return self.params.copy()

    def set_params(self, **params):
        self.params.update(params)
        return self

    def fit(self, x, y, **kwargs):
        self.calls.append((x.copy(), y.copy(), copy.deepcopy(kwargs)))
        if self.fail:
            raise RuntimeError("SYNTHETIC_BACKEND_FAILURE")
        return self

    def predict(self, x):
        return np.zeros(len(x))

    def predict_proba(self, x):
        return np.tile([.25, .75], (len(x), 1))


@pytest.fixture
def runtime(monkeypatch):
    hgb = dict(max_iter=64, max_depth=3, max_leaf_nodes=15, min_samples_leaf=100,
               learning_rate=.05, l2_regularization=1., early_stopping=False, random_state=obj.SEED)
    xgb = dict(n_estimators=64, max_depth=3, min_child_weight=20, learning_rate=.05,
               subsample=1., colsample_bytree=1., reg_lambda=1., tree_method="hist",
               n_jobs=2, random_state=obj.SEED, verbosity=0, missing=np.nan)
    def maker(name):
        return SpyEstimator(**(hgb if name == "hgb" else dict(alpha=100., solver="lsqr", tol=1e-6)))
    def native(role, pred):
        return SpyEstimator(**(hgb if role == "BOUNDARY_HGB" else
                               {**xgb, **obj.role_specs()[role]["native_params"]}))
    rank_calls = []
    def rank(x, y, clock):
        rank_calls.append((x.copy(), y.copy(), clock.copy()))
        order = np.arange(len(x))[::-1]
        # A sentinel return verifies delegation, rather than mirroring owner binning.
        return x[order], np.arange(len(y)) % 5, np.array([2, 5])
    pred = SimpleNamespace(_make_estimator=maker, rank_training_data=rank,
                           rank_calls=rank_calls, TREE_HGB=hgb, TREE_XGB=xgb)
    monkeypatch.setattr(obj, "_native_factory", native)
    monkeypatch.setattr(obj, "_version_for", lambda model: dict(module="SYNTHETIC_SPY", version="0", origin="NO_DATA"))
    return pred


@pytest.fixture
def rows():
    x = np.arange(7 * 32, dtype=float).reshape(7, 32) / 100
    y = np.array([.01, .03, -.02, .01, .01, .05, -.01])
    dates = pd.DatetimeIndex(["2022-04-04"] * 2 + ["2022-04-05"] * 5)
    boundary = np.array([0., 1., 0., 1., 0., 1., 0.])
    return x, y, dates, boundary


def test_date_weights_mean_one_equal_date_mass(rows):
    _, _, dates, _ = rows
    weight = est.date_weights(dates)
    np.testing.assert_allclose(weight.sum(), len(dates))
    np.testing.assert_allclose(weight[:2].sum(), weight[2:].sum())
    np.testing.assert_allclose(weight, [7 / 4] * 2 + [7 / 10] * 5)
    with pytest.raises(ValueError, match="CLOCK"):
        est.date_weights([])


def test_capacity_only_declared_mechanical_increases(runtime):
    specs = est.capacity_specs(runtime)
    assert tuple(specs["RIDGE"]) == ("LOW",)
    assert specs["POINT_HGB"]["LOW"] == runtime.TREE_HGB
    assert specs["BOUNDARY_HGB"]["LOW"] == runtime.TREE_HGB
    assert specs["RANK_XGB_NDCG"]["LOW"]["objective"] == "rank:ndcg"
    assert specs["RANK_XGB_NDCG"]["LOW"]["lambdarank_num_pair_per_sample"] == 4
    for role in ("POINT_HGB", "BOUNDARY_HGB", "RANK_XGB_NDCG"):
        low = specs[role]["LOW"]
        for level in ("MEDIUM", "HIGH"):
            changed = {key for key in low if low[key] != specs[role][level][key]}
            expected = {"n_estimators", "max_depth"} if role.startswith("RANK") else {"max_iter", "max_depth", "max_leaf_nodes"}
            assert changed == expected
    for role in ("PAIRWISE_MLP", "LISTWISE_MLP"):
        assert specs[role]["LOW"] == obj.role_specs()[role]["capacity"]
        assert [(specs[role][level]["hidden"], specs[role][level]["epochs"]) for level in est.CAPACITIES] == [(32, 10), (64, 20), (128, 30)]
    specs["POINT_HGB"]["LOW"]["max_depth"] = 999
    assert runtime.TREE_HGB["max_depth"] == 3


@pytest.mark.parametrize("role", ["POINT_HGB", "BOUNDARY_HGB", "RIDGE"])
def test_native_consumers_full_date_weight_and_single_callback(runtime, rows, role):
    x, y, dates, boundary = rows
    calls = []
    fitted = est.fit(role, x, y, dates, boundary, runtime=runtime, on_fit_call=calls.append)
    assert len(fitted.estimator.calls) == 1 and len(calls) == 1
    actual_x, actual_y, kwargs = fitted.estimator.calls[0]
    np.testing.assert_array_equal(actual_x, x)
    np.testing.assert_array_equal(actual_y, boundary if role == "BOUNDARY_HGB" else y)
    np.testing.assert_allclose(kwargs["sample_weight"], est.date_weights(dates))
    assert calls == [dict(operation="estimator_fit", role=role, paradigm=role, capacity="LOW")]
    assert fitted.metadata["training_rows"] == 7 and fitted.metadata["groups"] == 2
    assert fitted.metadata["estimator_fit_calls"] == 1
    assert fitted.metadata["scaler_fit_calls"] == 0
    assert fitted.metadata["target_stat_estimation"] == 0
    assert fitted.metadata["scientific_retries"] == 0
    np.testing.assert_array_equal(est.predict(fitted, x), np.full(len(x), .75) if role == "BOUNDARY_HGB" else np.zeros(len(x)))


def test_rank_delegates_original_transform_and_unit_query_weights(runtime, rows):
    x, y, dates, boundary = rows
    calls = []
    fitted = est.fit("RANK_XGB_NDCG", x, y, dates, boundary, capacity="HIGH", runtime=runtime, on_fit_call=calls.append)
    assert len(runtime.rank_calls) == 1
    passed_x, passed_y, passed_clock = runtime.rank_calls[0]
    np.testing.assert_array_equal(passed_x, x)
    np.testing.assert_array_equal(passed_y, y)
    assert passed_clock.equals(dates)
    fit_x, fit_y, kwargs = fitted.estimator.calls[0]
    np.testing.assert_array_equal(fit_x, x[::-1])
    np.testing.assert_array_equal(fit_y, np.arange(7) % 5)
    np.testing.assert_array_equal(kwargs["group"], [2, 5])
    np.testing.assert_array_equal(kwargs["sample_weight"], [1., 1.])
    assert len(kwargs["sample_weight"]) != len(x)
    assert fitted.estimator.params["n_estimators"] == 256
    assert fitted.estimator.params["max_depth"] == 5
    assert fitted.estimator.params["objective"] == "rank:ndcg"
    assert len(calls) == 1


@pytest.mark.parametrize("role,capacity", [("RIDGE", "MEDIUM"), ("POINT_HGB", "ULTRA"), ("POINT_XGB", "LOW")])
def test_rejects_unregistered_capacity_or_role_before_fit(runtime, rows, role, capacity):
    calls = []
    with pytest.raises(ValueError):
        est.fit(role, *rows, capacity=capacity, runtime=runtime, on_fit_call=calls.append)
    assert calls == []


def test_2026_training_clock_rejected_without_backend_entry(runtime, rows):
    x, y, _, boundary = rows
    calls = []
    with pytest.raises(ValueError, match="PRE2026"):
        est.fit("POINT_HGB", x, y, ["2026-01-02"] * len(y), boundary, runtime=runtime, on_fit_call=calls.append)
    assert calls == []


def test_failed_backend_is_not_retried(runtime, rows, monkeypatch):
    bad = SpyEstimator(max_iter=64)
    bad.fail = True
    real_native = est._native
    monkeypatch.setattr(est, "_native", lambda role, pred: bad if role == "POINT_HGB" else real_native(role, pred))
    calls = []
    with pytest.raises(RuntimeError, match="SYNTHETIC_BACKEND_FAILURE"):
        est.fit("POINT_HGB", *rows, runtime=runtime, on_fit_call=calls.append)
    assert len(bad.calls) == 1 and len(calls) == 1


def test_pair_loss_unit_weights_matches_owner_value_and_gradient_with_ties_singleton():
    dates = pd.DatetimeIndex(["2020-01-02"] * 3 + ["2020-01-03"])
    plan = obj.pair_plan(dates)
    target = torch.tensor([.1, .1, .3, -.1], dtype=torch.float64)
    left = torch.tensor([.4, -.2, .7, .9], dtype=torch.float64, requires_grad=True)
    right = left.detach().clone().requires_grad_()
    original = obj.pairwise_loss(left, target, plan)
    weighted = est.weighted_pairwise_loss(right, target, plan)
    original.backward()
    weighted.backward()
    torch.testing.assert_close(original, weighted, rtol=0, atol=0)
    torch.testing.assert_close(left.grad, right.grad, rtol=0, atol=0)
    assert left.grad[-1] == 0


def test_pair_date_weight_equals_mean_date_owner_loss(rows):
    _, target, dates, _ = rows
    plan = obj.pair_plan(dates)
    scores = torch.tensor([.1, -.2, .3, -.4, .5, -.6, .7], dtype=torch.float64, requires_grad=True)
    yy = torch.tensor(target, dtype=torch.float64)
    expected = torch.stack([obj.pairwise_loss(scores, yy, plan, anchors=torch.tensor(g)) for g in obj.date_groups(dates)]).mean()
    actual = est.weighted_pairwise_loss(scores, yy, plan, weights=est.date_weights(dates))
    torch.testing.assert_close(actual, expected, rtol=1e-13, atol=1e-13)
    actual.backward()
    assert torch.isfinite(scores.grad).all()


@pytest.mark.parametrize("mutation,error", [("SELF", "SELF"), ("CROSS", "CROSS_DATE"), ("DUP", "DUPLICATE"), ("DROP", "PARTNER_COUNT")])
def test_cached_plan_invalid_topology_rejected_before_fit(runtime, rows, mutation, error):
    x, y, dates, boundary = rows
    plan = obj.pair_plan(dates)
    if mutation == "SELF":
        plan[0, 0] = 0
    elif mutation == "CROSS":
        plan[0, 0] = 2
    elif mutation == "DUP":
        plan[2, 1] = plan[2, 0]
    else:
        plan[2, 0] = -1
    calls = []
    with pytest.raises(ValueError, match=error):
        est.fit("PAIRWISE_MLP", x, y, dates, boundary, runtime=runtime, pair_plan=plan, on_fit_call=calls.append)
    assert calls == []


def test_listwise_equal_date_ce_keeps_zero_positive_group(rows):
    _, _, dates, boundary = rows
    groups = obj.date_groups(dates)
    scores = torch.tensor([.1, -.2, .3, -.4, .5, -.6, .7], dtype=torch.float64, requires_grad=True)
    labels = torch.tensor(boundary, dtype=torch.float64)
    expected = torch.stack([obj.listwise_loss(scores, labels, [g]) for g in groups]).mean()
    actual = est.date_balanced_listwise_loss(scores, labels, groups)
    torch.testing.assert_close(actual, expected)
    assert not torch.isclose(actual, obj.listwise_loss(scores, labels, groups))
    zero_labels = labels.clone()
    zero_labels[groups[0]] = 0
    kept = est.date_balanced_listwise_loss(scores, zero_labels, groups)
    torch.testing.assert_close(kept, obj.listwise_loss(scores, zero_labels, [groups[1]]) / 2)
    kept.backward()
    assert torch.isfinite(scores.grad).all()
    assert torch.equal(scores.grad[groups[0]], torch.zeros(2, dtype=scores.dtype))


@pytest.mark.parametrize("width,parameters", [(32, 2145), (64, 6337), (128, 20865)])
def test_actual_network_width_persists_without_legacy_loader(tmp_path, rows, width, parameters):
    x, _, _, _ = rows
    torch.manual_seed(obj.SEED)
    network = est._network(width)
    assert isinstance(network, torch.nn.Sequential)
    assert sum(p.numel() for p in network.parameters()) == parameters
    fitted = obj.FittedObjective("PAIRWISE_MLP", network, {"synthetic_only": True}, True)
    before = est.predict(fitted, x)
    destination = tmp_path / "synthetic-network.joblib"
    joblib.dump(fitted, destination)
    restored = joblib.load(destination)
    assert restored.estimator[0].out_features == width
    np.testing.assert_array_equal(est.predict(restored, x), before)


@pytest.mark.parametrize("role", ["PAIRWISE_MLP", "LISTWISE_MLP"])
def test_tiny_nonproduction_one_epoch_entry_and_update_telemetry(runtime, rows, monkeypatch, role):
    x, y, dates, boundary = rows
    specs = est.capacity_specs(runtime)
    # Explicit nonproduction test override; never written to design/source config.
    specs[role]["LOW"]["epochs"] = 1
    monkeypatch.setattr(est, "capacity_specs", lambda runtime=None: copy.deepcopy(specs))
    cached = obj.pair_plan(dates) if role == "PAIRWISE_MLP" else None
    if cached is not None:
        monkeypatch.setattr(obj, "pair_plan", lambda *args, **kwargs: pytest.fail("cached plan redrawn"))
    calls = []
    fitted = est.fit(role, x, y, dates, boundary, runtime=runtime, pair_plan=cached, on_fit_call=calls.append)
    assert len(calls) == 1
    assert fitted.metadata["epochs"] == 1 and fitted.metadata["updates"] == 1
    assert fitted.metadata["estimator_fit_calls"] == 1 and fitted.metadata["scaler_fit_calls"] == 0
    assert fitted.metadata["training_input_rows"] == 7 and fitted.metadata["external_rows_dropped"] == 0
    assert fitted.metadata["parameter_count"] == 2145
    assert np.isfinite(est.predict(fitted, x)).all()


def test_native_missing_nan_strict_json_roundtrip_and_fit(runtime, rows, monkeypatch):
    specs = est.capacity_specs(runtime)
    frozen = json.loads(json.dumps(specs, allow_nan=False))
    for level in est.CAPACITIES:
        assert frozen["RANK_XGB_NDCG"][level]["missing"] == est.NATIVE_NAN_SENTINEL
    # Exercise a consumer using only the strict-JSON roundtrip configuration.
    monkeypatch.setattr(est, "capacity_specs", lambda runtime=None: copy.deepcopy(frozen))
    fitted = est.fit("RANK_XGB_NDCG", *rows, capacity="MEDIUM", runtime=runtime)
    assert np.isnan(fitted.estimator.params["missing"])
    assert fitted.metadata["spec"]["missing"] == est.NATIVE_NAN_SENTINEL
    json.dumps(fitted.metadata, allow_nan=False)
    assert len(fitted.estimator.calls) == 1
