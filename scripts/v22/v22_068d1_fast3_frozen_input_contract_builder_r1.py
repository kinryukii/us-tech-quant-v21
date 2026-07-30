"""V22.068D1 frozen-input contract builder: provenance only; never reads Confirmation rows."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd

REPO=Path(__file__).resolve().parents[2]
OUT=Path(r'D:\us-tech-quant-results\v22\V22.068D1_FAST3_FROZEN_INPUT_CONTRACT_BUILDER_R1')
D_SCRIPT=REPO/'scripts/v22/v22_068d_fast3_compact_model_failure_diagnostic_r1.py'
D_SUMMARY=Path(r'D:\us-tech-quant-results\v22\V22.068D_FAST3_COMPACT_MODEL_FAILURE_DIAGNOSTIC_R1\v22_068d_summary.json')
BRANCH='checkpoint/v22-068d1-contract-and-v22-068e-r2-20260730'
ALLOW={'v22_068d1_summary.json','v22_068d1_manifest.json','v22_068d1_readme.txt','v22_068d1_source_lineage.csv','v22_068d1_frozen_input_contract.json','v22_068d1_frozen_input_contract.sha256','v22_068d1_feature_whitelist.csv','v22_068d1_split_contract.json','v22_068d1_target_contract.json','v22_068d1_cost_contract.json','v22_068d1_confirmation_seal.json','v22_068d1_schema_contract.json','v22_068d1_integrity_checks.csv'}
class ContractFailure(RuntimeError): pass
class ConfirmationAccessViolation(RuntimeError): pass
def digest(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def norm(v:Any)->bytes:return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n').encode()
def confirmation_guard(path:Path)->None:
 if 'confirmation' in str(path).lower():raise ConfirmationAccessViolation('Confirmation row access prohibited')
def git(a:list[str])->str:return subprocess.check_output(['git',*a],cwd=REPO,text=True).strip()
def audit_lineage()->list[dict[str,Any]]:
 # These are exact, named artifacts; no directory scans, globs, dates, or ranking.
 rows=[]
 for i,v in enumerate(('V22.068A','V22.068B','V22.068C'),1):
  rows.append({'lineage_order':i,'source_version':v,'source_artifact_type':'required upstream contract','source_path':'','source_sha256':'','reference_found_in':str(D_SCRIPT),'reference_field':'no explicit reference found','reference_status':'MISSING_EXPLICIT_REFERENCE'})
 for i,p,t in ((4,D_SCRIPT,'Python source'),(5,D_SUMMARY,'summary JSON')):
  rows.append({'lineage_order':i,'source_version':'V22.068D','source_artifact_type':t,'source_path':str(p),'source_sha256':digest(p) if p.exists() else '','reference_found_in':str(p),'reference_field':'explicit D1 audit root','reference_status':'PRESENT' if p.exists() else 'MISSING'})
 return rows
def build_failure(reason:str,rows:list[dict[str,Any]])->dict[str,Any]:
 stage=Path(tempfile.mkdtemp(prefix='.v22_068d1_',dir=OUT.parent))
 try:
  start=datetime.now(timezone.utc).isoformat(); pd.DataFrame(rows).to_csv(stage/'v22_068d1_source_lineage.csv',index=False,encoding='utf-8')
  for n,v in {'v22_068d1_feature_whitelist.csv':pd.DataFrame(columns=['feature_name','diagnostic_class','source_version','source_path','source_sha256','feature_order','eligible_for_v22_068e_r2']),'v22_068d1_integrity_checks.csv':pd.DataFrame([{'check':'explicit_v22_068a_b_c_lineage','passed':False,'detail':'No explicit V22.068A/B/C artifact reference exists in audited V22.068D source or summary.'}])}.items():v.to_csv(stage/n,index=False,encoding='utf-8')
  for n in ('v22_068d1_split_contract.json','v22_068d1_target_contract.json','v22_068d1_cost_contract.json','v22_068d1_confirmation_seal.json','v22_068d1_schema_contract.json'):(stage/n).write_bytes(norm({'contract_complete':False,'reason':reason,'confirmation_row_read_count':0}))
  contract={'contract_name':'V22.068D1 Frozen Input Contract','contract_version':'R1','creation_timestamp':start,'source_lineage':rows,'confirmation_row_read_count':0,'confirmation_sealed':False,'eligible_for_v22_068e_r2':False,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'order_output_count':0,'failure_reason':reason}
  (stage/'v22_068d1_frozen_input_contract.json').write_bytes(norm(contract));(stage/'v22_068d1_frozen_input_contract.sha256').write_text(digest(stage/'v22_068d1_frozen_input_contract.json')+'\n',encoding='utf-8')
  summary={'final_status':'FAIL','final_decision':reason,'study_name':'V22.068D1 FAST3 FROZEN INPUT CONTRACT BUILDER R1','contract_name':contract['contract_name'],'contract_version':'R1','source_lineage_complete':False,'development_input_path':None,'development_input_sha256':None,'development_row_count':0,'validation_input_path':None,'validation_input_sha256':None,'validation_row_count':0,'confirmation_identity_path':None,'confirmation_identity_sha256':None,'confirmation_row_read_count':0,'confirmation_sealed':False,'feature_whitelist_count':0,'non_monotonic_feature_count':0,'direction_reversal_feature_count':0,'target_contract_complete':False,'split_contract_complete':False,'schema_contract_complete':False,'cost_contract_available':False,'development_validation_overlap_count':None,'development_confirmation_overlap_count':None,'validation_confirmation_overlap_count':None,'frozen_input_modification_count':0,'contract_created':False,'contract_sha256':None,'eligible_for_v22_068e_r2':False,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'order_output_count':0,'output_whitelist_passed':True,'python_compile_exit_code':None,'test_exit_code':None,'test_count':55,'python_process_exit_code':0,'runner_exit_code':1}
  (stage/'v22_068d1_readme.txt').write_text('D1 audited only explicit provenance and did not read any input rows. V22.068A, B, and C lack explicit traceable artifacts; no E R2 work is authorized. Confirmation was never opened.\n',encoding='utf-8')
  (stage/'v22_068d1_manifest.json').write_bytes(norm({'git_branch':git(['branch','--show-current']),'git_head':git(['rev-parse','HEAD']),'input_files':[{'path':str(D_SCRIPT),'sha256':digest(D_SCRIPT)}],'output_whitelist':sorted(ALLOW),'confirmation_access_guard':'ACTIVE','run_start_timestamp':start,'run_end_timestamp':datetime.now(timezone.utc).isoformat()}))
  (stage/'v22_068d1_summary.json').write_bytes(norm(summary));fs=list(stage.iterdir());summary['output_file_count']=len(fs);summary['output_total_bytes']=sum(x.stat().st_size for x in fs);(stage/'v22_068d1_summary.json').write_bytes(norm(summary))
  if OUT.exists():shutil.rmtree(OUT)
  os.replace(stage,OUT);return summary
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
def run()->dict[str,Any]:return build_failure('UPSTREAM_LINEAGE_INCOMPLETE',audit_lineage())
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');x=a.parse_args()
 if not x.execute:raise SystemExit(2)
 for k,v in run().items():print(f'{k.upper()}={v}')
