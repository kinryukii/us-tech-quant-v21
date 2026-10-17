"""Synthetic anchor contract/coordinate/phase gates; no data or account replay."""
from dataclasses import replace, asdict
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference.joint_shr_anchor_policy_r4 import *
from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState, SourceReceipt
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext


def fixture():
    assets=tuple("T%02d"%i for i in range(25));n=len(assets)
    asof=pd.Timestamp("2024-02-01T21:00:00Z");cutoff=pd.Timestamp("2024-01-31T21:00:00Z")
    path="R4_SHR_ANCHOR_SHR_HP"; weights=np.zeros((1,n));weights[0,0]=.04
    held=weights>0;reserve=held.copy();buy=np.ones((1,n),bool);buy[0,0]=False
    decision=np.ones((1,n),bool);decision[0,0]=False
    ctx=AccountContext(0,asof,asof,(path,),np.asarray(assets),held.astype(float),weights,
        np.array([2880.]),np.array([.96]),np.array([3000.]),reserve,np.array([.04]),
        np.array([1]),np.array([.96]),np.array([19]),buy,np.zeros((1,n),bool),
        np.ones((1,n),bool),decision,np.zeros((1,n),bool),20,.1,1.)
    contract=AnchorContract("V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4","a"*64,"b"*64,"c"*64)
    fields={k:None for k in RiskState.__dataclass_fields__}
    fields.update(risk_state_id="synthetic-risk",as_of=asof,cutoff=cutoff,assets=assets,
        method="SHR_HP",horizon=5,status="CONDITIONAL_FROZEN_HISTORY_MECHANISM",blocked_assets=(),
        source_receipt=SourceReceipt("synthetic-source","v1","a"*64,cutoff,scientific_contract_sha256="b"*64,
            scientific_contract_identity=contract.research_id,synthetic=True),
        covariance=np.eye(n)*.0002+.00001,coverage={a:{"uid":a} for a in assets})
    state=RiskState(**fields)
    use=AnchorUse("SHR_HP",state.risk_state_id,risk_state_sha256(state),str(asof),str(cutoff),
        "2024-04-01T20:00:00Z",assets,assets,"b"*64,"d"*64,"2024-01-01T00:00:00Z","2023-12-29T21:00:00Z",True)
    data=dict(use=use,state=state,expected_use_sha256=use.digest(),current_pool_assets=assets,
        current_pool_uids=assets,mu=np.linspace(.005,.03,n),uncertainty=np.full(n,.01))
    policy=ShrAnchorPolicy(contract,contract.digest(),lambda *args:data)
    return policy,ctx,data


def test_qualified_anchor_reuses_q0_a0_g0_and_preserves_reserved():
    policy,ctx,data=fixture();before=data["state"].covariance.copy()
    result=policy.evaluate(0,ctx.path_ids[0],ctx,data)
    effective=np.where(result.explicit_mask,result.weights,ctx.current_weights)
    assert effective[0,0]==.04 and effective.sum()<=1+1e-10
    assert np.count_nonzero(effective)>0 and np.count_nonzero(effective)<=20
    np.testing.assert_array_equal(before,data["state"].covariance)
    assert policy.diagnostics[0]["covariance_modified"] is False


@pytest.mark.parametrize("defect",["renamed_method","future","pool_shrink","uid_swap","covariance","source"])
def test_dependency_defects_fail_closed(defect):
    policy,ctx,data=fixture()
    if defect=="renamed_method": data["state"]=replace(data["state"],method="R0")
    elif defect=="future": ctx=replace(ctx,signal_asof=pd.Timestamp("2026-01-02T21:00:00Z"))
    elif defect=="pool_shrink":data["current_pool_assets"]=data["current_pool_assets"][:-1]
    elif defect=="uid_swap":data["current_pool_uids"]=("wrong",)+data["current_pool_uids"][1:]
    elif defect=="covariance":data["state"].covariance[0,0]=float("nan")
    else:data["state"]=replace(data["state"],source_receipt=replace(data["state"].source_receipt,scientific_contract_sha256="e"*64))
    with pytest.raises(AdapterBlocked):policy.evaluate(0,ctx.path_ids[0],ctx,data)


def test_support_phase_cannot_economic_replay():
    policy,ctx,_=fixture()
    with pytest.raises(AdapterBlocked,match="QUALIFICATION_ONLY"):policy(0,ctx)


def test_synthetic_use_cannot_activate_real_account():
    policy,ctx,_=fixture();policy.mode="ACCOUNT_REPLAY"
    with pytest.raises(AdapterBlocked,match="SYNTHETIC_CANNOT"):policy(0,ctx)


def test_producer_serialized_source_receipt_mapping_is_validated_without_mutation():
    policy,ctx,data=fixture()
    receipt=asdict(data["state"].source_receipt)
    data["state"]=replace(data["state"],source_receipt=receipt)
    data["use"]=replace(data["use"],risk_state_sha256=risk_state_sha256(data["state"]))
    data["expected_use_sha256"]=data["use"].digest()
    original=receipt.copy()
    result=policy.evaluate(0,ctx.path_ids[0],ctx,data)
    assert result.weights.shape==ctx.current_weights.shape
    assert receipt==original


def test_p0_exclusive_fit_cutoff_and_maturity_are_separate_clocks():
    policy,ctx,data=fixture()
    # Jan31 risk cutoff versus Feb1 model exclusive cutoff is legal only when
    # the latest matured observation actually precedes both.
    use=replace(data["use"],p0_fit_cutoff="2024-02-01T00:00:00Z",p0_matured_max="2024-01-31T20:00:00Z")
    data.update(use=use,expected_use_sha256=use.digest())
    policy.evaluate(0,ctx.path_ids[0],ctx,data)
    use=replace(use,p0_matured_max="2024-01-31T22:00:00Z")
    data.update(use=use,expected_use_sha256=use.digest())
    with pytest.raises(AdapterBlocked,match="FUTURE_CUTOFF"):
        policy.evaluate(0,ctx.path_ids[0],ctx,data)
