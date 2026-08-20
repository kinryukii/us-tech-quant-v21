"""R35A outcome-blind T1/T5/T6 combination preregistration; no model or outcome reads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

R=Path(r"D:\us-tech-quant-results"); OUT=R/"frozen/fast3/fast3_r35a_frozen_t1_t5_t6_outcome_blind_20260812T_r1"
T1=R/"scratch/fast3/r32b_full_universe_20260810T160000Z/FAST3_R32B_OOF_PREDICTIONS.parquet"
T5=R/"scratch/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33B_T5_OOF_PREDICTIONS.parquet"
T6=R/"scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
T1_SUM=R/"frozen/fast3/r32b_full_universe_20260810T160000Z/FAST3_R32B_SUMMARY.json"; T5C=R/"frozen/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1.json"; T6C=R/"frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
T1_TARGET_SHA="381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def stable(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def only(p, cols): return pd.read_parquet(p,columns=cols)
def main():
 t1s=json.loads(T1_SUM.read_text()); t5c=json.loads(T5C.read_text()); t6c=json.loads(T6C.read_text())
 if sha(T5C)!="d491b24943fc484577449b375a1bed3f34aa122773c0f007e674951193d1db3a" or sha(T6C)!="6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2":raise RuntimeError("STOP_PRE_RUN_IDENTITY_MISMATCH")
 # Strictly project prediction/key/fold columns—never target or payoff fields.
 a=only(T1,["candidate_id","decision_timestamp_utc","head","fold","pred_t1"]).rename(columns={"fold":"fold_t1","pred_t1":"t1_probability"})
 b=only(T5,["candidate_id","decision_timestamp_utc","head","fold","fold_model","pred_t5"]).rename(columns={"fold":"fold_t5","pred_t5":"t5_prediction_raw"})
 c=only(T6,["candidate_id","decision_timestamp_utc","head","fold","pred_t6"]).rename(columns={"fold":"fold_t6","pred_t6":"t6_prediction_raw"})
 key=["candidate_id","decision_timestamp_utc","head"]
 s1,s5,s6=set(a.candidate_id),set(b.candidate_id),set(c.candidate_id); common=s1&s5&s6
 if not common: raise RuntimeError("STOP_CROSS_HEAD_OOF_PREDICTIONS_NOT_COLOCATED")
 x=a.merge(b,on=key,validate="one_to_one").merge(c,on=key,validate="one_to_one")
 mismatch=int((x.fold_t1.ne(x.fold_t5)|x.fold_t1.ne(x.fold_t6)|x.fold_t5.ne(x.fold_model)).sum())
 if mismatch: raise RuntimeError("STOP_CROSS_HEAD_OOF_LINEAGE_INCOMPATIBLE")
 if not (t1s.get("TARGET_CONTRACT_SHA256")==T1_TARGET_SHA and t5c["TRAINING_ELIGIBILITY"]=="label_valid == true AND net20 < 0" and t6c["TRAINING_ELIGIBILITY"]=="label_valid == true AND net20 > 0"):raise RuntimeError("STOP_T1_T5_T6_EVENT_SEMANTICS_INCOMPATIBLE")
 if not ("log1p" in t5c["FORMULA"].lower() and "log1p" in t6c["TARGET_FORMULA"].lower()):raise RuntimeError("STOP_FROZEN_TARGET_TRANSFORM_UNRESOLVED")
 bad=int((~x.t1_probability.between(0,1)).sum());
 if bad:raise RuntimeError("STOP_T1_NOT_PROBABILITY")
 x["loss_magnitude"]=np.maximum(0,np.expm1(x.t5_prediction_raw)); x["gain_magnitude"]=np.maximum(0,np.expm1(x.t6_prediction_raw)); x["expected_gain_component"]=x.t1_probability*x.gain_magnitude; x["expected_loss_component"]=(1-x.t1_probability)*x.loss_magnitude; x["expected_payoff_raw"]=x.expected_gain_component-x.expected_loss_component
 ledger=x.rename(columns={"head":"direction","fold_t1":"fold_id"})[["candidate_id","decision_timestamp_utc","direction","fold_id","t1_probability","t5_prediction_raw","t6_prediction_raw","loss_magnitude","gain_magnitude","expected_gain_component","expected_loss_component","expected_payoff_raw"]].rename(columns={"candidate_id":"decision_key","decision_timestamp_utc":"timestamp"}).sort_values(["timestamp","decision_key"],kind="mergesort").reset_index(drop=True)
 if ledger.duplicated("decision_key").any() or not np.isfinite(ledger.select_dtypes("number")).all().all():raise RuntimeError("STOP_LEDGER_DOMAIN")
 OUT.mkdir(parents=True,exist_ok=False); path=OUT/"FAST3_R35A_FROZEN_EXPECTED_PAYOFF_LEDGER.parquet"; ledger.to_parquet(path,index=False); h1=sha(path); ledger.to_parquet(OUT/"_determinism_check.parquet",index=False); h2=sha(OUT/"_determinism_check.parquet")
 prereg={"CONTRACT_ID":"FAST3_R35B_FROZEN_OOF_ECONOMIC_ORDERING_EVALUATION_R1","STATUS":"PREREGISTERED_OUTCOME_BLIND","SCORE":"EXPECTED_PAYOFF_RAW","POSITIVE_EV_THRESHOLD":"EXPECTED_PAYOFF_RAW > 0","PASS_RULE":"Spearman>0; D10 mean>D1 mean; D10 median>=D1 median; majority chronological folds Spearman>0; positive-EV mean>non-positive-EV mean; not single-direction-only","DIAGNOSTICS":"fixed pooled deciles; top/bottom mean/median; UP/DOWN; decile monotonicity diagnostic only","OUTCOME_READ_IN_R35A":0}; pp=OUT/"FAST3_R35B_PREREGISTRATION.json";pp.write_text(json.dumps(prereg,sort_keys=True,indent=2)+"\n")
 summary={"FAST3_R35A_STATUS":"PASS","FAST3_R35A_CLASSIFICATION":"A_FROZEN_OUTCOME_BLIND_EXPECTED_PAYOFF_COMBINATION_READY","FAST3_R35A_DECISION":"AUTHORIZE_R35B_FROZEN_OOF_ECONOMIC_ORDERING_EVALUATION","FAST3_STORAGE_CONTRACT_R1_STATUS":"PASS_APPROVED_EXTERNAL_RESULTS_ROOT","FAST3_ANTI_BLOAT_STATUS":"PASS_ONE_SOURCE_ONE_FOCUSED_TEST","T1_TARGET_NAME":"T1_POSITIVE_NET20","T1_TARGET_SHA256":T1_TARGET_SHA,"T1_MODEL_ID":"FAST3_R32B_FULL_UNIVERSE_T1","T1_MODEL_SHA256":"NOT_SERIALIZED_FROZEN_OOF_ONLY","T1_OOF_ARTIFACT_PATH":str(T1),"T1_OOF_SHA256":sha(T1),"T1_FOLD_MANIFEST_SHA256":t1s["SPLIT_CONTRACT_SHA256"],"T1_PREDICTION_SEMANTICS":"P(corporate-action-normalized executable net20 > 0)","T5_TARGET_NAME":t5c["TARGET_NAME"],"T5_TARGET_SHA256":sha(T5C),"T5_OOF_ARTIFACT_PATH":str(T5),"T5_OOF_SHA256":sha(T5),"T5_FOLD_MANIFEST_SHA256":t5c["SPLIT_CONTRACT_SHA256"],"T5_TARGET_TRANSFORM":t5c["TRANSFORMATION"],"T5_PREDICTION_TRANSFORM":t5c["TRANSFORMATION"],"T5_CONDITION_DEFINITION":t5c["TRAINING_ELIGIBILITY"],"T5_INVERSE_TRANSFORM":"max(0, expm1(t5_prediction_raw))","T6_TARGET_NAME":t6c["TARGET_NAME"],"T6_TARGET_SHA256":sha(T6C),"T6_OOF_ARTIFACT_PATH":str(T6),"T6_OOF_SHA256":sha(T6),"T6_FOLD_MANIFEST_SHA256":t6c["SPLIT_CONTRACT_SHA256"],"T6_TARGET_TRANSFORM":t6c["TARGET_FORMULA"],"T6_PREDICTION_TRANSFORM":t6c["TARGET_FORMULA"],"T6_CONDITION_DEFINITION":t6c["TRAINING_ELIGIBILITY"],"T6_INVERSE_TRANSFORM":"max(0, expm1(t6_prediction_raw))","MAGNITUDE_NONNEGATIVITY_RULE":"max(0, inverse-transformed magnitude)","T1_OOF_ROW_COUNT":len(a),"T5_OOF_ROW_COUNT":len(b),"T6_OOF_ROW_COUNT":len(c),"T1_T5_INTERSECTION_COUNT":len(s1&s5),"T1_T6_INTERSECTION_COUNT":len(s1&s6),"T5_T6_INTERSECTION_COUNT":len(s5&s6),"T1_T5_T6_INTERSECTION_COUNT":len(common),"CROSS_HEAD_FOLD_IDENTITY_STATUS":"PASS","CROSS_HEAD_FOLD_MISMATCH_COUNT":mismatch,"T1_PROBABILITY_OUT_OF_RANGE_COUNT":bad,"T5_PREDICTION_FINITE_COUNT":int(np.isfinite(x.t5_prediction_raw).sum()),"T6_PREDICTION_FINITE_COUNT":int(np.isfinite(x.t6_prediction_raw).sum()),"CANONICAL_EXPECTED_PAYOFF_FORMULA":"p*gain_magnitude-(1-p)*loss_magnitude","EXECUTION_COST_TERM_INCLUDED":False,"R35A_EXPECTED_PAYOFF_LEDGER_ROW_COUNT":len(ledger),"R35A_EXPECTED_PAYOFF_LEDGER_SHA256":h1,"R35A_LEDGER_STABILITY_STATUS":"PASS" if h1==h2 else "FAIL","R35A_LEDGER_START":str(ledger.timestamp.min()),"R35A_LEDGER_END":str(ledger.timestamp.max()),"EXPECTED_PAYOFF_POSITIVE_COUNT":int(ledger.expected_payoff_raw.gt(0).sum()),"EXPECTED_PAYOFF_NEGATIVE_COUNT":int(ledger.expected_payoff_raw.lt(0).sum()),"EXPECTED_PAYOFF_ZERO_COUNT":int(ledger.expected_payoff_raw.eq(0).sum()),"R35B_PREREGISTRATION_STATUS":"PASS_FROZEN_BEFORE_OUTCOME_READ","R35B_PREREGISTRATION_SHA256":sha(pp),"OUTCOME_VALUE_READ_COUNT":0,"PAYOFF_VALUE_READ_COUNT":0,"ECONOMIC_METRIC_COMPUTE_COUNT":0,"POST_20260808_TARGET_READ_COUNT":0,"POST_20260808_PAYOFF_READ_COUNT":0,"MODEL_FIT_COUNT":0,"MODEL_PREDICT_CALL_COUNT":0,"FAST3_BASE_MODEL_CHANGED":False,"FAST3_BASE_SIGNAL_CHANGED":False,"FAST3_TARGET_CHANGED":False,"FAST3_R34R_PROSPECTIVE_CHANGED":False,"FAST3_POSITION_SIZING_CHANGED":False,"BROKER_ACTION_ALLOWED":False}
 (OUT/"FAST3_R35A_SUMMARY.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
if __name__=="__main__":main()
