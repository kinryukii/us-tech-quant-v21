"""Full-candidate TOP20 selection, explicit optimizers, target cooperation."""
import numpy as np
import pandas as pd
from shared import *
from fast_account import TargetDecision
from optimization import optimize,project_budget

class PortfolioPolicy:
    def __init__(self,roster,forecast,risk_cache,*,diagnostic_callback=None):
        self.roster=roster.reset_index(drop=True)
        self.forecast=forecast['mu'];self.stream_ids=forecast['stream_ids'].astype(str).tolist()
        self.risk_cache=risk_cache;self.callback=diagnostic_callback
        self.stream_index=np.array([self.stream_ids.index(f'{r.group}__{r.fusion}') for r in self.roster.itertuples()])
        self.risk_indices=np.array([RISKS.index(r.risk) for r in self.roster.itertuples()])
        self.optimizers=self.roster.optimizer.to_numpy(str)
        self.risks=self.roster.risk.to_numpy(str)
        self.path_ids=self.roster.path_id.to_numpy(str)
    def __call__(self,day,ctx):
        s,n=ctx.current_weights.shape
        active=np.isfinite(ctx.nav)&(ctx.nav>0)&np.isfinite(ctx.current_weights).all(axis=1)
        active&=np.isfinite(ctx.available_budget)&np.isfinite(ctx.reserved_weight)
        decision_mask=ctx.decision_mask&active[:,None]
        raw=self.forecast[day,self.stream_index]
        if not np.isfinite(raw[decision_mask]).all():raise RuntimeError('MISSING_FORECAST_CANNOT_BECOME_ZERO_MEAN')
        # Out-of-pool held context can be sold but never creates new capital.
        candidates=decision_mask & (ctx.buy_allowed | (ctx.current_units>1e-10))
        score=np.where(candidates,raw,-np.inf)
        # Market tickers are sorted; stable sort gives exact ticker tie break.
        selection=np.argsort(-score,axis=1,kind='stable')[:,:20]
        k=selection.shape[1]
        ri=np.arange(s)[:,None]
        valid=candidates[ri,selection]
        mu=np.where(valid,raw[ri,selection],0.)
        current=np.where(active[:,None],ctx.current_weights[ri,selection],0.)
        upper=np.where(valid&ctx.buy_allowed[ri,selection],.1,np.where(valid,np.minimum(current,.1),0.))
        covariance=np.zeros((s,k,k));scale=np.zeros((s,k));scenarios=np.zeros((s,32,k))
        risk_linear=np.zeros((s,k));locked_loss=np.zeros((s,32))
        reserved_current=np.where(active[:,None],ctx.current_weights,0.)*ctx.reserved_mask
        for risk in np.unique(self.risks):
            rows=np.flatnonzero((self.risks==risk)&active)
            if not len(rows):continue
            idx=selection[rows]
            correlation_key=risk if 'corr_'+risk in self.risk_cache.files else 'ledoit_wolf'
            r=self.risk_cache['corr_'+correlation_key];z=self.risk_cache['scenario_'+correlation_key]
            all_scale=self.risk_cache['scales'][day,RISKS.index(risk)]
            local_scale=all_scale[idx];scale[rows]=local_scale
            covariance[rows]=r[idx[:,:,None],idx[:,None,:]]*local_scale[:,:,None]*local_scale[:,None,:]
            scenarios[rows]=z[:,idx].transpose(1,0,2)
            if np.any(reserved_current[rows]):
                correlated_reserved=(reserved_current[rows]*all_scale[None,:])@r.T
                risk_linear[rows]=correlated_reserved[np.arange(len(rows))[:,None],idx]*local_scale
                locked_loss[rows]=-(reserved_current[rows]*all_scale[None,:])@z.T
        target=np.zeros((s,k));diagnostics=[]
        for opt in np.unique(self.optimizers):
            rows=np.flatnonzero((self.optimizers==opt)&active)
            if not len(rows):continue
            methods=['mean_variance','robust_mv','cvar'] if opt.startswith('target_') else [opt]
            results=[]
            for method in methods:
                result=optimize(method,mu[rows],covariance[rows],current[rows],ctx.available_budget[rows],ctx.available_slots[rows],
                    uncertainty=scale[rows],scenarios=scenarios[rows],upper=upper[rows],risk_linear=risk_linear[rows],
                    reserved_joint_loss=locked_loss[rows] if method=='cvar' else None)
                results.append(result)
                diagnostic=pd.DataFrame({'path_id':self.path_ids[rows],'signal_date':ctx.signal_date,'optimizer_component':method,
                    'status':result.status,'iterations':result.iterations,'proximal_gradient_residual':result.residual,
                    'gradient_evaluations':result.gradient_evaluations if result.gradient_evaluations is not None else np.zeros(len(rows),int),
                    'exact_fixed_point':result.exact_fixed_point if result.exact_fixed_point is not None else np.zeros(len(rows),bool),
                    'reported_objective':result.objective,'cvar_eta':result.cvar_eta,
                    'available_budget':ctx.available_budget[rows],'available_slots':ctx.available_slots[rows],
                    'reserved_weight':ctx.reserved_weight[rows],
                    'selected_tickers':[ctx.tickers[j].tolist() for j in selection[rows]],
                    'selected_mu':mu[rows].tolist(),'current_selected_weights':current[rows].tolist(),
                    'selected_upper_bounds':upper[rows].tolist(),'selected_scale':scale[rows].tolist(),
                    'component_target_weights':result.weights.tolist()})
                diagnostics.append(diagnostic)
            if opt=='target_equal':target[rows]=np.mean([r.weights for r in results],axis=0)
            elif opt=='target_median':target[rows]=np.median([r.weights for r in results],axis=0)
            else:target[rows]=results[0].weights
            target[rows]=project_budget(target[rows],ctx.available_budget[rows],upper[rows])
        full=np.zeros((s,n));full[ri,selection]=target
        # Every modeled name is explicit, including exits of unselected holdings.
        # Missing-model held names are left unmentioned and retained by the engine.
        explicit=decision_mask.copy()
        if self.callback is not None and diagnostics:self.callback(pd.concat(diagnostics,ignore_index=True))
        evidence=np.array([f'forecast:{key}|risk:{risk}|signal:{ctx.signal_date.date()}' for key,risk in
            zip(np.array(self.stream_ids,dtype=object)[self.stream_index],self.risks)],dtype=object)
        return TargetDecision(full,explicit,evidence)
