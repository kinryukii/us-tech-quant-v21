"""JOINT task adapter: existing feature artifacts, fixed sklearn fits and common replay.
No Raw A2 refit, universe producer, account engine or parameter search lives here.
"""
from __future__ import annotations
import argparse, hashlib, json, os, time, csv
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.covariance import LedoitWolf
from threadpoolctl import threadpool_limits
from scripts.common.storage_paths import resolve
from scripts.v22.abcde_a2_r1_nonlinear_cross_sectional_modeling import FEATURE_COLUMNS

def digest(path):
    with Path(path).open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()

class JointExecution:
    def __init__(self, root):
        self.root=Path(root).resolve()
        roots=resolve(Path(__file__).resolve().parents[4])
        if self.root != (roots.results_root/"JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1").resolve():
            raise ValueError("Unexpected task destination")
        self.parameters=self.read("EXECUTION_PARAMETERS.json")
        self.budget=self.read("SEARCH_BUDGET.json")
        self.features=list(FEATURE_COLUMNS)
        self.status=self.read("work/FIT_STATUS.json") if self.out("work/FIT_STATUS.json").exists() else {
            "status":"RUNNING","fit_attempts":0,"records":[],"failures":[],"test2026_rows_read":0,
            "training_mode":"ALL_OBSERVED_LEGAL_LABELS_NO_SAMPLING_FULL_POOL_KEYS_RETAINED",
            "qualification":"PARTIAL_REQUIRED_RAW_COVERAGE_NOT_COMPLETE"}
        for name in ["models","OOF","ledgers","reports","temp","cache","logs"]:
            self.out(name).mkdir(exist_ok=True)
    def out(self, rel):
        p=(self.root/rel).resolve()
        if not p.is_relative_to(self.root):raise ValueError("Task path escapes root")
        return p
    def read(self,rel):
        return json.loads(self.out(rel).read_text(encoding="utf-8-sig"))
    def write(self,rel,obj):
        p=self.out(rel);p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False)+"\n",encoding="utf-8")
    def checkpoint(self):
        self.write("work/FIT_STATUS.json",self.status)
        m=self.read("RUN_MANIFEST.json")
        m["status"]="REAL_FITS_RUNNING_PARTIAL_INPUT_QUALIFICATION"
        m["counts"]["new_fits"]=self.status["fit_attempts"]
        m["milestones"]["pre2026_full_chain_oof"]="REAL_LEGAL_PARTIAL_OOF_RUNNING_FULL_INPUT_GAP_RETAINED"
        self.write("RUN_MANIFEST.json",m)
    def fit_state(self, kind, year, key, frame, creator, state_count=1):
        artifact=self.out(f"models/{kind}_{year}.joblib")
        identity={
            "kind":kind,"cutoff_exclusive":f"{year}-01-01","target":self.parameters["target"],
            "features":self.features,"input_sha256":self.input_sha,"key":key,
            "train_keys_sha256":hashlib.sha256(pd.util.hash_pandas_object(
                frame[["signal_date","ticker","label_end_date"]],index=False).values.tobytes()).hexdigest(),
            "parameters_sha256":digest(self.out("EXECUTION_PARAMETERS.json")),
            "seed":42}
        previous=next((r for r in self.status["records"] if r.get("identity")==identity),None)
        if previous:
            if previous["status"]!="FIT_COMPLETE":raise RuntimeError("Preserve prior failed fit; no automatic retry")
            if not artifact.exists() or digest(artifact)!=previous["sha256"]:raise RuntimeError("Frozen fitted artifact changed")
            print(json.dumps({"status":"DIRECT_REUSE","kind":kind,"year":year}),flush=True)
            return joblib.load(artifact)
        if artifact.exists():raise RuntimeError("Unregistered artifact must be preserved")
        if self.status["fit_attempts"]+state_count>self.budget["limits"]["MAX_TOTAL_FITS"]:
            raise RuntimeError("Finite fit budget exhausted")
        self.status["fit_attempts"]+=state_count
        record={"identity":identity,"status":"FIT_STARTED","learned_states":state_count,"rows":len(frame),
            "signal_min":str(frame.signal_date.min()),"signal_max":str(frame.signal_date.max()),
            "max_label_end":str(frame.label_end_date.max()),"artifact":str(artifact),
            "started_utc":datetime.now(timezone.utc).isoformat()}
        self.status["records"].append(record);self.checkpoint()
        start=time.monotonic()
        print(json.dumps({"status":"REAL_FIT_STARTED","kind":kind,"year":year,"rows":len(frame)}),flush=True)
        try:
            with threadpool_limits(limits=2): obj=creator()
            joblib.dump(obj,artifact,compress=3)
            record.update(status="FIT_COMPLETE",sha256=digest(artifact),seconds=time.monotonic()-start)
        except Exception as exc:
            record.update(status="TRAINING_NUMERICAL_FAILURE",error=repr(exc),seconds=time.monotonic()-start)
            self.status["failures"].append({"kind":kind,"year":year,"error":repr(exc)})
            self.checkpoint();raise
        self.checkpoint()
        print(json.dumps({"status":"REAL_FIT_COMPLETE","kind":kind,"year":year,"seconds":round(record["seconds"],2)}),flush=True)
        return obj
    def fit(self):
        config=self.read("receipts/R1_TRAINING_INPUTS.json")
        self.input_sha=config["panel_sha256"]
        panel_path=Path(config["panel"])
        if not panel_path.is_relative_to(self.root):raise ValueError("Derived panel must be task local")
        # Producer receipt establishes physical pre-2026 boundary before data pages.
        if config["all_source_date_max"]>="2026-01-01" or config["task2026_data_pages_read"] != 0:
            raise ValueError("Training boundary violation")
        frame=pd.read_parquet(panel_path)
        frame["signal_date"]=pd.to_datetime(frame.signal_date)
        frame["label_end_date"]=pd.to_datetime(frame.label_end_date)
        if frame.signal_date.ge("2026-01-01").any():raise ValueError("Mixed-year input prohibited")
        feature_valid=np.isfinite(frame[self.features].to_numpy(float)).all(axis=1)
        label_valid=np.isfinite(frame.y_next_open.to_numpy(float)) & frame.label_end_date.notna().to_numpy()
        if "feature_eligible" in frame:feature_valid &= frame.feature_eligible.to_numpy(bool)
        observed=feature_valid & label_valid & frame.model_sample_eligible.to_numpy(bool)
        if not observed.any():raise RuntimeError("Required pre2026 matured targets physically absent")
        predictions=[]
        earlier={}
        for year in [2022,2023,2024,2025]:
            cutoff=pd.Timestamp(year,1,1)
            train=frame.loc[observed & frame.signal_date.lt(cutoff) & frame.label_end_date.lt(cutoff)].copy()
            if train.empty:raise RuntimeError(f"No legal OOF training fold:{year}")
            valid=frame.signal_date.ge(cutoff) & frame.signal_date.lt(pd.Timestamp(year+1,1,1))
            block=frame.loc[valid,["signal_date","ticker","execution_date","label_end_date","y_next_open"]].copy()
            block["fold_year"]=year
            block["feature_eligible"]=feature_valid[valid]
            block["label_available"]=label_valid[valid]
            block["full_pool_member"]=True
            xx=train[self.features].to_numpy(float);yy=train.y_next_open.to_numpy(float)
            vx=frame.loc[valid & feature_valid,self.features].to_numpy(float)
            for name in ["Ridge","HGB"]:
                cfg=self.parameters["opportunity_parameters"][name]
                def creator(name=name,cfg=cfg):
                    if name=="Ridge":
                        scaler=StandardScaler().fit(xx)
                        model=Ridge(**cfg).fit(scaler.transform(xx),yy)
                        return {"model":model,"scaler":scaler}
                    return {"model":HistGradientBoostingRegressor(**cfg).fit(xx,yy),"scaler":None}
                try:
                    bundle=self.fit_state(name,year,cfg,train,creator,2 if name=="Ridge" else 1)
                except RuntimeError as exc:
                    if "failed fit" in str(exc):continue
                    raise
                pred=np.full(len(block),np.nan)
                with threadpool_limits(limits=2):
                    features=bundle["scaler"].transform(vx) if bundle["scaler"] is not None else vx
                    pred[block.feature_eligible.to_numpy()]=bundle["model"].predict(features)
                block[name+"_raw"]=pred
                if year>2022:
                    history=pd.concat(earlier[name],ignore_index=True)
                    history=history.loc[history.label_available & history.label_end_date.lt(cutoff)
                        & history.signal_date.lt(cutoff) & np.isfinite(history[name+"_raw"])].copy()
                    if history.empty:raise RuntimeError("No legal matured inner OOF for calibration")
                    hx=history[[name+"_raw"]].to_numpy(float);hy=history.y_next_open.to_numpy(float)
                    counts=history.signal_date.map(history.signal_date.value_counts()).to_numpy(float)
                    weights=1/counts;weights/=weights.mean()
                    def make_calibrator():
                        scaler=StandardScaler().fit(hx,sample_weight=weights)
                        model=Ridge(alpha=100).fit(scaler.transform(hx),hy,sample_weight=weights)
                        residual=hy-model.predict(scaler.transform(hx))
                        return {"model":model,"scaler":scaler,
                            "residual_rms":float(max(np.sqrt(np.average(residual**2,weights=weights)),1e-6))}
                    calibrated=self.fit_state("calibration_"+name,year,{"alpha":100,"date_weighting":"equal","chronological_oof":True},
                        history,make_calibrator,2)
                    mu=np.full(len(block),np.nan)
                    ok=np.isfinite(pred)
                    mu[ok]=calibrated["model"].predict(calibrated["scaler"].transform(pred[ok,None]))
                    block[name+"_mu"]=mu
                    block[name+"_uncertainty"]=np.where(ok,calibrated["residual_rms"],np.nan)
                earlier.setdefault(name,[]).append(block[
                    ["signal_date","ticker","label_end_date","y_next_open","label_available",name+"_raw"]].copy())
            dest=self.out(f"OOF/predictions_{year}.parquet")
            block.to_parquet(dest,index=False)
            if year>=2023:predictions.append(block)
        combined=pd.concat(predictions,ignore_index=True)
        combined["ensemble_mu"]=(combined.Ridge_mu+combined.HGB_mu)/2
        combined["ensemble_disagreement"]=np.abs(combined.Ridge_mu-combined.HGB_mu)/2
        combined.to_parquet(self.out("OOF_PREDICTIONS.parquet"),index=False)
        self.status["status"]="REAL_OPPORTUNITY_AND_CALIBRATION_OOF_COMPLETE_PARTIAL_COVERAGE"
        self.status["oof_rows"]=len(combined)
        self.status["oof_actual_predicted_rows"]=int(np.isfinite(combined.ensemble_mu).sum())
        self.status["required_fullpool_input_complete"]=False
        self.checkpoint()
        self.write("CALIBRATION.json",{"status":"REAL_FITTED_EARLIER_MATURED_OOF_ONLY",
            "algorithm":"weighted scaler plus affine Ridge alpha100","sampling":False,
            "source":"models/calibration_*","full_input_qualification":False,"test2026_fit_rows":0})
        records=[]
        for r in self.status["records"]:
            records.append({"model_id":r["identity"]["kind"]+"_"+str(r["identity"]["cutoff_exclusive"])[:4],
                "status":r["status"],"fit_count":r["learned_states"],"cutoff":r["identity"]["cutoff_exclusive"],
                "artifact":r["artifact"],"sha256":r.get("sha256",""),"rows":r["rows"]})
        pd.DataFrame(records).to_csv(self.out("MODEL_REGISTRY.csv"),index=False)
        self.write("receipts/REAL_OOF_RECEIPT.json",{"status":self.status["status"],"output":str(self.out("OOF_PREDICTIONS.parquet")),
            "sha256":digest(self.out("OOF_PREDICTIONS.parquet")),"rows":len(combined),
            "predicted_rows":self.status["oof_actual_predicted_rows"],"full_pool_rows_retained":True,
            "feature_unavailable_rows":int((~combined.feature_eligible).sum()),
            "target_unavailable_rows":int((~combined.label_available).sum()),"fit_attempts":self.status["fit_attempts"],
            "test2026_rows_read":0,"no_raw_a2_refit":True,"no_input_sampling":True,
            "primary_qualification":"UNTESTABLE_REQUIRED_FULLPOOL_RAW_OBJECTS_ABSENT"})
        print(json.dumps({"status":self.status["status"],"fit_states":self.status["fit_attempts"],"oof_rows":len(combined),
            "predicted_rows":self.status["oof_actual_predicted_rows"],"2026_read":0}),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--task-root",required=True)
    parser.add_argument("command",choices=["fit"])
    args=parser.parse_args()
    JointExecution(args.task_root).fit()
if __name__=="__main__":main()
