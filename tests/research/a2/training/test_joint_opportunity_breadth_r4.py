"""R4 pure helpers: synthetic spies/arrays only, no source data or accounts."""
from types import SimpleNamespace
import warnings
import numpy as np
import pandas as pd
import pytest
from sklearn.exceptions import ConvergenceWarning
from scripts.research.a2.training import joint_opportunity_breadth_r4 as sut


class Spy:
    def __init__(self, quantile=None, failure=False, warning=False):
        self.params = dict(random_state=sut.SEEDS[0], quantile=quantile)
        self.calls = []
        self.failure, self.warning = failure, warning

    def get_params(self, deep=False):
        return self.params.copy()

    def set_params(self, **params):
        self.params.update(params)
        return self

    def fit(self, x, y, sample_weight):
        self.calls.append((x.copy(), y.copy(), sample_weight.copy()))
        if self.failure:
            raise RuntimeError("SYNTHETIC_FIT_FAILED")
        if self.warning:
            warnings.warn("SYNTHETIC_UNRESOLVED", ConvergenceWarning)
        return self

    def predict(self, x):
        return np.full(len(x), self.params.get("quantile") or 0.)


@pytest.fixture
def rows():
    x = np.arange(7*32).reshape(7,32)/100.
    y = np.array([.01,.03,-.02,.01,.01,.8,-.5])  # deliberately exceeds old clipped target
    dates = pd.to_datetime(["2021-04-04"]*2+["2021-04-05"]*5)
    return x, y, sut.date_weights(dates), dates


def native_spy(**opts):
    created = []
    def factory(name, quantile=None):
        obj = Spy(quantile, **opts)
        created.append(obj)
        return obj
    return SimpleNamespace(estimator=factory, created=created)


def test_frozen_catalog_and_transparent_multicoordinate_budget():
    spec = sut.specs()
    assert len(spec["applicable_models"]) == 22
    assert len(spec["blocked_models"]) == 9
    assert len(sut.slot_matrix()) == 464
    cost = spec["accounting"]
    assert cost["learned_total_upper"] == 864
    assert cost["estimator_fit_calls"] == 628
    assert cost["physical_fit_events"] == 634
    assert cost["scaler_fit_calls"] == 6
    assert sut.learned_states("mlp_q") == ("shared_trunk","q10_head","q50_head","q90_head")
    assert sut.learned_states("mlp_dist") == ("joint_body","location_head","scale_head")
    assert cost["states_per_small_round"] == 81
    assert cost["states_per_large_annual_round"] == 97
    assert cost["backend_calls_per_small_round"] == 58
    assert cost["backend_calls_per_large_annual_round"] == 74


def test_all_literal_capacity_configs_are_distinct_and_seed_policy_is_fixed():
    for model in sut.applicable_models():
        configs = [sut.capacity_config(model, cap) for cap in sut.CAPACITIES]
        assert configs[0] != configs[1] != configs[2]
        assert sut.seeds(model) == (sut.SEEDS if model in sut.STOCHASTIC else sut.SEEDS[:1])
    assert sut.capacity_config("resnet","HIGH")["capacity_axis"] == "FIXED_ARCHITECTURE_OPTIMIZATION_EPOCHS"
    assert sut.capacity_config("hgb","MEDIUM")["max_iter"] == 100
    assert sut.capacity_config("hgb","MEDIUM")["early_stopping"] is False


def test_metadata_purge_and_literal_flags_precede_values():
    metadata = pd.DataFrame(dict(
        signal_date=pd.to_datetime(["2020-12-01"]*4),
        execution_date=pd.to_datetime(["2020-12-02"]*4),
        label_end_date=pd.to_datetime(["2020-12-09","2021-01-01","2020-12-09","2020-12-09"]),
        label_mature_date=pd.to_datetime(["2020-12-09","2021-01-01","2021-01-01","2020-12-09"]),
        fit_eligible=[True,True,True,1]))
    assert sut.training_mask(metadata,"2021-01-01").tolist() == [True,False,False,False]
    with pytest.raises(ValueError,match="PRE2026"):
        sut.training_mask(metadata,"2026-01-02")


def test_validation_metadata_rejects_overlap_and_unknown_cohort():
    m = pd.DataFrame(dict(signal_date=pd.to_datetime(["2021-06-20","2021-06-25","2021-07-01"]),
        execution_date=pd.to_datetime(["2021-06-21","2021-06-28","2021-07-02"]),
        label_end_date=pd.to_datetime(["2021-06-29","2021-07-05","2021-07-09"]),
        label_mature_date=pd.to_datetime(["2021-06-29","2021-07-05","2021-07-09"]),
        fit_eligible=[True]*3))
    assert sut.validation_mask(m,"INNER_2021H1").tolist() == [True,False,False]
    with pytest.raises(ValueError,match="FIXED_2021"):
        sut.validation_mask(m,"ANNUAL_2025")


def test_shared_weighted_scaler_matches_equal_date_mass(rows):
    x,y,w,clock = rows
    assert np.isclose(w[:2].sum(),w[2:].sum())
    events=[]
    scaler=sut.fit_scaler(x,w,events.append)
    np.testing.assert_allclose(scaler.mean_,np.average(x,axis=0,weights=w))
    assert events == [dict(component="SHARED_SCALER",learned_units=1,backend_calls=1)]


def test_native_fit_keeps_unclipped_target_raw_hgb_and_full_weights(rows):
    x,y,w,_=rows; native=native_spy(); events=[]
    fitted=sut.fit_model("hgb","MEDIUM",sut.SEEDS[0],x,y,w,native=native,on_fit_started=events.append)
    call=native.created[0].calls[0]
    np.testing.assert_array_equal(call[0],x)
    np.testing.assert_array_equal(call[1],y)
    np.testing.assert_array_equal(call[2],w)
    assert fitted.metadata["mapper_fits"] == fitted.metadata["uncertainty_RMS_fits"] == 0
    assert len(events)==1 and events[0]["learned_units"]==1
    scaler=sut.fit_scaler(x,w)
    with pytest.raises(ValueError,match="RAW_FEATURE"):
        sut.fit_model("hgb","LOW",sut.SEEDS[0],x,y,w,native=native,scaler=scaler)


def test_scaled_model_cannot_fit_without_exact_caller_scaler(rows):
    x,y,w,_=rows
    with pytest.raises(ValueError,match="SHARED_SCALER"):
        sut.fit_model("ridge","LOW",sut.SEEDS[0],x,y,w,native=native_spy())


def test_independent_three_quantile_heads_have_three_calls_and_units(rows):
    x,y,w,_=rows; native=native_spy(); events=[]
    fit=sut.fit_model("hgb_q","LOW",sut.SEEDS[0],x,y,w,native=native,on_fit_started=events.append)
    assert len(native.created)==len(events)==3
    assert sum(e["learned_units"] for e in events)==3
    assert [e["quantile"] for e in events] == [.1,.5,.9]
    output=fit.predict(x[:3])
    assert set(output)>= {"q10","q50","q90","native_mu","native_sigma"}


def test_blocked_target_and_unknown_seed_reject_before_numeric_access():
    class Forbidden:
        def __len__(self):
            return 7
        def __array__(self,*args,**kwargs):
            raise AssertionError("forbidden numeric read")
    for model in ("logistic","xgb_rank"):
        with pytest.raises(ValueError,match="BLOCKED_SOURCE"):
            sut.fit_model(model,"LOW",sut.SEEDS[0],Forbidden(),Forbidden(),Forbidden())
    with pytest.raises(ValueError,match="FIXED_SEED"):
        sut.fit_model("hgb","LOW",sut.SEEDS[1],Forbidden(),Forbidden(),Forbidden())


@pytest.mark.parametrize("failure,warning",[(True,False),(False,True)])
def test_failed_backend_is_retained_and_never_retried(rows,failure,warning):
    x,y,w,_=rows; native=native_spy(failure=failure,warning=warning); events=[]
    with pytest.raises((RuntimeError,sut.ScientificFitFailure)):
        sut.fit_model("hgb","LOW",sut.SEEDS[0],x,y,w,native=native,on_fit_started=events.append)
    assert len(native.created)==1 and len(native.created[0].calls)==1 and len(events)==1


def test_seed_aggregation_requires_all_fixed_members_and_keeps_total_moment():
    records={s:dict(native_mu=np.array([float(i)]),native_sigma=np.array([2.]))
             for i,s in enumerate(sut.SEEDS)}
    pooled=sut.aggregate("mlp_dist",records)
    np.testing.assert_allclose(pooled["native_mu"],[1.])
    np.testing.assert_allclose(pooled["native_sigma"]**2,[4.+2./3.])
    with pytest.raises(ValueError,match="ALL_FIXED_SEEDS"):
        sut.aggregate("mlp_dist",{sut.SEEDS[0]:records[sut.SEEDS[0]]})


def test_capacity_selection_never_reads_annual_results_and_has_fixed_tie_rule():
    records=[dict(cohort=f["id"],capacity=c,status="COMPLETE",loss=.5)
             for f in sut.INNER for c in sut.CAPACITIES]
    assert sut.select_capacity(records)=="LOW"
    with pytest.raises(ValueError,match="2021_INNER"):
        sut.select_capacity(records+[dict(cohort="ANNUAL_2025",capacity="HIGH",status="COMPLETE",loss=-10.)])


def test_invalid_validation_clock_rejected_before_target_access():
    class Forbidden:
        def __len__(self):
            return 7
        def __array__(self,*a,**k): raise AssertionError("target must remain unread")
    with pytest.raises(ValueError,match="2021_ONLY"):
        sut.validation_loss("hgb",Forbidden(),{},["2025-01-03"])


def test_native_validation_objective_keeps_2021_raw_target(rows):
    _,y,_,clock=rows
    loss=sut.validation_loss("hgb",y,dict(native_mu=np.zeros(7)),clock)
    assert np.isclose(loss,np.average(y*y,weights=sut.date_weights(clock)))


def test_actual_small_native_ridge_roundtrip_is_target_independent(rows):
    x,y,w,_=rows
    scaler=sut.fit_scaler(x,w)
    from sklearn.linear_model import Ridge
    native=SimpleNamespace(estimator=lambda *a,**k:Ridge())
    fitted=sut.fit_model("ridge","MEDIUM",sut.SEEDS[0],x,y,w,scaler=scaler,native=native)
    before=fitted.predict(x[:2])["native_mu"]
    altered=x.copy();altered[2:]+=1000
    np.testing.assert_allclose(before,fitted.predict(altered[:2])["native_mu"])


def test_joint_quantile_has_one_backend_event_four_learned_states(rows,monkeypatch):
    x,y,w,_=rows; events=[]
    spy=Spy()
    monkeypatch.setattr(sut,"make_estimator",lambda *a,**k:spy)
    fitted=sut.fit_model("mlp_q","LOW",sut.SEEDS[0],x,y,w,
                         scaler=sut.fit_scaler(x,w),on_fit_started=events.append)
    assert len(spy.calls)==1 and len(events)==1
    assert events[0]["learned_units"]==4
    assert events[0]["backend_calls"]==1
    assert fitted.metadata["learned_units"]==4


@pytest.mark.parametrize("name",["hgb","hgb_q","lgb","lgb_q"])
def test_frozen_binning_seed_threshold_requires_complete_large_annual_ensemble(name):
    assert sut.seeds(name,200000)==sut.SEEDS[:1]
    assert sut.seeds(name,200001)==sut.SEEDS
    matrix=[x for x in sut.slot_matrix() if x["model"]==name]
    for cohort,rows in sut.COHORT_ROWS.items():
        members=[x for x in matrix if x["cohort"]==cohort]
        assert {x["seed"] for x in members}==set(sut.SEEDS if rows>200000 else sut.SEEDS[:1])
        assert {x["training_metadata_rows"] for x in members}=={rows}
    fields={seed:{"native_mu":np.array([float(i)])} for i,seed in enumerate(sut.SEEDS)}
    np.testing.assert_allclose(sut.aggregate(name,fields,training_rows=200001)["native_mu"],[1.])
    with pytest.raises(ValueError,match="ALL_FIXED_SEEDS_REQUIRED"):
        sut.aggregate(name,{sut.SEEDS[0]:fields[sut.SEEDS[0]]},training_rows=200001)
    with pytest.raises(ValueError,match="BOUND_METADATA_TRAINING_ROWCOUNT_REQUIRED"):
        sut.seeds(name,-1)
