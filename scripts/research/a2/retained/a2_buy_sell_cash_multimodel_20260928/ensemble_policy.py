"""Heterogeneous decision ensembles sharing one causal account state."""
import numpy as np
from adapters import PolicyV2
from engine_v2 import HoldingAwareDecision
from risk_aux import FrozenRisk

MEMBERS=['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb','joint_quantile_risk','joint_mlp']

def blend_targets(matrix, coefficients, names, *, slots=20, budget=.95, consensus=False):
    matrix=np.asarray(matrix,float);coefficients=np.asarray(coefficients,float)
    assert matrix.shape==(len(names),len(coefficients))
    assert np.isfinite(matrix).all() and np.all(matrix>=-1e-10)
    assert np.isfinite(coefficients).all() and np.all(coefficients>=0)
    assert abs(coefficients.sum()-1)<1e-8
    mean=matrix@coefficients
    dispersion=np.sqrt(((matrix-mean[:,None])**2)@coefficients)
    weights=mean/(1+dispersion/(mean+.01)) if consensus else mean.copy()
    weights=np.minimum(weights,.1)
    keep=np.argsort(-weights,kind='stable')[:slots]
    mask=np.zeros(len(names));mask[keep]=1;weights*=mask
    if weights.sum()>budget:weights*=budget/weights.sum()
    return weights,mean,dispersion

def risk_scale(weights,locked,covariance,limit=.015):
    """Only reduce active weights; preserve capital in nondecidable holdings."""
    weights=np.asarray(weights,float);locked=np.asarray(locked,float)
    def variance(scale):
        full=np.r_[weights*scale,locked]
        return float(full@covariance@full)
    if variance(0)>limit**2:return 0.
    if variance(1)<=limit**2:return 1.
    lo,hi=0.,1.
    for _ in range(60):
        mid=(lo+hi)/2
        if variance(mid)<=limit**2:lo=mid
        else:hi=mid
    return lo

class EnsemblePolicy:
    def __init__(self,name,stage='final'):
        assert name in ['ensemble_equal','ensemble_consensus_risk','ensemble_stacked']
        self.name=name;self.stage=stage
        self.members=[PolicyV2(n,stage=stage) for n in MEMBERS]
        if name=='ensemble_stacked':
            from ensemble_train import load_weights
            c=load_weights(stage);self.coefficients=np.array([c[n] for n in MEMBERS])
        else:self.coefficients=np.repeat(1/len(MEMBERS),len(MEMBERS))
        self.risk=FrozenRisk(stage) if name=='ensemble_consensus_risk' else None

    def __call__(self,day,ctx):
        names=sorted(day.ticker.astype(str).unique())
        if not names:return HoldingAwareDecision()
        opinions=[p(day,ctx).model_decisions for p in self.members]
        # A missing model decision must not be converted into an explicit sale.
        common=[t for t in names if all(t in o for o in opinions)]
        extra_locked=[t for t,w in ctx.current_weights.items() if w>0 and t not in common
                      and t not in ctx.reserved_tickers and t not in ctx.planned_operational_exits]
        extra_weight=sum(ctx.current_weights[t] for t in extra_locked)
        slots=max(0,ctx.available_slots-len(extra_locked))
        budget=max(0.,ctx.available_weight-extra_weight)
        matrix=np.array([[o[t] for o in opinions] for t in common],float).reshape(len(common),len(MEMBERS))
        weights,mean,std=blend_targets(matrix,self.coefficients,common,slots=slots,
                                      budget=budget,consensus=self.risk is not None)
        scale=1.
        if self.risk is not None and len(common):
            locked=list(ctx.reserved_tickers)+extra_locked
            covariance=self.risk.covariance_for(common+locked)
            scale=risk_scale(weights,[ctx.current_weights[t] for t in locked],covariance)
            weights*=scale
        raw={t:dict(member_names=MEMBERS,member_targets=matrix[i].tolist(),
                    coefficients=self.coefficients.tolist(),mean_target=float(mean[i]),
                    disagreement=float(std[i]),risk_scale=scale,ensemble_target=float(weights[i]))
             for i,t in enumerate(common)}
        return HoldingAwareDecision(model_decisions=dict(zip(common,weights)),raw_model_outputs=raw)
