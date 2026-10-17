"""Pure R10 frozen mechanism diagnostics and resolver projection.

The unique training/evaluation owners retain their calculations. Pure helpers
consume admitted frames; completion reads only SHA/footer-guarded own-run outputs.
No fit, account creation or authority promotion is performed.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.special import ndtr,logsumexp
from scripts.research.a2.training import stateful_mechanism_inputs as inputs

RECIPES=tuple('P'+str(i) for i in range(12))
GRID=(0.,.25,.5,.75,1.)
BUFFER=.0001
FRICTION=.001
SIGMA_K=1.
RISK_K=1.
PARTIAL=.5
VOL_TARGET=.02
EPS=1e-12
INTERACTIONS=(
    ('R1 vsR0 ENTRY','R1 ENTRY','R0 ENTRY'),
    ('R2 vsR0 ENTRY','R2 ENTRY','R0 ENTRY'),
    ('R3 vsR0 ENTRY','R3 ENTRY','R0 ENTRY'),
    ('R4 vsR0 ENTRY','R4 ENTRY','R0 ENTRY'),
    ('R5 vsR0 ENTRY','R5 ENTRY','R0 ENTRY'),
    ('R6 vsR0 ENTRY','R6 ENTRY','R0 ENTRY'),
    ('R7 vsR0 ENTRY','R7 ENTRY','R0 ENTRY'),
    ('R1 vsR0 REPLACE','R1 REPLACE','R0 REPLACE'),
    ('R2 vsR0 REPLACE','R2 REPLACE','R0 REPLACE'),
    ('R3 vsR0 REPLACE','R3 REPLACE','R0 REPLACE'),
    ('R4 vsR0 REPLACE','R4 REPLACE','R0 REPLACE'),
    ('R7 vsR0 REPLACE','R7 REPLACE','R0 REPLACE'),
    ('R4 vsR0 SELL/HOLD','R4 SELL/HOLD','R0 SELL/HOLD'),
    ('R5 vsR0 CONTINUATION','R5 CONTINUATION','R0 CONTINUATION'),
    ('P7 vsP6 UNCERTAINTY_WITH_RISK','P7','P6'),
    ('P3 vsP0 NO_TRADE_BUFFER','P3','P0'),
    ('P10 vsP8 UNCERTAINTY_GROSS','P10','P8'),
    ('P11 vsP8 REGIME_GROSS','P11','P8'),
    ('P4 vsP6 RISK_HYSTERESIS','P4','P6'),
    ('FIXED10_ACTION_REPLACE_FRICTION_5_20_SENSITIVITY',None,None),
)
QUESTIONS=(
    '哪些算法以前已经训练过，哪些本轮是真正的新问题？',
    'Risk state 是否提高了动作价值学习？',
    '哪种风险 representation 的跨年表现最稳定？',
    'Risk 是否仅降低动作频率，而没有改善 decision quality？',
    'Uncertainty gate 是否减少错误 replacement？',
    'Duration/hazard 是否提供独立于 Raw rank 的 continuation signal？',
    'Multi-horizon action value 是否跨年稳定？',
    'Sequence 相对 matched static state 是否有增量？',
    'Fusion 是否优于预注册成员？',
    'Gross/Cash 是否有稳定机制支持？',
    '哪些模型 2024 正向但 2025 失效？',
    '是否存在 MECHANISM_SUPPORTED？',
    '为什么仍不能称为真实账户 winner？',
    '1200 physical-fit 预算实际使用多少？',
    '是否保持不自动建立 R11？',
)


def _owner(owner):
    if owner is not None:return owner
    from scripts.research.a2.training import stateful_mechanism
    return stateful_mechanism


def _guard(frame):
    if 'signal_date' not in frame:raise ValueError('SIGNAL_DATE_REQUIRED')
    inputs._pre2026(frame.signal_date)
    if 'label_mature_date' in frame:inputs._pre2026(frame.label_mature_date,nullable=True)
    if 'sample_id' in frame and frame.sample_id.duplicated().any():
        raise ValueError('DUPLICATE_SAMPLE_ID')


def _array(prediction,key,n):
    value=prediction.get(key)
    if value is None:return np.full(n,np.nan)
    out=np.asarray(value,float)
    if out.shape!=(n,):raise ValueError('PREDICTION_SHAPE_'+key)
    return out.copy()


def _literal(values):
    return np.asarray([isinstance(v,(bool,np.bool_)) and bool(v) for v in values],bool)


def _aligned(frame,other,columns,qualified_column=None):
    n=len(frame)
    if other is None:return {c:np.full(n,np.nan) for c in columns},np.zeros(n,bool)
    if other.empty:return {c:np.full(n,np.nan) for c in columns},np.zeros(n,bool)
    _guard(other)
    keys=['signal_date','sample_id']
    if not set(keys).issubset(other):raise ValueError('SOURCE_JOIN_KEYS_REQUIRED')
    if other.duplicated(keys).any():raise ValueError('SOURCE_JOIN_NOT_ONE_TO_ONE')
    a=frame[keys].merge(other,on=keys,how='left',validate='one_to_one')
    output={c:a[c].to_numpy(float) if c in a else np.full(n,np.nan) for c in columns}
    accepted=_literal(a[qualified_column]) if qualified_column and qualified_column in a else np.zeros(n,bool)
    return output,accepted


def distribution_diagnostics(frame,prediction,*,objective='ADVANTAGE',mixture=None,gaussian_mixture=False):
    """Fixed, date-balanced descriptive diagnostics; never fitted calibration."""
    _guard(frame);n=len(frame)
    y=frame.target.to_numpy(float)
    legal=_literal(frame.label_qualified)&frame.label_mature_date.notna().to_numpy()&np.isfinite(y)
    def average(value,mask):
        mask=legal&mask&np.isfinite(value)
        if not mask.any():return None
        weight=inputs.date_equal_weights(frame.loc[mask],base_column='base_weight')
        return float(np.average(value[mask],weights=weight))
    result={'role':'NATIVE_OOF_DIAGNOSTICS_NOT_FITTED_CALIBRATION',
            'planned_rows':n,'legal_label_rows':int(legal.sum()),
            'account_qualified':False,'strict_PIT_promotion_eligible':False}
    mean=_array(prediction,'mean',n);probability=_array(prediction,'probability',n)
    sigma=_array(prediction,'sigma',n)
    result['mean_mae']=average(np.abs(mean-y),np.isfinite(mean))
    event=y if objective.upper()=='HAZARD' else (y>0).astype(float)
    pknown=np.isfinite(probability)&(probability>=0)&(probability<=1)
    if objective.upper()=='HAZARD':
        if np.any(legal&~np.isin(y,(0.,1.))):raise ValueError('HAZARD_BINARY_LABEL_REQUIRED')
    result['probability_brier']=average((probability-event)**2,pknown)
    clipped=np.clip(probability,EPS,1-EPS)
    result['probability_logloss']=average(-(event*np.log(clipped)+(1-event)*np.log1p(-clipped)),pknown)
    calibration=[]
    for index in range(10):
        mask=legal&pknown&(probability>=index/10)&((probability<(index+1)/10) if index<9 else probability<=1)
        calibration.append({'bin':index,'rows':int(mask.sum()),
            'mean_probability':average(probability,mask),
            'event_rate':average(event,mask)})
    result['fixed_probability_bins']=calibration
    for q,key in ((.1,'q10'),(.5,'q50'),(.9,'q90')):
        value=_array(prediction,key,n);known=np.isfinite(value)
        error=y-value
        result[key+'_pinball']=average(np.maximum(q*error,(q-1)*error),known)
        result[key+'_empirical_cdf']=average((y<=value).astype(float),known)
    q10=_array(prediction,'q10',n);q90=_array(prediction,'q90',n)
    interval=np.isfinite(q10)&np.isfinite(q90)&(q10<=q90)
    result['native_80_interval_coverage']=average(((y>=q10)&(y<=q90)).astype(float),interval)
    result['native_80_interval_width']=average(q90-q10,interval)
    native=np.isfinite(mean)&np.isfinite(sigma)&(sigma>0)
    z=np.divide(y-mean,sigma,out=np.full(n,np.nan),where=native)
    result['gaussian_nll']=average(.5*np.log(2*np.pi)+np.log(np.where(native,sigma,np.nan))+.5*z*z,native)
    phi=np.exp(-.5*z*z)/np.sqrt(2*np.pi)
    result['gaussian_crps']=average(sigma*(z*(2*ndtr(z)-1)+2*phi-1/np.sqrt(np.pi)),native)
    result['native_sigma_rows']=int((legal&native).sum())
    result['gaussian_density_role']='SINGLE_NATIVE_NORMAL'
    if gaussian_mixture and mixture is None:
        result['gaussian_nll_moment_matched_approx']=result['gaussian_nll']
        result['gaussian_crps_moment_matched_approx']=result['gaussian_crps']
        result['gaussian_nll']=None;result['gaussian_crps']=None
        result['gaussian_density_role']='MOMENT_MATCHED_APPROX_DIAGNOSTIC_NOT_NATIVE_MIXTURE'
    elif mixture is not None:
        mus=np.asarray(mixture['mean'],float);sds=np.asarray(mixture['sigma'],float)
        if mus.ndim!=2 or mus.shape!=sds.shape or mus.shape[0]!=n or mus.shape[1]!=3:
            raise ValueError('FROZEN_THREE_SEED_MIXTURE_SHAPE')
        valid=np.isfinite(mus).all(axis=1)&np.isfinite(sds).all(axis=1)&(sds>0).all(axis=1)
        z=(y[:,None]-mus)/sds
        logdensity=-.5*np.log(2*np.pi)-np.log(sds)-.5*z*z
        nll=-logsumexp(logdensity,axis=1)+np.log(3)
        def absolute_normal(delta,sd):
            zz=delta/sd
            return 2*sd*np.exp(-.5*zz*zz)/np.sqrt(2*np.pi)+delta*(2*ndtr(zz)-1)
        first=absolute_normal(y[:,None]-mus,sds).mean(axis=1)
        pair=absolute_normal(mus[:,:,None]-mus[:,None,:],
                             np.sqrt(sds[:,:,None]**2+sds[:,None,:]**2)).mean(axis=(1,2))
        result['gaussian_nll']=average(nll,valid)
        result['gaussian_crps']=average(first-.5*pair,valid)
        result['gaussian_density_role']='EXACT_EQUAL_THREE_NATIVE_NORMAL_MIXTURE'
    result['sigma_from_residuals_or_fusion_diagnostics']=False
    result['capability_status']={key:'AVAILABLE' if result[key] is not None else 'BLOCKED_NATIVE_CAPABILITY_OR_LEGAL_LABEL'
                                 for key in ('mean_mae','probability_brier','q10_pinball','gaussian_nll')}
    return result


def hazard_duration_regret(frame,prediction,*,owner=None):
    """H5 mature probe loss and observed event-age diagnostics, not survival fit."""
    _guard(frame);o=_owner(owner);n=len(frame)
    probability=_array(prediction,'probability',n)
    pknown=np.isfinite(probability)&(probability>=0)&(probability<=1)
    action=np.where(pknown,(probability>.5).astype(float),np.nan)
    proxy=frame.copy()
    raw=proxy.label_value.to_numpy(float) if 'label_value' in proxy else np.full(n,np.nan)
    proxy['target']=inputs.local_advantages(raw,friction_bps=10)['INCUMBENT']
    proxy['reference_action']=0.
    daily,metric=o.local_regret(proxy,action)
    metric.update(role='PROBE_CONDITIONAL_H5_SELL_VS_HOLD_NOT_COMPLETE_DURATION_OR_ACCOUNT',
                  exit_probability_threshold=.5,unknown_censor_not_event=True)
    records=[]
    required={'cohort_id','probe_age','hazard_at_risk','right_censored_unknown'}
    if required.issubset(frame):
        for cohort,part in frame.assign(predicted_probability=probability).groupby('cohort_id',sort=True,dropna=False):
            p=part.sort_values('probe_age')
            ages=p.probe_age.to_numpy(float)
            legal=_literal(p.label_qualified)&np.isfinite(p.target)&~p.right_censored_unknown.fillna(True).to_numpy(bool)
            # Sparse probes give an observed event at 7-session resolution only.
            contiguous=bool(len(p) and ages[0]==0 and np.array_equal(ages,np.arange(len(p))*7))
            event=p.loc[legal&p.target.eq(1)]
            known_prob=np.isfinite(p.predicted_probability)&p.predicted_probability.between(0,1)
            stop=p.loc[known_prob&p.predicted_probability.gt(.5)]
            actual=float(event.iloc[0].probe_age) if len(event) and contiguous and legal.all() else None
            predicted=float(stop.iloc[0].probe_age) if len(stop) and contiguous and known_prob.all() else None
            records.append({'cohort_id':cohort,'observed_probe_event_age':actual,
                            'predicted_probe_stop_age':predicted,'complete_observed_probe_prefix':contiguous and bool(legal.all()),
                            'censored_unknown':bool(p.right_censored_unknown.fillna(True).any()),
                            'absolute_probe_age_error':abs(actual-predicted) if actual is not None and predicted is not None else None,
                            'true_terminal_duration_known':False,'resolution_sessions':7})
    return {'daily':daily,'metrics':metric,'diagnostics':distribution_diagnostics(frame,prediction,objective='HAZARD'),
            'probe_duration':pd.DataFrame(records),'missing_duration_schema':sorted(required-set(frame))}


def _gross_choice(frame,gross_grid,key,owner):
    """Fixed learned grid choice. No missing-grid survivor argmax."""
    n=len(frame);selected=np.full(n,np.nan)
    if gross_grid is None:return selected,None,'BLOCKED_GROSS_NATIVE_INPUT'
    required={'signal_date','gross_previous_proxy','gross_candidate','sample_id',key}
    if not required.issubset(gross_grid):return selected,None,'BLOCKED_GROSS_NATIVE_CAPABILITY'
    _guard(gross_grid)
    if gross_grid.duplicated(['signal_date','gross_previous_proxy','gross_candidate']).any():
        raise ValueError('GROSS_GRID_DUPLICATE')
    choices={}
    for (date,previous),g in gross_grid.groupby(['signal_date','gross_previous_proxy'],sort=True):
        values=g[key].to_numpy(float)
        if len(g)!=5 or set(g.gross_candidate)!=set(GRID) or not np.isfinite(values).all():continue
        pick=g.assign(_score=values).sort_values(['_score','gross_candidate'],ascending=[False,True]).iloc[0]
        choices[(date,float(previous))]=float(pick.gross_candidate)
    if 'gross_previous_proxy' in frame:
        selected=np.array([choices.get((date,float(previous)),np.nan) if np.isfinite(previous) else np.nan
                           for date,previous in zip(frame.signal_date,frame.gross_previous_proxy)],float)
    else:
        # Exogenous Gprev is necessary; never assume an actual account's Gprev.
        selected=np.full(n,np.nan)
    daily,metrics=owner.gross_regret(gross_grid,gross_grid[key].to_numpy(float))
    return selected,{'daily':daily,'metrics':metrics,'frame':gross_grid.copy(),'score':gross_grid[key].to_numpy(float)},'AVAILABLE' if choices else 'BLOCKED_COMPLETE_NATIVE_GRID'


def resolver_streams(frame,prediction,*,group,risk=None,gross_predictions=None,owner=None):
    """Only the 12 predeclared recipes. Exports local actions plus separate G."""
    _guard(frame);o=_owner(owner);n=len(frame)
    if group not in ('ENTRY','INCUMBENT','REPLACE','SELL/HOLD','CONTINUATION'):
        raise ValueError('REGISTERED_ACTION_INTERFACE_REQUIRED')
    mean=_array(prediction,'mean',n);sigma=_array(prediction,'sigma',n)
    q10=_array(prediction,'q10',n)
    r,rqualified=_aligned(frame,risk,('risk_delta','portfolio_sigma','regime_probability'),'risk_qualified')
    penalty=np.maximum(r['risk_delta'],0)
    risk_known=rqualified&np.isfinite(r['risk_delta'])
    sigma_known=np.isfinite(sigma)&(sigma>=0)
    recipes={}
    gross_predictions=gross_predictions or {}
    for name in RECIPES:
        score=mean.copy();known=np.isfinite(mean);fraction=1.;gross=np.ones(n)
        threshold=np.zeros(n);capability=[];gross_metric=None;gross_status='FIXED_G1'
        if name=='P1':
            score=q10;known=np.isfinite(q10);capability.append('NATIVE_Q10')
        elif name=='P2':
            score=mean-SIGMA_K*sigma;known&=sigma_known;capability.append('NATIVE_SIGMA')
        elif name=='P3':threshold[:]=FRICTION+BUFFER
        elif name in ('P4','P6','P7'):
            score=mean-RISK_K*penalty;known&=risk_known;capability.append('SOURCE_R7_RISK')
            if name=='P7':
                score-=SIGMA_K*sigma;known&=sigma_known;capability.append('NATIVE_SIGMA')
            if name=='P4':
                if group=='ENTRY':threshold[:]=FRICTION+BUFFER
                elif 'action_type' in frame:
                    token=frame.action_type.to_numpy(float)
                    known&=np.isin(token,(0.,1.))
                    threshold=np.where(token==1,FRICTION+BUFFER,BUFFER)
                else:
                    known[:]=False;capability.append('INCUMBENT_ACTION_TYPE')
        elif name=='P5':fraction=PARTIAL
        elif name in ('P8','P10'):
            gross,gross_metric,gross_status=_gross_choice(
                frame,gross_predictions.get(name),'mean' if name=='P8' else 'q10',o)
            known&=np.isfinite(gross);capability.append('FIXED_MID_HGB_GROSS' if name=='P8' else 'NATIVE_GROSS_Q10')
        elif name=='P9':
            sd=r['portfolio_sigma'];ready=rqualified&np.isfinite(sd)&(sd>=0)
            gross=np.where(ready,np.divide(VOL_TARGET,sd,out=np.ones(n),where=sd>0).clip(0,1),np.nan)
            known&=ready;capability.append('NATIVE_H5_PORTFOLIO_SIGMA')
            gross_status='EXPORTED_CONTINUOUS_G_NOT_GRID_REGRET'
        elif name=='P11':
            p=r['regime_probability'];ready=rqualified&np.isfinite(p)&(p>=0)&(p<=1)
            gross=np.where(ready,1-p,np.nan);known&=ready;capability.append('SOURCE_REGIME_PROBABILITY')
            gross_status='EXPORTED_CONTINUOUS_G_NOT_GRID_REGRET'
        decision_score=score-threshold
        action=np.where(known,fraction*(decision_score>0).astype(float),np.nan)
        # G stays a separate policy coordinate; SELL/REPLACE labels already include
        # friction and must not be multiplied again by an arbitrary account gross.
        daily,metric=o.local_regret(frame,action,score=np.where(known,score,np.nan))
        metric.update(recipe=name,group=group,partial_fraction=fraction,
                      additional_hurdle_is_not_fee=name in ('P3','P4'),
                      gross_metric_separate=True,required_capabilities=capability)
        full=None
        if group in ('INCUMBENT','REPLACE','SELL/HOLD') and name!='P5':
            projected=frame.copy();projected['label_qualified']=_literal(frame.label_qualified)&known
            full=o.full_incumbent_oracle(projected,np.where(known,decision_score,np.nan))
        recipes[name]={'recipe':name,'status':'AVAILABLE' if known.any() else 'BLOCKED_CAPABILITY_OR_INPUT',
                       'frame':frame.copy(),'action':action,'gross':gross,'decision_score':np.where(known,decision_score,np.nan),
                       'known':known,'daily':daily,'metrics':metric,'full_oracle':full,
                       'gross_metric':gross_metric,'gross_status':gross_status,
                       'authority':{'account_qualified':False,'strict_PIT_promotion_eligible':False,
                                    'source_account_authority_upgraded':False}}
    return recipes


def paired_stream_contrast(left,right,*,name,owner=None,gross=False):
    """Exact same planned keys; equal-date paired comparison on known support."""
    o=_owner(owner)
    if gross:
        lm=left.get('gross_metric');rm=right.get('gross_metric')
        if not lm or not rm:return {'name':name,'status':'BLOCKED_REQUIRED_GROSS_METRIC','fit_units':0}
        lf=lm['frame'];rf=rm['frame'];_guard(lf);_guard(rf)
        keys=['signal_date','sample_id','gross_previous_proxy','gross_candidate']
        li=pd.MultiIndex.from_frame(lf[keys]);ri=pd.MultiIndex.from_frame(rf[keys])
        if li.duplicated().any() or ri.duplicated().any():raise ValueError('GROSS_PAIRED_DUPLICATE_GRID')
        if set(li)!=set(ri):return {'name':name,'status':'BLOCKED_UNMATCHED_COMPLETE_NATIVE_GRID','fit_units':0}
        order=pd.Series(np.arange(len(rf)),index=ri).reindex(li).to_numpy(int)
        rf=rf.iloc[order].reset_index(drop=True);lf=lf.reset_index(drop=True)
        if not np.array_equal(lf.target.to_numpy(float),rf.target.to_numpy(float),equal_nan=True):
            raise ValueError('GROSS_PAIRED_TARGET_IDENTITY')
        if not pd.to_datetime(lf.label_mature_date).equals(pd.to_datetime(rf.label_mature_date)):
            raise ValueError('GROSS_PAIRED_MATURITY_IDENTITY')
        for field in ('basket_members','basket_sids','source_label_identity'):
            if field in lf or field in rf:
                if field not in lf or field not in rf or not lf[field].equals(rf[field]):
                    raise ValueError('GROSS_PAIRED_SOURCE_IDENTITY')
        ls=np.asarray(lm['score'],float);rs=np.asarray(rm['score'],float)[order]
        shared=_literal(lf.label_qualified)&_literal(rf.label_qualified)&np.isfinite(ls)&np.isfinite(rs)
        projected=lf.copy();projected['label_qualified']=shared
        ld,_=o.gross_regret(projected,np.where(shared,ls,np.nan))
        rd,_=o.gross_regret(projected,np.where(shared,rs,np.nan))
        common=ld.index.intersection(rd.index)
        return {'name':name,'status':'PAIRED_CONDITIONAL_PROXY',
                'daily_improvement':rd.regret.reindex(common)-ld.regret.reindex(common),
                'support':'EXACT_SAMPLE_GPREV_NATIVE_GRID_COMMON_MASK','fit_units':0}
    lf=left['frame'];rf=right['frame'];_guard(lf);_guard(rf)
    keys=['signal_date','sample_id']
    lk=pd.MultiIndex.from_frame(lf[keys]);rk=pd.MultiIndex.from_frame(rf[keys])
    if set(lk)!=set(rk):return {'name':name,'status':'BLOCKED_UNMATCHED_EX_ANTE_SOURCE_SUPPORT','fit_units':0}
    order=pd.Series(np.arange(len(rf)),index=rk).reindex(lk).to_numpy(int)
    reordered=rf.iloc[order].reset_index(drop=True);base=lf.reset_index(drop=True)
    if not np.array_equal(base.target.to_numpy(float),reordered.target.to_numpy(float),equal_nan=True):
        raise ValueError('PAIRED_TARGET_IDENTITY_CHANGED')
    if not pd.to_datetime(base.label_mature_date).equals(pd.to_datetime(reordered.label_mature_date)):
        raise ValueError('PAIRED_MATURITY_IDENTITY_CHANGED')
    a=np.asarray(left['action'],float);b=np.asarray(right['action'],float)[order]
    known=np.isfinite(a)&np.isfinite(b)
    projected=base.copy();projected['label_qualified']=_literal(base.label_qualified)&_literal(reordered.label_qualified)&known
    ld,lm=o.local_regret(projected,np.where(known,a,np.nan))
    rd,rm=o.local_regret(projected,np.where(known,b,np.nan))
    common=ld.index.intersection(rd.index)
    errors_left=_error_rates(projected,np.where(known,a,np.nan))
    errors_right=_error_rates(projected,np.where(known,b,np.nan))
    return {'name':name,'status':'PAIRED_CONDITIONAL_PROXY','daily_improvement':rd.regret.reindex(common)-ld.regret.reindex(common),
            'left_wrong_action_rate':errors_left['wrong_action_rate'],'right_wrong_action_rate':errors_right['wrong_action_rate'],
            'left_missed_positive_advantage_rate':errors_left['missed_positive_advantage_rate'],
            'right_missed_positive_advantage_rate':errors_right['missed_positive_advantage_rate'],
            'known_prediction_rows':int(known.sum()),'planned_rows':len(base),
            'left_action_rate':lm.get('action_rate'),'right_action_rate':rm.get('action_rate'),
            'support':'PREDECLARED_BINARY_EDGES_NOT_FULL_ACTIONSET_OR_ACCOUNT','fit_units':0}


def registered_interactions(named_streams,*,owner=None,apply_simultaneous=True,friction_evidence=None):
    """The exact 20 preregistered contracts, with missing branches preserved."""
    o=_owner(owner);rows=[];series={}
    for name,left,right in INTERACTIONS:
        if left is None:
            rows.append({'name':name,'status':'SECONDARY_FIXED_ACTION_COST_SENSITIVITY',
                         'evidence':friction_evidence,'fit_units':0,
                         'mechanism_support_from_cost_level_choice':False});continue
        if left not in named_streams or right not in named_streams:
            rows.append({'name':name,'status':'BLOCKED_PREDECLARED_STREAM_MISSING',
                         'left':left,'right':right,'fit_units':0});continue
        row=paired_stream_contrast(named_streams[left],named_streams[right],name=name,owner=o,
                                    gross=name in ('P10 vsP8 UNCERTAINTY_GROSS','P11 vsP8 REGIME_GROSS'))
        rows.append(row)
        if 'daily_improvement' in row:series[name]=row['daily_improvement']
    bounds=o.simultaneous_bounds(series) if apply_simultaneous and series else {}
    return {'contrasts':rows,'simultaneous_bounds':bounds,'registered_count':20,'new_fit':0,
            'blocked_not_removed_from_report':True,'scientific_selection_after_results':False}


def friction_sensitivity(fixed_actions, native_frames,*,owner=None):
    """5/10/20bps, same fixed 10bps REPLACE actions and four native endpoints."""
    o=_owner(owner)
    if set(native_frames)!=set(inputs.HORIZONS):raise ValueError('ALL_FOUR_NATIVE_ENDPOINTS_REQUIRED')
    anchor=native_frames[5].copy();_guard(anchor)
    action=np.asarray(fixed_actions,float)
    if action.shape!=(len(anchor),):raise ValueError('FIXED_ACTION_SHAPE')
    if 'action_type' in anchor and not anchor.action_type.eq(1).all():
        raise ValueError('FIXED_REPLACE_SUBSET_REQUIRED')
    target={}
    clocks=[];flags=[]
    for h in inputs.HORIZONS:
        f=native_frames[h];_guard(f)
        keys=['signal_date','sample_id']
        ix=pd.MultiIndex.from_frame(f[keys])
        aligned=f.set_index(keys).reindex(pd.MultiIndex.from_frame(anchor[keys])).reset_index()
        if len(ix)!=len(set(ix)):raise ValueError('NATIVE_ENDPOINT_DUPLICATE')
        flags.append(_literal(aligned.label_qualified)&np.isfinite(aligned.e_y)&np.isfinite(aligned.i_y))
        clocks.append(pd.to_datetime(aligned.label_mature_date))
        for cost in (5,10,20):
            target.setdefault(cost,[]).append(inputs.local_advantages(
                aligned.e_y.to_numpy(float),aligned.i_y.to_numpy(float),friction_bps=cost)['REPLACE'])
    legal=np.logical_and.reduce(flags)&pd.concat(clocks,axis=1).notna().all(axis=1).to_numpy()
    maturity=pd.concat(clocks,axis=1).max(axis=1)
    result={}
    for cost in (5,10,20):
        frame=anchor.copy();frame['target']=np.mean(np.stack(target[cost]),axis=0)
        frame['label_qualified']=legal;frame['label_mature_date']=maturity
        daily,metric=o.local_regret(frame,action)
        result[cost]={'daily':daily,'metrics':metric,'fixed_action_identity':'ORIGINAL_10BPS_NO_REFIT_OR_RETUNE',
                      'one_way_bps':cost,'account_qualified':False}
    return result


def question_report(evidence,*,budget_actual=None,authorities=None,preservation=None):
    """Fifteen fixed questions; supplied evidence only, no invented answers."""
    rows=[]
    for index,question in enumerate(QUESTIONS,1):
        supplied=evidence.get(str(index),evidence.get(index))
        rows.append({'id':index,'question':question,
                     'status':'EVIDENCE_SUPPLIED' if supplied is not None else 'NOT_ESTABLISHED',
                     'evidence':supplied})
    return {'questions':rows,'budget_actual':budget_actual,'budget_cap':1200,
            'authority':authorities or {},'preservation':preservation or {},
            'result_role':'FROZEN_HISTORY_CONDITIONAL_MECHANISM_NOT_ACCOUNT_WINNER',
            '2023_role':'MECHANICAL_REFERENCE_AND_LIMITED_PAST_OOF_ONLY',
            'official_model_years':[2024,2025],'historical_exposure_retained':True,
            'automatic_R11_created':False,'report_generation_new_fit':0}


def comparison_templates():
    """Fixed before output inspection; zero new fits or resolver expansion."""
    return {'sequence':{'variants':['S1','S2','S3'],'reference':'S0',
                        'lookbacks':[5,10,20],'architectures':['tcn','gru','lstm'],
                        'roles':['CONTINUATION','SELL/HOLD','REPLACE_EDGE']},
            'fusion':{'fitted_reference_families':['ridge','hgb'],
                      'equal_median_reference_families':['ridge','elasticnet','huber','hgb','xgb','lgb',
                        'catboost','extratrees','mlp','resnet','ft_transformer','hgb_quantile','ngboost','gaussian_mlp'],
                      'all_fixed_members_compared':True,'best_member_selection':False},
            'risk':{'R7_vs_R0':['ridge','hgb','xgb','catboost','mlp','hgb_quantile'],
                    'independent_R1_R6':['ridge','hgb'],'matched_source_required':True},
            'recipes':list(RECIPES),'registered_interactions':[r[0] for r in INTERACTIONS],
            'same_combined_simultaneous_family':True,'distribution':{'families':['ngboost','gaussian_mlp','hgb_quantile'],
                            'capacities':['LOW','MID','HIGH'],'U1':'Native q10 vs same-family point',
                            'U2':'Native mean-sigma vs same-family mean',
                            'missing_capability':'BLOCKED_NO_NATIVE_CAPABILITY'},
            'main_recipe_anchor':'GAUSSIAN_MLP_MID_EQUAL_ALL_3_SEEDS_NO_FALLBACK',
            'no_new_fit':True}


def _score_prediction(frame):
    return {k:frame[k].to_numpy(float) if k in frame else None
            for k in ('mean','probability','q10','q50','q90','sigma')}


def _fixed_action(prediction,n):
    mean=_array(prediction,'mean',n)
    if np.isfinite(mean).any():return np.where(np.isfinite(mean),(mean>0).astype(float),np.nan),mean
    q50=_array(prediction,'q50',n)
    if np.isfinite(q50).any():return np.where(np.isfinite(q50),(q50>0).astype(float),np.nan),q50
    p=_array(prediction,'probability',n)
    return np.where(np.isfinite(p)&(p>=0)&(p<=1),(p>.5).astype(float),np.nan),None


def _role_frames(frame,group):
    if group=='HAZARD':return [('HAZARD',frame)]
    role='ENTRY' if group.startswith('ENTRY_') else 'INCUMBENT' if group.startswith('INCUMBENT_') else group
    output=[(role,frame)]
    if group in ('JOINT_SEQUENCE','SEQUENCE_COMPARISON') and 'action_type' in frame:
        subset=frame.loc[frame.action_type.isin((0.,1.))].copy().reset_index(drop=True)
        if len(subset):output.append(('INCUMBENT',subset))
    if 'action_type' in frame and group!='GROSS':
        for token,role in ((-1,'CONTINUATION'),(0,'SELL/HOLD'),(1,'REPLACE_EDGE')):
            pick=frame.action_type.eq(token)
            if pick.any():output.append((role,frame.loc[pick].copy().reset_index(drop=True)))
    return output


def _error_rates(frame,action):
    y=frame.target.to_numpy(float);a=np.asarray(action,float)
    good=_literal(frame.label_qualified)&np.isfinite(y)&np.isfinite(a)&frame.label_mature_date.notna().to_numpy()
    if not good.any():return {'wrong_action_rate':None,'missed_positive_advantage_rate':None}
    f=frame.loc[good].copy();weights=inputs.date_equal_weights(f,base_column='base_weight')
    return {'wrong_action_rate':float(np.average(a[good]*(y[good]<0),weights=weights)),
            'missed_positive_advantage_rate':float(np.average((1-a[good])*(y[good]>0),weights=weights))}


def complete_study(run,design,bundle,frames,publications,*,risk_result=None,risk_features=None,
                   risk_flat=None,risk_context=None,gross_frame=None):
    """Unique caller completion: own-run custody, all frozen outputs and receipts.

    No financial artifacts from other runs are read. This is evaluation and
    reporting only; no failed scientific slot is refit and no source is promoted.
    """
    from pathlib import Path
    from collections import Counter,defaultdict
    o=_owner(None);run=Path(run).resolve();o.authority_check(design)
    report_root=(o.RESULT/run.name).resolve()
    from scripts.common.storage_paths import resolve
    roots=resolve(o.fit_owner.REPO)
    if not report_root.is_relative_to(roots.results_root.resolve()):
        raise ValueError('REPORT_STORAGE_CUSTODY')
    report_root.mkdir(parents=True,exist_ok=True)
    tables=report_root/'tables';tables.mkdir(exist_ok=True)
    def own(path,expected=None):
        p=Path(path).resolve()
        if not p.is_relative_to(run):raise ValueError('OWN_RUN_ARTIFACT_CUSTODY')
        if expected is not None and o.fit_owner.sha(p)!=expected:raise ValueError('OWN_RUN_ARTIFACT_SHA')
        return p
    def guarded_oof(pub):
        path=own(pub['path'],pub.get('sha256'))
        if not pub.get('sha256'):raise ValueError('OWN_OOF_SHA_REQUIRED')
        import pyarrow.parquet as pq
        footer=pq.ParquetFile(path)
        if footer.metadata.num_rows==0:
            return footer.schema_arrow.empty_table().to_pandas()
        records=inputs.guard_sources({'OWN_OOF':dict(path=str(path),sha256=pub['sha256'],
                 date_columns=['signal_date','label_mature_date'],
                 required_columns=['sample_id','target','label_qualified'])})
        body=pd.read_parquet(path)
        fingerprint=records['OWN_OOF']['file_fingerprint'];stat=path.stat()
        if fingerprint!={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}:raise ValueError('OWN_OOF_CHANGED_DURING_READ')
        return body
    canonical_cache={}
    def canonical(pub):
        group=pub.get('group','');h=pub.get('horizon','MEAN')
        if str(h).isdigit():h=int(h)
        key=(group,h)
        if key in canonical_cache:return canonical_cache[key]
        if group=='GROSS':source=gross_frame
        elif group=='HAZARD':
            source=inputs.hazard_probes(bundle.frames.heads[5]['CONTINUATION'],bundle.reader.calendar,ages=(0,7,14),stride=7)
            source['sample_id']=source.signal_date.astype(str)+'|HAZARD|'+source.cohort_id
            source['base_weight']=1.;source['reference_action']=0.
        elif group.startswith('ENTRY'):source=frames[h]['ENTRY']
        elif group.startswith('INCUMBENT'):source=frames[h]['INCUMBENT']
        elif group=='CONTINUATION':source=frames[h]['CONTINUATION']
        elif group in ('JOINT_SEQUENCE','SEQUENCE_COMPARISON') or group.startswith('SEQUENCE_STATIC_L'):
            cont=frames[h]['CONTINUATION'].copy();cont['action_type']=-1.
            source=pd.concat([frames[h]['INCUMBENT'],cont],ignore_index=True,sort=False)
        else:raise ValueError('UNKNOWN_PUBLISHED_CANONICAL_GROUP')
        if source is None:raise ValueError('PUBLISHED_CANONICAL_INPUT_UNBOUND')
        canonical_cache[key]=source
        return source
    def table(name,value):
        p=tables/(name+'.parquet')
        value=value.copy()
        # Metadata horizon/seed fields may mix strings and integers. Preserve
        # exact values as text instead of letting Arrow guess an invalid type.
        for column in value:
            if value[column].dtype==object:
                if any(isinstance(v,(dict,list,tuple,np.ndarray)) for v in value[column]):
                    import json
                    value[column]=value[column].map(lambda v:None if v is None else json.dumps(o.clean(v),sort_keys=True,default=str) if isinstance(v,(dict,list,tuple,np.ndarray)) else v)
                nonnull=value[column].dropna()
                types={type(v) for v in nonnull}
                if len(types)>1 and any(isinstance(v,str) for v in nonnull):
                    value[column]=value[column].map(lambda v:None if v is None else str(v))
        value.to_parquet(p,index=True)
        return {'path':str(p),'sha256':o.fit_owner.sha(p),'rows':len(value)}
    def component_key(pub,role):
        g=pub.get('group','UNKNOWN')
        if g=='SEQUENCE_COMPARISON':
            return '|'.join(map(str,('SEQ',pub.get('lookback'),pub.get('architecture'),pub.get('variant'),role)))
        if g=='JOINT_SEQUENCE':
            return '|'.join(map(str,(g,'L'+str(pub.get('lookback')),pub.get('horizon'),pub.get('family'),pub.get('capacity'),role)))
        return '|'.join(map(str,(g,pub.get('horizon'),pub.get('family'),pub.get('capacity'),role)))
    receipt_rows=[];receipt_payloads={};seed_forecasts={};audits=[]
    batch_names=('ACTION_BATCH.json','HAZARD_CONTINUATION_BATCH.json','SEQUENCE_BATCH.json',
                 'SHARED_RISK_BATCH.json','RISK_ACTION_BATCH.json','FUSION_BATCH.json',
                 'SEQUENCE_FUSION_BATCH.json','GROSS_BATCH.json')
    batch_status={}
    for filename in batch_names:
        path=run/filename
        status=o.read_json(path).get('status') if path.exists() else 'MISSING'
        batch_status[filename]=status
        if status!='COMPLETE':audits.append({'batch':filename,'error':'BATCH_NOT_COMPLETE','status':status})
    for path in sorted((run/'models/mechanism').glob('**/fit_receipt.json')):
        row=o.read_json(own(path));receipt_payloads[str(path)]=row
        receipt_rows.append({k:row.get(k) for k in ('slot_id','family','capacity','seed','group','horizon','year',
                     'bucket','status','fit_units','training_rows','error','reason','prediction_status','prediction_error',
                     'scientific_tuple_sha256','model_path','model_sha256','receipt_path','matched_all7_domain','support_role')})
        if row.get('status')=='TRAINED' and row.get('model_path'):
            try:own(row['model_path'],row.get('model_sha256'))
            except ValueError as exc:audits.append({'path':str(path),'error':str(exc)})
    for path,expected in design.get('protected_source_pins',{}).items():
        actual=o.fit_owner.sha(path)
        if actual!=expected:audits.append({'protected_source':path,'expected':expected,'actual':actual})
    events=o.fit_owner._events(run/'FIT_LOG.jsonl')
    starts=[e for e in events if e.get('event')=='FIT_STARTED']
    buckets=Counter({b:0 for b in o.CAPS})
    for event in starts:buckets[event.get('budget_bucket','UNKNOWN')]+=int(event.get('fit_units',0))
    actual=sum(buckets.values())
    if actual>1200 or any(buckets[b]>o.CAPS[b] for b in o.CAPS):
        audits.append({'error':'PHYSICAL_FIT_CAP_EXCEEDED','actual':actual,'bucket_usage':dict(buckets)})
    receipt_index={row.get('slot_id'):row for row in receipt_rows}
    for event in starts:
        if event.get('role')=='SHARED_OWNER_RISK':
            continue
        row=receipt_index.get(event.get('model_id'))
        expected=event.get('reuse_tuple_sha256',event.get('scientific_tuple_sha256'))
        if not row or row.get('status') not in ('TRAINED','FAILED') or row.get('scientific_tuple_sha256')!=expected:
            audits.append({'model_id':event.get('model_id'),'error':'UNTERMINATED_FIT_STARTED_OR_RECEIPT_IDENTITY'})
    risk_result=risk_result or {}
    risk_starts=[event for event in starts if event.get('role')=='SHARED_OWNER_RISK']
    risk_units=sum(int(event.get('fit_units',0)) for event in risk_starts)
    if risk_units!=int(risk_result.get('attempted_learned_units',0)):
        audits.append({'error':'SHARED_RISK_COMPONENT_START_MISMATCH'})
    for receipt in risk_result.get('production_receipts',[]):
        for event in receipt.get('component_starts',[]):
            if event.get('status') in ('FIT_STARTED','RUNNING',None):
                audits.append({'error':'UNTERMINATED_SHARED_RISK_COMPONENT','name':event.get('name')})
    if not receipt_rows and not publications and not risk_result.get('production_receipts'):
        audits.append({'error':'NO_SCHEDULED_SLOT_RECEIPTS'})
    def mixture_packet(pub,part):
        if pub.get('family')!='gaussian_mlp':return None
        refs=pub.get('seed_receipts',[])
        if len(refs)!=3:raise ValueError('FROZEN_THREE_GAUSSIAN_SEED_RECEIPTS_REQUIRED')
        means=[];sigmas=[];seen_seeds=[]
        expected_cutoff='2023-10-01' if pub.get('prefix') is True else f"{int(pub['year'])}-01-01"
        for receipt_path in refs:
            rp=str(own(receipt_path));receipt=receipt_payloads.get(rp)
            if receipt is None:receipt=o.read_json(rp)
            if receipt.get('status')!='TRAINED':raise ValueError('GAUSSIAN_SEED_NOT_TRAINED')
            for field in ('family','group','horizon','year','capacity'):
                if receipt.get(field)!=pub.get(field):raise ValueError('GAUSSIAN_SEED_METADATA_LINEAGE_'+field)
            if receipt.get('cutoff_exclusive')!=expected_cutoff:raise ValueError('GAUSSIAN_SEED_METADATA_LINEAGE_cutoff')
            seen_seeds.append(receipt.get('seed'))
            leaf=receipt.get('publication')
            if not leaf:raise ValueError('GAUSSIAN_SEED_PUBLICATION_REQUIRED')
            lp=str(own(leaf['path'],leaf.get('sha256')))
            if lp not in seed_forecasts:
                forecast=guarded_oof(leaf);_guard(forecast)
                forecast=rebind_published_metadata(forecast,canonical(pub));seed_forecasts[lp]=forecast
            forecast=seed_forecasts[lp].set_index('sample_id').reindex(part.sample_id)
            if not np.array_equal(forecast.target.to_numpy(float),part.target.to_numpy(float),equal_nan=True):
                raise ValueError('GAUSSIAN_SEED_TARGET_IDENTITY')
            for clock in ('signal_date','label_mature_date'):
                if not pd.to_datetime(forecast[clock]).reset_index(drop=True).equals(pd.to_datetime(part[clock]).reset_index(drop=True)):
                    raise ValueError('GAUSSIAN_SEED_CLOCK_IDENTITY')
            if np.any(_literal(part.label_qualified)&~_literal(forecast.label_qualified)):
                raise ValueError('GAUSSIAN_SEED_QUALIFICATION_IDENTITY')
            means.append(forecast['mean'].to_numpy(float));sigmas.append(forecast['sigma'].to_numpy(float))
        if tuple(seen_seeds)!=tuple(o.SEEDS):raise ValueError('GAUSSIAN_SEED_FIXED_IDENTITY_ORDER')
        return {'mean':np.stack(means,axis=1),'sigma':np.stack(sigmas,axis=1)}
    for row in receipt_rows:
        units=int(row.get('fit_units') or 0)
        ack_units=sum(int(event.get('fit_units',0)) for event in starts
                      if event.get('model_id')==row.get('slot_id') and event.get('role')!='SHARED_OWNER_RISK')
        if units!=ack_units or row.get('status')=='TRAINED' and units<1:
            audits.append({'slot_id':row.get('slot_id'),'error':'RECEIPT_ACK_UNITS_MISMATCH_OR_UNACKNOWLEDGED_FIT',
                           'receipt_units':units,'ack_units':ack_units})
    publication_rows=[];distribution_rows=[];daily_rows=[];full_rows=[];duration_rows=[];native_uncertainty_rows=[]
    streams={};gross_packets={};primary=defaultdict(list);component_pairs=defaultdict(list)
    publication_errors=[]
    for pub in publications:
        meta={k:pub.get(k) for k in ('slot_id','group','family','capacity','year','horizon','prefix','status',
                         'path','sha256','lookback','architecture','variant','matched_all7_domain','support_role')}
        if not pub.get('path'):
            meta.update(status=pub.get('status','BLOCKED_NO_PUBLICATION'));publication_rows.append(meta);continue
        try:
            f=guarded_oof(pub);_guard(f);f=rebind_published_metadata(f,canonical(pub))
            prediction=_score_prediction(f)
            if pub.get('group')=='GROSS':gross_packets[(pub.get('family'),pub.get('capacity'),pub.get('year'))]=f
            if not bool(pub.get('prefix')) and pub.get('year') not in (2024,2025):
                raise ValueError('OFFICIAL_MODEL_YEAR_NOT_REGISTERED')
            roles=_role_frames(f,pub.get('group','UNKNOWN'))
            for role,part in roles:
                pred=_score_prediction(part);key=component_key(pub,role)
                if role=='HAZARD':
                    diagnosed=hazard_duration_regret(part,pred,owner=o)
                    daily=diagnosed['daily'];metric=diagnosed['metrics'];diag=diagnosed['diagnostics']
                    duration=diagnosed['probe_duration']
                    if len(duration):duration_rows.append(duration.assign(component=key,year=pub.get('year')))
                    action=np.where(np.isfinite(_array(pred,'probability',len(part))),
                        (_array(pred,'probability',len(part))>.5).astype(float),np.nan)
                elif role=='GROSS':
                    value=_array(pred,'mean',len(part))
                    if not np.isfinite(value).any():value=_array(pred,'q50',len(part))
                    daily,metric=o.gross_regret(part,value);diag=distribution_diagnostics(part,pred)
                    action=None
                else:
                    action,score=_fixed_action(pred,len(part))
                    daily,metric=o.local_regret(part,action,score=score)
                    metric.update(_error_rates(part,action))
                    diag=distribution_diagnostics(part,pred,mixture=mixture_packet(pub,part),gaussian_mixture=pub.get('family')=='gaussian_mlp')
                    if role in ('INCUMBENT','SELL/HOLD','REPLACE_EDGE') and score is not None:
                        # Full oracle can only use the unsplit full planned action set.
                        if role=='INCUMBENT':
                            ff=part.copy();ff['label_qualified']=_literal(ff.label_qualified)&np.isfinite(score)
                            full=o.full_incumbent_oracle(ff,score)
                            full_rows.append(full.assign(component=key,year=pub.get('year')))
                if role!='HAZARD' and pub.get('family') in comparison_templates()['distribution']['families'] and not pub.get('prefix'):
                    native=native_distribution_contrasts(part,pred,owner=o)
                    for gate,contrast in native.items():
                        native_uncertainty_rows.append({**meta,'role':role,'gate':gate,
                            **{k:v for k,v in contrast.items() if k!='daily_improvement'}})
                        if 'daily_improvement' in contrast:
                            component_pairs['NATIVE_U|'+str(pub.get('group'))+'|'+str(pub.get('family'))+'|'+str(pub.get('capacity'))+'|'+role+'|'+gate].append(contrast['daily_improvement'])
                row={**meta,'component':key,'role':role,**metric}
                publication_rows.append(row)
                distribution_rows.append({**diag,'component':key,'year':pub.get('year'),'role':role})
                if len(daily):
                    daily_rows.append(daily.assign(component=key,year=pub.get('year'),prefix=bool(pub.get('prefix'))))
                if not bool(pub.get('prefix')) and len(daily) and 'improvement' in daily:
                    primary[key].append(daily.improvement)
                # Cache already-read own forecasts; never consult another route/winner.
                if not bool(pub.get('prefix')) and action is not None and role!='HAZARD':
                    streams[(pub.get('group'),pub.get('family'),pub.get('capacity'),pub.get('year'),
                             pub.get('lookback'),pub.get('architecture'),pub.get('variant'),role,str(pub.get('horizon')))]={
                        'frame':part,'action':action,'prediction':pred,'daily':daily,'metrics':metric,'publication':pub}
        except (ValueError,KeyError,TypeError) as exc:
            publication_errors.append({**meta,'error':type(exc).__name__+':'+str(exc)})
    # Fixed fusion and sequence component contrasts use exact planned sample keys.
    for identity,left in streams.items():
        group,family,cap,year,length,arch,variant,role,horizon=identity
        references=[]
        if group=='SEQUENCE_COMPARISON' and variant in ('S1','S2','S3'):
            references=[(('SEQUENCE_COMPARISON',None,None,year,length,arch,'S0',role,horizon),'S0')]
        elif isinstance(family,str) and family.startswith('fusion_') and cap=='MID':
            families=comparison_templates()['fusion']['equal_median_reference_families'] if family in ('fusion_equal','fusion_median') else ('ridge','hgb')
            references=[((group,ref,'MID',year,None,None,None,role,horizon),ref) for ref in families]
        elif group in ('ENTRY_R7','INCUMBENT_R7') and cap=='MID':
            references=[((group[:-2]+'R0',family,'MID',year,None,None,None,role,horizon),'R0')]
        elif group in tuple('INCUMBENT_R'+str(i) for i in range(1,7)) and cap=='MID':
            source=left['publication']
            receipts=[row for row in receipt_rows if row.get('receipt_path') in source.get('seed_receipts',[])]
            if receipts and all(row.get('matched_all7_domain') is True for row in receipts):
                references=[(('INCUMBENT_R0',family,'MID',year,None,None,None,role,horizon),'R0')]
        for wanted,ref in references:
            if group=='SEQUENCE_COMPARISON':
                candidates=[value for key,value in streams.items()
                            if key[0]==wanted[0] and key[3:]==wanted[3:]]
                right=candidates[0] if len(candidates)==1 else None
                name='|'.join(map(str,('SEQUENCE_PAIRED',length,arch,variant,'vsS0',role)))
            else:
                right=streams.get(wanted)
                prefix='LEARNED_RISK_PAIRED' if '_R' in group else 'FUSION_PAIRED'
                name='|'.join(map(str,(prefix,group,family,'vs'+ref,role)))
            if right is None:continue
            contrast=paired_stream_contrast(left,right,name=name,owner=o)
            if 'daily_improvement' in contrast:component_pairs[name].append(contrast['daily_improvement'])
    # Same native Gaussian MID packet supplies the common P0-P11 comparisons.
    # This capability choice is frozen before output reads, not a best-family choice.
    resolver_rows=[];interaction_rows=[];cost_evidence=None
    indexed_recipe=defaultdict(list)
    for group in ('ENTRY','INCUMBENT'):
        for year in (2024,2025):
            anchor=streams.get((group,'gaussian_mlp','MID',year,None,None,None,group,'MEAN'))
            if anchor is None:continue
            risk=risk_features.get((group,'R7')) if risk_features else None
            gross_predictions={recipe:gross_packets.get((family,'MID',year)) for recipe,family in
                               (('P8','hgb'),('P10','hgb_quantile'))}
            named=resolver_streams(anchor['frame'],anchor['prediction'],group=group,risk=risk,
                                   gross_predictions=gross_predictions,owner=o)
            for name,stream in named.items():
                resolver_rows.append({'group':group,'year':year,'recipe':name,'status':stream['status'],
                                     'gross_status':stream['gross_status'],**stream['metrics']})
                if len(stream['daily']) and name in RECIPES[:8]:
                    primary['RESOLVER|'+group+'|'+name].append(stream['daily'].improvement)
                if stream.get('gross_metric') and len(stream['gross_metric']['daily']):
                    primary['GROSS_RESOLVER|'+group+'|'+name].append(stream['gross_metric']['daily'].improvement)
                indexed_recipe[(group,name)].append(stream)
            # Role-specific fixed risk resolvers use the same frozen Gaussian MID forecast.
            for rep in ('R0','R1','R2','R3','R4','R5','R6','R7'):
                rr=risk_features.get((group,rep)) if risk_features else None
                spec=resolver_streams(anchor['frame'],anchor['prediction'],group=group,risk=rr,owner=o)
                base=spec['P0' if rep=='R0' else 'P6']
                named[rep+' '+('ENTRY' if group=='ENTRY' else 'REPLACE')]=base
                if group=='INCUMBENT':
                    for token,role in ((0,'SELL/HOLD'),(1,'REPLACE')):
                        mask=base['frame'].action_type.eq(token).to_numpy()
                        cut={**base,'frame':base['frame'].loc[mask].copy().reset_index(drop=True),
                             'action':base['action'][mask]}
                        named[rep+' '+role]=cut
            interaction=registered_interactions(named,owner=o,apply_simultaneous=False)
            for row in interaction['contrasts']:
                interaction_rows.append({k:v for k,v in row.items() if k not in ('daily_improvement','evidence') }|{'group':group,'year':year})
                if 'daily_improvement' in row:primary['INTERACTION|'+group+'|'+row['name']].append(row['daily_improvement'])
            # Fixed original 10bps actions on all four native REPLACE endpoints.
            if group=='INCUMBENT':
                ids=anchor['frame'].loc[anchor['frame'].action_type.eq(1),'sample_id']
                native={h:frames[h]['INCUMBENT'].set_index('sample_id').reindex(ids).reset_index() for h in inputs.HORIZONS}
                if len(ids):
                    cost=friction_sensitivity(anchor['action'][anchor['frame'].action_type.eq(1).to_numpy()],native,owner=o)
                    cost_evidence=cost_evidence or {}
                    cost_evidence[year]={bps:data['metrics'] for bps,data in cost.items()}
    control=nonml_gross_controls({h:bundle.frames.gross[h] for h in inputs.HORIZONS},risk_result,owner=o,
                                native_q_grid=gross_packets.get(('hgb_quantile','MID',2025)))
    for name,series_control in control['series'].items():primary[name].append(series_control)
    for name,parts in component_pairs.items():primary[name].extend(parts)
    series={}
    for name,parts in primary.items():
        s=pd.concat(parts).sort_index()
        if s.index.duplicated().any():raise ValueError('DUPLICATE_PRIMARY_DATE_COMPONENT_'+name)
        series[name]=s
    if audits or publication_errors:
        o.save(report_root/'ENGINEERING_BLOCKERS.json',dict(status='ENGINEERING_RECOVERY_REQUIRED',
               audits=audits,publication_errors=publication_errors,batches=batch_status,report_generation_new_fit=0))
        raise RuntimeError('R10_COMPLETION_ENGINEERING_RECOVERY_REQUIRED')
    bounds=o.simultaneous_bounds(series)
    ci_rows=[dict(component=name,**value) for name,value in bounds.items()]
    source_slots={slot:'UNBOUND' for slot in ('market_quote','security_identity','cash_bundle','MKFG_terminal','MKFG_settlement')}
    source_status={'slots':source_slots,**o.AUTHORITY,'source_activated':False,
                   'strict_PIT_promotion_eligible':False,'real_accounts':0,'real_account_candidates':0}
    exposure_path=o.RESULT/'R10_INFO_EXPOSURE_RECEIPT.json'
    exposure_raw=o.read_json(exposure_path) if exposure_path.exists() else {}
    exposure={k:exposure_raw.get(k) for k in ('schema','status','recorded_at_utc','real_2026_or_2027_table_read',
                 'real_2026_prediction_account_or_financial_output_file_read','used_for_design_or_selection',
                 'holdout_independence_restored')}
    exposure.update(receipt_path=str(exposure_path),claim_absolute_2026_information_zero_exposure=False,
                    numerical_market_label_prediction_rows_read_2026=0,fit_selection_2026=0,
                    incidental_source_comment_exposure_disclosed=True,historical_holdout_independence_not_reset=True)
    risk_result=risk_result or {}
    risk_diagnostics=risk_diagnostic_tables(risk_result,bundle,owner=o)
    risk_coverage=pd.DataFrame(risk_result.get('coverage',[]))
    risk_blocks=risk_result.get('blocks',[])
    rcounts=Counter(row.get('status','UNKNOWN') for row in receipt_rows)
    prediction_failures=sum(row.get('status')=='TRAINED' and row.get('prediction_status')=='FAILED' for row in receipt_rows)
    input_blocks=sum(str(row.get('status','')).startswith('BLOCKED') for row in receipt_rows)+len(risk_blocks)
    failed_scientific_slots=int(rcounts.get('FAILED',0))
    failed_risk_physical=int(risk_result.get('failed_started_units',0))
    failed_started_physical=sum(int(row.get('fit_units') or 0) for row in receipt_rows if row.get('status')=='FAILED')+failed_risk_physical
    failed=failed_scientific_slots+prediction_failures
    supported=[name for name,row in bounds.items() if row.get('status')=='MECHANISM_SUPPORTED']
    budget_exhausted=actual>=1200 or any('BUDGET' in str(row.get('error')) or 'EXHAUSTED' in str(row.get('error')) for row in receipt_rows)
    terminal='R10_PARTIAL_INPUT_BLOCKED' if input_blocks else 'R10_BUDGET_EXHAUSTED' if budget_exhausted else 'R10_FULL_BREADTH_MECHANISM_SUPPORTED' if supported else 'R10_FULL_BREADTH_COMPLETE_NO_SUPPORT'
    refs={}
    refs['fit_receipts']=table('fit_receipts',pd.DataFrame(receipt_rows))
    refs['publications']=table('publications',pd.DataFrame(publication_rows))
    refs['distribution_diagnostics']=table('distribution_diagnostics',pd.DataFrame(distribution_rows))
    refs['native_uncertainty_paired']=table('native_uncertainty_paired',pd.DataFrame(native_uncertainty_rows))
    refs['daily_mechanism']=table('daily_mechanism',pd.concat(daily_rows) if daily_rows else pd.DataFrame())
    refs['full_incumbent_oracle']=table('full_incumbent_oracle',pd.concat(full_rows,ignore_index=True) if full_rows else pd.DataFrame())
    refs['hazard_probe_duration']=table('hazard_probe_duration',pd.concat(duration_rows,ignore_index=True) if duration_rows else pd.DataFrame())
    refs['resolver_coverage']=table('resolver_coverage',pd.DataFrame(resolver_rows))
    refs['registered_interactions']=table('registered_interactions',pd.DataFrame(interaction_rows))
    refs['simultaneous_bounds']=table('simultaneous_bounds',pd.DataFrame(ci_rows))
    refs['risk_coverage']=table('risk_coverage',risk_coverage)
    refs['nonml_gross_controls']=table('nonml_gross_controls',control['rows'])
    for key in ('state_numerical','volatility_downside','projection_quality','marginal_stability','uncertainty','native_request','native_aggregate'):
        refs['risk_'+key]=table('risk_'+key,risk_diagnostics[key])
    repair_path=o.RESULT/'R10_R3_PCA_CONSUMER_ENGINEERING_REPAIR.json'
    repair=o.read_json(repair_path) if repair_path.exists() else {}
    if repair:
        if repair.get('approved') is not True or repair.get('reviewed') is not True:
            raise RuntimeError('R10_RISK_REPAIR_RECEIPT_NOT_APPROVED')
        if repair.get('risk_fit_started_before_repair')!=0:raise RuntimeError('R10_RISK_REPAIR_NOT_PRE_FIT')
        actual_pins=risk_result.get('actual_producer_consumer_code_pins')
        if actual_pins and actual_pins!=repair.get('new_code_pins'):
            raise RuntimeError('R10_RISK_REPAIR_ACTUAL_SOURCE_PINS')
    source_custody=[dict(path=path,frozen_sha256=expected,actual_sha256=o.fit_owner.sha(path),
                        role='PROTECTED_UNCHANGED') for path,expected in design.get('protected_source_pins',{}).items()]
    if repair:
        source_custody.append(dict(path=str(repair_path),receipt_sha256=o.fit_owner.sha(repair_path),
                   role='APPROVED_SAME_SCIENCE_PRE_RISK_FIT_ENGINEERING_REPAIR',
                   old_code_pins=repair.get('old_code_pins'),new_code_pins=repair.get('new_code_pins'),
                   actual_code_pins=risk_result.get('actual_producer_consumer_code_pins'),
                   source_authority_upgraded=False))
    refs['source_custody']=table('source_custody',pd.DataFrame(source_custody))
    def numeric_bounds(prefix):
        return [dict(component=key,**value) for key,value in bounds.items() if prefix in key]
    def publication_numbers(match):
        return [{k:row.get(k) for k in ('component','year','legal_rows','coverage','date_balanced_improvement',
                                       'date_balanced_regret','action_rate','wrong_action_rate')}
                for row in publication_rows if match(row)]
    unstable=[dict(component=key,**value) for key,value in bounds.items()
              if value.get('yearly_improvement',{}).get('2024') is not None
              and value.get('yearly_improvement',{}).get('2025') is not None
              and value['yearly_improvement']['2024']>0 and value['yearly_improvement']['2025']<=0]
    evidence={
        '1':{'implementation_reuse':'Native/tabular/Torch/fusion/shared-risk owners reused; changed action/state targets require new scientific fits',
             'formal_new_projection':'Four-marginal Gaussian, joint role sequence, risk-conditioned action; prior exact fit receipts not replaced by mere implementation presence'},
        '2':{'method':'Matched risk-source comparisons and registered interactions; no post-result rescue','tested_matched_contrasts':numeric_bounds('LEARNED_RISK_PAIRED'),
             'matched_supported_count':sum(row.get('status')=='MECHANISM_SUPPORTED' for row in numeric_bounds('LEARNED_RISK_PAIRED')),
             'tables':[refs['registered_interactions'],refs['simultaneous_bounds']]},
        '3':{'method':'All representations reported, support requires two positive official years plus simultaneous lower bound','representation_year_values':publication_numbers(lambda row:'_R' in str(row.get('group')) and row.get('capacity')=='MID'),
             'native_source_coverage_counts':dict(Counter(risk_coverage.status)) if 'status' in risk_coverage else {},
             'table':refs['risk_coverage']},
        '4':{'method':'Compare matched regret and action rate jointly, no claim from lower turnover alone','paired_action_and_regret':[row for row in interaction_rows if 'vsR0' in row.get('name','')],
             'table':refs['resolver_coverage']},
        '5':{'method':'Native uncertainty only; wrong-action and missed-opportunity rates on same planned REPLACE support','paired_native_gate_values':[r for r in numeric_bounds('NATIVE_U') if '|REPLACE_EDGE|' in r['component']],
             'paired_replacement_error_values':[r for r in native_uncertainty_rows if r.get('role')=='REPLACE_EDGE'],
             'wrong_action_year_values':publication_numbers(lambda row:row.get('role')=='REPLACE_EDGE'),
             'table':refs['publications']},
        '6':{'status':'Probe-conditional mechanism; no actual fill age or continuous survival authority','official_year_values':publication_numbers(lambda row:row.get('role')=='HAZARD'),
             'conditional_probe_count':sum(len(row) for row in duration_rows),
             'independence_from_Raw_rank_not_established_without_matched_ablation':True,'table':refs['hazard_probe_duration']},
        '7':{'status':'Four native horizon anchors; report all horizons/capacities, no horizon selection','native_horizon_year_values':[dict(component=k,**v) for k,v in bounds.items() if any('|'+str(h)+'|' in k for h in inputs.HORIZONS)],
             'table':refs['simultaneous_bounds']},
        '8':{'method':'S1/S2/S3 vs same-mask S0 date-paired; missing 2024 L5/L10 S3 preserved','paired_values':numeric_bounds('SEQUENCE_PAIRED'),'tested_pair_count':len(numeric_bounds('SEQUENCE_PAIRED')),'table':refs['simultaneous_bounds']},
        '9':{'method':'Fitted fusion vs both fixed Ridge/HGB anchors; Equal/Median vs every 14 point member; simultaneous family correction','paired_values':numeric_bounds('FUSION_PAIRED'),'supported_pair_count':sum(v.get('status')=='MECHANISM_SUPPORTED' for v in numeric_bounds('FUSION_PAIRED')),'table':refs['simultaneous_bounds']},
        '10':{'status':'BLOCKED_INPUT' if gross_frame is None or not gross_frame.information_supported.any() else 'SEE_FULL_NATIVE_GRID_ONLY',
              'reason':'Unknown native ML context stays unknown; independent declared nonML controls continue','controls':control['summaries']},
        '11':{'method':'All model yearly improvements in CI table; 2024 positive/2025 nonpositive is instability, no new fit triggered','unstable_component_count':len(unstable),'unstable_components':unstable,'table':refs['simultaneous_bounds']},
        '12':{'supported_components':supported,'count':len(supported),'qualification':'Historical conditional mechanism; no account promotion'},
        '13':{'source_account_slots':source_slots,'authority':source_status,'information_exposure':exposure},
        '14':{'actual':actual,'cap':1200,'bucket_usage':dict(buckets),'caps':o.CAPS,'failed_start_units_included':True,'failed_scientific_slots':failed_scientific_slots,
              'failed_started_physical_units':failed_started_physical,'prediction_failed_slots':prediction_failures,
              'shared_risk_failed_started_physical_units':failed_risk_physical},
        '15':{'automatic_R11_created':False,'R9_fit_budget_consumed_by_R10':0,'future_fit_needs_distinct_authorized_identity':True}}
    questions=question_report(evidence,budget_actual=actual,authorities=source_status,
                             preservation={'protected_source_audit':audits,'R9_174_budget_consumed':0})
    summary={'schema':'R10_COMPLETION_REPORT_R1','status':terminal,'run_directory':str(run),'report_directory':str(report_root),
             'scientific_identity':inputs.IDENTITY,'frozen_design_sha256':o.fit_owner.sha(run/'FROZEN_DESIGN.json'),
             'fit_units_actual':actual,'fit_units_cap':1200,'bucket_usage':dict(buckets),'bucket_caps':o.CAPS,
             'fit_receipt_status_counts':dict(rcounts),'failed_scientific_slots':failed_scientific_slots,
             'failed_started_physical_units':failed_started_physical,'prediction_failed_slots':prediction_failures,
             'shared_risk_failed_started_physical_units':failed_risk_physical,
             'blocked_input_receipts_and_risk_blocks':input_blocks,'publication_errors':publication_errors,
             'source_custody_audits':audits,'tables':refs,'mechanism_supported':supported,
             'simultaneous_ci':bounds,'comparison_templates':comparison_templates(),'questions':questions,
             'coverage':bundle.metadata_coverage,'risk_owner_summary':{k:risk_result.get(k) for k in ('schema','attempted_learned_units','failed_started_units','source_notes')},
             'closed_scope_items':[
                 {'item':'DIRECT_POLICY_CONTEXTUAL_BANDIT_DIAGNOSTIC','status':'BLOCKED_REQUIRED_BEHAVIOR_SUPPORT',
                  'required':'Source-qualified behavior action propensity and positivity; proxy state cannot manufacture either','fit_units':0},
                 {'item':'COX','status':'BLOCKED_VALID_SURVIVAL_SCHEMA_OR_DEPENDENCY','fit_units':0},
                 {'item':'NEWS_NLP_LLM_EMBEDDING','status':'NOT_SCHEDULED_FORBIDDEN_SCOPE','fit_units':0},
                 {'item':'RL','status':'NOT_SCHEDULED_FORBIDDEN_SCOPE','fit_units':0}],
             'risk_numerical_quality_owner':risk_diagnostics['diagnostic_owner_path'],'risk_diagnostic_owner_sha256':risk_diagnostics['diagnostic_owner_sha256'],
             'approved_source_repair':repair,'risk_blocks':risk_blocks,'nonml_gross_controls':control['summaries'],'fixed_action_cost_sensitivity':cost_evidence,'information_exposure':exposure,
             'batch_completion':batch_status,'report_generation_new_fit':0,
             'CI_zero_se':'Conservative CI_NOT_TESTABLE; no degenerate positive support fabricated',
             'account_authorized':False,'source_activated':False,'real_account':0,'real_candidate':0,
             'R9_174_budget_consumed':0,'automatic_R11_created':False,**o.AUTHORITY}
    o.save(report_root/'R10_COMPLETION.json',summary)
    o.save(report_root/'R10_QUESTIONS_15.json',questions)
    lines=['# V24 A R10 完成报告','',
           f'状态：**{terminal}**。本报告只评价冻结历史下的 conditional stateful mechanism。',
           f'实际 physical fit：**{actual}/1200**。公司行动、报价和真实账户 authority 未升级；真实账户及候选执行均为 0。',
           '','训练与验证仅使用 2026-01-01 前合法输入。正式年度模型为 2024、2025；2023 是机械基准和事先冻结的有限 Q4 OOF，不是新独立留出集。',
           '数值市场/标签/预测表的 2026 行读取和拟合选择为 0；此前源码注释含历史 2026 个案信息的意外暴露已单独记录，不能声称绝对“2026 信息零暴露”，也不恢复历史留出独立性。',
           f'[信息暴露回执]({exposure_path.as_posix()})','',
           '## 目标与实际方法','',
           '冻结 Raw A2 Selection，研究 Entry、统一 SELL/REPLACE vs HOLD、continuation/hazard、sequence、risk-conditioned action、fusion 和 scalar Gross/Cash。现有唯一 owner 被复用，未创建新账户引擎或新报价权威。',
           'Entry 与 Incumbent 是两组实际 fit；REPLACE_EDGE 是后者的 exact subset，0 额外 fit。目标为四个原生 horizon 的等权 action advantage，独立 horizon anchors 保留各自全部合法行。',
           '所有模型、capacity、seed、风险表示和 resolver 都按事前设计保留；失败不重训，不按经济结果扩预算。',
           '','## 预算与故障','',
           '| 桶 | 实际 | 上限 |','|---|---:|---:|']
    lines.extend(f'| {bucket} | {buckets[bucket]} | {cap} |' for bucket,cap in o.CAPS.items())
    lines.extend(['',f'Fit receipt 状态：{dict(rcounts)}。输入阻塞项：{input_blocks}。已失败科学 slot：{failed_scientific_slots}；失败启动 physical units：{failed_started_physical}（含共享风险 {failed_risk_physical}）；已训练但预测失败 slot：{prediction_failures}。slot 与 physical unit 分开计数。',
                  'FAILED、BLOCKED、缺失 uncertainty、缺失 native risk 和 source 问题均保留在表中；未被替代为成功或 0。',
                  '零 bootstrap SE 采用保守 CI_NOT_TESTABLE，不给虚假的正向支持。',
                  '','## 结果与限制','',
                  f'MECHANISM_SUPPORTED 项数：{len(supported)}。全部比较使用同一 simultaneous max-T 家族；不选最佳 seed、capacity、年份或窗口。',
                  '二元 local regret 只描述事前指定的单个动作边；完整 incumbent oracle 必须拥有所有已声明动作标签。缺标签不会删 rival 后再冒称完整 oracle。',
                  'Gross 需要完整 Raw20、四个原生 endpoint、全部 OOF forecast/native sigma 和原生 risk context。未知 regime probability 或 downside matrix 不替换为 indicator、no-risk 或 survivor basket。',
                  'Hazard 只拥有合法成熟的 H5 probes；未制造 continuous survival/censor 时间或真实 fill age。sequence 与 static 用相同样本直接配对。',
                  '','## 15 项问题',''])
    answers=human_question_answers(evidence,refs=refs,actual=actual,failed=failed,blocked=input_blocks)
    for row,answer in zip(questions['questions'],answers):
        lines.extend([f"{row['id']}. **{row['question']}**",'',answer,''])
        if row['id']==10:
            lines.extend(['| 控制 | 状态 | 合法日期 | 2024 增量 | 2025 增量 |',
                          '|---|---|---:|---:|---:|'])
            def number(value):return '未知' if value is None else f'{float(value):.6g}'
            for control_row in control['summaries']:
                yy=control_row.get('yearly_improvement',{})
                lines.append(f"| {control_row['control']} | {control_row['status']} | {control_row['legal_dates']} | {number(yy.get('2024'))} | {number(yy.get('2025'))} |")
            lines.append('')
    lines.extend(['## 证据与未完成工作','',
                  '| 证据 | 路径 |','|---|---|'])
    lines.extend(f'| {key} | [{Path(ref["path"]).name}]({Path(ref["path"]).as_posix()}) |' for key,ref in refs.items())
    lines.extend(['','五个 source/account slot 仍 UNBOUND。真实 RAW_s10、frozen37、BREADTH19 和 R9 account-state 训练继续遵守原独立 gate；R10 的研究机制结果不解除这些阻塞。',
                  '本次完成所有输入允许的工作。下一步只补精确缺失 authority/input 或履行此前冻结的账户顺序；不自动建立 R11，不自动增加 fit。',
                  f'','[机器可读完成回执]({(report_root/"R10_COMPLETION.json").as_posix()})',''])
    report=report_root/'REPORT.md';report.write_text('\n'.join(lines),encoding='utf-8')
    o.save(run/'COMPLETION_RECEIPT.json',dict(status=terminal,report_path=str(report),report_sha256=o.fit_owner.sha(report),
           completion_path=str(report_root/'R10_COMPLETION.json'),completion_sha256=o.fit_owner.sha(report_root/'R10_COMPLETION.json'),
           fit_units_actual=actual,real_account=0,real_candidate=0,source_activated=False,**o.AUTHORITY))
    o.save(run/'EXECUTION_STATUS.json',dict(status=terminal,started_physical_fits=actual,bucket_usage=dict(buckets),
           bucket_caps=o.CAPS,report_path=str(report),mechanism_supported_count=len(supported),real_accounts=0,
           real_account_candidates=0,source_activated=False,automatic_R11_created=False,**o.AUTHORITY))
    task_path=o.RESULT/'TASK_RECORD.json'
    task=o.read_json(task_path) if task_path.exists() else {}
    task.update(status=terminal,run_directory=str(run),report_path=str(report),fit_units_actual=actual,real_accounts=0,
                real_account_candidates=0,source_activated=False,automatic_R11_created=False,**o.AUTHORITY)
    o.save(task_path,task)
    o.save(o.RESULT/'R10_LATEST_COMPLETION.json',dict(status=terminal,report_path=str(report),run_directory=str(run),
           report_sha256=o.fit_owner.sha(report),fit_units_actual=actual,**o.AUTHORITY))
    return summary


def native_distribution_contrasts(frame,prediction,*,owner=None):
    """Fixed same-family U1/U2 diagnostics; capability cannot create a fit."""
    _guard(frame);o=_owner(owner);n=len(frame)
    mean=_array(prediction,'mean',n);median=_array(prediction,'q50',n)
    point=mean if np.isfinite(mean).any() else median
    base={'frame':frame.copy(),'action':np.where(np.isfinite(point),(point>0).astype(float),np.nan)}
    q10=_array(prediction,'q10',n);sigma=_array(prediction,'sigma',n)
    streams={
        'U1':{'frame':frame.copy(),'action':np.where(np.isfinite(q10),(q10>0).astype(float),np.nan)},
        'U2':{'frame':frame.copy(),'action':np.where(np.isfinite(mean)&np.isfinite(sigma)&(sigma>=0),
                                                  (mean-sigma>0).astype(float),np.nan)}}
    output={}
    for label,left in streams.items():
        if not np.isfinite(left['action']).any():
            output[label]={'status':'BLOCKED_NO_NATIVE_CAPABILITY','fit_units':0}
        else:output[label]=paired_stream_contrast(left,base,name=label+'vsPOINT',owner=o)
    return output


def nonml_gross_controls(gross_by_horizon,risk_result,*,owner=None,native_q_grid=None):
    """Already-declared G0..G4 controls, independent of ML context availability.

    Local four-endpoint utility is exactly the established Gross target formula.
    Scalar risk values are consumed from the shared producer without covariance
    estimation, source promotion, replacement probability or survivor baskets.
    """
    o=_owner(owner)
    if set(gross_by_horizon)!=set(inputs.HORIZONS):raise ValueError('ALL_NATIVE_GROSS_HORIZONS_REQUIRED')
    packets={}
    for h,f in gross_by_horizon.items():
        _guard(f)
        if f.signal_date.duplicated().any():raise ValueError('RAW20_HORIZON_DATE_DUPLICATE')
        packets[h]=f.set_index('signal_date')
    risk={}
    for item in (risk_result or {}).get('projections',[]):
        req=item.get('request',{})
        if req.get('horizon')!=5 or req.get('cohort')!='FROZEN_RAW20_EQUAL':continue
        key=(pd.Timestamp(req['date']),item.get('representation'))
        if key in risk:raise ValueError('NONML_GROSS_RISK_PROJECTION_DUPLICATE')
        risk[key]=item
    native_q_grid=native_q_grid.copy() if native_q_grid is not None else None
    if native_q_grid is not None:_guard(native_q_grid)
    rows=[];summaries=[]
    dates=sorted(set().union(*(set(p.index) for p in packets.values())))
    for date in dates:
        raw=[packets[h].loc[date] if date in packets[h].index else None for h in inputs.HORIZONS]
        first=next((v for v in raw if v is not None),None)
        names=tuple(first.get('basket_members',())) if first is not None else ()
        sids=tuple(first.get('basket_sids',())) if first is not None else ()
        complete=len(names)==len(sids)==20 and len(set(names))==20 and all(inputs._sid(v) for v in sids)
        ys=[];clocks=[]
        for v in raw:
            accepted=v is not None and (isinstance(v.get('label_qualified'),(bool,np.bool_)) and bool(v.get('label_qualified')))
            if not accepted or v.get('raw20_count')!=20 or tuple(v.get('basket_members',()))!=names or tuple(v.get('basket_sids',()))!=sids:
                complete=False;continue
            if not np.isfinite(v.get('basket_y',np.nan)) or pd.isna(v.get('label_mature_date')):
                complete=False;continue
            ys.append(float(v['basket_y']));clocks.append(pd.Timestamp(v['label_mature_date']))
        complete &= len(ys)==4
        def scalar(rep,field):
            item=risk.get((date,rep))
            if item is None:return np.nan
            req=item['request'];uid=req.get('uids',{})
            if set(req.get('reference_assets',()))!=set(names) or any(uid.get(name)!=sid for name,sid in zip(names,sids)):
                return np.nan
            features=item['projection'].get('features',{})
            if field=='portfolio_sigma':
                value=item['projection'].get('diagnostics',{}).get('predicted_portfolio_sigma',np.nan)
            else:value=features.get(field,np.nan)
            return float(value) if np.ndim(value)==0 and np.isfinite(value) else np.nan
        sigma=scalar('R1','portfolio_sigma')
        downside=scalar('R4','portfolio_downside_sigma')
        regime=scalar('R5','p_high_vol_regime')
        choices={'G0':1.,
                 'G1':float(np.clip(VOL_TARGET/sigma,0,1)) if np.isfinite(sigma) and sigma>0 else 1. if sigma==0 else np.nan,
                 'G2':float(np.clip(VOL_TARGET/downside,0,1)) if np.isfinite(downside) and downside>0 else 1. if downside==0 else np.nan,
                 'G4':1-regime if np.isfinite(regime) and 0<=regime<=1 else np.nan}
        for previous in GRID:
            def utility(gross):
                # Exact owner gross_decision_frame target, not U(mean y).
                return float(np.mean([gross*y-FRICTION*abs(gross-previous)-FRICTION*gross*(1+y)
                                     -5*gross*gross*y*y for y in ys]))
            best=max(utility(g) for g in GRID) if complete else np.nan
            ref=utility(1.) if complete else np.nan
            g3=np.nan
            if native_q_grid is not None and 'q10' in native_q_grid:
                q=native_q_grid.loc[native_q_grid.signal_date.eq(date)&native_q_grid.gross_previous_proxy.eq(previous)]
                if len(q)==5 and set(q.gross_candidate)==set(GRID) and np.isfinite(q.q10).all():
                    g3=float(q.sort_values(['q10','gross_candidate'],ascending=[False,True]).iloc[0].gross_candidate)
            for control,gross in {**choices,'G3':g3}.items():
                known=complete and np.isfinite(gross) and 0<=gross<=1
                realized=utility(gross) if known else np.nan
                rows.append({'signal_date':date,'sample_id':f'{date.date()}|GP{previous}|{control}',
                             'control':control,'gross_previous_proxy':previous,'selected_G':gross,
                             'native_four_horizon_all20':bool(complete),'known':bool(known),
                             'label_mature_date':max(clocks) if complete else pd.NaT,
                             'realized_native_utility':realized,'reference_native_utility':ref,
                             'improvement':realized-ref if known else np.nan,
                             'finite_grid_opportunity_gap':best-realized if known else np.nan,
                             'not_complete_continuous_gross_oracle':True,
                             'risk_representation':{'G0':'NONE','G1':'R1','G2':'R4','G3':'NATIVE_GROSS_Q10','G4':'R5'}[control],
                             'information_supported_ML_context_required':False,'account_qualified':False})
    out=pd.DataFrame(rows);series={}
    for control in ('G0','G1','G2','G3','G4'):
        part=out.loc[out.control.eq(control)] if len(out) else pd.DataFrame()
        legal=part.loc[part.known.eq(True)] if len(part) else part
        daily=legal.groupby('signal_date').improvement.mean() if len(legal) else pd.Series(dtype=float)
        yearly={str(year):float(daily.loc[pd.DatetimeIndex(daily.index).year==year].mean())
                if len(daily) and (pd.DatetimeIndex(daily.index).year==year).any() else None for year in (2023,2024,2025)}
        summaries.append({'control':control,'status':'AVAILABLE_PROXY_ONLY' if len(legal) else 'BLOCKED_NATIVE_INPUT',
                          'legal_dates':len(daily),'known_rows':len(legal),'planned_rows':len(part),
                          'date_balanced_improvement':float(daily.mean()) if len(daily) else None,
                          'yearly_improvement':yearly,'selected_G_mean':float(legal.selected_G.mean()) if len(legal) else None,
                          'threshold_frozen':VOL_TARGET if control in ('G1','G2') else None,
                          'new_fit':0,'source_account_authority_upgraded':False})
        if len(daily):series['NONML_GROSS|'+control]=daily
    return {'rows':out,'summaries':summaries,'series':series,
            'utility_source_owner':'stateful_mechanism_inputs.gross_decision_frame',
            'utility_contract':'MEAN_OF_FOUR_NATIVE_U_H_NOT_U_OF_MEAN',
            'continuous_controls_compared_to_G1_reference_not_claimed_discrete_oracle':True,'new_fit':0}


def rebind_published_metadata(published,canonical):
    """Restore only exact canonical custody metadata; never predictions or labels."""
    _guard(published);_guard(canonical)
    keys=['signal_date','sample_id']
    if canonical.duplicated(keys).any():raise ValueError('CANONICAL_CUSTODY_KEY_DUPLICATE')
    wanted=pd.MultiIndex.from_frame(published[keys])
    source=canonical.set_index(keys).reindex(wanted).reset_index()
    if source[['signal_date','sample_id']].isna().any().any():
        raise ValueError('PUBLISHED_CUSTODY_KEY_UNBOUND')
    if not pd.MultiIndex.from_frame(canonical[keys]).get_indexer(wanted).min(initial=0)>=0:
        raise ValueError('PUBLISHED_CUSTODY_KEY_UNBOUND')
    for column in ('target','reference_action','base_weight'):
        if column in published and column in source:
            if not np.array_equal(published[column].to_numpy(float),source[column].to_numpy(float),equal_nan=True):
                raise ValueError('PUBLISHED_CANONICAL_'+column.upper())
    for column in ('label_mature_date',):
        if column in published and column in source:
            if not pd.to_datetime(published[column]).reset_index(drop=True).equals(pd.to_datetime(source[column]).reset_index(drop=True)):
                raise ValueError('PUBLISHED_CANONICAL_MATURITY')
    for column in ('ticker','security_id','incumbent','entrant','entrant_sid','incumbent_sid'):
        if column in published and column in source:
            def token(value):
                return ('MISSING',) if pd.isna(value) else ('PRESENT',value)
            if published[column].map(token).tolist()!=source[column].map(token).tolist():
                raise ValueError('PUBLISHED_CANONICAL_SECURITY_IDENTITY_'+column)
    if 'label_qualified' in source and np.any(_literal(published.label_qualified)&~_literal(source.label_qualified)):
        raise ValueError('PUBLISHED_CANONICAL_LABEL_PROMOTION')
    restored=published.copy()
    custody=('entrant_sid','incumbent_sid','pre_label_group_weight','source_label_identity',
             'basket_members','basket_sids','raw20_count','cohort_id','probe_age','hazard_at_risk',
             'right_censored_unknown','information_supported','label_quantity_multiplier',
             'identity_epoch','required_actionset_count','required_actionset_sha256')
    for column in custody:
        if column not in source:continue
        if column in restored:
            a=restored[column].reset_index(drop=True);b=source[column].reset_index(drop=True)
            def comparable(value):
                if isinstance(value,(tuple,list,np.ndarray)):return tuple(value)
                return value
            if not a.map(comparable).equals(b.map(comparable)):
                raise ValueError('PUBLISHED_CANONICAL_CUSTODY_CONFLICT_'+column)
        else:restored[column]=source[column].to_numpy()
    return restored


def risk_diagnostic_tables(risk_result,bundle,*,owner=None):
    """Consume source-owned pure diagnostics; no second risk estimator/cache."""
    from scripts.research.a2.risk import mechanism_risk_diagnostics as d
    o=_owner(owner);states=(risk_result or {}).get('states',[])
    numerical=d.state_numerical_diagnostics(states)
    forecast_checks=[];projection_quality=[];marginal=[];uncertainty=[]
    packets=getattr(bundle,'native_endpoint_labels',{})
    observations={}
    for h,packet in packets.items():
        _guard(packet)
        observations[h]=inputs.native_risk_observations(packet)
    for state in states:
        if state.covariance is None:continue
        assets=tuple(state.assets);uids={a:state.coverage.get(a,{}).get('uid') for a in assets}
        annual=int(pd.Timestamp(state.as_of).year)
        if state.horizon not in observations:
            forecast_checks.append({'risk_state_id':state.risk_state_id,'status':'BLOCKED_NATIVE_OBSERVATIONS'});continue
        try:
            row=d.volatility_downside_diagnostic(state,observations[state.horizon],assets=assets,uids=uids,
                       reference_assets=assets,evaluation_end=pd.Timestamp(f'{min(annual+1,2026)}-01-01',tz='UTC'))
            forecast_checks.append(row)
        except (ValueError,KeyError,TypeError) as exc:
            forecast_checks.append({'risk_state_id':state.risk_state_id,'status':'BLOCKED_CALIBRATION_INPUT',
                                    'reason':str(exc),'horizon':state.horizon,'fit_year':annual})
    previous={}
    for item in sorted((risk_result or {}).get('projections',[]),key=lambda item:(str(item['request']['date']),str(item['representation']),str(item['request'].get('horizon')),str(item['request'].get('cohort')))):
        req=item['request'];value=item['projection'];representation=item['representation']
        date=pd.Timestamp(req['date']);inputs._pre2026(pd.Series([date]))
        diagnostics=value.get('diagnostics',{})
        features=value.get('features',{})
        projection_quality.append({'signal_date':date,'representation':representation,
             'horizon':req.get('horizon'),'cohort':req.get('cohort'),'assets':len(req.get('assets',())),
             'predicted_portfolio_sigma':diagnostics.get('predicted_portfolio_sigma'),
             'numerical_diagnostics':diagnostics,
             'state_refs':item.get('state_refs'),'quote_qualified':False,'account_qualified':False})
        assets=tuple(req.get('assets',()));uids=req.get('uids',{})
        values=features.get('normalized_marginal_risk')
        sigma=features.get('stock_sigma')
        group_features=features.get('group_features',{})
        uncertainty.append({'signal_date':date,'representation':representation,'horizon':req.get('horizon'),
            'cohort':req.get('cohort'),'source_owned_estimation_uncertainty':group_features.get('R6',{}),
            'native_uncertainty_feature':features.get('jackknife_sigma_SE'),
            'native_disagreement_feature':features.get('covariance_disagreement'),
            'capability_present':any('jackknife' in k or 'disagreement' in k for k in features) or bool(group_features.get('R6'))})
        if values is None:continue
        a=np.asarray(values,float)
        if a.shape!=(len(assets),) or not np.isfinite(a).all():continue
        key=(representation,req.get('horizon'),req.get('cohort'))
        current={name:(uids.get(name),float(v)) for name,v in zip(assets,a)}
        old=previous.get(key)
        if old:
            prior,coords=old
            common=[name for name in current if name in coords and current[name][0]==coords[name][0]]
            delta=[abs(current[name][1]-coords[name][1]) for name in common]
            marginal.append({'signal_date':date,'prior_date':prior,'representation':representation,
                  'horizon':req.get('horizon'),'cohort':req.get('cohort'),'same_sid_common_assets':len(common),
                  'mean_abs_normalized_marginal_change':float(np.mean(delta)) if delta else None,
                  'status':'SOURCE_OWNED_MARGINAL_STABILITY_ONLY' if delta else 'BLOCKED_COMMON_SID',
                  'cross_year':date.year!=prior.year,'new_fit':0})
        previous[key]=(date,current)
    if observations:
        native=d.projection_native_diagnostics((risk_result or {}).get('projections',[]),
                   pd.concat(observations.values(),ignore_index=True),evaluation_end=pd.Timestamp('2026-01-01',tz='UTC'))
    else:
        native={'request_rows':[{'status':'BLOCKED_NATIVE_OBSERVATION_SCHEMA_UNBOUND','new_fit':0}],
                'aggregate_rows':[]}
    return {'native_request':pd.DataFrame(native['request_rows']),'native_aggregate':pd.DataFrame(native['aggregate_rows']),
            'state_numerical':pd.DataFrame(numerical),'volatility_downside':pd.DataFrame(forecast_checks),
            'projection_quality':pd.DataFrame(projection_quality),'marginal_stability':pd.DataFrame(marginal),
            'uncertainty':pd.DataFrame(uncertainty),
            'shared_exact_refs_not_reloaded':(risk_result or {}).get('shared_exact_refs',[]),
            'diagnostic_owner_path':d.__file__,'diagnostic_owner_sha256':o.fit_owner.sha(d.__file__),
            'new_fit':0,'diagnostics_not_used_for_rule_selection':True}

def human_question_answers(evidence,*,refs,actual,failed,blocked):
    """Chinese factual summaries of all predeclared evidence; no selection."""
    def counts(rows):
        valid=[r for r in rows if r.get('pooled_improvement') is not None]
        both=[r for r in valid if all(r.get('yearly_improvement',{}).get(str(y)) is not None
                      and r['yearly_improvement'][str(y)]>0 for y in (2024,2025))]
        return len(rows),len(valid),len(both),sum(r.get('status')=='MECHANISM_SUPPORTED' for r in rows)
    def link(key):
        value=refs.get(key,{})
        return f'[{key}]({str(value.get("path","")).replace(chr(92),"/")})'
    q=evidence;rows=[]
    rows.append(f'复用现有 tabular、Torch、fusion 与共享 risk 实现。本轮改变了动作目标与状态输入，因此是新的机制试验。实际 physical fit 为 {actual}；旧科学身份未重复拟合。')
    n,v,b,s=counts(q['2']['tested_matched_contrasts'])
    rows.append(f'已登记的配对风险学习比较有 {n} 项，其中 {v} 项可评价、{b} 项在 2024 和 2025 都为正、{s} 项通过 simultaneous 支持门。尚未通过的比较不能宣称 risk 有增量。详见 {link("simultaneous_bounds")}。')
    values=q['3']['representation_year_values']
    available=sum(r.get('date_balanced_improvement') is not None for r in values)
    rows.append(f'风险表示共有 {len(values)} 条模型年度结果，其中 {available} 条有可评价的成本后动作增量。来源覆盖状态为 {q["3"]["native_source_coverage_counts"]}。全部表示逐年列在 {link("publications")}；没有根据收益另选表示或窗口。')
    paired=q['4']['paired_action_and_regret']
    valid=[r for r in paired if r.get('left_action_rate') is not None and r.get('right_action_rate') is not None]
    lower=sum(r['left_action_rate']<r['right_action_rate'] for r in valid)
    rows.append(f'风险 resolver 的年度配对记录有 {len(paired)} 条；{len(valid)} 条可同时比较动作频率，{lower} 条减少了动作。频率下降不能代替 regret 改善。配对 regret 和错动作率见 {link("registered_interactions")}。')
    n,v,b,s=counts(q['5']['paired_native_gate_values'])
    paired=[r for r in q['5']['paired_replacement_error_values'] if r.get('left_wrong_action_rate') is not None and r.get('right_wrong_action_rate') is not None]
    reduced=sum(r['left_wrong_action_rate']<r['right_wrong_action_rate'] for r in paired)
    rows.append(f'REPLACE 的原生 uncertainty gate 有 {n} 项配对假设，{v} 项有可计算增量，{b} 项两年都为正，{s} 项通过 simultaneous 支持门。{len(paired)} 条年度配对可比较错动作，其中 {reduced} 条减少错 replacement；同时保留漏机会和 regret，不能仅凭少交易判定更好。详见 {link("native_uncertainty_paired")} 和 {link("simultaneous_bounds")}。')
    hazard=q['6']['official_year_values']
    hp=sum(r.get('date_balanced_improvement') is not None and r['date_balanced_improvement']>0 for r in hazard)
    rows.append(f'Hazard 有 {len(hazard)} 条年度结果，其中 {hp} 条动作增量为正；可输出的条件 probe-duration 记录为 {q["6"]["conditional_probe_count"]} 条。现有试验没有 matched Raw-rank ablation，因此尚未证明独立于 Raw rank。没有制造连续 survival 时间。详见 {link("hazard_probe_duration")}。')
    n,v,b,s=counts(q['7']['native_horizon_year_values'])
    rows.append(f'四个原生 horizon 产生 {n} 项结果，{v} 项可评价，{b} 项两年都为正，{s} 项达到 simultaneous 支持。每个 horizon 使用自己的全部合法行，不以完整四期限交集替代独立期限样本。详见 {link("simultaneous_bounds")}。')
    n,v,b,s=counts(q['8']['paired_values'])
    rows.append(f'Sequence 对同 mask 的 static S0 有 {n} 项配对，{v} 项可评价，{b} 项两年都为正，{s} 项达到 simultaneous 支持。L5/L10 的 2024 S3 缺真正 OOF，保持阻塞。详见 {link("simultaneous_bounds")}。')
    n,v,b,s=counts(q['9']['paired_values'])
    rows.append(f'Fusion 对预登记成员有 {n} 项配对，{v} 项可评价，{b} 项两年都为正，{s} 项达到 simultaneous 支持。拟合 fusion 同时对 Ridge/HGB；Equal/Median 对全部 14 个 point 成员，不挑较弱成员。详见 {link("simultaneous_bounds")}。')
    gross=q['10']['controls']
    available=sum(r.get('legal_dates',0)>0 for r in gross)
    rows.append(f'ML Gross 状态为 {q["10"]["status"]}。5 个已登记 non-ML controls 中 {available} 个拥有合法成熟日期；它们继续独立评价，不用未知 ML context 阻断。下表给出 G0–G4 的实际覆盖与逐年增量。')
    rows.append(f'有 {q["11"]["unstable_component_count"]} 项在 2024 为正、2025 非正。完整逐项结果见 {link("simultaneous_bounds")}；此诊断不触发重训、重选 horizon 或增加预算。')
    rows.append(f'MECHANISM_SUPPORTED 共 {q["12"]["count"]} 项。它只代表冻结历史下的条件机制证据，不代表真实账户、报价资格或交易许可。详见 {link("simultaneous_bounds")}。')
    slots=q['13']['source_account_slots']
    rows.append(f'{len(slots)} 个 source/account slot 继续 UNBOUND。真实账户与候选执行为 0。2026 数值表行读取与拟合选择为 0；此前源码注释信息暴露已披露，历史留出独立性没有恢复。')
    rows.append(f'实际预算使用 {actual}/1200 physical fit；失败启动计入预算。已失败科学 slot 为 {q['14']['failed_scientific_slots']}，失败启动 physical units 为 {q['14']['failed_started_physical_units']}（含共享风险 {q['14']['shared_risk_failed_started_physical_units']}）；已训练但预测失败 slot 为 {q['14']['prediction_failed_slots']}。输入阻塞记录计数为 {blocked}。各桶实际与上限已在预算表列出；报告生成新增 fit 为 0。')
    rows.append('没有创建 R11，也没有消费 R9 的 174-fit 预算。下一步先完成来源和账户 authority，再遵循 RAW_s10 一次 → frozen37 → BREADTH19 → 已预登记 R9 的独立顺序；本轮机制结果不能解除 gate。')
    return rows
