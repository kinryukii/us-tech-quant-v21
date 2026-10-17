"""Synthetic-only C13 coverage, no-fit diagnostics and immutable maxT reuse."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import selector_constrained_evidence as c


def design():
    return dict(research_id=c.RESEARCH_ID,official_freeze=True,formal_freeze_applied=True,
        roles=list(c.ROLES),active_roles=list(c.ACTIVE_ROLES),target=c.TARGET,primary_eval_years=list(c.YEARS),
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        new2026_estimation_authorized=False,evaluation=dict(common_mature_date_count=732,
        original_calendar_dates=752,year_counts=c.YEAR_COUNTS,legacy_numeric=147,legacy_exposure=178,
        legacy_failed=31,exposure_namespace=226,new_numeric=0,partial_only=True,
        risk_efficiency_support_requires_full732=True,primary="MEAN_REPLACEMENT_EDGE",
        bootstrap=dict(draws=5000,block=20,seed=20260928,method=c.BOOT_METHOD)))


@pytest.fixture
def frames():
    cal=pd.DatetimeIndex(np.concatenate([pd.bdate_range(f"{y}-01-02",periods=n).to_numpy()
                                         for y,n in ((2023,250),(2024,252),(2025,250))]))
    clock=pd.DataFrame(dict(signal_date=cal,included=np.r_[np.ones(732,bool),np.zeros(20,bool)]))
    dates=np.repeat(cal,41);n=np.tile(np.arange(1,42),len(cal));uids=[f"U{i:02d}" for i in n]
    end=np.repeat(pd.DatetimeIndex([cal[min(i+20,751)] for i in range(752)]),41)
    ref=pd.DataFrame(dict(signal_date=dates,security_uid=uids,raw_rank=n,target=n/1000,
                         label_end_date=end,ticker=uids,U_t_fingerprint="U_FIXED"))
    days=cal[[30,40,50,510]]
    panel=ref.loc[ref.signal_date.isin(days),["signal_date","security_uid","ticker","U_t_fingerprint"]].copy()
    ranks=np.tile(np.arange(1,42),len(days));ranks=np.where(ranks==20,21,np.where(ranks==21,20,ranks))
    panel["rank"]=ranks
    panel["candidate_id"]=c.ACTIVE_ROLES[0]
    return ref,panel,clock


def labels(ref,panel,clock):
    cal=pd.DatetimeIndex(clock.signal_date);rows=[]
    for date,group in panel.groupby("signal_date",sort=True):
        i=cal.get_loc(date)
        for uid in group.security_uid:
            rows.append(dict(signal_date=date,security_uid=uid,return_value=(i-45)/1000+int(uid[1:])/100000,
                qualified=True,label_coordinate=c.H5_COORDINATE,execution_date=cal[i+1],
                label_end_date=cal[i+6],label_mature_date=cal[i+6],label_available=True,
                endpoint_pair_available=True,label_unsupported_common_event=False))
    return pd.DataFrame(rows)


def old_receipt():
    return dict(status="COMPLETE",repeats=5000,block_sessions=20,seed=20260928,
                shared_draw_sha256="a"*64,critical_max_t=4.7,family_candidates=147,
                centering="unchanged",active_nonzero_se_columns=146)


def test_exact_design_and_roles():
    assert len(c.ROLES)==48 and len(c.ACTIVE_ROLES)==24
    assert c.validate_design(design())["new_numeric"]==0


@pytest.mark.parametrize("where,key,value",[("top","strict_PIT_promotion_eligible",True),
    ("top","new2026_estimation_authorized",True),("top","formal_freeze_applied",False),
    ("ev","new_numeric",1),("ev","common_mature_date_count",731),
    ("ev","exposure_namespace",178),("ev","risk_efficiency_support_requires_full732",False),
    ("boot","draws",150),("boot","block",10),("boot","seed",42),("boot","method","new math")])
def test_freeze_rejects_scientific_change(where,key,value):
    d=design();part=d if where=="top" else d["evaluation"] if where=="ev" else d["evaluation"]["bootstrap"]
    part[key]=value
    with pytest.raises(ValueError):c.validate_design(d)


def test_sparse_membership_is_descriptive_full_u(frames):
    ref,panel,clock=frames;daily=c.daily_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock)
    assert len(daily)==4 and daily.pool_rows.eq(41).all() and daily.replacement_count.eq(1).all()
    assert np.allclose(daily.replacement_edge,.00005)
    assert not daily.selector_supported.any() and not daily.risk_efficiency_supported.any()
    assert len(clock)==752 and clock.included.sum()==732


@pytest.mark.parametrize("mode",["drop","duplicate","core","outside40","rank","future","uid","mixed"])
def test_full_u_core_geometry_and_identity_guards(frames,mode):
    ref,panel,clock=frames;panel=panel.copy()
    if mode=="drop":panel=panel.iloc[1:]
    if mode=="duplicate":panel=pd.concat([panel,panel.iloc[:1]])
    if mode=="core":panel.loc[panel.security_uid.eq("U01"),"rank"]=41;panel.loc[panel.security_uid.eq("U41"),"rank"]=1
    if mode=="outside40":panel.loc[panel.security_uid.eq("U21"),"rank"]=41;panel.loc[panel.security_uid.eq("U41"),"rank"]=20
    if mode=="rank":
        panel["rank"]=panel["rank"].astype(float)
        panel.iloc[0,panel.columns.get_loc("rank")]=1.5
    if mode=="future":panel.iloc[0,panel.columns.get_loc("signal_date")]=pd.Timestamp("2026-01-01")
    if mode=="uid":panel.iloc[0,panel.columns.get_loc("security_uid")]="OTHER_UID"
    if mode=="mixed":panel.iloc[0,panel.columns.get_loc("candidate_id")]=c.ACTIVE_ROLES[1]
    with pytest.raises(ValueError):c.daily_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock)


def test_primary_clock_never_shrinks(frames):
    ref,panel,clock=frames
    with pytest.raises(ValueError):c.daily_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock.iloc[:-1])


def test_equal20_identity_covariance_formulas():
    uids=[f"U{i}" for i in range(20)];m=c.risk_coordinates(np.eye(20),uids,uids)
    assert m["predicted_variance"]==pytest.approx(.05)
    assert m["enb"]==pytest.approx(20) and m["abs_rc_hhi"]==pytest.approx(.05)
    assert m["condition_number"]==pytest.approx(1) and m["max_correlation"]==0
    assert m["diversification_ratio"]==pytest.approx(np.sqrt(20))


def test_correlated_enb_and_singular_no_repair():
    uids=[str(i) for i in range(20)];m=c.risk_coordinates(np.ones((20,20)),uids,uids)
    assert m["enb"]==pytest.approx(1) and m["predicted_variance"]==pytest.approx(1)
    assert m["singular_covariance"] and m["condition_number"] is None


@pytest.mark.parametrize("mode",["nan","asymmetry","negative","uid","duplicate"])
def test_predicted_covariance_rejects_unqualified_input(mode):
    a=np.eye(20);uids=[str(i) for i in range(20)];chosen=uids.copy()
    if mode=="nan":a[0,0]=np.nan
    if mode=="asymmetry":a[0,1]=.1
    if mode=="negative":a[0,0]=-1
    if mode=="uid":chosen[0]="OTHER"
    if mode=="duplicate":uids[0]=uids[1]
    with pytest.raises(ValueError):c.risk_coordinates(a,uids,chosen)


def test_realized_absolute_h5_not_mean_er(frames):
    ref,panel,clock=frames;y=labels(*frames)
    daily,summary=c.risk_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock,y)
    assert daily.realized_status.eq("COMPLETE").all() and daily.return_coordinate.eq(c.H5_COORDINATE).all()
    expected=y.loc[y.signal_date.eq(daily.iloc[0].signal_date)&y.security_uid.isin([f"U{i:02d}" for i in (*range(1,20),21)]),"return_value"].mean()
    assert daily.iloc[0].selected_h5_return==pytest.approx(expected)
    pooled=summary[-1]
    assert pooled["valid_h5_dates"]==4 and pooled["selected"]["std_ddof1"]==pytest.approx(daily.selected_h5_return.std(ddof=1))
    assert pooled["selected"]["downside_uncentered"]==pytest.approx(np.sqrt(np.minimum(daily.selected_h5_return,0).pow(2).mean()))
    assert pooled["overlapping_h5_returns"] and not pooled["iid_standard_error_used"]
    assert not pooled["risk_efficiency_supported"]


@pytest.mark.parametrize("mode",["missing","finite","qualified","unsupported","endpoint","clock","maturity"])
def test_missing_h5_only_blocks_diagnostic_no_candidate_drop(frames,mode):
    ref,panel,clock=frames;y=labels(*frames);key=y.security_uid.eq("U01") & y.signal_date.eq(panel.signal_date.iloc[0])
    if mode=="missing":y=y.loc[~key]
    if mode=="finite":y.loc[key,"return_value"]=np.nan
    if mode=="qualified":y.loc[key,"qualified"]=False
    if mode=="unsupported":y.loc[key,"label_unsupported_common_event"]=True
    if mode=="endpoint":y.loc[key,"endpoint_pair_available"]=False
    if mode=="clock":y.loc[key,"label_end_date"]=y.loc[key,"execution_date"].to_numpy()
    if mode=="maturity":y.loc[key,"label_mature_date"]=y.loc[key,"execution_date"].to_numpy()
    daily,summary=c.risk_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock,y)
    assert len(daily)==4 and summary[-1]["valid_h5_dates"]==3 and summary[-1]["blocked_h5_dates"]==1
    assert daily.iloc[0].selected_h5_return is None or pd.isna(daily.iloc[0].selected_h5_return)
    assert len(c.daily_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock))==4 and len(clock)==752


@pytest.mark.parametrize("mode",["future_signal","future_endpoint","coordinate","duplicate"])
def test_h5_source_contract_rejects_invalid_labels(frames,mode):
    ref,panel,clock=frames;y=labels(*frames)
    if mode=="future_signal":y.loc[0,"signal_date"]=pd.Timestamp("2026-01-01")
    if mode=="future_endpoint":y.loc[0,"label_end_date"]=pd.Timestamp("2026-01-01")
    if mode=="coordinate":y["label_coordinate"]=c.TARGET
    if mode=="duplicate":y=pd.concat([y,y.iloc[:1]])
    with pytest.raises(ValueError):c.risk_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock,y)


def test_tail_semantics_fixed_quantile_and_exceedance_mean():
    x=np.array([-.3,-.2,-.1,.1,.2]);m=c._return_metrics(x)
    assert m["q05"]==pytest.approx(-.28) and m["exceedance_mean"]==pytest.approx(-.3)
    assert m["cvar_loss_q05"]==pytest.approx(.3)
    assert c._return_metrics([])["dates"]==0


def test_missing_risk_sources_is_explicit_blocked(frames):
    daily,summary=c.risk_diagnostics(c.ACTIVE_ROLES[0],*frames)
    assert daily.realized_status.eq("BLOCKED_H5_SOURCE_UNAVAILABLE").all()
    assert summary[-1]["blocked_h5_dates"]==4


def test_max_t_exact_reuse_without_new_draws_or_mutation(monkeypatch):
    monkeypatch.setattr(c.shared,"shared_max_t",lambda *a,**k:(_ for _ in ()).throw(AssertionError("NO REDRAW")))
    original=old_receipt();original["failed_or_untestable"]={"OLD147":"ORIGINAL_FAILED"}
    before=deepcopy(original);ids=[f"OLD{i}" for i in range(147)];expo=[f"OLD{i}" for i in range(178)]
    summaries,r=c.reuse_statistics(original,ids,expo)
    assert original==before and r["shared_draw_sha256"]==before["shared_draw_sha256"]
    assert r["critical_max_t"]==before["critical_max_t"] and r["new_bootstrap_draws"]==0
    assert r["numeric_complete_series"]==147 and r["exposure_namespace"]==226
    assert len(summaries)==48 and all(x["pooled_edge"] is None and not x["supported"] for x in summaries)
    assert len(r["failed_or_untestable"])==48
    assert len(r["legacy_non_numeric_exposure_ids"])==31
    assert r["legacy_maxT_receipt"]==before
    assert r["legacy_failed_or_untestable"]=={"OLD147":"ORIGINAL_FAILED"}


@pytest.mark.parametrize("mode",["seed","draws","threshold","numeric","exposure","unregistered"])
def test_reuse_requires_exact_old_metadata(mode):
    r=old_receipt();ids=[f"O{i}" for i in range(147)];expo=[f"O{i}" for i in range(178)];failed={}
    if mode=="seed":r["seed"]=1
    if mode=="draws":r["repeats"]=500
    if mode=="threshold":r["critical_max_t"]=np.nan
    if mode=="numeric":ids=ids[:-1]
    if mode=="exposure":expo=expo[:-1]
    if mode=="unregistered":failed={"OTHER":"BLOCKED"}
    with pytest.raises(ValueError):c.reuse_statistics(r,ids,expo,failed=failed)


def test_pure_predicted_risk_joint_with_realized_diagnostics(frames):
    ref,panel,clock=frames;uids=tuple(sorted(panel.security_uid.unique()))
    info={pd.Timestamp(d):dict(covariance=np.eye(len(uids)),asset_uids=uids) for d in panel.signal_date.unique()}
    daily,summary=c.risk_diagnostics(c.ACTIVE_ROLES[0],ref,panel,clock,labels(*frames),info)
    assert daily.prediction_status.eq("COMPLETE").all() and daily.enb.eq(20).all()
    assert summary[-1]["valid_predicted_risk_dates"]==4
    assert summary[-1]["predicted_variance_mean"]==pytest.approx(.05)
    assert not daily.risk_efficiency_supported.any()


@pytest.mark.parametrize("n,losses,expected",[(25,[10.,6.],9.2),
    (30,[10.,6.],26./3.),(41,[10.,6.,6.],16.3/2.05)])
def test_exact_fractional_tail_cvar_distinct_from_exceedance_proxy(n,losses,expected):
    returns=-np.array([*losses,*([0.]*(n-len(losses)))])
    metric=c._return_metrics(returns)
    assert metric["cvar_loss_alpha95"]==pytest.approx(expected)
    assert metric["cvar_loss_q05_is_proxy"] is True
    assert metric["cvar_loss_q05"]!=pytest.approx(metric["cvar_loss_alpha95"])
    assert c._return_metrics([])["cvar_loss_alpha95"] is None
