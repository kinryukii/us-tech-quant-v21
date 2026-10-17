"""Generated account transitions only; no real sources, rewards, or data I/O."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import consensus_auxiliary as owner


def feature_frame():
    rng=np.random.default_rng(7);f=pd.DataFrame(rng.normal(size=(80,32)),columns=owner.FEATURES)
    f['signal_date']=pd.bdate_range('2021-01-04',periods=80);f['ticker']='SYN'
    f['feature_available']=True;f['feature_source']='FROZEN_RAW_A2_TRAINING_MATRIX_32'
    return f


def test_five_native_diagnostics_share_train_only_scaler_and_six_fit_callbacks():
    frame=feature_frame();calls=[]
    fitted=owner.fit_auxiliary(frame,cutoff='2022-01-01',source_contract=dict(feature_source_qualified=True,
        feature_order=list(owner.FEATURES),source_id='SYNTHETIC'),on_fit_started=calls.append)
    assert set(fitted.models)=={'kmeans5','gmm5','isolation_forest100','pca5','fa5'}
    assert len(calls)==6 and all(c['fit_units']==1 for c in calls)
    np.testing.assert_allclose(fitted.scaler.mean_,frame[list(owner.FEATURES)].mean())
    out=fitted.diagnostics(frame.assign(**{owner.FEATURES[0]:frame[owner.FEATURES[0]]+3}))
    assert out.filter(like='gmm_probability_').shape==(80,5)
    assert out.filter(like='pca5_component_').shape==(80,5) and 'anomaly_score' in out
    assert fitted.models['kmeans5'].n_init==10 and fitted.models['isolation_forest100'].n_estimators==100
    assert not fitted.receipt['primary_pto_changed']


def test_unqualified_auxiliary_is_not_testable_and_future_keys_precede_fit():
    frame=feature_frame()
    assert owner.fit_auxiliary(frame,cutoff='2022-01-01',source_contract={},on_fit_started=None)['status']=='NOT_TESTABLE'
    frame.loc[0,'signal_date']=pd.Timestamp('2026-01-02')
    with pytest.raises(ValueError,match='PAST_UNIQUE'):
        owner.fit_auxiliary(frame,cutoff='2022-01-01',source_contract=dict(feature_source_qualified=True,
            feature_order=list(owner.FEATURES)),on_fit_started=lambda *a:pytest.fail('future row fitted'))


class SyntheticCashEnvironment:
    """In-memory generated ledger; no real price or label source is touched."""
    def __init__(self):
        self.source_contract=dict(causal_observations=True,source_qualified=True,stateful_cash_holdings_fee_account=True,
            actual_fees_in_reward=True,episode_segments_frozen=True,training_reward_years=[2021,2022],
            activity_caps=list(owner.CAPS),observation_scaling=owner.RECIPE['observation_scaling'],
            reward_definition=owner.RECIPE['reward_definition'],environment_source_sha256='a'*64,
            account_owner='scripts.research.a2.evaluation.consensus_cash_account.run_cash_account',account_owner_sha256='b'*64,
            dependency_paths=[str(owner.TORCH_SNAPSHOT)],observation_fields=list(owner.ACCOUNT_FIELDS),reset_segments=[
                dict(segment_id='2021_fixture',start='2021-01-04',end_exclusive='2021-01-08'),
                dict(segment_id='2022_fixture',start='2022-01-03',end_exclusive='2022-01-07')],source_id='SYNTHETIC_ONLY')
        self.resets=[];self.steps=0

    def state(self,terminated=False):
        nav=self.cash+self.units*self.price
        return dict(observation=np.array([self.cash/nav,0.,self.units*self.price/nav,float(self.units>0)/20]),
            legal_actions=np.array([True]*5),as_of=self.date,terminated=terminated,source_qualified=True,
            account_state=dict(settled_cash=self.cash,unsettled_receivable=0.,corporate_receivable=0.,nav=nav,
                position_units=[self.units],position_market_values=[self.units*self.price],cumulative_fees=self.fees,nav_identity_error=0.))

    def reset(self,segment_id,seed):
        self.resets.append(segment_id);segment=next(s for s in self.source_contract['reset_segments'] if s['segment_id']==segment_id)
        self.date=pd.Timestamp(segment['start']);self.cash=3000.;self.units=0.;self.price=100.;self.fees=0.;self.day=0
        return self.state()

    def step(self,cap):
        before=self.cash+self.units*self.price;delta=cap*before-self.units*self.price
        fee=abs(delta)*.001+(.5 if abs(delta)>1e-9 else 0.)
        self.cash-=delta+fee;self.units+=delta/self.price;self.fees+=fee
        self.day+=1;self.date+=pd.Timedelta(days=1);self.price*=1.01 if self.day%2 else .985;self.steps+=1
        out=self.state(self.day==3);out.update(reward=out['account_state']['nav']/before-1.,reward_mature_at=self.date,transaction_fee_usd=fee)
        return out


@pytest.mark.parametrize('method',['reinforce','ppo'])
def test_real_policy_gradient_uses_stateful_fee_rewards_and_frozen_train_segments(method):
    env=SyntheticCashEnvironment();calls=[];fit=owner.fit_account_rl(method,env,on_fit_started=calls.append)
    assert isinstance(fit,owner.RLFit),fit
    assert env.steps==72 and len(env.resets)==24 and set(env.resets)=={'2021_fixture','2022_fixture'}
    assert fit.receipt['training_steps']==72 and fit.receipt['training_reward_years']==[2021,2022]
    assert fit.receipt['fit_units']==(13 if method=='reinforce' else 1)
    assert len(calls)==fit.receipt['fit_units']
    assert len(fit.receipt['updates'])==(12 if method=='reinforce' else 48)
    assert set(x['epoch'] for x in fit.receipt['updates'])==set(range(12))
    assert fit.activity_cap(np.array([1.,0.,0.,0.]),np.array([False,False,True,False,False]))==.5
    torch=owner._torch(env.source_contract['dependency_paths']);torch.manual_seed(owner.SEED);initial=owner.network(torch,method,4).state_dict()
    assert any(not np.allclose(v.numpy(),fit.weights[k]) for k,v in initial.items())
    assert fit.receipt['stateful_rewards'] and not fit.receipt['primary_pto_directly_changed']


def test_missing_or_2023_reward_environment_has_no_model_or_fit_start():
    assert owner.fit_account_rl('ppo',None,on_fit_started=None)['status']=='NOT_TESTABLE'
    env=SyntheticCashEnvironment();env.source_contract['reset_segments'][1]['end_exclusive']='2023-01-02'
    assert owner.fit_account_rl('ppo',env,on_fit_started=lambda *a:pytest.fail('unsafe environment fit'))['status']=='NOT_TESTABLE'
    assert env.steps==0


def test_static_label_reward_cannot_be_named_reinforcement_learning():
    env=SyntheticCashEnvironment();step=env.step
    def static(cap):out=step(cap);out['reward']=1.;return out
    env.step=static
    result=owner.fit_account_rl('reinforce',env,on_fit_started=lambda event:None)
    assert result['status']=='FAILED_NO_RETRY' and 'NET_ACCOUNT_NAV_RETURN' in result['failure']['reason']


def test_fee_receipt_must_match_actual_state_change():
    env=SyntheticCashEnvironment();step=env.step
    def wrong(cap):out=step(cap);out['transaction_fee_usd']+=1;return out
    env.step=wrong;result=owner.fit_account_rl('ppo',env,on_fit_started=lambda event:None)
    assert result['status']=='FAILED_NO_RETRY' and 'ACTUAL_FEE_STATE_TRANSITION' in result['failure']['reason']


def test_shared_budget_callback_denies_before_rl_reset_or_optimizer_training():
    env=SyntheticCashEnvironment()
    def deny(event):raise RuntimeError('GLOBAL_10000_FIT_BUDGET_EXHAUSTED')
    with pytest.raises(RuntimeError,match='GLOBAL_10000'):owner.fit_account_rl('ppo',env,on_fit_started=deny)
    assert env.steps==0 and env.resets==[]


def test_reward_clock_cannot_cross_pre_registered_training_segment():
    env=SyntheticCashEnvironment();step=env.step
    def future(cap):out=step(cap);out['reward_mature_at']=pd.Timestamp('2023-01-02');return out
    env.step=future;result=owner.fit_account_rl('ppo',env,on_fit_started=lambda event:None)
    assert result['status']=='FAILED_NO_RETRY' and 'REWARD_NOT_MATURE' in result['failure']['reason']


def test_gae_and_discounted_returns_are_actual_temporal_recursions():
    advantage,returns=owner.gae([1.,2.],[.2,.3],[False,True],gamma=.99,lam=.95)
    np.testing.assert_allclose(advantage,[1.+.99*.3-.2+.99*.95*(2.-.3),2.-.3])
    np.testing.assert_allclose(returns,advantage+[.2,.3])
    np.testing.assert_allclose(owner.discounted([1.,2.]),[2.98,2.])


def test_callback_reusing_state_and_observation_objects_preserves_rollout_and_fee_validation():
    class ReusedState(SyntheticCashEnvironment):
        def __init__(self):
            super().__init__();self.cached=None
        def reuse(self,state):
            if self.cached is None:self.cached=state;return state
            observation=self.cached['observation'];account=self.cached['account_state']
            observation[:]=state['observation'];account.clear();account.update(state['account_state'])
            self.cached.clear();self.cached.update(state);self.cached['observation']=observation;self.cached['account_state']=account
            return self.cached
        def reset(self,*args,**kwargs):return self.reuse(super().reset(*args,**kwargs))
        def step(self,cap):return self.reuse(super().step(cap))
    ordinary=owner.fit_account_rl('ppo',SyntheticCashEnvironment(),on_fit_started=lambda event:None)
    reused=owner.fit_account_rl('ppo',ReusedState(),on_fit_started=lambda event:None)
    assert isinstance(reused,owner.RLFit),reused
    assert ordinary.receipt['rollout_sha256']==reused.receipt['rollout_sha256']
    for key in ordinary.weights:np.testing.assert_array_equal(ordinary.weights[key],reused.weights[key])


def test_missing_dependency_binding_or_malformed_segments_are_not_testable_before_fit():
    env=SyntheticCashEnvironment();env.source_contract.pop('dependency_paths')
    assert owner.fit_account_rl('ppo',env,on_fit_started=lambda event:pytest.fail('missing binding fitted'))['status']=='NOT_TESTABLE'
    env=SyntheticCashEnvironment();env.source_contract['reset_segments']=[dict(segment_id='incomplete')]
    assert owner.fit_account_rl('ppo',env,on_fit_started=lambda event:pytest.fail('incomplete segment fitted'))['status']=='NOT_TESTABLE'
    assert env.steps==0 and env.resets==[]
