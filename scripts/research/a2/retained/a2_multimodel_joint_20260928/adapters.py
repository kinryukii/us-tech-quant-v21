"""Versioned policy adapters with explicit decisions and reserved holdings."""
from pathlib import Path
import sys
import numpy as np
import torch

ROOT=Path(__file__).resolve().parent
FROZEN=ROOT
sys.path.insert(0,str(FROZEN))
import values as value_models
from risk_aux import FrozenRisk
from neural import NeuralAdapter, project
from engine_v2 import HoldingAwareDecision, OperationalExit


class PolicyV2:
    def __init__(self,name,stage='final',operational_events=None):
        self.name=name;self.stage=stage;self.age={};self.risk=None
        self.operational_events=operational_events
        if name=='ensemble_equal_weight':
            self.members={key:PolicyV2(key,stage) for key in
                ['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb','joint_quantile_risk','joint_mlp']}
        elif name=='ensemble_stacked':
            from ensemble import StackedPolicy
            self.stack=StackedPolicy(stage=stage)
        elif name=='joint_mlp':self.neural=NeuralAdapter('direct',stage=stage)
        elif name=='joint_rl_ensemble':self.neural=NeuralAdapter('rl',stage=stage)
        elif name=='joint_rl_zero_control':self.neural=NeuralAdapter('rl',zero=True,stage=stage)
        elif name=='cash_control':pass
        else:
            value_name='hgb' if name in ['joint_hgb_lw','joint_hgb_pca'] else name.removeprefix('joint_')
            self.value=value_models.load_policy(value_name,stage=stage)
            if name in ['joint_hgb_lw','joint_hgb_pca']:
                # Each evaluation stage uses its separately fitted covariance.
                self.risk=FrozenRisk(stage=stage)

    def __call__(self,day,ctx):
        self.age={t:self.age.get(t,0)+1 for t,v in ctx.current_weights.items() if v>0}
        day=day.loc[day.new_buy_eligible.astype(bool)|day.ticker.map(ctx.current_weights).fillna(0).gt(0)]
        day=day.sort_values('ticker',kind='stable').reset_index(drop=True)
        names=day.ticker.tolist()
        raw={};decisions={str(t):0. for t in names}
        if names:
            if hasattr(self,'members'):
                member_outputs={key:actor(day,ctx).model_decisions for key,actor in self.members.items()}
                combined={t:sum(output.get(t,0.) for output in member_outputs.values())/len(self.members) for t in names}
                keep=set(sorted(names,key=lambda t:(-combined[t],t))[:ctx.available_slots])
                decisions={t:combined[t] if t in keep else 0. for t in names}
                raw={t:{'member_targets':{key:output.get(t,0.) for key,output in member_outputs.items()},
                        'equal_weight_target':decisions[t]} for t in names}
            elif hasattr(self,'stack'):
                current=np.array([ctx.current_weights.get(t,0.) for t in names])
                age=np.array([self.age.get(t,0.) for t in names])
                scores=self.stack.score_actions(day,current,ctx.cash_weight,age)
                acts=value_models.ACTIONS
                eligible=day.new_buy_eligible.to_numpy(bool)&~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
                allowed=eligible[:,None]|(acts[None,:]<=current[:,None]+1e-10)
                _,chosen=value_models.allocate_joint_scores(scores,names,max_names=ctx.available_slots,
                    max_units=min(38,int(np.floor((ctx.available_weight+1e-12)/.025))),allowed=allowed)
                decisions={t:float(acts[a]) for t,a in zip(names,chosen)}
                raw={t:{'stacked_action_values':scores[i].tolist(),'chosen_weight':decisions[t]} for i,t in enumerate(names)}
            elif self.name=='cash_control':
                pass
            elif hasattr(self,'neural'):
                decisions,raw=self._neural(day,ctx)
            else:decisions,raw=self._values(day,ctx)
        else:decisions={}
        ops={}
        if self.operational_events is not None:
            for r in self.operational_events.itertuples():
                if r.ticker in ctx.current_units and r.known_at<=ctx.signal_asof and r.effective_date<=ctx.signal_date:
                    ops[str(r.ticker)]=OperationalExit(reason=str(r.reason),known_at=r.known_at,source_id=str(r.source_id))
        return HoldingAwareDecision(model_decisions=decisions,operational_exits=ops,raw_model_outputs=raw)

    def _neural(self,day,ctx):
        n=len(day)
        x=np.clip((day[value_models.FEATURES].to_numpy(float)-self.neural.mean)/self.neural.scale,-8,8)
        current=np.array([ctx.current_weights.get(t,0.) for t in day.ticker])
        obs=torch.tensor(np.column_stack([x,current,np.repeat(ctx.cash_weight,n),current>0]),dtype=torch.float32)
        eligible=day.new_buy_eligible.to_numpy(bool)&~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
        upper=torch.tensor(np.where(eligible,.1,np.minimum(current,.1)),dtype=torch.float32)
        with torch.no_grad():
            logits=[m(obs) for m in self.neural.models]
            weights=torch.stack([project(v,upper=upper,max_names=ctx.available_slots,max_exposure=ctx.available_weight)
                                 for v in logits]).mean(dim=0).numpy()
        keep=np.argsort(-weights,kind='stable')[:ctx.available_slots]
        mask=np.zeros(n);mask[keep]=1;weights*=mask
        if weights.sum()>ctx.available_weight:weights*=ctx.available_weight/weights.sum()
        raw={str(t):{'logits':[float(v[i]) for v in logits],'projected_weight':float(weights[i])}
             for i,t in enumerate(day.ticker)}
        return {str(t):float(w) for t,w in zip(day.ticker,weights)},raw

    def _values(self,day,ctx):
        names=day.ticker.tolist();n=len(day);acts=value_models.ACTIONS
        x=day[value_models.FEATURES].to_numpy(float)
        current=np.array([ctx.current_weights.get(t,0.) for t in names])
        age=np.array([self.age.get(t,0.) for t in names])
        features=value_models.mapped_features(np.repeat(x,5,axis=0),np.repeat(current,5),
            np.full(n*5,ctx.cash_weight),np.repeat(age,5),np.tile(acts,n))
        if self.value.name=='quantile_risk':
            q=np.column_stack([value_models.predict_values(self.value.models[k],k,features) for k in ['q10','q50','q90']])
            q.sort(axis=1);flat=q[:,1]-.25*(q[:,1]-q[:,0])
        else:flat=value_models.predict_values(self.value.models[self.value.name],self.value.name,features)
        scores=flat.reshape(n,5)
        eligible=day.new_buy_eligible.to_numpy(bool)&~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
        allowed=eligible[:,None]|(acts[None,:]<=current[:,None]+1e-10)
        _,selected=value_models.allocate_joint_scores(scores,names,max_names=ctx.available_slots,
            max_units=min(38,int(np.floor((ctx.available_weight+1e-12)/.025))),allowed=allowed)
        weights=acts[selected].copy()
        if self.risk is not None:
            locked=list(ctx.reserved_tickers)
            c=self.risk.covariance_for(names+locked,factor=self.name.endswith('pca'))
            full=np.r_[weights,[ctx.reserved_weights[t] for t in locked]]
            cw=c@full
            for _ in range(4):
                changes=0
                for i in range(n):
                    old=full[i];delta=acts-old;idx=int(round(old/.025))
                    feasible=(full[:n].sum()+delta<=ctx.available_weight+1e-8)&(
                        ((full[:n]>1e-9).sum()-(old>1e-9)+(acts>0))<=ctx.available_slots)&allowed[i]
                    gain=scores[i]-scores[i,idx]-5*(2*delta*cw[i]+delta**2*c[i,i])
                    gain[~feasible]=-np.inf;best=int(np.argmax(gain))
                    if gain[best]>1e-10:cw+=delta[best]*c[:,i];full[i]=acts[best];changes+=1
                if changes==0:break
            weights=full[:n]
        raw={str(t):{'action_values':scores[i].tolist(),'chosen_weight':float(weights[i])} for i,t in enumerate(names)}
        return {str(t):float(w) for t,w in zip(names,weights)},raw

