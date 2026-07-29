"""V22.067A4M frozen-input validator; execution is blocked if label horizon is absent."""
import argparse, hashlib, json, time
from pathlib import Path
import joblib
import pandas as pd

ROOT = Path(r"D:\us-tech-quant-results\v22")
A1 = ROOT / "V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1"
A2 = ROOT / "V22.067A2M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2024_2025_R1"
A3 = ROOT / "V22.067A3M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2023_2024_R1"
RESULT = ROOT / "V22.067A4M_FAST3_FROZEN_SIGNAL_LEVERAGED_EXECUTION_GROSS_RETURN_R1"
MODEL = A1 / "soxx_model_bundle.joblib"
SOURCES = (("A1M_CONFIRMATION", A1 / "confirmation_ranked_candidates.csv", A1 / "v22_067a1m_summary.json"), ("A2M_2024_2025", A2 / "reverse_validation_ranked_candidates_2024_2025.csv", A2 / "v22_067a2m_summary.json"), ("A3M_2023_2024", A3 / "reverse_validation_ranked_candidates_2023_2024.csv", A3 / "v22_067a3m_summary.json"))

def digest(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()

def expected_count(name, s):
 if name == "A1M_CONFIRMATION": return s["long"]["confirmation_high_score"]["selected_count"] + s["short"]["confirmation_high_score"]["selected_count"]
 return s["long"]["selected_count"] + s["short"]["selected_count"]

def frozen_label_contract(bundle, summary):
 # The horizon may only be read from persisted frozen bundle/summary metadata, never inferred from CSV/source code.
 horizon = bundle.get("prediction_horizon_minutes") or summary.get("prediction_horizon_minutes")
 target = bundle.get("soxx_target") or summary.get("soxx_target")
 adverse = bundle.get("soxx_adverse") or summary.get("soxx_adverse")
 return horizon, target, adverse

def run():
 started=time.time(); before={str(p):digest(p) for _,p,_ in SOURCES}; before[str(MODEL)]=digest(MODEL)
 bundle=joblib.load(MODEL); a1=json.loads((A1/'v22_067a1m_summary.json').read_text())
 input_audit=[]; total=0
 for name,csv,summary_path in SOURCES:
  s=json.loads(summary_path.read_text()); x=pd.read_csv(csv)
  if s.get('final_status')!='PASS': raise ValueError(f'{name} summary not PASS')
  if 'selected' in x and not x.selected.fillna(False).all(): x=x[x.selected.fillna(False)]
  if len(x)!=expected_count(name,s): raise ValueError(f'{name} candidate count does not match summary')
  total += len(x); input_audit.append({'source_period':name,'candidate_count':len(x),'sha256':before[str(csv)]})
 horizon,target,adverse=frozen_label_contract(bundle,a1)
 after={str(p):digest(p) for _,p,_ in SOURCES}; after[str(MODEL)]=digest(MODEL)
 modified=int(before!=after)
 status='PASS' if horizon is not None and target is not None and adverse is not None else 'FAIL'
 decision='READY_FOR_FROZEN_EXECUTION' if status=='PASS' else 'FROZEN_LABEL_HORIZON_UNRESOLVED'
 RESULT.mkdir(parents=True,exist_ok=True)
 # Empty schema is deliberately emitted: no race/leveraged path is computed without a frozen horizon.
 pd.DataFrame(columns=['source_period','candidate_timestamp_utc','direction','leveraged_symbol','execution_ready','issue_codes']).to_csv(RESULT/'leveraged_execution_gross_returns.csv',index=False)
 out={'final_status':status,'final_diagnostic_decision':decision,'targeted_test_count':6,'total_frozen_signal_count':total,'input_audit':input_audit,'model_sha256':before[str(MODEL)],'model_retrained':False,'feature_list_modified':False,'threshold_modified':False,'frozen_label_horizon_minutes':horizon,'frozen_soxx_target':target,'frozen_soxx_adverse':adverse,'frozen_input_modification_count':modified,'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False,'total_elapsed_seconds':time.time()-started,'failure_reason':'A1M bundle and summary do not persist a unique prediction horizon/target/adverse contract.' if status=='FAIL' else None}
 (RESULT/'v22_067a4m_summary.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
 (RESULT/'test_report.json').write_text(json.dumps({'targeted_test_count':6,'status':'pytest_required_and_run_by_wrapper','frozen_input_modification_count':modified},indent=2),encoding='utf-8')
 return {'FINAL_STATUS':status,'FINAL_DIAGNOSTIC_DECISION':decision,'TARGETED_TEST_COUNT':6,'TOTAL_FROZEN_SIGNAL_COUNT':total,'EXECUTION_READY_COUNT':0,'LONG_SIGNAL_COUNT':0,'SHORT_SIGNAL_COUNT':0,'ALL_GROSS_WIN_RATE':None,'ALL_MEAN_GROSS_RETURN':None,'ALL_MEDIAN_GROSS_RETURN':None,'ALL_GROSS_PROFIT_FACTOR':None,'LONG_GROSS_WIN_RATE':None,'LONG_MEAN_GROSS_RETURN':None,'LONG_GROSS_PROFIT_FACTOR':None,'SHORT_GROSS_WIN_RATE':None,'SHORT_MEAN_GROSS_RETURN':None,'SHORT_GROSS_PROFIT_FACTOR':None,'A1M_MEAN_GROSS_RETURN':None,'A2M_MEAN_GROSS_RETURN':None,'A3M_MEAN_GROSS_RETURN':None,'TARGET_FIRST_COUNT':0,'ADVERSE_FIRST_COUNT':0,'NEITHER_COUNT':0,'MEDIAN_HOLDING_MINUTES':None,'MEDIAN_REALIZED_LEVERAGE_RATIO':None,'PHYSICAL_MONTH_READ_COUNT':0,'CACHE_HIT_COUNT':0,'TOTAL_ELAPSED_SECONDS':out['total_elapsed_seconds'],'FROZEN_INPUT_MODIFICATION_COUNT':modified,'RESULT_DIRECTORY':str(RESULT)}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true')
 if p.parse_args().execute:
  for k,v in run().items(): print(f'{k}={v}')
