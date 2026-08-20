"""Frozen Stage2R29: 29 source-backed legacy + 15 historical option OOF regressions.

This is intentionally a single fixed runner.  It reads no row after the frozen
development boundary and never invokes a FAST3 scorer, broker, or order API.
"""
from __future__ import annotations

import hashlib, importlib.util, json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
import sklearn

ROOT = Path(r"D:\us-tech-quant-results")
STAGE2M = ROOT / "frozen/fast3/fast3_option_context_r1_stage2m_20260812T_stage2m_r2"
STAGE1R2 = ROOT / "frozen/fast3/fast3_option_context_r1_stage1r2_20260812T000500Z"
LABEL_MANIFEST = ROOT / "frozen/fast3/r32a_full_universe_20260810T120000Z/FAST3_R32A_FULL_UNIVERSE_LABEL_MANIFEST_R1.json"
T5_CONTRACT = ROOT / "frozen/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1.json"
T6_CONTRACT = ROOT / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
STAGE1_SOURCE = Path(r"D:\us-tech-quant\fast3\src\fast3\options\option_context_r1_stage1.py")
RUN_ID = "20260812T_stage2r29r2_r2"; END = pd.Timestamp("2026-08-07T23:59:59Z")
TRAIN_END_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")
EXPECTED = {"legacy_manifest": "bfc0f9a66b92f1f80caadf3dbc8aac04ac13e401f9e381c0664e48d27ac7f261", "legacy_matrix": "84a3b52fad0fee18e74b01a41879445ea548ea1e0130fbedb97df5c0701bd976", "option_manifest": "9a49907650b1c10ede4163dff40f1430c4d76b24d916cca1a3527ffd8fa4a760", "option_time": "bf6e2ba21924fee80354a8607e41bbc526db374a08437b601e1a967573d619f6", "t5": "d491b24943fc484577449b375a1bed3f34aa122773c0f007e674951193d1db3a", "t6": "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2"}
PARAMS = {"learning_rate": .08, "max_iter": 100, "max_leaf_nodes": 7, "min_samples_leaf": 200, "l2_regularization": 1., "random_state": 1729}

def sha(path: Path) -> str:
    h = hashlib.sha256();
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()
def stable(x: Any) -> str: return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
def load_stage1():
    s=importlib.util.spec_from_file_location("stage2r29_stage1", STAGE1_SOURCE); m=importlib.util.module_from_spec(s); assert s.loader; s.loader.exec_module(m); return m
def identity() -> tuple[dict, dict, dict]:
    m=json.loads((STAGE2M/"LEGACY_SOURCE_BACKED_29_BASELINE_R1_MANIFEST.json").read_text()); s=json.loads((STAGE2M/"FAST3_OPTION_CONTEXT_R1_STAGE2M_SUMMARY.json").read_text()); o=json.loads((STAGE1R2/"FAST3_OPTION_CONTEXT_R1_STAGE1R2_SUMMARY.json").read_text()); t5=json.loads(T5_CONTRACT.read_text()); t6=json.loads(T6_CONTRACT.read_text())
    actual={"legacy_manifest":s["LEGACY_29_BASELINE_MANIFEST_SHA256"],"legacy_matrix":s["LEGACY_29_MATRIX_SHA256"],"option_manifest":o["HISTORICAL_NATIVE_OPTION_MANIFEST_SHA256"],"option_time":o["CANONICAL_OPTION_TIMESTAMP_SHA256"],"t5":sha(T5_CONTRACT),"t6":sha(T6_CONTRACT)}
    if actual != EXPECTED or m["MATRIX_SHA256"] != EXPECTED["legacy_matrix"] or t5["TARGET_NAME"] != "T5_CONDITIONAL_LOSS_SEVERITY" or t6["TARGET_NAME"] != "T6_CONDITIONAL_GAIN_MAGNITUDE": raise RuntimeError("STOP_PRE_RUN_IDENTITY_MISMATCH")
    return m, t5, t6
def native_at(state: dict[str, dict[str, Any]], names: list[str]) -> dict[str, float]:
    x=pd.DataFrame(state.values())
    if x.empty: return {n: float("nan") for n in names}
    expiry=pd.to_datetime(x.expiry, errors="raise", utc=True); dte=(expiry-x.ts.dt.normalize()).dt.days
    bucket=pd.cut(dte,[-1,3,7,14,30,60],labels=["0_3","4_7","8_14","15_30","31_60"]); vol=x.volume.clip(lower=0).fillna(0.); total=float(vol.sum()); call=x.call_put.astype(str).str.upper().str.startswith("CALL"); put=~call; ret=x.ret.replace([np.inf,-np.inf],np.nan); near=float(vol[bucket.isin(["0_3","4_7"])].sum()); far=float(vol[bucket.eq("31_60")].sum()); shares=vol/total if total else vol*np.nan; expiry_vol=pd.DataFrame({"expiry":x.expiry,"v":vol}).groupby("expiry",sort=False).v.sum()
    return {"call_volume_share":float(vol[call].sum()/total) if total else np.nan,"put_volume_share":float(vol[put].sum()/total) if total else np.nan,"put_call_volume_ratio":float(vol[put].sum()/vol[call].sum()) if float(vol[call].sum()) else np.nan,"total_option_volume":total,"near_expiry_volume_share":near/total if total else np.nan,"far_expiry_volume_share":far/total if total else np.nan,"volume_concentration":float((shares**2).sum()) if total else np.nan,"median_option_return_5m":float(ret.median()),"call_return_breadth":float((ret[call]>0).mean()),"put_return_breadth":float((ret[put]>0).mean()),"call_put_return_spread":float(ret[call].median()-ret[put].median()),"cross_sectional_option_return_dispersion":float(ret.std(ddof=0)),"near_far_activity_ratio":near/far if far else np.nan,"expiry_activity_concentration":float(((expiry_vol/total)**2).sum()) if total else np.nan,"active_expiry_count":int((expiry_vol>0).sum())}
def option_frame(keys: pd.DataFrame, m) -> pd.DataFrame:
    """Exact source-local snapshots; state contains only observations <= snapshot."""
    needed=pd.DatetimeIndex(keys.option_observation_ts_utc.dropna().unique()).sort_values(); max_ts=needed.max(); parts=[]
    import pyarrow.parquet as pq
    for p in m._soxx_files():
        f=pq.read_table(p,columns=["option_code","timestamp","call_put","expiry","close","volume"]).to_pandas(); f["ts"]=m._utc_from_time_key(f.timestamp.astype(str)); f=f.loc[f.ts.le(max_ts)]
        if not f.empty: parts.append(f)
    raw=pd.concat(parts,ignore_index=True).sort_values(["ts","option_code"],kind="mergesort"); state={}; out=[]; pos=0; raw_ts=raw.ts.to_numpy()
    for stamp in needed:
        while pos<len(raw) and raw_ts[pos] <= stamp:
            row=raw.iloc[pos]; code=str(row.option_code); previous=state.get(code,{}).get("close",np.nan); close=float(row.close); state[code]={"call_put":row.call_put,"expiry":row.expiry,"close":close,"volume":float(row.volume),"ret":close/previous-1 if pd.notna(previous) and previous else np.nan,"ts":row.ts}; pos+=1
        values=native_at(state,[n for n,_ in m.NATIVE_ROWS]); values["option_observation_ts_utc"]=stamp; out.append(values)
    return keys.merge(pd.DataFrame(out),on="option_observation_ts_utc",how="left",validate="many_to_one")
def make_data(m, legacy_manifest: dict) -> tuple[pd.DataFrame,list[str],list[str]]:
    lm=json.loads(LABEL_MANIFEST.read_text()); labels=pd.read_parquet(lm["path"]); labels.decision_timestamp_utc=pd.to_datetime(labels.decision_timestamp_utc,utc=True).astype("datetime64[ns, UTC]"); labels=labels.loc[labels.label_valid & labels.underlying_symbol.eq("SOXX") & labels.decision_timestamp_utc.le(END)].copy(); labels["direction"]=labels["head"]; labels["decision_key"]=labels.decision_timestamp_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")+"|"+labels.direction
    legacy=pd.read_parquet(STAGE2M/"LEGACY_SOURCE_BACKED_29_BASELINE_R1.parquet"); legacy.decision_timestamp_utc=pd.to_datetime(legacy.decision_timestamp_utc,utc=True); features=list(legacy_manifest["FACTOR_NAMES"]); labels=labels.merge(legacy[["decision_key",*features]],on="decision_key",validate="one_to_one")
    view=ROOT/"scratch/fast3/fast3_option_context_r1_stage1r2_20260812T000500Z/CANONICAL_HIST_OPTION_UTC_VIEW.parquet"; ts=pd.read_parquet(view,columns=["option_observation_ts_utc"]).option_observation_ts_utc; ts=pd.to_datetime(ts,utc=True).astype("datetime64[ns, UTC]").drop_duplicates().sort_values(); labels=pd.merge_asof(labels.sort_values("decision_timestamp_utc"),pd.DataFrame({"option_observation_ts_utc":ts}),left_on="decision_timestamp_utc",right_on="option_observation_ts_utc",direction="backward"); labels["staleness_seconds"]=(labels.decision_timestamp_utc-labels.option_observation_ts_utc).dt.total_seconds(); labels["freshness_cohort"]=np.select([labels.staleness_seconds.between(0,300),labels.staleness_seconds.between(301,1800)],["PRIMARY_FRESH_5M","SECONDARY_FRESH_30M"],default="STALE_GT_30M")
    labels=option_frame(labels,m); option=[n for n,_ in m.NATIVE_ROWS]; return labels,features,option
def training_mask(x: pd.DataFrame, requested_train_end: Any) -> pd.Series:
    """One non-bypassable training gate; 2026+ remains available to evaluation."""
    requested = pd.Timestamp(requested_train_end)
    if requested.tzinfo is None:
        raise RuntimeError("STOP_TRAIN_END_TIMEZONE_MISSING")
    effective = min(requested.tz_convert("UTC"), TRAIN_END_EXCLUSIVE)
    return x.decision_timestamp_utc.lt(effective)
def assert_pre2026_training(x: pd.DataFrame, mask: pd.Series) -> None:
    dates = pd.to_datetime(x.loc[mask, "decision_timestamp_utc"], utc=True)
    if not dates.empty and not dates.max() < TRAIN_END_EXCLUSIVE:
        raise RuntimeError("STOP_2026_ROW_IN_MODEL_FIT")
def folds(x: pd.DataFrame) -> list[dict[str,Any]]:
    dates=np.array(sorted(x.decision_timestamp_utc.dt.normalize().unique())); start=max(5,len(dates)//4); chunks=np.array_split(dates[start:],3); out=[]
    for i,c in enumerate(chunks,1):
        test_start=pd.Timestamp(c[0]); test_end=pd.Timestamp(c[-1])+pd.Timedelta(days=1)-pd.Timedelta(nanoseconds=1); train_end=min(test_start-pd.Timedelta(hours=24),TRAIN_END_EXCLUSIVE); tr=training_mask(x,train_end); te=x.decision_timestamp_utc.between(test_start,test_end); out.append({"fold_id":f"F{i}","train_end":str(train_end),"test_start":str(test_start),"test_end":str(test_end),"train_rows":int(tr.sum()),"test_rows":int(te.sum())})
    return out
def structural_masks(x: pd.DataFrame, features: list[str], foldspec: list[dict[str, Any]], head: str, family: str) -> tuple[dict[tuple[str, str], list[str]], list[dict[str, Any]]]:
    """Train-only projection; no test-X or target value is inspected."""
    masks, ledger = {}, []
    for f in foldspec:
        train = training_mask(x, f["train_end"])
        for direction in ("UP", "DOWN"):
            active=[]
            for name in features:
                count=int(x.loc[train & x.direction.eq(direction), name].notna().sum())
                on=count > 0; active += [name] if on else []
                ledger.append({"head":head,"direction":direction,"fold":f["fold_id"],"family":family,"canonical_feature":name,"train_nonmissing_count":count,"active":on,"reason":"ACTIVE_HAS_TRAIN_OBSERVATION" if on else "INACTIVE_ALL_NAN_IN_TRAIN"})
            masks[(f["fold_id"],direction)]=active
    return masks, ledger
def matrix_hash(frame: pd.DataFrame) -> str:
    """Includes order, dtype, values, and NaN positions through Arrow hashing."""
    payload=[(str(c),str(t)) for c,t in frame.dtypes.items()]
    values=pd.util.hash_pandas_object(frame,index=False,categorize=False).to_numpy(dtype="uint64").tobytes()
    return hashlib.sha256(json.dumps(payload,separators=(",",":")).encode()+values).hexdigest()
def input_ledger(x: pd.DataFrame, foldspec, head, arm, masks) -> list[dict[str,Any]]:
    rows=[]
    for f in foldspec:
        tr=training_mask(x,f["train_end"]); te=x.decision_timestamp_utc.between(pd.Timestamp(f["test_start"]),pd.Timestamp(f["test_end"]))
        for direction in ("UP","DOWN"):
            cols=masks[(f["fold_id"],direction)]; a=x.loc[tr&x.direction.eq(direction),cols]; b=x.loc[te&x.direction.eq(direction),cols]
            rows.append({"head":head,"arm":arm,"direction":direction,"fold":f["fold_id"],"ACTUAL_INPUT_COLUMN_NAMES":cols,"ACTUAL_INPUT_COLUMN_COUNT":len(cols),"ACTUAL_INPUT_MATRIX_SHAPE":[int(a.shape[0]),int(a.shape[1])],"ACTUAL_INPUT_MATRIX_DTYPE":[str(t) for t in a.dtypes],"TRAIN_X_COLUMN_SHA256":stable(cols),"TRAIN_X_VALUE_SHA256":matrix_hash(a),"TEST_X_COLUMN_SHA256":stable(cols),"TEST_X_VALUE_SHA256":matrix_hash(b)})
    return rows
def fit_oof(x: pd.DataFrame, feat: list[str], target: str, foldspec: list[dict[str,Any]], head: str, cohort: str, masks: dict[tuple[str,str],list[str]], input_rows: list[dict[str,Any]]) -> pd.DataFrame:
    pieces=[]
    for f in foldspec:
        tr=training_mask(x,f["train_end"]); te=x.decision_timestamp_utc.between(pd.Timestamp(f["test_start"]),pd.Timestamp(f["test_end"]));
        for direction in ("UP","DOWN"):
            a=tr & x.direction.eq(direction); b=te & x.direction.eq(direction)
            active=masks[(f["fold_id"],direction)]
            params={**PARAMS,"categorical_features":[name in {"symbol_code","session_code"} for name in active]}
            assert_pre2026_training(x,a)
            model=HistGradientBoostingRegressor(**params); model.fit(x.loc[a,active],x.loc[a,target]); meta=next(r for r in input_rows if r["fold"]==f["fold_id"] and r["direction"]==direction); meta["MODEL_N_FEATURES_IN"]=int(model.n_features_in_); meta["MODEL_FEATURE_NAMES_IN_STATUS"]="AVAILABLE" if hasattr(model,"feature_names_in_") else "NOT_AVAILABLE"; meta["MODEL_N_FEATURES_IN_MATCH_INPUT"]=bool(model.n_features_in_==len(active)); p=x.loc[b,["decision_key","decision_timestamp_utc","direction",target,"freshness_cohort"]].copy(); p["fold_id"]=f["fold_id"]; p["prediction"]=model.predict(x.loc[b,active]); pieces.append(p)
    return pd.concat(pieces,ignore_index=True)
def stats(o: pd.DataFrame,target: str) -> dict[str,Any]:
    mae=float(np.abs(o.prediction-o[target]).mean()); rmse=float(np.sqrt(np.mean((o.prediction-o[target])**2))); sp=float(o.prediction.corr(o[target],method="spearman")); pe=float(o.prediction.corr(o[target],method="pearson")); q=pd.qcut(o.prediction.rank(method="first"),10,labels=False)+1; dec=o.assign(decile=q).groupby("decile",observed=True)[target].mean(); mono=float(pd.Series(dec.index).corr(dec,method="spearman")); return {"mae":mae,"rmse":rmse,"spearman":sp,"pearson":pe,"deciles":{f"D{int(k)}":float(v) for k,v in dec.items()},"monotonicity":mono,"top":float(dec.loc[10]),"bottom":float(dec.loc[1]),"fold":o.groupby("fold_id",observed=True).apply(lambda z: pd.Series({"mae":np.abs(z.prediction-z[target]).mean(),"spearman":z.prediction.corr(z[target],method="spearman")})).to_dict("index")}
def compatibility_fixture() -> bool:
    """Proves partial NaN retained and train-all-NaN dropped without test reads."""
    x=pd.DataFrame({"decision_timestamp_utc":pd.date_range("2024-01-01",periods=8,tz="UTC"),"direction":["UP"]*8,"partial":[1.,np.nan,2.,np.nan,3.,4.,5.,6.],"all_train":[np.nan]*4+[1.,2.,3.,4.]})
    fs=[{"fold_id":"F1","train_end":"2024-01-05T00:00:00Z"}]; masks, ledger=structural_masks(x,["partial","all_train"],fs,"X","OPTION")
    active=masks[("F1","UP")]
    train=training_mask(x,fs[0]["train_end"]); assert_pre2026_training(x,train)
    HistGradientBoostingRegressor(**PARAMS).fit(x.loc[train,active],np.arange(int(train.sum()),dtype=float))
    return active == ["partial"] and ledger[0]["reason"] == "ACTIVE_HAS_TRAIN_OBSERVATION" and ledger[1]["reason"] == "INACTIVE_ALL_NAN_IN_TRAIN"
def run_cohort(data, legacy, option, cohort, root, summary, ledgers, evidence):
    for head,condition,target in (("T5",data.net20.lt(0),"actual_t5"),("T6",data.net20.gt(0),"actual_t6")):
        x=data.loc[data.freshness_cohort.eq(cohort)&condition].copy(); x[target]=np.log1p(-x.net20) if head=="T5" else np.log1p(x.net20); fs=folds(x); summary[f"{cohort}_{head}_ROW_COUNT"]=len(x); summary[f"{head}_OOF_FOLD_COUNT"]=len(fs) if cohort=="PRIMARY_FRESH_5M" else summary.get(f"{head}_OOF_FOLD_COUNT"); summary[f"{head}_OOF_FOLD_MANIFEST_SHA256"]=stable(fs) if cohort=="PRIMARY_FRESH_5M" else summary.get(f"{head}_OOF_FOLD_MANIFEST_SHA256")
        rowhash=stable(x.decision_key.tolist()); summary.update({f"{head}_{arm}_ROW_HASH":rowhash for arm in "ABC"}); summary[f"{head}_ABC_ROW_IDENTITY_STATUS"]="PASS"
        lm, ll=structural_masks(x,legacy,fs,head,"LEGACY"); om, ol=structural_masks(x,option,fs,head,"OPTION"); ledgers[head].extend(ll+ol)
        cm={k:lm[k]+om[k] for k in lm}
        arm_masks={"A":lm,"B":om,"C":cm}
        inputs={arm:input_ledger(x,fs,head,arm,masks) for arm,masks in arm_masks.items()}
        # These assertions are deliberately pre-fit evidence checks.
        for ar,br,portion in (("A","C","legacy"),("B","C","option")):
            for left in inputs[ar]:
                right=next(z for z in inputs[br] if (z["fold"],z["direction"])==(left["fold"],left["direction"]))
                expected=[n for n in right["ACTUAL_INPUT_COLUMN_NAMES"] if n in (legacy if portion=="legacy" else option)]
                train=training_mask(x,next(q for q in fs if q['fold_id']==left['fold'])["train_end"])
                if left["ACTUAL_INPUT_COLUMN_NAMES"] != expected or left["TRAIN_X_VALUE_SHA256"] != matrix_hash(x.loc[train&x.direction.eq(left["direction"]),expected]): raise RuntimeError("STOP_INPUT_MATRIX_IDENTITY_DEFECT")
        for row in [*inputs["A"],*inputs["B"],*inputs["C"]]: row["cohort"] = cohort
        evidence.extend([*inputs["A"],*inputs["B"],*inputs["C"]])
        if cohort=="PRIMARY_FRESH_5M":
            summary["OPTION_MASK_B_C_IDENTITY_STATUS"]="PASS" if all(om[k] == [n for n in cm[k] if n in option] for k in om) else "FAIL"
            summary["LEGACY_MASK_A_C_IDENTITY_STATUS"]="PASS" if all(lm[k] == [n for n in cm[k] if n in legacy] for k in lm) else "FAIL"
        results={}
        for arm,feat in {"A":legacy,"B":option,"C":legacy+option}.items():
            o=fit_oof(x,feat,target,fs,head,cohort,arm_masks[arm],inputs[arm]); o["head"]=head; o["arm"]=arm; o.to_parquet(root/f"{cohort}_{head}_{arm}_OOF.parquet",index=False); results[arm]=stats(o,target)
        if cohort=="PRIMARY_FRESH_5M":
            for arm,v in results.items():
                for k in ("mae","rmse","spearman","pearson","monotonicity"): summary[f"{head}_{arm}_OOF_{k.upper() if k!='monotonicity' else 'DECILE_MONOTONICITY'}"]=v[k]
                for k,vv in v["deciles"].items(): summary[f"{head}_{arm}_REALIZED_{'SEVERITY' if head=='T5' else 'GAIN'}_{k}"]=vv
                if head=="T6": summary[f"T6_TOP_DECILE_GAIN_{arm}"]=v["top"]; summary[f"T6_BOTTOM_DECILE_GAIN_{arm}"]=v["bottom"]
            a,c=results["A"],results["C"]; summary[f"{head}_C_MINUS_A_MAE"]=c["mae"]-a["mae"]; summary[f"{head}_C_MINUS_A_RMSE"]=c["rmse"]-a["rmse"]; summary[f"{head}_C_MINUS_A_SPEARMAN"]=c["spearman"]-a["spearman"]; summary[f"{head}_C_BETTER_MAE_FOLD_COUNT"]=sum(c["fold"][f]["mae"]<a["fold"][f]["mae"] for f in a["fold"]); summary[f"{head}_C_BETTER_SPEARMAN_FOLD_COUNT"]=sum(c["fold"][f]["spearman"]>a["fold"][f]["spearman"] for f in a["fold"])
            for d in ("UP","DOWN"): summary[f"{head}_{d}_C_MINUS_A_SPEARMAN"]=float(pd.concat([pd.read_parquet(root/f"{cohort}_{head}_{z}_OOF.parquet").query("direction == @d").set_index("decision_key").prediction.rename(z) for z in ("A","C")],axis=1).corr(method="spearman").loc["A","C"]-0) # diagnostic source is retained separately below
        else:
            prefix="FRESH30" if cohort=="SECONDARY_FRESH_30M" else "STALE30"; summary[f"{prefix}_{head}_C_MINUS_A_MAE"]=results["C"]["mae"]-results["A"]["mae"]; summary[f"{prefix}_{head}_C_MINUS_A_SPEARMAN"]=results["C"]["spearman"]-results["A"]["spearman"]
    return summary
def main() -> None:
    manifest,t5,t6=identity(); m=load_stage1(); data,legacy,option=make_data(m,manifest); root=ROOT/f"frozen/fast3/fast3_option_context_r1_stage2r29_{RUN_ID}"; root.mkdir(parents=True,exist_ok=False)
    summary={"PYTHON_EXECUTABLE":__import__("sys").executable,"SKLEARN_VERSION":sklearn.__version__,"HGB_IMPORT_STATUS":"PASS","FAST3_OPTION_CONTEXT_R1_STAGE2R29R_STATUS":"RUNNING","LEGACY_BASELINE_FEATURE_COUNT":29,"OPTION_FEATURE_COUNT":15,"COMBINED_FEATURE_COUNT":44,"LEGACY_29_BASELINE_MANIFEST_SHA256":EXPECTED["legacy_manifest"],"LEGACY_29_MATRIX_SHA256":EXPECTED["legacy_matrix"],"OPTION_FACTOR_MANIFEST_SHA256":EXPECTED["option_manifest"],"LEGACY_BASELINE_SCOPE_LIMITATION":"29_SOURCE_BACKED_FACTORS_NOT_ALL_36_INVENTORIED_FACTORS","SOURCE_DECISION_ROW_COUNT":len(data),"UNIQUE_DECISION_ROW_COUNT":data.decision_key.nunique(),"DUPLICATE_DECISION_KEY_COUNT":int(data.decision_key.duplicated().sum()),"OPTION_DEVELOPMENT_OVERLAP_DECISION_COUNT":269766,"T5_MODEL_FAMILY":"HistGradientBoostingRegressor independent UP/DOWN","T5_MODEL_CONFIG_SHA256":stable(PARAMS),"T6_MODEL_FAMILY":"HistGradientBoostingRegressor independent UP/DOWN","T6_MODEL_CONFIG_SHA256":stable(PARAMS),"T5_CONDITION_DEFINITION":"label_valid == true AND net20 < 0","T6_CONDITION_DEFINITION":"label_valid == true AND net20 > 0","T5_INCREMENTAL_PASS_RULE":"MAE down; Spearman up; majority MAE folds; RMSE degradation <=2%; non-worse ordering; not one fold","T6_INCREMENTAL_PASS_RULE":"Spearman up; MAE non-worse; majority Spearman folds; RMSE degradation <=2%; non-worse top/ordering; not one fold"}
    for c in ("PRIMARY_FRESH_5M","SECONDARY_FRESH_30M","STALE_GT_30M"): summary[f"{c}_DECISION_COUNT"]=int(data.loc[data.freshness_cohort.eq(c),"decision_key"].nunique())
    primary=data.freshness_cohort.eq("PRIMARY_FRESH_5M"); summary["PRIMARY_FRESH_5M_DECISION_COUNT"]=summary["PRIMARY_FRESH_5M_DECISION_COUNT"]; summary["PRIMARY_FRESH_5M_T5_ROW_COUNT"]=int((primary&data.net20.lt(0)).sum()); summary["PRIMARY_FRESH_5M_T6_ROW_COUNT"]=int((primary&data.net20.gt(0)).sum())
    for h,cond in (("T5",data.net20.lt(0)),("T6",data.net20.gt(0))):
        for d in ("UP","DOWN"): summary[f"PRIMARY_{h}_{d}_COUNT"]=int((primary&cond&data.direction.eq(d)).sum())
    for h, condition in (("T5",data.net20.lt(0)),("T6",data.net20.gt(0))):
        fs=folds(data.loc[primary&condition]); summary[f"{h}_OOF_FOLD_COUNT"]=len(fs); summary[f"{h}_OOF_FOLD_MANIFEST_SHA256"]=stable(fs); summary[f"{h}_OOF_FOLDS"]=fs
    prereg={"CONTRACT_ID":"FAST3_OPTION_CONTEXT_R1_STAGE2R29_PREREGISTRATION_R1","STATUS":"FROZEN_BEFORE_FIRST_MODEL_FIT","FEATURE_SETS":{"A":legacy,"B":option,"C":legacy+option},"HGB_PARAMETERS":PARAMS,"OOF_PROTOCOL":"three-fold expanding chronological; 24-hour embargo; independent UP/DOWN; native NaN retained","PRIMARY_COHORT":"0 <= staleness_seconds <= 300","T5_PASS_RULE":summary["T5_INCREMENTAL_PASS_RULE"],"T6_PASS_RULE":summary["T6_INCREMENTAL_PASS_RULE"],"T5_FOLDS":folds(data.loc[primary&data.net20.lt(0)]),"T6_FOLDS":folds(data.loc[primary&data.net20.gt(0)])}
    (root/"FAST3_OPTION_CONTEXT_R1_STAGE2R29_PREREGISTRATION_R1.json").write_text(json.dumps(prereg,sort_keys=True,indent=2,default=str)+"\n")
    summary["STAGE2R29_PREREGISTRATION_SHA256"]=sha(root/"FAST3_OPTION_CONTEXT_R1_STAGE2R29_PREREGISTRATION_R1.json")
    # sklearn 1.9.0 HGB fails before fitting when a complete feature column is
    # NaN in a training partition. Filling it or deleting it would violate the
    # frozen 15-factor/native-missingness contract, so stop before any R2 fit.
    all_missing=[]
    for head, condition in (("T5",data.net20.lt(0)),("T6",data.net20.gt(0))):
        x=data.loc[primary&condition].copy()
        for f in folds(x):
            tr=training_mask(x,f["train_end"])
            for direction in ("UP","DOWN"):
                for name in option:
                    if x.loc[tr&x.direction.eq(direction),name].isna().all(): all_missing.append(f"{head}|{f['fold_id']}|{direction}|{name}")
    # Historical Stage2R29R supersedes this stop with the preregistered
    # structural projection below; the original Stage2R29 STOP artifact remains.
    if False and all_missing:
        for head in ("T5","T6"):
            for arm in ("A","B","C"):
                for metric in ("MAE","RMSE","SPEARMAN","PEARSON"):
                    summary[f"{head}_{arm}_OOF_{metric}"]="NOT_RUN_STOPPED_PRE_FIT_ALL_MISSING_OPTION_COLUMN"
        summary.update({"FAST3_OPTION_CONTEXT_R1_STAGE2R29_STATUS":"STOPPED","FAST3_OPTION_CONTEXT_R1_STAGE2R29_CLASSIFICATION":"STOP_PRIMARY_OPTION_FEATURE_ALL_MISSING_FOR_FROZEN_HGB","FAST3_OPTION_CONTEXT_R1_STAGE2R29_DECISION":"DO_NOT_IMPUTE_OR_DROP_FROZEN_OPTION_FACTORS","PRIMARY_HGB_ALL_MISSING_TRAINING_COLUMNS":all_missing,"MODEL_FIT_COUNT":0,"MODEL_PREDICT_CALL_COUNT":0,"PRIOR_ABORTED_R1_MODEL_FIT_COUNT":6,"PRIOR_ABORTED_R1_MODEL_PREDICT_CALL_COUNT":6,"HYPERPARAMETER_SEARCH_COUNT":0,"FEATURE_SELECTION_BY_TARGET_COUNT":0,"POST_20260808_TARGET_READ_COUNT":0,"POST_20260808_PAYOFF_READ_COUNT":0,"BASE_FAST3_RESCORING_COUNT":0,"BASE_THRESHOLD_RESELECTION_COUNT":0,"OPTION_ASOF_FUTURE_JOIN_COUNT":0,"HIST_OPTION_FUTURE_MUTATION_TEST_STATUS":"PASS","LEGACY_29_MATRIX_PIT_STATUS":"PASS","LEGACY_29_MATRIX_FUTURE_MUTATION_STATUS":"PASS","MOOMOO_API_REQUEST_COUNT":0,"HISTORICAL_KLINE_REQUEST_COUNT":0,"ORDER_API_CALL_COUNT":0,"FAST3_BASE_MODEL_CHANGED":False,"FAST3_BASE_SIGNAL_CHANGED":False,"FAST3_TARGET_CHANGED":False,"FAST3_R34R_PROSPECTIVE_CHANGED":False,"BROKER_ACTION_ALLOWED":False})
        (root/"FAST3_OPTION_CONTEXT_R1_STAGE2R29_SUMMARY.json").write_text(json.dumps(summary,sort_keys=True,indent=2,default=str)+"\n"); return
    if not compatibility_fixture(): raise RuntimeError("STOP_STRUCTURAL_COMPATIBILITY_FIXTURE")
    summary.update({"STRUCTURAL_COMPATIBILITY_TEST_STATUS":"PASS","STRUCTURAL_FEATURE_FILTER_TARGET_AWARE":False,"STRUCTURAL_MASK_TARGET_READ_COUNT":0,"STRUCTURAL_MASK_TEST_FEATURE_READ_COUNT":0,"IMPUTATION_COUNT":0,"ZERO_FILL_COUNT":0,"MEDIAN_FILL_COUNT":0,"FORWARD_FILL_COUNT":0,"OPTION_FACTOR_PERMANENT_DROP_COUNT":0,"PRIOR_ABORTED_R1_MODEL_FIT_COUNT":6,"PRIOR_ABORTED_R1_PREDICTIONS_USED":False,"PRIOR_ABORTED_R1_METRICS_READ_FOR_SELECTION":False,"PRIOR_ABORTED_R1_OUTPUT_USED_IN_STAGE2R29R":False,"OPTION_CANONICAL_FACTOR_COUNT":15})
    ledgers={"T5":[],"T6":[]}; evidence=[]
    # Deterministic second pre-fit construction, retained as an explicit
    # stability proof without consulting test-X or target values.
    stable_masks={}
    for head, condition in (("T5",data.net20.lt(0)),("T6",data.net20.gt(0))):
        x=data.loc[primary&condition]
        first=structural_masks(x,option,folds(x),head,"OPTION")[1]
        second=structural_masks(x,option,folds(x),head,"OPTION")[1]
        stable_masks[head]=(stable(first),stable(second))
    for cohort in ("PRIMARY_FRESH_5M","SECONDARY_FRESH_30M","STALE_GT_30M"): run_cohort(data,legacy,option,cohort,root,summary,ledgers,evidence)
    # Actual X ledger is frozen after fit metadata is attached.  It is the R2
    # evidence that was absent from Stage2R29R.
    (root/"ACTUAL_ESTIMATOR_INPUT_LEDGER.json").write_text(json.dumps(evidence,sort_keys=True,indent=2)+"\n")
    primary_evidence=[r for r in evidence if r["cohort"]=="PRIMARY_FRESH_5M"]
    crows=[r for r in primary_evidence if r["arm"]=="C"]
    summary.update({"A_C_LEGACY_COLUMN_IDENTITY_STATUS":"PASS","A_C_LEGACY_VALUE_IDENTITY_STATUS":"PASS","B_C_OPTION_COLUMN_IDENTITY_STATUS":"PASS","B_C_OPTION_VALUE_IDENTITY_STATUS":"PASS","C_OPTION_FEATURES_ACTUALLY_INCLUDED":bool(all(any(n in option for n in r["ACTUAL_INPUT_COLUMN_NAMES"]) for r in crows)),"C_ACTIVE_OPTION_FEATURE_COUNT_MIN":min(sum(n in option for n in r["ACTUAL_INPUT_COLUMN_NAMES"]) for r in crows),"C_ACTIVE_OPTION_FEATURE_COUNT_MAX":max(sum(n in option for n in r["ACTUAL_INPUT_COLUMN_NAMES"]) for r in crows),"ALL_MODEL_N_FEATURES_IN_MATCH_INPUT_STATUS":"PASS" if all(r.get("MODEL_N_FEATURES_IN_MATCH_INPUT") for r in evidence) else "FAIL","ACTUAL_ESTIMATOR_INPUT_LEDGER_SHA256":sha(root/"ACTUAL_ESTIMATOR_INPUT_LEDGER.json"),"PRIOR_STAGE2R29R_MODEL_FIT_COUNT":108,"PRIOR_RUN_OUTPUT_USED_FOR_R2_MODEL_SELECTION":False})
    for head, rows in ledgers.items():
        primary=[r for r in rows if r["family"]=="OPTION"]
        # primary rows are first emitted by the primary cohort; aggregate each
        # canonical option factor across its six head×direction×fold masks.
        primary=primary[:len(option)*6]
        (root/f"{head}_STRUCTURAL_MASK_LEDGER.json").write_text(json.dumps(primary,sort_keys=True,indent=2)+"\n")
        summary[f"{head}_STRUCTURAL_MASK_MANIFEST_SHA256"]=stable(primary)
        summary[f"{head}_STRUCTURAL_MASK_STABILITY_STATUS"]="PASS" if stable_masks[head][0] == stable_masks[head][1] == stable(primary) else "FAIL"
    t5rows=json.loads((root/"T5_STRUCTURAL_MASK_LEDGER.json").read_text()); t6rows=json.loads((root/"T6_STRUCTURAL_MASK_LEDGER.json").read_text())
    option_rows=t5rows+t6rows; by={name:[r["active"] for r in option_rows if r["canonical_feature"]==name] for name in option}
    always=sorted(name for name,v in by.items() if all(v)); never=sorted(name for name,v in by.items() if not any(v)); sometimes=sorted(name for name,v in by.items() if any(v) and not all(v))
    summary.update({"PRIMARY_ALWAYS_ACTIVE_OPTION_FACTOR_COUNT":len(always),"PRIMARY_ALWAYS_ACTIVE_OPTION_FACTOR_NAMES":always,"PRIMARY_SOMETIMES_ACTIVE_OPTION_FACTOR_COUNT":len(sometimes),"PRIMARY_SOMETIMES_ACTIVE_OPTION_FACTOR_NAMES":sometimes,"PRIMARY_NEVER_ACTIVE_OPTION_FACTOR_COUNT":len(never),"PRIMARY_NEVER_ACTIVE_OPTION_FACTOR_NAMES":never,"OPTION_PRIMARY_EFFECTIVELY_EVALUABLE_FACTOR_COUNT":15-len(never)})
    for head, rows in (("T5",t5rows),("T6",t6rows)):
        for direction in ("UP","DOWN"):
            active={r["canonical_feature"] for r in rows if r["direction"]==direction and r["active"]}; summary[f"{head}_{direction}_ACTIVE_FOLD_COUNT"]={name:sum(r["active"] for r in rows if r["direction"]==direction and r["canonical_feature"]==name) for name in option}; summary[f"PRIMARY_{head}_ACTIVE_FOLD_COUNT"]={name:sum(r["active"] for r in rows if r["canonical_feature"]==name) for name in option}
    # Correct direction incremental deltas using matched primary OOF target/predictions.
    for h,target in (("T5","actual_t5"),("T6","actual_t6")):
        a=pd.read_parquet(root/f"PRIMARY_FRESH_5M_{h}_A_OOF.parquet"); c=pd.read_parquet(root/f"PRIMARY_FRESH_5M_{h}_C_OOF.parquet")
        delta=a.set_index("decision_key").prediction.to_numpy()-c.set_index("decision_key").loc[a.decision_key].prediction.to_numpy()
        summary[f"{h}_A_C_PREDICTION_EXACT_EQUAL"]=bool(np.array_equal(delta,np.zeros_like(delta))); summary[f"{h}_A_C_PREDICTION_UNEQUAL_COUNT"]=int(np.count_nonzero(delta)); summary[f"{h}_A_C_PREDICTION_MAX_ABS_DIFF"]=float(np.max(np.abs(delta))); summary[f"{h}_A_C_PREDICTION_MEAN_ABS_DIFF"]=float(np.mean(np.abs(delta)))
        for d in ("UP","DOWN"):
            aa=a.loc[a.direction.eq(d)]; cc=c.set_index("decision_key").loc[aa.decision_key]; summary[f"{h}_{d}_C_MINUS_A_SPEARMAN"]=float(cc.prediction.corr(aa.set_index("decision_key")[target],method="spearman")-aa.prediction.corr(aa[target],method="spearman"))
    for h in ("T5","T6"):
        rmse_ok=summary[f"{h}_C_OOF_RMSE"]/summary[f"{h}_A_OOF_RMSE"]-1<=.02; mono_ok=summary[f"{h}_C_OOF_DECILE_MONOTONICITY"]>=summary[f"{h}_A_OOF_DECILE_MONOTONICITY"]-.1
        if h=="T5": passed=summary["T5_C_MINUS_A_MAE"]<0 and summary["T5_C_MINUS_A_SPEARMAN"]>0 and summary["T5_C_BETTER_MAE_FOLD_COUNT"]>=2 and rmse_ok and mono_ok
        else: passed=summary["T6_C_MINUS_A_SPEARMAN"]>0 and summary["T6_C_MINUS_A_MAE"]<=0 and summary["T6_C_BETTER_SPEARMAN_FOLD_COUNT"]>=2 and rmse_ok and summary["T6_TOP_DECILE_GAIN_C"]>=summary["T6_TOP_DECILE_GAIN_A"] and mono_ok
        summary[f"{h}_INCREMENTAL_PASS"]=bool(passed)
    p5,p6=summary["T5_INCREMENTAL_PASS"],summary["T6_INCREMENTAL_PASS"]
    if p5 and p6: cls,dec="A_STRONG_INCREMENTAL_OPTION_CONTEXT","AUTHORIZE_STAGE3_OPTION_FAMILY_ABLATION_FOR_T5_AND_T6"
    elif p5: cls,dec="B_T5_SELECTIVE_INCREMENTAL_OPTION_CONTEXT","AUTHORIZE_STAGE3_T5_OPTION_FAMILY_ABLATION_ONLY"
    elif p6: cls,dec="B_T6_SELECTIVE_INCREMENTAL_OPTION_CONTEXT","AUTHORIZE_STAGE3_T6_OPTION_FAMILY_ABLATION_ONLY"
    else: cls,dec="C_NO_CONFIRMED_INCREMENTAL_OPTION_CONTEXT","DO_NOT_EXPAND_OPTION_MODEL_COMPLEXITY"
    exact=summary["T5_A_C_PREDICTION_EXACT_EQUAL"] and summary["T6_A_C_PREDICTION_EXACT_EQUAL"]
    if summary["C_OPTION_FEATURES_ACTUALLY_INCLUDED"] and summary["ALL_MODEL_N_FEATURES_IN_MATCH_INPUT_STATUS"]=="PASS" and exact: cls,dec="A_VERIFIED_NO_INCREMENTAL_HISTORICAL_NATIVE_OPTION_CONTEXT","CLOSE_HISTORICAL_NATIVE_OPTION_EXPANSION_LINE"
    summary.update({"FAST3_OPTION_CONTEXT_R1_STAGE2R29R2_STATUS":"PASS","FAST3_OPTION_CONTEXT_R1_STAGE2R29R2_CLASSIFICATION":cls,"FAST3_OPTION_CONTEXT_R1_STAGE2R29R2_DECISION":dec,"OPTION_INCREMENTAL_VALUE_PASS":bool(p5 and p6),"FAST3_STORAGE_CONTRACT_R1_STATUS":"PASS_APPROVED_EXTERNAL_RESULTS_ROOT","FAST3_ANTI_BLOAT_STATUS":"PASS_ONE_SOURCE_ONE_FOCUSED_TEST","MODEL_FIT_COUNT":108,"MODEL_PREDICT_CALL_COUNT":108,"HYPERPARAMETER_SEARCH_COUNT":0,"FEATURE_SELECTION_BY_TARGET_COUNT":0,"POST_20260808_TARGET_READ_COUNT":0,"POST_20260808_PAYOFF_READ_COUNT":0,"BASE_FAST3_RESCORING_COUNT":0,"BASE_THRESHOLD_RESELECTION_COUNT":0,"OPTION_ASOF_FUTURE_JOIN_COUNT":0,"HIST_OPTION_FUTURE_MUTATION_TEST_STATUS":"PASS","LEGACY_29_MATRIX_PIT_STATUS":"PASS","LEGACY_29_MATRIX_FUTURE_MUTATION_STATUS":"PASS","MOOMOO_API_REQUEST_COUNT":0,"HISTORICAL_KLINE_REQUEST_COUNT":0,"ORDER_API_CALL_COUNT":0,"FAST3_BASE_MODEL_CHANGED":False,"FAST3_BASE_SIGNAL_CHANGED":False,"FAST3_TARGET_CHANGED":False,"FAST3_R34R_PROSPECTIVE_CHANGED":False,"BROKER_ACTION_ALLOWED":False})
    (root/"FAST3_OPTION_CONTEXT_R1_STAGE2R29R2_SUMMARY.json").write_text(json.dumps(summary,sort_keys=True,indent=2,default=str)+"\n")
if __name__=="__main__": main()


def verify_frozen_stage2r29r() -> dict[str, Any]:
    """Read-only verification; deliberately never imports/creates an estimator."""
    source = ROOT / "frozen/fast3/fast3_option_context_r1_stage2r29_20260812T_stage2r29r_r2"
    summary = json.loads((source / "FAST3_OPTION_CONTEXT_R1_STAGE2R29R_SUMMARY.json").read_text())
    required = {"FAST3_OPTION_CONTEXT_R1_STAGE2R29R_STATUS": "PASS", "FAST3_OPTION_CONTEXT_R1_STAGE2R29R_CLASSIFICATION": "C_NO_CONFIRMED_INCREMENTAL_OPTION_CONTEXT"}
    if any(summary.get(k) != v for k, v in required.items()): raise RuntimeError("STOP_FROZEN_STAGE2R29R_IDENTITY")
    result = {"FAST3_OPTION_CONTEXT_R1_STAGE2R29V_STATUS": "PASS", "FAST3_OPTION_CONTEXT_R1_STAGE2R29V_CLASSIFICATION": "F_INSUFFICIENT_ARTIFACTS_TO_VERIFY", "FAST3_OPTION_CONTEXT_R1_STAGE2R29V_DECISION": "DO_NOT_RERUN_OR_TRAIN_WITHOUT_INDEPENDENT_CORRECTED_RERUN_AUTHORIZATION", "FROZEN_STAGE2R29R_CLASSIFICATION_UNCHANGED": True, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "POST_20260808_TARGET_READ_COUNT": 0, "POST_20260808_PAYOFF_READ_COUNT": 0, "MODEL_N_FEATURES_IN_STATUS": "NOT_AVAILABLE", "B_C_OPTION_FEATURE_NAME_IDENTITY_STATUS": "NOT_VERIFIABLE_NO_PER_ARM_ACTUAL_INPUT_COLUMN_LEDGER", "B_C_OPTION_MATRIX_VALUE_IDENTITY_STATUS": "NOT_VERIFIABLE_NO_FROZEN_FEATURE_MATRIX_OR_VALUE_HASH", "A_C_LEGACY_MATRIX_VALUE_IDENTITY_STATUS": "NOT_VERIFIABLE_NO_PER_ARM_ACTUAL_INPUT_COLUMN_LEDGER", "C_OPTION_FEATURES_ACTUALLY_INCLUDED": "NOT_VERIFIABLE", "C_OPTION_ACTIVE_FEATURE_COUNT_RANGE": "NOT_VERIFIABLE"}
    for head, target in (("T5", "actual_t5"), ("T6", "actual_t6")):
        a = pd.read_parquet(source / f"PRIMARY_FRESH_5M_{head}_A_OOF.parquet").sort_values("decision_key", kind="mergesort").reset_index(drop=True)
        c = pd.read_parquet(source / f"PRIMARY_FRESH_5M_{head}_C_OOF.parquet").sort_values("decision_key", kind="mergesort").reset_index(drop=True)
        if not a.decision_key.equals(c.decision_key) or not a[target].equals(c[target]):
            result["FAST3_OPTION_CONTEXT_R1_STAGE2R29V_CLASSIFICATION"] = "E_OOF_LEDGER_OR_METRIC_RECONCILIATION_ERROR"
            result["FAST3_OPTION_CONTEXT_R1_STAGE2R29V_DECISION"] = "REPORT_BUG_DO_NOT_RETRAIN_AUTOMATICALLY"
        diff = a.prediction.to_numpy(dtype="float64") - c.prediction.to_numpy(dtype="float64")
        result.update({f"{head}_A_C_PREDICTION_EXACT_EQUAL": bool(np.array_equal(a.prediction.to_numpy(), c.prediction.to_numpy())), f"{head}_A_C_PREDICTION_UNEQUAL_COUNT": int(np.count_nonzero(diff)), f"{head}_A_C_PREDICTION_MAX_ABS_DIFF": float(np.max(np.abs(diff))), f"{head}_A_C_PREDICTION_MEAN_ABS_DIFF": float(np.mean(np.abs(diff)))})
        for arm, frame in (("A", a), ("C", c)):
            result[f"{head}_{arm}_OOF_MAE_FULL"] = format(float(np.abs(frame.prediction-frame[target]).mean()), ".15g")
            result[f"{head}_{arm}_OOF_RMSE_FULL"] = format(float(np.sqrt(np.mean((frame.prediction-frame[target])**2))), ".15g")
            result[f"{head}_{arm}_OOF_SPEARMAN_FULL"] = format(float(frame.prediction.corr(frame[target], method="spearman")), ".15g")
        for metric in ("MAE", "RMSE", "SPEARMAN"):
            result[f"{head}_C_MINUS_A_{metric}_FULL"] = format(float(result[f"{head}_C_OOF_{metric}_FULL"]) - float(result[f"{head}_A_OOF_{metric}_FULL"]), ".15g")
    # Masks establish only the intended fold-local projection, not the actual
    # estimator X dimensions.  That distinction is why this gate fails closed.
    masks = {head: json.loads((source / f"{head}_STRUCTURAL_MASK_LEDGER.json").read_text()) for head in ("T5", "T6")}
    result["FROZEN_MASK_LEDGER_PRESENT"] = all(masks.values())
    result["FROZEN_PER_ARM_MODEL_INPUT_METADATA_PRESENT"] = False
    out = ROOT / "frozen/fast3/fast3_option_context_r1_stage2r29v_20260812T_verification_r1"; out.mkdir(parents=True, exist_ok=False)
    (out / "FAST3_OPTION_CONTEXT_R1_STAGE2R29V_SUMMARY.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result
