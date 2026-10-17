"""Synthetic C12 component/scaler-weight tests, without production readers.

Only estimator spies, artificial complete 20x10 pair grids and two tiny neural
probes are used. No old result/model, provider or real 2026 input is loaded.
"""
from types import SimpleNamespace
import copy
import json
import warnings
import joblib
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_boundary_estimators as est
from scripts.research.a2.training import selector_algorithm_objectives as obj


class SpyEstimator:
    def __init__(self, **params):
        self.params = params
        self.calls = []
        self.classes_ = np.array([0, 1])
        self.fail = False
        self.warn = False
    def set_params(self, **params):
        self.params.update(params)
        return self
    def fit(self, x, y, **kwargs):
        self.calls.append((x.copy(), y.copy(), copy.deepcopy(kwargs)))
        if self.warn:
            from sklearn.exceptions import ConvergenceWarning
            warnings.warn("Synthetic unresolved convergence", ConvergenceWarning)
        if self.fail: raise RuntimeError("SYNTHETIC_ONE_CALL_FAILURE")
        return self
    def predict(self, x): return np.full(len(x), .0125)
    def predict_proba(self, x): return np.tile([.25, .75], (len(x), 1))


@pytest.fixture
def runtime(monkeypatch):
    native = dict(
        logistic=dict(C=.3, max_iter=400, solver="lbfgs", random_state=est.SEEDS[0], convergence_extension_max_iter=1200),
        ridge=dict(alpha=100., solver="lsqr", tol=1e-6),
        huber=dict(epsilon=1.35, alpha=1e-4, max_iter=500, tol=1e-5, convergence_extension_max_iter=2000),
        hgb=copy.deepcopy(obj.role_specs()["BOUNDARY_HGB"]["capacity"]),
        xgb=copy.deepcopy(obj.role_specs()["BOUNDARY_XGB"]["capacity"]),
        cat=copy.deepcopy(obj.role_specs()["BOUNDARY_CAT"]["capacity"]))
    models = []
    def maker(name, quantile=None):
        spec = copy.deepcopy(native["hgb" if name == "hgb_q" else name])
        spec.pop("convergence_extension_max_iter", None)
        if name == "hgb_q": spec.update(loss="quantile", quantile=quantile)
        result = SpyEstimator(**spec); models.append(result)
        return result
    pred = SimpleNamespace(hyperparameters=lambda name: copy.deepcopy(native[name]),
                           _make_estimator=maker, made=models, native=native)
    monkeypatch.setattr(obj, "_version_for", lambda model: dict(module="SYNTHETIC_SPY", version="0", origin="NO_DATA"))
    return pred


@pytest.fixture
def rows():
    dates, challenger, incumbent = [], [], []
    for date in ("2021-04-01", "2021-04-05"):
        for e in range(20):
            for i in range(10):
                dates.append(date); challenger.append(f"E{e:02d}"); incumbent.append(f"I{i:02d}")
    x = np.random.default_rng(17).normal(size=(len(dates), est.FEATURE_COUNT))
    y = np.linspace(-.03, .05, len(dates)); y[0] = 0.
    return x, y, pd.DatetimeIndex(dates), np.array(challenger), np.array(incumbent)


def test_weight_hierarchy_has_date_mass_one_not_mean_one(rows):
    _, _, dates, challenger, incumbent = rows
    weights = est.pair_weights(dates, challenger, incumbent)
    assert weights.sum() == pytest.approx(2.)
    np.testing.assert_allclose(weights, .005)
    frame = pd.DataFrame(dict(date=dates, challenger=challenger, incumbent=incumbent, weight=weights))
    np.testing.assert_allclose(frame.groupby("date").weight.sum(), 1.)
    np.testing.assert_allclose(frame.groupby(["date", "challenger"]).weight.sum(), .05)
    np.testing.assert_allclose(frame.groupby(["date", "incumbent"]).weight.sum(), .1)


@pytest.mark.parametrize("mode", ["one_pair_missing", "duplicate_pair", "uid_overlap", "future_clock", "null_clock"])
def test_pair_validation_does_not_drop_or_substitute(rows, mode):
    _, _, dates, challenger, incumbent = rows
    dates, challenger, incumbent = dates.copy(), challenger.copy(), incumbent.copy()
    if mode == "one_pair_missing": dates, challenger, incumbent = dates[:-1], challenger[:-1], incumbent[:-1]
    elif mode == "duplicate_pair": incumbent[1] = incumbent[0]
    elif mode == "uid_overlap": challenger[:] = ["I" + u[1:] for u in challenger]
    elif mode == "future_clock": dates = pd.DatetimeIndex(["2026-01-02"] * len(dates))
    else: dates = pd.DatetimeIndex([None] + list(dates[1:]))
    with pytest.raises(ValueError): est.pair_weights(dates, challenger, incumbent)


def test_capacity_native_parameters_and_only_three_mechanical_tiers(runtime):
    specs = est.capacity_specs(runtime)
    assert tuple(specs) == ("LOGIT", "RIDGE", "HUBER", "HGB", "XGB", "CAT", "QUANTILE_HGB", "MLP", "MULTITASK_MLP")
    assert set(specs) == set(est.PARADIGMS)
    for family in est.PARADIGMS: assert tuple(specs[family]) == est.CAPACITIES
    np.testing.assert_allclose([specs["LOGIT"][c]["C"] for c in est.CAPACITIES], [.03, .3, 3.])
    np.testing.assert_allclose([specs["RIDGE"][c]["alpha"] for c in est.CAPACITIES], [1000., 100., 10.])
    np.testing.assert_allclose([specs["HUBER"][c]["alpha"] for c in est.CAPACITIES], [1e-3, 1e-4, 1e-5])
    for family, changed in (("LOGIT", {"C"}), ("RIDGE", {"alpha"}), ("HUBER", {"alpha"})):
        low = specs[family]["LOW"]
        assert "convergence_extension_max_iter" not in low
        for c in ("MID", "HIGH"):
            assert {k for k in low if low[k] != specs[family][c][k]} == changed
    for c, rounds, depth, leaves, width, epochs in zip(est.CAPACITIES, (64,128,256), (3,4,5), (15,31,63), (32,64,128), (10,20,30)):
        for family in ("HGB", "QUANTILE_HGB"):
            assert (specs[family][c]["max_iter"], specs[family][c]["max_depth"], specs[family][c]["max_leaf_nodes"]) == (rounds,depth,leaves)
        assert (specs["XGB"][c]["n_estimators"], specs["XGB"][c]["max_depth"]) == (rounds,depth)
        assert (specs["CAT"][c]["iterations"], specs["CAT"][c]["depth"]) == (rounds,depth)
        for family in ("MLP", "MULTITASK_MLP"):
            assert (specs[family][c]["hidden"], specs[family][c]["epochs"]) == (width,epochs)
            assert specs[family][c]["target_standardization"] == "NONE"
    specs["HGB"]["LOW"]["max_depth"] = 100
    assert runtime.native["hgb"]["max_depth"] == 3
    json.dumps(specs, allow_nan=False)


def test_default_runtime_loader_is_never_used(monkeypatch):
    monkeypatch.setattr(obj, "_predictors", lambda *a: pytest.fail("Default retained loader reached"))
    with pytest.raises(ValueError, match="QUALIFIED_NATIVE_RUNTIME"):
        est.capacity_specs(None)


@pytest.mark.parametrize("paradigm", ["LOGIT", "RIDGE", "HUBER", "HGB", "XGB", "CAT", "QUANTILE_HGB"])
def test_single_native_fit_keeps_exact_weights_and_component_callback(runtime, rows, paradigm):
    x, y, dates, challenger, incumbent = rows
    calls = []
    seed = est.SEEDS[1] if paradigm == "CAT" else est.SEEDS[0]
    q = .1 if paradigm == "QUANTILE_HGB" else None
    fitted = est.fit(paradigm, x, y, dates, challenger, incumbent, capacity="MID", runtime=runtime,
                     seed=seed, quantile=q, on_fit_call=calls.append)
    model = fitted.estimator
    assert len(model.calls) == len(calls) == 1
    np.testing.assert_array_equal(model.calls[0][0], x)
    np.testing.assert_array_equal(model.calls[0][1], (y > 0).astype(int) if paradigm == "LOGIT" else y)
    np.testing.assert_array_equal(model.calls[0][2]["sample_weight"], est.pair_weights(dates, challenger, incumbent))
    assert calls[0] == dict(operation="estimator_fit", paradigm=paradigm, capacity="MID", seed=seed, quantile=q)
    assert fitted.metadata["row_weight_sum"] == pytest.approx(2.)
    assert fitted.metadata["external_rows_dropped"] == fitted.metadata["scaler_fit_calls"] == fitted.metadata["scientific_retries"] == 0
    assert fitted.metadata["estimator_fit_calls"] == 1
    if paradigm == "CAT": assert model.params["random_seed"] == fitted.metadata["spec"]["random_seed"] == seed
    if paradigm == "QUANTILE_HGB": assert model.params["loss"] == "quantile" and model.params["quantile"] == q
    np.testing.assert_array_equal(est.predict(fitted,x), np.full(len(x), .75 if paradigm=="LOGIT" else .0125))


@pytest.mark.parametrize("mode", ["unknown_family", "unknown_capacity", "extra_seed", "extra_quantile", "missing_quantile", "nan_y", "wrong_multitask", "nan_x", "missing_pair"])
def test_bad_contract_rejected_before_backend(runtime, rows, mode):
    x, y, dates, challenger, incumbent = rows
    x, y = x.copy(), y.copy()
    kwargs=dict(paradigm="RIDGE", capacity="LOW", seed=est.SEEDS[0], quantile=None)
    if mode=="unknown_family": kwargs["paradigm"]="TRANSFORMER"
    elif mode=="unknown_capacity": kwargs["capacity"]="ULTRA"
    elif mode=="extra_seed": kwargs["seed"]=est.SEEDS[1]
    elif mode=="extra_quantile": kwargs["quantile"]=.1
    elif mode=="missing_quantile": kwargs["paradigm"]="QUANTILE_HGB"
    elif mode=="nan_y": y[-1]=np.nan
    elif mode=="wrong_multitask": kwargs["paradigm"]="MULTITASK_MLP"
    elif mode=="nan_x": x[-1,0]=np.nan
    else: x,y,dates,challenger,incumbent=x[:-1],y[:-1],dates[:-1],challenger[:-1],incumbent[:-1]
    calls=[]
    with pytest.raises(ValueError):
        est.fit(X_scaled=x,y=y,dates=dates,challenger_uids=challenger,incumbent_uids=incumbent,
                runtime=runtime,on_fit_call=calls.append,**kwargs)
    assert calls==[] and runtime.made==[]


@pytest.mark.parametrize("failure", ["raise", "convergence_warning"])
def test_failed_native_fit_is_charged_once_never_continued(runtime, rows, failure):
    original=runtime._make_estimator
    def make(name, quantile=None):
        model=original(name,quantile);model.fail=failure=="raise";model.warn=failure=="convergence_warning"
        return model
    runtime._make_estimator=make
    calls=[]
    with pytest.raises(RuntimeError,match="SYNTHETIC_ONE_CALL_FAILURE|CONVERGENCE"):
        est.fit("HUBER",*rows,runtime=runtime,on_fit_call=calls.append)
    assert len(calls)==1 and len(runtime.made)==1 and len(runtime.made[0].calls)==1


def test_ridge_absolute_weight_regularization_matches_closed_form(runtime, rows):
    from sklearn.linear_model import Ridge
    x,y,dates,challenger,incumbent=rows
    runtime._make_estimator=lambda name: Ridge(alpha=100.,solver="lsqr",tol=1e-9)
    fitted=est.fit("RIDGE",x,y,dates,challenger,incumbent,capacity="MID",runtime=runtime)
    weights=est.pair_weights(dates,challenger,incumbent)
    mean_x=np.average(x,axis=0,weights=weights);mean_y=np.average(y,weights=weights)
    xc=x-mean_x;yc=y-mean_y
    expected=np.linalg.solve(xc.T@(xc*weights[:,None])+100*np.eye(est.FEATURE_COUNT),xc.T@(weights*yc))
    np.testing.assert_allclose(fitted.estimator.coef_,expected,atol=1e-7,rtol=1e-5)
    assert fitted.estimator.alpha==100.


@pytest.mark.parametrize("paradigm", ["CAT", "MLP", "MULTITASK_MLP", "QUANTILE_HGB"])
def test_all_required_seed_or_quantile_components_no_winner_selection(paradigm):
    keys=est.QUANTILES if paradigm=="QUANTILE_HGB" else est.SEEDS
    shape=(5,4) if paradigm=="MULTITASK_MLP" else (5,)
    components={k:np.full(shape,float(i+1)) for i,k in enumerate(keys)}
    combined=est.combine_predictions(paradigm,components)
    if paradigm=="QUANTILE_HGB": np.testing.assert_array_equal(combined,np.tile([1.,2.,3.],(5,1)))
    else: np.testing.assert_array_equal(combined,np.full(5,2.))
    components.pop(keys[-1])
    with pytest.raises(ValueError,match="ALL_PREDECLARED_COMPONENTS"):
        est.combine_predictions(paradigm,components)


def test_multitask_fixed_equal_horizon_and_equal_seed_mean():
    matrices={seed:np.tile([1.,4.,8.,19.],(2,1))+offset for seed,offset in zip(est.SEEDS,[0.,2.,4.])}
    np.testing.assert_array_equal(est.combine_predictions("MULTITASK_MLP",matrices),[10.,10.])


def test_quantile_crossing_is_retained_without_reordering_or_fallback():
    result=est.combine_predictions("QUANTILE_HGB",{.1:np.array([.02]),.5:np.array([-.01]),.9:np.array([.01])})
    np.testing.assert_array_equal(result,[[.02,-.01,.01]])


def test_multitask_weighted_loss_is_date_mean_and_equal_task_mean(rows):
    torch=pytest.importorskip("torch")
    _,_,dates,challenger,incumbent=rows
    weights=torch.tensor(est.pair_weights(dates,challenger,incumbent),dtype=torch.float64)
    values=torch.arange(len(dates)*4,dtype=torch.float64).reshape(len(dates),4)/1000
    target=torch.zeros_like(values)
    actual=est.weighted_edge_loss(values,target,weights,training_rows=len(dates),training_date_mass=2.)
    expected=(values[:200].square().mean()+values[200:].square().mean())/2
    torch.testing.assert_close(actual,expected,rtol=1e-12,atol=1e-12)


@pytest.mark.parametrize("paradigm", ["MLP", "MULTITASK_MLP"])
def test_small_neural_component_seed_dimensions_final_epoch_and_persistence(runtime, rows, tmp_path, paradigm):
    pytest.importorskip("torch")
    x,y,dates,challenger,incumbent=rows
    x,y,dates,challenger,incumbent=x[:200],y[:200],dates[:200],challenger[:200],incumbent[:200]
    if paradigm=="MULTITASK_MLP": y=np.column_stack([y,y*2,y*3,y*4])
    calls=[]
    fitted=est.fit(paradigm,x,y,dates,challenger,incumbent,runtime=runtime,seed=est.SEEDS[2],on_fit_call=calls.append)
    assert len(calls)==1 and fitted.metadata["updates"]==fitted.metadata["update_budget"]==10
    assert fitted.estimator[0].in_features==114 and fitted.estimator[0].out_features==32
    assert fitted.estimator[-1].out_features==(4 if paradigm=="MULTITASK_MLP" else 1)
    assert fitted.metadata["spec"]["seed"]==fitted.seed==est.SEEDS[2]
    before=est.predict(fitted,x)
    path=tmp_path/"synthetic_component.joblib";joblib.dump(fitted,path)
    after=est.predict(joblib.load(path),x)
    np.testing.assert_array_equal(before,after)
    assert after.shape==((200,4) if paradigm=="MULTITASK_MLP" else (200,))
