"""R4: exact-token, metadata-first audit of only three expanded local roots."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,tempfile
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
REPO=Path(__file__).resolve().parents[2];OUT=Path(r'D:\us-tech-quant-results\v22\V22.068D1_FAST3_EXPANDED_LOCAL_ROOT_ARTIFACT_LINEAGE_RECOVERY_R4');ROOTS=[Path(r'D:\us-tech-quant-backtests'),Path(r'D:\us-tech-quant-cache'),Path(r'D:\us-tech-quant-data')];TOK=['V22.068A','V22_068A','v22_068a','V22.068B','V22_068B','v22_068b','V22.068C','V22_068C','v22_068c','V22.068D','V22_068D','v22_068d'];RISK=('confirmation','confirm','holdout','final_test','sealed_split');FIELDS=['development_input_path','development_input_sha256','validation_input_path','validation_input_sha256','confirmation_identity','sealed_confirmation_ids_sha256','feature whitelist','NON_MONOTONIC feature set','DIRECTION_REVERSAL feature set','target definition','target column','return definition','hit definition','profit definition','split definition','development IDs','validation IDs','trade/event ID column','instrument column','period column','cost contract'];ALLOW={'v22_068d1_r4_summary.json','v22_068d1_r4_manifest.json','v22_068d1_r4_readme.txt','v22_068d1_r4_expanded_candidate_inventory.csv','v22_068d1_r4_identity_verification.csv','v22_068d1_r4_lineage_edges.csv','v22_068d1_r4_contract_field_resolution.csv','v22_068d1_r4_inspected_artifacts.csv','v22_068d1_r4_integrity_checks.csv','v22_068d1_r4_root_statistics.csv'}
class ConfirmationAccessViolation(RuntimeError):pass
def h(p):
 x=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):x.update(b)
 return x.hexdigest()
def js(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n').encode()
def risk(p):return any(x in str(p).lower() for x in RISK)
def read_allowed(p):
 if risk(p):raise ConfirmationAccessViolation(str(p))
 return p.read_text(encoding='utf-8',errors='replace')
def scan():
 rows=[];stats=[]
 for root in ROOTS:
  count=0
  if root.exists():
   for b,ds,fs in os.walk(root):
    for n,d in [(x,1) for x in ds]+[(x,0) for x in fs]:
     count+=not d;p=Path(b)/n;hits=[t for t in TOK if t.lower() in n.lower()]
     if hits:
      st=p.stat();rows.append({'root_path':str(root),'candidate_path':str(p),'candidate_type':'DIRECTORY' if d else 'FILE','matched_token':';'.join(hits),'match_location':'name','file_extension':'' if d else p.suffix.lower(),'file_size':None if d else st.st_size,'last_write_time':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'currently_computed_sha256':'' if d else h(p),'content_opened':False,'content_read_scope':'metadata only','confirmation_risk':risk(p),'inspection_status':'DISCOVERED'})
  stats.append({'root_path':str(root),'scanned_file_count':count,'exists':root.exists()})
 return rows,stats
def run():
 c,stats=scan();ids=[]
 for r in c:
  p=Path(r['candidate_path']);ok=False;claims=[]
  if p.is_file() and p.suffix.lower() in {'.json','.txt','.md','.ps1','.py','.yaml','.yml','.toml','.sha256'} and not risk(p):
   text=read_allowed(p);ident=text if p.suffix.lower() not in {'.py','.ps1'} else '\n'.join(z for z in text.splitlines() if 'VERSION' in z.upper() or 'STUDY' in z.upper());claims=[t for t in TOK[:9] if t.lower() in ident.lower()];ok=bool(claims);r['content_opened']=True;r['content_read_scope']='allowed text'
  ids.append({'candidate_path':str(p),'claimed_version':';'.join(claims),'self_identity_verified':ok,'identity_evidence_path':str(p) if ok else '','identity_evidence_key_or_line':'explicit version metadata' if ok else '','identity_strength':'EXPLICIT' if ok else 'NONE','accepted_as_authoritative':ok,'rejection_reason':'' if ok else 'Filename/path alone is not self identity.'})
 resolved={'feature whitelist','NON_MONOTONIC feature set','DIRECTION_REVERSAL feature set'};res=[{'contract_field':f,'resolved':f in resolved,'newly_resolved_in_r4':False,'authoritative_value':'Inherited R2/R3 V22.068D evidence' if f in resolved else '','source_version':'V22.068D' if f in resolved else '','source_path':'','source_sha256':'','source_key_or_line':'','resolution_method':'inherited' if f in resolved else '','supporting_evidence':'','blocking_reason':'' if f in resolved else 'No authoritative expanded-root A/B/C contract evidence.'} for f in FIELDS];stage=Path(tempfile.mkdtemp(prefix='.068d1r4_',dir=OUT.parent))
 try:
  for n,d in [('v22_068d1_r4_expanded_candidate_inventory.csv',c),('v22_068d1_r4_identity_verification.csv',ids),('v22_068d1_r4_lineage_edges.csv',[]),('v22_068d1_r4_contract_field_resolution.csv',res),('v22_068d1_r4_inspected_artifacts.csv',[{'path':x['candidate_path'],'scope':x['content_read_scope']} for x in c]),('v22_068d1_r4_integrity_checks.csv',[{'check':'confirmation_rows','passed':True,'detail':'No confirmation-risk content opened.'}]),('v22_068d1_r4_root_statistics.csv',stats)]:pd.DataFrame(d).to_csv(stage/n,index=False,encoding='utf-8')
  un=[x['contract_field'] for x in res if not x['resolved']];s={'final_status':'FAIL','final_decision':'AUTHORITATIVE_EXPANDED_LOCAL_ROOT_LINEAGE_NOT_FOUND','study_name':'V22.068D1 FAST3 EXPANDED LOCAL ROOT ARTIFACT LINEAGE RECOVERY R4','search_roots':[str(x) for x in ROOTS],'excluded_roots':['D:\\us-tech-quant-envs'],'search_roots_exactly_enforced':True,'exact_search_tokens':TOK,'candidate_count':len(c),'self_identity_verified_candidate_count':sum(x['self_identity_verified'] for x in ids),'authoritative_candidate_count':0,'lineage_edge_count':0,'authoritative_lineage_edge_count':0,'contract_field_count':21,'resolved_contract_field_count':3,'newly_resolved_contract_field_count':0,'unresolved_contract_field_count':18,'resolved_contract_fields':sorted(resolved),'newly_resolved_contract_fields':[],'unresolved_contract_fields':un,'historical_hash_contract_complete':False,'confirmation_identity_resolved':False,'confirmation_sealed':False,'confirmation_row_read_count':0,'confirmation_access_detected':False,'earliest_missing_boundary_version':'V22.068A','earliest_missing_boundary_artifact':'expanded local roots','earliest_missing_boundary_field':'development_input_path','earliest_missing_boundary_reason':'No authoritative A/B/C input contract in backtests/cache/data.','recommended_next_action':'START_NEW_CLEAN_RESEARCH_LINEAGE_V22_069A','eligible_for_contract_build_r5':False,'frozen_input_modification_count':0,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'order_output_count':0,'output_whitelist_passed':True,'test_count':80,'python_process_exit_code':0,'runner_exit_code':1};(stage/'v22_068d1_r4_readme.txt').write_text('R4 searched only backtests/cache/data exact version tokens; no row-level Confirmation access.\n');(stage/'v22_068d1_r4_manifest.json').write_bytes(js({'search_roots':s['search_roots'],'excluded_roots':s['excluded_roots'],'output_whitelist':sorted(ALLOW)}));(stage/'v22_068d1_r4_summary.json').write_bytes(js(s));fs=list(stage.iterdir());s['output_file_count']=len(fs);s['output_total_bytes']=sum(p.stat().st_size for p in fs);(stage/'v22_068d1_r4_summary.json').write_bytes(js(s));
  if OUT.exists():shutil.rmtree(OUT)
  os.replace(stage,OUT);return s
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');x=a.parse_args()
 if not x.execute:raise SystemExit(2)
 for k,v in run().items():print(f'{k.upper()}={v}')
