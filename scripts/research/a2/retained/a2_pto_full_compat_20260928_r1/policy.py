"""Fixed finite solvers and same-account component experiments. No fit calls."""
from common import *
from risk_models import RiskBank
import time
from scipy.stats import norm, rankdata

def prox_box_budget(z, anchor, threshold, upper, budget):
    """Exact L1 proximal map subject to long-only box and cash budget."""
    def at(lam):
        v=z-anchor-lam[:,None]
        return np.clip(anchor+np.sign(v)*np.maximum(np.abs(v)-threshold[:,None],0),0,upper)
    k=len(z);zeros=np.zeros(k);w=at(zeros)
    violating=w.sum(1)>budget+1e-10
    if not violating.any():return w
    lo=zeros.copy();hi=np.max(z+np.abs(anchor)+threshold[:,None],axis=1)+1.
    for _ in range(28):
        mid=(lo+hi)/2;v=at(mid);large=v.sum(1)>budget
        lo=np.where(large,mid,lo);hi=np.where(large,hi,mid)
    adjusted=at(hi)
    return np.where(violating[:,None],adjusted,w)

def solve_quadratic(mu,cov,current,upper,budget,uncertainty=None):
    """Deterministic proximal gradient, fixed maximum 128 iterations."""
    q=4*np.asarray(cov,float);reward=np.asarray(mu,float).copy()
    if uncertainty is not None:reward-=.25*np.asarray(uncertainty,float)
    lips=np.maximum(np.linalg.eigvalsh(q)[:,-1],1e-6)
    step=1/lips
    w=np.minimum(np.maximum(current,0),upper)
    w=prox_box_budget(w,w,np.zeros(len(w)),upper,budget)
    for iteration in range(128):
        grad=np.einsum('kij,kj->ki',q,w)-reward
        new=prox_box_budget(w-step[:,None]*grad,current,.001*step,upper,budget)
        delta=np.max(np.abs(new-w),axis=1);w=new
        if np.all(delta<1e-8):break
    grad=np.einsum('kij,kj->ki',q,w)-reward
    check=prox_box_budget(w-step[:,None]*grad,current,.001*step,upper,budget)
    residual=np.max(np.abs(check-w),axis=1)
    objective=-(reward*w).sum(1)+.5*np.einsum('ki,kij,kj->k',w,q,w)+.001*np.abs(w-current).sum(1)
    return w,dict(objective=objective,solver_residual=residual,iterations=np.full(len(w),iteration+1),
        status=np.where(residual<=1e-5,'SOLVED_TOLERANCE','APPROXIMATE_BUDGET'))

def cvar_values(scenarios,w,tail=.05,with_gradient=False,base_returns=None):
    returns=np.einsum('ksi,ki->ks',scenarios,w)
    if base_returns is not None:returns=returns+base_returns
    losses=-returns
    n=scenarios.shape[1];mass=n*tail;whole=int(np.floor(mass));frac=mass-whole
    order=np.argsort(-losses,axis=1,kind='stable')[:,:whole+int(frac>1e-12)]
    tail_loss=np.take_along_axis(losses,order,axis=1)
    weights=np.ones(order.shape[1]);
    if frac>1e-12:weights[-1]=frac
    value=(tail_loss*weights).sum(1)/mass
    if not with_gradient:return value
    rows=np.arange(len(w))[:,None];selected=scenarios[rows,order,:]
    gradient=-(selected*weights[None,:,None]).sum(1)/mass
    return value,gradient

def linear_oracle(gradient,upper,budget):
    order=np.argsort(gradient,axis=1,kind='stable');caps=np.take_along_axis(upper,order,axis=1)
    before=np.cumsum(caps,axis=1)-caps
    ordered=np.minimum(caps,np.maximum(budget[:,None]-before,0))
    ordered*=np.take_along_axis(gradient,order,axis=1)<0
    out=np.zeros_like(gradient);np.put_along_axis(out,order,ordered,axis=1);return out

def solve_cvar(mu,scenarios,current,upper,budget,base_returns=None):
    """Frank-Wolfe over exact historical 95% CVaR, fixed 96 iterations.

    Feasible best iterate is retained. A valid convex supporting-plane gap is
    saved; budget-limited approximations are never presented as exact optima.
    """
    def values(w,grad=False):
        result=cvar_values(scenarios,w,with_gradient=grad,base_returns=base_returns)
        cv,g=result if grad else (result,None)
        value=-(mu*w).sum(1)+.25*cv+.001*np.abs(w-current).sum(1)
        return (value,-mu+.25*g+.001*np.sign(w-current)) if grad else value
    w=prox_box_budget(current,current,np.zeros(len(current)),upper,budget)
    best=w.copy();bestval=values(best);bestgap=np.full(len(w),np.inf)
    # Zero investment is also feasible; retain it only if this exact objective improves.
    zero=np.zeros_like(w);zero_value=values(zero)
    use=zero_value<bestval;best[use]=0;bestval=np.minimum(bestval,zero_value)
    # At the all-cash point every scenario is tied (when no fixed holdings).
    # A valid tail subgradient from an arbitrary positive probe can certify
    # optimal cash cheaply. This is a numerical certificate, not model pruning.
    probe=linear_oracle(-mu,upper,budget)
    _,tail_gradient=cvar_values(scenarios,probe,with_gradient=True,base_returns=base_returns)
    zero_gradient=-mu+.25*tail_gradient+.001*np.where(current>0,-1,1)
    certified_zero=np.all(zero_gradient>=-1e-10,axis=1)
    if base_returns is not None:certified_zero&=np.ptp(base_returns,axis=1)<1e-12
    if certified_zero.all():
        return zero,dict(objective=zero_value,solver_residual=np.zeros(len(w)),iterations=np.zeros(len(w),int),status=np.full(len(w),'SOLVED_CASH_CERTIFICATE',dtype=object))
    # Remove certified accounts from the iterative solve; their targets still
    # pass the common account engine and are preserved in the coverage table.
    if certified_zero.any():
        active=~certified_zero
        aw,am=solve_cvar(mu[active],scenarios[active],current[active],upper[active],budget[active],None if base_returns is None else base_returns[active])
        result=np.zeros_like(w);result[active]=aw
        meta={name:np.zeros(len(w)) for name in ['objective','solver_residual','iterations']};meta['objective']=zero_value.copy();meta['status']=np.full(len(w),'SOLVED_CASH_CERTIFICATE',dtype=object)
        for name in meta:meta[name][active]=am[name]
        return result,meta
    for iteration in range(96):
        value,g=values(w,True);v=linear_oracle(g,upper,budget)
        gap=np.maximum(np.sum(g*(w-v),axis=1),0)
        improved=value<bestval
        best[improved]=w[improved];bestval=np.minimum(bestval,value);bestgap[improved]=gap[improved]
        if np.all(gap<1e-5):break
        direction=v-w
        # Deterministic batched golden-section line minimization, not strategy-weight search.
        left=np.zeros(len(w));right=np.ones(len(w));ratio=(np.sqrt(5)-1)/2
        for _ in range(14):
            a=right-ratio*(right-left);b=left+ratio*(right-left)
            va=values(w+a[:,None]*direction);vb=values(w+b[:,None]*direction)
            lower=va<vb;right=np.where(lower,b,right);left=np.where(lower,left,a)
        t=(left+right)/2;w=w+t[:,None]*direction
    value,g=values(w,True);v=linear_oracle(g,upper,budget)
    use=value<bestval;best[use]=w[use];bestval=np.minimum(bestval,value)
    # Compute the supporting-plane certificate at the retained iterate.
    _,g=values(best,True);v=linear_oracle(g,upper,budget)
    bestgap=np.maximum(np.sum(g*(best-v),axis=1),0)
    return best,dict(objective=bestval,solver_residual=bestgap,iterations=np.full(len(w),iteration+1),
        status=np.where(bestgap<=1e-5,'SOLVED_TOLERANCE','APPROXIMATE_BUDGET'))

def isolate_axis(proposed,reference,current,axis,upper,budget):
    """Same-account ablations; the other component rules come from a fixed reference.

    buy: reference reductions, proposed relative buy increments, reference gross.
    sell: proposed reductions, reference relative buy increments, reference gross.
    cash: reference relative risky allocation, proposed gross.
    The common projection can bind; all projection effects are logged.
    """
    if isinstance(axis,str):axis=[axis]*len(proposed)
    out=reference.copy()
    for k,a in enumerate(axis):
        if a=='joint':out[k]=proposed[k];continue
        if a=='cash':
            total=proposed[k].sum();denom=reference[k].sum()
            out[k]=reference[k]*total/denom if denom>1e-12 else 0
        else:
            gross=reference[k].sum()
            reductions=np.minimum(proposed[k] if a=='sell' else reference[k],current[k])
            increments=np.maximum((proposed[k] if a=='buy' else reference[k])-current[k],0)
            room=max(gross-reductions.sum(),0)
            if increments.sum()>1e-12:out[k]=reductions+increments*room/increments.sum()
            else:out[k]=reductions
    return prox_box_budget(out,out,np.zeros(len(out)),upper,budget)

class StreamBank:
    def __init__(self,stage,tickers):
        self.tickers=list(tickers);self.lookup={t:i for i,t in enumerate(tickers)};self.stage=stage
        self.stream_names=[s['stream'] for s in registry()[0]];self.data={};self.failures={};self.quantile_shapes={};self.dates=None;self.date_index=None
        for stream in self.stream_names:
            path=ROOT/f'predictions/streams/{stage}/{stream}.parquet'
            if not path.exists():self.failures[stream]='MISSING_FROZEN_PREDICTION';continue
            import pyarrow.parquet as pq
            schema=pq.read_schema(path).names
            qcols=['q10','q50','q90'] if all(c in schema for c in ['q10','q50','q90']) else []
            frame=pd.read_parquet(path,columns=['signal_date','ticker','mu','sigma']+qcols)
            if frame.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_STREAM_KEYS')
            if self.dates is None:
                self.dates=pd.DatetimeIndex(sorted(frame.signal_date.unique()));self.date_index={pd.Timestamp(d):i for i,d in enumerate(self.dates)}
            frame=frame.loc[frame.ticker.isin(self.lookup)]
            ri=self.dates.get_indexer(pd.DatetimeIndex(frame.signal_date));ci=frame.ticker.map(self.lookup).to_numpy(int)
            if (ri<0).any():raise ValueError('STREAM_DATE_SUPPORT_MISMATCH:'+stream)
            array=np.full((2,len(self.dates),len(tickers)),np.nan);array[:,ri,ci]=frame[['mu','sigma']].to_numpy(float).T
            self.data[stream]=array
            if qcols:
                q=np.sort(frame[qcols].to_numpy(float),axis=1);span=np.maximum(q[:,2]-q[:,0],1e-8)
                shape=np.ones_like(array);shape[:,ri,ci]=np.column_stack([2*(q[:,1]-q[:,0])/span,2*(q[:,2]-q[:,1])/span]).T
                for i,date in enumerate(self.dates):self.quantile_shapes[(pd.Timestamp(date),stream)]=shape[:,i,:]
    def at(self,date,stream):
        i=self.date_index.get(pd.Timestamp(date),-1) if self.date_index is not None else -1
        if stream not in self.data or i<0:return np.full((2,len(self.tickers)),np.nan)
        return self.data[stream][:,i,:]

class PTOBatchPolicy:
    def __init__(self,paths,stage,tickers,stream_bank=None):
        self.paths=paths;self.stage=stage;self.tickers=list(tickers);self.risk=RiskBank(stage);self.streams=stream_bank if stream_bank is not None else StreamBank(stage,tickers)
        self.date=None;self.risk_cov={};self.scenario_cache={};self.failures=[];self.solver_counts={}
    def _reset(self,day,context):
        date=pd.Timestamp(context['signal_date'])
        if self.date==date:return
        self.date=date;self.scenario_cache={}
        usable=day[day[FEATURES].notna().all(axis=1)].copy()
        self.valid_day=usable
        requested={p['risk'] for p in self.paths}|{'diagonal'}
        self.risk_cov={r:self.risk.covariance(r,self.tickers,usable) for r in requested}
    def _solve(self,paths,context):
        k=len(paths);n=len(self.tickers);current=np.asarray(context['current_weights'],float)
        masks=np.asarray(context['decision_mask'],bool);buy=np.asarray(context['buy_allowed_mask'],bool)
        present=(current>1e-12);available=masks&(buy|present)
        mu=np.array([self.streams.at(self.date,p['stream'])[0] for p in paths]);unc=np.array([self.streams.at(self.date,p['stream'])[1] for p in paths])
        decided=masks&np.isfinite(mu)&np.isfinite(unc)
        # Missing predictions preserve held units, so their weight and slots
        # must enter this optimization as fixed holdings before the solve.
        extra_reserved=present&~decided&~context['reserved_mask']
        reserved=context['reserved_mask']|extra_reserved
        slots=np.maximum(0,np.asarray(context['available_slots'],int)-extra_reserved.sum(1))
        budget=np.maximum(0,np.asarray(context['available_weight'],float)-(current*extra_reserved).sum(1))
        valid=available&np.isfinite(mu)&np.isfinite(unc)
        scores=np.where(valid,mu,-np.inf)
        indices=np.argsort(-scores,axis=1,kind='stable')[:,:20]
        rows=np.arange(k)[:,None];chosen=np.take_along_axis(valid,indices,axis=1)&(np.arange(20)[None,:]<slots[:,None])
        means=np.take_along_axis(mu,indices,axis=1);means=np.where(chosen,means,0)
        uncertainty=np.where(chosen,np.take_along_axis(unc,indices,axis=1),0)
        cur=np.take_along_axis(current,indices,axis=1)
        upp=np.full_like(cur,.1)*chosen
        chosen_buy=np.take_along_axis(buy,indices,axis=1)
        upp=np.where(chosen_buy,upp,np.minimum(upp,cur))
        selected_targets=np.zeros_like(cur);diagnostics={z:np.zeros(k) for z in ['objective','solver_residual','iterations']};diagnostics['status']=np.full(k,'NO_VALID_INPUT',dtype=object)
        for risk_name in RISKS:
            for optimizer in OPTIMIZERS:
                group=np.array([i for i,p in enumerate(paths) if p['risk']==risk_name and p['optimizer']==optimizer],int)
                if not len(group):continue
                ix=indices[group];cov=self.risk_cov[risk_name][ix[:,:,None],ix[:,None,:]]
                try:
                    if optimizer=='cvar':
                        scenarios=[];fixed_returns=[]
                        for i in group:
                            fixed_indices=np.flatnonzero(reserved[i]&present[i])
                            combined=list(indices[i])+[j for j in fixed_indices if j not in indices[i]]
                            key=(risk_name,tuple(combined))
                            if key not in self.scenario_cache:
                                names=[self.tickers[j] for j in combined]
                                self.scenario_cache[key]=self.risk.scenarios(risk_name,names,self.valid_day)
                            all_scen=self.scenario_cache[key]
                            residual=all_scen[:,:20].copy()
                            stream=paths[i]['stream']
                            if stream in DISTRIBUTIONS:
                                # Gaussian marginal forecasts imply normal-shaped
                                # margins, retaining contemporaneous joint ranks.
                                sd=np.std(residual,axis=0,ddof=1)
                                z=norm.ppf((rankdata(residual,axis=0)-.5)/len(residual))
                                residual=(z-z.mean(0))/np.maximum(z.std(0,ddof=1),1e-8)*sd
                            elif (self.date,stream) in self.streams.quantile_shapes:
                                shape=self.streams.quantile_shapes[(self.date,stream)][:,indices[i]]
                                sd=np.std(residual,axis=0,ddof=1);z=residual/np.maximum(sd,1e-8)
                                z=np.where(z<0,z*shape[0],z*shape[1]);z-=z.mean(0)
                                residual=z/np.maximum(z.std(0,ddof=1),1e-8)*sd
                            scenarios.append(residual)
                            fixed=np.array([current[i,j] if j in fixed_indices else 0. for j in combined])
                            fixed_returns.append(all_scen@fixed)
                        scen=np.asarray(scenarios)+means[group,None,:]
                        w,meta=solve_cvar(means[group],scen,cur[group],upp[group],budget[group],np.asarray(fixed_returns))
                    else:
                        fixed=np.where(reserved[group],current[group],0.)
                        cross=np.einsum('kin,kn->ki',self.risk_cov[risk_name][ix,:],fixed)
                        conditional_means=means[group]-4*cross
                        w,meta=solve_quadratic(conditional_means,cov,cur[group],upp[group],budget[group],uncertainty[group] if optimizer=='robust' else None)
                    if not np.isfinite(w).all():raise ValueError('NONFINITE_SOLVER_TARGET')
                    selected_targets[group]=w
                    for z in diagnostics:diagnostics[z][group]=meta[z]
                except Exception as e:
                    diagnostics['status'][group]='FAILED_PRESERVE_UNITS'
                    self.failures.append({'date':str(self.date),'risk':risk_name,'optimizer':optimizer,'reason':str(e),'strategies':[paths[i]['strategy'] for i in group]})
        targets=np.zeros_like(current);targets[rows,indices]=selected_targets
        # A prediction failure is an absent decision, never an implicit held-name exit.
        failed=diagnostics['status']=='FAILED_PRESERVE_UNITS';decided[failed]=False
        diagnostics['selected_count']=chosen.sum(1);diagnostics['raw_gross']=targets.sum(1)
        return targets,decided,diagnostics
    def __call__(self,day,context):
        self._reset(day,context);k=len(self.paths);n=len(self.tickers)
        # Fusion and component replacement share an account. Require all
        # contributing predictions before releasing any held name's reserve.
        context=context.copy()
        masks=context['decision_mask'].copy()
        for i,p in enumerate(self.paths):
            required=POINT if p['target_fusion']!='none' else [p['stream']]
            if p['axis']!='joint':required=list(required)+['ridge']
            for stream in required:masks[i]&=np.isfinite(self.streams.at(self.date,stream)).all(0)
        extra=(context['current_weights']>1e-12)&~masks&~context['reserved_mask']
        context['decision_mask']=masks
        context['reserved_mask']=context['reserved_mask']|extra
        context['available_slots']=np.maximum(0,context['available_slots']-extra.sum(1))
        context['available_weight']=np.maximum(0,context['available_weight']-(context['current_weights']*extra).sum(1))
        targets=np.zeros((k,n));decided=np.zeros((k,n),bool);raw=[]
        ordinary=[i for i,p in enumerate(self.paths) if p['target_fusion']=='none']
        for i in ordinary:
            if self.paths[i]['stream'] in self.streams.failures:raise RuntimeError(self.streams.failures[self.paths[i]['stream']])
        def subset(indices):
            return {name:(value[indices] if isinstance(value,np.ndarray) and value.ndim and len(value)==k else value) for name,value in context.items()}
        meta={z:np.zeros(k) for z in ['objective','solver_residual','iterations','selected_count','raw_gross']};meta['status']=np.full(k,'UNSET',dtype=object)
        if ordinary:
            a,d,m=self._solve([self.paths[i] for i in ordinary],subset(ordinary));targets[ordinary]=a;decided[ordinary]=d
            for name in m:meta[name][ordinary]=m[name]
        # Target experts optimize within each fusion account, not independent accounts.
        fusion_indices=[i for i,p in enumerate(self.paths) if p['target_fusion']!='none']
        if fusion_indices:
            expert_targets=[];expert_decisions=[];expert_meta=[]
            for member in POINT:
                expert_paths=[{**self.paths[i],'stream':member} for i in fusion_indices]
                a,d,m=self._solve(expert_paths,subset(fusion_indices));expert_targets.append(a);expert_decisions.append(d);expert_meta.append(m)
            tensor=np.asarray(expert_targets)
            for j,i in enumerate(fusion_indices):
                targets[i]=tensor[:,j,:].mean(0) if self.paths[i]['target_fusion']=='target_equal' else np.median(tensor[:,j,:],axis=0)
                decided[i]=np.logical_and.reduce(np.asarray(expert_decisions)[:,j,:],axis=0)
                meta['status'][i]='TARGET_EXPERT_FUSION';meta['raw_gross'][i]=targets[i].sum();meta['selected_count'][i]=(targets[i]>0).sum()
        reference_paths=[{**p,'stream':'ridge','risk':'diagonal','optimizer':'mean_variance'} for p in self.paths]
        reference,rd,_=self._solve(reference_paths,context)
        axes=[p['axis'] for p in self.paths]
        current=context['current_weights'];upper=np.full((k,n),.1)
        upper=np.where(context['buy_allowed_mask'],upper,np.minimum(upper,current))
        upper*=context['decision_mask']
        before=targets.copy();targets=isolate_axis(targets,reference,current,axes,upper,context['available_weight'])
        before_slot=targets.copy()
        # Target fusion/axis changes can broaden names: common capital and slot projection.
        for i in range(k):
            positive=np.flatnonzero(targets[i]>1e-12)
            ordered=sorted(positive,key=lambda j:(-targets[i,j],self.tickers[j]))
            targets[i,ordered[int(context['available_slots'][i]):]]=0
        for i,p in enumerate(self.paths):
            status=str(meta['status'][i]);self.solver_counts[status]=self.solver_counts.get(status,0)+1
            raw.append(dict(strategy_id=p['strategy'],signal_date=self.date,stream=p['stream'],risk=p['risk'],optimizer=p['optimizer'],axis=p['axis'],
                solver_status=status,objective=float(meta['objective'][i]),solver_residual=float(meta['solver_residual'][i]),iterations=int(meta['iterations'][i]),
                selected_count=int(meta['selected_count'][i]),raw_gross=float(meta['raw_gross'][i]),
                final_gross=float(targets[i].sum()),component_projection_l1=float(np.abs(targets[i]-before[i]).sum()),
                reference_gross=float(reference[i].sum()),gross_gap_vs_reference=float(targets[i].sum()-reference[i].sum()),
                axis_replacement_l1=float(np.abs(before_slot[i]-before[i]).sum()),slot_projection_l1=float(np.abs(targets[i]-before_slot[i]).sum()),
                prediction_file=f'predictions/streams/{self.stage}/{p["stream"]}.parquet'))
        for j,i in enumerate(fusion_indices):
            raw[i]['expert_solver_statuses']={member:str(expert_meta[a]['status'][j]) for a,member in enumerate(POINT)}
            raw[i]['expert_solver_residuals']={member:float(expert_meta[a]['solver_residual'][j]) for a,member in enumerate(POINT)}
            raw[i]['prediction_files']=[f'predictions/streams/{self.stage}/{m}.parquet' for m in POINT]
        result={'targets':targets,'decided':decided,'raw':raw}
        if fusion_indices:
            result['expert_targets']=tensor.transpose(1,0,2)
            result['expert_strategy_indices']=fusion_indices
            result['expert_names']=POINT
        return result
