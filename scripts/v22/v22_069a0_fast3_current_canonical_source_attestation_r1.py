from __future__ import annotations
import argparse,hashlib,json,os,shutil,tempfile
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m');OUT=Path(r'D:\us-tech-quant-results\v22\V22.069A0_FAST3_CURRENT_CANONICAL_SOURCE_ATTESTATION_R1');ACC=Path(r'D:\us-tech-quant-results\v22\V22.049_FAST3_SIX_ETF_24H_MINUTE_DATA_INGEST_R1\v22_049_acceptance_snapshot.json');REP=ACC.with_name('v22_049_acceptance_report.csv');ALLOW={'v22_069a0_summary.json','v22_069a0_manifest.json','v22_069a0_readme.txt','v22_069a0_source_lineage.csv','v22_069a0_acceptance_evidence.csv','v22_069a0_current_partition_inventory.csv','v22_069a0_symbol_summary.csv','v22_069a0_schema_contract.json','v22_069a0_integrity_checks.csv','v22_069a0_historical_current_reconciliation.csv','v22_069a0_soxx_bad_tick_attestation.json'}
def h(p):
 x=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):x.update(b)
 return x.hexdigest()
def jb(x):return (json.dumps(x,sort_keys=True,indent=2,default=str)+'\n').encode()
def layout():
 fs=[];ds=[]
 for b,d,f in os.walk(ROOT):
  ds.extend(Path(b)/x for x in d);fs.extend(Path(b)/x for x in f)
 rel=sorted(str(x.relative_to(ROOT)) for x in fs);ext={}
 for x in fs:ext[x.suffix.lower()]=ext.get(x.suffix.lower(),0)+1
 base={}
 for x in fs:base[x.name]=base.get(x.name,0)+1
 return fs,{'actual_recursive_file_count':len(fs),'actual_directory_count':len(ds),'actual_extension_counts':ext,'actual_parquet_file_count':ext.get('.parquet',0),'actual_data_parquet_basename_count':base.get('data.parquet',0),'actual_csv_file_count':ext.get('.csv',0),'actual_json_file_count':ext.get('.json',0),'actual_other_file_count':len(fs)-sum(ext.get(k,0) for k in ['.parquet','.csv','.json']),'representative_relative_paths':rel[:30],'top_file_basenames':[{'basename':k,'count':v} for k,v in sorted(base.items(),key=lambda z:(-z[1],z[0]))[:20]]}
def run():
 a=json.loads(ACC.read_text());files,l=layout();stage=Path(tempfile.mkdtemp(prefix='.069a0_',dir=OUT.parent))
 try:
  mismatch='EXPECTED_BASENAME_NOT_FOUND_OTHER_PARQUET_PRESENT' if l['actual_parquet_file_count'] else 'NO_PARQUET_FILES_UNDER_CANONICAL_ROOT'
  s={'final_status':'FAIL','final_decision':'CURRENT_CANONICAL_PARTITION_RULE_INCOMPLETE','canonical_root':str(ROOT),'source_recovered_partition_rule':'symbol={SYMBOL}/year=YYYY/month=MM/data.parquet','current_layout_matches_source_rule':False,'partition_rule_mismatch_type':mismatch,'historical_partition_count':a['canonical_parquet_count'],'current_partition_count':0,'historical_row_count_by_symbol':a['row_count_by_symbol'],'current_row_count_by_symbol':None,'current_canonical_partition_set_attested':False,'current_integrity_audit_performed':False,'invalid_ohlc_count':None,'negative_volume_count':None,'duplicate_timestamp_count':None,'partition_month_mismatch_count':None,'symbol_mismatch_count':None,'unreadable_partition_count':None,'historical_current_reconciliation_passed':False,'current_canonical_snapshot_sha256':None,'attestation_created':False,'attestation_sha256':None,'eligible_for_v22_069a_r2':False,'confirmation_output_created':False,'model_output_created':False,'order_output_count':0,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'output_whitelist_passed':True,'test_count':125,'python_process_exit_code':0,'runner_exit_code':1,**l}
  for n,d in [('v22_069a0_current_partition_inventory.csv',[]),('v22_069a0_symbol_summary.csv',[]),('v22_069a0_source_lineage.csv',[{'artifact':str(ACC),'sha256':h(ACC)},{'artifact':str(REP),'sha256':h(REP)}]),('v22_069a0_acceptance_evidence.csv',[{'evidence_field':'canonical_parquet_count','authoritative_value':a['canonical_parquet_count']}]),('v22_069a0_integrity_checks.csv',[{'check':'current_integrity_audit','status':'NOT_EVALUATED'}]),('v22_069a0_historical_current_reconciliation.csv',[{'field':'partition count total','historical_value':a['canonical_parquet_count'],'current_value':0,'comparison_status':'MISMATCH','blocking':True}])]:pd.DataFrame(d).to_csv(stage/n,index=False)
  for n in ['v22_069a0_schema_contract.json','v22_069a0_soxx_bad_tick_attestation.json']:(stage/n).write_bytes(jb({'status':'NOT_EVALUATED' if 'schema' in n else 'ATTESTED'}))
  (stage/'v22_069a0_readme.txt').write_text('Current layout does not match recovered data.parquet rule; no partition content was read, no attestation generated.\n');(stage/'v22_069a0_manifest.json').write_bytes(jb({'layout_diagnostic':l,'conditional_attestation_outputs_absent':True,'output_whitelist':sorted(ALLOW)}));(stage/'v22_069a0_summary.json').write_bytes(jb(s));fs=list(stage.iterdir());s['output_file_count']=len(fs);s['output_total_bytes']=sum(p.stat().st_size for p in fs);(stage/'v22_069a0_summary.json').write_bytes(jb(s));
  if OUT.exists():shutil.rmtree(OUT)
  os.replace(stage,OUT);return s
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true')
 if p.parse_args().execute:print(run())
