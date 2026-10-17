"""Thin production binding for the fixed monthly C risk experiment.

The reservation kernel owns budgets and the public risk/head owners own numerical
methods. This adapter adds persistence, exact cadence selection and epoch-safe
full-pool projection; it introduces no estimator, source authority or tuning.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import traceback

import numpy as np
import pandas as pd
import joblib

from scripts.common import storage_paths
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.data.selector_frozen_history import FrozenHistoryReader
from scripts.research.a2.training import selector_monthly_risk as kernel
from scripts.research.a2.training import selector_challenge as prior
from scripts.research.a2.training import selector_risk_challenge as old
from scripts.research.a2.training import selector_cooperation as coop

KEY = ["signal_date", "security_uid"]
ROLES = (*kernel.preflight.ROLES, *kernel.REFERENCES)
FLAGS = dict(mechanism_research_eligible=True, strict_PIT_promotion_eligible=False,
             test2026_locked=True)


def checked(run):
    context = kernel.checked(run)
    if context["authority_mode"] != kernel.FH_MODE:
        raise kernel.ExecutionBlocked("PRODUCTION_FROZEN_HISTORY_MODE_REQUIRED")
    design = prior.readj(Path(run)/"DESIGN_FREEZE.json")
    if design["sources"].get(str(Path(__file__).resolve())) != prior.sha(__file__):
        raise kernel.ExecutionBlocked("PRODUCTION_ADAPTER_SOURCE_PIN_REQUIRED")
    return context, design


def output(run, relative):
    path = Path(run)/relative
    storage_paths.assert_safe_output_path(path, kind="backtest")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def state(run, phase, **values):
    path = output(run, "PIPELINE_STATE.json")
    value = prior.readj(path) if path.exists() else {}
    value.update(phase=phase, updated_at=prior.now(), **FLAGS, **values)
    prior.putj(path, value)
    prior.emit(phase=phase, **values)


def paths_for_risk(run, slot):
    period = pd.Timestamp(slot["cutoff"]).strftime("%Y%m%d")
    stem = f"risk_{slot['cadence'].lower()}/{period}_{slot['method']}"
    return output(run, "models/"+stem+".json"), output(run, "models/"+stem+".joblib")


def validate_risk_receipt(context,slot,receipt,model_path):
    if (receipt.get("design_sha256") != context["design_sha256"]
            or receipt.get("status") != "FITTED"
            or receipt.get("source_proof_sha256") != context["source_proof_sha256"]
            or any(receipt.get(key) != slot[key] for key in ("slot_id","cutoff","cadence","method"))
            or prior.sha(model_path) != receipt.get("model_sha256")):
        raise kernel.ExecutionBlocked("SUCCESSFUL_RISK_PERSISTENCE_CHANGED")


def ledger_events(context):
    _, ledger = kernel._ledger(context)
    return {entry["id"]: entry for entry in ledger["events"]}


def risk_bank(run, reader):
    """One durable risk attempt per 260 frozen slots, persist before success."""
    context, design = checked(run)
    for slot in context["slots"]:
        if slot["kind"] != "RISK":
            continue
        receipt_path, model_path = paths_for_risk(run, slot)
        events = ledger_events(context)
        if slot["slot_id"] in events:
            event = events[slot["slot_id"]]
            if event["status"] == "SUCCEEDED":
                receipt = prior.readj(receipt_path)
                validate_risk_receipt(context,slot,receipt,model_path)
            continue
        state(run, "RISK_BANK", status="RUNNING", slot_id=slot["slot_id"])
        def persist(current, bundle, coverage, metadata, universe):
            if current != slot:
                raise kernel.ExecutionBlocked("RISK_PERSISTENCE_SLOT_CHANGED")
            coverage_path = output(run, f"derived/coverage/{slot['cadence'].lower()}_{pd.Timestamp(slot['cutoff']).strftime('%Y%m%d')}_{slot['method']}.parquet")
            coverage.to_parquet(coverage_path, index=False)
            joblib.dump(bundle, model_path, compress=3)
            receipt = dict(status="FITTED", slot_id=slot["slot_id"],
                design_sha256=context["design_sha256"], source_proof_sha256=context["source_proof_sha256"],
                model_path=str(model_path), model_sha256=prior.sha(model_path),
                coverage_path=str(coverage_path), coverage_sha256=prior.sha(coverage_path),
                cutoff=slot["cutoff"], cadence=slot["cadence"], method=slot["method"],
                universe_epochs=dict(zip(universe.security_uid, universe.identity_epoch)),
                estimated_assets=list(bundle.estimated_assets), panel_qualification=metadata,
                estimator_budget=bundle.budget, actual_backend_fit_calls=slot["reservation"]["risk_backend_fit_calls"],
                **FLAGS)
            prior.putj(receipt_path, receipt)
        try:
            kernel.fit_risk_slot(run, slot["slot_id"], reader, persist_result=persist)
        except Exception as exc:
            prior.putj(receipt_path, dict(status="FAILED", slot_id=slot["slot_id"],
                design_sha256=context["design_sha256"], error=str(exc),
                traceback=traceback.format_exc(), actual_backend_fit_calls="UNKNOWN",
                retry_allowed=False, **FLAGS))
            prior.emit(phase="RISK_FAILURE_RETAINED", slot_id=slot["slot_id"], error=str(exc))
    state(run, "RISK_BANK", status="ATTEMPTS_COMPLETE")


def effective_slot(slots, day, method, cadence):
    """Monthly state may apply on its first accepted session; annual is Jan1."""
    day = pd.Timestamp(day)
    candidates = [slot for slot in slots if slot["kind"] == "RISK"
        and slot["method"] == method and slot["cadence"] == cadence
        and pd.Timestamp(slot["cutoff"]).year == day.year
        and pd.Timestamp(slot["cutoff"]) <= day]
    if not candidates:
        raise kernel.ExecutionBlocked("NO_LEGAL_CADENCE_STATE")
    return max(candidates, key=lambda slot: pd.Timestamp(slot["cutoff"]))


def epoch_projection(bundle, bank_epochs, keys, current_epochs):
    if len(keys) != len(current_epochs) or keys.security_uid.duplicated().any():
        raise ValueError("FULL_U_EPOCH_KEYS_CHANGED")
    # Unknown epoch names remain in equal-mass full-U; they cannot borrow an old
    # UID covariance merely because a UID or ticker reappears after a boundary.
    requested = [uid if bank_epochs.get(uid) == epoch else f"UNKNOWN_EPOCH:{uid}:{epoch}"
                 for uid, epoch in zip(keys.security_uid, current_epochs)]
    return kernel.project_full_pool(bundle, requested)


def _reuse_manifest(design):
    pin = design["base_oof_reuse"]
    if prior.sha(pin["path"]) != pin["sha256"]:
        raise kernel.ExecutionBlocked("CALIBRATED_REUSE_MANIFEST_CHANGED")
    metadata = prior.readj(pin["path"])
    entries = metadata["entries"]
    if {(entry["model"],entry["year"]) for entry in entries} != {
            (member, year) for member in old.MEMBERS for year in kernel.preflight.YEARS}:
        raise kernel.ExecutionBlocked("EXACT20_CALIBRATED_BANK_REQUIRED")
    parent = Path(design["parent_run"]).resolve()
    for entry in entries:
        for prefix in ("prediction", "calibration_receipt", "native_fit_receipt"):
            path = Path(entry[prefix+"_path"]).resolve()
            if not path.is_relative_to(parent) or prior.sha(path) != entry[prefix+"_sha256"]:
                raise kernel.ExecutionBlocked("CALIBRATED_BANK_ARTIFACT_CHANGED")
        guard_parquet(entry["prediction_path"], entry["prediction_sha256"], ["signal_date"])
    return metadata


def joined_base(run, cal):
    _, design = checked(run)
    _reuse_manifest(design)
    return {year: old.parent_members(Path(design["parent_run"]), year, cal, coop)
            .sort_values(KEY).reset_index(drop=True) for year in kernel.preflight.YEARS}


def projections(run, reader, bases):
    context, _ = checked(run)
    events = ledger_events(context)
    models = {}
    # One epoch lookup per year, shared by all five cores and both cadences.
    epoch_values = {year: reader.epoch_keys(base) for year, base in bases.items()}
    for cadence in ("MONTHLY", "ANNUAL"):
        for year, base in bases.items():
            for method in kernel.preflight.CORE:
                dest = output(run, f"predictions/risk_{cadence.lower()}_{method}_{year}.parquet")
                receipt_dest = dest.with_suffix(".json")
                if dest.exists() and receipt_dest.exists():
                    receipt = prior.readj(receipt_dest)
                    if receipt["design_sha256"] != context["design_sha256"] or receipt["sha256"] != prior.sha(dest):
                        raise kernel.ExecutionBlocked("PERSISTED_PROJECTION_CHANGED")
                    continue
                out = base[KEY+["ticker"]].copy()
                result, cutoffs = np.empty((len(out), 3)), np.empty(len(out), dtype="datetime64[ns]")
                try:
                    for positions in out.groupby("signal_date", sort=True).indices.values():
                        day = out.iloc[positions].signal_date.iloc[0]
                        slot = effective_slot(context["slots"], day, method, cadence)
                        if events.get(slot["slot_id"], {}).get("status") != "SUCCEEDED":
                            raise kernel.ExecutionBlocked("MISSING_CORE_STATE:"+slot["slot_id"])
                        if slot["slot_id"] not in models:
                            meta_path, model_path = paths_for_risk(run, slot)
                            meta = prior.readj(meta_path)
                            validate_risk_receipt(context,slot,meta,model_path)
                            models[slot["slot_id"]] = joblib.load(model_path), meta
                        bundle, meta = models[slot["slot_id"]]
                        keys = out.iloc[positions]
                        result[positions] = epoch_projection(bundle, meta["universe_epochs"], keys,
                            [epoch_values[year][position] for position in positions])
                        cutoffs[positions] = np.datetime64(pd.Timestamp(slot["cutoff"]))
                    for index, suffix in enumerate(("marginal_sigma","pool_covariance_normalized","unknown_flag")):
                        out[f"{method}__{suffix}"] = result[:,index]
                    out["risk_cutoff"] = cutoffs
                    out["eligibility_upgraded"] = False
                    if not np.isfinite(result).all() or not out.risk_cutoff.le(out.signal_date).all():
                        raise ValueError("RISK_FULL_U_OR_CLOCK_INVALID")
                    out.to_parquet(dest,index=False)
                    prior.putj(receipt_dest, dict(status="COMPLETE",sha256=prior.sha(dest),rows=len(out),
                        design_sha256=context["design_sha256"],cadence=cadence,method=method,year=year,
                        unknown_rows=int(out[f"{method}__unknown_flag"].sum()),**FLAGS))
                except Exception as exc:
                    prior.putj(receipt_dest, dict(status="BLOCKED_DEPENDENCY",design_sha256=context["design_sha256"],
                        error=str(exc),**FLAGS))
                    prior.emit(phase="PROJECTION_BLOCKED",cadence=cadence,method=method,year=year,error=str(exc))
    state(run, "RISK_PROJECTION", status="ATTEMPTS_COMPLETE")


def join_risk(run, base, year, cadence):
    context,_=checked(run)
    result = base.copy()
    for method in kernel.preflight.CORE:
        path = Path(run)/f"predictions/risk_{cadence.lower()}_{method}_{year}.parquet"
        if not path.exists():
            raise kernel.ExecutionBlocked("MISSING_CORE_PROJECTION:"+str(path))
        receipt = prior.readj(path.with_suffix(".json"))
        if (receipt.get("design_sha256") != context["design_sha256"]
                or receipt.get("status") != "COMPLETE" or receipt.get("sha256") != prior.sha(path)):
            raise kernel.ExecutionBlocked("INVALID_CORE_PROJECTION_RECEIPT")
        value = pd.read_parquet(path).sort_values(KEY).reset_index(drop=True)
        if not value[KEY+["ticker"]].equals(base[KEY+["ticker"]]):
            raise ValueError("RISK_FULL_U_COMMON_POOL_CHANGED")
        columns = [column for column in value if column.startswith(method+"__")]
        result = result.merge(value[KEY+columns],on=KEY,validate="one_to_one")
    return result


def head_columns(role):
    if role not in ROLES:
        raise ValueError("FIFTH_ROLE_OR_REFERENCE_FORBIDDEN")
    suffixes = ("unknown_flag",) if "COVERAGE_FLAG_ONLY" in role else (
        "marginal_sigma","pool_covariance_normalized","unknown_flag")
    return [member+"__mu" for member in old.MEMBERS]+[
        method+"__"+suffix for method in kernel.preflight.CORE for suffix in suffixes]


def fit_head_arrays(role, history, current, cutoff, cal):
    """Established chronological OOF guard/sample/scaler/head recipe."""
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from threadpoolctl import threadpool_limits
    h = history.loc[history.label_end_date.lt(cutoff)&history.target.notna()].copy()
    h, _ = coop._guard(h,cutoff,"CALIBRATED_OOF")
    h = cal.sample(h)
    columns = head_columns(role)
    x,y,w = h[columns].to_numpy(float),h.target.to_numpy(float),cal.date_weights(h.signal_date)
    future = current[columns].to_numpy(float)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(future).all():
        raise ValueError("FINITE_COMPLETE_HEAD_INPUT_REQUIRED")
    scaler = StandardScaler().fit(x,sample_weight=w)
    model = cal.tree() if "HGB" in role else Ridge(alpha=100.)
    with threadpool_limits(limits=2):
        model.fit(scaler.transform(x),y,sample_weight=w)
        values = model.predict(scaler.transform(future))
    if not np.isfinite(values).all():
        raise ValueError("FINITE_FULL_SCORE_REQUIRED")
    return values, dict(scaler=scaler,model=model,columns=columns),dict(
        rows=len(h),max_train_signal=str(h.signal_date.max()),
        max_train_label_end=str(h.label_end_date.max()),fit_cutoff_exclusive=str(cutoff.date()),
        source_kind="CALIBRATED_OOF_WITH_FROZEN_HISTORY_PRIOR_RISK",actual_backend_fit_calls=2)


def heads(run, bases, cal):
    context, _ = checked(run)
    joined = {}
    for slot in context["slots"]:
        if slot["kind"] != "ANNUAL_HEAD":
            continue
        role,year = slot["role"],slot["year"]
        meta_path=output(run,f"models/{role}/{year}.json")
        model_path=meta_path.with_suffix(".joblib")
        prediction_path=output(run,f"predictions/native_{role}_{year}.parquet")
        event=ledger_events(context).get(slot["slot_id"])
        if event:
            if event["status"] == "SUCCEEDED":
                receipt=prior.readj(meta_path)
                if receipt["design_sha256"] != context["design_sha256"] or prior.sha(prediction_path) != receipt["prediction_sha256"] or prior.sha(model_path) != receipt["model_sha256"]:
                    raise kernel.ExecutionBlocked("HEAD_PERSISTENCE_CHANGED")
            continue
        state(run,"HEAD_TRAINING",status="RUNNING",role=role,year=year)
        def operation(current_slot):
            cadence="ANNUAL" if role in kernel.REFERENCES else "MONTHLY"
            for y in range(2022,year+1):
                if (cadence,y) not in joined:
                    joined[(cadence,y)]=join_risk(run,bases[y],y,cadence)
            current=joined[(cadence,year)]
            history=pd.concat([joined[(cadence,y)] for y in range(2022,year)],ignore_index=True)
            cutoff=pd.Timestamp(f"{year}-01-01")
            values,model,receipt=fit_head_arrays(role,history,current,cutoff,cal)
            joblib.dump(model,model_path,compress=3)
            part=current[KEY+["ticker","U_t_fingerprint","target","label_end_date"]].copy()
            part["score"],part["candidate_id"],part["source_cutoff"],part["source_kind"]=values,role,cutoff,"PIPELINE_OOF"
            part.to_parquet(prediction_path,index=False)
            prior.putj(meta_path,dict(status="TRAINED",role=role,year=year,design_sha256=context["design_sha256"],
                model_path=str(model_path),model_sha256=prior.sha(model_path),
                prediction_path=str(prediction_path),prediction_sha256=prior.sha(prediction_path),
                **receipt,**FLAGS))
        try:
            kernel.execute(run,slot["slot_id"],operation)
        except Exception as exc:
            prior.putj(meta_path,dict(status="FAILED_UNTESTABLE",role=role,year=year,
                design_sha256=context["design_sha256"],error=str(exc),traceback=traceback.format_exc(),
                actual_backend_fit_calls="UNKNOWN",retry_allowed=False,**FLAGS))
            prior.emit(phase="HEAD_FAILURE_RETAINED",role=role,year=year,error=str(exc))
    state(run,"HEAD_TRAINING",status="ATTEMPTS_COMPLETE")


def assemble(run):
    context,design=checked(run)
    complete,refs,failed,score_paths=[],[],{},{}
    common_keys=None
    events=ledger_events(context)
    for role in ROLES:
        parts=[Path(run)/f"predictions/native_{role}_{year}.parquet" for year in (2023,2024,2025)]
        qualified=True
        for year,path in zip((2023,2024,2025),parts):
            meta_path=Path(run)/f"models/{role}/{year}.json"
            event=events.get(f"ANNUAL_HEAD:{role}:{year}",{})
            if event.get("status") != "SUCCEEDED" or not path.exists() or not meta_path.exists():
                qualified=False
                break
            receipt=prior.readj(meta_path)
            if (receipt.get("status") != "TRAINED" or receipt.get("role") != role
                    or receipt.get("year") != year or receipt.get("design_sha256") != context["design_sha256"]
                    or receipt.get("prediction_path") != str(path)
                    or receipt.get("prediction_sha256") != prior.sha(path)
                    or receipt.get("model_sha256") != prior.sha(receipt["model_path"])):
                qualified=False
                break
        if not qualified:
            failed[role]="MISSING_QUALIFIED_SUCCESSFUL_THREE_YEAR_OOF"
            continue
        frame=pd.concat([pd.read_parquet(path) for path in parts],ignore_index=True)
        keys=frame[KEY].sort_values(KEY).reset_index(drop=True)
        if common_keys is None:
            common_keys=keys
        if not keys.equals(common_keys):
            raise ValueError("ROLE_FULL_U_COMMON_KEYS_CHANGED")
        path=output(run,f"predictions/scores_{role}_pre2026.parquet")
        prior.rank_panel(frame,pd).to_parquet(path,index=False)
        score_paths[role]=dict(path=str(path),sha256=prior.sha(path))
        (refs if role in kernel.REFERENCES else complete).append(role)
    raw_id="RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE"
    raw_pin=design["score_reuse"][raw_id]
    guard_parquet(raw_pin["path"],raw_pin["sha256"],["signal_date"])
    raw_keys=pd.read_parquet(raw_pin["path"],columns=KEY).sort_values(KEY).reset_index(drop=True)
    if common_keys is not None and not common_keys.equals(raw_keys):
        raise ValueError("NEW_SCORE_FULL_U_DIFFERS_FROM_FIXED_RAW_REFERENCE")
    assembly=dict(complete_candidates=complete,complete_fixed_references=refs,failed_or_untestable=failed,
        score_paths=score_paths,common_rows=len(raw_keys),common_dates=raw_keys.signal_date.nunique(),
        raw_candidate_id=raw_id,forecast2026_rows=0,design_freeze_sha256=context["design_sha256"],**FLAGS)
    prior.putj(output(run,"SCORE_ASSEMBLY.json"),assembly)
    evaluation=prior.REPO/"scripts/research/a2/evaluation"
    sources={str(path):prior.sha(path) for path in [evaluation/"selector_frozen_history_evidence.py",
        evaluation/"selector_evidence.py",evaluation/"selector_account_compare.py"]}
    if any(design["sources"].get(path) != value for path,value in sources.items()):
        raise kernel.ExecutionBlocked("EVALUATION_SOURCE_NOT_FORMALLY_FROZEN")
    prior.putj(output(run,"EVALUATION_CODE_ACTIVATION.json"),dict(
        design_freeze_sha256=context["design_sha256"],score_assembly_sha256=prior.sha(Path(run)/"SCORE_ASSEMBLY.json"),sources=sources,**FLAGS))
    state(run,"ASSEMBLY",status="COMPLETE",complete_roles=len(complete),complete_fixed_references=len(refs),failed_roles=len(failed))
    return assembly


def run_training(run, phase="all"):
    _,design=checked(run)
    # Create only this run's declared cache locations before package imports.
    config=prior.readj(Path(run)/"run_config.json")
    cache=Path(config["cache_directory"])
    for name in ("temp","matplotlib","torch","package_cache"):
        path=cache/name
        storage_paths.assert_safe_output_path(path,kind="cache")
        path.mkdir(parents=True,exist_ok=True)
    # The existing runtime routes temporary files and fixes BLAS threads.
    rt=prior.runtime(Path(run))
    cal=rt[8]
    reader=FrozenHistoryReader(design["frozen_history_source"]["path"],design["frozen_history_source"]["sha256"])
    if phase in ("risk","all"):
        risk_bank(run,reader)
    if phase in ("heads","all"):
        bases=joined_base(run,cal)
        projections(run,reader,bases)
        heads(run,bases,cal)
    if phase in ("assemble","all"):
        return assemble(run)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--phase",choices=("risk","heads","assemble","all"),default="all")
    args=parser.parse_args()
    run=args.run.resolve()
    try:
        run_training(run,args.phase)
    except Exception as exc:
        state(run,"PIPELINE_EXCEPTION",status="FAILED",error=str(exc),traceback=traceback.format_exc())
        raise


if __name__=="__main__":
    main()
