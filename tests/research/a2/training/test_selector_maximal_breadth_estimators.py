"""Synthetic-only acceptance for the C14 estimator consumer (no real inputs)."""
import copy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_maximal_breadth_estimators as m

def data():
    rng=np.random.default_rng(33)
    X=rng.normal(size=(200,216));y=np.linspace(-.02,.02,200)
    tasks=np.column_stack((.5*y,1.5*y,y,y))
    dates=np.repeat(np.datetime64("2023-07-03"),200)
    ch=np.repeat([f"C{i:02}" for i in range(20)],10)
    inc=np.tile([f"I{i:02}" for i in range(10)],20)
    return X,y,tasks,dates,ch,inc

class FakeNative:
    def __init__(self):self.params={};self.classes_=np.array([0,1])
    def set_params(self,**p):self.params.update(p);return self
    def fit(self,X,y,**kwargs):
        self.training=(X.copy(),np.array(y),copy.deepcopy(kwargs))
        self.outputs=1 if np.asarray(y).ndim==1 else np.asarray(y).shape[1]
        return self
    def predict(self,X):return np.zeros(len(X)) if self.outputs==1 else np.zeros((len(X),self.outputs))
    def decision_function(self,X):return np.zeros(len(X))
    def predict_proba(self,X):return np.tile([.4,.6],(len(X),1))

@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(m,"_native",lambda *a,**k:FakeNative())

def test_roles_and_only_declared_capacity():
    s=m.specs()
    assert len(m.PARADIGMS)==23 and set(s)==set(m.PARADIGMS)
    assert len([p for p in m.PARADIGMS if not p.startswith("MT_")])==20
    for p in s:
        assert tuple(s[p])==m.CAPACITIES
        for c in s[p]:
            assert s[p][c]["input_features"]==216
            assert s[p][c]["scientific_retry"]==0
            assert s[p][c]["target_standardization"]=="NONE"
    s["RIDGE"]["LOW"]["params"]["alpha"]=123
    assert m.specs()["RIDGE"]["LOW"]["params"]["alpha"]==1000

@pytest.mark.parametrize("role",m.PARADIGMS)
def test_component_policy(role):
    cs=m.component_specs(role)
    assert {a["seed"] for a in cs}==set(m.SEEDS if role in m.STOCHASTIC else m.SEEDS[:1])
    assert {a["quantile"] for a in cs}==set(m.QUANTILES if role=="QUANTILE_HGB" else (None,))
    assert len(cs)==(3 if role in m.STOCHASTIC or role=="QUANTILE_HGB" else 1)

@pytest.mark.parametrize("role",[p for p in m.PARADIGMS if p not in m.NEURAL])
def test_one_native_backend_call_per_component(role,fake):
    X,y,t,d,ch,inc=data();events=[]
    q=.9 if role=="QUANTILE_HGB" else None
    fit=m.fit_component(role,X,y,t,d,ch,inc,"LOW",m.SEEDS[0],q,None,events.append)
    assert len(events)==1 and fit.metadata["physical_backend_fit_calls"]==1
    assert events[0]["outputs"]==(4 if role in m.MULTITASK else 1)
    yy=fit.estimator.training[1]
    assert yy.shape==((200,4) if role in m.MULTITASK else (200,))
    result=m.predict(fit,X)
    if role in m.MARGINS:
        assert set(result)=={"margin"} and "prob" not in result and "point" not in result
    elif role in m.MULTITASK:assert result["tasks"].shape==(200,4)
    if role=="PAIRWISE_RANKER":
        assert fit.estimator.training[2]["sample_weight"].shape==(1,)
        assert fit.estimator.training[2]["group"]==[200]
    else:assert np.allclose(fit.estimator.training[2]["sample_weight"],.005)
    assert all(a.shape[0]==0 for a in m.predict(fit,X[:0]).values())

@pytest.mark.parametrize("bad",[20260931,1])
def test_unregistered_seed_rejected(bad):
    X,y,t,d,ch,inc=data()
    with pytest.raises(ValueError,match="FROZEN_CAPACITY"):
        m.fit_component("RF",X,y,t,d,ch,inc,"LOW",bad)

def test_date_weight_rescale_rejected():
    X,y,*_=data()
    with pytest.raises(ValueError,match="NO_RESCALE"):
        m.fit("RIDGE","LOW",m.SEEDS[0],X,y,np.ones(200),[np.arange(200)])

def test_future_clock_before_backend(fake):
    X,y,t,d,ch,inc=data();events=[]
    d=np.repeat(np.datetime64("2026-01-02"),200)
    with pytest.raises(ValueError,match="PRE2026"):
        m.fit_component("RIDGE",X,y,t,d,ch,inc,"LOW",m.SEEDS[0],on_fit=events.append)
    assert events==[]

@pytest.mark.parametrize("failure",["order","duplicate","unknown","overlap"])
def test_pair_geometry_before_backend(failure,fake):
    X,y,t,d,ch,inc=data();events=[]
    if failure=="order":ch=np.roll(ch,1)
    elif failure=="duplicate":inc[1]=inc[0]
    elif failure=="unknown":ch[0]="UNKNOWN"
    else:inc[0]=ch[0]
    with pytest.raises(ValueError):
        m.fit_component("RIDGE",X,y,t,d,ch,inc,"LOW",m.SEEDS[0],on_fit=events.append)
    assert not events

@pytest.mark.parametrize("failure",["X","y","tasks","group"])
def test_finite_and_complete_inputs(failure,fake):
    X,y,t,d,ch,inc=data()
    if failure=="X":X[0,0]=np.nan
    elif failure=="y":y[0]=np.nan
    elif failure=="tasks":t=t[:,:3]
    else:d[0]=np.datetime64("2023-07-04")
    role="MT_RIDGE" if failure=="tasks" else "RIDGE"
    with pytest.raises(ValueError):m.fit_component(role,X,y,t,d,ch,inc,"LOW",m.SEEDS[0])

def test_quantiles_are_three_separate_fits_and_no_reordering(fake):
    X,y,t,d,ch,inc=data();calls=[];parts={}
    for q in m.QUANTILES:
        f=m.fit_component("QUANTILE_HGB",X,y,t,d,ch,inc,"LOW",m.SEEDS[0],q,on_fit=calls.append)
        parts[(m.SEEDS[0],q)]=m.predict(f,X)
    assert len(calls)==3
    out=m.combine_predictions("QUANTILE_HGB",parts)
    assert set(out)=={"q10","q50","q90"}
    with pytest.raises(ValueError,match="ALL_FROZEN"):
        m.combine_predictions("QUANTILE_HGB",{k:v for k,v in parts.items() if k[1]!=.9})

def test_gaussian_mixture_total_variance_probability_and_quantiles():
    parts={}
    for s,mu in zip(m.SEEDS,(-2.,0.,2.)):
        parts[(s,None)]=m._normal(np.array([mu]),np.array([1.]))
    out=m.combine_predictions("GAUSSIAN_MLP",parts)
    assert out["mu"]==pytest.approx([0])
    assert out["between_variance"]==pytest.approx([8/3])
    assert out["within_variance"]==pytest.approx([1])
    assert out["sigma"]==pytest.approx([np.sqrt(11/3)])
    assert out["prob"]==pytest.approx([.5])
    assert out["q50"]==pytest.approx([0],abs=1e-12)
    assert out["q10"]==pytest.approx(-out["q90"])
    parts[(m.SEEDS[0],None)]["sigma"]=np.array([-1.])
    with pytest.raises(ValueError,match="POSITIVE"):m.combine_predictions("GAUSSIAN_MLP",parts)

def test_seed_mean_requires_every_component_and_same_rows():
    p={(s,None):{"point":np.array([float(i)])} for i,s in enumerate(m.SEEDS)}
    assert m.combine_predictions("MLP",p)["point"]==pytest.approx([1])
    with pytest.raises(ValueError,match="ALL_FROZEN"):m.combine_predictions("MLP",{next(iter(p)):p[next(iter(p))]})
    p[(m.SEEDS[-1],None)]={"point":np.array([0.,1.])}
    with pytest.raises(ValueError,match="ROW_COUNTS"):m.combine_predictions("MLP",p)

def test_soft_matching_has_gradient_and_no_hard_solver(monkeypatch):
    torch=m._torch()
    import scipy.optimize
    monkeypatch.setattr(scipy.optimize,"linear_sum_assignment",lambda *a,**k:(_ for _ in ()).throw(AssertionError("hard solver")))
    s=torch.zeros(200,dtype=torch.float64,requires_grad=True)
    truth=torch.linspace(-.02,.02,200,dtype=torch.float64)
    loss=m.soft_optional_matching_utility(s,truth,[np.arange(200)])
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(s.grad).all() and float(s.grad.abs().sum())>0
    with pytest.raises(ValueError):m.soft_optional_matching_utility(s,truth,[np.arange(200)],iterations=10)

def test_neural_component_synthetic_persistence_and_joint_outputs(tmp_path):
    X,y,t,d,ch,inc=data();events=[]
    f=m.fit_component("MT_MLP",X,y,t,d,ch,inc,"LOW",m.SEEDS[0],on_fit=events.append)
    assert len(events)==1 and f.metadata["physical_backend_fit_calls"]==1
    assert f.metadata["spec"]["outputs"]==4
    before=m.predict(f,X[:3])
    import joblib
    path=tmp_path/"synthetic.joblib";joblib.dump(f,path);restored=joblib.load(path)
    after=m.predict(restored,X[:3])
    np.testing.assert_array_equal(before["tasks"],after["tasks"])
    assert after["point"]==pytest.approx(after["tasks"].mean(1))

def test_listwise_synthetic_training_uses_only_soft_transforms():
    X,y,t,d,ch,inc=data();events=[]
    f=m.fit_component("LISTWISE_MLP",X,y,t,d,ch,inc,"LOW",m.SEEDS[0],on_fit=events.append)
    assert len(events)==1 and f.metadata["hard_matching_training_calls"]==0
    assert f.metadata["soft_matching_transforms"]==f.metadata["epochs"]
    assert f.metadata["spec"]["output_kind"]=="utility_score_relative_to_dummy_zero"
    assert np.isfinite(m.predict(f,X[:2])["point"]).all()

def test_architecture_topology_frozen_and_input_dimension():
    s=m.specs()
    for cap in m.CAPACITIES:
        assert s["RESNET"][cap]["params"]["residual_blocks"]==2
        assert s["FT_TRANSFORMER"][cap]["params"]["heads"]==2
        assert s["FT_TRANSFORMER"][cap]["params"]["layers"]==1
        network=m._network("FT_TRANSFORMER",s["FT_TRANSFORMER"][cap])
        assert network.token_weight.shape[0]==216



def test_native_dependency_is_typed_before_callback(monkeypatch):
    X,y,t,d,ch,inc=data();events=[]
    def absent(*args,**kwargs):raise ImportError("synthetic absent backend")
    monkeypatch.setattr(m,"_native",absent)
    with pytest.raises(RuntimeError,match="BLOCKED_DEPENDENCY_NATIVE"):
        m.fit_component("EBM",X,y,t,d,ch,inc,"LOW",m.SEEDS[0],on_fit=events.append)
    assert not events


def test_multitask_prediction_shape_cannot_drift(fake):
    X,y,t,d,ch,inc=data()
    fitted=m.fit_component("MT_RIDGE",X,y,t,d,ch,inc,"LOW",m.SEEDS[0])
    fitted.estimator.outputs=5
    with pytest.raises(ValueError,match="COMPLETE_C14_OUTPUTS"):
        m.predict(fitted,X[:2])


def test_multitask_scalar_mean_target_cannot_change(fake):
    X,y,t,d,ch,inc=data();t[:,0]+=1
    with pytest.raises(ValueError,match="EQUAL_MEAN_TARGET"):
        m.fit_component("MT_RIDGE",X,y,t,d,ch,inc,"LOW",m.SEEDS[0])


@pytest.mark.parametrize("role",m.HYBRID_PARADIGMS)
def test_only_registered_hybrid_heads_accept_228(role,fake):
    X,y,t,d,ch,inc=data();X=np.column_stack((X,np.zeros((200,12))));events=[]
    q=.1 if role=="QUANTILE_HGB" else None
    f=m.fit_component(role,X,y,t,d,ch,inc,"LOW",m.SEEDS[0],q,on_fit=events.append,input_feature_count=228)
    assert len(events)==1 and f.metadata["spec"]["input_features"]==228
    assert all(len(v)==3 for v in m.predict(f,X[:3]).values())
    with pytest.raises(ValueError,match="PREDICTION_INPUT"):m.predict(f,X[:3,:216])


@pytest.mark.parametrize("role",[r for r in m.PARADIGMS if r not in m.HYBRID_PARADIGMS])
def test_other_heads_cannot_expand_information(role):
    X,y,t,d,ch,inc=data();X=np.column_stack((X,np.zeros((200,12))))
    q=.1 if role=="QUANTILE_HGB" else None
    with pytest.raises(ValueError,match="SIX_FROZEN_HYBRID"):
        m.fit_component(role,X,y,t,d,ch,inc,"LOW",m.SEEDS[0],q,input_feature_count=228)


def test_hybrid_specs_preserve_capacity_and_main_information():
    base=m.specs();hybrid=m.capacity_specs(input_feature_count=228)
    assert set(hybrid)==set(m.HYBRID_PARADIGMS)
    for role in hybrid:
        for cap in m.CAPACITIES:
            a=copy.deepcopy(hybrid[role][cap]);a["input_features"]=216
            assert a==base[role][cap]
    assert all(base[r][c]["input_features"]==216 for r in base for c in m.CAPACITIES)
    with pytest.raises(ValueError):m.capacity_specs(input_feature_count=217)


def test_native_training_loss_distinct_from_oof_capacity_objective():
    for p in m.MARGINS:
        for c in m.CAPACITIES:
            s=m.specs()[p][c]
            assert s["selection_kind"]=="OOF_BRIER_SIGN"
            assert "BRIER" not in s["loss_kind"]
    assert m.specs()["LOGIT"]["LOW"]["loss_kind"]=="O2_BINARY_LOG_LOSS"


def single_data():
    rng=np.random.default_rng(31); n=54
    x=rng.normal(size=(n,32));y=np.linspace(-.03,.03,n)
    tasks=np.column_stack((.5*y,1.5*y,y,y))
    dates=np.repeat(pd.to_datetime(["2023-07-03","2023-07-05"]).to_numpy(),[23,31])
    uids=np.array([f"UID:{i:03}" for i in range(23)]+[f"UID:{i:03}" for i in range(31)],object)
    expected={pd.Timestamp(d):tuple(uids[np.flatnonzero(dates==d)]) for d in pd.unique(dates)}
    return x,y,tasks,dates,uids,dict(fit_cutoff="2024-01-01",label_end_dates=dates+pd.Timedelta(days=30),expected_full_day_uids=expected)


def test_single_specs_preserve_old_profile_and_cover20_plus3():
    old=m.capacity_specs();new=m.capacity_specs(input_feature_count=32,representation=m.SINGLE_FULL_U32)
    assert len(new)==23 and all(c["input_features"]==32 for v in new.values() for c in v.values())
    assert m.capacity_specs()==old and all("representation" not in c for v in old.values() for c in v.values())
    assert new["LISTWISE_MLP"]["MID"]["loss_kind"]=="FULL_DAY_TOP20_MASS_CROSS_ENTROPY"
    assert new["LAMBDAMART"]["LOW"]["selection_kind"]=="NEGATIVE_FULL_DAY_TOP20_MEAN_TARGET"
    with pytest.raises(ValueError): m.capacity_specs(input_feature_count=32)
    with pytest.raises(ValueError): m.capacity_specs(input_feature_count=216,representation=m.SINGLE_FULL_U32)


@pytest.mark.parametrize("role",[r for r in m.PARADIGMS if r not in m.NEURAL])
def test_single_native_full_groups_and_date_weight(role,fake):
    x,y,t,d,u,kw=single_data();x[0,0]=np.nan;events=[]
    model=m.fit_single_component(role,x,y,t,d,u,"LOW",m.SEEDS[0],.5 if role=="QUANTILE_HGB" else None,on_fit=events.append,**kw)
    assert len(events)==1 and model.metadata["date_group_sizes"]==[23,31]
    assert model.metadata["missing_channels_added"]==0 and np.isfinite(model.estimator.training[0]).all()
    args=model.estimator.training[2]
    if role=="PAIRWISE_RANKER": assert args["group"]==[23,31] and np.array_equal(args["sample_weight"],[1.,1.])
    else:
        assert args["sample_weight"][:23].sum()==pytest.approx(27.)
        assert args["sample_weight"][23:].sum()==pytest.approx(27.)
    assert all(len(v)==3 for v in m.predict(model,x[:3]).values())


@pytest.mark.parametrize("bad",["future","maturity","duplicate_uid","axis_reorder","pool_shrink","inf","mt_mean"])
def test_single_boundary_identity_fail_before_native(bad,fake):
    x,y,t,d,u,kw=single_data();events=[];role="RIDGE"
    if bad=="future": d[0]=np.datetime64("2026-01-02")
    elif bad=="maturity": kw["label_end_dates"]=pd.DatetimeIndex(["2024-01-01"]*len(d))
    elif bad=="duplicate_uid": u[0]=u[1]
    elif bad=="axis_reorder": u[:23]=u[:23][::-1]
    elif bad=="pool_shrink": kw["expected_full_day_uids"][pd.Timestamp(d[0])]+= ("UID:999",)
    elif bad=="inf": x[0,0]=np.inf
    else: role="MT_RIDGE";t[:,0]+=1.
    with pytest.raises(ValueError): m.fit_single_component(role,x,y,t,d,u,"LOW",m.SEEDS[0],on_fit=events.append,**kw)
    assert not events


def test_single_top20_target_ties_and_future_append_are_local():
    x,y,t,d,u,kw=single_data();y[:23]=1.
    groups=[np.arange(23),np.arange(23,54)]
    a=m.single_top20_labels(y,groups,u)
    assert np.flatnonzero(a[:23]).tolist()==list(range(20))
    ext=m.single_top20_labels(np.r_[y,[999.,999.]],groups+[np.arange(54,56)],np.r_[u,["UID:A","UID:B"]])
    np.testing.assert_array_equal(a,ext[:54])


def test_single_dag_exact_physical_counts_and_no_fake_estimators():
    dag=m.single_training_dag()
    assert dag["counts"]==dict(CALIBRATOR=10,ESTIMATOR=505,META_MODEL=32,META_SCALER=28,META_TARGET_SCALE=14,SCALER=5)
    assert dag["learned_operation_ceiling"]==594 and dag["hybrid_separate_ceiling"]["learned_operations"]==144
    assert dag["signed_amplitude_fits"]==dag["equal_median_fit_calls"]==dag["native_rank_calibration_fits"]==0
    assert len({n["node_id"] for n in dag["nodes"]})==594
    assert all(n["role"]=="LINEAR_SVM" for n in dag["nodes"] if n["kind"]=="ESTIMATOR" and n["cutoff"]=="2023-04-01")


def test_single_full_day_listwise_loss_uses_existing_owner(monkeypatch):
    torch=m._torch(); from scripts.research.a2.training.selector_sufficiency_estimators import date_balanced_listwise_loss
    scores=torch.zeros(54,dtype=torch.float64,requires_grad=True)
    x,y,t,d,u,kw=single_data();groups=[np.arange(23),np.arange(23,54)]
    labels=torch.tensor(m.single_top20_labels(y,groups,u),dtype=torch.float64)
    loss=date_balanced_listwise_loss(scores,labels,groups);loss.backward()
    assert float(loss)==pytest.approx((np.log(23)+np.log(31))/2)
    assert torch.isfinite(scores.grad).all() and float(scores.grad.abs().sum())>0


@pytest.mark.parametrize("role",m.HYBRID_PARADIGMS)
def test_single_hybrid34_only_six_heads_with_same_full_axis(role,fake):
    x,y,t,d,u,kw=single_data();x=np.column_stack((x,np.ones((len(x),2))))
    kw["representation"]=m.SINGLE_HYBRID_U34
    f=m.fit_single_component(role,x,y,t,d,u,"LOW",m.SEEDS[0],.5 if role=="QUANTILE_HGB" else None,**kw)
    assert f.metadata["spec"]["input_features"]==34
    assert f.metadata["spec"]["risk_feature_order"]==list(m.SINGLE_RISK_COLUMNS)
    assert f.metadata["date_group_sizes"]==[23,31]
    assert np.isfinite(next(iter(m.predict(f,x[:3]).values()))).all()
    with pytest.raises(ValueError):m.predict(f,x[:3,:32])


def test_single_hybrid_specs_cannot_expand_other_heads():
    new=m.capacity_specs(input_feature_count=34,representation=m.SINGLE_HYBRID_U34)
    assert tuple(new)==m.HYBRID_PARADIGMS
    with pytest.raises(ValueError,match="SIX_SINGLE_HYBRID"):
        m._feature_count("LOGIT",34,m.SINGLE_HYBRID_U34)
