"""New full-U C evidence adapter; existing block-draw, mean and CVaR owners.

This module is pure. The caller must freeze all policies and account facts before
projecting outer outcomes. It adds the new fixed roster and different supports;
it never retrains, selects a family, edits old statistics or claims a holdout.
"""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as mixed
from scripts.research.a2.evaluation import selector_constrained_evidence as metrics
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.training.selector_full_fixed_policy import catalog,FAMILIES
from scripts.research.a2.data.full_selector_inputs import ID,KEYS,require

RULE = dict(repeats=5000,block=20,seed=20260928,confidence=.95,
    method="shared noncircular 20-session moving blocks; centered studentized one-sided maxT simultaneous lower",
    formal_endpoints=321,alpha_support="ALL_FIXED_LEARNED_MATURE_DATES",
    account_support="ALL_752_ACCOUNT_SESSIONS",
    risk_support="ALL_FIXED_H5_CALENDAR_MATURE_DATES",
    zero_se="CANNOT_PASS",annual_alpha_rule="2024>0 AND 2025>0",
    annual_account_rule="2024>0 AND 2025>0 for both TOTAL and LIQUID",
    dual_account_rule="TOTAL lower>0 AND LIQUID lower>0 AND both annual rules",
    historical_statistics="NO_RECOMPUTE_OR_INCOMPATIBLE_MAXIMA_CONCATENATION")

def endpoint_specs():
    _,contrasts=catalog()
    specs=[]
    for c in contrasts:
        for metric,support in (("ALPHA","alpha_learned_mature"),("TOTAL_NETLOG","account"),("LIQUID_NETLOG","account")):
            specs.append(dict(endpoint_id=c["contrast_id"]+"|"+metric,metric=metric,support=support,**c))
    for family in FAMILIES:
        for metric in ("DOWN","CVAR"):
            c=dict(contrast_id="RISK_"+family+"__VS_HGB",candidate="RISK_"+family,reference="HGB")
            specs.append(dict(endpoint_id=c["contrast_id"]+"|"+metric,metric=metric,support="h5_endpoint_calendar_available",**c))
    require(len(specs)==321 and len({s["endpoint_id"] for s in specs})==321,"FIXED_321_ENDPOINTS_REQUIRED")
    return specs

def _dates(clock,synthetic=False):
    required={"signal_date","alpha_learned_mature","alpha_full_mature","h5_endpoint_calendar_available"}
    require(required<=set(clock),"FROZEN_EVALUATION_CLOCK_REQUIRED")
    dates=pd.DatetimeIndex(clock.signal_date)
    require(dates.tz is None and not dates.hasnans and dates.is_unique and dates.is_monotonic_increasing and (dates<pd.Timestamp("2026-01-01")).all(),"EXACT_PRE2026_ORDERED_CLOCK_REQUIRED")
    require(synthetic or len(dates)==752,"ALL_752_SESSIONS_REQUIRED")
    for name in required-{"signal_date"}:
        require(pd.api.types.is_bool_dtype(clock[name]) and not clock[name].isna().any(),"EXACT_BOOLEAN_SUPPORT_REQUIRED")
    require((~clock.alpha_learned_mature | clock.alpha_full_mature).all(),"LEARNED_SUPPORT_SUBSET_OF_FULL_MATURE_REQUIRED")
    require((~clock.alpha_learned_mature | np.isin(dates.year,(2024,2025))).all(),"LEARNED_SUPPORT_2024_2025_ONLY")
    if not synthetic:
        require({int(y):int((dates.year==y).sum()) for y in (2023,2024,2025)}=={2023:250,2024:252,2025:250},"EXACT_COMMON_2023_2025_CALENDAR_COUNTS_REQUIRED")
    return dates

def _calendar_digest(dates):
    return hashlib.sha256(np.asarray(pd.DatetimeIndex(dates).asi8,dtype="<i8").tobytes()).hexdigest()

def clock_digest(clock):
    fields=("alpha_learned_mature","alpha_full_mature","h5_endpoint_calendar_available")
    blob=np.asarray(pd.DatetimeIndex(clock.signal_date).asi8,dtype="<i8").tobytes()
    blob+=np.asarray(clock[list(fields)],dtype=np.uint8).tobytes()
    return hashlib.sha256(blob).hexdigest()

def _support(clock,spec):
    return np.ones(len(clock),bool) if spec["support"]=="account" else clock[spec["support"]].to_numpy(bool)

def _finite(series,index,reason):
    require(isinstance(series,pd.Series) and series.index.equals(index) and np.isfinite(series.to_numpy(float)).all(),reason)
    return series.to_numpy(float)

def _risk_function(x,metric):
    return np.sqrt(np.square(np.minimum(x,0.)).mean(axis=-1)) if metric=="DOWN" else metrics._empirical_cvar_owner()(-x,alpha=.95)

def paired_statistics(clock,endpoints,h5_returns,failed=None,*,design=None,terminal=None,synthetic=False,repeats=None,account_qualifications=None):
    """One shared maxT family: 95 alpha, 190 netlog and 36 realized H5 tests.

    Missing policies are exposure-only. No endpoint is shortened or zero-filled.
    Account qualification is an independent mandatory gate, not a covariance gate.
    """
    dates=_dates(clock,synthetic);specs=endpoint_specs();failed=dict(failed or {});account_qualifications=dict(account_qualifications or {})
    require(set(failed)<={s["endpoint_id"] for s in specs},"ONLY_FROZEN_ENDPOINT_FAILURE_IDS_REQUIRED")
    if not synthetic:
        require(design and design.get("research_id")==ID and design.get("evaluation",{}).get("rule")==RULE,"EXACT_NEW_EVIDENCE_FREEZE_REQUIRED")
        require(design["evaluation"].get("clock_sha256")==clock_digest(clock),"FROZEN_EXACT_SUPPORT_CLOCK_REQUIRED")
        require(terminal and terminal.get("status")=="ALL_POLICIES_FROZEN_BEFORE_OUTCOMES"
            and terminal.get("research_id")==ID and terminal.get("all_training_terminal") is True
            and terminal.get("outer_result_feedback") is False,"TERMINAL_POLICY_GATE_BEFORE_OUTCOME_REQUIRED")
        require(repeats is None,"UNFROZEN_BOOTSTRAP_COUNT")
    rule={**RULE,"repeats":(repeats or RULE["repeats"])}
    counts,draw_sha,_=mixed._draw_counts(np.arange(len(dates)),rule)
    maxima=np.zeros(rule["repeats"]);estimates={}
    for spec in specs:
        eid=spec["endpoint_id"];mask=_support(clock,spec);index=dates[mask]
        if eid in failed:continue
        if spec["metric"] in ("TOTAL_NETLOG","LIQUID_NETLOG") and eid in endpoints:
            pair=(spec["reference"],spec["candidate"])
            qualified=all(
                isinstance(account_qualifications.get(role),dict)
                and account_qualifications[role].get("policy_id")==role
                and account_qualifications[role].get("status")=="PASS"
                and account_qualifications[role].get("research_accounting_qualified") is True
                and account_qualifications[role].get("complete_window") is True
                and account_qualifications[role].get("sessions")==len(dates)
                and account_qualifications[role].get("calendar_sha256")==_calendar_digest(dates)
                for role in pair)
            if not qualified:
                failed[eid]="FULL_WINDOW_PAIRED_ACCOUNT_QUALIFICATION_REQUIRED";continue
        if spec["metric"] in ("DOWN","CVAR"):
            pair=(spec["reference"],spec["candidate"])
            if any(role not in h5_returns for role in pair):
                failed[eid]="SOURCE_NOT_TESTABLE_COMPLETE_H5_REQUIRED";continue
            reference=_finite(h5_returns[pair[0]],index,"NO_PARTIAL_OR_ZERO_FILLED_H5_REFERENCE")
            selected=_finite(h5_returns[pair[1]],index,"NO_PARTIAL_OR_ZERO_FILLED_H5_CANDIDATE")
            require(len(index)>20,"FULL_H5_SUPPORT_TOO_SHORT")
            local=counts[:,mask];mass=local.sum(1)
            require((mass>0).all(),"ZERO_SUPPORT_DRAW_MASS")
            observed=float(_risk_function(reference,spec["metric"])-_risk_function(selected,spec["metric"]))
            # Counts define the same master's support-only multiset; recompute
            # each nonlinear functional, never substitute a daily CVaR proxy.
            boot=np.empty(rule["repeats"])
            for b,row in enumerate(local.astype(int)):
                ix=np.repeat(np.arange(len(index)),row)
                boot[b]=_risk_function(reference[ix],spec["metric"])-_risk_function(selected[ix],spec["metric"])-observed
            boot-=boot.mean()
        else:
            if eid not in endpoints:
                failed[eid]="NO_COMPLETE_QUALIFIED_PAIRED_ENDPOINT";continue
            value=_finite(endpoints[eid],index,"NO_PARTIAL_DATE_OR_ZERO_FILLED_ENDPOINT:"+eid)
            observed=float(value.mean());boot=mixed.masked_bootstrap(value,counts[:,mask])
        se=float(boot.std(ddof=1));active=bool(np.isfinite(se) and se>shared.SE_TOL)
        if active:maxima=np.maximum(maxima,boot/se)
        annual = {str(year): float(value[index.year == year].mean()) if (index.year == year).any() else None for year in (2024, 2025)} if spec["metric"] not in ("DOWN", "CVAR") else {}
        estimates[eid]=dict(observed=observed,bootstrap_se=se,active=active,dates=len(index),spec=spec,annual=annual)
    critical=float(np.quantile(maxima,RULE["confidence"],method="higher"))
    summary=[]
    for spec in specs:
        eid=spec["endpoint_id"];v=estimates.get(eid)
        if v is None:summary.append(dict(**spec,status=failed.get(eid,"NOT_EXECUTED"),observed=None,lower=None,bootstrap_se=None,supported=False));continue
        lower=v["observed"]-critical*v["bootstrap_se"] if v["active"] else None
        annual_pass = all(v["annual"].get(str(year)) is not None and v["annual"][str(year)] > 0 for year in (2024, 2025)) if v["annual"] else True
        dual_nav_pass=True
        if spec["metric"] in ("TOTAL_NETLOG", "LIQUID_NETLOG"):
            other = "LIQUID_NETLOG" if spec["metric"] == "TOTAL_NETLOG" else "TOTAL_NETLOG"
            dual = estimates.get(spec["contrast_id"] + "|" + other)
            annual_pass = annual_pass and dual is not None and all(dual["annual"].get(str(year)) is not None and dual["annual"][str(year)] > 0 for year in (2024, 2025))
            dual_lower=dual["observed"]-critical*dual["bootstrap_se"] if dual is not None and dual["active"] else None
            dual_nav_pass=bool(lower is not None and lower>0 and dual_lower is not None and dual_lower>0)
        summary.append(dict(**spec,status="COMPLETE",observed=v["observed"],lower=lower,
            bootstrap_se=v["bootstrap_se"],support_dates=v["dates"],simultaneous_positive=bool(lower is not None and lower>0),
            annual_mean=v["annual"],annual_direction_pass=bool(annual_pass),supported=bool(lower is not None and lower>0 and annual_pass and dual_nav_pass),
            dual_nav_simultaneous_positive=dual_nav_pass if spec["metric"] in ("TOTAL_NETLOG","LIQUID_NETLOG") else None,
            metric_units="return" if spec["metric"] in ("ALPHA","DOWN","CVAR") else "log_NAV_ratio_per_session",
            zero_se_cannot_pass=not v["active"]))
    receipt=dict(status="COMPLETE",research_id=ID,rule=rule,shared_draw_sha256=draw_sha,
        named_endpoints=321,numeric_endpoints=len(estimates),failed_or_untestable=len(failed),
        critical_max_t=critical,se_ddof=1,quantile_method="higher",
        studentization="fixed bootstrap-SE plugin; no per-replicate SE refit",
        centering="sample-centered; then conditional bootstrap-mean recenter",
        historical_exposures_preserved=True,old_statistics_recomputed=False,
        limitation="Approximate simultaneous exploratory evidence on exposed pre2026 data; not independent confirmation")
    return pd.DataFrame(summary),receipt,maxima

def selection_daily(reference,panel,labels,clock):
    """UID-aligned entire-U diagnostics, with finite labels only on fixed support."""
    dates=_dates(clock);r=reference.sort_values(KEYS).reset_index(drop=True);p=panel.sort_values(KEYS).reset_index(drop=True)
    require(r[KEYS].equals(p[KEYS]) and not p.duplicated(KEYS).any(),"NO_FULL_U_SHRINK_OR_IDENTITY_STITCH")
    for name in ("ticker","U_t_fingerprint"):
        require(r[name].equals(p[name]),"EXACT_FULL_U_IDENTITY_REQUIRED")
    require(p.score.notna().all() and np.isfinite(p.score).all(),"INCOMPLETE_PREDICTION_POLICY_NOT_EVALUABLE")
    y=r.merge(labels[KEYS+["target"]],on=KEYS,how="left",validate="one_to_one").target.to_numpy(float)
    support=dict(zip(dates,clock.alpha_full_mature));rows=[];previous=None
    for day,ix in r.groupby("signal_date",sort=True).indices.items():
        a=p.iloc[ix].selected.to_numpy(bool);raw=r.iloc[ix].selected.to_numpy(bool);n=len(ix)
        require(a.sum()==raw.sum()==min(20,n),"SAME_TOP20_OR_FIXED_UNUSED_SLOTS_REQUIRED")
        require(np.all(p.iloc[ix].target_weight.to_numpy()==np.where(a,.05,0.)),"FIXED_FIVE_PERCENT_NO_NORMALIZATION")
        mature=bool(support[pd.Timestamp(day)]);truth=y[ix];members=set(p.iloc[ix].loc[a,"security_uid"])
        if mature:require(np.isfinite(truth).all(),"MATURE_FULL_U_LABEL_GAP")
        rows.append(dict(signal_date=day,year=int(pd.Timestamp(day).year),mature=mature,
            mean_er=float(truth[a].sum()/20) if mature else None,raw_mean_er=float(truth[raw].sum()/20) if mature else None,
            alpha_edge=shared.replacement_edge(truth,raw,a) if mature else None,
            raw_overlap=int((raw&a).sum()),raw_core10_replaced=int((r.iloc[ix]["rank"].to_numpy()<=10)[~a].sum()),
            selected_outside_raw40=int((r.iloc[ix]["rank"].to_numpy()[a]>40).sum()),
            member_turnover=None if previous is None else len(previous^members)/40,
            rank_ic=shared.correlation(-p.iloc[ix]["rank"].to_numpy(),truth) if mature else None))
        previous=members
    out=pd.DataFrame(rows);require(pd.DatetimeIndex(out.signal_date).equals(dates),"COMPLETE_752_SELECTION_DIAGNOSTICS_REQUIRED")
    return out

def account_qualification(daily,clock,policy_id):
    """Complete common account gate, shared by both NAV endpoint producers."""
    dates=_dates(clock);g=daily.sort_values("date");index=pd.DatetimeIndex(g.date)
    require(index.equals(dates) and g.research_accounting_qualified.eq(True).all(),"COMPLETE_QUALIFIED_ACCOUNT_WINDOW_REQUIRED")
    for field in ("TOTAL_ECONOMIC_NAV","LIQUID_NAV"):
        values=g[field].to_numpy(float)
        require(np.isfinite(values).all() and (values>0).all(),"BOTH_POSITIVE_COMPLETE_REAL_NAV_REQUIRED")
    return dict(policy_id=policy_id,status="PASS",research_accounting_qualified=True,complete_window=True,
        sessions=len(dates),calendar_sha256=_calendar_digest(dates))


def account_netlog(daily,clock,field):
    dates=_dates(clock);require(field in ("TOTAL_ECONOMIC_NAV","LIQUID_NAV"),"NAMED_DUAL_NAV_REQUIRED")
    account_qualification(daily,clock,"ENDPOINT_PRODUCER")
    values=daily.sort_values("date")[field].to_numpy(float)
    return pd.Series(np.log(values/np.r_[3000.,values[:-1]]),index=dates)
