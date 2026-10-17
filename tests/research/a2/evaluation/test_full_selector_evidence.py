"""Pure synthetic full-selector statistics; no research readers."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import full_selector_evidence as e

def clock(n=60):
    d=pd.bdate_range("2024-01-02",periods=n)
    return pd.DataFrame(dict(signal_date=d,alpha_full_mature=np.ones(n,bool),
        alpha_learned_mature=np.ones(n,bool),h5_endpoint_calendar_available=np.ones(n,bool)))

def test_fixed_roster95_and321_metric_endpoints():
    specs=e.endpoint_specs()
    assert len(specs)==321
    assert len({s["contrast_id"] for s in specs})==95
    assert sum(s["metric"]=="ALPHA" for s in specs)==95
    assert sum(s["metric"] in ("DOWN","CVAR") for s in specs)==36

def test_shared_maximum_equals_original_mean_owner_on_same_draws():
    c=clock();d=pd.DatetimeIndex(c.signal_date);r=np.random.default_rng(7)
    values=r.normal(.002,.03,(len(d),2))
    specs=[s for s in e.endpoint_specs() if s["metric"]=="ALPHA"][:2]
    inp={s["endpoint_id"]:pd.Series(values[:,j],index=d) for j,s in enumerate(specs)}
    summary,receipt,maxima=e.paired_statistics(c,inp,{},synthetic=True,repeats=50)
    rule=dict(repeats=50,seed=20260928,confidence=.95,family_candidates=2)
    lower,se,old,expected=e.shared.shared_max_t(values,np.arange(len(d)),[True,True],rule)
    assert receipt["shared_draw_sha256"]==old["shared_draw_sha256"]
    np.testing.assert_allclose(maxima,np.maximum(expected,0.))
    for j,s in enumerate(specs):
        row=summary.loc[summary.endpoint_id.eq(s["endpoint_id"])].iloc[0]
        assert row.bootstrap_se==pytest.approx(se[j])
        assert row.lower==pytest.approx(lower[j])

def test_constant_observed_gain_zero_se_never_supported_and_missing_not_numeric():
    c=clock();d=pd.DatetimeIndex(c.signal_date);s=e.endpoint_specs()[0]
    out,receipt,_=e.paired_statistics(c,{s["endpoint_id"]:pd.Series(.01,index=d)}, {},synthetic=True,repeats=20)
    row=out.iloc[0]
    assert row.observed==pytest.approx(.01) and not row.supported and pd.isna(row.lower)
    assert receipt["numeric_endpoints"]==1 and len(out)==321
    assert out.iloc[1].status=="NO_COMPLETE_QUALIFIED_PAIRED_ENDPOINT"

def test_partial_or_nonfinite_endpoint_is_rejected_before_bootstrap_mean():
    c=clock();d=pd.DatetimeIndex(c.signal_date);s=e.endpoint_specs()[0]
    for series in (pd.Series(np.ones(len(d)-1),index=d[:-1]),pd.Series(np.r_[np.nan,np.ones(len(d)-1)],index=d)):
        with pytest.raises(ValueError,match="NO_PARTIAL"):
            e.paired_statistics(c,{s["endpoint_id"]:series},{},synthetic=True,repeats=5)

def test_2026_clock_cannot_enter_even_synthetic_evaluation():
    c=clock();c.loc[len(c)-1,"signal_date"]=pd.Timestamp("2026-01-02")
    with pytest.raises(ValueError,match="PRE2026"):
        e.paired_statistics(c,{}, {},synthetic=True,repeats=5)

def test_realized_tail_is_nonadditive_original_cvar():
    x=np.r_[np.full(29,.01),-.6]
    metric=e._risk_function(x,"CVAR")
    assert metric==e.metrics._empirical_cvar_owner()(-x,alpha=.95)
    assert e._risk_function(x,"DOWN")==pytest.approx(np.sqrt(.36/30))


def test_positive_pooled_statistic_cannot_hide_negative_annual_direction():
    c=clock(400);d=pd.DatetimeIndex(c.signal_date);s=e.endpoint_specs()[0]
    r=np.random.default_rng(19)
    values=r.normal(.03,.01,len(d))
    values[d.year==2025]=r.normal(-.001,.0001,int((d.year==2025).sum()))
    out,_,_=e.paired_statistics(c,{s["endpoint_id"]:pd.Series(values,index=d)}, {},synthetic=True,repeats=20)
    row=out.iloc[0]
    assert row.observed>0 and row.annual_mean["2025"]<0
    assert not row.annual_direction_pass and not row.supported

def qualifications(c,*roles):
    return {role:dict(policy_id=role,status="PASS",research_accounting_qualified=True,complete_window=True,
        sessions=len(c),calendar_sha256=e._calendar_digest(pd.DatetimeIndex(c.signal_date))) for role in roles}


def complete_clock():
    dates=pd.DatetimeIndex(np.concatenate([pd.bdate_range(str(y)+"-01-02",periods=n).to_numpy() for y,n in ((2023,250),(2024,252),(2025,250))]))
    full=np.ones(len(dates),bool);full[-20:]=False
    h5=np.ones(len(dates),bool);h5[-5:]=False
    return pd.DataFrame(dict(signal_date=dates,alpha_full_mature=full,alpha_learned_mature=full&(dates.year>=2024),h5_endpoint_calendar_available=h5))


def test_learned_support_cannot_include_fallback_or_unmature_dates():
    c=clock();c.loc[0,"alpha_full_mature"]=False
    with pytest.raises(ValueError,match="SUBSET_OF_FULL_MATURE"):e._dates(c,synthetic=True)
    c=clock();c.loc[0,"signal_date"]=pd.Timestamp("2023-12-29")
    with pytest.raises(ValueError,match="2024_2025_ONLY"):e._dates(c,synthetic=True)


def test_actual_gate_requires_frozen_support_hash_and_no_outer_feedback():
    c=complete_clock();design=dict(research_id=e.ID,evaluation=dict(rule=e.RULE,clock_sha256="wrong"))
    terminal=dict(status="ALL_POLICIES_FROZEN_BEFORE_OUTCOMES",research_id=e.ID,all_training_terminal=True,outer_result_feedback=False)
    with pytest.raises(ValueError,match="EXACT_SUPPORT_CLOCK"):e.paired_statistics(c,{}, {},design=design,terminal=terminal)
    design["evaluation"]["clock_sha256"]=e.clock_digest(c);terminal["outer_result_feedback"]=True
    with pytest.raises(ValueError,match="TERMINAL_POLICY_GATE"):e.paired_statistics(c,{}, {},design=design,terminal=terminal)


def test_unqualified_account_endpoint_remains_exposure_only():
    c=clock(400);d=pd.DatetimeIndex(c.signal_date);spec=next(s for s in e.endpoint_specs() if s["metric"]=="TOTAL_NETLOG")
    inp={spec["endpoint_id"]:pd.Series(.01+np.sin(np.arange(len(d)))*.001,index=d)}
    out,receipt,_=e.paired_statistics(c,inp,{},synthetic=True,repeats=20)
    row=out.loc[out.endpoint_id.eq(spec["endpoint_id"])].iloc[0]
    assert receipt["numeric_endpoints"]==0 and row.status=="FULL_WINDOW_PAIRED_ACCOUNT_QUALIFICATION_REQUIRED" and not row.supported
    q=qualifications(c,spec["candidate"],spec["reference"]);q[spec["candidate"]]["calendar_sha256"]="other_window"
    _,receipt,_=e.paired_statistics(c,inp,{},synthetic=True,repeats=20,account_qualifications=q)
    assert receipt["numeric_endpoints"]==0


def test_dual_nav_economic_support_needs_both_simultaneous_lowers():
    c=clock(400);d=pd.DatetimeIndex(c.signal_date);spec=next(s for s in e.endpoint_specs() if s["metric"]=="TOTAL_NETLOG")
    rng=np.random.default_rng(31);total=rng.normal(.003,.0001,len(d));liquid=rng.normal(0,.03,len(d))
    for year in (2024,2025):
        mask=d.year==year;liquid[mask]-=liquid[mask].mean();liquid[mask]+=1e-6
    inp={spec["endpoint_id"]:pd.Series(total,index=d),spec["contrast_id"]+"|LIQUID_NETLOG":pd.Series(liquid,index=d)}
    out,_,_=e.paired_statistics(c,inp,{},synthetic=True,repeats=50,account_qualifications=qualifications(c,spec["candidate"],spec["reference"]))
    pair=out.loc[out.contrast_id.eq(spec["contrast_id"]) & out.metric.isin(("TOTAL_NETLOG","LIQUID_NETLOG"))]
    assert pair.annual_direction_pass.all() and pair.loc[pair.metric.eq("TOTAL_NETLOG"),"lower"].iloc[0]>0
    assert pair.loc[pair.metric.eq("LIQUID_NETLOG"),"lower"].iloc[0]<0
    assert not pair.dual_nav_simultaneous_positive.any() and not pair.supported.any()


def test_paired_account_other_nav_missing_cannot_pass():
    c=clock(400);d=pd.DatetimeIndex(c.signal_date);spec=next(s for s in e.endpoint_specs() if s["metric"]=="TOTAL_NETLOG")
    inp={spec["endpoint_id"]:pd.Series(.01+np.sin(np.arange(len(d)))*.001,index=d)}
    out,_,_=e.paired_statistics(c,inp,{},synthetic=True,repeats=30,account_qualifications=qualifications(c,spec["candidate"],spec["reference"]))
    row=out.loc[out.endpoint_id.eq(spec["endpoint_id"])].iloc[0]
    assert row.lower>0 and not row.supported and not row.dual_nav_simultaneous_positive


def test_masked_master_draw_uses_actual_mass_not_zero_padded_mean():
    c=clock(80);mask=np.arange(len(c))%3!=0;c.alpha_full_mature=mask;c.alpha_learned_mature=mask
    d=pd.DatetimeIndex(c.signal_date);spec=next(s for s in e.endpoint_specs() if s["metric"]=="ALPHA")
    values=np.sin(np.arange(mask.sum()))*.03+.002
    out,receipt,_=e.paired_statistics(c,{spec["endpoint_id"]:pd.Series(values,index=d[mask])},{},synthetic=True,repeats=35)
    counts,sha,_=e.mixed._draw_counts(np.arange(len(c)),dict(repeats=35,seed=20260928))
    expected=e.mixed.masked_bootstrap(values,counts[:,mask]);row=out.loc[out.endpoint_id.eq(spec["endpoint_id"])].iloc[0]
    assert row.bootstrap_se==pytest.approx(expected.std(ddof=1)) and receipt["shared_draw_sha256"]==sha
    padded=np.zeros(len(c));padded[mask]=values-values.mean();wrong=counts@padded/len(c);wrong-=wrong.mean()
    assert not np.isclose(row.bootstrap_se,wrong.std(ddof=1))


@pytest.mark.parametrize("metric",["DOWN","CVAR"])
def test_h5_nonlinear_function_recomputed_on_same_masked_multiset(metric):
    c=clock(80);c.h5_endpoint_calendar_available=np.arange(len(c))<73
    d=pd.DatetimeIndex(c.signal_date);mask=c.h5_endpoint_calendar_available.to_numpy();a=np.sin(np.arange(mask.sum()))*.02;a[6]=-.3;b=a*.8
    inp={"HGB":pd.Series(a,index=d[mask]),"RISK_DIAG":pd.Series(b,index=d[mask])}
    out,_,_=e.paired_statistics(c,{},inp,synthetic=True,repeats=25)
    counts,_,_=e.mixed._draw_counts(np.arange(len(c)),dict(repeats=25,seed=20260928))
    observed=e._risk_function(a,metric)-e._risk_function(b,metric)
    boot=[]
    for row in counts[:,mask].astype(int):
        ix=np.repeat(np.arange(mask.sum()),row);boot.append(e._risk_function(a[ix],metric)-e._risk_function(b[ix],metric)-observed)
    boot=np.asarray(boot);boot-=boot.mean()
    row=out.loc[out.endpoint_id.eq("RISK_DIAG__VS_HGB|"+metric)].iloc[0]
    assert row.observed==pytest.approx(observed) and row.bootstrap_se==pytest.approx(boot.std(ddof=1))


def test_account_netlog_requires_full_window_and_both_real_navs():
    c=complete_clock();daily=pd.DataFrame(dict(date=c.signal_date,research_accounting_qualified=True,TOTAL_ECONOMIC_NAV=3000.+np.arange(len(c)),LIQUID_NAV=3000.+np.arange(len(c))))
    q=e.account_qualification(daily,c,"RIDGE");assert q["sessions"]==752 and q["status"]=="PASS"
    out=e.account_netlog(daily,c,"TOTAL_ECONOMIC_NAV");assert len(out)==752 and out.iloc[0]==pytest.approx(0.)
    daily.loc[0,"LIQUID_NAV"]=0.
    with pytest.raises(ValueError,match="BOTH_POSITIVE"):e.account_netlog(daily,c,"TOTAL_ECONOMIC_NAV")
    daily.loc[0,"LIQUID_NAV"]=3000.;daily.loc[500,"research_accounting_qualified"]=False
    with pytest.raises(ValueError,match="QUALIFIED_ACCOUNT_WINDOW"):e.account_qualification(daily,c,"RIDGE")
    with pytest.raises(ValueError,match="QUALIFIED_ACCOUNT_WINDOW"):e.account_netlog(daily.iloc[:-1],c,"LIQUID_NAV")
