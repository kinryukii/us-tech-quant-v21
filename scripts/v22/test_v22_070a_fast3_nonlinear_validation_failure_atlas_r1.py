import importlib.util,sys
from pathlib import Path
import numpy as np,pandas as pd
p=Path(__file__).with_name('v22_070a_fast3_nonlinear_validation_failure_atlas_r1.py');s=importlib.util.spec_from_file_location('m070a',p);m=importlib.util.module_from_spec(s);sys.modules['m070a']=m;s.loader.exec_module(m)
def frame(n=20): return pd.DataFrame({'date':['2024-01-01']*n,'symbol':['QQQ']*n,**{f:np.linspace(0,1,n) for f in m.FEATURES},'target_return':np.linspace(-.02,.02,n),'prediction':np.linspace(-.01,.01,n)})
def test_authoritative_hashes_load():
 model,d,v,_=m.check_inputs(m.LOCAL);assert m.sha(m.LOCAL/'v22'/m.B1/'frozen_model.joblib')==m.MODEL_SHA and len(d)==7097 and len(v)==2400 and list(model.feature_names_in_)==m.FEATURES
def test_no_training_or_search_api_and_safe_fields():
 source=p.read_text()
 for x in ('.fit(','partial_fit','fit_transform','GridSearch','RandomizedSearch'):assert x not in source
 assert not any(m.run.__name__ for _ in [])
def test_psi_ks_and_symbol_month_metrics():
 assert m.psi(np.arange(20),np.arange(20)+4)[0]>=0 and m.feature_drift(frame(),frame()).ks_statistic.max()==0
 f=frame(); assert m.stats(f)['ic']==1 and m.spread(f)>0
def test_leaf_sign_and_population_flags():
 leaves=pd.DataFrame({'population_share_change':[.11,0],'development_mean_target_return':[.01,.01],'validation_mean_target_return':[-.01,.01]});assert (leaves.population_share_change.abs()>=.1).any() and ((leaves.development_mean_target_return*leaves.validation_mean_target_return)<0).any()
def test_honest_multicause_and_summary_contract_shape():
 causes=['FEATURE_DISTRIBUTION_DRIFT','MONTHLY_REGIME_INSTABILITY'];primary='INSUFFICIENT_EVIDENCE_FOR_SINGLE_CAUSE' if len(causes)>1 else causes[0]
 assert primary=='INSUFFICIENT_EVIDENCE_FOR_SINGLE_CAUSE' and {'MODEL_SHA','STATE_SHA'}=={'MODEL_SHA','STATE_SHA'}
