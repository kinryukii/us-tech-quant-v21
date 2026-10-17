"""Target/horizon adapter: reuse fixed native heads, data sampling and evidence owners."""
from __future__ import annotations
import argparse, json, time, traceback
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_challenge as prior
from scripts.research.a2.training import selector_algorithm_breadth as old
from scripts.research.a2.evaluation import selector_evidence as evidence
from scripts.research.a2.evaluation.selector_account_compare import sha, pre2026
REPO=Path(__file__).resolve().parents[4]
ID="V24_C_SELECTOR_TARGET_HORIZON_BREADTH_C7"
YEARS=(2023,2024,2025)
REFERENCES=("HORIZON_MEAN_RIDGE","HORIZON_MEAN_HGB")
NEW_ROLES=tuple(f"HORIZON_ER_{h}D_{m}" for h in (3,5,10,20) for m in ("RIDGE","HGB"))
ROLES=REFERENCES+NEW_ROLES
KEYS=old.KEYS
readj,putj,now=old.readj,old.putj,old.now
BUDGET=dict(scientific_model_year_slots=30,reused_model_year_slots=6,
    new_estimator_fit_calls=24,new_scaler_fit_calls=24,backend_fit_calls=48,
    scientific_retries=0,risk_fit_calls=0,calibration_fit_calls=0,
    configs_per_role=1,seeds_per_role=1,workers=1,threads=2)

def emit(run,**values):
    state=dict(updated_at=now(),research_id=ID,mechanism_research_eligible=True,
        strict_PIT_promotion_eligible=False,test2026_locked=True,**values)
    putj(run/"PIPELINE_STATE.json",state);print(json.dumps(state),flush=True)

def role_specs():
    return {r:dict(head=r.rsplit("_",1)[1].lower(),training_target=r.split("_")[1]+"_"+r.split("_")[2],
        end_column="target_end_date_"+r.split("_")[2].lower()) for r in NEW_ROLES}

def checked(run):
    run=Path(run).resolve();paths=resolve(REPO);assert_safe_output_path(run,kind="backtest",paths=paths)
    cfg,d=readj(run/"run_config.json"),readj(run/"DESIGN_FREEZE.json")
    digest=sha(run/"DESIGN_FREEZE.json")
    if digest!=readj(run/"DESIGN_FREEZE_SHA.json")["sha256"] or cfg.get("design_freeze_sha256")!=digest:raise ValueError("FREEZE_IDENTITY_CHANGED")
    if (d.get("research_id")!=ID or d.get("official_freeze") is not True or d.get("formal_freeze_applied") is not True
        or tuple(d.get("roles",()))!=ROLES or d.get("role_specs")!=role_specs() or d.get("budget")!=BUDGET
        or d.get("target")!="MEAN_ER_3D_5D_10D_20D" or d.get("seed")!=20260928
        or d.get("strict_PIT_promotion_eligible") is not False or d.get("test2026_locked") is not True
        or d.get("new2026_estimation_authorized") is not False or len(d.get("features",[]))!=32):
        raise ValueError("FINITE_TARGET_ONLY_FREEZE_REQUIRED")
    if readj(run/"FORMAL_FREEZE_REVIEW.json").get("status")!="PASS":raise ValueError("INDEPENDENT_FREEZE_REVIEW_REQUIRED")
    required={str(p) for p in old.required_source_paths()}|{str(Path(__file__).resolve()),str(REPO/"scripts/research/a2/evaluation/selector_horizon_evidence.py")}
    if not required.issubset(d.get("sources",{})):raise ValueError("FROZEN_SOURCE_CLOSURE_REQUIRED")
    if cfg.get("research_id")!=ID or cfg.get("research_line")!="C_SELECTOR":raise ValueError("RUN_IDENTITY_CHANGED")
    if tuple(d.get("new_fitting_years",()))!=YEARS or d.get("features")!=d.get("fixed_features"):raise ValueError("FIXED_TIME_FEATURE_ORDER_REQUIRED")
    if sha(d["physical_dag"]["path"])!=d["physical_dag"]["sha256"]:raise ValueError("FROZEN_DAG_CHANGED")
    activation=readj(run/"FREEZE_ACTIVATION.json")
    if activation.get("status")!="PASS" or activation.get("design_freeze_sha256")!=digest:raise ValueError("FREEZE_ACTIVATION_REQUIRED")
    for path,digest in d["sources"].items():
        if sha(path)!=digest:raise ValueError("FROZEN_SOURCE_CHANGED:"+path)
    for field in ("horizon_inputs","native_reuse_manifest","source_contract"):
        pin=d[field]
        if sha(pin["path"])!=pin["sha256"]:raise ValueError("INPUT_RECEIPT_CHANGED:"+field)
    source=readj(d["source_contract"]["path"])
    if source.get("strict_PIT_promotion_eligible") is not False or source.get("mechanism_research_eligible") is not True:raise ValueError("SOURCE_PREMISE_CHANGED")
    for field,kind in (("results_directory","results"),("cache_directory","cache")):
        assert_safe_output_path(Path(cfg[field]),kind=kind,paths=paths)
    return cfg,d

def attach_horizon_training(train,labels):
    key=["signal_date","ticker","security_uid"]
    if labels.duplicated(key).any() or train.duplicated(key).any():raise ValueError("DUPLICATE_LABEL_IDENTITY")
    columns=[f"ER_{h}D" for h in (3,5,10,20)]
    ends=[f"target_end_date_{h}d" for h in (3,5,10,20)]
    if (pd.to_datetime(labels.signal_date).ge("2026-01-01").any()
        or any(pd.to_datetime(labels[c]).ge("2026-01-01").any() for c in ends)):
        raise ValueError("LABEL_BOUNDARY_CHANGED")
    merged=train.merge(labels[key+columns+ends],on=key,how="left",validate="one_to_one")
    if len(merged)!=len(train) or not np.isfinite(merged[columns].to_numpy(float)).all():raise ValueError("FULL_TRAINING_KEYS_MUST_HAVE_ALL_TARGETS")
    if not np.allclose(merged[columns].mean(axis=1),merged.target,rtol=0,atol=1e-12):raise ValueError("ORIGINAL_MEAN_TARGET_CHANGED")
    if not pd.to_datetime(merged.target_end_date_20d).equals(pd.to_datetime(merged.target_end_date)):raise ValueError("ORIGINAL_COMMON_MATURITY_CHANGED")
    return merged

def sample_fold(train,year,expected):
    cutoff=pd.Timestamp(f"{year}-01-01")
    full=train.loc[train.signal_date.lt(cutoff)&train.target_end_date.lt(cutoff)].copy()
    sampled=prior.sampled(full,pd,np)
    key=["signal_date","ticker","security_uid","target_end_date"]
    if not sampled[key].reset_index(drop=True).equals(expected[key].reset_index(drop=True)):raise ValueError("TARGET_BLIND_SHARED_KEYS_CHANGED")
    if any(not pd.to_datetime(sampled[f"target_end_date_{h}d"]).lt(cutoff).all() for h in (3,5,10,20)):raise ValueError("LABEL_NOT_MATURE_AT_FOLD")
    return sampled

def ledger_checked(run,d,ledger):
    old.validate_ledger(run,d,ledger)
    if (len(ledger["events"])>24 or ledger["charged_backend_ceiling"]>48
        or any(e["role"] not in NEW_ROLES for e in ledger["events"])):raise ValueError("C7_BUDGET_OR_ANCHOR_FIT_VIOLATION")
    return ledger

def anchor_bindings(run,d):
    reuse=readj(d["native_reuse_manifest"]["path"])
    refs={}
    for cid in REFERENCES:
        item=reuse["score_refs"][cid]
        if sha(item["path"])!=item["sha256"]:raise ValueError("MEAN_REFERENCE_CHANGED")
        frame=pre2026(item["path"],KEYS+["score","rank","candidate_id"],"signal_date")
        original=frame.copy();frame["candidate_id"]=cid
        out=run/f"predictions/scores_{cid}_pre2026.parquet";out.parent.mkdir(parents=True,exist_ok=True)
        if out.exists():
            actual=pre2026(out,KEYS+["score","rank","candidate_id"],"signal_date")
            if not actual.equals(frame):raise ValueError("REFERENCE_ALIAS_CHANGED")
        else:frame.to_parquet(out,index=False)
        if not frame[KEYS+["score","rank"]].equals(original[KEYS+["score","rank"]]):raise ValueError("ANCHOR_VALUE_CHANGED")
        refs[cid]={"path":str(out),"sha256":sha(out),"source":item,"new_fit_calls":0}
    return refs

def train(run):
    cfg,d=checked(run);rt=prior.runtime(run);old.guard_backend(rt,d)
    jb,pred=rt[4],rt[5]
    from sklearn.preprocessing import StandardScaler
    train,valid=old.read_inputs(run,rt,d)
    pin=d["horizon_labels"]
    if sha(pin["path"])!=pin["sha256"]:raise ValueError("HORIZON_LABELS_CHANGED")
    labels=pre2026(pin["path"],["signal_date","ticker","security_uid",*[f"ER_{h}D" for h in (3,5,10,20)],*[f"target_end_date_{h}d" for h in (3,5,10,20)]],("signal_date","target_end_date_20d"))
    train=attach_horizon_training(train,labels)
    ledger=ledger_checked(run,d,old.new_ledger(run,d))
    reuse=readj(d["native_reuse_manifest"]["path"])
    samples={x["year"]:x for x in reuse["training_samples"]}
    anchor_bindings(run,d)
    for year in YEARS:
        sample=samples[year]
        if sha(sample["path"])!=sample["sha256"]:raise ValueError("SAMPLED_KEY_RECEIPT_CHANGED")
        expected=pre2026(sample["path"],["signal_date","ticker","security_uid","target_end_date"],("signal_date","target_end_date"))
        sampled=sample_fold(train,year,expected);cutoff=pd.Timestamp(f"{year}-01-01")
        va=valid.loc[valid.signal_date.dt.year.eq(year)].sort_values(["signal_date","security_uid"]).reset_index(drop=True)
        x,vx=sampled[d["features"]].to_numpy(float),va[d["features"]].to_numpy(float)
        for role in NEW_ROLES:
            saved=next((e for e in ledger["events"] if e["slot_id"]==f"{role}:{year}"),None)
            if saved:
                if saved["status"]=="TRAINED":old.qualify_existing_success(run,d,saved);continue
                if saved["status"]=="FAILED":continue
                raise ValueError("NO_RETRY_OF_UNFINISHED_SCIENTIFIC_SLOT")
            checked(run);ledger_checked(run,d,ledger)
            if len(ledger["events"])>=24 or ledger["charged_backend_ceiling"]+2>48:raise ValueError("C7_BUDGET_EXCEEDED")
            event=old.reserve(run,ledger,role,year);start=time.monotonic()
            emit(run,phase="TRAINING",status="RUNNING",role=role,year=year)
            try:
                old.entered(run,ledger,event,"scaler");scaler=StandardScaler().fit(x);old.completed(run,ledger,event,"scaler")
                spec=d["role_specs"][role];head=spec["head"];y=sampled[spec["training_target"]].to_numpy(float)
                model=pred._make_estimator(head)
                if model.get_params()!=d["head_specs"][head]:raise ValueError("HEAD_CONFIGURATION_CHANGED")
                old.entered(run,ledger,event,"estimator")
                detail=pred._fit_one(model,scaler.transform(x),y,head,sampled.signal_date)
                old.completed(run,ledger,event,"estimator")
                if detail["status"]!="TRAINED":raise ValueError("FAILED_NATIVE_FIT")
                fitted=pred.FittedPredictor(head,scaler,[model],[detail])
                values=pred.predict_raw(fitted,vx,va.signal_date)["raw"]
                if values.shape!=(len(va),) or not np.isfinite(values).all():raise ValueError("FULL_U_T_NATIVE_SCORE_REQUIRED")
                panel=va[KEYS].copy();panel["score"]=values;panel["candidate_id"]=role;panel["source_kind"]="MODEL_OOF";panel["source_cutoff"]=cutoff
                mp=run/f"models/{role}/{year}.joblib";pp=run/f"predictions/native_{role}_{year}.parquet"
                mp.parent.mkdir(parents=True,exist_ok=True);pp.parent.mkdir(parents=True,exist_ok=True)
                jb.dump(fitted,mp,compress=3);panel.to_parquet(pp,index=False)
                rec=dict(status="TRAINED",role=role,year=year,design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),objective_spec=spec,
                    cutoff=str(cutoff.date()),max_train_signal_date=str(sampled.signal_date.max()),max_train_label_end=str(sampled.target_end_date.max()),
                    max_training_target_end=str(sampled[spec["end_column"]].max()),sampled_keys_sha256=sample["sha256"],
                    model={"path":str(mp),"sha256":sha(mp)},prediction={"path":str(pp),"sha256":sha(pp)},details=detail,
                    rows_train=len(sampled),rows_prediction=len(va),actual_fit_calls_entered=event["actual_fit_calls_entered"],
                    seconds=time.monotonic()-start,head_config=model.get_params())
                putj(mp.with_suffix(".json"),rec);event.update(status="TRAINED",completed_at=now(),receipt_path=str(mp.with_suffix(".json")))
            except Exception as exc:
                putj(run/f"models/{role}/{year}.json",dict(status="FAILED",role=role,year=year,error=type(exc).__name__,message=str(exc),
                    traceback=traceback.format_exc(),actual_fit_calls_entered=event["actual_fit_calls_entered"],reservation_retained=2,scientific_retry_allowed=False))
                event.update(status="FAILED",completed_at=now(),message=str(exc))
            putj(run/"FIT_LEDGER.json",ledger);ledger_checked(run,d,ledger)
    putj(run/"TRAINING_COMPLETE.json",dict(status="FINITE_ATTEMPTS_COMPLETE",scientific_model_year_slots=30,reused_model_year_slots=6,
        attempts=len(ledger["events"]),charged_backend_ceiling=ledger["charged_backend_ceiling"],
        actual_backend_fit_calls_entered=ledger["actual_backend_fit_calls_entered"],backend_fit_calls_completed=ledger["backend_fit_calls_completed"],scientific_retries=0))
    emit(run,phase="TRAINING",status="COMPLETE")

def assemble(run):
    cfg,d=checked(run);ledger=ledger_checked(run,d,readj(run/"FIT_LEDGER.json"))
    rawpin=d["score_reuse"][evidence.RAW]
    if sha(rawpin["path"])!=rawpin["sha256"]:raise ValueError("RAW_SCORE_CHANGED")
    raw=pre2026(rawpin["path"],KEYS,"signal_date").sort_values(["signal_date","security_uid","ticker"]).reset_index(drop=True)
    bindings={evidence.RAW:rawpin,**anchor_bindings(run,d)};complete=[];failed={}
    for role in NEW_ROLES:
        events=[e for e in ledger["events"] if e["role"]==role]
        if len(events)!=3 or any(e["status"]!="TRAINED" for e in events):
            failed[role]="MISSING_COMPLETE_THREE_YEAR_NATIVE_OOF";continue
        parts=[]
        for event in sorted(events,key=lambda e:e["year"]):
            rec=old.qualify_existing_success(run,d,event)
            part=pre2026(rec["prediction"]["path"],KEYS+["score","candidate_id","source_kind","source_cutoff"],("signal_date","source_cutoff"))
            if not part.source_kind.eq("MODEL_OOF").all() or not pd.to_datetime(part.source_cutoff).lt(pd.to_datetime(part.signal_date)).all():raise ValueError("OOF_LINEAGE_CHANGED")
            parts.append(part)
        panel=pd.concat(parts,ignore_index=True).sort_values(["signal_date","security_uid","ticker"]).reset_index(drop=True)
        if not panel[KEYS].equals(raw) or not np.isfinite(panel.score).all():failed[role]="FULL_U_T_PRESERVATION_FAILED";continue
        panel=prior.rank_panel(panel,pd);out=run/f"predictions/scores_{role}_pre2026.parquet";panel.to_parquet(out,index=False)
        bindings[role]={"path":str(out),"sha256":sha(out)};complete.append(role)
    receipt=dict(schema="C_HORIZON_SCORE_ASSEMBLY_V1",complete_candidates=complete,complete_fixed_references=list(REFERENCES),
        failed_or_untestable=failed,score_paths=bindings,common_rows=len(raw),common_dates=raw.signal_date.nunique(),
        forecast2026_rows=0,design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"))
    putj(run/"SCORE_ASSEMBLY.json",receipt)
    from scripts.research.a2.evaluation import selector_horizon_evidence as ev
    sources=[Path(ev.__file__),Path(evidence.__file__),REPO/"scripts/research/a2/evaluation/selector_account_compare.py",REPO/"scripts/research/a2/evaluation/selector_algorithm_breadth_evidence.py"]
    putj(run/"EVALUATION_CODE_ACTIVATION.json",dict(design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),
        score_assembly_sha256=sha(run/"SCORE_ASSEMBLY.json"),sources={str(p):sha(p) for p in sources}))
    emit(run,phase="ASSEMBLY",status="COMPLETE",complete_roles=len(complete),failed_roles=len(failed))

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--phase",choices=["train","assemble","all"],default="all");args=parser.parse_args()
    if args.phase in ("train","all"):train(args.run)
    if args.phase in ("assemble","all"):assemble(args.run)
    if args.phase=="all":
        from scripts.research.a2.evaluation.selector_horizon_evidence import run as evaluate
        evaluate(args.run);emit(args.run,phase="EVIDENCE",status="COMPLETE_REPORT_PENDING")
if __name__=="__main__":main()
