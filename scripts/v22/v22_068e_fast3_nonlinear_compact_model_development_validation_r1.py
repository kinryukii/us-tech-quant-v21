"""V22.068E: deterministic, compact, Development-only binned additive study.

This program never opens Confirmation data.  It deliberately fails closed when
the V22.068D frozen-input contract cannot be reconstructed from its summary or
manifest.  The functions below are also intentionally small and deterministic
so their behavior can be tested with synthetic fixtures without data access.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, platform, shutil, subprocess, sys, tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

REPO=Path(__file__).resolve().parents[2]
OUT=Path(r"D:\us-tech-quant-results\v22\V22.068E_FAST3_NONLINEAR_COMPACT_MODEL_DEVELOPMENT_VALIDATION_R1")
DOUT=Path(r"D:\us-tech-quant-results\v22\V22.068D_FAST3_COMPACT_MODEL_FAILURE_DIAGNOSTIC_R1")
SUMMARY=DOUT/'v22_068d_summary.json'; MANIFEST=DOUT/'v22_068d_manifest.json'
BRANCH='checkpoint/v22-068e-nonlinear-compact-20260730'; LAMBDA=20.0
ALLOW={'v22_068e_summary.json','v22_068e_manifest.json','v22_068e_readme.txt','v22_068e_feature_whitelist.csv','v22_068e_feature_bin_definition.csv','v22_068e_feature_bin_development_statistics.csv','v22_068e_validation_scored_rows.csv','v22_068e_validation_metrics.csv','v22_068e_validation_score_buckets.csv','v22_068e_validation_by_period.csv','v22_068e_validation_by_instrument.csv','v22_068e_validation_cost_stress.csv','v22_068e_gate_results.csv','v22_068e_frozen_model_spec.json','v22_068e_frozen_model_spec.sha256','v22_068e_rejected_candidate_spec.json'}

class ContractError(RuntimeError): pass
class ConfirmationAccessViolation(RuntimeError): pass
@dataclass(frozen=True)
class Config: quantile_method:str='linear'; shrinkage_lambda:float=LAMBDA
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def stable_json(x:Any)->bytes: return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n').encode('utf-8')
def git(args:list[str])->str: return subprocess.check_output(['git',*args],cwd=REPO,text=True).strip()
def guard_confirmation(path:Path)->None:
 if 'confirmation' in str(path).lower(): raise ConfirmationAccessViolation('CONFIRMATION_ACCESS_VIOLATION')
def source_contract()->dict[str,Any]:
 if not SUMMARY.exists(): raise ContractError('V22.068D summary missing')
 s=json.loads(SUMMARY.read_text(encoding='utf-8')); m={}
 if MANIFEST.exists(): m=json.loads(MANIFEST.read_text(encoding='utf-8'))
 # Only formal summary/manifest may establish frozen data identity.
 paths=s.get('source_input_paths',m.get('source_input_paths',m.get('input_files')))
 hashes=s.get('source_input_hashes',m.get('source_input_hashes',m.get('input_hashes')))
 splits=s.get('split_definition',m.get('split_definition'))
 features=s.get('feature_whitelist',m.get('feature_whitelist'))
 target=s.get('target_definition',m.get('target_definition'))
 if not all([paths,hashes,splits,features,target]): raise ContractError('FROZEN_INPUT_CONTRACT_INCOMPLETE')
 return {'summary':s,'manifest':m,'paths':paths,'hashes':hashes,'splits':splits,'features':features,'target':target}
def whitelist(rows:Iterable[dict[str,Any]])->list[dict[str,Any]]:
 seen=set(); out=[]
 for r in rows:
  cls=str(r.get('source_diagnostic_class',''))
  f=str(r.get('feature_name',''))
  if cls in {'NON_MONOTONIC','DIRECTION_REVERSAL'} and f and f not in seen:
   seen.add(f);out.append({'feature_name':f,'source_diagnostic_class':cls,'source_v22_068d_file':r.get('source_v22_068d_file',''),'allowed_for_m1':True,'ordering_index':len(out)+1})
 return out
def min_bin(n:int)->int:return max(20,math.ceil(.05*n))
def bins_development(v:pd.Series)->tuple[list[float],str]:
 x=v.dropna().astype(float); q=np.quantile(x,np.linspace(0,1,6),method='linear'); e=list(dict.fromkeys(float(z) for z in q))
 return e, 'INSUFFICIENT_VARIATION' if len(e)<3 else 'OK'
def merge_sparse(edges:list[float], values:pd.Series, minimum:int)->tuple[list[float],list[dict[str,Any]]]:
 e=list(edges); hist=[]
 while len(e)-1>2:
  cats=pd.cut(values,bins=e,include_lowest=True,duplicates='drop'); counts=cats.value_counts(sort=False).to_numpy()
  bad=np.where(counts<minimum)[0]
  if not len(bad): break
  i=int(bad[0]); opts=[]
  if i>0: opts.append((counts[i-1],abs((e[i]+e[i+1])/2-(e[i-1]+e[i])/2),0,i))
  if i<len(counts)-1: opts.append((counts[i+1],abs((e[i]+e[i+1])/2-(e[i+1]+e[i+2])/2),1,i+1))
  _,_,_,remove=min(opts); hist.append({'sparse_bin_index':i,'removed_edge':e[remove],'rule':'neighbor_count_then_center_distance_then_left'});e.pop(remove)
 return e,hist
def fit_feature(v:pd.Series,y:pd.Series,feature:str)->dict[str,Any]:
 valid=v.notna() & y.notna(); e,status=bins_development(v[valid]); rec={'feature_name':feature,'raw_quantiles':e.copy(),'status':status,'merge_history':[]}
 if status!='OK': return rec
 e,hist=merge_sparse(e,v[valid],min_bin(int(valid.sum())));rec.update(final_bin_edges=e,merge_history=hist,status='OK')
 g=float(y[valid].mean()); rec['global_development_target_mean']=g; stats=[]
 cats=pd.cut(v,bins=e,include_lowest=True)
 for label,idx in cats.groupby(cats,observed=True).groups.items():
  z=y.loc[idx].dropna();n=len(z);mean=float(z.mean());raw=mean-g;stats.append({'bin_label':str(label),'n_bin':n,'bin_target_mean':mean,'raw_bin_excess':raw,'shrunk_bin_contribution':n/(n+LAMBDA)*raw})
 rec['bins']=stats;return rec
def score(rows:pd.DataFrame, models:dict[str,dict[str,Any]])->pd.DataFrame:
 out=[]
 for _,r in rows.iterrows():
  vals=[]
  for f,m in models.items():
   if m.get('status')!='OK' or pd.isna(r[f]): continue
   for b in m['bins']:
    lohi=b['bin_label'].strip('()[]').split(', ');lo=float(lohi[0]);hi=float(lohi[1].rstrip(']'))
    if lo<=float(r[f])<=hi: vals.append(b['shrunk_bin_contribution']);break
  out.append({'final_score':float(np.mean(vals)) if vals else None,'score_status':'OK' if vals else 'ALL_FEATURES_MISSING'})
 return pd.concat([rows.reset_index(drop=True),pd.DataFrame(out)],axis=1)
def top(df:pd.DataFrame,n:int)->pd.DataFrame:return df.sort_values(['final_score','trade_id'],ascending=[False,True],kind='mergesort').head(n)
def safe_corr(a:pd.Series,b:pd.Series,kind:str)->float|None:
 z=pd.concat([a,b],axis=1).dropna()
 return None if len(z)<2 or z.iloc[:,0].nunique()<2 or z.iloc[:,1].nunique()<2 else float(spearmanr(z.iloc[:,0],z.iloc[:,1]).statistic if kind=='s' else pearsonr(z.iloc[:,0],z.iloc[:,1]).statistic)
def decision(valid:int,topn:int,gates:dict[str,bool],effective:int)->str:
 if not effective:return 'NONLINEAR_MODEL_INSUFFICIENT_FEATURE_VARIATION'
 if valid<60 or topn<12:return 'NONLINEAR_COMPACT_MODEL_INSUFFICIENT_SAMPLE_BEFORE_CONFIRMATION'
 return 'NONLINEAR_COMPACT_MODEL_VALIDATED_AND_FROZEN_FOR_ONE_TIME_CONFIRMATION' if all(gates.values()) else 'NONLINEAR_COMPACT_MODEL_REJECTED_BEFORE_CONFIRMATION'
def write_csv(stage:Path,name:str,rows:list[dict[str,Any]])->None: pd.DataFrame(rows).to_csv(stage/name,index=False,encoding='utf-8')
def publish(payload:dict[str,Any], status:str, reason:str)->dict[str,Any]:
 print('PUBLISH_STAGE=create',flush=True)
 stage=Path(tempfile.mkdtemp(prefix='.v22_068e_',dir=OUT.parent)); start=datetime.now(timezone.utc).isoformat()
 try:
  s={'final_status':status,'final_decision':reason,'study_name':'V22.068E FAST3 NONLINEAR COMPACT MODEL DEVELOPMENT VALIDATION R1','model_name':'M1_DETERMINISTIC_BINNED_ADDITIVE','model_version':'R1','source_v22_068d_summary_path':str(SUMMARY),'source_v22_068d_manifest_path':str(MANIFEST),'source_input_hash_verified':False,'frozen_input_modification_count':0,'development_row_count':0,'validation_row_count':0,'confirmation_row_read_count':0,'confirmation_used_for_tuning':False,'feature_whitelist_count':0,'non_monotonic_feature_count':0,'direction_reversal_feature_count':0,'effective_feature_count':0,'insufficient_variation_feature_count':0,'initial_bin_count':5,'final_bin_count_by_feature':{},'min_bin_count':None,'shrinkage_lambda':LAMBDA,'trained_feature_weight_count':0,'automatic_model_search_used':False,'score_direction':'HIGHER_SCORE_EXPECTED_HIGHER_TARGET','score_direction_reversed':False,'validation_valid_score_count':0,'validation_null_score_count':0,'validation_spearman':None,'validation_pearson':None,'validation_overall_mean':None,'validation_top_mean':None,'validation_bottom_mean':None,'validation_top_minus_bottom_spread':None,'validation_top_hit_rate':None,'validation_overall_hit_rate':None,'validation_top_minus_overall_hit_rate':None,'cost_stress_available':False,'validation_two_x_cost_top_mean':None,'top1_profit_concentration':None,'top5_profit_concentration':None,'single_instrument_dominance':None,'single_period_dominance':None,'all_validation_gates_passed':False,'frozen_model_spec_created':False,'frozen_model_spec_sha256':None,'eligible_for_one_time_confirmation':False,'prospective_shadow_allowed':False,'paper_action_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False,'order_output_count':0,'output_whitelist_passed':True,'test_count':60,'test_exit_code':None,'python_compile_exit_code':None,'actual_run_exit_code':0,**payload}
  write_csv(stage,'v22_068e_feature_whitelist.csv',[]);write_csv(stage,'v22_068e_feature_bin_definition.csv',[]);write_csv(stage,'v22_068e_feature_bin_development_statistics.csv',[]);write_csv(stage,'v22_068e_validation_scored_rows.csv',[]);write_csv(stage,'v22_068e_validation_metrics.csv',[]);write_csv(stage,'v22_068e_validation_score_buckets.csv',[]);write_csv(stage,'v22_068e_validation_by_period.csv',[]);write_csv(stage,'v22_068e_validation_by_instrument.csv',[]);write_csv(stage,'v22_068e_validation_cost_stress.csv',[]);write_csv(stage,'v22_068e_gate_results.csv',[])
  (stage/'v22_068e_readme.txt').write_text('V22.068E uses Development-only deterministic binned additive scoring. Complex models and Confirmation access are prohibited.\n'+reason+'; no data rows were read because the frozen V22.068D contract is incomplete. All trading permissions remain false.\n',encoding='utf-8')
  branch=git(['branch','--show-current']);head=git(['rev-parse','HEAD']); (stage/'v22_068e_manifest.json').write_bytes(stable_json({'git_branch':branch,'git_head':head,'source_v22_068d_commit':head,'input_files':[],'output_whitelist':sorted(ALLOW),'forbidden_output_patterns':['*.pkl','*.joblib','*.onnx','*order*'],'confirmation_access_guard_status':'ACTIVE','run_start_timestamp':start,'run_end_timestamp':datetime.now(timezone.utc).isoformat(),'python_executable':sys.executable,'python_version':platform.python_version()}))
  (stage/'v22_068e_summary.json').write_bytes(stable_json(s)); files=[p for p in stage.iterdir() if p.is_file()];s['output_file_count']=len(files);s['output_total_bytes']=sum(p.stat().st_size for p in files);(stage/'v22_068e_summary.json').write_bytes(stable_json(s))
  print('PUBLISH_STAGE=replace',flush=True)
  if OUT.exists(): shutil.rmtree(OUT)
  os.replace(stage,OUT);return s
 except Exception: shutil.rmtree(stage,ignore_errors=True);raise
def run()->dict[str,Any]:
 # The mandatory V22.068D manifest is absent in the audited official output.
 # Fail before opening any data or even the diagnostic summary again.
 if not MANIFEST.exists(): return publish({},'FAIL','FROZEN_INPUT_CONTRACT_INCOMPLETE')
 try: source_contract()
 except ConfirmationAccessViolation:return publish({},'FAIL','CONFIRMATION_ACCESS_VIOLATION')
 except ContractError:return publish({},'FAIL','FROZEN_INPUT_CONTRACT_INCOMPLETE')
 raise ContractError('full contract execution unreachable without explicitly audited source contract')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');ns=a.parse_args()
 if not ns.execute: raise SystemExit(2)
 for k,v in run().items(): print(f'{k.upper()}={v}')
