"""R6 ex-ante finite method space; no data, model or account reads."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json
import numpy as np

ID = 'V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6'
YEARS = (2022,2023,2024,2025)
CAPS = dict(estimator_learned_state_fit=2500, deterministic_optimizer_policy_solve=20000, account_mechanism_paths=120, scientific_retry=0)
RISK = ('DCC','KALMAN','DYNAMIC_FACTOR','HUBER','TYLER','ROBUST_FACTOR','NONLINEAR','POET','GRAPHICAL','HIER_POSTERIOR','BAYES_FACTOR','POSTERIOR_PREDICTIVE','SEMIVARIANCE','EMPIRICAL_CVAR','EVT','AVERAGE')
Q = ('MV','GMV','CVAR','SEMIVARIANCE','MAD','ENTROPIC','ERC','RISK_PARITY','MAX_DIV','MIN_CORR','HRP','HERC','ROBUST_MV','ELLIPSOIDAL','COV_ROBUST','DRO','FRACTIONAL_KELLY','LOG_UTILITY','QUADRATIC_UTILITY','TURNOVER_MV','TURNOVER_CVAR','ENTROPY_TURNOVER','PROXIMAL')
ACTION = ('DIRECT','PARTIAL','SYMMETRIC_BAND','ASYMMETRIC_BAND','HYSTERESIS','TURNOVER_BUDGET','REPLACEMENT_COST','BENEFIT_COST','MPC','MIN_HOLD','COOLDOWN')
GROSS = ('FIXED1','VOL_TARGET','DOWNSIDE_TARGET','CVAR_TARGET','REGIME','DRAWDOWN','UNCERTAINTY','BREADTH','DISAGREEMENT','RIDGE','HGB','CATBOOST','MLP','QUANTILE')
FUSION = ('EQUAL','MEDIAN','SIMPLEX','NNLS','RIDGE_STACK','HGB_STACK','MLP_STACK','LINEAR_GATE','MLP_GATE','RESIDUAL')
UNCERTAINTY = ('POINT','LOWER_CONFIDENCE','Q10','DISAGREEMENT')
COVERAGE_STATUSES = frozenset(('TRIED_COMPLETE','TRIED_FAILED','BLOCKED_INPUT','BLOCKED_SOURCE','BLOCKED_ACCOUNT','EXACT_REUSE','NOT_APPLICABLE','NOT_INCLUDED_BY_FROZEN_SCOPE'))

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def action_recipes():
    return dict(rho=.5, symmetric_band=.0025, buy_band=.005, sell_band=.0025,
      uncertainty_hysteresis=.5, turnover_budget=.10, minimum_trade_usd=1.,
      min_hold_sessions=5, cooldown_trigger_l1=.25, cooldown_sessions=5,
      mpc_horizon=2, friction='actual one-way bps times USD notional',
      replacement='entrant utility - incumbent utility - explicit friction - declared marginal risk; coefficients fixed1',
      dd1_threshold=.10, dd1_multiplier=.5, dd2_full_reduction=.20,
      dd_window_sessions=63, vol_target_annual=.15, downside_target_annual=.10,
      effective_gross='min(grid controller G, continuous optimizer gross_cap); optimizer cap may be non-grid; report controller/cap/effective separately',
      cvar_target_5d=.03, uncertainty_ratio_limit=1., breadth_full_fraction=.5,
      disagreement_limit=.5, gross_grid=(0,.25,.5,.75,1),
      regime='past-only QQQ20D realized vol versus lagged252-session median and75% quantile; 3states only if252history, otherwise BLOCKED_INPUT; no two-state result-driven switch',
      tail='EXISTING_FROZEN_PAST_ONLY_TAIL_STATE_ONLY; exact source/version/availability receipt required; missing pre-existing binary state BLOCKED_SOURCE; no newly invented macro or threshold predictor',
      learned_gross_target='past-mature H5 utility over fixed grid: argmax(G*y_reference - .5*G^2*variance_reference - actual friction*abs(G-G_prior)); fixed EQUAL genuine-OOF top20 reference; diagonal PIT32 volatility proxy; previous reference G=1; all targets mature; not account NAV reward; no in-sample forecast or outer account feedback')

def policy_space():
    """Roles alias identical tuples; cost/current-dependent solves never alias."""
    roles, paths = [], {}
    base = dict(prediction='EQUAL',risk='AVERAGE',q='MV',action='DIRECT',gross='FIXED1',uncertainty='POINT',replacement='RPL0',drawdown='DD0',regime='NONE',tail='NONE',planner='NONE')
    def add(role, track, **changes):
        spec=base|changes
        requested_q=spec['q']
        spec['q']={'RISK_PARITY':'ERC','QUADRATIC_UTILITY':'MV'}.get(requested_q,requested_q)
        if spec['action']=='REPLACEMENT_COST' and 'replacement' not in changes:
            spec['replacement']='RPL1'
        key=digest(spec)
        if key not in paths: paths[key]=dict(path_id='R6_'+key[:12], specification=spec, primary_bps=10)
        roles.append(dict(role=role,track=track,path_id=paths[key]['path_id'],requested_q=requested_q,effective_q=spec['q'],exact_q_alias=requested_q!=spec['q']))
    for q in Q:add('Q_'+q,'q',q=q)
    # Curated joint rows, not a Cartesian product; predetermined cyclic blocks.
    for i,r in enumerate(RISK[:-1]):
        add('RISK_'+r,'risk',risk=r,q={'DCC':'MV','KALMAN':'RISK_PARITY','DYNAMIC_FACTOR':'MAX_DIV','EMPIRICAL_CVAR':'CVAR','POSTERIOR_PREDICTIVE':'ROBUST_MV'}.get(r,Q[(3*i+1)%len(Q)]),action={'DCC':'SYMMETRIC_BAND','ROBUST_FACTOR':'HYSTERESIS','EMPIRICAL_CVAR':'BENEFIT_COST','POSTERIOR_PREDICTIVE':'REPLACEMENT_COST'}.get(r,ACTION[(2*i+1)%len(ACTION)]),gross=GROSS[(3*i+1)%9])
    for i,a in enumerate(ACTION[1:]):
        add('ACTION_'+a,'action',action=a,risk='DYNAMIC_FACTOR' if a=='TURNOVER_BUDGET' else RISK[(3*i)%16],q=Q[(2*i+4)%23],gross=GROSS[(i+2)%9],regime='ACTION_BUDGET_CONDITIONED' if a=='TURNOVER_BUDGET' else 'NONE', planner='TWO_STEP' if a=='MPC' else 'NONE')
    for i,g in enumerate(GROSS[1:]):
        add('GROSS_'+g,'gross',gross=g,risk={'CVAR_TARGET':'EMPIRICAL_CVAR','UNCERTAINTY':'POSTERIOR_PREDICTIVE','DISAGREEMENT':'AVERAGE'}.get(g,RISK[(2*i+1)%16]),q=Q[(3*i+7)%23],action=ACTION[(i+3)%11])
    add('RPL0','replacement',replacement='RPL0',action='REPLACEMENT_COST')
    for rpl in ('RPL1','RPL2','RPL3','RPL4'):add(rpl,'replacement',replacement=rpl,action='REPLACEMENT_COST',risk='EMPIRICAL_CVAR' if rpl=='RPL3' else 'POSTERIOR_PREDICTIVE' if rpl=='RPL4' else 'AVERAGE')
    for i,u in enumerate(UNCERTAINTY[1:]):add('UNCERTAINTY_'+u,'uncertainty',uncertainty=u,q=('MV','CVAR','ROBUST_MV')[i],prediction='DISTRIBUTION_ENSEMBLE' if u=='Q10' else 'EQUAL')
    for i,f in enumerate(FUSION):add('FUSION_'+f,'fusion',prediction=f,q=('MV','RISK_PARITY','CVAR','ROBUST_MV')[i%4])
    for dd in ('DD1','DD2'):add(dd,'drawdown',gross='DRAWDOWN',drawdown=dd)
    for p in ('TCN','GRU','LSTM','TEMPORAL_MLP','LAG_LINEAR','BAYESIAN_RIDGE'):add('OPPORTUNITY_'+p,'opportunity',prediction=p)
    add('REGIME_Q','regime',q='RISK_PARITY',risk='DYNAMIC_FACTOR',regime='RISK_CONDITIONED')
    add('REGIME_BAND','regime',action='SYMMETRIC_BAND',regime='BAND_CONDITIONED')
    add('TAIL_NO_TRADE','tail',action='SYMMETRIC_BAND',risk='EMPIRICAL_CVAR',tail='ELEVATED_BAND')
    add('DP_ANCHOR','planner',action='MPC',planner='TWO_STEP')
    for name in ('CONTROL_RAW_A2_POLICY','JOINT_SIMPLE_EQUAL'):
        key=digest(dict(control=name))
        paths[key]=dict(path_id=name,specification=dict(control=name),primary_bps=10)
        roles.append(dict(role=name,track='control',path_id=name))
    unique=list(paths.values())
    # Twelve ex-ante matched friction anchors; no winner-driven sensitivities.
    sens_roles=('CONTROL_RAW_A2_POLICY','JOINT_SIMPLE_EQUAL','Q_MV','Q_CVAR','Q_RISK_PARITY','Q_ROBUST_MV','Q_TURNOVER_MV','Q_TURNOVER_CVAR','DD1','DD2','OPPORTUNITY_TCN','OPPORTUNITY_BAYESIAN_RIDGE')
    byrole={r['role']:r['path_id'] for r in roles}
    for role in sens_roles:
        primary=next(p for p in unique if p['path_id']==byrole[role])
        for cost in (5,20):
            unique.append(dict(path_id=primary['path_id']+f'@{cost}bps',specification=primary['specification'],primary_bps=cost,sensitivity_parent=primary['path_id']))
    joint=[r for r in roles if r['track'] in ('risk','action','gross')]
    assert len(joint)<=48 and len(joint)>=30
    assert len(unique)<=CAPS['account_mechanism_paths']
    return dict(roles=roles,physical_paths=unique,joint_roles=[r['role'] for r in joint],sensitivity_roles=sens_roles)

def clock_from_metadata(support):
    """Global source/UID structural events and monthly first session; no values."""
    assert support['numeric_reads']==0 and support['outcome_reads']==0 and support['test2026_rows_read']==0
    days=[row['decision_date'] for row in support['daily_support_chain']]
    if len(days)!=len(set(days)) or days!=sorted(days) or any(d>='2026-01-01' for d in days):raise ValueError('PRE2026_UNIQUE_MONOTONE_METADATA_ONLY')
    first={}
    for day in days:first.setdefault(day[:7],day)
    structural={row['decision_date'] for row in support['events']}
    return dict(decision_dates=days,q_dates=sorted(structural|set(first.values())),monthly_dates=list(first.values()),structural_dates=sorted(structural),daily_action_evaluations=len(days),target_clock_semantics='MONTHLY_FIRST_OR_OBSERVED_METADATA_STRUCTURAL_CHANGE; carry ex-ante target between anchors; daily forecast only used in action/Gross gate; not legacy daily target equivalence')

def budget_proof(space, clock, learned_components):
    n=len(space['physical_paths']); days=len(clock['decision_dates']); anchors=len(clock['q_dates'])
    # Each method has at most one whole-objective backend per target update.
    # HERC is frozen binary analytical sibling allocation, with no hidden solves.
    mpc=sum(p['specification'].get('action')=='MPC' for p in space['physical_paths'])
    solves=n*anchors+mpc*days
    result=dict(fits=sum(learned_components.values()),fit_components=learned_components,policy_solves_upper=solves,account_paths_upper=n,scientific_retry=0,q_anchor_count=anchors,mpc_paths=mpc,mpc_additional_solves_upper=mpc*days,deterministic_state_evaluations_upper=n*days,preprocessing_selection_failed_fits_nonrefundable=True,inner_numerical_iterations='separate physical counter, not extra independently chosen models; all complete optimizer/backend invocations debited',risk_recursive_updates='separate deterministic/posterior counter; any fresh parameter estimation gets fit debit')
    if result['fits']>2500 or solves>20000 or n>120:raise ValueError('FROZEN_PHYSICAL_BUDGET_EXCEEDED')
    return result

@dataclass
class BudgetCounter:
    counts: dict
    def reserve(self,kind,units=1):
        if kind not in CAPS or type(units) is not int or units<0:raise ValueError('EXACT_DEBIT_UNIT_REQUIRED')
        value=self.counts.get(kind,0)+units
        if value>CAPS[kind]:raise ValueError('BUDGET_EXHAUSTED_WITH_FROZEN_QUEUE')
        self.counts[kind]=value
        return value
