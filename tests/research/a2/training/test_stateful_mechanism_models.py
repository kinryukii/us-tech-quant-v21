"""Synthetic-only R10 model consumer acceptance; no research/source I/O."""
import copy
import hashlib
import pickle
import numpy as np
import pytest
from scripts.research.a2.training import stateful_mechanism_models as m
from scripts.research.a2.training.stateful_value_extensions import TORCH_SNAPSHOT
DEPENDENCIES=(str(TORCH_SNAPSHOT),)

def payload(family="ridge",capacity="LOW",seed=20260928,n=24,objective="ADVANTAGE"):
    return dict(family=family,capacity=capacity,seed=seed,objective=objective,
                target=np.linspace(-2.,3.,n),weights=np.linspace(.2,2.,n))

def matrix(n=24):
    return np.column_stack([np.linspace(-1,1,n),np.arange(n)%3]).astype(float)

@pytest.mark.parametrize("family",m.FAMILIES)
@pytest.mark.parametrize("capacity",m.CAPACITIES)
def test_all_family_exact_predeclared_capacity(family,capacity):
    assert m.parameters(family,capacity)==m.specifications()["configurations"][family][capacity]
    assert m.specifications()["target_clip"]=="NONE"

@pytest.mark.parametrize("family",m.ACTION_FAMILIES+("tcn","gru","lstm","gaussian_mlp4h"))
def test_root_family_alias(family):
    objective="ADVANTAGE"
    p=payload(family);p["lookback"]=20
    node=m._node("opaque_budget_slot_1",p)
    assert node["family"]==m.canonical_family(family)

def test_frozen_seeds_and_deterministic_no_extra_seed():
    with pytest.raises(ValueError,match="DETERMINISTIC_EXTRA_SEED"):
        m._node("slot",payload("ridge",seed=20260929))
    with pytest.raises(ValueError,match="SEED_NOT_FROZEN"):
        m._node("slot",payload("mlp",seed=9))
    assert m._node("slot",payload("mlp",seed=20260930))["seed"]==20260930

def test_opaque_id_is_only_audit_key_and_explicit_conflict_rejected():
    node=m._node("R10_entry_ridge2024",payload())
    assert node["audit_id"]=="R10_entry_ridge2024"
    with pytest.raises(ValueError,match="CONFLICT"):
        m._node({"family":"HGB","capacity":"LOW","seed":20260928},payload())

def test_ridge_no_target_clipping_no_hidden_scaler():
    p=payload();x=matrix();calls=[]
    model,meta=m.fit("budget_identity",x,p,on_fit_started=calls.append)
    assert meta["actual_fit_count"]==1 and meta["scaler_fit_count"]==0
    assert calls==["MECHANISM_ESTIMATOR"]
    assert model.estimator.intercept_==pytest.approx(np.average(p["target"],weights=p["weights"])-
              np.average(x,axis=0,weights=p["weights"])@model.estimator.coef_)
    assert np.max(p["target"])==3.
    out=m.predict(model,x)
    assert out["mean"].shape==(len(x),)
    assert out["sigma"] is None and out["probability"] is None

def test_logistic_probability_not_money_mean():
    model,meta=m.fit("log_slot",matrix(),payload("logistic"))
    out=m.predict(model,matrix())
    assert out["mean"] is None and out["sigma"] is None
    assert np.all((out["probability"]>=0)&(out["probability"]<=1))
    assert meta["actual_fit_count"]==1

def test_native_quantile_three_real_fits_not_one():
    calls=[]
    model,meta=m.fit("quantile_slot",matrix(),payload("hgb_quantile"),on_fit_started=calls.append)
    assert meta["actual_fit_count"]==3
    assert calls==["MECHANISM_QUANTILE_Q10","MECHANISM_QUANTILE_Q50","MECHANISM_QUANTILE_Q90"]
    out=m.predict(model,matrix())
    assert out["mean"] is None and out["sigma"] is None
    assert out["point_statistic"]=="NATIVE_MEDIAN"
    assert np.all(out["q10"]<=out["q50"]) and np.all(out["q50"]<=out["q90"])

def test_single_quantile_head_is_one_fit_and_unsupported_null():
    model,meta=m.fit("q10_slot",matrix(),payload("hgb_quantile"),quantile=.1)
    out=m.predict(model,matrix())
    assert meta["actual_fit_count"]==1
    assert out["q10"] is not None and out["q50"] is None and out["mean"] is None

def test_worker_ack_rejection_prevents_fit():
    class Pipe:
        def __init__(self):self.messages=[];self.closed=False
        def send(self,value):self.messages.append(value)
        def recv(self):return False
        def close(self):self.closed=True
    pipe=Pipe()
    m.fit_worker(pipe,"mechanism","slot",matrix(),payload(),None,None,[],[],None)
    assert pipe.messages[0]==("FIT_START","MECHANISM_ESTIMATOR")
    assert pipe.messages[-1][0]=="ERROR"
    assert "PARENT_REJECTED" in pipe.messages[-1][-1]
    assert pipe.closed

def test_worker_rejects_any_unregistered_operation():
    class Pipe:
        def __init__(self):self.messages=[]
        def send(self,value):self.messages.append(value)
        def close(self):pass
    pipe=Pipe()
    m.fit_worker(pipe,"real_account","slot",matrix(),payload(),None,None,[],[],None)
    assert pipe.messages[0][0]=="ERROR"

def test_weighted_scaler_single_fit_no_target_use():
    x=np.array([[0.,1.],[4.,7.],[8.,3.]])
    weights=np.array([1.,1.,8.]);calls=[]
    sc,meta=m.fit_weighted_scaler(x,dict(weights=weights,target=np.array([999,999,999])),
                                 on_fit_started=calls.append)
    assert sc.mean_==pytest.approx(np.average(x,axis=0,weights=weights))
    assert meta["actual_fit_count"]==1 and len(calls)==1

def test_sequence_scaler_excludes_unobserved_cells_datebalanced():
    x=np.array([[[1.,10.],[99.,20.]],[[5.,30.],[7.,40.]]])
    mask=np.ones_like(x,dtype=bool);mask[0,1,0]=False
    weights=np.array([1.,3.])
    sc,meta=m.fit_weighted_scaler(x,dict(weights=weights),observed=mask)
    assert sc.mean_[0]==pytest.approx((1*.5+5*1.5+7*1.5)/3.5)
    assert meta["observed_cells"]==7 and meta["actual_fit_count"]==1

def test_all_unobserved_scaler_channel_failclosed():
    x=np.array([[np.nan,1.],[np.nan,2.]])
    with pytest.raises(ValueError,match="NO_TRAIN_ONLY_OBSERVED_MEAN"):
        m.fit_weighted_scaler(x,dict(weights=np.ones(2)))

def fusion_payload(method="stack_ridge",n=24):
    x=matrix(n);experts=np.column_stack([x[:,0],(x[:,0]+x[:,1])/2,x[:,1]])
    state=np.column_stack([x,x**2]);weights=np.linspace(1.,2.,n)
    views={"expert":experts,"state":state,"combined":np.column_stack([experts,state])}
    scalers={view:m.fit_weighted_scaler(a,dict(weights=weights))[0] for view,a in views.items()}
    digests={view:hashlib.sha256(np.ascontiguousarray(a,dtype=float).tobytes()).hexdigest() for view,a in views.items()}
    p=dict(method=method,seed=20260928,target=np.linspace(-.2,.3,n),weights=weights,state=state,
           shared_scalers=scalers,shared_scaler_input_sha256=digests)
    return experts,p

@pytest.mark.parametrize("method",["equal","median","nnls","convex","stack_ridge","stack_elastic","stack_hgb","residual_first_hgb","residual_last_ridge"])
def test_fusion_real_owner_no_extra_scaler_and_point_only(method):
    x,p=fusion_payload(method);calls=[]
    before={k:pickle.dumps(v) for k,v in p["shared_scalers"].items()}
    model,meta=m.fit_fusion("budget_fusion_slot",x,p,on_fit_started=calls.append,dependencies=DEPENDENCIES)
    assert meta["actual_fit_count"]==(0 if method in ("equal","median") else 1)
    assert meta["scaler_fit_count"]==0
    assert before=={k:pickle.dumps(v) for k,v in p["shared_scalers"].items()}
    cloned=pickle.loads(pickle.dumps(model))
    out=m.predict(cloned,dict(experts=x,state=p["state"]))
    assert out["mean"].shape==(len(x),) and out["sigma"] is None
    assert out["q10"] is None and out["probability"] is None
    assert meta["independent_expert_count"]==2

def test_fusion_virtual_expert_exactness_and_scaler_input_binding():
    x,p=fusion_payload()
    xx=x.copy();xx[0,1]+=.001
    with pytest.raises(ValueError,match="VIRTUAL_EXPERT"):
        m.fit_fusion("slot",xx,p)
    p["shared_scaler_input_sha256"]["expert"]="unbound"
    with pytest.raises(ValueError,match="SCALER_INPUT_IDENTITY"):
        m.fit_fusion("slot",x,p,dependencies=DEPENDENCIES)

def test_source_pin_mismatch_prevents_any_fit():
    p=payload();p["source_pins"]={"adapter_sha256":"UNBOUND"}
    with pytest.raises(ValueError,match="SOURCE_PINS"):
        m.fit("slot",matrix(),p)

def test_shapes_failclosed():
    with pytest.raises(ValueError,match="TARGET_SHAPE"):
        m.fit("slot",matrix(),{**payload(),"target":[1.]})
    with pytest.raises(ValueError,match="WEIGHTS"):
        m.fit("slot",matrix(),{**payload(),"weights":np.zeros(24)})
    with pytest.raises(ValueError,match="ALREADY_TRANSFORMED"):
        m.fit("slot",np.full((24,2),np.nan),payload())

def test_science_snapshot_counters_and_no_source_activation():
    spec=m.specifications()
    assert spec["fusion"]["total"]==76
    assert spec["preprocessing"].startswith("ROOT_SHARED")
    assert "source_activated" not in spec
    assert spec["gaussian4h"].endswith("NO_JOINT_SIGMA")


@pytest.mark.parametrize("family",["resnet","ft_transformer","gaussian_mlp","gaussian_mlp4h","tcn","gru","lstm"])
def test_real_frozen_torch_owner_private_clone_and_serialization(family):
    native=m.values._native(DEPENDENCIES)
    original_seed=native.SEED
    original_code=native.fit_torch.__code__.co_code
    n=8
    x=matrix(n)
    p=payload(family,n=n)
    p["target"]=np.linspace(-.1,.2,n)
    if family=="gaussian_mlp4h":
        p["target"]=np.column_stack([p["target"]+v for v in (0.,.01,.02,.03)])
    if family in ("tcn","gru","lstm"):
        p["lookback"]=5;x=np.repeat(x[:,None,:],5,axis=1)
    calls=[]
    model,meta=m.fit("toy_torch_budget_slot",x,p,dependencies=DEPENDENCIES,on_fit_started=calls.append)
    assert meta["actual_fit_count"]==1 and meta["scaler_fit_count"]==0
    assert meta["epochs"]==12 and len(calls)==1
    assert original_code==native.fit_torch.__code__.co_code and native.SEED==original_seed
    cloned=pickle.loads(pickle.dumps(model));out=m.predict(cloned,x)
    assert out["mean"].shape==(n,) and np.isfinite(out["mean"]).all()
    if family=="gaussian_mlp":
        assert np.all(out["sigma"]>0) and out["probability"].shape==(n,)
    elif family=="gaussian_mlp4h":
        assert out["mean_h"].shape==(n,4) and out["sigma_h"].shape==(n,4)
        assert out["sigma"] is None and out["probability"] is None
        assert out["mean"]==pytest.approx(out["mean_h"].mean(axis=1))
    else:assert out["sigma"] is None

@pytest.mark.parametrize("method",["stack_mlp","gate_linear","gate_mlp"])
def test_stochastic_fusion_actual_fixed_epoch_owner(method):
    x,p=fusion_payload(method)
    if method in ("stack_mlp","gate_mlp"):p["seed"]=20260929
    calls=[]
    model,meta=m.fit_fusion("toy_fusion_neural",x,p,dependencies=DEPENDENCIES,on_fit_started=calls.append)
    assert meta["actual_fit_count"]==1 and meta["scaler_fit_count"]==0
    if method=="stack_mlp":assert model.estimator.model.steps[-1][1].n_iter_==40
    out=m.predict(pickle.loads(pickle.dumps(model)),dict(experts=x,state=p["state"]))
    assert np.isfinite(out["mean"]).all() and out["sigma"] is None
