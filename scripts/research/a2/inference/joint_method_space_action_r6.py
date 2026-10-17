"""New R6 deterministic action/Gross primitives over the shared account API.

Callers bind legal prefix states and existing q/cap projection; no market reader,
fill, mark, fee, cash or entitlement implementation is duplicated here.
"""
from __future__ import annotations
import numpy as np
from scripts.research.a2.evaluation.joint_method_space_design_r6 import action_recipes
SPEC=action_recipes()
GRID=np.asarray(SPEC['gross_grid'],float)

def _finite(*values):
    if any(not np.isfinite(np.asarray(v,float)).all() for v in values):raise ValueError('BLOCKED_INPUT_NONFINITE_LEGAL_STATE')

def quantize_gross(value):
    _finite(value)
    if not 0<=float(value)<=1:raise ValueError('GROSS_OUTSIDE_NO_LEVERAGE_DOMAIN')
    # Nearest grid with conservative smaller-G tie.
    return float(GRID[np.argmin(np.abs(GRID-float(value)))])

def replacement_utility(kind, entrant, incumbent, *, friction, marginal_variance=0., marginal_tail=0., entrant_sigma=0., incumbent_sigma=0.):
    _finite(entrant,incumbent,friction,marginal_variance,marginal_tail,entrant_sigma,incumbent_sigma)
    if min(friction,entrant_sigma,incumbent_sigma)<0:raise ValueError('INVALID_COST_OR_UNCERTAINTY')
    if kind=='RPL0':return float(entrant-incumbent)
    if kind=='RPL1':return float(entrant-incumbent-friction)
    if kind=='RPL2':return float(entrant-incumbent-friction-marginal_variance)
    if kind=='RPL3':return float(entrant-incumbent-friction-marginal_tail)
    if kind=='RPL4':return float((entrant-entrant_sigma)-(incumbent-incumbent_sigma)-friction)
    raise ValueError('UNREGISTERED_REPLACEMENT')

def uncertainty_mu(kind,mu,*,sigma=None,q10=None,disagreement=None):
    mu=np.asarray(mu,float);_finite(mu)
    if kind=='POINT':return mu.copy()
    value={'LOWER_CONFIDENCE':sigma,'Q10':q10,'DISAGREEMENT':disagreement}.get(kind)
    if value is None:raise ValueError('BLOCKED_INPUT_TYPED_UNCERTAINTY')
    value=np.asarray(value,float);_finite(value)
    if value.shape!=mu.shape:raise ValueError('UNCERTAINTY_COORDINATE_MISMATCH')
    if kind=='Q10':return value.copy()
    if np.any(value<0):raise ValueError('NEGATIVE_UNCERTAINTY')
    return mu-value

def gross_value(kind,*,portfolio_vol=None,downside_vol=None,cvar=None,regime=None,drawdown=0.,sigma=None,mu=None,breadth=None,disagreement=None,learned=None,dd='DD0'):
    if kind=='FIXED1':value=1.
    elif kind=='VOL_TARGET':
        _finite(portfolio_vol)
        if portfolio_vol<0:raise ValueError('NEGATIVE_RISK')
        value=min(1.,SPEC['vol_target_annual']/max(float(portfolio_vol),1e-12))
    elif kind=='DOWNSIDE_TARGET':
        _finite(downside_vol);value=min(1.,SPEC['downside_target_annual']/max(float(downside_vol),1e-12))
    elif kind=='CVAR_TARGET':
        _finite(cvar);value=min(1.,SPEC['cvar_target_5d']/max(float(cvar),1e-12))
    elif kind=='REGIME':
        if regime not in ('LOW_VOL','NORMAL','HIGH_VOL'):raise ValueError('BLOCKED_INPUT_REGIME')
        value={'LOW_VOL':1.,'NORMAL':.75,'HIGH_VOL':.5}[regime]
    elif kind=='DRAWDOWN':
        _finite(drawdown)
        if drawdown<0:raise ValueError('NEGATIVE_DRAWDOWN')
        value=(1. if dd=='DD0' else .5 if dd=='DD1' and drawdown>=SPEC['dd1_threshold'] else 1. if dd=='DD1' else max(0.,1.-drawdown/SPEC['dd2_full_reduction']) if dd=='DD2' else None)
        if value is None:raise ValueError('UNREGISTERED_DRAWDOWN')
    elif kind=='UNCERTAINTY':
        _finite(sigma,mu)
        if sigma<0:raise ValueError('NEGATIVE_UNCERTAINTY')
        value=max(0.,min(1.,max(float(mu),0)/(float(sigma)+1e-12)))
    elif kind=='BREADTH':
        _finite(breadth)
        if not 0<=breadth<=1:raise ValueError('INVALID_BREADTH')
        value=min(1.,breadth/SPEC['breadth_full_fraction'])
    elif kind=='DISAGREEMENT':
        _finite(disagreement)
        if disagreement<0:raise ValueError('NEGATIVE_DISAGREEMENT')
        value=1./(1.+disagreement/SPEC['disagreement_limit'])
    elif kind in ('RIDGE','HGB','CATBOOST','MLP','QUANTILE'):
        if learned is None:raise ValueError('BLOCKED_INPUT_GROSS_LEARNED_STATE')
        _finite(learned);value=float(np.clip(learned,0,1))
    else:raise ValueError('UNREGISTERED_GROSS')
    return quantize_gross(value)

class StatefulActionMemory:
    """Persistent prefix state; one instance per physical account, no year reset."""
    def __init__(self):self.cooldown_until=-1;self.nav_prefix=[];self.last_session=-1
    def observe(self,session,nav):
        _finite(nav)
        if session!=self.last_session+1 or nav<=0:raise ValueError('CONTINUOUS_LEGAL_ACCOUNT_PREFIX_REQUIRED')
        self.last_session=session;self.nav_prefix.append(float(nav))
        del self.nav_prefix[:-SPEC['dd_window_sessions']]
        return float(1.-nav/max(self.nav_prefix))
    def record_realized_turnover(self,session,l1):
        _finite(l1)
        if l1<0 or session>self.last_session:raise ValueError('PAST_REALIZED_TURNOVER_REQUIRED')
        if l1>=SPEC['cooldown_trigger_l1']:self.cooldown_until=session+SPEC['cooldown_sessions']

def action_target(kind,current,target,*,nav,cost_bps,mu,sigma,holding_age,session=0,memory=None,regime='NORMAL',tail_elevated=False,on_evaluation=None):
    current,target,mu,sigma,age=map(lambda x:np.asarray(x,float),(current,target,mu,sigma,holding_age))
    _finite(current,target,nav,cost_bps,mu,sigma,age)
    if any(x.shape!=current.shape for x in (target,mu,sigma,age)) or nav<=0 or cost_bps<0 or np.any(current<0) or np.any(target<0) or np.any(sigma<0):raise ValueError('ACTION_COORDINATE_OR_STATE_INVALID')
    delta=target-current; result=target.copy(); one_way=cost_bps/10000.
    tiny=np.abs(delta)*nav<SPEC['minimum_trade_usd']
    band=SPEC['symmetric_band']*(2. if regime=='HIGH_VOL' or tail_elevated else 1.)
    if kind=='DIRECT':pass
    elif kind=='PARTIAL':result=current+SPEC['rho']*delta
    elif kind=='SYMMETRIC_BAND':tiny|=np.abs(delta)<band
    elif kind=='ASYMMETRIC_BAND':tiny|=np.abs(delta)<np.where(delta>0,SPEC['buy_band'],SPEC['sell_band'])
    elif kind=='HYSTERESIS':tiny|=(np.abs(mu)<=SPEC['uncertainty_hysteresis']*sigma)
    elif kind=='TURNOVER_BUDGET':result=current+delta*min(1.,(SPEC['turnover_budget']*(.5 if regime=='HIGH_VOL' else 1.))/max(np.abs(delta).sum(),1e-12))
    elif kind=='REPLACEMENT_COST':tiny|=(delta>0)&(mu<=2.*one_way)
    elif kind=='BENEFIT_COST':tiny|=delta*mu<=np.abs(delta)*one_way
    elif kind=='MIN_HOLD':tiny|=(delta<0)&(current>0)&(age<SPEC['min_hold_sessions'])
    elif kind=='COOLDOWN':
        if memory is None:raise ValueError('BLOCKED_ACCOUNT_CONTINUOUS_COOLDOWN_STATE')
        if session<=memory.cooldown_until:tiny|=delta>0
    elif kind=='MPC':raise ValueError('CALL_TWO_STEP_PLANNER_WITH_RISK_REQUIRED')
    else:raise ValueError('UNREGISTERED_ACTION')
    result[tiny]=current[tiny]
    if on_evaluation:on_evaluation('DETERMINISTIC_ACTION_STATE_EVALUATION',1)
    # Shared caller still applies locked holdings, buy masks and capped simplex;
    # this primitive never certifies feasibility or invents fills.
    return result

def two_step_planner(current,target,mu,covariance,*,cost_bps,on_solve=None,on_evaluation=None):
    current,target,mu,covariance=map(lambda x:np.asarray(x,float),(current,target,mu,covariance))
    _finite(current,target,mu,covariance,cost_bps)
    if current.shape!=target.shape or mu.shape!=target.shape or covariance.shape!=(len(mu),len(mu)) or cost_bps<0:raise ValueError('MPC_COORDINATE_INVALID')
    if on_solve:on_solve('MPC_TWO_STEP_WHOLE_POLICY_SOLVE',1)
    # Frozen finite action set, not fitted hyperparameters: stay/half/full target.
    fractions=(0.,.5,1.);best=None;one_way=cost_bps/10000.
    for a in fractions:
        w1=current+a*(target-current)
        for b in fractions:
            w2=w1+b*(target-w1)
            utility=float(mu@(w1+w2)-.5*(w1@covariance@w1+w2@covariance@w2)-one_way*(np.abs(w1-current).sum()+np.abs(w2-w1).sum()))
            if on_evaluation:on_evaluation('MPC_FINITE_BRANCH_EVALUATION',1)
            key=(utility,-a,-b)
            if best is None or key>best[0]:best=(key,w1)
    return best[1].copy()
