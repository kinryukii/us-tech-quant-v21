"""Couple learned state/action values and frozen correlated portfolio risk."""
import numpy as np
from joint_linear_tree import load_policy, mapped_features, predict_values, ACTIONS, FEATURES
from risk import FrozenRisk

class JointRiskPolicy:
    def __init__(self,factor=False):
        self.base=load_policy('hgb');self.risk=FrozenRisk();self.factor=factor;self.last_diagnostic={}
    def __call__(self,day,weights,cash,held_age=None):
        if day.empty:return {}
        day=day.sort_values('ticker',kind='stable').reset_index(drop=True)
        x=day[FEATURES].to_numpy(float);names=day.ticker.tolist();n=len(names)
        current=np.array([weights.get(t,0.) for t in names])
        age=np.array([(held_age or {}).get(t,0.) for t in names])
        values=mapped_features(np.repeat(x,5,axis=0),np.repeat(current,5),np.full(n*5,cash),np.repeat(age,5),np.tile(ACTIONS,n))
        q=predict_values(self.base.models['hgb'],'hgb',values).reshape(n,5)
        initial=self.base(day,weights,cash,held_age)
        w=np.array([initial.get(t,0.) for t in names])
        allowed=day.new_buy_eligible.to_numpy(bool)[:,None]|(ACTIONS[None,:]<=current[:,None]+1e-10)
        c=self.risk.covariance_for(names,factor=self.factor)
        cw=c@w
        initial_q=float(q[np.arange(n),np.rint(w/.025).astype(int)].sum()-5*w@cw)
        changes=0
        # Fixed bounded coordinate ascent, no return-based candidate prescreen.
        for iteration in range(4):
            changed=0
            for i in range(n):
                old=w[i];delta=ACTIONS-old
                feasible=(w.sum()+delta<=.95000001)&(((w>1e-9).sum()-(old>1e-9)+(ACTIONS>0))<=20)&allowed[i]
                idx=int(round(old/.025))
                improvement=q[i]-q[i,idx]-5*(2*delta*cw[i]+delta**2*c[i,i])
                improvement[~feasible]=-np.inf
                best=int(np.argmax(improvement))
                if improvement[best]>1e-10:
                    cw+=delta[best]*c[:,i];w[i]=ACTIONS[best];changed+=1
            changes+=changed
            if changed==0:break
        final_q=float(q[np.arange(n),np.rint(w/.025).astype(int)].sum()-5*w@c@w)
        assert final_q>=initial_q-1e-8
        self.last_diagnostic=dict(iterations=iteration+1,coordinate_changes=changes,initial_utility=initial_q,
            final_utility=final_q,predicted_daily_variance=float(w@c@w),factor=self.factor,
            unknown_risk_names=sum(t not in self.risk.lookup for t in names),solver='bounded_coordinate_ascent_not_global_optimum')
        return {t:float(v) for t,v in zip(names,w) if v>0}
