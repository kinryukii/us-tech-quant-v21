"""R6/R7 bounded supervised adapter; reuses frozen reader, fit ACK and owned lock.
No account engine, selector training, provider fetch or real-data access on import.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from scripts.research.a2.training import stateful_inputs as inputs
from scripts.research.a2.training import stateful_values as values
from scripts.research.a2.training import stateful_decision_models as models
from scripts.research.a2.training import stateful_execution as execution
from scripts.research.a2.training import stateful_breadth as breadth
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

R6='V24_A_DIRECT_DECISION_LEARNING_PRE2026_R6'
R7='V24_A_LEARNED_GROSS_CASH_PRE2026_R7'
YEARS=(2023,2024,2025)
OBJECTIVES=('buy','hold','replace','duration','distribution')
LEARNERS=('linear','tree','neural')
G=np.array([0.,.25,.5,.75,1.])
S=.001
STATE=('raw_rank','raw_score','rank_change','score_change','cohort_age_sessions','entrant','raw_member','friction')
SINGLE=tuple(inputs.FEATURES)+STATE
PAIR=tuple(prefix+c for prefix in ('e_','i_','delta_') for c in SINGLE)
GROSS=tuple('mean_'+c for c in inputs.FEATURES)+('raw_score_mean','raw_score_std','raw_score_width','diagonal_vol_proxy','gross_previous_proxy','friction')
LABEL_COLS=('signal_date','ticker','security_id','label_mature_date','feature_available','label_available','account_event_unhandled','label_unsupported_common_event','y_open5')
PRED_EXTRA=('raw_a2_rank','raw_a2_prediction','raw_a2_oof_split')


def counterfactual_edges(y_e,y_i=None):
    y=np.asarray(y_e,float)
    if not np.isfinite(y).all() or (y < -1).any():raise ValueError('INVALID_SHAREHOLDER_RETURN')
    k=(1-S)/(1+S)
    result={'buy':k*(1+y)-1,'hold':(1-S)*y}
    if y_i is not None:
        i=np.asarray(y_i,float)
        if not np.isfinite(i).all() or (i < -1).any():raise ValueError('INVALID_INCUMBENT_RETURN')
        result['replace']=(1-S)*(k*(1+y)-(1+i))
    return result


def gross_utilities(y,gprev):
    y=np.asarray(y,float);p=np.asarray(gprev,float)
    if not np.isfinite(y).all() or (y < -1).any() or not np.isin(p,G).all():raise ValueError('INVALID_GROSS_LOCAL_COORDINATE')
    return y[...,None]*G-S*np.abs(G-p[...,None])-S*G*(1+y[...,None])-5*G**2*y[...,None]**2


def gross_targets(y,gprev):
    utility=gross_utilities(y,gprev);target=[]
    for row,p in zip(utility,np.asarray(gprev,float)):
        choices=np.flatnonzero(row==row.max())
        target.append(min(choices,key=lambda j:(abs(G[j]-p),G[j])))
    return np.asarray(target,int)


def date_weights(dates,edge=None):
    dates=pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    w=1/dates.map(dates.value_counts()).to_numpy(float)
    if edge is not None:
        e=np.abs(np.asarray(edge,float))
        total=pd.Series(e).groupby(dates).transform('sum').to_numpy(float)
        w=np.divide(e,total,out=w.copy(),where=total>0)
    if w.sum()<=0:raise ValueError('NO_POSITIVE_DATE_WEIGHT')
    return w/w.mean()


def encode_features(frame,columns):
    x=frame[list(columns)].to_numpy(float)
    if np.isinf(x).any():raise ValueError('INFINITE_FEATURE_FAIL_CLOSED')
    return np.column_stack((np.nan_to_num(x,nan=0.),np.isnan(x).astype(float))),tuple(columns)+tuple(c+'__missing' for c in columns)


def _valid_sid(sid):
    return pd.notna(sid) and str(sid).strip().lower() not in ('','nan','null','none','unknown','unbound','na','<na>')


def _legal_label(label,sid):
    if label is None or not _valid_sid(sid) or str(label['security_id'])!=str(sid):return False
    required={'feature_available':True,'label_available':True,'account_event_unhandled':False,'label_unsupported_common_event':False}
    if any(pd.isna(label.get(k)) or label.get(k) not in (True,False,0,1) or bool(label[k])!=expected for k,expected in required.items()):return False
    return (label['feature_available'] is not None and bool(label['feature_available'])
        and bool(label['label_available']) and not bool(label['account_event_unhandled'])
        and not bool(label.get('label_unsupported_common_event',False))
        and pd.notna(label['label_mature_date']) and pd.Timestamp(label['label_mature_date'])<inputs.BOUNDARY
        and np.isfinite(label['y_open5']) and label['y_open5']>=-1)


def _sample(base,objective,key,label,sid,edge=None):
    result=dict(base,objective=objective,sample_id=key,label_qualified=_legal_label(label,sid),target=np.nan,edge=np.nan,label_mature_date=pd.NaT)
    if result['label_qualified']:
        result.update(label_mature_date=pd.Timestamp(label['label_mature_date']),target=float(label['y_open5']),edge=float(edge if edge is not None else label['y_open5']))
    return result


def build_samples(pred,labels,calendar,*,descriptive_evaluation_authority=None):
    """Exogenous cohort features first; future labels only annotate fixed rows.
    No share/cash/NAV/fill simulation. Calendar t+1 inception, 21-session support.
    """
    pred=pred.copy();labels=labels.copy();calendar=pd.DatetimeIndex(pd.to_datetime(calendar))
    pred['signal_date']=pd.to_datetime(pred.signal_date);labels['signal_date']=pd.to_datetime(labels.signal_date)
    labels['label_mature_date']=pd.to_datetime(labels.label_mature_date)
    if descriptive_evaluation_authority is not None:
        if len(labels):raise ValueError('DESCRIPTIVE_TEST_INFERENCE_FORBIDS_LABEL_ROWS')
        from scripts.research.a2.evaluation.frozen_test_authority import validate_descriptive_input_dates
        validate_descriptive_input_dates(descriptive_evaluation_authority,pred.signal_date,feature_context=True)
        validate_descriptive_input_dates(descriptive_evaluation_authority,calendar,feature_context=True)
    elif pred.signal_date.ge(inputs.BOUNDARY).any() or labels.signal_date.ge(inputs.BOUNDARY).any() or calendar.max()>=inputs.BOUNDARY:
        raise ValueError('2026_LOCKED')
    if pred.duplicated(['signal_date','ticker']).any() or labels.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_SAMPLE_SOURCE')
    pred=pred.sort_values(['signal_date','ticker']).reset_index(drop=True)
    pred['raw_rank']=pred.raw_a2_rank;pred['raw_score']=pred.raw_a2_prediction
    grouped=pred.groupby(['ticker','security_id'],dropna=False,sort=False)
    pred['rank_change']=pred.raw_rank-grouped.raw_rank.shift(1)
    pred['score_change']=pred.raw_score-grouped.raw_score.shift(1)
    lookup={(pd.Timestamp(r.signal_date),str(r.ticker)):r._asdict() for r in labels.itertuples(index=False)}
    index={d:i for i,d in enumerate(calendar)}
    samples={o:[] for o in (*OBJECTIVES,'gross')};active={};probes={};audit={'cohort_type':'EXOGENOUS_UNIT_LOT_NOT_ACCOUNT','pair_selected_before_y':0,'pair_invalid_not_replaced':0,'gross_incomplete_label_dates':0,'sid_breaks':0,'raw20_input_opportunities':int(pred.is_raw_top20.sum()),'raw_buy_input_opportunities':int(pred.new_buy_eligible.sum()),'entrant_opportunities':0,'entrant_feature_excluded':0,'entrant_sid_unknown':0,'incumbent_proxy_opportunities':0,'incumbent_feature_excluded':0,'expected_raw_decision_dates':int(pred.signal_date.nunique()),'gross_raw20_or_feature_blocked_dates':0,'gross_scheduled_grid_rows':int(pred.signal_date.nunique())*5}
    for date,day in pred.groupby('signal_date',sort=True):
        ix=index[date];rows={str(r.ticker):r._asdict() for r in day.itertuples(index=False)}
        for ticker,c in list(active.items()):
            current=rows.get(ticker)
            changed=current is not None and (not _valid_sid(current['security_id']) or str(current['security_id'])!=c['sid'])
            if ix-c['inception']>=21 or changed:
                if changed:audit['sid_breaks']+=1
                active.pop(ticker);probes.pop(c['id'],None)
        top=day.loc[day.new_buy_eligible.astype(bool)].sort_values(['raw_rank','ticker'],na_position='last')
        entrants=[str(t) for t in top.ticker if str(t) not in active]
        audit['entrant_opportunities']+=len(entrants)
        audit['entrant_feature_excluded']+=sum(not bool(rows[t]['feature_available']) for t in entrants)
        audit['entrant_sid_unknown']+=sum(not _valid_sid(rows[t]['security_id']) for t in entrants)
        held=[t for t,c in active.items() if 0<=ix-c['inception']<21]
        audit['incumbent_proxy_opportunities']+=len(held)
        audit['incumbent_feature_excluded']+=sum(t not in rows or not bool(rows[t]['feature_available']) for t in held)
        features={}
        for ticker,row in rows.items():
            if not bool(row['feature_available']):continue
            c=active.get(ticker);age=ix-c['inception'] if c and ix>=c['inception'] else 0
            features[ticker]={**{f:float(row[f]) for f in inputs.FEATURES},**{f:row[f] for f in ('raw_rank','raw_score','rank_change','score_change')},'cohort_age_sessions':age,'entrant':float(ticker in entrants),'raw_member':float(bool(row['is_raw_top20'])),'friction':S}
        incumbents=sorted([t for t,c in active.items() if 0<=ix-c['inception']<21 and t in features],key=lambda t:(float(rows[t]['raw_rank']) if pd.notna(rows[t]['raw_rank']) else float('inf'),t))
        for ticker in sorted(set(entrants)|set(incumbents)):
            if ticker not in features:continue
            row=rows[ticker];lab=lookup.get((date,ticker));base=dict(features[ticker],signal_date=date,ticker=ticker,security_id=row['security_id'],cohort_id=active.get(ticker,{}).get('id','ENTRANT_'+str(date.date())+'_'+ticker))
            sample=_sample(base,'distribution',str(date.date())+'_'+ticker,lab,row['security_id'])
            samples['distribution'].append(sample)
            objective='buy' if ticker in entrants else 'hold'
            srow=_sample(base,objective,str(date.date())+'_'+ticker,lab,row['security_id'])
            if srow['label_qualified']:
                srow['edge']=float(counterfactual_edges(lab['y_open5'])[objective]);srow['target']=int(srow['edge']>0)
            samples[objective].append(srow)
            if objective=='hold' and features[ticker]['cohort_age_sessions'] in (0,7,14):
                c=active[ticker];previous=probes.get(c['id']);age=features[ticker]['cohort_age_sessions']
                risk=age==0 or (previous is not None and previous['probe_age']==age-7 and previous['legal'] and previous['mature']<date and previous['edge']>0)
                if risk:
                    h=dict(srow,objective='duration',probe_age=age,censor_endpoint=calendar[min(ix+6,len(calendar)-1)],target=int(srow['edge']<=0) if srow['label_qualified'] else np.nan)
                    samples['duration'].append(h)
                    probes[c['id']]={'probe_age':age,'legal':srow['label_qualified'],'mature':srow['label_mature_date'] if srow['label_qualified'] else h['censor_endpoint'],'edge':srow['edge']}
        for entrant in entrants:
            if entrant not in features:continue
            # At most two incumbent pairs per entrant, selected before label masks.
            chosen=[i for i in incumbents if i!=entrant][:2]
            for incumbent in chosen:
                audit['pair_selected_before_y']+=1
                e,i=features[entrant],features[incumbent];er,ir=rows[entrant],rows[incumbent]
                el,il=lookup.get((date,entrant)),lookup.get((date,incumbent))
                legal=_legal_label(el,er['security_id']) and _legal_label(il,ir['security_id'])
                r={**{'e_'+f:e[f] for f in SINGLE},**{'i_'+f:i[f] for f in SINGLE},**{'delta_'+f:e[f]-i[f] for f in SINGLE},'signal_date':date,'ticker':entrant,'incumbent':incumbent,'security_id':er['security_id'],'incumbent_sid':ir['security_id'],'sample_id':str(date.date())+'_'+entrant+'_'+incumbent,'objective':'replace','label_qualified':legal,'target':np.nan,'edge':np.nan,'label_mature_date':pd.NaT}
                if legal:
                    edge=float(counterfactual_edges(el['y_open5'],il['y_open5'])['replace'])
                    r.update(edge=edge,target=int(edge>0),label_mature_date=max(pd.Timestamp(el['label_mature_date']),pd.Timestamp(il['label_mature_date'])))
                else:audit['pair_invalid_not_replaced']+=1
                samples['replace'].append(r)
        # Scalar Gross has five exogenous prior states; never account cash/state.
        raw=day.loc[day.is_raw_top20.astype(bool)].sort_values(['raw_rank','ticker'])
        if len(raw)==20 and raw.raw_top20_set_complete.eq(True).all() and raw.feature_available.eq(True).all():
            labs=[lookup.get((date,str(r.ticker))) for r in raw.itertuples(index=False)]
            legal=all(_legal_label(l,str(r.security_id)) for l,r in zip(labs,raw.itertuples(index=False)))
            if not legal:audit['gross_incomplete_label_dates']+=1
            feature={**{'mean_'+f:float(np.mean(raw[f].to_numpy(float))) for f in inputs.FEATURES},'raw_score_mean':float(raw.raw_score.mean()),'raw_score_std':float(raw.raw_score.std(ddof=0)),'raw_score_width':float(raw.raw_score.max()-raw.raw_score.min()),'diagonal_vol_proxy':float(np.sqrt(np.sum(raw.realized_vol_20d.to_numpy(float)**2))/20),'friction':S}
            y=float(np.mean([l['y_open5'] for l in labs])) if legal else np.nan
            for p in G:
                r=dict(feature,gross_previous_proxy=float(p),signal_date=date,ticker='RAW20_BASKET',sample_id=str(date.date())+'_G'+str(p),objective='gross',label_qualified=legal,target=np.nan,edge=np.nan,label_mature_date=pd.NaT,basket_y=y)
                if legal:r.update(target=int(gross_targets(np.array([y]),np.array([p]))[0]),edge=y,label_mature_date=max(pd.Timestamp(l['label_mature_date']) for l in labs))
                samples['gross'].append(r)
        else:audit['gross_raw20_or_feature_blocked_dates']+=1
        # Membership-driven cohort creation uses only current source identity.
        for ticker in entrants:
            sid=rows[ticker]['security_id']
            if _valid_sid(sid) and ix+1<len(calendar):
                active[ticker]={'sid':str(sid),'inception':ix+1,'id':str(date.date())+'_'+str(sid)+'_'+ticker}
    return {o:pd.DataFrame(v) for o,v in samples.items()},audit


def split_sample(frame,fold):
    if frame.empty:return frame.copy(),frame.copy(),frame.copy()
    f=frame.copy();f['signal_date']=pd.to_datetime(f.signal_date);f['label_mature_date']=pd.to_datetime(f.label_mature_date)
    if f.signal_date.ge(inputs.BOUNDARY).any():raise ValueError('2026_LOCKED')
    legal=f.label_qualified.eq(True)&f.label_mature_date.notna()&f.label_mature_date.lt(inputs.BOUNDARY)&np.isfinite(f.target)
    train=f.loc[legal&f.signal_date.lt(fold['calibration_start'])&f.label_mature_date.lt(fold['calibration_start'])].copy()
    cal=f.loc[legal&f.signal_date.isin(fold['calibration_sessions'])&f.label_mature_date.lt(fold['cutoff_exclusive'])].copy()
    evaluation=f.loc[f.signal_date.ge(fold['cutoff_exclusive'])&f.signal_date.lt(pd.Timestamp(f"{fold['year']+1}-01-01"))].copy()
    return train,cal,evaluation


def bounded_training(frame,cap=12000):
    # Keys only, balanced deterministic cap; independent of y/model outcomes.
    if len(frame)<=cap:return frame.copy()
    f=frame.copy();f['_hash']=f.sample_id.map(lambda s:hashlib.sha256(str(s).encode()).hexdigest())
    f=f.sort_values(['signal_date','_hash']);f['_round']=f.groupby('signal_date').cumcount()
    return f.sort_values(['_round','signal_date','_hash']).iloc[:cap].drop(columns=['_hash','_round']).sort_values(['signal_date','sample_id']).reset_index(drop=True)


def specification():
    candidates=[]
    for objective in OBJECTIVES:
        for learner in LEARNERS:
            c=dict(candidate_id='R6_'+objective.upper()+'_'+learner.upper(),objective=objective,learner=learner,friction_bps=10,reference='RAW_s10',replace_only_declared_mechanism=True,risk='diag20_reference',gross='fixed_1',q='RAW20_EQUAL_REFERENCE',order=len(candidates)+1,failure_replacement=False,year_2023='REFERENCE_NO_R6_MODEL',support_fallback='REFERENCE_IF_SID_UNKNOWN_OR_AGE_OUTSIDE_0_20_OR_FEATURE_UNAVAILABLE',account_status='NOT_AUTHORIZED_SOURCE_UNBOUND')
            c['scientific_tuple_sha256']=values.digest(c);candidates.append(c)
    gross=[]
    for learner in LEARNERS:
        c=dict(candidate_id='R7_GROSS_'+learner.upper(),objective='gross',learner=learner,friction_bps=10,reference='RAW_s10',q='RAW20_EQUAL_REFERENCE',action='RAW_s10_REFERENCE',risk='diag20_reference',gross_grid=G.tolist(),order=len(gross)+1,failure_replacement=False,year_2023='REFERENCE_NO_R7_MODEL',account_status='NOT_AUTHORIZED_SOURCE_UNBOUND');c['scientific_tuple_sha256']=values.digest(c);gross.append(c)
    schedule=[dict(stage='R6',objective=o,learner=l,year=y,slot_id=f'{o}_{l}_{y}') for o in OBJECTIVES for l in LEARNERS for y in YEARS]+[dict(stage='R7',objective='gross',learner=l,year=y,slot_id=f'gross_{l}_{y}') for l in LEARNERS for y in YEARS]
    return dict(R6_identity=R6,R7_identity=R7,selector='FROZEN_RAW_A2_NO_RERANK',parent_label=inputs.LABEL,training_cutoff_exclusive='2026-01-01',**{'2026_locked':True},model_specifications=models.specifications(),schedule=schedule,R6_future_account_candidates=candidates,R7_future_account_candidates=gross,features=dict(single=list(SINGLE),pair=list(PAIR),gross=list(GROSS),encoding='ZERO_FILL_WITH_EXPLICIT_MISSING_FLAGS_NO_FIT'),budget=dict(R6_model_year_cap=45,R7_model_year_cap=9,R6_physical_fit_cap=81,R7_physical_fit_cap=15,prior_model_year_exposure=201,prior_physical_fits=455,prior_account_paths=89,new_account_paths_authorized=0,max_training_rows_per_objective_fold=12000,fit_timeout_seconds=1800,R6_wall_seconds=7200,R7_wall_seconds=3600,wall_budget_semantics='NO_NEW_SLOT_AFTER_STAGE_DEADLINE;CURRENT_SLOT_MAX_COMPONENTS_TIMES_1800_SECONDS;NO_RETRY',scientific_retry=0,seeds=[models.SEED]),folds='ANNUAL_JAN1;TRAIN_SIGNAL_AND_MATURITY_BEFORE_60_SESSION_CAL_START;CAL_MATURITY_BEFORE_CUTOFF;CAL_DIAGNOSTIC_ONLY',objective_labels=dict(buy='k*(1+y)-1',hold='(1-s)*y',replace='(1-s)*(k*(1+y_e)-(1+y_i));PAIR_MAX_2_PER_ENTRANT_CURRENT_RANK_TICKER_NO_LABEL_REPLACEMENT',duration='FIRST_OBSERVED_MATURE_NONPOSITIVE_FIVE_SESSION_PROBE_HAZARD;AGES_0_7_14;STRIDE7;SUPPORTED_POSITIVE_PREVIOUS_MATURE_BEFORE_CURRENT;UNKNOWN_CENSOR_TPLUS6',distribution='UNCLIPPED_PARENT_Y_NATIVE_QUANTILES_OR_NORMAL',gross='G*y-.001*abs(G-Gprev)-.001*G*(1+y)-5*G^2*y^2;ALL20_LABELS_REQUIRED;ALL5_EXOGENOUS_Gprev_DATEEQUAL;TIE_CLOSEST_Gprev_THEN_SMALLER'),cohort='EXOGENOUS_UNIT_LOT_START_CALENDAR_TPLUS1_21SESSIONS_SID_CUT_NO_ACCOUNT',training_weights='DATE_EQUAL_ABS_EDGE_NORMALIZED_WITHIN_DATE_FOR_BUY_HOLD_REPLACE;DATE_EQUAL_OTHERS;NOT_CALIBRATED_SUPERIORITY_PROB',action_rules=dict(classification='PREGRET>0.5;TIES_REFERENCE',duration='P_FAILURE>0.5_EXIT_ONLY_AT_FIXED_PROBES;OTHER_DAYS_REFERENCE',distribution_buy='median_buy_edge>0 and q10_buy_edge>=-.02 and width<=.25',distribution_hold='median_hold_edge>=0 and q10_hold_edge>=-.03 and width<=.30',distribution_replace='(1-s)*(k*(1+q10_entrant)-(1+q90_incumbent))>0;NO_JOINT_CDF_CLAIM'),evaluation='DATE_EQUAL_LOCAL_EDGE_REGRET_COVERAGE_SWITCH_RATE;NO_NAV_OR_WINNER',limitations=['Proxy unit-notional local labels, not self-financing account utilities','Gross friction excludes component turnover and cash constraints','Cohort age is not actual fill/holding age','2023 no prior frozen Raw surface: BLOCKED_INPUT; not R6/R7 OOF','2023/24/25 historical exposure retained, no fresh holdout claim'],workflow='SOURCE_ACCOUNT>RAW_s10_ONCE_SEVEN_TRUE>FROZEN37>BREADTH19>R6_ACCOUNTS>R7_ACCOUNTS>UNIFIED_REPORT>FINALIST_FREEZE>SEPARATELY_AUTHORIZED_2026',future_account_contract=dict(capital_usd=3000,fractional=True,long_only=True,financing=False,annual_reset=False,years=[2023,2024,2025],execution='ACTUAL_NEXT_LEGAL_OPEN',friction_bps=10,reference='EXACT_FROZEN_RAW_s10_ACCOUNT_PARAMETERS',requires_seven_literal_true_baseline=True),source_slots='ALL_UNBOUND',source_activated=False,Branch_N_adopted=False,new_fit_authorization='HUMAN_PASTED_R6_R7_REQUEST_ONLY_PRE2026_SUPERVISION')


def _publication(model,frame,columns):
    x,_=encode_features(frame,columns);p=models.predict(model,x)
    keep=[k for k in ('signal_date','sample_id','ticker','incumbent','security_id','label_qualified','label_mature_date','target','edge','basket_y','gross_previous_proxy','cohort_age_sessions') if k in frame]
    out=frame[keep].reset_index(drop=True).copy()
    for k,v in p.items():
        if k!='classes' and np.ndim(v)==1 and len(v)==len(out):out[k]=v
    if model.objective=='distribution':
        edge=counterfactual_edges(out.q50.to_numpy(float)) if (out.q50>=-1).all() else {'buy':(1-S)/(1+S)*(1+out.q50)-1,'hold':(1-S)*out.q50}
        buy=((edge['buy']>0)&((1-S)/(1+S)*(1+out.q10)-1>=-.02)&(out.width<=.25))
        hold=((edge['hold']>=0)&((1-S)*out.q10>=-.03)&(out.width<=.30))
        out['action']=np.where(frame.entrant.to_numpy(bool),buy,hold).astype(int)
        out['edge']=np.where(frame.entrant.to_numpy(bool),(1-S)/(1+S)*(1+frame.edge)-1,(1-S)*frame.edge)
        out['reference_action']=1
    elif model.objective=='gross':out['reference_action']=4
    elif model.objective=='duration':out['reference_action']=0;out['action']=(out.p_failure>.5).astype(int)
    else:
        out['reference_action']=1 if model.objective in ('buy','hold') else 0
        out['action']=((out.p_superior>=.5) if model.objective in ('buy','hold') else (out.p_superior>.5)).astype(int)
    return out



def distribution_replace_publication(model,pairs):
    # Exact preselected pairs, both sides of the same fitted marginal model.
    sides=[]
    for prefix in ('e_','i_'):
        f=pairs[[prefix+c for c in SINGLE]].copy()
        f.columns=list(SINGLE)
        x,_=encode_features(f,SINGLE);sides.append(models.predict(model,x))
    keep=[k for k in ('signal_date','sample_id','ticker','incumbent','security_id','incumbent_sid','label_qualified','label_mature_date','target','edge') if k in pairs]
    out=pairs[keep].reset_index(drop=True).copy()
    e,i=sides;k=(1-S)/(1+S)
    out['entrant_q10']=e['q10'];out['incumbent_q90']=i['q90']
    out['tail_replace_margin']=(1-S)*(k*(1+e['q10'])-(1+i['q90']))
    out['action']=(out.tail_replace_margin>0).astype(int);out['reference_action']=0
    return out


def metrics(out,objective):
    legal=out.loc[out.label_qualified.eq(True)&np.isfinite(out.target)].copy()
    result=dict(inference_rows=len(out),qualified_rows=len(legal),coverage=float(len(legal)/len(out)) if len(out) else 0.,qualified_dates=int(legal.signal_date.nunique()),metric_role='LOCAL_LABEL_OOF_NOT_ACCOUNT_NAV',coverage_denominator='CONDITIONAL_FEATURE_SUPPORTED_ROWS;RAW_OPPORTUNITY_EXCLUSIONS_IN_STATE_LABEL_AUDIT',primary_date_equal_regret=None,reference_date_equal_regret=None,action_switch_rate=None)
    if legal.empty:return result
    if objective=='gross':
        u=gross_utilities(legal.basket_y.to_numpy(float),legal.gross_previous_proxy.to_numpy(float));a=legal.action.to_numpy(int);regret=u.max(axis=1)-u[np.arange(len(u)),a];reference=u.max(axis=1)-u[:,4]
        legal['realized_local_utility']=u[np.arange(len(u)),a]
        result['date_equal_local_utility']=float(legal.groupby('signal_date').realized_local_utility.mean().mean())
        legal['stay_previous_regret']=u.max(axis=1)-u[np.arange(len(u)),np.rint(legal.gross_previous_proxy.to_numpy(float)*4).astype(int)]
        result['stay_previous_date_equal_regret']=float(legal.groupby('signal_date').stay_previous_regret.mean().mean())
    elif objective=='duration':
        # Hazard auxiliary loss is date-equal; economic hold/exit sign reverses action.
        take=1-legal.action.to_numpy(int);regret=np.maximum(legal.edge,0)-take*legal.edge;reference=np.maximum(legal.edge,0)-legal.edge
        p=legal.p_failure.clip(1e-9,1-1e-9);legal['logloss']=-(legal.target*np.log(p)+(1-legal.target)*np.log(1-p));result['date_equal_logloss']=float(legal.groupby('signal_date').logloss.mean().mean())
    else:
        take=legal.action.to_numpy(int);regret=np.maximum(legal.edge,0)-take*legal.edge;reference=np.maximum(legal.edge,0)-legal.reference_action*legal.edge
        legal['realized_local_edge']=take*legal.edge
        result['date_equal_realized_local_edge']=float(legal.groupby('signal_date').realized_local_edge.mean().mean())
    legal['regret']=regret;legal['reference_regret']=reference
    result['primary_date_equal_regret']=float(legal.groupby('signal_date').regret.mean().mean());result['reference_date_equal_regret']=float(legal.groupby('signal_date').reference_regret.mean().mean())
    result['date_equal_action_rate']=float(legal.groupby('signal_date').action.mean().mean())
    ordered=out.sort_values(['ticker','signal_date','sample_id']);key='incumbent' if 'incumbent' in out else 'gross_previous_proxy' if 'gross_previous_proxy' in out else None
    group=['ticker']+([key] if key else []);prior=ordered.groupby(group,dropna=False).action.shift(1)
    switch=ordered.loc[prior.notna()].copy();switch['switch']=(switch.action!=prior.loc[prior.notna()]).astype(float)
    result['action_switch_rate']=float(switch.groupby('signal_date').switch.mean().mean()) if len(switch) else None
    if objective=='distribution':
        legal['interval_cover']=((legal.target>=legal.q10)&(legal.target<=legal.q90)).astype(float)
        result['date_equal_q10_q90_coverage']=float(legal.groupby('signal_date').interval_cover.mean().mean());result['date_equal_width']=float(legal.groupby('signal_date').width.mean().mean())
    return result


def _source_pins():
    names=[Path(__file__),Path(models.__file__),Path(inputs.__file__),Path(values.__file__),values.NATIVE,values.FEATURE_SOURCE,values.FEATURE_CHECK]
    return {str(p):values.sha(p) for p in names}


def execute(run):
    run=Path(run).resolve();cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8'));contract=json.loads((run/'FROZEN_SPECIFICATION.json').read_text(encoding='utf-8'))
    if contract['specification_sha256']!=values.digest(contract['specification']) or contract['specification']!=specification():raise ValueError('FROZEN_SCIENTIFIC_SPEC_CHANGED')
    if cfg.get('account_authorized') is not False or cfg.get('source_activated') is not False or cfg.get('2026_locked') is not True:raise ValueError('SUPERVISED_SCOPE_ONLY')
    if cfg.get('registry_admission',{}).get('status')!='PASS':raise ValueError('REGISTRY_ADMISSION_REQUIRED')
    from scripts.maintenance import research_registry as registry
    for research_id in (R6,R7):
        registry.verify_a_decision_admission(values.REPO.parent/'us-tech-quant-results/US_TECH_QUANT_RESEARCH_REGISTRY',research_id=research_id,frozen_spec_sha256=values.sha(run/'FROZEN_SPECIFICATION.json'),input_manifest_sha256=contract['input_manifest_sha256'],training_source_pins=contract['source_pins'])
    if contract['source_pins']!=_source_pins():raise ValueError('FROZEN_SOURCE_CHANGED')
    breadth.protected_custody()
    reader=inputs.InputReader(run)
    if values.sha(run/'input_manifest.json')!=contract['input_manifest_sha256']:raise ValueError('FROZEN_INPUT_MANIFEST_CHANGED')
    with execution.continuation_lock(run,values.sha(Path(__file__)),namespace=R6):
        # Every parquet footer/hash is verified by canonical reader before numeric reads.
        predcols=list(dict.fromkeys((*inputs.PRED_FLAGS,*inputs.FEATURES,*PRED_EXTRA)))
        pred=reader._vectors('prediction_feature_panel',predcols,[('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',inputs.BOUNDARY)])
        # Unsupported/unavailable labels are never read numerically; metadata flags
        # preserve missing inference rows and source-defined censoring.
        flags=reader._vectors('value_training_panel',list(LABEL_COLS[:-1]),[('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',inputs.BOUNDARY)])
        targets=reader._vectors('value_training_panel',['signal_date','ticker','y_open5'],[('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',inputs.BOUNDARY),('label_available','==',True),('account_event_unhandled','==',False),('label_unsupported_common_event','==',False),('label_mature_date','<',inputs.BOUNDARY)])
        labels=flags.merge(targets,on=['signal_date','ticker'],how='left',validate='one_to_one')
        samples,stateaudit=build_samples(pred,labels,reader.calendar)
        write_json_atomic(run/'STATE_LABEL_AUDIT.json',dict(stateaudit,input_y_changed=False,proxy_state_not_account=True,test_2026_numeric_rows_read=0,sample_counts={k:len(v) for k,v in samples.items()}))
        log=run/'FIT_LOG.jsonl';slots=[]
        for stage in ('R6','R7'):
            start=time.monotonic();stagewall=contract['specification']['budget'][stage+'_wall_seconds']
            for slot in [s for s in contract['specification']['schedule'] if s['stage']==stage]:
                path=run/'models/decision'/slot['slot_id'];receipt_path=path/'fit_receipt.json';receipt={**slot,'receipt_path':str(receipt_path),'status':'RUNNING','fit_units':0,'seed':models.SEED,'role':'DIRECT_DECISION' if stage=='R6' else 'SCALAR_GROSS','specification_sha256':contract['specification_sha256']}
                if receipt_path.exists():
                    old=json.loads(receipt_path.read_text(encoding='utf-8'))
                    if old['specification_sha256']!=contract['specification_sha256']:raise ValueError('SLOT_IDENTITY_CHANGED')
                    if old['status']=='RUNNING':
                        write_json_atomic(path/'interrupted_original_receipt.json',old)
                        old.update(status='FAILED',error='INTERRUPTED_ORPHAN_NO_SCIENTIFIC_RETRY',automatic_retry=False)
                        values._append(run/'FIT_LOG.jsonl',dict(event='MODEL_YEAR_ATTEMPT_FAILED',model_id=slot['slot_id'],year=slot['year'],stage=slot['stage'],fit_units=old.get('fit_units',0),scientific_tuple_sha256=old.get('scientific_tuple_sha256')))
                        write_json_atomic(receipt_path,old)
                    if old['status']=='TRAINED':
                        for name in ('model','oof'):
                            if values.sha(Path(old[name+'_path']))!=old[name+'_sha256']:raise ValueError('EXACT_REUSE_ARTIFACT_CHANGED')
                        if old.get('distribution_replace_oof_path') and values.sha(Path(old['distribution_replace_oof_path']))!=old['distribution_replace_oof_sha256']:raise ValueError('EXACT_REUSE_PAIR_OOF_CHANGED')
                        if old.get('scientific_tuple_sha256')!=values.digest(old.get('scientific_tuple')):raise ValueError('EXACT_REUSE_TUPLE_CHANGED')
                    if old['status'] not in ('TRAINED','FAILED','BLOCKED_INPUT','NOT_EXECUTED_WALL_BUDGET'):raise ValueError('UNKNOWN_NONTERMINAL_SLOT_NO_REUSE')
                    slots.append(old);continue
                path.mkdir(parents=True,exist_ok=True)
                o,l,y=slot['objective'],slot['learner'],slot['year'];columns=PAIR if o=='replace' else GROSS if o=='gross' else SINGLE
                if y==2023:
                    receipt.update(status='BLOCKED_INPUT',reason='NO_PRE2023_FROZEN_RAW_RANK_MEMBERSHIP_HISTORY',model_year_attempted=False)
                    write_json_atomic(receipt_path,receipt);slots.append(receipt);continue
                if time.monotonic()-start>=stagewall:
                    receipt.update(status='NOT_EXECUTED_WALL_BUDGET',model_year_attempted=False);write_json_atomic(receipt_path,receipt);slots.append(receipt);continue
                train,cal,evaluation=split_sample(samples[o],reader.annual_fold(y));train=bounded_training(train)
                if len(train)<20 or (o!='distribution' and train.target.nunique()<2):
                    receipt.update(status='BLOCKED_INPUT',reason='INSUFFICIENT_LEGAL_CHRONOLOGICAL_ROWS_OR_CLASSES',model_year_attempted=False,training_rows=len(train));write_json_atomic(receipt_path,receipt);slots.append(receipt);continue
                x,features=encode_features(train,columns);weight=date_weights(train.signal_date,train.edge if o in ('buy','hold','replace') else None)
                tupleidentity=dict(slot=slot,contract_sha256=contract['specification_sha256'],input_manifest_sha256=contract['input_manifest_sha256'],training_rows_sha256=hashlib.sha256(pd.util.hash_pandas_object(train[['signal_date','sample_id','label_mature_date','target',*columns]],index=False).values.tobytes()).hexdigest(),feature_order=list(features),training_signal_max=str(train.signal_date.max()),training_maturity_max=str(train.label_mature_date.max()),calibration_start=str(reader.annual_fold(y)['calibration_start']),seed=models.SEED)
                tuplesha=values.digest(tupleidentity);receipt.update(model_year_attempted=True,scientific_tuple=tupleidentity,scientific_tuple_sha256=tuplesha,training_rows=len(train),calibration_rows=len(cal),inference_rows=len(evaluation))
                values._append(log,dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id=slot['slot_id'],year=y,stage=stage,scientific_tuple_sha256=tuplesha));write_json_atomic(receipt_path,receipt)
                auth=dict(max_fit_units=551,max_new_bucket_fit_units=81 if stage=='R6' else 15,budget_bucket=stage)
                t=time.monotonic()
                try:
                    target=dict(objective=o,learner=l,target=train.target.to_numpy(float),sample_weight=weight,source_sha256=models.source_sha256(),seed=models.SEED)
                    model=values._fit_job('decision',slot['slot_id'],x,target,train.signal_date.to_numpy(),None,cfg['dependency_paths'],features,None,log=log,auth=auth,prior=455,year=y,tuple_sha=tuplesha,receipt=receipt,worker_target=models.worker)
                    expected=models.specifications()['fit_units']['distribution' if o=='distribution' else 'classification'][l]
                    if receipt['fit_units']!=expected:raise RuntimeError('FIT_COMPONENT_COUNT_MISMATCH')
                    model_path=path/'model.joblib';joblib.dump(model,model_path);receipt.update(model_sha256=values.sha(model_path),model_path=str(model_path))
                    publication=_publication(model,evaluation,columns);oof=path/'oof.parquet';assert_write_path(oof,'backtest');publication.to_parquet(oof,index=False)
                    if o=='distribution':
                        _,_,pairs=split_sample(samples['replace'],reader.annual_fold(y))
                        pairout=distribution_replace_publication(model,pairs)
                        pairpath=path/'distribution_replace_oof.parquet';assert_write_path(pairpath,'backtest');pairout.to_parquet(pairpath,index=False)
                        receipt.update(distribution_replace_oof_path=str(pairpath),distribution_replace_oof_sha256=values.sha(pairpath),distribution_replace_metrics=metrics(pairout,'replace'))
                    receipt.update(status='TRAINED',oof_path=str(oof),oof_sha256=values.sha(oof),label_oof_metrics=metrics(publication,o),calibration_diagnostic=metrics(_publication(model,cal,columns),o),runtime_seconds=time.monotonic()-t,actual_warnings=model.metadata['warnings'])
                except Exception as exc:
                    receipt.update(status='FAILED',error=type(exc).__name__+':'+str(exc),runtime_seconds=time.monotonic()-t,automatic_retry=False)
                values._append(log,dict(event='MODEL_YEAR_ATTEMPT_'+receipt['status'],model_id=slot['slot_id'],year=y,stage=stage,fit_units=receipt['fit_units'],scientific_tuple_sha256=tuplesha));write_json_atomic(receipt_path,receipt);slots.append(receipt)
                write_json_atomic(run/'EXECUTION_STATUS.json',dict(status='SUPERVISED_RUNNING',completed_slots=len(slots),scheduled_slots=54,last_slot=slot['slot_id'],last_state=receipt['status'],source_activated=False,new_accounts=0))
                print(json.dumps({k:receipt.get(k) for k in ('slot_id','status','fit_units','runtime_seconds','error')},ensure_ascii=False),flush=True)
        counts=pd.Series([s['status'] for s in slots]).value_counts().to_dict();physical=sum(s.get('fit_units',0) for s in slots)
        summary=dict(status='SUPERVISED_BATCH_TERMINAL',R6_identity=R6,R7_identity=R7,slot_counts=counts,scheduled_model_year_slots=54,model_year_attempts=sum(s.get('model_year_attempted',False) for s in slots),new_physical_fits=physical,cumulative_model_year_exposure=201+sum(s.get('model_year_attempted',False) for s in slots),cumulative_physical_fits=455+physical,real_account_paths=0,real_account_candidates=0,source_activated=False,Branch_N_adopted=False,test_2026_numeric_rows_read=0,account_status='NOT_TESTABLE_SOURCE_UNBOUND',slots=slots)
        write_json_atomic(run/'SUPERVISED_SUMMARY.json',summary);write_json_atomic(run/'EXECUTION_STATUS.json',{k:v for k,v in summary.items() if k!='slots'})
        print(json.dumps({k:v for k,v in summary.items() if k!='slots'},ensure_ascii=False),flush=True)
        return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);args=parser.parse_args();execute(args.run)

