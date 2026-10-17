
"""Finite training-sufficiency study; reuse frozen data/rank/objective owners."""
from __future__ import annotations
import argparse, hashlib, json, time, traceback
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_challenge as prior
from scripts.research.a2.training import selector_algorithm_breadth as old
from scripts.research.a2.training import selector_sufficiency_estimators as kernel
from scripts.research.a2.evaluation import selector_evidence as evidence
from scripts.research.a2.evaluation.selector_account_compare import sha, pre2026
REPO=Path(__file__).resolve().parents[4]
ID="V24_C_SELECTOR_TRAINING_SUFFICIENCY_C10"
PARADIGMS=("POINT_HGB","BOUNDARY_HGB","PAIRWISE_MLP","LISTWISE_MLP","RANK_XGB_NDCG")
CAPACITIES=("LOW","MEDIUM","HIGH")
YEARS=(2023,2024,2025)
STATES=("LEGACY_40K_FIXED","FULL_BALANCED_FIXED","FULL_BALANCED_NESTED")
ROLES=tuple(f"C10_{p}_{s}" for p in PARADIGMS for s in STATES)+("C10_RIDGE_FULL_BALANCED",)
NEW_ROLES=tuple(f"C10_{p}_{s}" for p in PARADIGMS for s in STATES[1:])+("C10_RIDGE_FULL_BALANCED",)
REFERENCES=tuple(f"C10_{p}_LEGACY_40K_FIXED" for p in PARADIGMS)+("C10_RIDGE_LEGACY_40K_FIXED",)
ALL_ROLES=REFERENCES+NEW_ROLES
CUTS=tuple(f"{y}-{m}-01" for y,m in ((2022,"01"),(2022,"07"),(2023,"01"),(2023,"07"),(2024,"01"),(2024,"07"),(2025,"01")))
KEYS=old.KEYS
readj,putj,now=old.readj,old.putj,old.now
BUDGET=dict(main_outer_model_year_slots=45,legacy_main_reuse=15,legacy_sanity_reuse=3,new_outer_logical_slots=33,
 inner_logical_slots=90,unique_estimator_ceiling=103,unique_scaler_ceiling=7,backend_fit_ceiling=110,
 scientific_retries=0,risk_fit_calls=0,calibration_fit_calls=0,configs_per_tier=1,capacity_tiers=3,
 seeds_per_role=1,workers=1,threads=2)
def folds(year):
 return [(f"{year-1}-01-01",f"{year-1}-07-01"),(f"{year-1}-07-01",f"{year}-01-01")]
def emit(run,**state):
 putj(run/"PIPELINE_STATE.json",dict(research_id=ID,updated_at=now(),mechanism_research_eligible=True,
 strict_PIT_promotion_eligible=False,test2026_locked=True,**state));print(json.dumps(state),flush=True)
def checked(run):
 run=Path(run).resolve();paths=resolve(REPO);assert_safe_output_path(run,kind="backtest",paths=paths)
 cfg,d=readj(run/"run_config.json"),readj(run/"DESIGN_FREEZE.json");digest=sha(run/"DESIGN_FREEZE.json")
 if (digest!=readj(run/"DESIGN_FREEZE_SHA.json")["sha256"] or cfg.get("design_freeze_sha256")!=digest
     or cfg.get("research_id")!=ID or cfg.get("research_line")!="C_SELECTOR"):raise ValueError("FREEZE_IDENTITY_CHANGED")
 if (d.get("research_id")!=ID or d.get("official_freeze") is not True or d.get("formal_freeze_applied") is not True
     or tuple(d.get("roles",()))!=ALL_ROLES or tuple(d.get("scientific_roles",()))!=ROLES or tuple(d.get("new_fitting_years",()))!=YEARS
     or d.get("target")!="MEAN_ER_3D_5D_10D_20D" or d.get("seed")!=20260928 or d.get("budget")!=BUDGET
     or d.get("features")!=d.get("fixed_features") or len(d.get("features",[]))!=32
     or d.get("strict_PIT_promotion_eligible") is not False or d.get("test2026_locked") is not True
     or d.get("new2026_estimation_authorized") is not False):raise ValueError("FINITE_FIXED_X_MEAN_NESTED_FREEZE_REQUIRED")
 required={str(x) for x in old.required_source_paths()}|{str(Path(__file__).resolve()),str(Path(kernel.__file__).resolve()),
  str(REPO/"scripts/research/a2/evaluation/selector_sufficiency_evidence.py"),
  str(REPO/"scripts/research/a2/evaluation/selector_horizon_evidence.py")}
 if not required.issubset(d["sources"]):raise ValueError("FROZEN_SOURCE_CLOSURE_REQUIRED")
 for p,s in d["sources"].items():
  if sha(p)!=s:raise ValueError("FROZEN_SOURCE_CHANGED:"+p)
 for field in ("source_contract","native_reuse_manifest","physical_dag","input_qualification"):
  if sha(d[field]["path"])!=d[field]["sha256"]:raise ValueError("FROZEN_INPUT_OR_DAG_CHANGED:"+field)
 review=readj(run/"FORMAL_FREEZE_REVIEW.json")
 if (review.get("status")!="PASS" or review.get("design_freeze_sha256")!=digest
     or sha(d["independent_source_review"]["path"])!=d["independent_source_review"]["sha256"]):raise ValueError("FORMAL_REVIEW_REQUIRED")
 source=readj(d["source_contract"]["path"])
 if source.get("mechanism_research_eligible") is not True or source.get("strict_PIT_promotion_eligible") is not False:raise ValueError("SOURCE_PREMISE_CHANGED")
 act=readj(run/"FREEZE_ACTIVATION.json")
 if act.get("status")!="PASS" or act.get("design_freeze_sha256")!=digest:raise ValueError("ACTIVATION_REQUIRED")
 for n,k in (("results_directory","results"),("cache_directory","cache")):assert_safe_output_path(Path(cfg[n]),kind=k,paths=paths)
 return cfg,d
def full_pool(train,cutoff):
 cut=pd.Timestamp(cutoff);pool=train.loc[train.signal_date.lt(cut)&train.target_end_date.lt(cut)].copy()
 return pool.sort_values(["signal_date","security_uid","ticker"],kind="stable").reset_index(drop=True)
def row_weights(dates):
 clock=pd.DatetimeIndex(pd.to_datetime(dates))
 if len(clock)==0 or clock.hasnans:raise ValueError("WEIGHT_CLOCK_REQUIRED")
 counts=pd.Series(clock).value_counts()
 weights=len(clock)/(len(counts)*pd.Series(clock).map(counts).to_numpy(float))
 if not np.isfinite(weights).all() or (weights<=0).any() or not np.isclose(weights.sum(),len(clock)):raise ValueError("DATE_WEIGHT_NORMALIZATION")
 return weights
def inner_frame(frame,start,end):
 part=frame.loc[frame.signal_date.ge(start)&frame.signal_date.lt(end)].copy()
 legal=np.isfinite(part.target)&part.label_end_date.notna()&part.label_end_date.lt(end)
 good=legal.groupby(part.signal_date).all()
 part=part.loc[part.signal_date.isin(good[good].index)].sort_values(["signal_date","security_uid","ticker"]).reset_index(drop=True)
 if part.empty or part.groupby("signal_date").size().min()<20:raise ValueError("INNER_FULL_U_MATURE_DATES_REQUIRED")
 return part
def key_digest(frame):
 cols=["signal_date","ticker","security_uid","target_end_date"]
 return hashlib.sha256(pd.util.hash_pandas_object(frame[cols],index=False).to_numpy(np.uint64).tobytes()).hexdigest()
def qualify(run,d,rt):
 if (run/"INPUT_QUALIFICATION.json").exists() or (run/"DESIGN_FREEZE.json").exists():raise FileExistsError("PRESERVE_EXISTING_INPUT_QUALIFICATION")
 (run/"derived").mkdir(parents=True,exist_ok=True)
 train,frame=old.read_inputs(run,rt,d);facts={}
 for cut in CUTS:
  pool=full_pool(train,cut)
  if not np.isfinite(pool[d["features"]+["target"]].to_numpy(float)).all():raise ValueError("FULL_MATURE_INPUT_NOT_FINITE")
  p=run/f"derived/full_keys_{cut.replace('-','')}.parquet"
  pool[["signal_date","ticker","security_uid","target_end_date"]].to_parquet(p,index=False)
  facts[cut]=dict(rows=len(pool),dates=pool.signal_date.nunique(),key_digest=key_digest(pool),keys=dict(path=str(p),sha256=sha(p)),
   max_train_signal=str(pool.signal_date.max()),max_train_label_end=str(pool.target_end_date.max()),
   min_date_rows=int(pool.groupby("signal_date").size().min()),max_date_rows=int(pool.groupby("signal_date").size().max()),
   weights="N_rows/(N_dates*N_t)",sum_weights=float(row_weights(pool.signal_date).sum()))
 validation=[]
 for year in YEARS:
  for start,end in folds(year):
   part=inner_frame(frame,start,end);clock=part[["signal_date","security_uid","ticker","U_t_fingerprint","label_end_date"]]
   p=run/f"derived/inner_keys_{start.replace('-','')}_{end.replace('-','')}.parquet";clock.to_parquet(p,index=False)
   validation.append(dict(outer_year=year,fit_cutoff=start,validation_end=end,rows=len(part),dates=part.signal_date.nunique(),
    max_label_end=str(part.label_end_date.max()),keys=dict(path=str(p),sha256=sha(p))))
 q=dict(status="QUALIFIED_FROZEN_HISTORY_NO_FIT",research_id=ID,training=facts,validation=validation,
  strict_PIT_promotion_eligible=False,fit_calls=0,test2026_rows_read=0,new_provider_fetches=0,F_accesses=0,
  no_outcome_statistics_used=True,validation_date_policy="all original U rows need finite original mean label and label_end<inner end; no model-based date shrink")
 putj(run/"INPUT_QUALIFICATION.json",q);return q
def node_id(kind,p,cut,cap):return f"{kind}|{p}|{cut}|{cap}"
def allowed_nodes():
 return ({node_id("scaler","SHARED",cut,"WEIGHTED") for cut in CUTS}
  | {node_id("estimator",p,cut,cap) for cut in CUTS[:-1] for p in PARADIGMS for cap in CAPACITIES}
  | {node_id("estimator",p,CUTS[-1],cap) for p in PARADIGMS for cap in CAPACITIES}
  | {node_id("estimator","RIDGE",f"{y}-01-01","LOW") for y in YEARS})
def ledger_checked(run,ledger):
 if ledger["design_freeze_sha256"]!=sha(run/"DESIGN_FREEZE.json"):raise ValueError("LEDGER_FREEZE_CHANGED")
 seen=set();entered=completed=0;counts={"estimator":0,"scaler":0}
 for e in ledger["events"]:
  ident=e["physical_id"];kind=e["kind"]
  if ident in seen or e["attempt"]!=1 or kind not in counts or e["status"] not in ("RESERVED","TRAINED","FAILED"):raise ValueError("PHYSICAL_NODE_OR_RETRY_CHANGED")
  if ident not in allowed_nodes() or ident!=node_id(kind,e["paradigm"],e["cutoff"],e["capacity"]):raise ValueError("UNPLANNED_PHYSICAL_NODE")
  seen.add(ident);counts[kind]+=1
  if e["cutoff"] not in CUTS or (kind=="scaler" and (e["paradigm"]!="SHARED" or e["capacity"]!="WEIGHTED")):raise ValueError("SCALER_CUTOFF_CHANGED")
  if kind=="estimator":
   if e["paradigm"] not in (*PARADIGMS,"RIDGE") or e["capacity"] not in CAPACITIES:raise ValueError("ESTIMATOR_IDENTITY_CHANGED")
   if e["paradigm"]=="RIDGE" and (e["capacity"]!="LOW" or e["cutoff"] not in [f"{y}-01-01" for y in YEARS]):raise ValueError("RIDGE_SANITY_CHANGED")
  if type(e["entered"]) is not int or type(e["completed"]) is not int or not 0<=e["completed"]<=e["entered"]<=1:raise ValueError("FIT_TELEMETRY_CHANGED")
  if e["status"]=="TRAINED" and (e["entered"]!=1 or e["completed"]!=1):raise ValueError("SUCCESS_CALL_MISSING")
  entered+=e["entered"];completed+=e["completed"]
 conditional=[e for e in ledger["events"] if e["kind"]=="estimator" and e["cutoff"]==CUTS[-1] and e["capacity"]!="LOW"]
 if len({e["paradigm"] for e in conditional})!=len(conditional):raise ValueError("ONLY_ONE_SELECTED_2025_CAPACITY")
 if (counts["estimator"]>103 or counts["scaler"]>7 or len(seen)>110 or ledger["charged_backend_ceiling"]!=len(seen)
     or ledger["actual_backend_entered"]!=entered or ledger["backend_completed"]!=completed or ledger["scientific_retries"]!=0):raise ValueError("BUDGET_OR_COUNTER_CHANGED")
 return ledger
def reserve(run,L,kind,p,cut,cap):
 ident=node_id(kind,p,cut,cap)
 if any(e["physical_id"]==ident for e in L["events"]):raise ValueError("NO_DUPLICATE_ATTEMPT")
 e=dict(physical_id=ident,kind=kind,paradigm=p,cutoff=cut,capacity=cap,attempt=1,status="RESERVED",entered=0,completed=0,started_at=now())
 L["events"].append(e);L["charged_backend_ceiling"]+=1;ledger_checked(run,L);putj(run/"FIT_LEDGER.json",L);return e
def entered(run,L,e):
 if e["entered"]!=0:raise ValueError("SECOND_BACKEND_CALL_FORBIDDEN")
 e["entered"]=1;L["actual_backend_entered"]+=1;putj(run/"FIT_LEDGER.json",L)
def completed(run,L,e):
 e["completed"]=1;L["backend_completed"]+=1;putj(run/"FIT_LEDGER.json",L)
def artifact(run,L,kind,p,cut,cap):
 e=next((e for e in L["events"] if e["physical_id"]==node_id(kind,p,cut,cap)),None)
 if not e:return None
 if e["status"]=="RESERVED":raise ValueError("UNFINISHED_ATTEMPT_NO_SCIENTIFIC_RETRY")
 if e["status"]=="FAILED":return False
 rec=readj(e["receipt_path"])
 if (rec["design_freeze_sha256"]!=sha(run/"DESIGN_FREEZE.json") or sha(rec["artifact"]["path"])!=rec["artifact"]["sha256"]
     or rec.get("cutoff")!=cut):raise ValueError("PERSISTED_MODEL_CHANGED")
 if kind=="estimator" and (rec.get("physical_id")!=e["physical_id"] or rec.get("paradigm")!=p or rec.get("capacity")!=cap):raise ValueError("PERSISTED_FIT_IDENTITY_CHANGED")
 return rec
def utility(scores,frame):
 if len(scores)!=len(frame) or not np.isfinite(scores).all() or not np.isfinite(frame.target.to_numpy(float)).all():raise ValueError("INNER_FINITE_FULL_U_SCORE_REQUIRED")
 temp=frame[["signal_date","security_uid","ticker","target"]].copy();temp["score"]=scores
 top=temp.sort_values(["signal_date","score","security_uid","ticker"],ascending=[True,False,True,True],kind="stable").groupby("signal_date",sort=False).head(20)
 daily=top.groupby("signal_date",sort=True).target.mean()
 if not top.groupby("signal_date").size().eq(20).all():raise ValueError("INNER_TOP20_REQUIRED")
 return daily
def choose_capacity(records,year,paradigm):
 eligible=[]
 for cap in CAPACITIES:
  rows=[records.get(f"{paradigm}|{start}|{cap}") for start,_ in folds(year)]
  if any(not row or row["status"]!="COMPLETE" for row in rows):continue
  for row,(start,end) in zip(rows,folds(year)):
   if (row.get("fit_cutoff")!=start or row.get("validation_end")!=end
       or pd.isna(pd.Timestamp(row["max_label_end"])) or pd.Timestamp(row["max_label_end"])>=pd.Timestamp(end)
       or row["dates"]<=0 or not np.isfinite(row["sum_daily_utility"])):raise ValueError("INNER_SELECTION_USED_FUTURE_OR_CHANGED_FOLD")
  n=sum(row["dates"] for row in rows);mean=sum(row["sum_daily_utility"] for row in rows)/n
  eligible.append((cap,float(mean),n))
 if not eligible:return None,eligible
 best=max(v for _,v,_ in eligible)
 choice=next(c for c,v,_ in eligible if v>=best-1e-12)
 return choice,eligible
def check_inner_record(row,run,q,start,end,fit_record,expected_dates):
 if (row.get("design_freeze_sha256")!=sha(run/"DESIGN_FREEZE.json") or row.get("validation_keys")!=q["keys"]
     or row.get("fit_cutoff")!=start or row.get("validation_end")!=end or row.get("max_label_end")!=q["max_label_end"]):
  raise ValueError("INNER_RECORD_LINEAGE_CHANGED")
 if row["status"]!="COMPLETE":
  if fit_record is not None:raise ValueError("INNER_FAILURE_DEPENDENCY_CHANGED")
  return
 if fit_record is None or row.get("fit")!=fit_record["artifact"] or row.get("physical_id")!=fit_record["physical_id"]:
  raise ValueError("INNER_FIT_DEPENDENCY_CHANGED")
 pin=row["daily"]
 if sha(pin["path"])!=pin["sha256"]:raise ValueError("INNER_DAILY_ARTIFACT_CHANGED")
 daily=pre2026(pin["path"],["signal_date","top20_mean_utility"],"signal_date")
 clock=pd.DatetimeIndex(daily.signal_date)
 if (clock.hasnans or clock.has_duplicates or not clock.equals(pd.DatetimeIndex(expected_dates))
     or (clock<pd.Timestamp(start)).any() or (clock>=pd.Timestamp(end)).any()
     or len(daily)!=q["dates"] or row["dates"]!=len(daily)
     or not np.isfinite(daily.top20_mean_utility).all()
     or not np.isclose(daily.top20_mean_utility.sum(),row["sum_daily_utility"],rtol=1e-12,atol=1e-12)
     or not np.isclose(daily.top20_mean_utility.mean(),row["mean_daily_utility"],rtol=1e-12,atol=1e-12)):
  raise ValueError("INNER_UTILITY_OR_CLOCK_CHANGED")

def bind_references(run,d):
 refs={}
 reuse=readj(d["native_reuse_manifest"]["path"])
 for cid in REFERENCES:
  pin=reuse["score_refs"][cid]
  if sha(pin["path"])!=pin["sha256"]:raise ValueError("LEGACY_REFERENCE_CHANGED")
  frame=pre2026(pin["path"],KEYS+["score","rank","candidate_id"],"signal_date");frame["candidate_id"]=cid
  out=run/f"predictions/scores_{cid}_pre2026.parquet";out.parent.mkdir(parents=True,exist_ok=True)
  if out.exists():
   if not pre2026(out,KEYS+["score","rank","candidate_id"],"signal_date").equals(frame):raise ValueError("REFERENCE_ALIAS_CHANGED")
  else:frame.to_parquet(out,index=False)
  refs[cid]=dict(path=str(out),sha256=sha(out),source=pin,new_fit_calls=0)
 return refs
def train(run):
 cfg,d=checked(run);rt=prior.runtime(run);old.guard_backend(rt,d);jb=rt[4]
 from sklearn.preprocessing import StandardScaler
 from threadpoolctl import threadpool_limits
 thread_guard=threadpool_limits(limits=2)
 if kernel.capacity_specs(rt)!=d["capacity_specs"]:raise ValueError("CAPACITY_CONFIGURATION_CHANGED")
 train,frame=old.read_inputs(run,rt,d);Q=readj(d["input_qualification"]["path"])
 path=run/"FIT_LEDGER.json"
 L=readj(path) if path.exists() else dict(design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),events=[],charged_backend_ceiling=0,actual_backend_entered=0,backend_completed=0,scientific_retries=0)
 ledger_checked(run,L);putj(path,L);bind_references(run,d)
 inner=readj(run/"INNER_FOLD_SCORES.json") if (run/"INNER_FOLD_SCORES.json").exists() else {}
 selections=readj(run/"NESTED_SELECTION.json") if (run/"NESTED_SELECTION.json").exists() else {}
 for cut in CUTS:
  checked(run);pool=full_pool(train,cut);q=Q["training"][cut]
  if key_digest(pool)!=q["key_digest"] or len(pool)!=q["rows"]:raise ValueError("FULL_TRAINING_KEYS_CHANGED")
  x=pool[d["features"]].to_numpy(float);y=pool.target.to_numpy(float);weights=row_weights(pool.signal_date)
  srec=artifact(run,L,"scaler","SHARED",cut,"WEIGHTED")
  if srec is None:
   e=reserve(run,L,"scaler","SHARED",cut,"WEIGHTED")
   try:
    entered(run,L,e);scaler=StandardScaler().fit(x,sample_weight=weights);completed(run,L,e)
    out=run/f"models/scalers/{cut}.joblib";out.parent.mkdir(parents=True,exist_ok=True);jb.dump(scaler,out,compress=3)
    srec=dict(status="TRAINED",design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),artifact=dict(path=str(out),sha256=sha(out)),keys=q["keys"],cutoff=cut,weights="N/(D*Nt)",rows=len(pool))
    putj(out.with_suffix(".json"),srec);e.update(status="TRAINED",receipt_path=str(out.with_suffix(".json")),completed_at=now())
   except Exception as exc:e.update(status="FAILED",error=str(exc),traceback=traceback.format_exc(),completed_at=now());srec=False
   putj(path,L);ledger_checked(run,L)
  elif srec:
   if srec.get("keys")!=q["keys"] or srec.get("rows")!=q["rows"]:raise ValueError("SCALER_TRAINING_IDENTITY_CHANGED")
   scaler=jb.load(srec["artifact"]["path"])
  if not srec:continue
  xs=scaler.transform(x);boundary=old.boundary_labels(pool)
  plan=kernel.cached_pair_plan(pool.signal_date) if hasattr(kernel,"cached_pair_plan") else old.objectives.pair_plan(pool.signal_date)
  def fit_one(p,cap):
   rec=artifact(run,L,"estimator",p,cut,cap)
   if rec is False:return None,None
   if rec:
    if (rec.get("keys")!=q["keys"] or rec.get("scaler")!=srec["artifact"]
        or rec.get("capacity_spec")!=d["capacity_specs"][p][cap]
        or rec.get("max_train_label_end")!=q["max_train_label_end"]):raise ValueError("ESTIMATOR_TRAINING_IDENTITY_CHANGED")
    return jb.load(rec["artifact"]["path"]),rec
   e=reserve(run,L,"estimator",p,cut,cap);emit(run,phase="TRAINING",status="RUNNING",cutoff=cut,paradigm=p,capacity=cap,backend_entered=L["actual_backend_entered"])
   start=time.monotonic()
   try:
    def on_fit_call(info):entered(run,L,e)
    fitted=kernel.fit(p,xs,y,pool.signal_date,boundary,cap,rt,pair_plan=plan if p=="PAIRWISE_MLP" else None,on_fit_call=on_fit_call)
    completed(run,L,e);old.guard_backend(rt,d,fitted.metadata)
    out=run/f"models/fits/{p}/{cut}_{cap}.joblib";out.parent.mkdir(parents=True,exist_ok=True);jb.dump(fitted,out,compress=3)
    rec=dict(status="TRAINED",physical_id=e["physical_id"],design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),
      artifact=dict(path=str(out),sha256=sha(out)),scaler=srec["artifact"],capacity_spec=d["capacity_specs"][p][cap],
      paradigm=p,capacity=cap,cutoff=cut,keys=q["keys"],max_train_signal=q["max_train_signal"],max_train_label_end=q["max_train_label_end"],
      rows=len(pool),dates=q["dates"],metadata=fitted.metadata,seconds=time.monotonic()-start)
    putj(out.with_suffix(".json"),rec);e.update(status="TRAINED",receipt_path=str(out.with_suffix(".json")),completed_at=now())
   except Exception as exc:
    e.update(status="FAILED",error=type(exc).__name__+":"+str(exc),traceback=traceback.format_exc(),completed_at=now());rec=None;fitted=None
    putj(run/f"models/failed_{p}_{cut}_{cap}.json",e)
   putj(path,L);ledger_checked(run,L);return fitted,rec
  models={}
  for p in PARADIGMS:
   for cap in CAPACITIES if cut in CUTS[:-1] else ("LOW",):
    models[(p,cap)]=fit_one(p,cap)
  if cut.endswith("-01-01") and int(cut[:4]) in YEARS:
   year=int(cut[:4]);va=frame.loc[frame.signal_date.dt.year.eq(year)].sort_values(["signal_date","security_uid","ticker"],kind="stable").reset_index(drop=True)
   vx=scaler.transform(va[d["features"]].to_numpy(float))
   for p in PARADIGMS:
    choice,metrics=choose_capacity(inner,year,p)
    selections[f"{p}:{year}"]=dict(outer_cutoff=cut,selected_capacity=choice,eligible_capacity_statistics=metrics,
     inner_keys=[f"{p}|{start}|{cap}" for start,_ in folds(year) for cap in CAPACITIES],
     outer_target="MEAN_ER_3D_5D_10D_20D",selection_rule="pooled equal-date Top20 mean utility; LOW MEDIUM HIGH tie tolerance1e-12")
    for state,cap in (("FULL_BALANCED_FIXED","LOW"),("FULL_BALANCED_NESTED",choice)):
     if cap is None:continue
     fitted,rec=models.get((p,cap),(None,None))
     if fitted is None and (p,cap) not in models:fitted,rec=fit_one(p,cap);models[(p,cap)]=(fitted,rec)
     if fitted is None:continue
     values=kernel.predict(fitted,vx);cid=f"C10_{p}_{state}";panel=va[KEYS].copy();panel["score"]=values;panel["candidate_id"]=cid;panel["source_kind"]="MODEL_OOF";panel["source_cutoff"]=pd.Timestamp(cut)
     out=run/f"predictions/native_{cid}_{year}.parquet";out.parent.mkdir(parents=True,exist_ok=True)
     if out.exists():
      if not pre2026(out,KEYS+["score","candidate_id","source_kind","source_cutoff"],("signal_date","source_cutoff")).equals(panel):raise ValueError("PREDICTION_CHANGED_ON_RESUME")
     else:panel.to_parquet(out,index=False)
     putj(out.with_suffix(".json"),dict(role=cid,year=year,prediction=dict(path=str(out),sha256=sha(out)),fit=rec["artifact"],physical_id=rec["physical_id"],
       selected_capacity=cap,selection_lineage=selections[f"{p}:{year}"] if state=="FULL_BALANCED_NESTED" else None,rows=len(panel),design_freeze_sha256=sha(run/"DESIGN_FREEZE.json")))
   fitted,rec=fit_one("RIDGE","LOW")
   if fitted is not None:
    cid="C10_RIDGE_FULL_BALANCED";panel=va[KEYS].copy();panel["score"]=kernel.predict(fitted,vx);panel["candidate_id"]=cid;panel["source_kind"]="MODEL_OOF";panel["source_cutoff"]=pd.Timestamp(cut)
    out=run/f"predictions/native_{cid}_{year}.parquet"
    if not out.exists():panel.to_parquet(out,index=False)
    elif not pre2026(out,KEYS+["score","candidate_id","source_kind","source_cutoff"],("signal_date","source_cutoff")).equals(panel):raise ValueError("RIDGE_PREDICTION_CHANGED")
    putj(out.with_suffix(".json"),dict(role=cid,year=year,prediction=dict(path=str(out),sha256=sha(out)),fit=rec["artifact"],physical_id=rec["physical_id"],selected_capacity="LOW",rows=len(panel),design_freeze_sha256=sha(run/"DESIGN_FREEZE.json")))
   putj(run/"NESTED_SELECTION.json",selections)
  if cut in CUTS[:-1]:
   end=f"{cut[:4]}-07-01" if cut.endswith("-01-01") else f"{int(cut[:4])+1}-01-01"
   part=inner_frame(frame,cut,end);vq=next(v for v in Q["validation"] if v["fit_cutoff"]==cut)
   if len(part)!=vq["rows"] or part.signal_date.nunique()!=vq["dates"]:raise ValueError("INNER_CLOCK_CHANGED")
   vx=scaler.transform(part[d["features"]].to_numpy(float))
   for p in PARADIGMS:
    for cap in CAPACITIES:
     ident=f"{p}|{cut}|{cap}";fitted,rec=models[(p,cap)]
     if ident in inner:
      check_inner_record(inner[ident],run,vq,cut,end,rec,sorted(part.signal_date.unique()));continue
     if fitted is None:
      inner[ident]=dict(status="FAILED_DEPENDENCY",fit_cutoff=cut,validation_end=end,max_label_end=vq["max_label_end"],design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),validation_keys=vq["keys"]);continue
     daily=utility(kernel.predict(fitted,vx),part);out=run/f"diagnostics/inner/{p}/{cut}_{cap}.parquet";out.parent.mkdir(parents=True,exist_ok=True)
     daily.rename("top20_mean_utility").rename_axis("signal_date").reset_index().to_parquet(out,index=False)
     inner[ident]=dict(status="COMPLETE",fit_cutoff=cut,validation_end=end,max_label_end=vq["max_label_end"],
      dates=len(daily),sum_daily_utility=float(daily.sum()),mean_daily_utility=float(daily.mean()),
      physical_id=rec["physical_id"],daily=dict(path=str(out),sha256=sha(out)),fit=rec["artifact"],
      design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),validation_keys=vq["keys"])
   putj(run/"INNER_FOLD_SCORES.json",inner)
 putj(run/"TRAINING_COMPLETE.json",dict(status="FINITE_ATTEMPTS_COMPLETE",charged_backend_ceiling=L["charged_backend_ceiling"],
 actual_backend_entered=L["actual_backend_entered"],backend_completed=L["backend_completed"],failed_physical_nodes=sum(e["status"]=="FAILED" for e in L["events"]),
 estimator_attempts=sum(e["kind"]=="estimator" for e in L["events"]),scaler_attempts=sum(e["kind"]=="scaler" for e in L["events"]),scientific_retries=0,legacy_reused_model_year=18))
 emit(run,phase="TRAINING",status="COMPLETE")
def assemble(run):
 cfg,d=checked(run);ledger_checked(run,readj(run/"FIT_LEDGER.json"));rawpin=d["score_reuse"][evidence.RAW]
 if sha(rawpin["path"])!=rawpin["sha256"]:raise ValueError("RAW_SCORE_CHANGED")
 raw=pre2026(rawpin["path"],KEYS,"signal_date").sort_values(["signal_date","security_uid","ticker"]).reset_index(drop=True)
 bindings={evidence.RAW:rawpin,**bind_references(run,d)};complete=[];failed={}
 for cid in NEW_ROLES:
  pieces=[]
  for year in YEARS:
   p=run/f"predictions/native_{cid}_{year}.parquet";recp=p.with_suffix(".json")
   if not p.exists() or not recp.exists():break
   rec=readj(recp)
   if rec["design_freeze_sha256"]!=sha(run/"DESIGN_FREEZE.json") or rec["prediction"]["sha256"]!=sha(p) or rec["fit"]["sha256"]!=sha(rec["fit"]["path"]):raise ValueError("ANNUAL_PREDICTION_OR_MODEL_CHANGED")
   pieces.append(pre2026(p,KEYS+["score","candidate_id","source_kind","source_cutoff"],("signal_date","source_cutoff")))
  if len(pieces)!=3:failed[cid]="MISSING_COMPLETE_THREE_YEAR_OOF";continue
  panel=pd.concat(pieces,ignore_index=True).sort_values(["signal_date","security_uid","ticker"]).reset_index(drop=True)
  if not panel[KEYS].equals(raw) or not np.isfinite(panel.score).all():raise ValueError("FULL_U_PRESERVATION_REQUIRED:"+cid)
  panel=prior.rank_panel(panel,pd);out=run/f"predictions/scores_{cid}_pre2026.parquet"
  if out.exists():
   if not pd.read_parquet(out).equals(panel):raise ValueError("ASSEMBLED_PANEL_CHANGED")
  else:panel.to_parquet(out,index=False)
  bindings[cid]=dict(path=str(out),sha256=sha(out));complete.append(cid)
 A=dict(status="COMPLETE",design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),complete_candidates=complete,
 complete_fixed_references=list(REFERENCES),failed_or_untestable=failed,score_paths=bindings,common_rows=len(raw),common_dates=raw.signal_date.nunique(),forecast2026_rows=0)
 putj(run/"SCORE_ASSEMBLY.json",A)
 files=[REPO/"scripts/research/a2/evaluation"/x for x in ("selector_sufficiency_evidence.py","selector_evidence.py","selector_algorithm_breadth_evidence.py","selector_horizon_evidence.py","selector_account_compare.py")]
 putj(run/"EVALUATION_CODE_ACTIVATION.json",dict(status="PASS",design_freeze_sha256=sha(run/"DESIGN_FREEZE.json"),score_assembly_sha256=sha(run/"SCORE_ASSEMBLY.json"),sources={str(p):sha(p) for p in files}))
 emit(run,phase="ASSEMBLY",status="COMPLETE",complete_roles=len(complete),failed_roles=len(failed))
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--run",type=Path,required=True);parser.add_argument("--phase",choices=("train","assemble","all"),default="all");a=parser.parse_args()
 try:
  if a.phase in ("train","all"):train(a.run)
  if a.phase in ("assemble","all"):assemble(a.run)
  if a.phase=="all":
   from scripts.research.a2.evaluation.selector_sufficiency_evidence import run as evaluate
   evaluate(a.run);emit(a.run,phase="EVIDENCE",status="COMPLETE_REPORT_PENDING")
 except Exception as exc:
  emit(a.run,phase="ENGINEERING",status="FAILED",error=type(exc).__name__+":"+str(exc),traceback=traceback.format_exc());raise
if __name__=="__main__":main()
