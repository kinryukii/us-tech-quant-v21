"""Behavioral checks for causal split, fair sampling, capacity, and allocation."""
import itertools
import numpy as np
import pandas as pd
import pytest
import values as v
from train_values import counterfactual, quota, realized_weight, sample, validate_frame


def frame():
    dates=pd.to_datetime(['2024-12-27','2024-12-30','2024-12-31'])
    rows=[]
    for d in dates:
        for i in range(5):
            rows.append({'signal_date':d,'ticker':f'T{i}','label_end_date':d+pd.Timedelta(days=2),
                'label_available':True,'new_buy_eligible':True,'y_next_open':.05,
                **{f: .03 for f in v.FEATURES}})
    result=pd.DataFrame(rows);result['avg_dollar_volume_20d']=1e6
    return result


def test_maturity_purges_labels_crossing_boundary():
    f=frame()
    mature,_=sample(f,'2025-01-01')
    assert set(mature.signal_date)=={pd.Timestamp('2024-12-27')}
    assert mature.label_end_date.max()<pd.Timestamp('2025-01-01')
    f['signal_date']=pd.Timestamp('2026-01-01')
    with pytest.raises(RuntimeError,match='NON_PRE2026'):
        validate_frame(f)


def test_sampler_covers_every_date_and_ignores_input_order_and_targets():
    f=frame();a,audit=sample(f,'2026-01-01',8)
    g=f.sample(frac=1,random_state=99);g['y_next_open']=np.arange(len(g))*100
    b,_=sample(g,'2026-01-01',8)
    assert len(a)==8 and a.signal_date.nunique()==audit['selected_dates']==3
    pd.testing.assert_frame_equal(a[['signal_date','ticker']],b[['signal_date','ticker']])
    assert a.groupby('signal_date').size().max()-a.groupby('signal_date').size().min()<=1
    assert quota([1,7,20],8).tolist()==[1,4,3]
    with pytest.raises(RuntimeError,match='COVERAGE_BUDGET'):
        sample(f,'2026-01-01',2)


def test_capacity_limits_buys_but_allows_sell_and_only_training_clips_return():
    np.testing.assert_allclose(realized_weight(.025,.1,np.array([1e6,1e9])),[.035,.1])
    np.testing.assert_allclose(realized_weight(.1,0.,np.array([1e6,1e9])),[0.,0.])
    f=frame().iloc[:1].copy();f['y_next_open']=.9
    x,y,a=counterfactual(f,True);_,unclipped,_=counterfactual(f,False)
    assert x.shape==(15,106) and a['capacity_limited_buy_labels']>0
    actual=.01;expected=actual*.2-v.COST*actual-.5*v.RISK_AVERSION*.03**2*actual**2
    assert y[4]==pytest.approx(expected)
    assert unclipped[4]-y[4]==pytest.approx(actual*.7)


def test_joint_solver_matches_bruteforce_with_restrictions_and_reserved_budget():
    scores=np.random.default_rng(53).normal(size=(4,5))
    allowed=np.ones_like(scores,dtype=bool);allowed[1,2:]=False
    _,selected=v.allocate_joint_scores(scores,list('ABCD'),max_names=2,max_units=5,allowed=allowed)
    actual=sum(scores[i,a]-scores[i,0] for i,a in enumerate(selected))
    feasible=[actions for actions in itertools.product(range(5),repeat=4)
        if sum(a>0 for a in actions)<=2 and sum(actions)<=5 and all(allowed[i,a] for i,a in enumerate(actions))]
    best=max(sum(scores[i,a]-scores[i,0] for i,a in enumerate(actions)) for actions in feasible)
    assert actual==pytest.approx(best)
    weights,selected=v.allocate_joint_scores(scores,list('ABCD'),max_names=0,max_units=0)
    assert weights=={} and not selected.any()


def test_all_declared_models_are_fresh_and_no_random_early_stopping():
    for name in v.NAMES:
        model=v.estimator(name)
        assert not hasattr(model,'n_features_in_')
        if name in ['hgb','q10','q50','q90']:
            assert model.early_stopping is False
