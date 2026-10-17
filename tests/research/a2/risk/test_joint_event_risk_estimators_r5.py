"""Synthetic-only tests; reuse the reviewed native fixture, no real readers."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from tests.research.a2.risk.test_short_history_risk_r4 import fixture_input
from scripts.research.a2.risk import short_history_risk_r4 as parent
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget,content_hash
from scripts.research.a2.risk.joint_event_risk_estimators_r5 import EventRiskEstimator,specification


def cold_input():
    inputs,asof,support=fixture_input(industry=True)
    observations=inputs.observations.loc[~inputs.observations.asset.eq("S0")].copy()
    last=observations.loc[observations.asset.eq("S1")].tail(7).origin_at
    observations=observations.loc[~observations.asset.eq("S1") | observations.origin_at.isin(last)].copy()
    support=support.merge(observations[["asset","origin_at"]],on=["asset","origin_at"],how="inner",validate="one_to_one")
    inputs=replace(inputs,observations=observations)
    current=dict(assets=list(inputs.assets),asset_uids=dict(inputs.asset_uids),
        asset_epochs={a:"OBSERVED_EPOCH_"+a for a in inputs.assets},security_coordinate="SYNTHETIC_RAW_SHARES",
        source_support_identity={"local_event_identity":"synthetic-known-current-source","sha256":"a"*64},
        source_qualified=True,maturity_qualified=True)
    return inputs,asof,support,current


def ff_current(inputs,current):
    return {**current,"family_source_support_identity":{"FF48_HIERARCHICAL":dict(
        dependency="FF48",dependency_local_event_id="SYNTHETIC_FF48_EVENT",
        dependency_local_signature_sha256="b"*64,
        source_pins={"FF48":inputs.industry_receipt.source_sha256},
        industry_source=inputs.industry_receipt.cache_identity())}}


def fit(estimator,family,inputs,asof,support,current,**kwargs):
    return estimator.fit_family(family,inputs,as_of=asof,support_metadata=support,current_identity_proof=current,**kwargs)


def test_known_uid_n0_and_n7_hp_prior_are_new_science_and_no_rows_created():
    inputs,asof,support,current=cold_input()
    original_rows=len(inputs.observations)
    e=EventRiskEstimator()
    q=e.qualify(inputs,as_of=asof,support_metadata=support,current_identity_proof=current)
    assert q["nominal_n"]["S0"]==0 and q["nominal_n"]["S1"]==7
    assert q["n0_prior_only_assets"]==["S0"] and q["observations_created"]==0
    state=fit(e,"SHR_HP",inputs,asof,support,current,expected_qualification=q)
    assert state.status=="PASS_SYNTHETIC",state.notes
    assert state.assets==inputs.assets and state.covariance.shape==(10,10)
    assert state.method=="R5::SHR_HP::KNOWN_UID_PRIOR_PREDICTIVE_N0"
    assert state.estimation_uncertainty["S0"]["sigma2_posterior"]["shape"]==3.
    assert np.isfinite(state.covariance).all() and np.linalg.eigvalsh(state.covariance).min()>0
    assert state.coverage["S0"]["nominal_n"]==0
    assert state.coverage["S0"]["identity_epoch"]==current["asset_epochs"]["S0"]
    assert state.coverage["S0"]["pooled_identity_epoch"]==inputs.identity_epoch
    assert len(inputs.observations)==original_rows and not inputs.observations.asset.eq("S0").any()
    native=parent.fit_risk("SHR_HP",inputs,as_of=asof,support_metadata=support)
    assert native.status=="BLOCKED" and "FIXED_MINIMUM" in native.notes["block_reason"]
    assert parent.specification()["minimum_nominal_n"]==10


def test_metadata_qualification_never_decodes_numeric_values_and_no_future_groups():
    inputs,asof,support,current=cold_input()
    poison=inputs.observations.copy();poison["return_value"]="must never decode"
    e=EventRiskEstimator()
    q=e.qualify(replace(inputs,observations=poison),as_of=asof,support_metadata=support,current_identity_proof=current)
    assert q["nominal_n"]["S0"]==0 and q["active_groups"]==[]
    assert all(v is None for v in q["industry_groups"].values())


def test_byte_identical_pinned_fit_body_and_no_parent_global_mutation():
    inputs,asof,support,current=cold_input()
    calendar=parent._calendar;qualifier=parent.qualify_metadata;recipe=parent.specification()
    e=EventRiskEstimator()
    clone=e._native_for("SHR_HP",current)
    assert clone.__code__ is parent.fit_risk.__code__
    assert clone.__code__.co_code==parent.fit_risk.__code__.co_code
    assert clone.__globals__ is not parent.fit_risk.__globals__
    assert parent._calendar is calendar and parent.qualify_metadata is qualifier
    assert parent.specification()==recipe


def test_core_shared_cache_budget_and_identical_cohort_preprocessing():
    inputs,asof,support,current=cold_input()
    e=EventRiskEstimator();budget=StateBudget(limit=100)
    cache=e.make_cache(inputs,as_of=asof,budget=budget)
    hp=fit(e,"SHR_HP",inputs,asof,support,current,cache=cache)
    assert hp.status=="PASS_SYNTHETIC" and budget.learned_total==7
    cc=fit(e,"SHR_CC",inputs,asof,support,current,cache=cache)
    assert cc.status=="PASS_SYNTHETIC" and budget.learned_total==8
    np.testing.assert_allclose(np.diag(hp.covariance),np.diag(cc.covariance))
    for family in ("LW","OAS","EWMA","PCA_FACTOR"):
        state=fit(e,family,inputs,asof,support,current,cache=cache)
        assert state.status=="PASS_SYNTHETIC",state.notes
        assert state.assets==inputs.assets and state.covariance.shape==(10,10)
        assert not state.coverage["S0"]["native_estimator_qualified"]
        assert not state.coverage["S1"]["native_estimator_qualified"]
        assert state.coverage["S0"]["n0_prior_only"]
    assert budget.learned_total==13
    before=budget.learned_total
    state=fit(e,"LW",inputs,asof,support,current,cache=cache)
    assert state.status=="PASS_SYNTHETIC" and budget.learned_total==before
    rb=fit(e,"QQQ_RESIDUAL",inputs,asof,support,current,cache=cache)
    assert rb.status=="PASS_SYNTHETIC",rb.notes
    # Root budget must use measured native primitive DAG, not an assumed count.
    assert budget.learned_total==18


@pytest.mark.parametrize("family",["SHR_EB","SHR_FACTOR","CONSTANT_CORRELATION"])
def test_native_minimum_cohort_then_explicit_full_prior_completion(family):
    inputs,asof,support,current=cold_input()
    e=EventRiskEstimator()
    state=fit(e,family,inputs,asof,support,current)
    assert state.status=="PASS_SYNTHETIC",state.notes
    assert state.assets==inputs.assets and state.covariance.shape==(10,10)
    assert state.method.startswith("R5::")
    assert "S0" not in state.notes["native_cohort_assets"] and "S1" not in state.notes["native_cohort_assets"]
    assert state.notes["completion"]["observations_fabricated"] is False
    assert not state.notes["original_native_full_domain_qualification_claim"]


@pytest.mark.parametrize("defect",["unknown_uid","unknown_epoch","source","maturity","missing_proof","donors","stock_epoch","qqq_maturity"])
def test_source_identity_maturity_and_donor_fail_closed_before_learning(defect):
    inputs,asof,support,current=cold_input();current={**current}
    if defect=="unknown_uid":
        inputs=replace(inputs,asset_uids={**inputs.asset_uids,"S0":"UNKNOWN"})
        current["asset_uids"]=dict(inputs.asset_uids)
    elif defect=="unknown_epoch":current["asset_epochs"]={**current["asset_epochs"],"S0":"UNKNOWN"}
    elif defect=="source":current["source_qualified"]=False
    elif defect=="maturity":current["maturity_qualified"]=False
    elif defect=="missing_proof":current={}
    elif defect=="donors":support.loc[support.asset.isin(["D0","D1","D2","D3"]),"qualified"]=False
    elif defect=="stock_epoch":inputs=replace(inputs,source_receipt=replace(inputs.source_receipt,identity_epoch="WRONG"))
    else:
        q=inputs.qqq_observations.copy();q.loc[q.index[-1],"endpoint_at"]-=pd.Timedelta(days=10)
        inputs=replace(inputs,qqq_observations=q)
    e=EventRiskEstimator();budget=StateBudget(limit=100);cache=e.make_cache(inputs,as_of=asof,budget=budget)
    state=fit(e,"SHR_HP",inputs,asof,support,current,cache=cache)
    assert state.status=="BLOCKED" and state.covariance is None and state.assets==inputs.assets
    assert budget.learned_total==0


def test_tail_requires_real_scenario_source_not_native_rt_relabel():
    inputs,asof,support,current=cold_input()
    e=EventRiskEstimator();budget=StateBudget(limit=100);cache=e.make_cache(inputs,as_of=asof,budget=budget)
    state=fit(e,"TAIL_CVAR",inputs,asof,support,current,cache=cache)
    assert state.status=="BLOCKED" and "SCENARIO" in state.notes["block_reason"]
    assert budget.learned_total==0


def test_real_fit_requires_exact_frozen_recipe_and_metadata_before_numeric_access():
    inputs,asof,support,current=cold_input()
    receipt=replace(inputs.source_receipt,synthetic=False,mechanism=True,
        status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",scientific_contract_identity="R5_TEST_ONLY",
        scientific_contract_sha256="d"*64,actual_snapshot_timestamp="2026-10-04T00:00:00Z",observation_time_assumed=True)
    inputs=replace(inputs,source_receipt=receipt)
    e=EventRiskEstimator();budget=StateBudget(limit=100)
    state=fit(e,"SHR_HP",inputs,asof,support,current,budget=budget)
    assert state.status=="BLOCKED" and "FREEZE_REQUIRED" in state.notes["block_reason"]
    assert budget.learned_total==0


def test_scientific_numeric_failure_preserves_failed_reservation_no_retry():
    inputs,asof,support,current=cold_input()
    q=inputs.qqq_observations.copy();q["return_value"]=0.
    inputs=replace(inputs,qqq_observations=q)
    e=EventRiskEstimator();budget=StateBudget(limit=100);cache=e.make_cache(inputs,as_of=asof,budget=budget)
    first=fit(e,"SHR_HP",inputs,asof,support,current,cache=cache)
    assert first.status=="BLOCKED" and "VARIANCE_NOT_IDENTIFIABLE" in first.notes["block_reason"]
    before=budget.learned_total
    again=fit(e,"SHR_HP",inputs,asof,support,current,cache=cache)
    assert again.status=="BLOCKED" and "NO_RETRY" in again.notes["block_reason"]
    assert budget.learned_total==before


def test_event_close_is_not_native_quarterly_refresh_and_fixed_recipe_only():
    inputs,asof,support,current=cold_input()
    asof=inputs.sessions[inputs.sessions.get_loc(asof)+1]
    e=EventRiskEstimator()
    state=fit(e,"SHR_HP",inputs,asof,support,current)
    assert state.status=="PASS_SYNTHETIC",state.notes
    assert state.cutoff==inputs.sessions[inputs.sessions.get_loc(asof)-1]
    bad=specification();bad["hp_prior_strength"]=9.
    with pytest.raises(ValueError,match="EXACT_LITERAL"):
        EventRiskEstimator(bad)



def test_complete_broad_anchor_dag_uses_independent_ff_source_and_bound33(capsys):
    inputs,asof,support,current=cold_input()
    # A reviewed synthetic H1 endpoint producer; never invent it for a real source.
    sessions=inputs.sessions;cut=sessions.get_loc(asof)-1
    rng=np.random.default_rng(20260928)
    daily=[]
    for oi in range(cut-602,cut-2):
        daily.append(dict(asset="QQQ",origin_at=sessions[oi],entry_at=sessions[oi+1]-pd.Timedelta(hours=6),
            endpoint_at=sessions[oi+2]-pd.Timedelta(hours=6),matured_at=sessions[oi+2]-pd.Timedelta(hours=5),
            available_at=sessions[oi+2]-pd.Timedelta(hours=4),horizon=1,uid="QQQ",
            identity_epoch=inputs.qqq_receipt.identity_epoch,source_identity=inputs.qqq_receipt.source_identity,
            return_value=float(rng.normal(0.,.01))))
    inputs=replace(inputs,qqq_observations=pd.concat([inputs.qqq_observations,pd.DataFrame(daily)],ignore_index=True))
    current=ff_current(inputs,current)
    e=EventRiskEstimator();budget=StateBudget(limit=100);cache=e.make_cache(inputs,as_of=asof,budget=budget)
    counts={}
    for family in ("SHR_HP","SHR_CC","LW","OAS","EWMA","PCA_FACTOR","QQQ_RESIDUAL"):
        state=fit(e,family,inputs,asof,support,current,cache=cache)
        assert state.status=="PASS_SYNTHETIC",state.notes
    assert budget.learned_total==18
    base=budget.learned_total
    for family in ("CONSTANT_CORRELATION","FF48_HIERARCHICAL","SHR_EB","SHR_FACTOR",
                   "DOWNSIDE_SEMIVARIANCE","TAIL_CVAR","REGIME_COVARIANCE",
                   "UNCERTAINTY_JACKKNIFE","DISAGREEMENT_ENSEMBLE"):
        before=budget.learned_total
        state=fit(e,family,inputs,asof,support,current,cache=cache)
        counts[family]=budget.learned_total-before
        if family=="TAIL_CVAR":
            assert state.status=="BLOCKED" and counts[family]==0
        else:
            assert state.status=="PASS_SYNTHETIC",state.notes
            assert state.assets==inputs.assets and state.covariance.shape==(10,10)
    assert counts["FF48_HIERARCHICAL"]<=7
    assert counts["SHR_EB"]+counts["SHR_FACTOR"]<=9
    assert counts["CONSTANT_CORRELATION"]==1
    assert counts["DOWNSIDE_SEMIVARIANCE"]<=2
    assert counts["REGIME_COVARIANCE"]<=6
    assert counts["UNCERTAINTY_JACKKNIFE"]==8
    assert counts["DISAGREEMENT_ENSEMBLE"]==0
    assert budget.learned_total-base<=33,counts
    print({"synthetic_core":base,"synthetic_anchor_extra":budget.learned_total-base,"per_family_new_learned":counts})


def test_family_ff_source_is_output_specific_and_primary_hp_cache_is_shared():
    inputs,asof,support,primary=cold_input()
    current=ff_current(inputs,primary)
    e=EventRiskEstimator();budget=StateBudget(limit=100)
    base=e.qualify(inputs,as_of=asof,support_metadata=support,current_identity_proof=primary)
    extended=e.qualify(inputs,as_of=asof,support_metadata=support,current_identity_proof=current)
    assert base==extended
    cache=e.make_cache(inputs,as_of=asof,budget=budget)
    hp=fit(e,"SHR_HP",inputs,asof,support,primary,cache=cache)
    assert hp.status=="PASS_SYNTHETIC" and budget.learned_total==7
    again=fit(e,"SHR_HP",inputs,asof,support,current,cache=cache)
    assert again.status=="PASS_SYNTHETIC" and budget.learned_total==7
    np.testing.assert_array_equal(again.covariance,hp.covariance)
    before=budget.learned_total
    ff=fit(e,"FF48_HIERARCHICAL",inputs,asof,support,current,cache=cache)
    assert ff.status=="PASS_SYNTHETIC",ff.notes
    # Native min30 preprocessing and RH are independent from the full HP cohort.
    assert budget.learned_total-before<=8
    source=current["family_source_support_identity"]["FF48_HIERARCHICAL"]
    lineage=ff.notes["estimator_lineage"]
    assert lineage["source_support_identity_sha256"]==content_hash(source)
    assert lineage["structural_identity"]==e._current_lineage(current,source)
    assert lineage["source_support_identity_sha256"]!=hp.notes["estimator_lineage"]["source_support_identity_sha256"]
    assert ff.notes["full_HP_prior_state_id"]==again.risk_state_id
    assert ff.assets==inputs.assets and ff.coverage["S0"]["nominal_n"]==0


@pytest.mark.parametrize("defect",["missing","receipt","local_event","pin","future"])
def test_ff_family_source_rejected_before_shared_hp_learning(defect):
    inputs,asof,support,primary=cold_input();current=ff_current(inputs,primary)
    source=current["family_source_support_identity"]["FF48_HIERARCHICAL"]
    if defect=="missing":current=primary
    elif defect=="receipt":source["industry_source"]={"sha256":"e"*64}
    elif defect=="local_event":source["dependency_local_signature_sha256"]=""
    elif defect=="pin":source["source_pins"]["FF48"]="e"*64
    else:
        inputs=replace(inputs,industry_receipt=replace(inputs.industry_receipt,available_at=asof+pd.Timedelta(days=1)))
        current=ff_current(inputs,primary)
    e=EventRiskEstimator();budget=StateBudget(limit=100)
    state=fit(e,"FF48_HIERARCHICAL",inputs,asof,support,current,budget=budget)
    assert state.status=="BLOCKED" and state.covariance is None and state.assets==inputs.assets
    assert budget.learned_total==0
