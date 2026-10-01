import numpy as np
import pandas as pd
import pytest

import ensemble as e
import train_ensemble as train
import values as v


def frame():
    x=pd.DataFrame(np.ones((8,len(v.FEATURES)))*.02,columns=v.FEATURES)
    x['ticker']=[f'T{i}' for i in range(8)]
    x['signal_date']=pd.to_datetime(['2024-01-02']*4+['2024-12-30']*4)
    x['label_end_date']=x.signal_date+pd.Timedelta(days=2)
    x['label_available']=True;x['new_buy_eligible']=True;x['y_next_open']=.04
    x['avg_dollar_volume_20d']=1e6
    return x


def test_meta_matrix_contains_only_observables_and_exact_declared_columns():
    pred=np.arange(21).reshape(3,7)/100
    actual=e.meta_feature_matrix(pred,[0,1,-1],[0,.05,.1],[.95,.5,.05],[0,10,40],[0,.05,.1])
    assert actual.shape==(3,len(e.META_FEATURES)) and np.isfinite(actual).all()
    assert not any('return' in name or 'label' in name or 'target' in name for name in e.META_FEATURES)
    assert actual[0,e.META_FEATURES.index('mlp_preference')]==pytest.approx(.05)
    assert actual[0,e.META_FEATURES.index('negative_squared_action_preference_distance')]==pytest.approx(-.05**2)


def test_oof_purges_cross_year_labels_and_refuses_test_year():
    picked,audit=train.select_oof(frame(),2024)
    assert len(picked)==4 and picked.label_end_date.lt('2025-01-01').all()
    assert audit['all_mature_dates_present']
    with pytest.raises(ValueError,match='2024_OR_2025'):
        train.select_oof(frame(),2026)


def test_counterfactual_state_action_order_matches_reward_order_and_ignores_outcome():
    x=frame().iloc[:2].copy()
    expanded=train.expand_observable_state(x)
    changed=x.copy();changed['y_next_open']=[9.,-9.]
    for a,b in zip(expanded,train.expand_observable_state(changed)):
        np.testing.assert_array_equal(a,b)
    for state_index,state in enumerate(v.STATE_GRID):
        for action_index,action in enumerate(v.ACTIONS):
            start=(state_index*5+action_index)*len(x)
            assert np.all(expanded[1][start:start+len(x)]==state[0])
            assert np.all(expanded[4][start:start+len(x)]==action)


def test_oof_rejects_future_trained_predictor():
    class Bad:
        stage='validation';boundary='2025-01-01'
    with pytest.raises(RuntimeError,match='NOT_STRICTLY_PRIOR_YEAR'):
        train.build_oof(frame().iloc[:2],2024,Bad())
    with pytest.raises(RuntimeError,match='TIME_LEAKAGE'):
        e.require_preboundary({'date':'2024-01-01'},'2024-01-01',['date'])


def test_score_actions_preserves_stock_then_action_order():
    class Base:
        def matrix(self,x,current,cash,age,action):
            return np.column_stack([x[:,0],current,action])
    class Model:
        def predict(self,x):
            return x[:,0]+x[:,1]+x[:,2]
    obj=object.__new__(e.StackedPolicy);obj.base=Base();obj.model=Model()
    x=frame().iloc[:2];current=np.array([0.,.05])
    scores=obj.score_actions(x,current,.9,np.zeros(2))
    np.testing.assert_allclose(scores,x[v.FEATURES[0]].to_numpy()[:,None]+current[:,None]+v.ACTIONS)


def test_fitted_stacking_artifact_integration():
    if not (e.OUT/'FIT_RECEIPT.json').exists():
        pytest.skip('meta training not complete yet')
    for stage in e.STAGES:
        actor=e.StackedPolicy(stage)
        day=frame().iloc[:2]
        scores=actor.score_actions(day,np.array([0.,.05]),.9,np.array([0.,10.]))
        assert scores.shape==(2,5) and np.isfinite(scores).all()
