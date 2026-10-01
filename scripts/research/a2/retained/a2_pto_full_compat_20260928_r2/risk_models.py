"""Pre-2026 risk fits; risk and return statistical objects stay separate."""
import time, warnings
import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf, OAS
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from shared import *

SPEC={'covariance_missing':'demeaned observed returns; absent observations mean-imputed, with coverage retained',
 'factors':5,'pca_solver':'randomized','fa_max_iter':60,'fa_tol':.01,'eigen_floor':1e-8,
 'supervised_target':'abs(one-day next-open return), calibrated to RMS with earlier-stage matured outcomes',
 'hgb':{'max_iter':64,'max_depth':3,'max_leaf_nodes':15,'min_samples_leaf':100,'learning_rate':.05,'l2_regularization':1.,'early_stopping':False},
 'mlp':{'hidden_layer_sizes':[32],'max_iter':10,'batch_size':512,'learning_rate_init':.001,'alpha':.0001,'early_stopping':False},
 'garch':'one shared parameter fit on equal-security aggregate standardized squared innovation, then causal per-name filter',
 'garch_maxiter':200,'garch_stationarity_cap':.995,'scenario_rows':32,'scenario_seed':SEED}

def _fit_garch(r,asymmetric):
    # Fit shared dynamic variance to a daily cross-sectional squared shock.
    v=np.nanmean(r*r,axis=1);neg=np.nanmean(np.where(r<0,r*r,0.),axis=1)
    initial=np.array([.04,.06,.9,.02] if asymmetric else [.04,.06,.9])
    def objective(p):
        omega,alpha,beta=p[:3];gamma=p[3] if asymmetric else 0.
        if alpha+beta+.5*gamma>=.995: return 1e6+1e6*(alpha+beta+.5*gamma-.995)
        h=1.;loss=0.
        for i in range(1,len(v)):
            h=max(1e-8,omega+alpha*v[i-1]+beta*h+gamma*neg[i-1])
            loss+=np.log(h)+v[i]/h
        return loss/len(v)
    result=minimize(objective,initial,method='SLSQP',bounds=[(1e-6,1.),(0.,.4),(0.,.994)]+([(0.,.4)] if asymmetric else []),
        constraints=[{'type':'ineq','fun':lambda p:.995-p[1]-p[2]-(.5*p[3] if asymmetric else 0.)}],options={'maxiter':200,'ftol':1e-8})
    return result.x,{'success':bool(result.success),'message':str(result.message),'objective':float(result.fun),'iterations':int(result.nit)}

def train_risk(stage):
    destination=ROOT/'models'/f'risk_{stage}.joblib'
    if destination.exists(): return joblib.load(destination)
    p=pd.read_parquet(PRE_PANEL)
    cutoff=pd.Timestamp(STAGES[stage]);p=p.loc[p.label_available&p.label_end_date.lt(cutoff)&p.signal_date.lt(cutoff)]
    table=p.pivot(index='signal_date',columns='ticker',values='y_next_open').sort_index()
    observed=table.notna().sum().to_numpy();means=table.mean().fillna(0.).to_numpy()
    variance=table.var().to_numpy();fallback=float(np.nanmedian(variance[observed>=30]))
    variance=np.where((observed>=30)&np.isfinite(variance),variance,fallback)
    sigma=np.sqrt(np.maximum(variance,1e-8));raw=table.to_numpy(float)
    centered=np.where(np.isfinite(raw),raw-means,0.)
    with threadpool_limits(limits=2):
        lw=LedoitWolf().fit(centered).covariance_;oas=OAS().fit(centered).covariance_
        sample=np.cov(centered,rowvar=False)
        pc=PCA(n_components=5,svd_solver='randomized',random_state=SEED).fit(centered)
        pc_cov=pc.components_.T@np.diag(pc.explained_variance_)@pc.components_
        pc_cov+=np.diag(np.maximum(np.diag(sample)-np.diag(pc_cov),1e-8))
        fa=FactorAnalysis(n_components=5,max_iter=60,tol=.01,random_state=SEED).fit(centered)
        fa_cov=fa.components_.T@fa.components_+np.diag(np.maximum(fa.noise_variance_,1e-8))
    def corr(cov):
        s=np.sqrt(np.maximum(np.diag(cov),1e-8));r=cov/s[:,None]/s[None,:]
        r=(r+r.T)/2;np.fill_diagonal(r,1.);return r
    # All structures share empirical marginal RMS; isolate dependence estimate.
    correlations={'diagonal':np.eye(len(sigma)),'sample':corr(sample),'ledoit_wolf':corr(lw),
        'oas':corr(oas),'pca':corr(pc_cov),'factor_analysis':corr(fa_cov)}
    correlations['lw_oas_average']=(correlations['ledoit_wolf']+correlations['oas'])/2
    correlations['pca_fa_average']=(correlations['pca']+correlations['factor_analysis'])/2
    frame,keys=fit_frame(stage);x=frame[FEATURES].to_numpy(float);y=np.abs(frame.y_next_open.to_numpy(float))
    yscale=max(float(np.sqrt(np.mean(y*y))),1e-6)
    scaler=StandardScaler().fit(x)
    with threadpool_limits(limits=2):
        hgb=HistGradientBoostingRegressor(**SPEC['hgb'],random_state=SEED).fit(x,y/yscale)
        with warnings.catch_warnings(record=True) as ws:
            mlp=MLPRegressor(**{**SPEC['mlp'],'hidden_layer_sizes':(32,)},random_state=SEED).fit(scaler.transform(x),y/yscale)
    # Fixed empirical normal moment mapping E|r| -> sqrt(E r^2); no test calibration.
    ratio=float(np.sqrt(np.mean(y*y))/max(np.mean(y),1e-8))
    standardized=raw/sigma[None,:]
    gp,gr=_fit_garch(standardized,False);jp,jr=_fit_garch(standardized,True)
    # Causal per-security filter from its own innovations, shared fitted parameters.
    def final_h(params):
        h=np.ones(len(sigma));omega,alpha,beta=params[:3];gamma=params[3] if len(params)==4 else 0.
        for row in standardized:
            shock=np.where(np.isfinite(row),row*row,h)
            negative=np.where(np.isfinite(row)&(row<0),row*row,0.)
            h=np.maximum(omega+alpha*shock+beta*h+gamma*negative,1e-8)
        return h
    rng=np.random.default_rng(SEED)
    gaussian=rng.normal(size=(SPEC['scenario_rows'],len(sigma)))
    # Joint historical innovations are transformed to each risk correlation;
    # standardized PCA-whitened scores avoid pretending marginals independent.
    scores=pc.transform(centered)
    score_std=np.maximum(scores.std(axis=0),1e-8)
    selected=np.linspace(0,len(scores)-1,SPEC['scenario_rows'],dtype=int)
    gaussian[:,:5]=scores[selected]/score_std
    obj={'stage':stage,'tickers':table.columns.tolist(),'sigma':sigma,'correlations':correlations,
        'hgb':hgb,'mlp':mlp,'scaler':scaler,'yscale':yscale,'ratio':ratio,'garch_params':gp,'gjr_params':jp,
        'garch_initial_h':final_h(gp),'gjr_initial_h':final_h(jp),'scenario_latent':gaussian,
        'spec':SPEC,'cutoff':str(cutoff.date()),'max_label_end':str(p.label_end_date.max()),
        'observed':observed,'mean':means}
    destination.parent.mkdir(exist_ok=True,parents=True);joblib.dump(obj,destination)
    write_json(ROOT/'models'/f'risk_{stage}_receipt.json',{'status':'FIT_COMPLETE','stage':stage,
        'cutoff':str(cutoff.date()),'fit_2026_rows':0,'fit_rows':len(p),'days':len(table),'names':len(sigma),
        'max_label_end':str(p.label_end_date.max()),'garch':gr,'gjr_garch':jr,'fa_iterations':int(fa.n_iter_),
        'mlp_fixed_budget_warnings':[str(w.message) for w in ws],'spec':SPEC,'artifact_sha256':sha(destination),
        'coverage':{'minimum':int(observed.min()),'median':float(np.median(observed)),'mean_imputation_disclosed':True}})
    return obj

class RiskRuntime:
    def __init__(self,obj,market_tickers):
        self.obj=obj;self.tickers=list(market_tickers);self.index={t:i for i,t in enumerate(obj['tickers'])}
        self.mapping=np.array([self.index.get(t,-1) for t in self.tickers]);self.known=self.mapping>=0
        fallback=float(np.median(obj['sigma']));self.sigma=np.full(len(self.tickers),fallback)
        self.sigma[self.known]=obj['sigma'][self.mapping[self.known]]
        self.correlations={}
        for key,r in obj['correlations'].items():
            dest=np.eye(len(self.tickers));idx=np.flatnonzero(self.known)
            dest[np.ix_(idx,idx)]=r[np.ix_(self.mapping[idx],self.mapping[idx])]
            self.correlations[key]=dest
        self.h={key:np.ones(len(self.tickers)) for key in ['garch','gjr_garch']}
        for key in self.h:
            self.h[key][self.known]=obj[key.replace('gjr_garch','gjr')+'_initial_h'][self.mapping[self.known]]
        self.last_date=None
        self.scenarios={}
        # Fixed historical joint innovations, whitened before changing dependence.
        # Newly observed names have no pre-2026 residuals; their explicit fallback
        # is independent seeded Normal innovation, never an eligibility upgrade.
        adapter=np.load(ROOT/'models'/f'risk_scenario_adapter_{obj["stage"]}.npz')
        latent=np.random.default_rng(SEED).normal(size=(32,len(self.tickers)))
        historical_indices={str(t):i for i,t in enumerate(adapter['tickers'])}
        matched=np.array([historical_indices.get(t,-1) for t in self.tickers])
        valid=matched>=0
        latent[:,valid]=adapter['whitened'][...,matched[valid]]
        for key,r in self.correlations.items():
            with threadpool_limits(limits=2):
                vals,vecs=np.linalg.eigh(r)
                root=(vecs*np.sqrt(np.maximum(vals,1e-8)))@vecs.T
            self.scenarios[key]=latent@root.T
    def prepare_day(self,date,features):
        # Called once per calendar signal, shared market filtering only, no fit.
        x=np.asarray(features,float);safe=np.where(np.isfinite(x),x,0.)
        with threadpool_limits(limits=2):
            hgb=np.maximum(self.obj['hgb'].predict(safe)*self.obj['yscale']*self.obj['ratio'],1e-4)
            mlp=np.maximum(self.obj['mlp'].predict(self.obj['scaler'].transform(safe))*self.obj['yscale']*self.obj['ratio'],1e-4)
        valid_features=np.isfinite(x).all(axis=1)
        hgb=np.where(valid_features,hgb,self.sigma);mlp=np.where(valid_features,mlp,self.sigma)
        ret=x[:,FEATURES.index('ret_1d')];valid=np.isfinite(ret)
        if self.last_date!=date:
            for key,params in [('garch',self.obj['garch_params']),('gjr_garch',self.obj['gjr_params'])]:
                omega,alpha,beta=params[:3];gamma=params[3] if len(params)==4 else 0.
                z=np.where(valid,ret/self.sigma,0.);shock=np.where(valid,z*z,self.h[key])
                self.h[key]=np.maximum(omega+alpha*shock+beta*self.h[key]+gamma*np.where(z<0,z*z,0.),1e-8)
            self.last_date=date
        self.scales={'historical':self.sigma,'lw_hgb_scale':hgb,'lw_mlp_scale':mlp,
            'lw_learned_scale_average':(hgb+mlp)/2,'garch':self.sigma*np.sqrt(self.h['garch']),
            'gjr_garch':self.sigma*np.sqrt(self.h['gjr_garch'])}
    def get(self,name,selected):
        idx=np.asarray(selected,int)
        correlation_key=name if name in self.correlations else 'ledoit_wolf'
        r=self.correlations[correlation_key]
        scale=self.scales.get(name,self.sigma)[idx]
        cov=r[idx[:,:,None],idx[:,None,:]]*scale[:,:,None]*scale[:,None,:]
        scenarios=self.scenarios[correlation_key][:,idx].transpose(1,0,2)
        return cov,scale,scenarios

def build_scenario_adapter(stage):
    """Algebraic adapter of fixed fits, preserving the original fitted artifacts."""
    dest=ROOT/'models'/f'risk_scenario_adapter_{stage}.npz'
    if dest.exists():return dest
    receipt=read_json(ROOT/'models'/f'risk_{stage}_receipt.json')
    artifact=ROOT/'models'/f'risk_{stage}.joblib'
    if sha(artifact)!=receipt['artifact_sha256']:raise RuntimeError('RISK_FIT_CHANGED')
    obj=joblib.load(artifact)
    source=WS/'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
    cols=['signal_date','ticker','y_next_open','label_end_date','label_available',*FEATURES]
    old=pd.read_parquet(source,columns=cols);new=pd.read_parquet(PRE_PANEL,columns=cols)
    pd.testing.assert_frame_equal(old,new,check_exact=True)
    cutoff=pd.Timestamp(STAGES[stage]);p=new.loc[new.label_available&new.label_end_date.lt(cutoff)]
    table=p.pivot(index='signal_date',columns='ticker',values='y_next_open').reindex(columns=obj['tickers']).sort_index()
    values=table.to_numpy(float);centered=np.where(np.isfinite(values),values-obj['mean'],0.)
    sample_sigma=np.sqrt(np.maximum(np.var(centered,axis=0,ddof=1),1e-8))
    standardized=centered/sample_sigma
    selected=np.linspace(0,len(table)-1,32,dtype=int)
    with threadpool_limits(limits=2):
        vals,vecs=np.linalg.eigh(obj['correlations']['sample'])
        inverse_root=(vecs*(1/np.sqrt(np.maximum(vals,1e-8))))@vecs.T
        whitened=standardized[selected]@inverse_root
    np.savez_compressed(dest,tickers=np.asarray(obj['tickers']),whitened=whitened,
        historical_dates=table.index.to_numpy()[selected],eigenvalues=vals)
    write_json(dest.with_suffix('.json'),{'status':'HISTORICAL_SCENARIO_ADAPTER_COMPLETE','stage':stage,
        'fit_2026_rows':0,'cutoff_exclusive':STAGES[stage],'mature_labels_max':str(p.label_end_date.max()),
        'original_fit_sha256':sha(artifact),'adapter_sha256':sha(dest),'old_input_sha256':sha(source),
        'isolated_input_sha256':sha(PRE_PANEL),'old_and_isolated_learning_columns_equal':True,
        'historical_scenario_dates':[str(d) for d in table.index[selected]],'historical_rows':32,
        'unknown_risk_name_fallback':'independent seeded Normal plus median frozen scale, eligibility unchanged',
        'covariance_singular_floor':1e-8,'no_parameter_refit':True})
    return dest

if __name__=='__main__':
    for stage in ['validation','final']:
        started=time.monotonic();train_risk(stage);build_scenario_adapter(stage);print(stage,round(time.monotonic()-started,2),flush=True)
