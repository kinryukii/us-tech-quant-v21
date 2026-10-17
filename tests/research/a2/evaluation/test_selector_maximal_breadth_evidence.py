"""Synthetic-only C14 mixed-support evidence, final gate and diagnostic checks."""
from __future__ import annotations
import copy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as sut


def clock():
    cal = pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02",periods=n).to_numpy()
        for y,n in ((2023,250),(2024,252),(2025,250))]))
    return pd.DataFrame(dict(signal_date=cal,included=np.arange(752)<732))


def metadata():
    old=[f"OLD_{i}" for i in range(147)]; failed={f"OLD_BLOCKED_{i}":"RETAINED" for i in range(79)}
    return dict(research_id=sut.RESEARCH_ID,official_freeze=True,formal_freeze_applied=True,
        roles=list(sut.ROLES),target=sut.TARGET,mechanism_research_eligible=True,
        strict_PIT_promotion_eligible=False,test2026_locked=True,new2026_estimation_authorized=False,
        read2027_authorized=False,blocked_roles={r:"BLOCKED_BUDGET" for r in (*sut.DELTA,"C14_D12")},
        evaluation=dict(common_mature_date_count=732,original_calendar_dates=752,year_counts=sut.YEAR_COUNTS.copy(),
            progressive_mature_date_count=482,progressive_year_counts=sut.PROGRESSIVE_COUNTS.copy(),
            exposure_namespace=321,legacy=dict(numeric_ids=old,exposure_ids=old+list(failed),
                failed_or_untestable=failed),new_specs=sut.role_specs(),risk_specs=list(sut.RISK_SPECS),
            bootstrap=dict(method=sut.BOOT_METHOD,repeats=5000,block=20,seed=20260928,confidence=.95)))


def gate():
    return dict(status="FINAL_PIPELINES_FROZEN",research_id=sut.RESEARCH_ID,design_sha256="a"*64,
        all_training_terminal=True,capacity_selection_complete=True,roles=list(sut.ROLES),
        role_statuses={r:"COMPLETE" for r in sut.ROLES},score_assembly_sha256="b"*64,
        fit_ledger_sha256="c"*64,pair_key_sha256="d"*64,forecast2026_rows=0)


def assembly():
    return dict(status="SCORE_ASSEMBLY_COMPLETE",design_freeze_sha256="a"*64,pair_key_sha256="d"*64,
        complete_candidates=list(sut.MAIN),failed_or_untestable={r:"BLOCKED" for r in sut.DELTA},
        forecast2026_rows=0)


def series():
    c=clock();index=pd.DatetimeIndex(c.loc[c.included,"signal_date"]);ids=metadata()["evaluation"]["legacy"]["numeric_ids"]
    rng=np.random.default_rng(41)
    old=pd.DataFrame(rng.normal(0,.01,(732,147)),index=index,columns=ids);old.iloc[:,-1]=0
    prog=pd.Series(rng.normal(.004,.006,482),index=index[index.year>=2024])
    return c,old,prog,{**metadata()["evaluation"]["bootstrap"],"repeats":40}


def stats(old,new,c,rule,failed=None,**kwargs):
    return sut.statistics(old,new,c,rule,list(old),sut.role_specs(),failed,synthetic=True,**kwargs)


def test_formal_identity_all_75_and_twenty_risk_namespace():
    d=metadata();ev=sut.validate_design(d)
    assert len(sut.ROLES)==75 and len(sut.RISK_SPECS)==20 and ev["exposure_namespace"]==321
    assert sut.validate_final_pipeline_gate(d,gate(),assembly(),"a"*64)


@pytest.mark.parametrize("field,value",[
    ("official_freeze",False),("formal_freeze_applied",False),("target","ER_20D"),
    ("strict_PIT_promotion_eligible",True),("test2026_locked",False),
    ("new2026_estimation_authorized",True),("read2027_authorized",True),
    ("roles",list(sut.ROLES[:-1])),("research_id","C12_REPAIR")])
def test_no_identity_or_future_unlock(field,value):
    d=metadata();d[field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


@pytest.mark.parametrize("field,value",[
    ("common_mature_date_count",482),("original_calendar_dates",732),
    ("progressive_mature_date_count",230),("exposure_namespace",301),
    ("year_counts",{"2024":252,"2025":230}),("risk_specs",[])])
def test_fixed_clock_exposure_and_risk_hypotheses_not_trimmed(field,value):
    d=metadata();d["evaluation"][field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


def test_history_226_not_reset_to_147_and_blocked_not_numeric():
    d=metadata();d["evaluation"]["legacy"]["exposure_ids"]=d["evaluation"]["legacy"]["numeric_ids"]
    with pytest.raises(ValueError,match="HISTORY"):sut.validate_design(d)
    d=metadata();d["blocked_roles"][sut.DELTA[0]]="ALLOW_TRAIN"
    with pytest.raises(ValueError,match="BUDGET"):sut.validate_design(d)


@pytest.mark.parametrize("field,value",[
    ("repeats",100),("seed",1),("block",10),("confidence",.9),("method","circular")])
def test_bootstrap_contract_frozen(field,value):
    d=metadata();d["evaluation"]["bootstrap"][field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


def test_shape_alias_bootstrap_draws_is_lossless_not_new_method():
    a=metadata()["evaluation"]["bootstrap"];b=dict(a);b["draws"]=b.pop("repeats")
    assert sut.bootstrap_rule(a)==sut.bootstrap_rule(b)
    b["repeats"]=4
    with pytest.raises(ValueError,match="AMBIGUOUS"):sut.bootstrap_rule(b)


@pytest.mark.parametrize("mode",["missing_gate","unresolved","changed_design","changed_pair","future"])
def test_final_pipeline_gate_before_any_outcome_arrays(mode):
    d=metadata();g=gate();a=assembly()
    if mode=="missing_gate":g["status"]="TRAINING_RUNNING"
    elif mode=="unresolved":g["role_statuses"][sut.MAIN[0]]="RESERVED"
    elif mode=="changed_design":g["design_sha256"]="e"*64
    elif mode=="changed_pair":a["pair_key_sha256"]="e"*64
    else:a["forecast2026_rows"]=1
    with pytest.raises(ValueError):sut.validate_final_pipeline_gate(d,g,a,"a"*64)


def test_production_numeric_access_refused_before_formal_freeze():
    class Poison:
        def to_numpy(self,*a,**kw):raise AssertionError("NUMERIC_ACCESS_TOO_EARLY")
    d=metadata();d["formal_freeze_applied"]=False
    with pytest.raises(ValueError,match="FREEZE"):
        sut.statistics(Poison(),{},clock(),d["evaluation"]["bootstrap"],[],sut.role_specs(),
            design=d,gate=gate(),assembly=assembly(),expected_design_sha256="a"*64)


def test_no_new_numeric_reuses_exact_legacy_draws_and_maxima():
    c,old,_,rule=series()
    rows,receipt,maxima=stats(old,{},c,rule)
    _,_,oldreceipt,oldmax=sut.shared.shared_max_t(old.to_numpy(float),np.arange(732),[True]*147,
        {**rule,"family_candidates":147})
    np.testing.assert_array_equal(maxima,oldmax)
    assert receipt["shared_draw_sha256"]==oldreceipt["shared_draw_sha256"]
    assert receipt["critical_max_t"]==oldreceipt["critical_max_t"]
    assert receipt["numeric_complete_series"]==147 and receipt["exposure_namespace"]==321
    assert len(rows)==75 and all(row["pooled_edge"] is None for row in rows)
    assert len(receipt["risk_tests"])==20 and all(row["status"]=="FAILED_UNTESTABLE" for row in receipt["risk_tests"])


def test_progressive_482_same_draws_nonlower_threshold_and_2023_not_success():
    c,old,new,rule=series()
    rows,receipt,_=stats(old,{"C14_P01":new},c,rule)
    row=next(row for row in rows if row["candidate_id"]=="C14_P01")
    assert row["required_dates"]==482 and row["year_edges"]["2023"] is None
    assert row["year2023_counted_as_learning_success"] is False
    assert receipt["numeric_complete_series"]==148
    assert receipt["minimum_draw_wise_max_increment"]>=0
    assert receipt["critical_max_t"]>=receipt["legacy_critical_max_t"]
    assert row["pooled_edge"]==float(new.mean())


def test_masked_bootstrap_uses_actual_support_mass_not_732_divisor():
    x=np.array([1.,3.]);counts=np.array([[1,0],[0,3],[2,1]],float)
    expected=np.array([-1.,1.,-1./3]);expected-=expected.mean()
    np.testing.assert_allclose(sut.masked_bootstrap(x,counts),expected,rtol=0,atol=1e-15)
    with pytest.raises(ValueError,match="ZERO_FIXED_SUPPORT"):
        sut.masked_bootstrap(x,np.array([[0,0],[1,1]],float))


def test_full_support_extension_is_identical_to_original_single_column_kernel():
    c,old,_,rule=series();x=old.iloc[:,0].to_numpy(float)
    counts,drawsha,_=sut._draw_counts(np.arange(732),rule)
    boot=sut.masked_bootstrap(x,counts)
    lower,se,receipt,maxima=sut.shared.shared_max_t(x[:,None],np.arange(732),[True],{**rule,"family_candidates":1})
    np.testing.assert_allclose(boot/se[0],maxima,rtol=1e-14,atol=1e-14)
    assert drawsha==receipt["shared_draw_sha256"]
    assert boot.std(ddof=1)==pytest.approx(se[0],rel=1e-14)


@pytest.mark.parametrize("mode",["padded_2023","missing_day","nan","fake_failed_zero","future_clock","short_legacy","bad_domain","blocked_delta"])
def test_zero_padding_partial_window_future_and_namespace_fail_closed(mode):
    c,old,new,rule=series();ns={"C14_P01":new};failed=None
    if mode=="padded_2023":ns["C14_P01"]=new.reindex(old.index,fill_value=0)
    elif mode=="missing_day":ns["C14_P01"]=new.iloc[1:]
    elif mode=="nan":ns["C14_P01"]=new.copy();ns["C14_P01"].iloc[0]=np.nan
    elif mode=="fake_failed_zero":ns["C14_P01"]=new*0;failed={"C14_P01":"FAILED"}
    elif mode=="future_clock":c=c.copy();c.loc[751,"signal_date"]=pd.Timestamp("2026-01-02")
    elif mode=="short_legacy":old=old.iloc[1:]
    elif mode=="bad_domain":
        specs=sut.role_specs();specs[0]["domain"]="FULL_732"
        with pytest.raises(ValueError):sut.statistics(old,ns,c,rule,list(old),specs,synthetic=True)
        return
    else:ns={sut.DELTA[0]:new}
    with pytest.raises(ValueError):stats(old,ns,c,rule,failed)


def test_real_zero_edge_complete_policy_is_not_failed_zero_placeholder():
    c,old,new,rule=series()
    rows,receipt,_=stats(old,{"C14_P01":new*0},c,rule)
    row=next(row for row in rows if row["candidate_id"]=="C14_P01")
    assert row["status"]=="COMPLETE" and row["pooled_edge"]==0 and row["bootstrap_se"]==0
    assert row["simultaneous_lower_95"] is None and not row["supported"]


def test_matched_contrast_exact_endpoints_same_support_and_historical_tests_kept():
    c,old,new,rule=series();left=sut.HYBRIDS[0];cid=next(iter(sut.CONTRASTS))
    data={"C14_P01":new,left:new*.7,cid:new*.7-new}
    rows,r,_=stats(old,data,c,rule)
    assert r["numeric_complete_series"]==150
    assert next(row for row in rows if row["candidate_id"]==cid)["test_kind"]=="MATCHED_CONTRAST"
    data[cid]=data[cid]+.001
    with pytest.raises(ValueError,match="CONTRAST"):stats(old,data,c,rule)


def test_nonadditive_risk_owner_fractional_tail_and_shared_draws():
    c,old,_,rule=series();x=-.01+np.sin(np.arange(732))*.002;selected=x*.5
    counts,sha,draws=sut._draw_counts(np.arange(732),rule)
    observed,boot=sut.risk_bootstrap(x,selected,"CVAR",draws)
    fn=sut.risk_metrics._empirical_cvar_owner()
    expected=fn(-x[draws],alpha=.95)-fn(-selected[draws],alpha=.95);expected-=expected.mean()
    np.testing.assert_allclose(boot,expected,rtol=0,atol=1e-15)
    assert observed==pytest.approx(float(fn(-x,alpha=.95)-fn(-selected,alpha=.95)))
    down,db=sut.risk_bootstrap(x,selected,"DOWN",draws)
    assert down==pytest.approx(float(np.sqrt(np.mean(np.minimum(x,0)**2))*.5))
    assert np.isfinite(db).all() and counts.shape==(40,732)


def test_risk_twenty_namespace_missing_owner_blocks_without_fake_numeric():
    c,old,new,rule=series();full=pd.Series(.02+np.sin(np.arange(732))*.002,index=old.index)
    raw=pd.Series(-.01+np.cos(np.arange(732))*.001,index=old.index)
    proof=dict(status="PASS",source_receipt_sha256="f"*64,horizon_sessions=5,complete_dates=732,
        labels_mature_pre2026=True,native_shareholder_coordinate=True,predicted_risk_decreased=True)
    inputs={"C14_D01":dict(raw=raw,selected=raw*.5,qualification=proof)}
    rows,r,_=stats(old,{"C14_D01":full},c,rule,risk_inputs=inputs)
    assert r["numeric_complete_series"]==150 and r["exposure_namespace"]==321
    assert sum(row["status"]=="COMPLETE" for row in r["risk_tests"])==2
    assert r["hybrid_gate_risk_efficiency_inferential"] is False
    for bad in ("labels_mature_pre2026","native_shareholder_coordinate"):
        wrong=copy.deepcopy(inputs);wrong["C14_D01"]["qualification"][bad]=False
        with pytest.raises(ValueError,match="OWNER"):stats(old,{"C14_D01":full},c,rule,risk_inputs=wrong)
    wrong=copy.deepcopy(inputs);wrong["C14_D01"]["raw"]=raw.iloc[1:]
    with pytest.raises(ValueError,match="H5_CLOCK"):stats(old,{"C14_D01":full},c,rule,risk_inputs=wrong)


def diagnostic_pairs():
    ref=pd.DataFrame(dict(signal_date=pd.Timestamp("2024-01-03"),
        security_uid=[f"UID{i:02d}" for i in range(1,51)],raw_rank=np.arange(1,51)))
    return sut.pairs_owner.geometry(ref)


def test_pair_and_matching_regret_are_distinct_and_oracle_is_supplied_not_recomputed():
    p=diagnostic_pairs();y=np.full(200,.002);prediction=np.full(200,.003)
    matched=p.iloc[[0]].to_dict("records");oracle=pd.Series([.001],index=pd.to_datetime(["2024-01-03"]))
    daily,bins,ranks=sut.pair_diagnostics("C14_P01",p,prediction,y,matched,oracle,
        final_gate=gate(),expected_design_sha256="a"*64)
    assert daily.matching_utility.iloc[0]==pytest.approx(.002/20)
    assert daily.matching_regret.iloc[0]==pytest.approx(.001-.002/20)
    assert daily.pair_regret.iloc[0]==0 and daily.replacement_count.iloc[0]==1
    assert len(ranks)==2 and bins.date_pair_mass.sum()==1
    with pytest.raises(ValueError,match="FREEZE"):
        sut.pair_diagnostics("C14_P01",p,prediction,y,matched,oracle,final_gate={},expected_design_sha256="a"*64)


@pytest.mark.parametrize("kind,decision", [("probability","U1"),("quantile","U2"),("gaussian","U3")])
def test_probability_quantile_gaussian_fixed_semantics_and_no_calibration_fit(kind,decision):
    p=diagnostic_pairs();y=np.full(200,.002)
    prediction=np.full(200,.6) if kind=="probability" else (
        np.tile([-.001,.005,.003],(200,1)) if kind=="quantile" else np.tile([.004,.005],(200,1)))
    rows,_,_=sut.pair_diagnostics("C14_P19",p,prediction,y,[],pd.Series([.001],index=pd.to_datetime(["2024-01-03"])),
        kind=kind,decision=decision,final_gate=gate(),expected_design_sha256="a"*64)
    if kind=="probability":assert rows.brier.iloc[0]==pytest.approx(.16)
    elif kind=="quantile":
        assert rows.quantile_crossing_fraction.iloc[0]==1 and rows.q10_coverage.iloc[0]==0
    else:assert rows.replacement_count.iloc[0]==0 and rows.brier.iloc[0] is not None


def test_unavailable_pair_labels_do_not_drop_partners_or_make_regret_zero():
    p=diagnostic_pairs();y=np.full(200,.002);y[0]=np.nan
    rows,_,_=sut.pair_diagnostics("C14_P01",p,np.zeros(200),y,[],
        pd.Series([np.nan],index=pd.to_datetime(["2024-01-03"])),final_gate=gate(),expected_design_sha256="a"*64)
    assert rows.pair_count.iloc[0]==200 and rows.unavailable_label_pairs.iloc[0]==1
    assert pd.isna(rows.matching_regret.iloc[0]) and pd.isna(rows.pair_regret.iloc[0])


def test_training_coverage_is_measured_from_success_not_reserved_quota():
    plan={dim:dict(planned=["A","B"],slot_field="paradigm") for dim in sut.COVERAGE_DIMENSIONS}
    slots=[dict(paradigm="A",status="COMPLETE",backend_entered=True),
           dict(paradigm="B",status="RESERVED",backend_entered=False)]
    rows=sut.training_coverage_audit(plan,slots,{})
    assert len(rows)==12 and all(r["actual"]==1 and r["attempted"]==1 and r["coverage"]==.5 for r in rows)
    slots[1].update(status="FAILED",backend_entered=True)
    assert sut.training_coverage_audit(plan,slots,{})[0]["actual"]==1
    assert sut.training_coverage_audit(plan,slots,{})[0]["attempted"]==2


def test_chinese_report_units_risk_namespace_and_missing_coverage_explicit():
    payload=dict(status="C14_PARTIAL_INPUT_BLOCKED",tests=[dict(candidate_id="C14_P01",status="COMPLETE",
        pooled_edge=.001,simultaneous_lower_95=-.0003,bootstrap_se=.0004,year_edges={"2024":.001,"2025":.001},
        supported=False)],training_coverage_audit=[],risk_tests=[],remaining=["B bank BLOCKED"])
    text=sut.render_report(payload)
    assert "321" in text and "TRAINING_COVERAGE_AUDIT" in text and "10.0" in text and "-3.0" in text
    assert "DELTA8" in text and "2023零edge不算第三个学习成功年份" in text and "不能冒充净账户收益" in text


def membership_frames():
    c=clock();dates=np.repeat(c.signal_date.to_numpy(),50);rr=np.tile(np.arange(1,51),752)
    r=pd.DataFrame(dict(signal_date=dates,security_uid=[f"UID{i:02d}" for i in rr],raw_rank=rr,
        target=rr*.001,label_end_date=pd.to_datetime(dates)+pd.Timedelta(days=1),
        ticker=[f"T{i:02d}" for i in rr],U_t_fingerprint="FROZEN_FULL_U"))
    p=r[list(sut.shared.KEY)+["ticker","U_t_fingerprint"]].copy();p["rank"]=rr
    learned=p.signal_date.dt.year.ge(2024)
    p.loc[learned & r.raw_rank.eq(20),"rank"]=40;p.loc[learned & r.raw_rank.eq(40),"rank"]=20
    return c,r,p


def test_full_U_752_policy_raw_core10_and_2023_exactfallback_edge():
    c,r,p=membership_frames()
    rows=sut.membership_diagnostics("C14_P01",r,p,c,final_gate=gate(),expected_design_sha256="a"*64)
    assert len(rows)==752 and rows.loc[rows.year.eq(2023),"replacement_count"].eq(0).all()
    assert rows.loc[rows.year.eq(2023),"replacement_edge"].eq(0).all()
    assert rows.loc[rows.year.ge(2024),"replacement_count"].eq(1).all()
    assert rows.loc[rows.year.ge(2024),"raw_overlap"].eq(19).all()
    np.testing.assert_allclose(rows.loc[rows.year.ge(2024) & rows.common_mature_date,"replacement_edge"],.001)


@pytest.mark.parametrize("mode",["drop_row","drop_date","missing_uid","identity_swap","core10","over40","falsefallback"])
def test_membership_no_pool_or_date_shrink_identity_swap_or_boundary_violation(mode):
    c,r,p=membership_frames()
    if mode=="drop_row":p=p.iloc[:-1]
    elif mode=="drop_date":r=r.iloc[50:];p=p.iloc[50:]
    elif mode=="missing_uid":r.loc[0,"security_uid"]="";p.loc[0,"security_uid"]=""
    elif mode=="identity_swap":p.loc[0,"U_t_fingerprint"]="OTHER_UID_EPOCH"
    else:
        date=pd.Timestamp("2023-01-02") if mode=="falsefallback" else pd.Timestamp("2024-01-02")
        left,right=(1,41) if mode=="core10" else (19,41) if mode=="over40" else (20,40)
        a=p.signal_date.eq(date) & r.raw_rank.eq(left);b=p.signal_date.eq(date) & r.raw_rank.eq(right)
        ranks=(int(p.loc[a,"rank"].iloc[0]),int(p.loc[b,"rank"].iloc[0]))
        p.loc[a,"rank"]=ranks[1];p.loc[b,"rank"]=ranks[0]
    with pytest.raises(ValueError):
        sut.membership_diagnostics("C14_P01",r,p,c,final_gate=gate(),expected_design_sha256="a"*64)


def test_unmature_selected_label_is_null_diagnostic_without_changing_membership():
    c,r,p=membership_frames();date=c.loc[c.included & c.signal_date.dt.year.eq(2025),"signal_date"].iloc[-1]
    take=r.signal_date.eq(date) & r.raw_rank.eq(40);r.loc[take,"label_end_date"]=pd.Timestamp("2026-01-02")
    rows=sut.membership_diagnostics("C14_P01",r,p,c,final_gate=gate(),expected_design_sha256="a"*64)
    day=rows.loc[rows.signal_date.eq(date)].iloc[0]
    assert not day.common_mature_date and pd.isna(day.replacement_edge) and day.replacement_count==1


def test_risk_efficiency_cannot_skip_predicted_risk_receipt_or_zero_alpha_margin():
    c,old,_,rule=series();full=pd.Series(.02+np.sin(np.arange(732))*.001,index=old.index)
    raw=pd.Series(-.01+np.sin(np.arange(732))*.001,index=old.index)
    proof=dict(status="PASS",source_receipt_sha256="f"*64,horizon_sessions=5,complete_dates=732,
        labels_mature_pre2026=True,native_shareholder_coordinate=True)
    _,receipt,_=stats(old,{"C14_D01":full},c,rule,risk_inputs={"C14_D01":dict(raw=raw,selected=raw*.5,qualification=proof)})
    row=receipt["risk_efficiency"]["C14_D01"]
    assert not row["supported"] and not row["conditions"]["predicted_risk_decreased"]
    assert receipt["active_nonzero_se_columns"]==149


def test_gaussian_native_mixture_probability_drives_brier_not_moment_cdf():
    p=diagnostic_pairs();y=np.full(200,.002);values=np.tile([.004,.005],(200,1))
    oracle=pd.Series([.001],index=pd.to_datetime(["2024-01-03"]))
    kw=dict(kind="gaussian",decision="U3",final_gate=gate(),expected_design_sha256="a"*64)
    exact,bins,_=sut.pair_diagnostics("C14_P20",p,values,y,[],oracle,native_probability=np.full(200,.7),**kw)
    approx,_,_=sut.pair_diagnostics("C14_P20",p,values,y,[],oracle,**kw)
    assert exact.brier.iloc[0]==pytest.approx(.09)
    assert exact.brier.iloc[0]!=pytest.approx(approx.brier.iloc[0])
    assert exact.probability_coordinate.iloc[0]=="NATIVE_THREE_NORMAL_MIXTURE_CDF"
    assert approx.probability_coordinate.iloc[0]=="GAUSSIAN_MOMENT_APPROXIMATION"
    assert bins.prediction_mean.iloc[0]==pytest.approx(.7)
    assert exact.replacement_count.iloc[0]==approx.replacement_count.iloc[0]==0


@pytest.mark.parametrize("probability",[np.full(199,.7),np.full(200,np.nan),np.full(200,1.1)])
def test_gaussian_native_mixture_probability_has_finite_bounded_row_shape(probability):
    p=diagnostic_pairs()
    with pytest.raises(ValueError,match="MIXTURE_PROBABILITY"):
        sut.pair_diagnostics("C14_P20",p,np.tile([.004,.005],(200,1)),np.full(200,.002),[],
            pd.Series([.001],index=pd.to_datetime(["2024-01-03"])),kind="gaussian",decision="U3",
            native_probability=probability,final_gate=gate(),expected_design_sha256="a"*64)
