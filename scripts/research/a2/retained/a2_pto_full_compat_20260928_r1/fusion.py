"""Time-legal output adapters and pre-registered prediction cooperation."""
from common import *
import argparse, time, joblib
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from scipy.optimize import minimize
import torch
from torch import nn
torch.set_num_threads(2)
GATE_FEATURES = ['ret_1d','ret_20d','realized_vol_20d','downside_vol_20d','volume_ratio_5d_20d']

class SmallNet:
    def __init__(self, kind='stack'):
        self.kind=kind
    def fit(self,x,y,context=None):
        torch.manual_seed(SEED)
        self.xscale=StandardScaler().fit(context if self.kind.endswith('gate') else x)
        a=self.xscale.transform(context if self.kind.endswith('gate') else x).astype('float32')
        self.ym=float(np.mean(y));self.ys=max(float(np.std(y)),1e-5)
        if self.kind=='linear_gate':self.net=nn.Linear(a.shape[1],x.shape[1])
        elif self.kind=='mlp_gate':self.net=nn.Sequential(nn.Linear(a.shape[1],8),nn.Tanh(),nn.Linear(8,x.shape[1]))
        else:self.net=nn.Sequential(nn.Linear(a.shape[1],32),nn.Tanh(),nn.Linear(32,1))
        optimizer=torch.optim.Adam(self.net.parameters(),lr=.001)
        inputs=torch.from_numpy(a);targets=torch.from_numpy(((y-self.ym)/self.ys).astype('float32'))
        experts=torch.from_numpy(((x-self.ym)/self.ys).astype('float32'))
        self.losses=[]
        for epoch in range(8):
            total=0.
            for first in range(0,len(y),1024):
                z=self.net(inputs[first:first+1024])
                output=(torch.softmax(z,1)*experts[first:first+1024]).sum(1) if self.kind.endswith('gate') else z[:,0]
                loss=((output-targets[first:first+1024])**2).mean()
                optimizer.zero_grad();loss.backward();optimizer.step();total+=float(loss.detach())
            self.losses.append(total)
        self.net.eval();return self
    def predict(self,x,context=None,return_weights=False):
        a=self.xscale.transform(context if self.kind.endswith('gate') else x).astype('float32')
        with torch.no_grad():
            z=self.net(torch.from_numpy(a))
            if self.kind.endswith('gate'):
                weights=torch.softmax(z,1).numpy()
                return (weights*x).sum(1),weights if return_weights else None
            return z[:,0].numpy()*self.ys+self.ym,None

def raw_columns(member,frame):
    """Do not rename probability, median or rank score to a raw expected return."""
    def choose(names):
        for name in names:
            if name in frame:return name
        raise ValueError(f'{member}:missing raw interface: {names}; have {frame.columns.tolist()}')
    if member.startswith('prob_'):return [choose(['p_up','p','probability','prob'])]
    if member.startswith('quant_'):return [choose(['q10']),choose(['q50']),choose(['q90'])]
    if member.startswith('rank_'):return [choose(['rank_score','score','raw_score'])]
    if member.startswith('dist_'):return [choose(['raw_mu','mu','mean']),choose(['sigma','std','scale'])]
    return [choose(['raw_mu','mu','prediction','pred'])]

def interface_x(member,frame):
    cols=raw_columns(member,frame)
    x=frame[cols].to_numpy(float)
    if member.startswith('rank_'):
        # Full contemporaneous cross-section ranking; no labels participate.
        x=frame.groupby('signal_date',sort=False)[cols[0]].rank(method='average',pct=True).to_numpy(float)[:,None]
    if not np.isfinite(x).all():raise ValueError('NONFINITE_RAW_PREDICTION')
    return x

def base_path(stage,member):
    options=[ROOT/f'predictions/base/{stage}/{member}.parquet',ROOT/f'predictions/base/{stage}_{member}.parquet']
    for p in options:
        if p.exists():return p
    raise FileNotFoundError(str(options[0]))

def load_raw(stage,member):
    frame=pd.read_parquet(base_path(stage,member));frame['signal_date']=pd.to_datetime(frame.signal_date)
    if frame.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_PREDICTION_KEY')
    return frame.sort_values(['signal_date','ticker']).reset_index(drop=True)

def fit_adapter(member,raw,truth,cutoff):
    joined=raw.merge(truth[['signal_date','ticker','y_next_open','label_end_date','label_available','new_buy_eligible']+FEATURES],
                     on=['signal_date','ticker'],validate='one_to_one')
    train=training_sample(joined,cutoff)
    if len(train)<100:raise ValueError('INSUFFICIENT_CALIBRATION_OOF')
    # Rank percentiles must be computed before sampling the labeled rows.
    xfull=interface_x(member,joined)
    key=pd.MultiIndex.from_frame(joined[['signal_date','ticker']])
    ix=key.get_indexer(pd.MultiIndex.from_frame(train[['signal_date','ticker']]))
    x=xfull[ix];y=np.clip(train.y_next_open.to_numpy(float),-.2,.2)
    model=make_pipeline(StandardScaler(),Ridge(alpha=10.)).fit(x,y)
    residual=y-model.predict(x)
    base_scale=max(float(np.sqrt(np.mean(residual**2))),1e-4)
    if member.startswith('quant_'):
        sig=(np.sort(x,axis=1)[:,2]-np.sort(x,axis=1)[:,0])/2.563103
    elif member.startswith('dist_'):sig=np.maximum(x[:,1],1e-5)
    else:sig=np.repeat(base_scale,len(x))
    ratio=max(float(np.sqrt(np.mean(residual**2)/max(np.mean(sig**2),1e-10))),.01)
    return dict(model=model,member=member,scale=base_scale,scale_ratio=ratio,raw_columns=raw_columns(member,raw),
                cutoff=cutoff,label_end_max=str(train.label_end_date.max()),n=len(train),
                calibration_diagnostic='Training-OOF residual scale; coverage must be evaluated, not assumed correct.')

def adapt(adapter,raw):
    x=interface_x(adapter['member'],raw);mu=adapter['model'].predict(x)
    name=adapter['member']
    if name.startswith('quant_'):
        q=np.sort(x,axis=1);sig=np.maximum((q[:,2]-q[:,0])/2.563103,1e-5)*adapter['scale_ratio']
    elif name.startswith('dist_'):sig=np.maximum(x[:,1],1e-5)*adapter['scale_ratio']
    else:sig=np.repeat(adapter['scale'],len(raw))
    result=raw[['signal_date','ticker']].copy();result['mu']=mu;result['sigma']=sig
    if name.startswith('quant_'):
        for j,c in enumerate(['q10','q50','q90']):result[c]=q[:,j]
    if name.startswith('prob_'):result['p_up']=x[:,0]
    return result

def estimator(name):
    if name=='ridge_stack':return make_pipeline(StandardScaler(),Ridge(alpha=10.))
    if name=='elastic_stack':return make_pipeline(StandardScaler(),ElasticNet(alpha=.0001,l1_ratio=.5,max_iter=10000))
    if name=='hgb_stack':return HistGradientBoostingRegressor(max_iter=60,max_depth=2,max_leaf_nodes=7,min_samples_leaf=100,
        learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=SEED)
    return SmallNet('stack')

def fit_fusion(name,x,y,context,dates):
    if name in ['equal','median']:return {'name':name}
    if name=='simplex':
        scale=max(float(np.std(y)),1e-5);a=x/scale;b=y/scale
        objective=lambda w:float(np.mean((a@w-b)**2))
        gradient=lambda w:2*a.T@(a@w-b)/len(b)
        r=minimize(objective,np.full(x.shape[1],1/x.shape[1]),jac=gradient,method='SLSQP',bounds=[(0,1)]*x.shape[1],
                   constraints={'type':'eq','fun':lambda w:w.sum()-1,'jac':lambda w:np.ones(len(w))},
                   options={'maxiter':200,'ftol':1e-10})
        if not r.success:raise ValueError('SIMPLEX_SOLVER_FAILED:'+r.message)
        return {'name':name,'weights':r.x,'objective':r.fun}
    if name.endswith('_gate'):return {'name':name,'model':SmallNet(name).fit(x,y,context)}
    if '_then_' in name:
        unique=np.sort(pd.to_datetime(dates).unique());boundary=unique[len(unique)//2]
        first=np.asarray(pd.to_datetime(dates)<boundary);last=~first
        left,right=name.split('_then_')
        anchor=estimator(left+'_stack').fit(x[first],y[first])
        correction=estimator(right+'_stack').fit(x[last],y[last]-anchor.predict(x[last]))
        return {'name':name,'anchor':anchor,'correction':correction,'anchor_end':str(boundary),
                'residual_end':str(pd.to_datetime(dates).max()),'nested_training':True}
    model=estimator(name)
    return {'name':name,'model':model.fit(x,y)}

def predict_fusion(model,x,context):
    name=model['name'];weights=None
    if name=='equal':weights=np.full_like(x,1/x.shape[1]);mu=x.mean(1)
    elif name=='median':mu=np.median(x,axis=1)
    elif name=='simplex':weights=np.broadcast_to(model['weights'],x.shape);mu=x@model['weights']
    elif name.endswith('_gate'):mu,weights=model['model'].predict(x,context,return_weights=True)
    elif '_then_' in name:mu=model['anchor'].predict(x)+model['correction'].predict(x)
    elif name=='mlp_stack':mu,_=model['model'].predict(x)
    else:mu=model['model'].predict(x)
    return mu,weights

def wide(adapted,members):
    index=pd.MultiIndex.from_frame(adapted[members[0]][['signal_date','ticker']])
    arrays=[];scales=[]
    for member in members:
        f=adapted[member].set_index(['signal_date','ticker']).reindex(index)
        if f.mu.isna().any():raise ValueError('MEMBER_KEY_SUPPORT_MISMATCH:'+member)
        arrays.append(f.mu.to_numpy(float));scales.append(f.sigma.to_numpy(float))
    return index,np.column_stack(arrays),np.column_stack(scales)

def train_all(stages=('validation','final')):
    if (ROOT/'models/fusion/FUSION_COMPLETE.json').exists():raise RuntimeError('REFUSE_OVERWRITE_COMPLETED_FUSION')
    truth=pd.read_parquet(DATA_SOURCE);truth.signal_date=pd.to_datetime(truth.signal_date);truth.label_end_date=pd.to_datetime(truth.label_end_date)
    all_adapted={};receipts=[];failed=[]
    for stage in stages:
        destination=ROOT/f'models/fusion/{stage}';destination.mkdir(parents=True,exist_ok=True)
        if (destination/'RECEIPT.json').exists():
            print('skip completed fusion stage',stage,flush=True);continue
        meta={};adapters={};predictions={}
        for m in MEMBERS:
            try:
                parts=[load_raw('development',m)]
                if stage=='final':parts.append(load_raw('validation',m))
                raw=pd.concat(parts,ignore_index=True)
                first=raw[raw.signal_date.lt('2024-07-01')]
                half_adapter=fit_adapter(m,first,truth,'2024-07-01')
                late24=adapt(half_adapter,raw[raw.signal_date.ge('2024-07-01')&raw.signal_date.lt('2025-01-01')])
                adapter24=fit_adapter(m,raw[raw.signal_date.lt('2025-01-01')],truth,'2025-01-01')
                if stage=='final':year25=adapt(adapter24,raw[raw.signal_date.ge('2025-01-01')])
                else:
                    try:year25=adapt(adapter24,load_raw('validation',m))
                    except FileNotFoundError:year25=None
                meta[m]=late24 if stage=='validation' else pd.concat([late24,year25],ignore_index=True)
                adapters[m]=adapter24 if stage=='validation' else fit_adapter(m,raw,truth,'2026-01-01')
                joblib.dump(adapters[m],destination/f'{m}_adapter.joblib')
                if stage=='validation' and year25 is not None:predictions[m]=year25
                receipts.append({'stage':stage,'kind':'adapter','member':m,'status':'TRAINED',
                    'cutoff':adapters[m]['cutoff'],'label_end_max':adapters[m]['label_end_max'],'rows':adapters[m]['n']})
            except Exception as e:
                failed.append({'stage':stage,'member':m,'kind':'adapter','reason':str(e)})
        stream_receipts=[]
        for bundle,members in BUNDLES.items():
            if any(m not in meta for m in members):
                for f in FUSIONS:failed.append({'stage':stage,'stream':bundle+'__'+f,'reason':'MISSING_REQUIRED_MEMBER'})
                continue
            index,x,sigma=wide(meta,members)
            joined=index.to_frame(index=False).merge(truth[['signal_date','ticker','y_next_open','label_end_date','label_available','new_buy_eligible']+FEATURES],on=['signal_date','ticker'],validate='one_to_one')
            sample=training_sample(joined,CUTOFFS[stage]);ix=index.get_indexer(pd.MultiIndex.from_frame(sample[['signal_date','ticker']]))
            y=np.clip(sample.y_next_open.to_numpy(float),-.2,.2);context=sample[GATE_FEATURES].to_numpy(float)
            for f in FUSIONS:
                stream=bundle+'__'+f;start=time.time()
                try:
                    model=fit_fusion(f,x[ix],y,context,sample.signal_date)
                    joblib.dump(model,destination/f'{stream}.joblib')
                    if stage=='validation' and all(m in predictions for m in members):
                        idx,a,ss=wide(predictions,members)
                        ct=idx.to_frame(index=False).merge(truth[['signal_date','ticker']+GATE_FEATURES],on=['signal_date','ticker'],validate='one_to_one')[GATE_FEATURES].to_numpy(float)
                        mu,weights=predict_fusion(model,a,ct)
                        sig=np.sqrt(np.mean(ss**2+(a-mu[:,None])**2,axis=1))
                        out=idx.to_frame(index=False);out['mu']=mu;out['sigma']=sig
                        if weights is not None:
                            for j,m in enumerate(members):out['weight__'+m]=weights[:,j]
                        predictions[stream]=out
                    record={'stage':stage,'stream':stream,'kind':'fusion','members':members,'rows':len(y),
                        'label_end_max':str(sample.label_end_date.max()),'status':'TRAINED' if f not in ['equal','median'] else 'FIXED_RULE',
                        'seconds':time.time()-start,'artifact_sha256':sha(destination/f'{stream}.joblib')}
                    stream_receipts.append(record);print(stage,stream,record['status'],round(record['seconds'],2),flush=True)
                except Exception as e:failed.append({'stage':stage,'stream':stream,'reason':str(e)})
        if stage=='validation':
            for stream,p in predictions.items():
                out=ROOT/f'predictions/streams/{stage}/{stream}.parquet';out.parent.mkdir(parents=True,exist_ok=True);p.to_parquet(out,index=False)
        write_json(destination/'RECEIPT.json',{'status':'COMPLETE_WITH_FAILURES' if failed else 'COMPLETE','adapters':[r for r in receipts if r['stage']==stage],
            'fusions':stream_receipts,'failures':[f for f in failed if f['stage']==stage], 'source_sha256':sha(DATA_SOURCE),
            'contract_sha256':sha(ROOT/'EXPERIMENT_CONTRACT.md'),'reads_2026_rows':0,'fits_on_in_sample_base_predictions':False})
    if all((ROOT/f'models/fusion/{s}/RECEIPT.json').exists() for s in ['validation','final']):
        stage_receipts={s:json.loads((ROOT/f'models/fusion/{s}/RECEIPT.json').read_text(encoding='utf-8')) for s in ['validation','final']}
        write_json(ROOT/'models/fusion/FUSION_COMPLETE.json',{'status':'ALL_REGISTERED_ATTEMPTED','stage_receipts':stage_receipts,'failures':[f for s in stage_receipts.values() for f in s['failures']]})

def predict_stage(stage='final'):
    if stage=='final':
        freeze=json.loads((ROOT/'FREEZE.json').read_text(encoding='utf-8'))
        if freeze['status']!='FROZEN_ALL_LEARNING_PRE2026':raise RuntimeError('ALL_BATCH_FREEZE_REQUIRED')
    truth=pd.read_parquet(ROOT/('data/test.parquet' if stage=='final' else 'data/pre.parquet'));predictions={};destination=ROOT/f'models/fusion/{stage}'
    failures=[]
    for m in MEMBERS:
        try:
            adapter=joblib.load(destination/f'{m}_adapter.joblib');predictions[m]=adapt(adapter,load_raw(stage,m))
        except Exception as e:failures.append({'stream':m,'reason':str(e)})
    for bundle,members in BUNDLES.items():
        if any(m not in predictions for m in members):
            failures.extend({'stream':bundle+'__'+f,'reason':'MISSING_REQUIRED_MEMBER'} for f in FUSIONS);continue
        idx,x,sig=wide(predictions,members)
        ct=idx.to_frame(index=False).merge(truth[['signal_date','ticker']+GATE_FEATURES],on=['signal_date','ticker'],validate='one_to_one')[GATE_FEATURES].to_numpy(float)
        for f in FUSIONS:
            stream=bundle+'__'+f
            try:model=joblib.load(destination/f'{stream}.joblib');mu,weights=predict_fusion(model,x,ct)
            except Exception as e:failures.append({'stream':stream,'reason':str(e)});continue
            out=idx.to_frame(index=False);out['mu']=mu;out['sigma']=np.sqrt(np.mean(sig**2+(x-mu[:,None])**2,axis=1))
            if weights is not None:
                for j,m in enumerate(members):out['weight__'+m]=weights[:,j]
            predictions[stream]=out
    for stream,p in predictions.items():
        out=ROOT/f'predictions/streams/{stage}/{stream}.parquet';out.parent.mkdir(parents=True,exist_ok=True)
        if out.exists():
            old=pd.read_parquet(out)
            if not old.equals(p):raise ValueError('REFUSE_OVERWRITE_DIFFERENT_FROZEN_STREAM:'+stream)
        else:p.to_parquet(out,index=False)
    write_json(ROOT/f'predictions/streams/{stage}/INFERENCE_RECEIPT.json',{'stage':stage,'streams':list(predictions),'failures':failures,'fit_calls':0,
        'artifact_sha256':{stream:sha(ROOT/f'predictions/streams/{stage}/{stream}.parquet') for stream in predictions}})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--test',action='store_true');p.add_argument('--predict-validation',action='store_true');p.add_argument('--stage',choices=['validation','final']);a=p.parse_args()
    if a.test:predict_stage('final')
    elif a.predict_validation:predict_stage('validation')
    else:train_all((a.stage,) if a.stage else ('validation','final'))
