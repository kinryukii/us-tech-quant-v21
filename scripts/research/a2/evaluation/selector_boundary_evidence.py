"""C12 cumulative evidence and post-freeze descriptive boundary diagnostics.

No readers, fits, model choice, calibration fitting or output writers live here.
The runner owns qualified source pins, pair SHA, maturity and final-pipeline gate.
Shared selector evidence remains the sole bootstrap/replacement-edge authority.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import selector_evidence as shared
from scripts.research.a2.evaluation import selector_classical_evidence as c11
from scripts.research.a2.factors import selector_boundary_pairs as pairs_owner

RESEARCH_ID = "V24_C_SELECTOR_RAW_ANCHORED_BOUNDARY_DECISION_LEARNING_C12"
ROLES = pairs_owner.ROLES
YEARS, YEAR_COUNTS, PRIMARY, BOOT_METHOD, TARGET = c11.YEARS, c11.YEAR_COUNTS, c11.PRIMARY, c11.BOOT_METHOD, c11.TARGET
PAIR_REGRET_DEFINITION = "mean(max(realized_pair_edge,0)-realized_pair_edge*predicted_eligible); isolated pair diagnostic, not matching regret"
PROBABILITY_BINS = tuple(np.linspace(0., 1., 11))
EDGE_BINS = (-np.inf, -.05, -.02, -.01, 0., .01, .02, .05, np.inf)


def _require(ok, message):
    if not ok: raise ValueError(message)


def _rule(rule, synthetic=False):
    _require(rule.get("method") == BOOT_METHOD and rule.get("seed") == 20260928
             and rule.get("confidence") == .95 and rule.get("family_candidates") == 156
             and isinstance(rule.get("repeats"), int) and rule["repeats"] >= 2
             and (synthetic or rule["repeats"] == 5000), "ORIGINAL_SHARED_5000_MAXT_RULE_REQUIRED")


def validate_design(design):
    _require(design.get("official_freeze") is True and design.get("formal_freeze_applied") is True
             and design.get("research_id") == RESEARCH_ID and tuple(design.get("roles", ())) == ROLES
             and design.get("target") == TARGET and tuple(design.get("primary_eval_years", ())) == YEARS,
             "EXACT_FORMAL_RAW_BOUNDARY_FREEZE_REQUIRED")
    _require(design.get("mechanism_research_eligible") is True
             and design.get("strict_PIT_promotion_eligible") is False
             and design.get("test2026_locked") is True and design.get("new2026_estimation_authorized") is False,
             "MECHANISM_ONLY_2026_LOCK_REQUIRED")
    ev = design["evaluation"]
    _require(ev.get("primary") == PRIMARY and ev.get("common_mature_date_count") == 732
             and ev.get("year_counts") == YEAR_COUNTS and ev.get("original_calendar_dates") == 752
             and ev.get("exposure_namespace") == 178 and ev.get("numeric_ceiling") == 156,
             "ORIGINAL_732_752_CLOCK_AND_178_EXPOSURE_REQUIRED")
    _rule(ev["bootstrap"])
    wanted = dict(pooled_edge_positive=True, year2025_edge_positive=True,
                  positive_years_min=2, simultaneous_lower_bound_gt_zero=True)
    _require(all(ev.get("inherited_selection_requirements", {}).get(k) == v for k,v in wanted.items()),
             "ORIGINAL_SUPPORT_THRESHOLD_REQUIRED")
    old = ev["legacy"]; numeric, exposure, failed = old["numeric_ids"], old["exposure_ids"], old["failed_or_untestable"]
    _require(len(numeric)==len(set(numeric))==147 and len(exposure)==len(set(exposure))==169
             and len(failed)==22 and not set(numeric)&set(failed)
             and set(numeric)|set(failed)==set(exposure) and not set(exposure)&set(ROLES),
             "CLOSED_147_NUMERIC_169_EXPOSURE_22_FAILED_HISTORY_REQUIRED")
    return ev


def validate_legacy_metadata(old_design, assembly, legacy):
    """Caller passes hash-qualified C11 metadata; economic evidence stays opaque."""
    ev = c11.validate_design(old_design)
    complete = list((*c11.A_ROLES,*c11.SANITY_ROLES))
    expected_failed = {**ev["legacy"]["failed_or_untestable"], **old_design["blocked_roles"]}
    _require(set(old_design["blocked_roles"])==set(c11.B_ROLES)
             and assembly.get("status")=="SCORE_ASSEMBLY_COMPLETE"
             and assembly.get("complete_candidates")==complete
             and assembly.get("failed_or_untestable")==old_design["blocked_roles"]
             and assembly.get("forecast2026_rows")==0
             and assembly.get("design_freeze_sha256")==legacy["design"]["sha256"]
             and legacy["numeric_ids"]==[*ev["legacy"]["numeric_ids"],*complete]
             and legacy["exposure_ids"]==[*ev["legacy"]["exposure_ids"],*c11.ROLES]
             and legacy["failed_or_untestable"]==expected_failed
             and legacy.get("sources")==old_design["sources"], "CLOSED_C11_METADATA_LINEAGE_CHANGED")
    return ev


def statistics(legacy_edges, new_edges, positions, calendar, rule, legacy_ids, failed=None, *, synthetic=False):
    """Only common 732-date series enter maxT; an empty new matrix is legitimate."""
    _rule(rule, synthetic)
    legacy_ids, failed = list(legacy_ids), dict(failed or {})
    calendar, positions, index = pd.DatetimeIndex(calendar), np.asarray(positions), legacy_edges.index
    _require(len(legacy_ids)==len(set(legacy_ids))==147 and list(legacy_edges)==legacy_ids
             and len(index)==732 and isinstance(index,pd.DatetimeIndex) and not index.has_duplicates
             and not index.hasnans and index.tz is None
             and {str(y):int((index.year==y).sum()) for y in YEARS}==YEAR_COUNTS
             and new_edges.index.equals(index) and not new_edges.columns.has_duplicates
             and set(new_edges).issubset(ROLES) and set(failed).issubset(ROLES)
             and not set(new_edges)&set(failed) and not set(legacy_ids)&set(ROLES)
             and np.isfinite(legacy_edges.to_numpy(float)).all() and np.isfinite(new_edges.to_numpy(float)).all()
             and len(calendar)==752 and not calendar.hasnans and not calendar.has_duplicates
             and calendar.tz is None and calendar.is_monotonic_increasing
             and (calendar<pd.Timestamp("2026-01-01")).all(), "EXACT_FINITE_732_752_COMMON_CLOCK_REQUIRED")
    _require(np.issubdtype(positions.dtype,np.integer) and len(positions)==len(index)
             and (positions>=0).all() and (positions<len(calendar)).all()
             and (np.diff(positions)>0).all() and calendar[positions].equals(index), "ORIGINAL_CALENDAR_POSITIONS_REQUIRED")
    matrix = legacy_edges.copy()
    for cid in ROLES:
        if cid in new_edges: matrix[cid]=new_edges[cid]
        else: failed.setdefault(cid,"UNTESTABLE_NO_COMPLETE_COMMON_2023_2024_2025_OOF")
    ids = list(matrix)
    _,_,previous,old_max = shared.shared_max_t(legacy_edges.to_numpy(float),positions,[True]*147,{**rule,"family_candidates":147})
    lower,se,receipt,maxima = shared.shared_max_t(matrix.to_numpy(float),positions,[True]*len(ids),{**rule,"family_candidates":len(ids)})
    _require(receipt.get("status")==previous.get("status")=="COMPLETE"
             and receipt["shared_draw_sha256"]==previous["shared_draw_sha256"]
             and len(maxima)==len(old_max) and (maxima+1e-12>=old_max).all()
             and receipt["critical_max_t"]+1e-12>=previous["critical_max_t"], "JOINT_MAXT_MUST_NOT_LOWER_LEGACY_THRESHOLD")
    summaries=[]
    for cid in ROLES:
        complete=cid in matrix; j=ids.index(cid) if complete else None
        yearly={str(y):float(matrix.loc[index.year==y,cid].mean()) if complete else None for y in YEARS}
        pooled=float(matrix[cid].mean()) if complete else None
        conditions=dict(complete_oof=complete,pooled_positive=pooled is not None and pooled>0,
            year2025_positive=yearly["2025"] is not None and yearly["2025"]>0,
            two_of_three_years_positive=sum(v is not None and v>0 for v in yearly.values())>=2,
            nonzero_bootstrap_se=bool(complete and np.isfinite(se[j]) and se[j]>shared.SE_TOL),
            simultaneous_lower_positive=bool(complete and np.isfinite(lower[j]) and lower[j]>0))
        summaries.append(dict(candidate_id=cid,status="COMPLETE" if complete else "FAILED_UNTESTABLE",
            failure_reason=failed.get(cid),pooled_edge=pooled,year_edges=yearly,
            bootstrap_se=float(se[j]) if complete and np.isfinite(se[j]) else None,
            simultaneous_lower_95=float(lower[j]) if complete and np.isfinite(lower[j]) else None,
            research_support_conditions=conditions,supported=all(conditions.values()),
            strict_PIT_promotion_eligible=False,economic_promotion_allowed=False))
    receipt.update(exposure_namespace=178,numeric_ceiling=156,legacy_numeric_complete_series=147,
        legacy_exposure_namespace=169,legacy_failed_or_blocked=22,numeric_complete_series=len(ids),
        new_exposure_roles=list(ROLES),failed_or_untestable=failed,
        failed_series="exposure metadata only; never zero placeholders",
        legacy_shared_draw_sha256=previous["shared_draw_sha256"],legacy_critical_max_t=previous["critical_max_t"],
        minimum_draw_wise_max_increment=float((maxima-old_max).min()),legacy_C11_reselected=False,
        descriptive_partial_years_entered_numeric=False,synthetic_validation_only=synthetic)
    return matrix,summaries,receipt,maxima


def _evaluation_reference(reference):
    needed=["signal_date","security_uid","raw_rank","target","label_end_date"]
    _require(isinstance(reference,pd.DataFrame) and set(needed).issubset(reference)
             and not reference.columns.has_duplicates,"EVALUATION_REFERENCE_REQUIRED")
    out=reference[needed].copy()
    out["signal_date"]=pd.to_datetime(out.signal_date);out["label_end_date"]=pd.to_datetime(out.label_end_date)
    pairs_owner._raw(out)
    _require(out.signal_date.dt.year.isin(YEARS).all(),"EXPOSED_PRE2026_2023_2024_2025_EVALUATION_ONLY")
    return out.sort_values(["signal_date","security_uid"],kind="stable").reset_index(drop=True)


def daily_diagnostics(cid,reference,panel,common=None):
    """Descriptive dates may be partial; they do not become a 732-date series."""
    _require(cid in ROLES,"FROZEN_C12_ROLE_REQUIRED")
    ref=_evaluation_reference(reference)
    _require(set(["signal_date","security_uid","rank"]).issubset(panel)
             and not panel.duplicated(["signal_date","security_uid"]).any(),"FULL_U_MEMBERSHIP_REQUIRED")
    p=panel[["signal_date","security_uid","rank"]].copy();p["signal_date"]=pd.to_datetime(p.signal_date)
    p=p.sort_values(["signal_date","security_uid"],kind="stable").reset_index(drop=True)
    _require(p[list(shared.KEY)].equals(ref[list(shared.KEY)]) and np.isfinite(p["rank"].to_numpy(float)).all(),"EXACT_FULL_U_NO_ROW_DROP")
    rows,previous=[],None
    for date,ix in ref.groupby("signal_date",sort=True).indices.items():
        group=ref.iloc[ix];ranks=p.iloc[ix]["rank"].to_numpy(float)
        _require(np.array_equal(np.sort(ranks),np.arange(1,len(group)+1)),"FULL_U_ORDINAL_MEMBERSHIP_REQUIRED")
        chosen=ranks<=20;raw=group.raw_rank.le(20).to_numpy();core=group.raw_rank.le(10).to_numpy()
        _require(chosen.sum()==20 and chosen[core].all() and group.loc[chosen,"raw_rank"].le(40).all(),"RAW_TOP10_TOP40_BOUNDARY_ONLY_REQUIRED")
        mature,_=shared.maturity(group.reset_index(drop=True),raw|chosen)
        included=bool(mature[raw|chosen].all())
        if common is not None:
            _require(date in common.index,"ORIGINAL_CALENDAR_MEMBERSHIP_REQUIRED")
            included=bool(common.loc[date]) and included
        y=group.target.to_numpy(float);entries=chosen&~raw;exits=raw&~chosen
        selected=set(group.loc[chosen,"security_uid"]);n=int(entries.sum())
        rows.append(dict(candidate_id=cid,signal_date=date,year=int(date.year),
            common_mature_date=included,descriptive_only=True,replacement_edge=shared.replacement_edge(y,raw,chosen) if included else None,
            raw_overlap=float((chosen&raw).sum()/20),replacement_count=n,
            membership_turnover=None if previous is None else len(previous^selected)/40,
            turnover_definition="previous available policy date; not an account turnover/cost",
            challenger_raw_rank_mean=float(group.loc[entries,"raw_rank"].mean()) if n else None,
            incumbent_raw_rank_mean=float(group.loc[exits,"raw_rank"].mean()) if n else None,
            challenger_raw_35_40_count=int((entries&group.raw_rank.between(35,40).to_numpy()).sum()),
            incumbent_raw_19_20_count=int((exits&group.raw_rank.between(19,20).to_numpy()).sum()),
            selected_replacement_realized_edge=float((y[entries].sum()-y[exits].sum())/n) if included and n else None,
            unmatched_incumbents=10-n))
        previous=selected
    return pd.DataFrame(rows)


def pair_diagnostics(cid,pairs,prediction,y_edges,matched_pairs=None,horizon_predictions=None):
    """Fixed-bin calibration/sign/regret summaries; never fit or choose a model."""
    _require(cid in ROLES,"FROZEN_C12_ROLE_REQUIRED")
    keysha=pairs_owner.pair_key_sha256(pairs);p=pairs[list(pairs_owner.PAIR_KEYS)].copy().reset_index(drop=True)
    p["signal_date"]=pd.to_datetime(p.signal_date)
    _require(p.signal_date.dt.year.isin(YEARS).all(),"EXPOSED_PRE2026_EVALUATION_ONLY")
    values,truth=np.asarray(prediction,float),np.asarray(y_edges,float)
    expected=(len(p),3) if cid==ROLES[8] else (len(p),)
    _require(values.shape==expected and np.isfinite(values).all() and truth.shape==(len(p),),"COMPLETE_PAIR_PREDICTION_AND_LABEL_SHAPE_REQUIRED")
    score=values[:,1] if cid==ROLES[8] else values
    if cid==ROLES[0]:
        _require(((score>=0)&(score<=1)).all(),"PAIR_SIGN_PROBABILITY_REQUIRED")
        eligible=score>.5
    elif cid==ROLES[8]:eligible=(values[:,0]>0)&(score>0)
    else:eligible=score>0
    horizon=None if horizon_predictions is None else np.asarray(horizon_predictions,float)
    if horizon is not None:
        _require(cid==ROLES[7] and horizon.shape==(len(p),4) and np.isfinite(horizon).all()
                 and np.allclose(horizon.mean(axis=1),score,rtol=1e-12,atol=1e-12),"FIXED_EQUAL_FOUR_HORIZON_SCORE_REQUIRED")
    match=pd.DataFrame(matched_pairs) if matched_pairs is not None else None
    if match is not None and len(match):
        _require(set(pairs_owner.PAIR_KEYS).issubset(match) and not match.duplicated(["signal_date","challenger_uid","incumbent_uid"]).any(),"MATCHED_PAIR_KEYS_REQUIRED")
        match=match.copy();match["signal_date"]=pd.to_datetime(match.signal_date)
        _require(match.merge(p,on=list(pairs_owner.PAIR_KEYS),how="left",indicator=True)._merge.eq("both").all(),"MATCHED_PAIRS_MUST_BE_FROZEN_PAIRS")
    rows,bins,ranks=[],[],[]
    for date,ix in p.groupby("signal_date",sort=True).indices.items():
        g=p.iloc[ix];s,y,ok=score[ix],truth[ix],eligible[ix];finite=bool(np.isfinite(y).all())
        predicted_sign=(s>.5) if cid==ROLES[0] else (s>0)
        selected=np.zeros(len(g),bool)
        if match is not None:
            m=match.loc[match.signal_date.eq(date)] if len(match) else match
            _require(len(m)<=10 and (not len(m) or m.challenger_uid.is_unique and m.incumbent_uid.is_unique),"ONE_TO_ONE_MATCH_DIAGNOSTIC_REQUIRED")
            chosenkeys=set(zip(m.challenger_uid,m.incumbent_uid)) if len(m) else set()
            selected=np.array([(e,i) in chosenkeys for e,i in zip(g.challenger_uid,g.incumbent_uid)])
            _require((~selected|ok).all(),"MATCH_DIAGNOSTIC_REQUIRES_LEGAL_POSITIVE_EDGES")
            for side,column in (("challenger","challenger_raw_rank"),("incumbent","incumbent_raw_rank")):
                for rank in g.loc[selected,column]:ranks.append(dict(candidate_id=cid,signal_date=date,year=int(date.year),side=side,raw_rank=int(rank)))
        n=int(selected.sum()) if match is not None else None
        rows.append(dict(candidate_id=cid,signal_date=date,year=int(date.year),descriptive_only=True,pair_key_sha256=keysha,
            pair_count=len(g),unavailable_label_pairs=int((~np.isfinite(y)).sum()),prediction_mean=float(s.mean()),
            actual_pair_edge_mean=float(y.mean()) if finite else None,
            pair_sign_accuracy=float((predicted_sign==(y>0)).mean()) if finite else None,
            pair_regret=float((np.maximum(y,0)-y*ok).mean()) if finite else None,pair_regret_definition=PAIR_REGRET_DEFINITION,
            mean_absolute_edge_error=float(np.abs(s-y).mean()) if finite and cid!=ROLES[0] else None,
            brier_score=float(((s-(y>0))**2).mean()) if finite and cid==ROLES[0] else None,
            replacement_count=n,selected_replacement_realized_edge=float(y[selected].mean()) if finite and n else None,
            horizon_prediction_disagreement_mean=float(horizon[ix].std(axis=1,ddof=0).mean()) if horizon is not None else None,
            quantile_crossing_fraction=float(((values[ix,0]>values[ix,1])|(values[ix,1]>values[ix,2])).mean()) if cid==ROLES[8] else None))
        if finite:
            boundaries=PROBABILITY_BINS if cid==ROLES[0] else EDGE_BINS
            assignment=np.clip(np.searchsorted(boundaries,s,side="right")-1,0,len(boundaries)-2)
            for binid in sorted(set(assignment)):
                take=assignment==binid
                bins.append(dict(candidate_id=cid,signal_date=date,year=int(date.year),bin_id=int(binid),pair_count=int(take.sum()),
                    date_pair_mass=float(take.sum()/200),prediction_mean=float(s[take].mean()),
                    realized_pair_edge_mean=float(y[take].mean()),realized_positive_rate=float((y[take]>0).mean()),
                    calibration_kind="probability event rate" if cid==ROLES[0] else "edge predicted versus realized mean",
                    descriptive_only=True))
    return pd.DataFrame(rows),pd.DataFrame(bins),pd.DataFrame(ranks)


def summarize_diagnostics(daily):
    """Date-equal yearly summaries and an explicit 0..10 replacement histogram."""
    _require(set(["candidate_id","signal_date","year","replacement_count"]).issubset(daily),"DAILY_DIAGNOSTICS_REQUIRED")
    metrics=[c for c in ("replacement_edge","raw_overlap","replacement_count","membership_turnover",
        "selected_replacement_realized_edge","pair_sign_accuracy","pair_regret","brier_score",
        "horizon_prediction_disagreement_mean") if c in daily]
    yearly=daily.groupby(["candidate_id","year"])[metrics].mean().reset_index()
    hist=daily.groupby(["candidate_id","year","replacement_count"]).size()
    grid=pd.MultiIndex.from_tuples([(cid,int(year),n) for cid,year in daily[["candidate_id","year"]].drop_duplicates().itertuples(index=False,name=None) for n in range(11)],names=hist.index.names)
    histogram=hist.reindex(grid,fill_value=0).rename("dates").reset_index()
    yearly["descriptive_only"]=True;histogram["descriptive_only"]=True
    return yearly,histogram


def oracle_headroom(reference,final_pipelines_freeze):
    """After all fitting/capacity selection: fixed core plus best 10 of Raw11..40."""
    gate=final_pipelines_freeze
    _require(gate.get("status")=="FINAL_PIPELINES_FROZEN" and gate.get("research_id")==RESEARCH_ID
             and gate.get("all_training_terminal") is True and gate.get("capacity_selection_complete") is True
             and tuple(gate.get("roles",()))==ROLES and set(gate.get("role_statuses",{}))==set(ROLES)
             and all(v in ("COMPLETE","PARTIAL_INPUT_BLOCKED","BLOCKED_INPUT","FAILED") for v in gate["role_statuses"].values())
             and isinstance(gate.get("design_sha256"),str) and len(gate["design_sha256"])==64,
             "FINAL_PIPELINES_FREEZE_REQUIRED_BEFORE_ORACLE")
    ref=_evaluation_reference(reference);rows=[]
    for date,ix in ref.groupby("signal_date",sort=True).indices.items():
        g=ref.iloc[ix].reset_index(drop=True);raw=g.raw_rank.le(20).to_numpy();boundary=g.raw_rank.between(11,40).to_numpy()
        mature,_=shared.maturity(g,raw|boundary)
        valid=bool(mature[raw|boundary].all());headroom=None;count=None
        if valid:
            best=g.loc[boundary].sort_values(["target","raw_rank","security_uid"],ascending=[False,True,True],kind="stable").head(10)
            chosen=g.raw_rank.le(10).to_numpy()|g.security_uid.isin(best.security_uid).to_numpy()
            headroom=shared.replacement_edge(g.target.to_numpy(float),raw,chosen)
            _require(headroom>=-1e-12,"NONNEGATIVE_ORACLE_HEADROOM_REQUIRED")
            count=int((chosen&~raw).sum())
        rows.append(dict(signal_date=date,year=int(date.year),boundary_oracle_headroom=headroom,
            oracle_replacement_count=count,common_boundary_labels_mature=valid,diagnostic_only=True,
            selector_eligible=False,used_for_capacity_selection=False,used_for_next_research_selection=False))
    return pd.DataFrame(rows)
