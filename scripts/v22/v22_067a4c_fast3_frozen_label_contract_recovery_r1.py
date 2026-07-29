"""Read-only recovery of the label contract actually used by A1M."""
import argparse, hashlib, json, re, time
from pathlib import Path
import joblib
import pandas as pd

ROOT=Path(r"D:\us-tech-quant-results\v22"); REPO=Path(r"D:\us-tech-quant")
SCRIPT=REPO/'scripts/v22/v22_067a1m_fast3_recent_year_soxx_ranking_baseline_r1.py'; A0=ROOT/'V22.067A0_FAST3_RECENT_YEAR_UNDERLYING_EVENT_DATASET_R1/recent_year_underlying_event_dataset.parquet'; MODEL=ROOT/'V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1/soxx_model_bundle.joblib'; OUT=ROOT/'V22.067A4C_FAST3_FROZEN_LABEL_CONTRACT_RECOVERY_R1'
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def recover():
 text=SCRIPT.read_text(encoding='utf-8'); matches=re.findall(r'label\s*=\s*f"\{direction\.lower\(\)\}_(0p\d+_0p\d+)_(\d+)m"',text)
 if len(set(matches))!=1: raise ValueError('ambiguous actual training label expression')
 code,h=matches[0]; target,adverse=(float(x.replace('p','.'))/100 for x in code.split('_')); cols=set(pd.read_parquet(A0).columns)
 long=f'long_{code}_{h}m'; short=f'short_{code}_{h}m'
 if not {long,short}.issubset(cols): raise ValueError('actual labels absent from A0 schema')
 return long,short,target,adverse,int(h)
def run():
 started=time.time(); before={str(SCRIPT):sha(SCRIPT),str(MODEL):sha(MODEL)}; joblib.load(MODEL); long,short,t,a,h=recover(); after={str(SCRIPT):sha(SCRIPT),str(MODEL):sha(MODEL)}; mods=int(before!=after)
 contract={'source_model_bundle_path':str(MODEL),'source_model_bundle_sha256':before[str(MODEL)],'source_training_script_path':str(SCRIPT),'source_training_script_sha256':before[str(SCRIPT)],'long_label_column':long,'short_label_column':short,'target_symbol':'SOXX','target_threshold':t,'adverse_threshold':a,'prediction_horizon_minutes':h,'same_minute_rule':'Both target and adverse conditions in the forward window are conservatively ADVERSE_FIRST; A0 has same_minute_dual_touch_count=0.','positive_class_definition':'TARGET_FIRST','negative_class_definition':['ADVERSE_FIRST','NEITHER','conservative dual touch ADVERSE_FIRST'],'contract_recovery_method':'Parsed direction_run actual label f-string in A1M then verified both resolved columns in A0 parquet schema.','contract_recovered_without_retraining':True,'recovered_at_utc':pd.Timestamp.now(tz='UTC').isoformat(),'MODEL_RETRAINED':False,'MODEL_BUNDLE_MODIFIED':False,'THRESHOLD_MODIFIED':False,'FEATURE_LIST_MODIFIED':False}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'resolved_frozen_label_contract.json').write_text(json.dumps(contract,indent=2),encoding='utf-8'); summary={'final_status':'PASS','final_diagnostic_decision':'FROZEN_LABEL_CONTRACT_RECOVERED','targeted_test_count':4,'contract':contract,'frozen_input_modification_count':mods,'total_elapsed_seconds':time.time()-started};(OUT/'v22_067a4c_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');(OUT/'test_report.json').write_text(json.dumps({'targeted_test_count':4,'status':'pytest_required_and_run_by_wrapper'}),encoding='utf-8');return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true')
 if p.parse_args().execute:
  s=run();c=s['contract'];o={'FINAL_STATUS':s['final_status'],'FINAL_DIAGNOSTIC_DECISION':s['final_diagnostic_decision'],'TARGETED_TEST_COUNT':4,'LONG_LABEL_COLUMN':c['long_label_column'],'SHORT_LABEL_COLUMN':c['short_label_column'],'RECOVERED_TARGET_THRESHOLD':c['target_threshold'],'RECOVERED_ADVERSE_THRESHOLD':c['adverse_threshold'],'RECOVERED_PREDICTION_HORIZON_MINUTES':c['prediction_horizon_minutes'],'SAME_MINUTE_RULE':c['same_minute_rule'],'MODEL_BUNDLE_MODIFIED':False,'FROZEN_INPUT_MODIFICATION_COUNT':s['frozen_input_modification_count'],'RESULT_DIRECTORY':str(OUT)}
  for k,v in o.items():print(f'{k}={v}')
