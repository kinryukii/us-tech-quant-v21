"""Pure numerical evaluation of caller-owned R10 states/observations.

No reader, writer, fit, calibration transform or model selection. These diagnostic
summaries are never input features or historical quote/account qualification.
"""
import numpy as np
import pandas as pd
from .shared_risk_engine_r2 import RiskState, META, COORDINATE, CUTOFF, _time
from .joint_risk_estimators import validate_covariance


def state_numerical_diagnostics(states):
    result=[]
    for state in states:
        row=dict(risk_state_id=state.risk_state_id,method=state.method,horizon=state.horizon,
            as_of=str(state.as_of),cutoff=str(state.cutoff),assets=len(state.assets),
            source_identity=state.source_identity,source_status=state.status,
            effective_N=state.effective_sample_size,shrinkage=state.shrinkage_intensity,
            strict_PIT_promotion_eligible=False,account_qualified=False,quote_qualified=False)
        if state.covariance is None:
            row.update(status="BLOCKED_INPUT",reason=state.notes.get("block_reason"))
        else:
            try:
                if not _time(state.cutoff)<_time(state.as_of)<CUTOFF or state.return_coordinate!=COORDINATE:
                    raise ValueError("STATE_TIME_OR_COORDINATE")
                matrix,psd=validate_covariance(state.covariance,regularize=False)
                eig=np.linalg.eigvalsh(matrix);condition=float(np.linalg.cond(matrix))
                if not np.isfinite(condition) or condition>1e12:raise ValueError("STATE_CONDITION")
                row.update(status="PASS_NUMERICAL_DIAGNOSTIC_ONLY",PSD=psd,
                    min_eigenvalue=float(eig.min()),max_eigenvalue=float(eig.max()),condition_number=condition,
                    native_horizon=state.method!="RM",time_scale_proxy=state.method=="RM",
                    fit_year=int(_time(state.as_of).year),coverage=state.coverage)
            except (ValueError,TypeError,np.linalg.LinAlgError) as exc:
                row.update(status="BLOCKED_NUMERICAL",reason=str(exc))
        result.append(row)
    return result


def volatility_downside_diagnostic(state,observations,*,assets,uids,reference_assets,evaluation_end):
    """Fixed equal-q matured native-return forecast check; no estimated calibrator.

    Metadata projects eligible rows BEFORE touching return_value. The observed
    source identity remains distinct from the forecast source. Any missing basket
    member/SID/source coordinate fails closed. Overlap N/H is a structural proxy,
    never an IID effective-size certificate. Actual 2026 values are never read.
    """
    assets=tuple(assets);reference_assets=tuple(reference_assets);end=_time(evaluation_end)
    if (not isinstance(state,RiskState) or not state.assets or state.covariance is None
            or end>CUTOFF or not _time(state.as_of)<end
            or not assets or len(set(assets))!=len(assets) or set(uids)!=set(assets)
            or not reference_assets or len(set(reference_assets))!=len(reference_assets)
            or not set(reference_assets).issubset(assets)
            or state.return_coordinate!=COORDINATE):raise ValueError("DIAGNOSTIC_REFERENCE_TIME_COORDINATE")
    if any(a not in state.assets or state.coverage.get(a,{}).get("uid")!=uids[a] for a in assets):
        raise ValueError("DIAGNOSTIC_SID_DOMAIN_UNBOUND")
    required=(*META,"mechanism_coordinate_supported","return_value")
    if not isinstance(observations,pd.DataFrame) or not set(required).issubset(observations.columns):
        raise ValueError("NATIVE_RETURN_DIAGNOSTIC_PROOF_REQUIRED")
    meta=observations.loc[:,list(META)+["mechanism_coordinate_supported"]].copy()
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):meta[c]=meta[c].map(_time)
    legal=meta.asset.isin(assets)&meta.horizon.eq(state.horizon)&meta.origin_at.ge(_time(state.as_of))
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):legal &= meta[c].lt(end)&meta[c].lt(CUTOFF)
    meta=meta.loc[legal]
    if not meta.mechanism_coordinate_supported.map(lambda x:isinstance(x,(bool,np.bool_)) and bool(x)).all():
        raise ValueError("DIAGNOSTIC_QUANTITY_COORDINATE_UNSUPPORTED")
    if not meta.uid.eq(meta.asset.map(uids)).all():raise ValueError("DIAGNOSTIC_OBSERVATION_UID_SWAP")
    if not ((meta.origin_at<meta.entry_at)&(meta.entry_at<meta.endpoint_at)&(meta.endpoint_at<=meta.matured_at)&(meta.matured_at<=meta.available_at)).all():
        raise ValueError("DIAGNOSTIC_OBSERVATION_CLOCK")
    values=observations.loc[meta.index,["asset","origin_at","return_value"]].copy()
    if values.duplicated(["asset","origin_at"]).any():raise ValueError("DIAGNOSTIC_DUPLICATE_NATIVE_RETURN")
    if not np.isfinite(pd.to_numeric(values.return_value,errors="raise").to_numpy(float)).all():raise ValueError("DIAGNOSTIC_NONFINITE_LEGAL_RETURN")
    panel=values.pivot(index="origin_at",columns="asset",values="return_value").reindex(columns=assets)
    complete=panel.dropna(how="any")
    if len(complete)<2:return dict(status="BLOCKED_HISTORY",complete_origins=len(complete),account_qualified=False,reason="FEWER_THAN_TWO_COMPLETE_MATURED_NATIVE_BASKETS")
    positions=[state.assets.index(a) for a in assets]
    matrix,_=validate_covariance(np.asarray(state.covariance)[np.ix_(positions,positions)],regularize=False)
    q=np.asarray([1/len(reference_assets) if a in reference_assets else 0. for a in assets])
    predicted=float(np.sqrt(max(q@matrix@q,0.)));realized=complete.to_numpy(float)@q
    observed=float(np.std(realized,ddof=1));downside=float(np.sqrt(np.mean(np.minimum(realized,0.)**2)))
    predicted_downside=None
    if state.downside_state is not None:
        negative=np.asarray(state.downside_state["downside_second_moment"])[np.ix_(positions,positions)]
        predicted_downside=float(np.sqrt(max(q@negative@q,0.)))
    return dict(status="PASS_CALIBRATION_DIAGNOSTIC_ONLY",risk_state_id=state.risk_state_id,horizon=state.horizon,
        forecast_source_identity=state.source_identity,observed_source_identities=tuple(sorted(meta.source_identity.unique())),
        nominal_complete_origins=len(complete),structural_overlap_N_over_H=len(complete)/state.horizon,
        missing_basket_origins=len(panel)-len(complete),observed_first=str(complete.index.min()),observed_last=str(complete.index.max()),
        predicted_portfolio_sigma=predicted,observed_portfolio_sigma=observed,
        sigma_ratio=observed/predicted if predicted>0 else None,predicted_downside_sigma=predicted_downside,
        observed_downside_sigma=downside,downside_ratio=downside/predicted_downside if predicted_downside else None,
        not_a_fitted_calibrator=True,not_input_feature=True,account_qualified=False,quote_qualified=False,
        strict_PIT_promotion_eligible=False,**{"2026_locked":True})



def projection_native_diagnostics(projections, observations, *, evaluation_end):
    """Exact-origin native reference-basket evaluation; no fit, I/O or selection.

    Annual state domains do not define the realized basket. Each immutable daily
    request defines its own fixed equal-q reference at that same origin. Legal
    metadata and complete reference SID/quantity support are checked before any
    return body is touched. A missing member is never filled or replaced.
    """
    from collections import Counter
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    end=_time(evaluation_end)
    if end>CUTOFF:raise ValueError("PROJECTION_DIAGNOSTIC_PRE2026_END_REQUIRED")
    required=(*META,"mechanism_coordinate_supported","return_value")
    if not isinstance(observations,pd.DataFrame) or not set(required).issubset(observations.columns):
        raise ValueError("PROJECTION_NATIVE_OBSERVATION_SCHEMA_REQUIRED")
    if not observations.index.is_unique:raise ValueError("PROJECTION_OBSERVATION_INDEX_UNIQUE_REQUIRED")
    meta=observations.loc[:,list(META)+["mechanism_coordinate_supported"]].copy()
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):
        meta[c]=meta[c].map(_time)
    false_flags=dict(strict_PIT_promotion_eligible=False,account_qualified=False,quote_qualified=False,
                     not_a_fitted_calibrator=True,not_input_feature=True,**{"2026_locked":True})
    by_origin_h={(origin,h):group for (origin,h),group in meta.groupby(["origin_at","horizon"],sort=False)}
    items=list(projections);keys=[]
    for item in items:
        request=item.get("request",{})
        keys.append((str(request.get("date")),item.get("representation"),request.get("horizon"),request.get("cohort")))
    duplicates={k for k,v in Counter(keys).items() if v>1}
    rows=[]
    for item,key in zip(items,keys):
        request=item.get("request",{});row=dict(date=request.get("date"),representation=item.get("representation"),
            horizon=request.get("horizon"),cohort=request.get("cohort"),**false_flags)
        try:
            if key in duplicates:raise ValueError("DUPLICATE_REFERENCE_REQUEST")
            origin=_time(request["decision_at"]);day=pd.Timestamp(request["date"])
            if day.tzinfo is not None or day!=day.normalize() or origin!=_clock(day) or not origin<end or not origin<CUTOFF:
                raise ValueError("EXACT_REQUEST_ORIGIN_CLOCK_REQUIRED")
            h=request["horizon"]
            if type(h) is not int or h not in (3,5,10,20):raise ValueError("NATIVE_HORIZON_REQUIRED")
            assets=tuple(request["assets"]);reference=tuple(request["reference_assets"]);uids=request["uids"]
            if (not assets or len(set(assets))!=len(assets) or set(uids)!=set(assets) or not reference
                    or len(set(reference))!=len(reference) or not set(reference).issubset(assets)
                    or any(not isinstance(uids[a],str) or not uids[a].strip() for a in assets)):
                raise ValueError("REFERENCE_REQUEST_SID_DOMAIN_REQUIRED")
            row.update(year=int(day.year),origin_at=str(origin),reference_assets=reference,
                       reference_uids={a:uids[a] for a in reference})
            view=item["projection"]
            matrix,_=validate_covariance(view["reference_covariance"],regularize=False)
            if matrix.shape!=(len(assets),len(assets)):raise ValueError("PROJECTION_MATRIX_DOMAIN")
            q=np.asarray([1/len(reference) if a in reference else 0. for a in assets])
            weights=view["reference_weights"]
            if set(weights)!=set(assets) or not np.allclose([weights[a] for a in assets],q,rtol=0,atol=1e-15):
                raise ValueError("EXACT_FIXED_REFERENCE_WEIGHTS_REQUIRED")
            predicted=float(view["diagnostics"]["predicted_portfolio_sigma"])
            if (not np.isfinite(predicted) or predicted<0 or not np.isclose(predicted,np.sqrt(max(q@matrix@q,0.)),rtol=1e-10,atol=1e-12)
                    or not np.isclose(predicted,float(view["features"]["portfolio_sigma"]),rtol=1e-10,atol=1e-12)):
                raise ValueError("SOURCE_OWNED_PREDICTED_SIGMA_IDENTITY")
            refs=item.get("state_refs",{})
            if not refs or any(v.get("verified") is not True or not isinstance(v.get("risk_state_id"),str) or not v["risk_state_id"] for v in refs.values()):
                raise ValueError("VERIFIED_SOURCE_OWNED_STATE_REFERENCES_REQUIRED")
            origin_rows=by_origin_h.get((origin,h),meta.iloc[:0])
            selected=origin_rows.loc[origin_rows.asset.isin(reference)]
            if selected.asset.duplicated().any():raise ValueError("DUPLICATE_EXACT_NATIVE_MEMBER")
            if set(selected.asset)!=set(reference):raise ValueError("INCOMPLETE_EXACT_NATIVE_REFERENCE_BASKET")
            if not selected.uid.eq(selected.asset.map(uids)).all():raise ValueError("EXACT_NATIVE_SID_MISMATCH")
            if not selected.mechanism_coordinate_supported.map(lambda x:isinstance(x,(bool,np.bool_)) and bool(x)).all():
                raise ValueError("EXACT_NATIVE_QUANTITY_COORDINATE_UNSUPPORTED")
            if not selected.source_identity.map(lambda x:isinstance(x,str) and bool(x.strip())).all():raise ValueError("NATIVE_SOURCE_IDENTITY_UNBOUND")
            if not selected.identity_epoch.map(lambda x:isinstance(x,str) and bool(x.strip())).all():raise ValueError("NATIVE_IDENTITY_EPOCH_UNBOUND")
            if not ((selected.origin_at<selected.entry_at)&(selected.entry_at<selected.endpoint_at)
                    &(selected.endpoint_at<=selected.matured_at)&(selected.matured_at<=selected.available_at)).all():
                raise ValueError("EXACT_NATIVE_OBSERVATION_CLOCK")
            if any(not selected[c].lt(end).all() or not selected[c].lt(CUTOFF).all()
                   for c in ("entry_at","endpoint_at","matured_at","available_at")):
                raise ValueError("EXACT_NATIVE_REFERENCE_NOT_MATURED")
            # Read only the metadata-admitted complete same-origin basket.
            values=pd.to_numeric(observations.loc[selected.index,"return_value"],errors="raise").to_numpy(float)
            if not np.isfinite(values).all():raise ValueError("NONFINITE_EXACT_NATIVE_RETURN")
            realized=float(values.mean())
            downside=view["features"].get("portfolio_downside_sigma")
            downside_basis="SOURCE_OWNED_TAIL_STATE" if downside is not None else None
            if downside is None and item.get("representation")=="R7":
                downside=view["features"].get("group_features",{}).get("R4",{}).get("portfolio_downside_sigma")
                downside_basis="R4_SOURCE_OWNED_TAIL_STATE" if downside is not None else None
            if downside is not None:
                downside=float(downside)
                if not np.isfinite(downside) or downside<0:raise ValueError("SOURCE_OWNED_DOWNSIDE_NONFINITE")
            row.update(status="PASS_EXACT_MATURED_REFERENCE_DIAGNOSTIC_ONLY",predicted_portfolio_sigma=predicted,
                       realized_reference_return=realized,predicted_downside_sigma=downside,downside_basis=downside_basis,
                       observed_source_identities=tuple(sorted(selected.source_identity.unique())),
                       observed_identity_epochs=tuple(sorted(selected.identity_epoch.unique())),
                       forecast_state_refs={k:v["risk_state_id"] for k,v in refs.items()},
                       last_matured_at=str(selected.matured_at.max()),last_available_at=str(selected.available_at.max()))
        except (ValueError,TypeError,KeyError,np.linalg.LinAlgError) as exc:
            row.update(status="BLOCKED_REFERENCE_DIAGNOSTIC",reason=str(exc))
        rows.append(row)
    groups={}
    for row in rows:
        k=(row["representation"],row["horizon"],row["cohort"],row.get("year"))
        groups.setdefault(k,[]).append(row)
    aggregates=[]
    for (representation,h,cohort,year),group in groups.items():
        valid=[r for r in group if r["status"]=="PASS_EXACT_MATURED_REFERENCE_DIAGNOSTIC_ONLY"]
        a=dict(representation=representation,horizon=h,cohort=cohort,year=year,total_requests=len(group),
               matured_complete_reference_requests=len(valid),blocked_requests=len(group)-len(valid),
               blocked_reason_counts=dict(Counter(r.get("reason") for r in group if r["status"]!="PASS_EXACT_MATURED_REFERENCE_DIAGNOSTIC_ONLY")),
               nominal_N=len(valid),structural_overlap_N_over_H=len(valid)/h if type(h) is int and h>0 else None,
               effective_IID_N_certified=False,**false_flags)
        if not valid:
            a.update(status="BLOCKED_HISTORY_NO_COMPLETE_MATURED_REFERENCE_BASKET")
        else:
            p=np.asarray([r["predicted_portfolio_sigma"] for r in valid]);real=np.asarray([r["realized_reference_return"] for r in valid])
            pred=float(np.sqrt(np.mean(p*p)));observed=float(np.std(real,ddof=1)) if len(real)>1 else None
            tail=[r for r in valid if r["predicted_downside_sigma"] is not None]
            pred_tail=float(np.sqrt(np.mean([r["predicted_downside_sigma"]**2 for r in tail]))) if tail else None
            matched_tail=float(np.sqrt(np.mean([min(r["realized_reference_return"],0.)**2 for r in tail]))) if tail else None
            a.update(status="PASS_REFERENCE_CALIBRATION_DIAGNOSTIC_ONLY" if len(valid)>1 else "BLOCKED_SAMPLE_SIZE_ONE_REFERENCE_DIAGNOSTIC",
                     predicted_sigma_rms=pred,observed_reference_sigma=observed,sigma_ratio=observed/pred if observed is not None and pred>0 else None,
                     observed_reference_downside_sigma=float(np.sqrt(np.mean(np.minimum(real,0.)**2))),
                     predicted_downside_sigma_rms=pred_tail,matched_observed_downside_sigma=matched_tail,
                     downside_prediction_matched_N=len(tail),downside_ratio=matched_tail/pred_tail if pred_tail else None,
                     observed_source_identities=tuple(sorted({s for r in valid for s in r["observed_source_identities"]})),
                     forecast_state_ids=tuple(sorted({s for r in valid for s in r["forecast_state_refs"].values()})),
                     first_origin=min(r["origin_at"] for r in valid),last_origin=max(r["origin_at"] for r in valid))
        aggregates.append(a)
    return dict(schema="R10_PROJECTION_NATIVE_DIAGNOSTIC_R1",request_rows=rows,aggregate_rows=aggregates,**false_flags)
