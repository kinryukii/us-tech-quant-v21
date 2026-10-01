"""OOF-only return fusion. Prediction fusion and target fusion stay distinct."""
from __future__ import annotations
from common import *
import numpy as np
import pandas as pd
import torch
from torch import nn
from scipy.optimize import minimize
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

def state_features(panel, predictions):
    f=panel[['signal_date','ret_20d','realized_vol_20d','price_vs_ma20']].copy()
    f['breadth']=f.price_vs_ma20.gt(0).astype(float)
    f['expert_disagreement']=np.std(predictions,axis=1)
    cols=['ret_20d','realized_vol_20d','breadth','expert_disagreement']
    return f.groupby('signal_date')[cols].transform('mean').to_numpy(float)

class Gate(nn.Module):
    def __init__(self,m,hidden=0):
        super().__init__()
        self.network=nn.Sequential(nn.Linear(4,hidden),nn.Tanh(),nn.Linear(hidden,m)) if hidden else nn.Linear(4,m)
        for p in self.parameters(): nn.init.zeros_(p) if p.ndim==1 else nn.init.normal_(p, std=.02)
    def forward(self,x): return torch.softmax(self.network(x),dim=-1)

class Fusion:
    def __init__(self,method,seed=20260928): self.method=method;self.seed=seed
    def fit(self,x,y,state,weights):
        x=np.asarray(x,float); y=np.asarray(y,float);weights=np.asarray(weights,float).copy();weights/=weights.mean()
        assert np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(state).all()
        m=x.shape[1];self.members_count=m;self.fitted_rows=len(y)
        self.fixed=np.full(m,1/m)
        if self.method=='convex':
            def objective(w):
                residual=x@w-y
                return np.average(residual*residual,weights=weights)+.001*np.sum((w-1/m)**2)
            result=minimize(objective,self.fixed,jac=lambda w:2*(x.T@(weights*(x@w-y)))/weights.sum()+.002*(w-1/m),
                method='SLSQP',bounds=[(0,1)]*m,constraints=[{'type':'eq','fun':lambda w:w.sum()-1,'jac':lambda w:np.ones(m)}],
                options={'maxiter':200,'ftol':1e-12})
            if not result.success: raise RuntimeError('CONVEX_FUSION_FAILED:'+result.message)
            self.fixed=result.x; self.optimizer_message=result.message
        elif self.method.startswith('stack_'):
            model={'stack_ridge':Ridge(alpha=100),
              'stack_elastic':ElasticNet(alpha=.0001,l1_ratio=.35,max_iter=2000,tol=1e-5),
              'stack_hgb':HistGradientBoostingRegressor(max_iter=100,max_depth=2,max_leaf_nodes=7,min_samples_leaf=100,
                    l2_regularization=5,learning_rate=.05,early_stopping=False,random_state=self.seed),
              'stack_mlp':MLPRegressor(hidden_layer_sizes=(8,),max_iter=40,n_iter_no_change=41,early_stopping=False,
                    batch_size=512,alpha=.1,random_state=self.seed)}[self.method]
            self.model=make_pipeline(StandardScaler(),model)
            self.model.fit(x,y,standardscaler__sample_weight=weights,**{self.model.steps[-1][0]+'__sample_weight':weights})
        elif self.method.startswith('gate_'):
            self.scale=StandardScaler().fit(state,sample_weight=weights)
            torch.manual_seed(self.seed);torch.set_num_threads(2)
            self.gate=Gate(m,8 if self.method=='gate_mlp' else 0)
            optimizer=torch.optim.Adam(self.gate.parameters(),lr=.01)
            xx=torch.tensor(x,dtype=torch.float32);ss=torch.tensor(self.scale.transform(state),dtype=torch.float32)
            yy=torch.tensor(y,dtype=torch.float32);ww=torch.tensor(weights,dtype=torch.float32)
            for _ in range(80):
                optimizer.zero_grad();g=self.gate(ss)
                loss=(ww*((g*xx).sum(1)-yy).square()).mean()+.001*((g-1/m).square().sum(1)).mean()
                loss.backward();torch.nn.utils.clip_grad_norm_(self.gate.parameters(),2);optimizer.step()
            self.final_loss=float(loss.detach());self.gate.eval()
        elif self.method.startswith('residual_'):
            self.anchor=0 if self.method=='residual_first_hgb' else -1
            model=HistGradientBoostingRegressor(max_iter=100,max_depth=2,max_leaf_nodes=7,min_samples_leaf=100,
                l2_regularization=5,learning_rate=.05,early_stopping=False,random_state=self.seed) if self.anchor==0 else Ridge(alpha=100)
            self.model=make_pipeline(StandardScaler(),model)
            self.model.fit(np.column_stack([x,state]),y-x[:,self.anchor],standardscaler__sample_weight=weights,
                **{self.model.steps[-1][0]+'__sample_weight':weights})
        elif self.method not in ['equal','median']: raise ValueError('UNKNOWN_FUSION')
        fitted=self.predict(x,state)
        self.residual_scale=max(.01,float(np.sqrt(np.average((y-fitted)**2,weights=weights))))
        self.training_mse=float(np.average((y-fitted)**2,weights=weights))
        return self
    def predict(self,x,state):
        x=np.asarray(x,float)
        if self.method in ['equal','convex']: return x@self.fixed
        if self.method=='median': return np.median(x,axis=1)
        if self.method.startswith('stack_'): return self.model.predict(x)
        if self.method.startswith('gate_'):
            with torch.no_grad():
                weights=self.gate(torch.tensor(self.scale.transform(state),dtype=torch.float32)).numpy()
            return np.sum(x*weights,axis=1)
        if self.method.startswith('residual_'): return x[:,self.anchor]+self.model.predict(np.column_stack([x,state]))
        raise ValueError('UNKNOWN_FUSION')
    def uncertainty(self,x,sigma,state):
        mu=self.predict(x,state)
        if self.method.startswith('gate_'):
            with torch.no_grad(): w=self.gate(torch.tensor(self.scale.transform(state),dtype=torch.float32)).numpy()
        elif self.method in ['equal','convex']: w=np.broadcast_to(self.fixed,x.shape)
        else: return np.full(len(x),self.residual_scale)
        return np.sqrt(np.maximum(.0001,np.sum(w*(sigma**2+(x-mu[:,None])**2),axis=1)))
