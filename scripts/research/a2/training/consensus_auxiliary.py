"""Pure caller-bound diagnostics and real account-environment policy learning.

No research readers, file writers, static-label RL, or primary-PTO overrides.
The caller freezes and authenticates the source contract and persists artifacts.
Every estimator/statistics fit requests the caller's global-budget callback first.
"""
from __future__ import annotations
from dataclasses import dataclass,field
import copy
import hashlib
import json
import warnings
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.ensemble import IsolationForest
from sklearn.decomposition import PCA,FactorAnalysis
from sklearn.preprocessing import StandardScaler
from scripts.research.a2.training.stateful_inputs import FEATURES,ALLOWED_SOURCES
from scripts.research.a2.training.stateful_value_extensions import _torch,TORCH_SNAPSHOT

SEED=20260928
CAPS=(0.,.25,.5,.75,.95)
RECIPE=dict(seed=SEED,epochs=12,hidden=32,learning_rate=.001,gamma=.99,gae_lambda=.95,
    ppo_clip=.2,ppo_updates_per_rollout=4,value_weight=.5,entropy_weight=.01,gradient_clip=2.,
    observation_scaling='CALLER_FROZEN_CAUSAL_ACCOUNT_NORMALIZED_NO_FIT',activity_caps=list(CAPS),
    reward_years=[2021,2022],reward_definition='NET_CERTIFIED_NAV_RETURN_NO_EXTERNAL_FLOWS',max_steps_per_segment=600,no_early_stop=True,no_seed_search=True)
ACCOUNT_FIELDS=('settled_cash_ratio','unsettled_cash_ratio','gross_weight','name_count_fraction')


def require(ok,message):
    if not ok:raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def started(callback,component,method,identity):
    require(callable(callback),'GLOBAL_FIT_BUDGET_CALLBACK_REQUIRED')
    callback(dict(component=component,method=method,fit_units=1,identity_sha256=identity))


def not_testable(reason):return dict(status='NOT_TESTABLE',reason=reason,fitted=False,primary_pto_changed=False)


@dataclass
class AuxiliaryFit:
    scaler:object
    models:dict
    receipt:dict

    def diagnostics(self,frame):
        x=frame[list(FEATURES)].to_numpy(float);require(np.isfinite(x).all(),'NONFINITE_DIAGNOSTIC_FEATURES')
        z=self.scaler.transform(x);out=frame[['signal_date','ticker']].copy()
        for name,model in self.models.items():
            if name=='kmeans5':out['cluster']=model.predict(z)
            elif name=='gmm5':
                probabilities=model.predict_proba(z)
                for i in range(5):out['gmm_probability_'+str(i)]=probabilities[:,i]
            elif name=='isolation_forest100':out['anomaly_score']=model.decision_function(z)
            else:
                transformed=model.transform(z)
                for i in range(5):out[name+'_component_'+str(i)]=transformed[:,i]
        out.attrs['scope']='DIAGNOSTICS_ONLY_NO_PRIMARY_PTO_OR_ELIGIBILITY_CHANGE'
        return out


def fit_auxiliary(frame,*,cutoff,source_contract,on_fit_started):
    cutoff=pd.Timestamp(cutoff)
    if not isinstance(source_contract,dict) or source_contract.get('feature_source_qualified') is not True:
        return not_testable('QUALIFIED_PAST_32_FEATURE_SOURCE_REQUIRED')
    require(pd.Timestamp('2020-01-01')<cutoff<=pd.Timestamp('2026-01-01'),'AUXILIARY_PRE2026_CUTOFF_REQUIRED')
    require(source_contract.get('feature_order')==list(FEATURES),'FROZEN_32_FEATURE_ORDER_REQUIRED')
    dates=pd.to_datetime(frame.signal_date)
    require((dates<cutoff).all() and not frame.duplicated(['signal_date','ticker']).any(),'PAST_UNIQUE_AUXILIARY_KEYS_REQUIRED')
    require(frame.feature_available.eq(True).all() and frame.feature_source.isin(ALLOWED_SOURCES).all(),'SOURCE_QUALIFIED_FEATURE_ROWS_REQUIRED')
    if 'feature_available_at' in frame:require((pd.to_datetime(frame.feature_available_at)<=dates).all(),'FUTURE_AUXILIARY_INFORMATION')
    x=frame[list(FEATURES)].to_numpy(float);require(len(x)>=5 and np.isfinite(x).all(),'FIVE_FINITE_PAST_ROWS_REQUIRED')
    identity=digest(dict(source_contract=source_contract,cutoff=cutoff.isoformat(),features=list(FEATURES),
        input_sha256=hashlib.sha256(pd.util.hash_pandas_object(frame[['signal_date','ticker',*FEATURES]],index=False).to_numpy().tobytes()).hexdigest(),seed=SEED))
    started(on_fit_started,'TRAIN_ONLY_32_STANDARD_SCALER','auxiliary',identity)
    scaler=StandardScaler().fit(x);z=scaler.transform(x);models={};status={}
    factories=dict(kmeans5=lambda:KMeans(n_clusters=5,random_state=SEED,n_init=10),
        gmm5=lambda:GaussianMixture(n_components=5,random_state=SEED),
        isolation_forest100=lambda:IsolationForest(n_estimators=100,random_state=SEED,n_jobs=1),
        pca5=lambda:PCA(n_components=5,svd_solver='full',random_state=SEED),
        fa5=lambda:FactorAnalysis(n_components=5,random_state=SEED))
    for name,factory in factories.items():
        started(on_fit_started,'NATIVE_'+name.upper(),name,identity)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always');model=factory().fit(z)
            require(not any(w.category.__name__ in ('ConvergenceWarning','RuntimeWarning') for w in caught),'NATIVE_UNRESOLVED_FIT_WARNING_NO_RETRY')
            if hasattr(model,'converged_'):require(model.converged_,'NATIVE_FIXED_FIT_NOT_CONVERGED')
            models[name]=model;status[name]=dict(status='FITTED')
        except Exception as error:status[name]=dict(status='FAILED_NO_RETRY',type=type(error).__name__,reason=str(error))
    return AuxiliaryFit(scaler,models,dict(status='FITTED_DIAGNOSTICS_ONLY',methods=status,identity_sha256=identity,
        source_contract=source_contract,fit_units=6,source_vintage='UNKNOWN_RETAINED',strict_PIT_certified=False,primary_pto_changed=False))


def environment_contract(env):
    if env is None:return None
    c=getattr(env,'source_contract',None)
    if not isinstance(c,dict) or not callable(getattr(env,'reset',None)) or not callable(getattr(env,'step',None)):return None
    flags=('causal_observations','source_qualified','stateful_cash_holdings_fee_account','actual_fees_in_reward','episode_segments_frozen')
    if any(c.get(key) is not True for key in flags):return None
    if c.get('training_reward_years')!=[2021,2022] or c.get('activity_caps')!=list(CAPS):return None
    if c.get('observation_scaling')!=RECIPE['observation_scaling'] or c.get('reward_definition')!=RECIPE['reward_definition']:return None
    if not isinstance(c.get('environment_source_sha256'),str) or len(c['environment_source_sha256'])!=64:return None
    if c.get('account_owner')!='scripts.research.a2.evaluation.consensus_cash_account.run_cash_account':return None
    if not isinstance(c.get('account_owner_sha256'),str) or len(c['account_owner_sha256'])!=64:return None
    dependencies=c.get('dependency_paths',[])
    if not isinstance(dependencies,(list,tuple)) or any(not isinstance(p,str) for p in dependencies) or str(TORCH_SNAPSHOT) not in dependencies:return None
    fields=c.get('observation_fields',[])
    if not isinstance(fields,(list,tuple)) or any(not isinstance(f,str) for f in fields):return None
    if len(fields)<4 or len(set(fields))!=len(fields) or not set(ACCOUNT_FIELDS)<=set(fields):return None
    segments=c.get('reset_segments',[])
    if not isinstance(segments,(list,tuple)) or not segments:return None
    if any(not isinstance(s,dict) or not isinstance(s.get('segment_id'),str) or not s['segment_id'] or 'start' not in s or 'end_exclusive' not in s for s in segments):return None
    if len({s['segment_id'] for s in segments})!=len(segments):return None
    previous=pd.Timestamp('2021-01-01')
    try:
        for segment in segments:
            lower,upper=pd.Timestamp(segment['start']),pd.Timestamp(segment['end_exclusive'])
            if not previous<=lower<upper<=pd.Timestamp('2023-01-01'):return None
            previous=upper
    except (TypeError,ValueError):return None
    return copy.deepcopy(c)


def validate_state(state,contract,segment,previous=None):
    fields=contract['observation_fields'];obs=np.array(state['observation'],dtype=float,copy=True)
    legal=np.array(state['legal_actions'],copy=True)
    require(obs.shape==(len(fields),) and np.isfinite(obs).all(),'CAUSAL_FINITE_ACCOUNT_OBSERVATION_REQUIRED')
    require(legal.shape==(len(CAPS),) and legal.dtype==bool,'FIVE_EXPLICIT_LEGAL_ACCOUNT_ACTIONS_REQUIRED')
    terminated=state['terminated'];require(isinstance(terminated,(bool,np.bool_)),'EXPLICIT_TERMINATION_REQUIRED')
    require(terminated or legal.any(),'NO_LEGAL_ACCOUNT_ACTIVITY_CAP')
    date=pd.Timestamp(state['as_of']);lower=pd.Timestamp(segment['start']);upper=pd.Timestamp(segment['end_exclusive'])
    require(lower<=date<upper and date<pd.Timestamp('2023-01-01'),'RL_STATE_OUTSIDE_FROZEN_2021_2022_SEGMENT')
    require(previous is None or date>previous,'RL_STEP_MUST_ADVANCE_CAUSAL_CLOCK')
    require(state['source_qualified'] is True,'UNQUALIFIED_ACCOUNT_STATE')
    account=state['account_state']
    required=('settled_cash','unsettled_receivable','corporate_receivable','nav','position_units','position_market_values','cumulative_fees','nav_identity_error')
    require(set(required)<=set(account),'STATEFUL_CASH_POSITIONS_FEES_RECEIPT_REQUIRED')
    scalars=np.array([account[k] for k in ('settled_cash','unsettled_receivable','nav','cumulative_fees','nav_identity_error')],float)
    require(np.isfinite(scalars).all() and (scalars[:4]>=0).all() and account['nav']>0 and abs(account['nav_identity_error'])<=1e-7,'INVALID_ACCOUNT_NAV_CASH_FEE_RECEIPT')
    units=np.asarray(account['position_units'],float);require(units.ndim==1 and np.isfinite(units).all() and (units>=0).all(),'ACTUAL_NONNEGATIVE_POSITION_STATE_REQUIRED')
    marked=np.asarray(account['position_market_values'],float);corporate=float(account['corporate_receivable'])
    require(marked.shape==units.shape and np.isfinite(marked).all() and (marked>=0).all() and np.isfinite(corporate) and corporate>=0,'CERTIFIED_MARKED_POSITION_VALUES_REQUIRED')
    require(np.all(marked[units==0]==0) and abs(account['settled_cash']+account['unsettled_receivable']+corporate+marked.sum()-account['nav'])<=1e-7,'ACTUAL_ACCOUNT_NAV_RECONCILIATION_REQUIRED')
    if previous is not None:
        reward=float(state['reward']);mature=pd.Timestamp(state['reward_mature_at'])
        require(np.isfinite(reward) and previous<mature<=date and mature<upper and mature<pd.Timestamp('2023-01-01'),'RL_REWARD_NOT_MATURE_WITHIN_TRAINING_SEGMENT')
        fee=float(state['transaction_fee_usd']);require(np.isfinite(fee) and fee>=0,'ACTUAL_STEP_TRANSACTION_FEE_REQUIRED')
    return obs,legal,date,bool(terminated)


def network(torch,method,dimension):
    return torch.nn.Sequential(torch.nn.Linear(dimension,32),torch.nn.Tanh(),
        torch.nn.Linear(32,32),torch.nn.Tanh(),torch.nn.Linear(32,6 if method=='ppo' else 5))


def gae(rewards,values,terminated,gamma=.99,lam=.95,bootstrap=0.):
    rewards=np.asarray(rewards,float);values=np.asarray(values,float);done=np.asarray(terminated,bool)
    require(rewards.shape==values.shape==done.shape and rewards.ndim==1,'GAE_ROLLOUT_COORDINATES_REQUIRED')
    advantage=np.zeros(len(rewards));following=float(bootstrap);carry=0.
    for i in range(len(rewards)-1,-1,-1):
        continuation=0. if done[i] else 1.
        delta=rewards[i]+gamma*following*continuation-values[i]
        carry=delta+gamma*lam*continuation*carry;advantage[i]=carry;following=values[i]
    return advantage,advantage+values


def discounted(rewards,gamma=.99):
    out=np.zeros(len(rewards));carry=0.
    for i in range(len(rewards)-1,-1,-1):carry=float(rewards[i])+gamma*carry;out[i]=carry
    return out


@dataclass
class RLFit:
    method:str
    contract:dict
    weights:dict
    receipt:dict
    _model:object=field(default=None,repr=False)

    def activity_cap(self,observation,legal_actions):
        torch=_torch(self.contract.get('dependency_paths',()))
        if self._model is None:
            self._model=network(torch,self.method,len(self.contract['observation_fields']))
            self._model.load_state_dict({k:torch.from_numpy(v.copy()) for k,v in self.weights.items()});self._model.eval()
        obs=np.asarray(observation,np.float32);legal=np.asarray(legal_actions,bool)
        require(obs.shape==(len(self.contract['observation_fields']),) and np.isfinite(obs).all() and legal.shape==(5,) and legal.any(),'LEGAL_CAUSAL_GATE_OBSERVATION_REQUIRED')
        with torch.no_grad():logits=self._model(torch.from_numpy(obs))[:5].masked_fill(~torch.from_numpy(legal),-1e9)
        return CAPS[int(logits.argmax())]


def fit_account_rl(method,env,*,on_fit_started):
    require(method in ('reinforce','ppo'),'ACTUAL_REINFORCE_OR_PPO_REQUIRED')
    contract=environment_contract(env)
    if contract is None:return not_testable('MISSING_QUALIFIED_STATEFUL_ACCOUNT_ENVIRONMENT_NO_STATIC_Y_SUBSTITUTE')
    identity=digest(dict(method=method,recipe=RECIPE,environment=contract))
    torch=_torch(contract.get('dependency_paths',()));torch.set_num_threads(2);torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)
    model=network(torch,method,len(contract['observation_fields']));optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    started(on_fit_started,'ACCOUNT_RL_ACTOR_VALUE_NETWORK_12_EPOCHS' if method=='ppo' else 'ACCOUNT_RL_ACTOR_NETWORK_12_EPOCHS',method,identity)
    history=[];rollout_sha=hashlib.sha256();steps=0;units=1
    try:
        for epoch in range(12):
            observations=[];masks=[];actions=[];old_logprob=[];old_values=[];returns=[];advantages=[]
            for segment in contract['reset_segments']:
                state=env.reset(segment['segment_id'],seed=SEED+epoch)
                obs,legal,date,done=validate_state(state,contract,segment)
                require(not done,'RESET_MUST_START_NONTERMINATED_ACCOUNT_SEGMENT')
                rewards=[];values=[];ends=[]
                for step in range(RECIPE['max_steps_per_segment']):
                    tensor=torch.tensor(obs,dtype=torch.float32);mask=torch.tensor(legal,dtype=torch.bool)
                    output=model(tensor);distribution=torch.distributions.Categorical(logits=output[:5].masked_fill(~mask,-1e9))
                    action=distribution.sample();logprob=distribution.log_prob(action).detach()
                    value=float(output[5].detach()) if method=='ppo' else 0.
                    prior_nav=float(state['account_state']['nav']);prior_fee=float(state['account_state']['cumulative_fees'])
                    next_state=env.step(CAPS[int(action)])
                    next_obs,next_legal,next_date,done=validate_state(next_state,contract,segment,date)
                    reward=float(next_state['reward'])
                    next_account=next_state['account_state']
                    require(abs(reward-(next_account['nav']/prior_nav-1.))<=1e-10,'REWARD_MUST_BE_ACTUAL_NET_ACCOUNT_NAV_RETURN')
                    require(abs(next_account['cumulative_fees']-prior_fee-next_state['transaction_fee_usd'])<=1e-7,'ACTUAL_FEE_STATE_TRANSITION_REQUIRED')
                    rewards.append(reward);values.append(value);ends.append(done)
                    observations.append(obs);masks.append(legal);actions.append(int(action));old_logprob.append(float(logprob));old_values.append(value)
                    rollout_sha.update(digest(dict(date=date.isoformat(),observation=obs.tolist(),legal=legal.tolist(),action=int(action),reward=reward,
                        next_date=next_date.isoformat(),transaction_fee_usd=float(next_state['transaction_fee_usd']))).encode());steps+=1
                    obs,legal,date=next_obs,next_legal,next_date;state=next_state
                    if done:break
                require(done,'TRAINING_SEGMENT_MUST_TERMINATE_NO_IMPLICIT_TRUNCATION')
                if method=='ppo':
                    advantage,value_target=gae(rewards,values,ends);advantages.extend(advantage);returns.extend(value_target)
                else:returns.extend(discounted(rewards))
            x=torch.tensor(np.asarray(observations),dtype=torch.float32);mask=torch.tensor(np.asarray(masks),dtype=torch.bool)
            action=torch.tensor(actions,dtype=torch.long);old=torch.tensor(old_logprob,dtype=torch.float32)
            target=torch.tensor(returns,dtype=torch.float32)
            if method=='reinforce':
                started(on_fit_started,'PAST_DISCOUNTED_RETURN_BASELINE',method,identity);units+=1
                advantage=target-target.mean()
            else:advantage=torch.tensor(advantages,dtype=torch.float32)
            for update in range(4 if method=='ppo' else 1):
                output=model(x);distribution=torch.distributions.Categorical(logits=output[:,:5].masked_fill(~mask,-1e9));logprob=distribution.log_prob(action)
                if method=='ppo':
                    ratio=torch.exp(logprob-old);clipped=torch.clamp(ratio,.8,1.2)
                    policy_loss=-torch.minimum(ratio*advantage,clipped*advantage).mean()
                    value_loss=((output[:,5]-target)**2).mean();loss=policy_loss+.5*value_loss-.01*distribution.entropy().mean()
                    clip_fraction=float(((ratio<.8)|(ratio>1.2)).float().mean().detach())
                else:
                    policy_loss=-(logprob*advantage).mean();value_loss=torch.tensor(0.);loss=policy_loss;clip_fraction=0.
                require(bool(torch.isfinite(loss)),'NONFINITE_ACTUAL_ACCOUNT_RL_LOSS')
                optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),2.);optimizer.step()
                history.append(dict(epoch=epoch,update=update,policy_loss=float(policy_loss.detach()),value_loss=float(value_loss.detach()),clip_fraction=clip_fraction))
        weights={k:v.detach().cpu().numpy().copy() for k,v in model.state_dict().items()}
        return RLFit(method,contract,weights,dict(status='FITTED_ACCOUNT_POLICY',identity_sha256=identity,recipe=copy.deepcopy(RECIPE),
            source_contract=contract,training_steps=steps,rollout_sha256=rollout_sha.hexdigest(),fit_units=units,updates=history,
            stateful_rewards=True,training_reward_years=[2021,2022],primary_pto_directly_changed=False,strict_PIT_certified=False))
    except Exception as error:return dict(status='FAILED_NO_RETRY',method=method,identity_sha256=identity,fit_units=units,
        failure=dict(type=type(error).__name__,reason=str(error)),fitted=False,primary_pto_changed=False)
