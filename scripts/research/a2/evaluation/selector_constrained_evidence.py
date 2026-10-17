"""Pure C13 evidence: immutable maxT reuse and descriptive H5 risk only.

The caller owns source/UID/clock qualification and terminal-decision freeze.
No source readers, fitted risk states, optimizers, bootstrap implementation or
writers are introduced; selector_evidence remains the sole statistical owner.
"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import ast,hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.evaluation import selector_classical_evidence as c11

RESEARCH_ID = "V24_C_SELECTOR_RISK_CONSTRAINED_AND_CLASSICAL_STATISTICS_C13"
COMPATIBILITY = {
 "R01":("D02",), "R02":("D02",), "R03":("D02","D05"), "R04":("D02",),
 "R05":("D10","D11"), "R06":("D02","D05","D06","D09","D10","D11"),
 "R07":("D10","D11"), "R08":("D02","D05","D06","D09","D10","D11"),
 "R09":("D02",), "R10":("D02",), "R11":("D02",), "R12":("D03","D07"),
 "R13":("D04","D07"), "R14":("D06","D08"), "R15":("D08","D12"),
 "R16":("D08","D12"), "R17":("D02","D05","D06","D09","D10","D11","D08","D12"),
 "R18":("D02","D05","D06","D09","D10","D11")}
ROLES = tuple(f"C13_{r}_{d}" for r, rules in COMPATIBILITY.items() for d in rules)
ACTIVE_ROLES = tuple(f"C13_{r}_{d}" for r in ("R06","R08","R17","R18")
                     for d in ("D02","D05","D06","D09","D10","D11"))
APPLICABLE_COUNTS = {"R06":115,"R08":115,"R17":194,"R18":194}
YEARS, YEAR_COUNTS, TARGET, BOOT_METHOD = c11.YEARS,c11.YEAR_COUNTS,c11.TARGET,c11.BOOT_METHOD
H5_COORDINATE = "SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED"
CVAR_OWNER_PATH = Path(__file__).resolve().parents[1]/"retained"/"a2_predict_then_optimize_20260928_r1"/"optimizers.py"
CVAR_OWNER_SHA256 = "0e9e5dcc72697ab292ff8bcfe9661b98792ec084f3b75042caf652d6f58b4d6b"


def _require(ok, message):
    if not ok: raise ValueError(message)


def validate_design(design):
    _require(design.get("research_id")==RESEARCH_ID and design.get("official_freeze") is True
        and design.get("formal_freeze_applied") is True and tuple(design.get("roles",()))==ROLES
        and tuple(design.get("active_roles",()))==ACTIVE_ROLES and design.get("target")==TARGET
        and tuple(design.get("primary_eval_years",()))==YEARS,"EXACT_C13_FORMAL_FREEZE_REQUIRED")
    _require(design.get("mechanism_research_eligible") is True
        and design.get("strict_PIT_promotion_eligible") is False and design.get("test2026_locked") is True
        and design.get("new2026_estimation_authorized") is False,"MECHANISM_ONLY_2026_LOCK_REQUIRED")
    ev=design["evaluation"]; b=ev["bootstrap"]
    _require(ev.get("common_mature_date_count")==732 and ev.get("original_calendar_dates")==752
        and ev.get("year_counts")==YEAR_COUNTS and ev.get("legacy_numeric")==147
        and ev.get("legacy_exposure")==178 and ev.get("legacy_failed")==31
        and ev.get("exposure_namespace")==226 and ev.get("new_numeric")==0
        and ev.get("partial_only") is True and ev.get("risk_efficiency_support_requires_full732") is True
        and ev.get("primary")=="MEAN_REPLACEMENT_EDGE","ORIGINAL_CLOCK_AND_226_EXPOSURE_REQUIRED")
    _require(b.get("draws")==5000 and b.get("block")==20 and b.get("seed")==20260928
        and b.get("method")==BOOT_METHOD,"EXACT_SHARED_5000_BLOCK20_RULE_REQUIRED")
    return ev


def _clock(clock):
    _require(isinstance(clock,pd.DataFrame) and set(("signal_date","included")).issubset(clock)
        and not clock.columns.has_duplicates and len(clock)==752
        and pd.api.types.is_bool_dtype(clock.included) and not clock.included.isna().any(),
        "ORIGINAL_752_CLOCK_REQUIRED")
    cal=pd.DatetimeIndex(clock.signal_date); mature=cal[clock.included.to_numpy()]
    _require(cal.tz is None and not cal.hasnans and not cal.has_duplicates and cal.is_monotonic_increasing
        and (cal<pd.Timestamp("2026-01-01")).all() and len(mature)==732
        and {str(y):int((mature.year==y).sum()) for y in YEARS}==YEAR_COUNTS,
        "DO_NOT_SHRINK_OR_CHANGE_732_752_CLOCK")
    return cal, clock.set_index("signal_date").included


def _bound(reference,panel,clock):
    cal,common=_clock(clock)
    keys=shared.KEY
    _require(isinstance(reference,pd.DataFrame) and isinstance(panel,pd.DataFrame)
        and not reference.columns.has_duplicates and not panel.columns.has_duplicates
        and set(keys+["rank"]).issubset(panel) and set(keys).issubset(reference)
        and not reference.duplicated(keys).any() and not panel.duplicated(keys).any(),"EXACT_FULL_U_KEYS_REQUIRED")
    ref=reference.copy(); p=panel.copy()
    ref["signal_date"]=pd.to_datetime(ref.signal_date);p["signal_date"]=pd.to_datetime(p.signal_date)
    for f in (ref,p):
        dates=pd.DatetimeIndex(f.signal_date)
        _require(dates.tz is None and not dates.hasnans and dates.isin(cal).all()
            and f.security_uid.map(lambda x:isinstance(x,str) and bool(x)).all(),"PRE2026_ORIGINAL_CALENDAR_AND_UID_REQUIRED")
    _require(pd.DatetimeIndex(sorted(ref.signal_date.unique())).equals(cal),"REFERENCE_FULL_752_CALENDAR_REQUIRED")
    if "raw_rank" not in ref: ref["raw_rank"]=ref["rank"]
    dates=pd.DatetimeIndex(sorted(p.signal_date.unique()))
    _require(len(dates)>0,"EMPTY_APPLICABLE_PANEL")
    r=ref.loc[ref.signal_date.isin(dates)].sort_values(keys,kind="stable").reset_index(drop=True)
    p=p.sort_values(keys,kind="stable").reset_index(drop=True)
    _require(p[keys].equals(r[keys]) and np.isfinite(p["rank"].to_numpy(float)).all()
        and np.isfinite(r.raw_rank.to_numpy(float)).all(),"FULL_U_NO_ROW_DROP_OR_NONFINITE_RANK")
    for name in ("ticker","U_t_fingerprint"):
        if name in p and name in r: _require(p[name].equals(r[name]),"IDENTITY_OR_UNIVERSE_FINGERPRINT_CHANGED")
    if "score" in p: _require(np.isfinite(p.score.to_numpy(float)).all(),"NONFINITE_SCORE")
    for _,ix in r.groupby("signal_date",sort=True).indices.items():
        rr=r.raw_rank.to_numpy()[ix]; ranks=p["rank"].to_numpy()[ix]
        _require(np.array_equal(np.sort(rr),np.arange(1,len(ix)+1))
            and np.array_equal(np.sort(ranks),np.arange(1,len(ix)+1)),"ORDINAL_FULL_U_RANK_REQUIRED")
        selected=ranks<=20
        _require(len(ix)>=40 and selected.sum()==20 and selected[rr<=10].all()
            and (rr[selected]<=40).all(),"RAW_TOP10_FIXED_TOP40_FINAL20_REQUIRED")
    return r,p,common


def daily_diagnostics(candidate_id,reference,panel,clock):
    _require(candidate_id in ACTIVE_ROLES,"REGISTERED_ACTIVE_C13_ROLE_REQUIRED")
    r,p,common=_bound(reference,panel,clock); rows=[];previous=None
    if "candidate_id" in p: _require(p.candidate_id.eq(candidate_id).all(),"MIXED_OR_WRONG_CANDIDATE_PANEL")
    for date,ix in r.groupby("signal_date",sort=True).indices.items():
        g=r.iloc[ix]; rr=g.raw_rank.to_numpy(); selected=p.iloc[ix]["rank"].to_numpy()<=20;raw=rr<=20
        mature=False; reason="PRIMARY_TARGET_UNAVAILABLE"
        if set(("target","label_end_date")).issubset(g):
            valid,detail=shared.maturity(g.reset_index(drop=True),raw|selected)
            mature=bool(common.loc[date] and valid[raw|selected].all()); reason=str(detail.iloc[0].reason)
        y=g.target.to_numpy(float) if "target" in g else None
        members=set(g.loc[selected,"security_uid"]);n=int((selected&~raw).sum())
        rows.append(dict(candidate_id=candidate_id,signal_date=date,year=int(date.year),
            applicable=True,common_mature_date=mature,descriptive_only=True,pool_rows=len(g),
            replacement_edge=shared.replacement_edge(y,raw,selected) if mature else None,
            primary_unavailable_reason=None if mature else reason,raw_overlap=int((raw&selected).sum()),
            replacement_count=n,membership_turnover=None if previous is None else len(previous^members)/40,
            turnover_definition="previous applicable membership date; not account cost or turnover",
            selector_supported=False,risk_efficiency_supported=False,strict_PIT_promotion_eligible=False))
        previous=members
    return pd.DataFrame(rows)


def risk_coordinates(covariance,asset_uids,selected_uids):
    """Equal20 covariance diagnostics; no fitting, PSD repair or portfolio weights."""
    uids=tuple(asset_uids); chosen=tuple(selected_uids); a=np.asarray(covariance,float)
    _require(len(uids)==len(set(uids)) and len(chosen)==len(set(chosen))==20
        and set(chosen).issubset(uids) and all(isinstance(u,str) and u for u in uids)
        and a.shape==(len(uids),len(uids)) and np.isfinite(a).all()
        and np.allclose(a,a.T,rtol=0,atol=1e-12),"QUALIFIED_UID_ORDER_AND_FINITE_SYMMETRIC_COVARIANCE_REQUIRED")
    ix=[uids.index(u) for u in chosen];s=a[np.ix_(ix,ix)]
    _require(np.linalg.eigvalsh(s).min()>=-1e-12,"PSD_SELECTED_COVARIANCE_REQUIRED_NO_REPAIR")
    w=np.full(20,.05)
    variance=float(w@s@w); rc=w*(s@w); total=float(np.abs(rc).sum())
    result=dict(predicted_variance=variance,abs_rc_hhi=float(np.square(np.abs(rc)/total).sum()) if total>0 else None,
        condition_number=float(np.linalg.cond(s)) if np.linalg.matrix_rank(s)==20 else None,
        singular_covariance=bool(np.linalg.matrix_rank(s)<20))
    diag=np.diag(s)
    if (diag<=0).any():
        return {**result,"status":"BLOCKED_ZERO_MARGINAL_VARIANCE","enb":None,"max_correlation":None,
                "max_abs_correlation":None,"diversification_ratio":None}
    sigma=np.sqrt(diag);corr=s/np.outer(sigma,sigma);off=corr[~np.eye(20,dtype=bool)]
    result.update(status="COMPLETE",enb=float(400./np.square(corr).sum()),max_correlation=float(off.max()),
        max_abs_correlation=float(np.abs(off).max()),
        diversification_ratio=float(w@sigma/np.sqrt(variance)) if variance>0 else None)
    return result


@lru_cache(maxsize=1)
def _empirical_cvar_owner():
    # Execute only the original pure metric and its original default constant.
    # The legacy module imports absolute common; no solver/module is imported.
    payload=CVAR_OWNER_PATH.read_bytes()
    _require(hashlib.sha256(payload).hexdigest()==CVAR_OWNER_SHA256,"EMPIRICAL_CVAR_OWNER_PIN_CHANGED")
    tree=ast.parse(payload.decode("utf-8-sig"),filename=str(CVAR_OWNER_PATH))
    constants=[n for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=="CVAR_ALPHA" for t in n.targets)]
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="empirical_cvar"]
    _require(len(constants)==len(functions)==1,"ORIGINAL_PURE_CVAR_DEFINITION_REQUIRED")
    namespace={"np":np}
    exec(compile(ast.Module(body=[*constants,*functions],type_ignores=[]),str(CVAR_OWNER_PATH),"exec"),namespace)
    return namespace["empirical_cvar"]


def _return_metrics(values):
    x=np.asarray(values,float);_require(x.ndim==1 and np.isfinite(x).all(),"FINITE_DIAGNOSTIC_RETURN_SERIES_REQUIRED")
    if not len(x):return dict(dates=0,std_ddof1=None,downside_uncentered=None,q05=None,exceedance_mean=None,cvar_loss_q05=None,cvar_loss_q05_is_proxy=True,cvar_loss_alpha95=None)
    q=float(np.quantile(x,.05,method="linear"));tail=x[x<=q];mean=float(tail.mean())
    return dict(dates=len(x),std_ddof1=float(x.std(ddof=1)) if len(x)>1 else None,
        downside_uncentered=float(np.sqrt(np.square(np.minimum(x,0)).mean())),
        q05=q,exceedance_mean=mean,cvar_loss_q05=-mean,cvar_loss_q05_is_proxy=True,
        cvar_loss_alpha95=float(_empirical_cvar_owner()(-x,alpha=.95)))


def risk_diagnostics(candidate_id,reference,panel,clock,realized_h5=None,predicted_risk=None):
    """Only qualified finite all20 union days get realized H5 basket diagnostics.

    Missing y affects this diagnostic only. It never changes applicable panels,
    the primary common clock, scientific roles or the candidate membership.
    """
    _require(candidate_id in ACTIVE_ROLES,"REGISTERED_ACTIVE_C13_ROLE_REQUIRED")
    r,p,_=_bound(reference,panel,clock);rows=[];labels=None
    if "candidate_id" in p: _require(p.candidate_id.eq(candidate_id).all(),"MIXED_OR_WRONG_CANDIDATE_PANEL")
    if realized_h5 is not None:
        needed=shared.KEY+["return_value","qualified"]
        _require(isinstance(realized_h5,pd.DataFrame) and set(needed).issubset(realized_h5)
            and not realized_h5.columns.has_duplicates and not realized_h5.duplicated(shared.KEY).any()
            and pd.api.types.is_bool_dtype(realized_h5.qualified) and not realized_h5.qualified.isna().any(),
            "BOUND_UID_H5_LABELS_AND_EXPLICIT_QUALIFICATION_REQUIRED")
        labels=realized_h5.copy(); labels["signal_date"]=pd.to_datetime(labels.signal_date)
        _require(labels.signal_date.notna().all() and labels.signal_date.lt("2026-01-01").all()
            and labels.signal_date.dt.tz is None,"PRE2026_H5_LABELS_REQUIRED")
        if "label_coordinate" in labels:
            _require(labels.label_coordinate.eq(H5_COORDINATE).all(),"ABSOLUTE_SHAREHOLDER_H5_COORDINATE_REQUIRED")
        for col in ("execution_date","label_end_date","label_mature_date"):
            if col in labels:
                labels[col]=pd.to_datetime(labels[col]);known=labels[col].notna()
                _require(labels.loc[known,col].lt("2026-01-01").all(),"PRE2026_H5_CLOCK_REQUIRED")
        labels=labels.set_index(shared.KEY)
    for date,ix in r.groupby("signal_date",sort=True).indices.items():
        g=r.iloc[ix]; selected=p.iloc[ix]["rank"].to_numpy()<=20;raw=g.raw_rank.to_numpy()<=20
        chosen=tuple(g.loc[selected,"security_uid"]);baseline=tuple(g.loc[raw,"security_uid"])
        row=dict(candidate_id=candidate_id,signal_date=date,year=int(date.year),descriptive_only=True,
            return_coordinate=H5_COORDINATE,realized_status="BLOCKED_H5_SOURCE_UNAVAILABLE",
            selected_h5_return=None,raw_h5_return=None,unavailable_union_labels=int((raw|selected).sum()),
            prediction_status="BLOCKED_SHARED_COVARIANCE_UNAVAILABLE",selector_supported=False,
            risk_efficiency_supported=False,strict_PIT_promotion_eligible=False)
        if labels is not None:
            keys=pd.MultiIndex.from_arrays([np.repeat(date,len(g)),g.security_uid],names=shared.KEY)
            lab=labels.reindex(keys);union=raw|selected
            values=pd.to_numeric(lab.return_value,errors="coerce").to_numpy(float)
            legal=lab.qualified.eq(True).to_numpy() & np.isfinite(values)
            for col,wanted in (("label_available",True),("endpoint_pair_available",True),("label_unsupported_common_event",False)):
                if col in lab:legal &= lab[col].eq(wanted).to_numpy()
            cal,_=_clock(clock); origin=cal.get_loc(date)
            for name,offset in (("execution_date",1),("label_end_date",6)):
                if name in lab:
                    expected=cal[origin+offset] if origin+offset<len(cal) else pd.NaT
                    legal &= lab[name].eq(expected).to_numpy()
            if "label_mature_date" in lab and "label_end_date" in lab:
                legal &= lab.label_mature_date.ge(lab.label_end_date).to_numpy()
            row["unavailable_union_labels"]=int((~legal[union]).sum())
            if legal[union].all():
                row.update(realized_status="COMPLETE",selected_h5_return=float(values[selected].mean()),raw_h5_return=float(values[raw].mean()))
            else:row["realized_status"]="BLOCKED_INCOMPLETE_QUALIFIED_FINITE_UNION20"
        info=(predicted_risk or {}).get(date)
        if info is not None:
            new=risk_coordinates(info["covariance"],info["asset_uids"],chosen)
            old=risk_coordinates(info["covariance"],info["asset_uids"],baseline)
            row.update(prediction_status=new["status"],**{k:v for k,v in new.items() if k!="status"},raw_predicted_variance=old["predicted_variance"])
        rows.append(row)
    daily=pd.DataFrame(rows);summaries=[]
    for year in (*YEARS,"POOLED"):
        g=daily if year=="POOLED" else daily.loc[daily.year.eq(year)]
        valid=g.realized_status.eq("COMPLETE");s=_return_metrics(g.loc[valid,"selected_h5_return"].to_numpy(float))
        raw=_return_metrics(g.loc[valid,"raw_h5_return"].to_numpy(float))
        pred=g.loc[g.prediction_status.eq("COMPLETE")]
        pm=float(pred.predicted_variance.mean()) if len(pred) else None
        rm=float(pred.raw_predicted_variance.mean()) if len(pred) else None
        summaries.append(dict(candidate_id=candidate_id,year=str(year),applicable_dates=len(g),valid_h5_dates=int(valid.sum()),
            valid_predicted_risk_dates=len(pred),predicted_variance_mean=pm,raw_predicted_variance_mean=rm,
            predicted_variance_difference_mean=pm-rm if pm is not None else None,
            tail_definition="q05 linear quantile; exceedance_mean=mean(r<=q05); cvar_loss_q05 is an exceedance proxy; cvar_loss_alpha95 uses original empirical_cvar fractional 5% loss tail mass",
            blocked_h5_dates=int((~valid).sum()),selected=s,raw=raw,
            realized_variance_difference=(s["std_ddof1"]**2-raw["std_ddof1"]**2) if s["std_ddof1"] is not None else None,
            overlapping_h5_returns=True,iid_standard_error_used=False,descriptive_only=True,
            selector_supported=False,risk_efficiency_supported=False,strict_PIT_promotion_eligible=False))
    return daily,summaries


def reuse_statistics(legacy_receipt,legacy_edge_columns,legacy_exposure_ids,planned_roles=ROLES,failed=None):
    """An unchanged 147-column matrix reuses its original 5000 draws, without I/O."""
    ids=list(legacy_edge_columns);expo=list(legacy_exposure_ids);r=deepcopy(legacy_receipt)
    _require(len(ids)==len(set(ids))==147 and len(expo)==len(set(expo))==178 and set(ids).issubset(expo)
        and not set(expo)&set(ROLES) and tuple(planned_roles)==ROLES,"PRESERVED_147_NUMERIC_178_EXPOSURE_REQUIRED")
    _require(r.get("status")=="COMPLETE" and r.get("repeats")==5000 and r.get("block_sessions")==20
        and r.get("seed")==20260928 and isinstance(r.get("shared_draw_sha256"),str)
        and len(r["shared_draw_sha256"])==64 and np.isfinite(r.get("critical_max_t",np.nan)),
        "QUALIFIED_ORIGINAL_MAXT_RECEIPT_REQUIRED")
    failed=dict(failed or {})
    _require(set(failed).issubset(ROLES),"UNREGISTERED_FAILURE_ROLE")
    for role in ROLES:failed.setdefault(role,"UNTESTABLE_NO_COMPLETE_COMMON_732_SERIES")
    summaries=[dict(candidate_id=role,status="FAILED_UNTESTABLE",failure_reason=failed[role],
        pooled_edge=None,year_edges={str(y):None for y in YEARS},bootstrap_se=None,simultaneous_lower_95=None,
        supported=False,selector_supported=False,risk_efficiency_supported=False,strict_PIT_promotion_eligible=False) for role in ROLES]
    r.update(exposure_namespace=226,numeric_complete_series=147,new_numeric_complete_series=0,
        legacy_numeric_complete_series=147,legacy_exposure_namespace=178,legacy_failed_or_blocked=31,
        new_exposure_roles=list(ROLES),failed_or_untestable=failed,numeric_ceiling=195,
        exact_legacy_maxT_reuse=True,new_bootstrap_draws=0,legacy_receipt_preserved_verbatim=True,
        legacy_maxT_receipt=deepcopy(legacy_receipt),legacy_numeric_ids=ids,legacy_exposure_ids=expo,
        legacy_non_numeric_exposure_ids=[x for x in expo if x not in set(ids)],
        legacy_failed_or_untestable=deepcopy(legacy_receipt.get("failed_or_untestable",{})),
        failed_series="exposure metadata only; no zero placeholders",descriptive_sparse_dates_entered_numeric=False,
        selector_supported=False,risk_efficiency_supported=False)
    return summaries,r
