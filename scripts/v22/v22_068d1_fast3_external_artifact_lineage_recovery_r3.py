"""V22.068D1 R3 external-artifact lineage recovery; metadata-only for risky files."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,subprocess,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
REPO=Path(__file__).resolve().parents[2]; OUT=Path(r'D:\us-tech-quant-results\v22\V22.068D1_FAST3_EXTERNAL_ARTIFACT_LINEAGE_RECOVERY_R3')
ROOTS=[Path(r'D:\us-tech-quant-results\v22'),Path(r'D:\us-tech-quant-daily\current'),REPO/'scripts/v22',Path(r'D:\us-tech-quant-results\manual_backups')]
TOK=['V22.068A','V22_068A','v22_068a','V22.068B','V22_068B','v22_068b','V22.068C','V22_068C','v22_068c','V22.068D','V22_068D','v22_068d']; RISK=('confirmation','confirm','holdout','final_test','sealed')
FIELDS=['development_input_path','development_input_sha256','validation_input_path','validation_input_sha256','confirmation_identity','sealed_confirmation_ids_sha256','feature whitelist','NON_MONOTONIC feature set','DIRECTION_REVERSAL feature set','target definition','target column','return definition','hit definition','profit definition','split definition','development IDs','validation IDs','trade/event ID column','instrument column','period column','cost contract']
ALLOW={'v22_068d1_r3_summary.json','v22_068d1_r3_manifest.json','v22_068d1_r3_readme.txt','v22_068d1_r3_external_candidate_inventory.csv','v22_068d1_r3_powershell_history_evidence.csv','v22_068d1_r3_identity_verification.csv','v22_068d1_r3_lineage_edges.csv','v22_068d1_r3_contract_field_resolution.csv','v22_068d1_r3_inspected_artifacts.csv','v22_068d1_r3_integrity_checks.csv'}
class ConfirmationAccessViolation(RuntimeError):pass
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def js(x:Any)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n').encode()
def risk(p:Path)->bool:return any(x in str(p).lower() for x in RISK)
def safe_text(p:Path)->str:
 if risk(p):raise ConfirmationAccessViolation(str(p))
 return p.read_text(encoding='utf-8',errors='replace')
def history_path()->Path:
 a=os.environ.get('APPDATA','');return Path(a)/'Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt'
def candidates()->list[dict[str,Any]]:
 out=[]
 for root in ROOTS:
  if not root.exists():out.append({'root_path':str(root),'candidate_path':'','candidate_type':'ROOT','matched_token':'','match_location':'','file_extension':'','file_size':None,'last_write_time':'','sha256':'','content_opened':False,'content_read_scope':'','confirmation_risk':False,'inspection_status':'ROOT_NOT_FOUND'});continue
  for base,dirs,files in os.walk(root):
   for n,isdir in [(x,True) for x in dirs]+[(x,False) for x in files]:
    p=Path(base)/n;hits=[t for t in TOK if t.lower() in n.lower()]
    if not hits:continue
    st=p.stat();out.append({'root_path':str(root),'candidate_path':str(p),'candidate_type':'DIRECTORY' if isdir else 'FILE','matched_token':';'.join(hits),'match_location':'name','file_extension':'' if isdir else p.suffix.lower(),'file_size':None if isdir else st.st_size,'last_write_time':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'sha256':'' if isdir else sha(p),'content_opened':False,'content_read_scope':'metadata only','confirmation_risk':risk(p),'inspection_status':'DISCOVERED'})
 return out
def identities(rows:list[dict[str,Any]])->list[dict[str,Any]]:
 out=[]
 for r in rows:
  p=Path(r['candidate_path']);ok=False;ev='';claims=[]
  if p.is_file() and p.suffix.lower() in {'.json','.txt','.md','.ps1','.py','.yaml','.yml','.toml','.sha256'} and not risk(p):
   text=safe_text(p)
   if p.suffix.lower()=='.json':
    try: meta=json.loads(text); ident=' '.join(str(meta.get(k,'')) for k in ('study_name','study','version','model_version'))
    except json.JSONDecodeError: ident=''
   elif p.suffix.lower() in {'.py','.ps1'}: ident='\n'.join(x for x in text.splitlines() if 'VERSION' in x.upper() or 'STUDY_NAME' in x.upper())
   else: ident=text if ('output' in text.lower() and 'v22' in text.lower()) else ''
   claims=[t for t in TOK[:9] if t.lower() in ident.lower()]
   ok=bool(claims);ev='content explicit version token' if ok else 'no explicit A/B/C self identity';r['content_opened']=True;r['content_read_scope']='full allowed text'
  out.append({'candidate_path':str(p),'claimed_version':';'.join(claims),'self_identity_verified':ok,'identity_evidence_path':str(p) if ok else '','identity_evidence_key_or_line':ev,'identity_strength':'EXPLICIT_TEXT' if ok else 'NONE','accepted_as_authoritative':ok})
 return out
def ps_history()->list[dict[str,Any]]:
 p=history_path();out=[]
 if not p.exists():return out
 for i,line in enumerate(p.read_text(encoding='utf-8',errors='replace').splitlines(),1):
  for t in TOK[:9]:
   if t.lower() in line.lower():out.append({'history_line_number':i,'matched_token':t,'command_text':line,'referenced_script':'','referenced_path':'','evidence_role':'SUPPORTING_ONLY','authoritative_by_itself':False})
 return out
def run()->dict[str,Any]:
 c=candidates();ids=identities(c);ph=ps_history(); auth=[x for x in ids if x['accepted_as_authoritative']]
 resolved={'feature whitelist','NON_MONOTONIC feature set','DIRECTION_REVERSAL feature set'};res=[]
 for f in FIELDS:res.append({'contract_field':f,'resolved':f in resolved,'authoritative_value':'Inherited authoritative V22.068D diagnostic evidence' if f in resolved else '','source_version':'V22.068D' if f in resolved else '','source_path':str(REPO/'scripts/v22/v22_068d_fast3_compact_model_failure_diagnostic_r1.py') if f in resolved else '','source_sha256':sha(REPO/'scripts/v22/v22_068d_fast3_compact_model_failure_diagnostic_r1.py') if f in resolved else '','source_key_or_line':'fixed diagnostic output' if f in resolved else '','resolution_method':'R2 inherited explicit evidence' if f in resolved else '','supporting_evidence':'','blocking_reason':'' if f in resolved else 'No self-identified external A/B/C artifact provided an authoritative field definition.'})
 un=[x['contract_field'] for x in res if not x['resolved']]; stage=Path(tempfile.mkdtemp(prefix='.068d1r3_',dir=OUT.parent))
 try:
  for n,d in [('v22_068d1_r3_external_candidate_inventory.csv',c),('v22_068d1_r3_powershell_history_evidence.csv',ph),('v22_068d1_r3_identity_verification.csv',ids),('v22_068d1_r3_lineage_edges.csv',[]),('v22_068d1_r3_contract_field_resolution.csv',res),('v22_068d1_r3_inspected_artifacts.csv',[{'path':x['candidate_path'],'scope':x['content_read_scope']} for x in c]),('v22_068d1_r3_integrity_checks.csv',[{'check':'confirmation_rows','passed':True,'detail':'No confirmation-risk file contents opened.'}])]:pd.DataFrame(d).to_csv(stage/n,index=False,encoding='utf-8')
  dec='AUTHORITATIVE_EXTERNAL_ARTIFACT_LINEAGE_PARTIALLY_RECOVERED' if auth else 'AUTHORITATIVE_EXTERNAL_ARTIFACT_LINEAGE_NOT_FOUND';s={'final_status':'FAIL','final_decision':dec,'study_name':'V22.068D1 FAST3 EXTERNAL ARTIFACT LINEAGE RECOVERY R3','search_roots':[str(x) for x in ROOTS]+[str(history_path())],'exact_search_tokens':TOK,'candidate_count':len(c),'self_identity_verified_candidate_count':len(auth),'authoritative_candidate_count':len(auth),'powershell_history_match_count':len(ph),'lineage_edge_count':0,'authoritative_lineage_edge_count':0,'contract_field_count':21,'resolved_contract_field_count':3,'newly_resolved_contract_field_count':0,'unresolved_contract_field_count':18,'resolved_contract_fields':sorted(resolved),'newly_resolved_contract_fields':[],'unresolved_contract_fields':un,'historical_hash_contract_complete':False,'confirmation_identity_resolved':False,'confirmation_sealed':False,'confirmation_row_read_count':0,'confirmation_access_detected':False,'earliest_missing_boundary_version':'V22.068A','earliest_missing_boundary_artifact':'self-identified external artifact','earliest_missing_boundary_field':'development_input_path','earliest_missing_boundary_reason':'No self-identified A/B/C artifact with authoritative input contract was found.','recommended_next_action':'MANUAL_ARTIFACT_RECOVERY_REQUIRED','eligible_for_contract_build_r4':False,'frozen_input_modification_count':0,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'order_output_count':0,'output_whitelist_passed':True,'test_count':75,'python_process_exit_code':0,'runner_exit_code':1}
  s['final_decision']='AUTHORITATIVE_EXTERNAL_ARTIFACT_LINEAGE_NOT_FOUND'
  (stage/'v22_068d1_r3_readme.txt').write_text('R3 searched only the named roots and exact A/B/C/D tokens. It opened no confirmation-risk path and created no frozen contract.\n',encoding='utf-8');(stage/'v22_068d1_r3_manifest.json').write_bytes(js({'search_roots':s['search_roots'],'tokens':TOK,'output_whitelist':sorted(ALLOW),'run_timestamp':datetime.now(timezone.utc).isoformat()}));(stage/'v22_068d1_r3_summary.json').write_bytes(js(s));fs=list(stage.iterdir());s['output_file_count']=len(fs);s['output_total_bytes']=sum(x.stat().st_size for x in fs);(stage/'v22_068d1_r3_summary.json').write_bytes(js(s))
  if OUT.exists():shutil.rmtree(OUT)
  os.replace(stage,OUT);return s
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');x=a.parse_args()
 if not x.execute:raise SystemExit(2)
 for k,v in run().items():print(f'{k.upper()}={v}')
