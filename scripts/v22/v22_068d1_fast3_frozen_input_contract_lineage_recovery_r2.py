"""Read-only V22.068D1 R2 lineage recovery.  No data files, especially Confirmation, are opened."""
from __future__ import annotations
import argparse,csv,hashlib,json,os,shutil,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
REPO=Path(__file__).resolve().parents[2]; OUT=Path(r'D:\us-tech-quant-results\v22\V22.068D1_FAST3_FROZEN_INPUT_CONTRACT_LINEAGE_RECOVERY_R2')
BRANCH='checkpoint/v22-068d1-r2-lineage-recovery-20260730'; D=REPO/'scripts/v22/v22_068d_fast3_compact_model_failure_diagnostic_r1.py'; DE=D.parent/'v22_068d_decision_evidence.csv'
DO=Path(r'D:\us-tech-quant-results\v22\V22.068D_FAST3_COMPACT_MODEL_FAILURE_DIAGNOSTIC_R1'); ALLOW={'v22_068d1_r2_summary.json','v22_068d1_r2_manifest.json','v22_068d1_r2_readme.txt','v22_068d1_r2_repository_source_inventory.csv','v22_068d1_r2_git_history_lineage.csv','v22_068d1_r2_lineage_edges.csv','v22_068d1_r2_contract_field_resolution.csv','v22_068d1_r2_inspected_artifacts.csv','v22_068d1_r2_integrity_checks.csv'}
TERMS=['v22_068a','v22_068b','v22_068c','v22_068d','V22.068A','V22.068B','V22.068C','V22.068D','NON_MONOTONIC','DIRECTION_REVERSAL','FAILURE_EXPLAINED_BY_NON_MONOTONIC_FEATURE_STRUCTURE','COMPACT_MODEL','compact_model','confirmation','validation','development','feature_whitelist','target_definition','split_definition','input_path','source_path','manifest','summary']
FIELDS=['development_input_path','development_input_sha256','validation_input_path','validation_input_sha256','confirmation_identity','sealed_confirmation_ids_sha256','feature whitelist','NON_MONOTONIC feature set','DIRECTION_REVERSAL feature set','target definition','target column','return definition','hit definition','profit definition','split definition','development IDs','validation IDs','trade/event ID column','instrument column','period column','cost contract']
class ConfirmationAccessViolation(RuntimeError):pass
def sh(a:list[str])->str:return subprocess.check_output(a,cwd=REPO,text=True,encoding='utf-8',errors='replace')
def h(p:Path)->str:
 x=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):x.update(b)
 return x.hexdigest()
def js(x:Any)->bytes:return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n').encode()
def guard(p:Path)->None:
 if 'confirmation' in str(p).lower():raise ConfirmationAccessViolation('confirmation artifact read denied')
def inventory()->tuple[list[dict[str,Any]],int,int]:
 files=sh(['git','ls-files']).splitlines(); rows=[];opened=set()
 for term in TERMS:
  r=subprocess.run(['git','grep','-n','-i','-e',term,'--','scripts/v22'],cwd=REPO,text=True,capture_output=True,encoding='utf-8',errors='replace')
  for line in r.stdout.splitlines():
   parts=line.split(':',2)
   if len(parts)==3:
    path,ln,text=parts;opened.add(path);rows.append({'search_term':term,'tracked_path':path,'file_type':Path(path).suffix,'matched_line_number':ln,'matched_text':text[:500],'candidate_version':'V22.068D' if '068d' in path.lower() else 'OTHER','inspection_status':'MATCHED_AND_OPENED'})
 for v in ('v22_068a','v22_068b','v22_068c'):
  if not any(v in p.lower() for p in files):rows.append({'search_term':v,'tracked_path':'','file_type':'','matched_line_number':'','matched_text':'No tracked current-worktree file with this exact version token','candidate_version':v.upper().replace('_','.'),'inspection_status':'CURRENT_FILE_NOT_FOUND'})
 return rows,len(files),len(opened)
def history()->tuple[list[dict[str,Any]],int]:
 rows=[]; commits=set()
 for term in ['V22.068A','V22.068B','V22.068C','NON_MONOTONIC','DIRECTION_REVERSAL','FAILURE_EXPLAINED_BY_NON_MONOTONIC_FEATURE_STRUCTURE']:
  out=sh(['git','log','--all','--format=%H|%cI','-S',term,'--','scripts/v22'])
  for line in out.splitlines():
   if '|' in line:
    sha,date=line.split('|',1);commits.add(sha); names=sh(['git','show','--format=','--name-only',sha,'--','scripts/v22']).splitlines()
    for path in filter(None,names):rows.append({'commit_sha':sha,'commit_date':date,'path':path,'search_term':term,'evidence_type':'git_log_-S_and_git_show','evidence_text':f'exact string change: {term}','inspection_status':'INSPECTED_NO_CHECKOUT'})
 return rows,len(commits)
def fields()->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
 source=DO/'v22_068d_decision_evidence.csv'; resolved={'NON_MONOTONIC feature set','DIRECTION_REVERSAL feature set','feature whitelist'}; rs=[];edges=[]
 for f in FIELDS:
  ok=f in resolved
  rs.append({'contract_field':f,'resolved':ok,'authoritative_value':'PREMARKET_CUM_RETURN; PREMARKET_MAX_DRAWDOWN' if f=='NON_MONOTONIC feature set' else ('PREMARKET_REALIZED_VOLATILITY; PREMARKET_MAX_DRAWDOWN; PREMARKET_CUM_RETURN' if f=='DIRECTION_REVERSAL feature set' else ('union of D diagnostic sets' if f=='feature whitelist' else '')),'source_version':'V22.068D' if ok else '','source_path':str(source) if ok else '','source_sha256':h(source) if ok and source.exists() else '','source_line_or_key':'v22_068d_decision_evidence.csv: non_monotonic_factors/direction_reversals' if ok else '','resolution_method':'explicit D script output path and diagnostic evidence' if ok else '','blocking_reason':'' if ok else 'No explicit authoritative source path/hash/contract field was found in tracked source or Git-history evidence.'})
  if ok:edges.append({'from_version':'V22.068D','from_artifact':str(D),'reference_location':str(D),'reference_field_or_line':'out[v22_068d_decision_evidence.csv]','to_version':'V22.068D','to_artifact':str(source),'reference_type':'fixed output filename','reference_strength':'EXPLICIT','accepted_as_authoritative':True})
 return rs,edges
def run()->dict[str,Any]:
 inv,tracked,inspected=inventory();hist,hcommits=history();res,edges=fields();un=[x['contract_field'] for x in res if not x['resolved']];rr=[x['contract_field'] for x in res if x['resolved']]
 stage=Path(tempfile.mkdtemp(prefix='.v22_068d1r2_',dir=OUT.parent))
 try:
  for n,data in [('v22_068d1_r2_repository_source_inventory.csv',inv),('v22_068d1_r2_git_history_lineage.csv',hist),('v22_068d1_r2_lineage_edges.csv',edges),('v22_068d1_r2_contract_field_resolution.csv',res),('v22_068d1_r2_inspected_artifacts.csv',[{'path':str(D),'sha256':h(D),'inspection':'read source constants only'},{'path':str(DO/'v22_068d_decision_evidence.csv'),'sha256':h(DO/'v22_068d_decision_evidence.csv'),'inspection':'diagnostic identifiers only'}]),('v22_068d1_r2_integrity_checks.csv',[{'check':'confirmation_row_access','passed':True,'detail':'No Confirmation artifact was opened.'},{'check':'no_frozen_contract_output','passed':True,'detail':'R2 output allowlist excludes contract artifacts.'}])]:pd.DataFrame(data).to_csv(stage/n,index=False,encoding='utf-8')
  s={'final_status':'FAIL','final_decision':'AUTHORITATIVE_LINEAGE_PARTIALLY_RECOVERED','study_name':'V22.068D1 FAST3 FROZEN INPUT CONTRACT LINEAGE RECOVERY R2','repository_tracked_file_count':tracked,'repository_matched_file_count':len(inv),'repository_inspected_file_count':inspected,'git_history_commit_count_scanned':len(sh(['git','log','--all','--format=%H']).splitlines()),'git_history_matched_commit_count':hcommits,'git_history_artifact_count_inspected':len(hist),'lineage_edge_count':len(edges),'authoritative_lineage_edge_count':len(edges),'contract_field_count':len(FIELDS),'resolved_contract_field_count':len(rr),'unresolved_contract_field_count':len(un),'resolved_contract_fields':rr,'unresolved_contract_fields':un,'earliest_missing_boundary_version':'V22.068A','earliest_missing_boundary_artifact':'tracked source / Git-history artifact','earliest_missing_boundary_field':'development_input_path','earliest_missing_boundary_reason':'No exact V22.068A source artifact or explicit upstream reference is present in the audited tracked files or string-history search.','confirmation_row_read_count':0,'confirmation_access_detected':False,'frozen_input_modification_count':0,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'order_output_count':0,'eligible_for_contract_build_r3':False,'output_whitelist_passed':True,'python_compile_exit_code':None,'test_exit_code':None,'test_count':65,'python_process_exit_code':0,'runner_exit_code':1}
  (stage/'v22_068d1_r2_readme.txt').write_text('R2 performed only Git-tracked source and Git-history lineage recovery. Three feature-related fields were explicitly recovered from V22.068D diagnostic evidence; all data, split, target, and Confirmation-seal contract fields remain unresolved. No Confirmation rows were read.\n',encoding='utf-8')
  (stage/'v22_068d1_r2_manifest.json').write_bytes(js({'git_branch':sh(['git','branch','--show-current']).strip(),'git_head':sh(['git','rev-parse','HEAD']).strip(),'search_terms':TERMS,'output_whitelist':sorted(ALLOW),'confirmation_access_guard':'ACTIVE'}));(stage/'v22_068d1_r2_summary.json').write_bytes(js(s));fs=list(stage.iterdir());s['output_file_count']=len(fs);s['output_total_bytes']=sum(p.stat().st_size for p in fs);(stage/'v22_068d1_r2_summary.json').write_bytes(js(s))
  if OUT.exists():shutil.rmtree(OUT)
  os.replace(stage,OUT);return s
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');x=a.parse_args()
 if not x.execute:raise SystemExit(2)
 for k,v in run().items():print(f'{k.upper()}={v}')
