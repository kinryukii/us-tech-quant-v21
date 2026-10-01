"""OOF-only adapters and cooperation, no test-year fitting or selection."""
import argparse, time, traceback
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from shared import *
from calibration_fusion import fit_calibration, fit_fusion, SPEC

CALENDAR={'2024':(['2023H2'],'2024-01-01','2024'),'2025':(['2023H2','2024'],'2025-01-01','2025'),
 'final':(['2023H2','2024','2025'],'2026-01-01',None)}

def calibrate(period,fit_only=False):
    histories,cutoff,evaluate=CALENDAR[period];folder=ROOT/'models'/f'calibration_{period}';folder.mkdir(exist_ok=True,parents=True)
    frames=[pd.read_parquet(ROOT/'predictions'/f'raw_oof_{year}.parquet') for year in histories]
    frame=pd.concat(frames,ignore_index=True)
    hashes={str(ROOT/'predictions'/f'raw_oof_{year}.parquet'):sha(ROOT/'predictions'/f'raw_oof_{year}.parquet') for year in histories}
    binding={'inputs':hashes,'calibration_code':sha(ROOT/'calibration_fusion.py'),'trainer':sha(Path(__file__)),'shared':sha(ROOT/'shared.py')}
    done=folder/'STATUS.json'
    old=read_json(done) if done.exists() else {'records':[],'binding':binding}
    if old['binding']!=binding:raise RuntimeError('CALIBRATION_FROZEN_BINDING_CHANGED')
    recorded={r['name']:r for r in old['records']}
    for name in PREDICTORS:
        if name in recorded:continue
        started=time.monotonic();r={'name':name,'period':period,'cutoff':cutoff}
        try:
            with threadpool_limits(limits=2):obj,receipt=fit_calibration(name,frame,cutoff)
            destination=folder/f'{name}.joblib';joblib.dump(obj,destination)
            r.update(status='TRAINED',artifact=str(destination),artifact_sha256=sha(destination),receipt=receipt)
        except Exception as exc:r.update(status='FAILED',error=str(exc),traceback=traceback.format_exc())
        r['seconds']=round(time.monotonic()-started,3);old['records'].append(r);write_json(done,old)
    old['status']='COMPLETE_WITH_FAILURES' if any(r['status']=='FAILED' for r in old['records']) else 'COMPLETE';write_json(done,old)
    if evaluate and not fit_only:
        raw=pd.read_parquet(ROOT/'predictions'/f'raw_oof_{evaluate}.parquet')
        result=apply_calibration(raw,period)
        out=ROOT/'predictions'/f'mu_oof_{evaluate}.parquet'
        if out.exists():
            if not pd.read_parquet(out).equals(result):raise RuntimeError('PRESERVE_MU_OOF')
        else:result.to_parquet(out,index=False)
        write_json(out.with_suffix('.json'),{'status':'COMPLETE','fit_period':period,'file_sha256':sha(out),
            'raw_oof_sha256':sha(ROOT/'predictions'/f'raw_oof_{evaluate}.parquet'),'calibration_status_sha256':sha(done),
            'base_fit_cutoff':f'{evaluate}-01-01','calibration_cutoff':cutoff,'fit_2026_rows':0,'rows':len(result)})
    return old

def apply_calibration(raw,period):
    folder=ROOT/'models'/f'calibration_{period}';status=read_json(folder/'STATUS.json')
    result=raw[[c for c in ['signal_date','ticker','y_next_open','label_end_date'] if c in raw]].copy()
    for r in status['records']:
        name=r['name']
        if r['status']=='TRAINED':
            destination=Path(r['artifact'])
            if sha(destination)!=r['artifact_sha256']:raise RuntimeError('CALIBRATION_CHANGED')
            obj=joblib.load(destination)
            mu,uncertainty,probability=obj.predict(raw)
            result[f'{name}__mu']=mu;result[f'{name}__uncertainty']=uncertainty
            if probability is not None:result[f'{name}__calibrated_p']=probability
            if name in QUANTILE:
                q=raw[[f'{name}__q10',f'{name}__q50',f'{name}__q90']].to_numpy(float)
                result[f'{name}__raw_crossing']=(q[:,0]>q[:,1])|(q[:,1]>q[:,2])
        else:
            result[f'{name}__mu']=np.nan;result[f'{name}__uncertainty']=np.nan
    return result

def train_fusions(stage):
    years=['2024'] if stage=='validation' else ['2024','2025'];cutoff=STAGES[stage]
    frames=[pd.read_parquet(ROOT/'predictions'/f'mu_oof_{year}.parquet') for year in years]
    frame=pd.concat(frames,ignore_index=True)
    features=pd.read_parquet(PRE_PANEL,columns=['signal_date','ticker',*SPEC['context']])
    frame=frame.merge(features,on=['signal_date','ticker'],how='left',validate='one_to_one')
    folder=ROOT/'models'/f'fusion_{stage}';folder.mkdir(parents=True,exist_ok=True)
    binding={'inputs':{year:sha(ROOT/'predictions'/f'mu_oof_{year}.parquet') for year in years},
        'features':sha(PRE_PANEL),'code':sha(ROOT/'calibration_fusion.py'),'trainer':sha(Path(__file__)),'shared':sha(ROOT/'shared.py')}
    status_path=folder/'STATUS.json';status=read_json(status_path) if status_path.exists() else {'records':[],'binding':binding}
    if status['binding']!=binding:raise RuntimeError('FUSION_BINDING_CHANGED')
    finished={(r['group'],r['method']) for r in status['records']}
    for group,members in GROUPS.items():
        for method in FUSIONS:
            if (group,method) in finished:continue
            r={'group':group,'method':method,'stage':stage};start=time.monotonic()
            try:
                with threadpool_limits(limits=2):obj,receipt=fit_fusion(method,members,frame,cutoff)
                dest=folder/f'{group}__{method}.joblib';joblib.dump(obj,dest)
                r.update(status='TRAINED',artifact=str(dest),artifact_sha256=sha(dest),receipt=receipt)
            except Exception as exc:r.update(status='FAILED',error=str(exc),traceback=traceback.format_exc())
            r['seconds']=round(time.monotonic()-start,3);status['records'].append(r);write_json(status_path,status)
            print(group,method,r['status'],r['seconds'],r.get('error',''),flush=True)
    status['status']='COMPLETE_WITH_FAILURES' if any(r['status']=='FAILED' for r in status['records']) else 'COMPLETE'
    write_json(status_path,status);return status

class CooperationRuntime:
    def __init__(self,stage):
        self.stage=stage;self.period='2025' if stage=='validation' else 'final'
        folder=ROOT/'models'/f'fusion_{stage}';status=read_json(folder/'STATUS.json')
        self.fusions={};self.failures={}
        for r in status['records']:
            key=f"{r['group']}__{r['method']}"
            if r['status']=='TRAINED':
                if sha(r['artifact'])!=r['artifact_sha256']:raise RuntimeError('FUSION_ARTIFACT_CHANGED')
                self.fusions[key]=joblib.load(r['artifact'])
            else:self.failures[key]=r['error']
        cs=read_json(ROOT/'models'/f'calibration_{self.period}'/'STATUS.json')
        self.calibrators={}
        for r in cs['records']:
            if r['status']=='TRAINED':self.calibrators[r['name']]=joblib.load(r['artifact'])
            else:self.failures[f"{r['name']}__identity"]=r['error']
        self.stream_ids=[f'{name}__identity' for name in PREDICTORS]+[f'{group}__{f}' for group in GROUPS for f in FUSIONS]
    def calibrated(self,raw):
        result=raw[['signal_date','ticker']].copy()
        for name in PREDICTORS:
            if name in self.calibrators:
                mu,uncertainty,p=self.calibrators[name].predict(raw);result[f'{name}__mu']=mu
            else:result[f'{name}__mu']=np.nan
        return result
    def predict_streams(self,mu_frame,context):
        outputs={name+'__identity':mu_frame[name+'__mu'].to_numpy(float) for name in PREDICTORS}
        for group,members in GROUPS.items():
            inputs=mu_frame[[f'{m}__mu' for m in members]].to_numpy(float)
            for method in FUSIONS:
                key=f'{group}__{method}'
                outputs[key]=self.fusions[key].predict(inputs,context) if key in self.fusions else np.full(len(mu_frame),np.nan)
        return outputs

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--calibration',choices=CALENDAR);parser.add_argument('--fusion',choices=['validation','final']);parser.add_argument('--fit-only',action='store_true');a=parser.parse_args()
    if a.calibration:calibrate(a.calibration,a.fit_only)
    elif a.fusion:train_fusions(a.fusion)
    else:
        for period in CALENDAR:calibrate(period)
        for stage in ['validation','final']:train_fusions(stage)
