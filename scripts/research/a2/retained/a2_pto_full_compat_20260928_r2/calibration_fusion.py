"""Time-legal statistical adapters and OOF-only prediction cooperation."""
from dataclasses import dataclass
import warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import Ridge, ElasticNet, LogisticRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
import torch
from torch import nn
from shared import *

SPEC={'calibration':'Ridge alpha100 on earlier OOF only; probabilities separately calibrated then signed amplitude mapping',
 'probability_C':1.,'probability_clip':1e-6,'date_weighting':'equal total weight per signal date',
 'meta_max_rows':40000,'ridge_alpha':100.,'elastic_alpha':1e-5,'elastic_l1_ratio':.35,
 'tree_iterations':64,'tree_depth':3,'tree_leaf':15,'tree_min_leaf':100,'tree_learning_rate':.05,
 'nn_epochs':10,'nn_batch':512,'nn_hidden':32,'gate_hidden':16,'nn_lr':.001,
 'simplex_solver':'SLSQP','simplex_maxiter':500,'simplex_ftol':1e-10,
 'context':['ret_1d','ret_20d','realized_vol_20d','realized_vol_60d','volume_ratio_5d_20d'],
 'residual_crossfit':'first chronological half fit primary; second half out-of-time residual; primary refit all eligible OOF',
 'quantile_crossing':'sort three raw quantiles rowwise, retain crossing indicator'}

def sample(frame):
    frame=frame.sort_values(['signal_date','ticker']).reset_index(drop=True)
    rng=np.random.default_rng(SEED);quota=max(1,MAX_ROWS//frame.signal_date.nunique())
    picks=[]
    for _,g in frame.groupby('signal_date',sort=True):
        picks.extend(sorted(rng.choice(g.index,min(quota,len(g)),replace=False)))
    if len(picks)>MAX_ROWS:picks=sorted(rng.choice(picks,MAX_ROWS,replace=False))
    return frame.loc[picks].reset_index(drop=True)
def date_weights(dates):
    dates=pd.Series(dates);counts=dates.map(dates.value_counts()).to_numpy(float)
    w=1./counts;return w/w.mean()
def inputs(frame,name):
    if name in PROB:
        p=np.clip(frame[f'{name}__p'].to_numpy(float),1e-6,1-1e-6)
        return np.log(p/(1-p))[:,None]
    if name in QUANTILE:
        return np.sort(frame[[f'{name}__q10',f'{name}__q50',f'{name}__q90']].to_numpy(float),axis=1)
    if name in DISTRIBUTION:return frame[[f'{name}__location']].to_numpy(float)
    if name in RANK:return frame[[f'{name}__rank']].to_numpy(float)
    return frame[[f'{name}__raw']].to_numpy(float)

@dataclass
class Calibration:
    name:str
    scaler:object
    model:object
    residual_rms:float
    signed_amplitudes:tuple|None=None
    scale_multiplier:float=1.
    def predict(self,frame):
        xx=self.scaler.transform(inputs(frame,self.name))
        if self.name in PROB:
            probability=self.model.predict_proba(xx)[:,1]
            plus,minus=self.signed_amplitudes
            mu=probability*plus+(1-probability)*minus
        else:
            mu=self.model.predict(xx)
            probability=None
        uncertainty=np.full(len(frame),self.residual_rms)
        if self.name in DISTRIBUTION:
            uncertainty=np.maximum(frame[f'{self.name}__scale'].to_numpy(float)*self.scale_multiplier,1e-6)
        return mu,uncertainty,probability

def fit_calibration(name,history,cutoff):
    cutoff=pd.Timestamp(cutoff)
    if not history.signal_date.lt(cutoff).all() or not history.label_end_date.lt(cutoff).all():
        raise ValueError('CALIBRATION_CLOCK_LEAK')
    h=sample(history);x=inputs(h,name);y=h.y_next_open.to_numpy(float);w=date_weights(h.signal_date)
    if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('FAILED_BASE_PREDICTOR')
    scaler=StandardScaler().fit(x,sample_weight=w);xx=scaler.transform(x)
    if name in PROB:
        event=y>0
        if len(np.unique(event))<2:raise ValueError('SINGLE_CLASS_CALIBRATION')
        model=LogisticRegression(C=1.,max_iter=400,random_state=SEED).fit(xx,event,sample_weight=w)
        plus=float(np.average(y[event],weights=w[event]));minus=float(np.average(y[~event],weights=w[~event]))
        p=model.predict_proba(xx)[:,1];fit_mu=p*plus+(1-p)*minus;amp=(plus,minus)
    else:
        model=Ridge(alpha=100.).fit(xx,y,sample_weight=w);fit_mu=model.predict(xx);amp=None
    rms=float(np.sqrt(np.average((y-fit_mu)**2,weights=w)))
    scale_multiplier=1.
    if name in DISTRIBUTION:
        sigma=np.maximum(h[f'{name}__scale'].to_numpy(float),1e-6)
        scale_multiplier=float(np.sqrt(np.average(((y-fit_mu)/sigma)**2,weights=w)))
    obj=Calibration(name,scaler,model,max(rms,1e-6),amp,scale_multiplier)
    receipt={'name':name,'rows':len(h),'fit_cutoff_exclusive':str(cutoff.date()),
        'max_signal':str(h.signal_date.max()),'max_label_end':str(h.label_end_date.max()),'fit_2026_rows':0,
        'residual_rms_in_fit':rms,'scale_multiplier':scale_multiplier,'signed_amplitudes':amp,
        'input_columns':x.shape[1],'calibration_unit':'one-day raw return decimal','spec':SPEC}
    return obj,receipt

def tree():
    return HistGradientBoostingRegressor(max_iter=64,max_depth=3,max_leaf_nodes=15,min_samples_leaf=100,
        learning_rate=.05,l2_regularization=1.,early_stopping=False,random_state=SEED)

class GateNetwork(nn.Module):
    def __init__(self,n_members,nonlinear):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(5,16),nn.Tanh(),nn.Linear(16,n_members)) if nonlinear else nn.Linear(5,n_members)
    def forward(self,x):return torch.softmax(self.net(x),dim=1)

@dataclass
class Gate:
    nonlinear:bool
    def fit(self,mu,context,y,weights):
        torch.set_num_threads(2);torch.manual_seed(SEED)
        self.scaler=StandardScaler().fit(context,sample_weight=weights)
        self.network=GateNetwork(mu.shape[1],self.nonlinear)
        xx=torch.tensor(np.clip(self.scaler.transform(context),-8,8),dtype=torch.float32)
        scale=max(float(np.sqrt(np.mean(y*y))),1e-6)
        experts=torch.tensor(mu/scale,dtype=torch.float32);yy=torch.tensor(y/scale,dtype=torch.float32)
        ww=torch.tensor(weights,dtype=torch.float32)
        optimizer=torch.optim.Adam(self.network.parameters(),lr=.001,weight_decay=.0001)
        rng=torch.Generator().manual_seed(SEED);self.losses=[]
        for _ in range(10):
            order=torch.randperm(len(xx),generator=rng);losses=[]
            for start in range(0,len(xx),512):
                j=order[start:start+512];optimizer.zero_grad()
                output=(self.network(xx[j])*experts[j]).sum(dim=1)
                loss=(ww[j]*(output-yy[j])**2).mean();loss.backward();optimizer.step();losses.append(float(loss.detach()))
            self.losses.append(float(np.mean(losses)))
        self.network.eval();return self
    def predict_weights(self,context):
        with torch.no_grad():
            return self.network(torch.tensor(np.clip(self.scaler.transform(context),-8,8),dtype=torch.float32)).numpy()
    def predict(self,mu,context):return (self.predict_weights(context)*mu).sum(axis=1)

@dataclass
class Fusion:
    method:str
    members:list
    scaler:object=None
    model:object=None
    secondary:object=None
    secondary_scaler:object=None
    coefficients:object=None
    def predict(self,mu,context):
        if self.method=='equal':return mu.mean(axis=1)
        if self.method=='median':return np.median(mu,axis=1)
        if self.method=='simplex':return mu@self.coefficients
        if self.method in ['linear_gate','mlp_gate']:return self.model.predict(mu,context)
        xx=self.scaler.transform(mu)
        value=self.model.predict(xx)
        if self.secondary is not None:value+=self.secondary.predict(self.secondary_scaler.transform(mu))
        return value

def fit_fusion(method,members,frame,cutoff):
    cutoff=pd.Timestamp(cutoff)
    if not frame.signal_date.lt(cutoff).all() or not frame.label_end_date.lt(cutoff).all():raise ValueError('FUSION_CLOCK_LEAK')
    frame=sample(frame);x=frame[[f'{m}__mu' for m in members]].to_numpy(float)
    y=frame.y_next_open.to_numpy(float);context=frame[SPEC['context']].to_numpy(float);w=date_weights(frame.signal_date)
    if not np.isfinite(x).all():raise ValueError('UNAVAILABLE_MEMBER_DO_NOT_DROP')
    obj=Fusion(method,list(members));extra={}
    if method in ['equal','median']:pass
    elif method=='simplex':
        scale=max(float(np.sqrt(np.mean(y*y))),1e-6);xx=x/scale;yy=y/scale
        def fun(a):return float(np.average((xx@a-yy)**2,weights=w))
        def jac(a):return 2*xx.T@(w*(xx@a-yy))/w.sum()
        result=minimize(fun,np.full(x.shape[1],1/x.shape[1]),jac=jac,method='SLSQP',bounds=[(0.,1.)]*x.shape[1],
            constraints=[{'type':'eq','fun':lambda a:a.sum()-1,'jac':lambda a:np.ones_like(a)}],options={'maxiter':500,'ftol':1e-10})
        if not result.success:raise RuntimeError('SIMPLEX_NOT_CONVERGED:'+str(result.message))
        obj.coefficients=result.x;extra={'weights':result.x.tolist(),'iterations':int(result.nit)}
    elif method in ['linear_gate','mlp_gate']:
        obj.model=Gate(method=='mlp_gate').fit(x,context,y,w);extra={'epoch_losses':obj.model.losses}
    else:
        obj.scaler=StandardScaler().fit(x,sample_weight=w);xx=obj.scaler.transform(x)
        if method=='ridge_stack':model=Ridge(alpha=100.)
        elif method=='elastic_stack':model=ElasticNet(alpha=1e-5,l1_ratio=.35,max_iter=2500,tol=1e-5,random_state=SEED)
        elif method=='hgb_stack':model=tree()
        elif method=='mlp_stack':model=MLPRegressor(hidden_layer_sizes=(32,),max_iter=10,batch_size=512,learning_rate_init=.001,alpha=.0001,random_state=SEED,early_stopping=False)
        elif method in ['ridge_then_hgb','hgb_then_ridge']:
            dates=np.sort(frame.signal_date.unique());boundary=pd.Timestamp(dates[len(dates)//2])
            first=frame.label_end_date.lt(boundary).to_numpy();second=frame.signal_date.ge(boundary).to_numpy()
            if first.sum()<200 or second.sum()<200:raise ValueError('NESTED_RESIDUAL_FOLD_TOO_SMALL')
            first_scaler=StandardScaler().fit(x[first],sample_weight=w[first])
            primary=Ridge(alpha=100.) if method=='ridge_then_hgb' else tree()
            primary.fit(first_scaler.transform(x[first]),y[first],sample_weight=w[first])
            residual=y[second]-primary.predict(first_scaler.transform(x[second]))
            obj.secondary_scaler=StandardScaler().fit(x[second],sample_weight=w[second])
            obj.secondary=tree() if method=='ridge_then_hgb' else Ridge(alpha=100.)
            obj.secondary.fit(obj.secondary_scaler.transform(x[second]),residual,sample_weight=w[second])
            model=Ridge(alpha=100.) if method=='ridge_then_hgb' else tree()
            extra={'nested_boundary':str(boundary),'nested_first_rows':int(first.sum()),'nested_residual_rows':int(second.sum()),
                'nested_primary_max_label_end':str(frame.loc[first,'label_end_date'].max()),'nested_primary_refit_all_for_future':True}
        else:raise ValueError('UNKNOWN_FUSION')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always');model.fit(xx,y,sample_weight=w)
        obj.model=model;extra['fixed_budget_warnings']=[str(z.message) for z in caught]
    receipt={'method':method,'members':members,'rows':len(frame),'cutoff_exclusive':str(cutoff.date()),
        'max_signal':str(frame.signal_date.max()),'max_label_end':str(frame.label_end_date.max()),'fit_2026_rows':0,'spec':SPEC,**extra}
    return obj,receipt
