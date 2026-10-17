"""Generated-only diagnostics; no real data, model fit or account."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState,COORDINATE
from scripts.research.a2.risk.mechanism_risk_diagnostics import state_numerical_diagnostics,volatility_downside_diagnostic


def fixture():
    covariance=np.asarray([[.0004,.0001],[.0001,.0009]])
    state=RiskState("a"*64,pd.Timestamp("2024-01-02",tz="UTC"),pd.Timestamp("2023-12-29",tz="UTC"),
        ("A","B"),"GENERATED",COORDINATE,5,covariance,np.sqrt(np.diag(covariance)),
        {"A":{"uid":"SID_A"},"B":{"uid":"SID_B"}},{"A":50,"B":50},"TEST",2.8,.2,None,None,None,
        {"downside_second_moment":covariance*.5},None,(),{},"PASS_SYNTHETIC","RT")
    rows=[]
    for j,d in enumerate(pd.bdate_range("2024-02-01","2024-02-07",tz="UTC")):
        for a in state.assets:
            rows.append(dict(asset=a,origin_at=d,entry_at=d+pd.Timedelta(hours=1),endpoint_at=d+pd.Timedelta(days=5),
                matured_at=d+pd.Timedelta(days=5,hours=1),available_at=d+pd.Timedelta(days=5,hours=2),
                horizon=5,uid="SID_"+a,identity_epoch="TEST",source_identity="GENERATED_OBS",mechanism_coordinate_supported=True,
                return_value=(-1)**j*.01))
    return state,pd.DataFrame(rows)


def check(state,frame):return volatility_downside_diagnostic(state,frame,assets=state.assets,uids={"A":"SID_A","B":"SID_B"},reference_assets=state.assets,evaluation_end=pd.Timestamp("2026-01-01",tz="UTC"))


def test_covariance_numeric_native_and_rm_proxy_explicit():
    state,frame=fixture();out=state_numerical_diagnostics([state,replace(state,method="RM")])
    assert out[0]["status"]=="PASS_NUMERICAL_DIAGNOSTIC_ONLY" and out[0]["fit_year"]==2024
    assert out[0]["effective_N"]=={"A":50,"B":50}
    assert out[1]["native_horizon"] is False and out[1]["time_scale_proxy"] is True


def test_no_fit_fixed_q_realized_diagnostic_and_future_poison_invariance():
    state,frame=fixture();base=check(state,frame)
    future=frame.iloc[:1].copy()
    for c in ["origin_at","entry_at","endpoint_at","matured_at","available_at"]:future[c]+=pd.Timedelta(days=800)
    future["return_value"]="2026_VALUE_MUST_NOT_PARSE"
    assert check(state,pd.concat([frame,future],ignore_index=True))==base
    assert base["not_a_fitted_calibrator"] and base["not_input_feature"] and not base["account_qualified"]
    assert base["observed_source_identities"]==("GENERATED_OBS",)
    assert base["structural_overlap_N_over_H"]==1


@pytest.mark.parametrize("defect",["sid","quantity","nan","duplicate","future_eval"])
def test_invalid_legal_row_fails_closed(defect):
    state,frame=fixture()
    if defect=="sid":frame.loc[0,"uid"]="WRONG"
    elif defect=="quantity":frame.loc[0,"mechanism_coordinate_supported"]=False
    elif defect=="nan":frame.loc[0,"return_value"]=np.nan
    elif defect=="duplicate":frame=pd.concat([frame,frame.iloc[:1]],ignore_index=True)
    if defect=="future_eval":
        with pytest.raises(ValueError):volatility_downside_diagnostic(state,frame,assets=state.assets,uids={"A":"SID_A","B":"SID_B"},reference_assets=state.assets,evaluation_end=pd.Timestamp("2027-01-01",tz="UTC"))
    else:
        with pytest.raises(ValueError):check(state,frame)



def projection_fixture(days=("2024-02-01","2024-02-02","2024-02-05"),representation="R3"):
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    cal=pd.bdate_range("2023-12-20","2025-02-20")
    assets=("A","B","C");uids={a:"SID_"+a for a in assets};matrix=np.diag([.0004,.0009,.0016])
    q=np.asarray([.5,.5,0.]);predicted=float(np.sqrt(q@matrix@q))
    items=[];rows=[]
    for j,date in enumerate(days):
        day=pd.Timestamp(date);origin=_clock(day);i=cal.get_loc(day)
        request=dict(date=date,decision_at=origin,assets=assets,uids=uids,reference_assets=("A","B"),horizon=5,cohort="RAW_SUBSET")
        features=dict(portfolio_sigma=predicted)
        if representation=="R4":features["portfolio_downside_sigma"]=predicted/2
        if representation=="R7":features["group_features"]={"R4":{"portfolio_downside_sigma":predicted/2}}
        items.append(dict(request=request,representation=representation,
            state_refs={"PCA":{"verified":True,"risk_state_id":"pca-whole-state"}},
            projection=dict(reference_covariance=matrix,reference_weights=dict(zip(assets,q)),features=features,
                            diagnostics=dict(predicted_portfolio_sigma=predicted))))
        for a in ("A","B"):
            rows.append(dict(asset=a,origin_at=origin,entry_at=_clock(cal[i+1],opening=True),endpoint_at=_clock(cal[i+6],opening=True),
                matured_at=_clock(cal[i+6]),available_at=_clock(cal[i+6]),horizon=5,uid=uids[a],identity_epoch="GEN_EPOCH",
                source_identity="GENERATED_NATIVE",mechanism_coordinate_supported=True,return_value=(-.01,.02,-.005)[j%3]))
    return items,pd.DataFrame(rows)


def projection_check(items,rows):
    from scripts.research.a2.risk.mechanism_risk_diagnostics import projection_native_diagnostics
    return projection_native_diagnostics(items,rows,evaluation_end=pd.Timestamp("2026-01-01",tz="UTC"))


def test_exact_daily_reference_subset_not_annual_union_and_aggregation():
    items,rows=projection_fixture();out=projection_check(items,rows)
    assert all(r["status"]=="PASS_EXACT_MATURED_REFERENCE_DIAGNOSTIC_ONLY" for r in out["request_rows"])
    a=out["aggregate_rows"][0]
    assert a["nominal_N"]==3 and a["structural_overlap_N_over_H"]==.6
    assert a["observed_reference_sigma"]==pytest.approx(np.std([-.01,.02,-.005],ddof=1))
    assert a["predicted_sigma_rms"]==pytest.approx(items[0]["projection"]["features"]["portfolio_sigma"])
    assert a["predicted_downside_sigma_rms"] is None and a["downside_prediction_matched_N"]==0
    assert a["effective_IID_N_certified"] is False and not a["account_qualified"]
    # Annual-domain C is never demanded as an observed member of A/B reference.
    assert all(tuple(r["reference_assets"])==("A","B") for r in out["request_rows"])


def test_exact_projection_future_append_other_horizon_poison_invariance():
    items,rows=projection_fixture();base=projection_check(items,rows)
    future=rows.iloc[:1].copy()
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):future[c]+=pd.Timedelta(days=800)
    future["return_value"]="2026_VALUE_MUST_NOT_PARSE"
    other=rows.iloc[:1].copy();other["horizon"]=10;other["return_value"]="OTHER_HORIZON_MUST_NOT_PARSE"
    assert projection_check(items,pd.concat([rows,future,other],ignore_index=True))==base


@pytest.mark.parametrize("defect",["sid","quantity","quantity1","partial","duplicate","nonfinite","unmatured","sigma","weights","ref1","clock"])
def test_exact_daily_native_reference_fail_closed(defect):
    import copy
    items,rows=projection_fixture();items=copy.deepcopy(items)
    if defect=="sid":rows.loc[0,"uid"]="WRONG_SID"
    elif defect=="quantity":rows.loc[0,"mechanism_coordinate_supported"]=False
    elif defect=="quantity1":
        rows["mechanism_coordinate_supported"]=rows.mechanism_coordinate_supported.astype(object)
        rows.loc[0,"mechanism_coordinate_supported"]=1
    elif defect=="partial":rows=rows.drop(index=1).reset_index(drop=True)
    elif defect=="duplicate":rows=pd.concat([rows,rows.iloc[:1]],ignore_index=True)
    elif defect=="nonfinite":rows.loc[0,"return_value"]=np.nan
    elif defect=="unmatured":
        rows.loc[0,"available_at"]=pd.Timestamp("2026-01-01",tz="UTC")
        rows["return_value"]=rows.return_value.astype(object)
        rows.loc[0,"return_value"]="UNMATURED_BODY_MUST_NOT_PARSE"
    elif defect=="sigma":items[0]["projection"]["diagnostics"]["predicted_portfolio_sigma"]*=2
    elif defect=="weights":items[0]["projection"]["reference_weights"]["A"]=1.
    elif defect=="ref1":items[0]["state_refs"]["PCA"]["verified"]=1
    elif defect=="clock":items[0]["request"]["decision_at"]+=pd.Timedelta(hours=1)
    out=projection_check(items,rows)
    assert out["request_rows"][0]["status"]=="BLOCKED_REFERENCE_DIAGNOSTIC"
    assert "realized_reference_return" not in out["request_rows"][0]
    assert out["aggregate_rows"][0]["blocked_requests"]==1


def test_reference_cohort_not_reused_at_other_origin_and_duplicate_request_rejected():
    import copy
    items,rows=projection_fixture();single=copy.deepcopy(items[:1])
    # Only a later day's cohort observations exist; do not move them to prior origin.
    out=projection_check(single,rows.loc[rows.origin_at.ne(single[0]["request"]["decision_at"])].reset_index(drop=True))
    assert out["request_rows"][0]["reason"]=="INCOMPLETE_EXACT_NATIVE_REFERENCE_BASKET"
    out=projection_check(single+copy.deepcopy(single),rows)
    assert all(r["reason"]=="DUPLICATE_REFERENCE_REQUEST" for r in out["request_rows"])


def test_projection_tail_source_owned_r4_r7_and_year_is_origin_year():
    for representation in ("R4","R7"):
        items,rows=projection_fixture(representation=representation);out=projection_check(items,rows)
        a=out["aggregate_rows"][0]
        assert a["downside_prediction_matched_N"]==3
        assert a["predicted_downside_sigma_rms"]==pytest.approx(a["predicted_sigma_rms"]/2)
        assert a["matched_observed_downside_sigma"]==pytest.approx(np.sqrt((.01**2+.005**2)/3))
        if representation=="R7":assert all(r["downside_basis"]=="R4_SOURCE_OWNED_TAIL_STATE" for r in out["request_rows"])
    items,rows=projection_fixture(days=("2024-12-30","2025-01-02"));out=projection_check(items,rows)
    assert {a["year"] for a in out["aggregate_rows"]}=={2024,2025}
    assert all(r["status"]=="PASS_EXACT_MATURED_REFERENCE_DIAGNOSTIC_ONLY" for r in out["request_rows"])


def test_projection_2026_origin_and_end_never_read_bodies():
    import copy
    from scripts.research.a2.risk.mechanism_risk_diagnostics import projection_native_diagnostics
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    items,rows=projection_fixture();items=copy.deepcopy(items[:1])
    items[0]["request"].update(date="2026-01-02",decision_at=_clock(pd.Timestamp("2026-01-02")))
    rows["return_value"]="NO_2026_READ"
    out=projection_check(items,rows)
    assert out["request_rows"][0]["reason"]=="EXACT_REQUEST_ORIGIN_CLOCK_REQUIRED"
    with pytest.raises(ValueError,match="PRE2026"):
        projection_native_diagnostics(items,rows,evaluation_end=pd.Timestamp("2027-01-01",tz="UTC"))
