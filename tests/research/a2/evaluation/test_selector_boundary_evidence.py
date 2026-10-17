"""Synthetic C12 cumulative inference, partial diagnostics and gated oracle."""
from __future__ import annotations
import copy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_boundary_evidence as sut


def metadata():
    older=[f"OLD_{i}" for i in range(137)];older_failed={f"FAILED_{i}":"RETAINED" for i in range(12)}
    blocked={r:"BLOCKED_SHARED_RISK" for r in sut.c11.B_ROLES}
    sources={"synthetic_source.py":"f"*64}
    c11=dict(official_freeze=True,formal_freeze_applied=True,research_id=sut.c11.RESEARCH_ID,
        roles=list(sut.c11.ROLES),target=sut.TARGET,primary_eval_years=list(sut.YEARS),
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        new2026_estimation_authorized=False,blocked_roles=blocked,sources=sources,
        evaluation=dict(primary=sut.PRIMARY,common_mature_date_count=732,year_counts=sut.YEAR_COUNTS.copy(),
            original_calendar_dates=752,exposure_namespace=169,numeric_ceiling=157,sanity_diagnostic_only=True,
            bootstrap=dict(method=sut.BOOT_METHOD,repeats=5000,seed=20260928,confidence=.95,family_candidates=157),
            inherited_selection_requirements=dict(pooled_edge_positive=True,year2025_edge_positive=True,
                positive_years_min=2,simultaneous_lower_bound_gt_zero=True),
            legacy=dict(numeric_ids=older,exposure_ids=older+list(older_failed),failed_or_untestable=older_failed)))
    complete=list((*sut.c11.A_ROLES,*sut.c11.SANITY_ROLES))
    assembly=dict(status="SCORE_ASSEMBLY_COMPLETE",complete_candidates=complete,failed_or_untestable=blocked,
        forecast2026_rows=0,design_freeze_sha256="e"*64)
    legacy=dict(design={"sha256":"e"*64},numeric_ids=older+complete,
        exposure_ids=older+list(older_failed)+list(sut.c11.ROLES),
        failed_or_untestable={**older_failed,**blocked},sources=sources)
    design=dict(official_freeze=True,formal_freeze_applied=True,research_id=sut.RESEARCH_ID,
        roles=list(sut.ROLES),target=sut.TARGET,primary_eval_years=list(sut.YEARS),
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        new2026_estimation_authorized=False,
        evaluation=dict(primary=sut.PRIMARY,common_mature_date_count=732,year_counts=sut.YEAR_COUNTS.copy(),
            original_calendar_dates=752,exposure_namespace=178,numeric_ceiling=156,
            bootstrap=dict(method=sut.BOOT_METHOD,repeats=5000,seed=20260928,confidence=.95,family_candidates=156),
            inherited_selection_requirements=dict(pooled_edge_positive=True,year2025_edge_positive=True,
                positive_years_min=2,simultaneous_lower_bound_gt_zero=True),legacy=legacy))
    return design,c11,assembly,legacy


def clocks():
    calendar=pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02",periods=n).to_numpy()
        for y,n in ((2023,250),(2024,252),(2025,250))]))
    positions=np.arange(732)
    return calendar,positions,calendar[positions]


def series():
    calendar,positions,index=clocks();ids=metadata()[3]["numeric_ids"]
    rng=np.random.default_rng(73)
    old=pd.DataFrame(rng.normal(0,.02,(732,147)),index=index,columns=ids)
    old[sut.c11.SANITY_ROLES[1]]=0.
    new=pd.DataFrame(rng.normal(.01,.02,(732,9)),index=index,columns=sut.ROLES)
    rule={**metadata()[0]["evaluation"]["bootstrap"],"repeats":40}
    return calendar,positions,ids,old,new,rule


def reference():
    rows=[]
    for date in pd.to_datetime(["2025-01-03","2025-01-06"]):
        for rank in range(1,51):
            rows.append(dict(signal_date=date,security_uid=f"UID{rank:02d}",raw_rank=rank,
                raw_score=-rank,target=.002*rank,label_end_date=date+pd.Timedelta(days=28)))
    return pd.DataFrame(rows)


def panel_and_pairs(ref,role=None):
    role=role or sut.ROLES[1]
    panels,ps,values,matched=[],[],[],[]
    for _,g in ref.groupby("signal_date",sort=True):
        pairs=sut.pairs_owner.geometry(g)
        score=np.zeros(len(pairs))
        score[(pairs.challenger_raw_rank.eq(40)&pairs.incumbent_raw_rank.eq(20)).to_numpy()]=.03
        panel=sut.pairs_owner.resolve(g,pairs,score,role)
        panels.append(panel);ps.append(pairs);values.append(score);matched.extend(panel.attrs["matched_pairs"])
    return pd.concat(panels,ignore_index=True),pd.concat(ps,ignore_index=True),np.concatenate(values),matched


def gate():
    return dict(status="FINAL_PIPELINES_FROZEN",research_id=sut.RESEARCH_ID,
        all_training_terminal=True,capacity_selection_complete=True,roles=list(sut.ROLES),
        role_statuses={r:"PARTIAL_INPUT_BLOCKED" for r in sut.ROLES},design_sha256="b"*64)


def test_formal_identity_and_c11_metadata_only_lineage():
    d,old,assembly,legacy=metadata()
    assert sut.validate_design(d)["exposure_namespace"]==178
    assert sut.validate_legacy_metadata(old,assembly,legacy)["exposure_namespace"]==169
    legacy["failed_or_untestable"].pop(sut.c11.B_ROLES[0])
    with pytest.raises(ValueError,match="LINEAGE"):sut.validate_legacy_metadata(old,assembly,legacy)


@pytest.mark.parametrize("field,value",[("official_freeze",False),("formal_freeze_applied",False),
    ("research_id","OTHER"),("roles",list(sut.ROLES[:8])),("target","ER_20D"),
    ("primary_eval_years",[2025]),("strict_PIT_promotion_eligible",True),
    ("test2026_locked",False),("new2026_estimation_authorized",True)])
def test_identity_and_future_lock_cannot_change(field,value):
    d=metadata()[0];d[field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


@pytest.mark.parametrize("field,value",[("original_calendar_dates",230),("common_mature_date_count",230),
    ("exposure_namespace",156),("numeric_ceiling",178),("year_counts",{"2025":230})])
def test_no_relabeling_partial_window_as_common(field,value):
    d=metadata()[0];d["evaluation"][field]=value
    with pytest.raises(ValueError):sut.validate_design(d)


@pytest.mark.parametrize("field,value",[("repeats",100),("seed",1),("confidence",.9),
    ("family_candidates",9),("method","circular")])
def test_production_max_t_fixed(field,value):
    d=metadata()[0];d["evaluation"]["bootstrap"][field]=value
    with pytest.raises(ValueError,match="MAXT"):sut.validate_design(d)


def test_empty_new_numeric_preserves_147_178_without_zero_or_partial_support():
    calendar,positions,ids,old,new,rule=series()
    empty=pd.DataFrame(index=old.index)
    failure={r:"EARLY_RAW_IDENTITY_BLOCKED" for r in sut.ROLES}
    matrix,rows,receipt,maxima=sut.statistics(old,empty,positions,calendar,rule,ids,failure,synthetic=True)
    pd.testing.assert_frame_equal(matrix,old)
    assert receipt["numeric_complete_series"]==147 and receipt["exposure_namespace"]==178
    assert receipt["critical_max_t"]==receipt["legacy_critical_max_t"]
    assert receipt["minimum_draw_wise_max_increment"]==0.
    assert len(rows)==9 and all(not t["supported"] and t["pooled_edge"] is None
        and all(v is None for v in t["year_edges"].values()) for t in rows)
    assert all(t["failure_reason"]=="EARLY_RAW_IDENTITY_BLOCKED" for t in rows)


def test_full_156_numeric_reuses_same_draws_and_threshold_cannot_fall():
    calendar,positions,ids,old,new,rule=series()
    matrix,rows,receipt,maxima=sut.statistics(old,new,positions,calendar,rule,ids,synthetic=True)
    assert matrix.shape==(732,156) and len(rows)==9
    assert receipt["shared_draw_sha256"]==receipt["legacy_shared_draw_sha256"]
    assert receipt["minimum_draw_wise_max_increment"]>=-1e-12
    assert receipt["critical_max_t"]>=receipt["legacy_critical_max_t"]-1e-12


@pytest.mark.parametrize("mode",["partial_index","partial_nans","fake_failed_zero","future_calendar","clock_drop","position_swap"])
def test_partial_series_future_or_fake_failed_zero_rejected(mode):
    calendar,positions,ids,old,new,rule=series();failed={}
    if mode=="partial_index":new=new.loc[new.index.year==2025]
    elif mode=="partial_nans":new.iloc[:502]=np.nan
    elif mode=="fake_failed_zero":new[sut.ROLES[0]]=0.;failed={sut.ROLES[0]:"BLOCKED"}
    elif mode=="future_calendar":calendar=pd.DatetimeIndex(list(calendar[:-1])+[pd.Timestamp("2026-01-02")])
    elif mode=="clock_drop":calendar=calendar[:-1]
    else:positions=positions.copy();positions[[1,2]]=positions[[2,1]]
    with pytest.raises(ValueError):sut.statistics(old,new,positions,calendar,rule,ids,failed,synthetic=True)


def test_daily_geometry_replacement_edge_and_continuous_policy_turnover():
    ref=reference();panel,_,_,_=panel_and_pairs(ref)
    daily=sut.daily_diagnostics(sut.ROLES[1],ref,panel)
    assert daily.replacement_count.eq(1).all() and daily.raw_overlap.eq(.95).all()
    np.testing.assert_allclose(daily.replacement_edge,.002)
    np.testing.assert_allclose(daily.selected_replacement_realized_edge,.04)
    assert pd.isna(daily.membership_turnover.iloc[0]) and daily.membership_turnover.iloc[1]==0.
    yearly,hist=sut.summarize_diagnostics(daily)
    assert len(hist)==11 and hist.loc[hist.replacement_count.eq(1),"dates"].iloc[0]==2
    assert hist.dates.sum()==2 and yearly.descriptive_only.all()


@pytest.mark.parametrize("mode",["drop_uid","drop_core","pick_over40","future_label"])
def test_full_U_or_boundary_violation_and_unmature_labels(mode):
    ref=reference();panel,_,_,_=panel_and_pairs(ref)
    if mode=="drop_uid":panel=panel.iloc[:-1]
    elif mode in ("drop_core","pick_over40"):
        date=panel.signal_date.iloc[0]
        selected_uid="UID01" if mode=="drop_core" else "UID19"
        target_uid="UID41"
        oldrank=panel.loc[panel.signal_date.eq(date)&panel.security_uid.eq(selected_uid),"rank"].iloc[0]
        otherrank=panel.loc[panel.signal_date.eq(date)&panel.security_uid.eq(target_uid),"rank"].iloc[0]
        panel.loc[panel.signal_date.eq(date)&panel.security_uid.eq(selected_uid),"rank"]=otherrank
        panel.loc[panel.signal_date.eq(date)&panel.security_uid.eq(target_uid),"rank"]=oldrank
    else:
        ref.loc[ref.security_uid.eq("UID40"),"label_end_date"]=pd.Timestamp("2026-01-02")
        daily=sut.daily_diagnostics(sut.ROLES[1],ref,panel)
        assert not daily.common_mature_date.any() and daily.replacement_edge.isna().all()
        return
    with pytest.raises(ValueError):sut.daily_diagnostics(sut.ROLES[1],ref,panel)


def pair_truth(ref,p):
    lookup=ref.set_index(["signal_date","security_uid"]).target
    return np.array([lookup.loc[(d,e)]-lookup.loc[(d,i)] for d,e,i in p[["signal_date","challenger_uid","incumbent_uid"]].itertuples(index=False,name=None)])


def test_pair_calibration_regret_matching_rank_distribution_and_partial_label_nulls():
    ref=reference();_,p,s,m=panel_and_pairs(ref);y=pair_truth(ref,p)
    daily,bins,ranks=sut.pair_diagnostics(sut.ROLES[1],p,s,y,m)
    assert daily.pair_count.eq(200).all() and daily.replacement_count.eq(1).all()
    assert daily.pair_sign_accuracy.eq(.005).all()
    np.testing.assert_allclose(daily.selected_replacement_realized_edge,.04)
    assert bins.groupby("signal_date").date_pair_mass.sum().eq(1.).all()
    assert set(ranks.loc[ranks.side.eq("challenger"),"raw_rank"])=={40}
    assert set(ranks.loc[ranks.side.eq("incumbent"),"raw_rank"])=={20}
    y[0]=np.nan
    daily,bins,_=sut.pair_diagnostics(sut.ROLES[1],p,s,y,m)
    assert pd.isna(daily.pair_regret.iloc[0]) and daily.unavailable_label_pairs.iloc[0]==1
    assert len(bins.signal_date.unique())==1


def test_logit_calibration_uses_probability_and_strict_half_threshold():
    ref=reference();_,p,_,_=panel_and_pairs(ref)
    pred=np.full(len(p),.5);truth=np.zeros(len(p))
    daily,bins,_=sut.pair_diagnostics(sut.ROLES[0],p,pred,truth,[])
    assert daily.pair_sign_accuracy.eq(1).all() and daily.brier_score.eq(.25).all()
    assert daily.pair_regret.eq(0).all()
    assert bins.realized_positive_rate.eq(0).all()


def test_quantile_and_multitask_diagnostics_preserve_actual_output_semantics():
    ref=reference();_,p,score,_=panel_and_pairs(ref);truth=pair_truth(ref,p)
    q=np.column_stack([np.full(len(p),.02),np.full(len(p),-.01),np.full(len(p),.01)])
    daily,_,_=sut.pair_diagnostics(sut.ROLES[8],p,q,truth,[])
    assert daily.quantile_crossing_fraction.eq(1).all() and daily.replacement_count.eq(0).all()
    np.testing.assert_allclose(daily.pair_regret,[truth[:200].mean(),truth[200:].mean()])
    h=np.column_stack([score-.003,score-.001,score+.001,score+.003])
    daily,_,_=sut.pair_diagnostics(sut.ROLES[7],p,score,truth,[],h)
    assert daily.horizon_prediction_disagreement_mean.gt(0).all()
    with pytest.raises(ValueError,match="EQUAL_FOUR_HORIZON"):
        sut.pair_diagnostics(sut.ROLES[7],p,score,truth,[],h+.01)


def test_oracle_is_only_post_final_training_freeze_and_keeps_raw_core():
    ref=reference()
    ref.loc[ref.raw_rank.le(10),"target"]=-10.
    result=sut.oracle_headroom(ref,gate())
    np.testing.assert_allclose(result.boundary_oracle_headroom,.02)
    assert result.oracle_replacement_count.eq(10).all() and result.diagnostic_only.all()
    assert not result.selector_eligible.any() and not result.used_for_capacity_selection.any()


@pytest.mark.parametrize("field,value",[("status","TRAINING"),("all_training_terminal",False),
    ("capacity_selection_complete",False),("roles",list(sut.ROLES[:8])),
    ("role_statuses",{r:"RUNNING" for r in sut.ROLES}),("design_sha256","not_a_pin")])
def test_oracle_cannot_precede_fit_or_capacity_completion(field,value):
    frozen=gate();frozen[field]=value
    with pytest.raises(ValueError,match="FINAL_PIPELINES_FREEZE"):
        sut.oracle_headroom(reference(),frozen)


def test_oracle_unknown_boundary_label_not_silently_dropped():
    ref=reference();ref.loc[ref.raw_rank.eq(40),"target"]=np.nan
    rows=sut.oracle_headroom(ref,gate())
    assert rows.boundary_oracle_headroom.isna().all() and not rows.common_boundary_labels_mature.any()
