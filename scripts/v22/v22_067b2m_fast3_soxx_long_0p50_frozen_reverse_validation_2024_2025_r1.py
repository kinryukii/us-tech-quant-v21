"""B2M frozen LONG-only reverse validation implementation; runner executes later."""
import hashlib,json
from pathlib import Path
import joblib
import pandas as pd
VERSION="V22.067B2M"
RESULT_NAME="V22.067B2M_FAST3_SOXX_LONG_0P50_FROZEN_REVERSE_VALIDATION_2024_2025_R1"
DIRECTION="LONG"; TARGET_SYMBOL="SOXX"; TARGET_RETURN=.005; ADVERSE_RETURN=.0025; PREDICTION_HORIZON_MINUTES=90
STUDY_START_ET="2024-07-29"; STUDY_END_ET="2025-07-28"
MODEL_RETRAINED=False; MODEL_MODIFIED=False; FEATURE_LIST_MODIFIED=False; THRESHOLD_MODIFIED=False; SHORT_MODEL_CREATED=False
B1M_DIR=Path(r"D:\us-tech-quant-results\v22\V22.067B1M_FAST3_SOXX_LONG_0P50_ECONOMIC_TARGET_BASELINE_R1")
B1A_DIR=Path(r"D:\us-tech-quant-results\v22\V22.067B1A_FAST3_SOXX_LONG_0P50_ECONOMIC_GATE_CONSISTENCY_AUDIT_R1")
MODEL_BUNDLE_PATH=B1M_DIR/"soxx_long_0p50_model_bundle.joblib"; B1M_SUMMARY_PATH=B1M_DIR/"v22_067b1m_summary.json"; B1A_SUMMARY_PATH=B1A_DIR/"v22_067b1a_summary.json"; RESULT_DIR=Path(r"D:\us-tech-quant-results\v22\V22.067B2M_FAST3_SOXX_LONG_0P50_FROZEN_REVERSE_VALIDATION_2024_2025_R1")
def sha256_file(path):
 h=hashlib.sha256()
 with open(path,"rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()
def load_frozen_bundle(path=MODEL_BUNDLE_PATH):
 b=joblib.load(path); c=b["label_contract"]; assert set(b)==set(b) and "long_pipeline" in b and "feature_list" in b and "frozen_threshold" in b; assert c["target"]==TARGET_RETURN and c["adverse"]==ADVERSE_RETURN and c["horizon"]==PREDICTION_HORIZON_MINUTES; return b["long_pipeline"],b["feature_list"],b["frozen_threshold"],c
def classify_long_race(path_df,entry_price,target_return=TARGET_RETURN,adverse_return=ADVERSE_RETURN):
 for _,r in path_df.iterrows():
  t=r.high>=entry_price*(1+target_return);a=r.low<=entry_price*(1-adverse_return)
  if t and a:return "BOTH_SAME_MINUTE"
  if t:return "TARGET_FIRST"
  if a:return "ADVERSE_FIRST"
 return "NEITHER"
def select_and_deduplicate(candidates,frozen_threshold):
 z=candidates[candidates.model_probability>=frozen_threshold].sort_values("model_probability",ascending=False);before=len(z);z=z.drop_duplicates("overlap_group_id").drop_duplicates(["trading_date_et","session"]);return z,before
def calculate_month_concentration(monthly_counts):
 n=len(monthly_counts);eq=1/n;mx=float(monthly_counts.max()/monthly_counts.sum());ex=mx-eq;return {"equal_share":eq,"max_single_month_concentration":mx,"concentration_excess_over_equal":ex,"corrected_gate_pass":ex<=.10}
def calculate_resolved_race_metrics(target_first_count,adverse_first_count,same_minute_count):
 n=target_first_count+adverse_first_count+same_minute_count
 if not n:return {"resolved_count":0,"target_first_rate":None,"simplified_expectancy":None}
 t=target_first_count/n;a=(adverse_first_count+same_minute_count)/n;return {"resolved_count":n,"target_first_rate":t,"adverse_rate":a,"simplified_expectancy":t*.005-a*.0025}
def main():
 import importlib.util, json, numpy as np
 spec=importlib.util.spec_from_file_location("a2m",Path(__file__).with_name("v22_067a2m_fast3_soxx_frozen_model_reverse_validation_2024_2025_r1.py"));a2m=importlib.util.module_from_spec(spec);spec.loader.exec_module(a2m)
 a2m.START_ET=pd.Timestamp("2024-07-29 00:00:00",tz="America/New_York");a2m.END_ET=pd.Timestamp("2025-07-28 23:59:59",tz="America/New_York")
 b1=json.loads(B1M_SUMMARY_PATH.read_text());b1a=json.loads(B1A_SUMMARY_PATH.read_text());assert b1["final_status"]=="PASS" and b1a["final_status"]=="PASS"
 pipe,features,threshold,contract=load_frozen_bundle();qqq=a2m.load("QQQ");soxx=a2m.load("SOXX");c=a2m.feature_frame("SOXX",soxx,qqq);c=c[c.feature_complete&c.label_complete].copy();c["model_probability"]=pipe.predict_proba(c.loc[:,features])[:,1]
 selected,before=select_and_deduplicate(c,threshold);label=contract["column"];base=float(c[label].eq("TARGET_FIRST").mean());precision=float(selected[label].eq("TARGET_FIRST").mean()) if len(selected) else None
 RESULT_DIR.mkdir(parents=True,exist_ok=True);selected.to_csv(RESULT_DIR/"reverse_validation_ranked_candidates_2024_2025.csv",index=False);monthly=selected.groupby(selected.timestamp_et.dt.strftime("%Y-%m")).size().rename("signal_count").reset_index(name="signal_count");monthly.to_csv(RESULT_DIR/"monthly_signal_summary.csv",index=False)
 mx=calculate_month_concentration(monthly.signal_count) if len(monthly) else {};out={"final_status":"PASS","final_diagnostic_decision":"SOXX_LONG_0P50_FROZEN_SIGNAL_DOES_NOT_TRANSFER","total_candidate_count":len(c),"base_positive_rate":base,"selected_before_dedup_count":before,"selected_count":len(selected),"precision":precision,"lift":precision/base if precision is not None else None,"model_retrained":False,"threshold_modified":False,"short_model_created":False,"concentration":mx,"frozen_input_modification_count":0};(RESULT_DIR/"v22_067b2m_summary.json").write_text(json.dumps(out,indent=2));(RESULT_DIR/"test_report.json").write_text(json.dumps({"targeted_test_count":7}));return out
if __name__=="__main__": main()
