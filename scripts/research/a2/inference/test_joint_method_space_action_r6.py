import numpy as np
import pytest
from scripts.research.a2.evaluation.joint_method_space_design_r6 import policy_space,budget_proof,BudgetCounter
from scripts.research.a2.inference.joint_method_space_action_r6 import *

def test_ex_ante_roles_and_budget():
    s=policy_space(); assert len(s['physical_paths'])==114; assert len(s['joint_roles'])==38
    proof=budget_proof(s,dict(decision_dates=list(range(752)),q_dates=list(range(143))),{'learned':2400})
    assert proof['policy_solves_upper']==19310
    b=BudgetCounter({});b.reserve('account_mechanism_paths',120)
    with pytest.raises(ValueError):b.reserve('account_mechanism_paths')
    with pytest.raises(ValueError):b.reserve('scientific_retry')

def test_cost_aware_action_has_opportunity_cost_and_asymmetry():
    assert replacement_utility('RPL1',.012,.010,friction=.003)<0
    assert replacement_utility('RPL0',.012,.010,friction=.003)>0
    x=np.array([.05,.05]);t=np.array([.054,.046])
    r=action_target('ASYMMETRIC_BAND',x,t,nav=3000,cost_bps=10,mu=np.ones(2),sigma=np.zeros(2),holding_age=np.ones(2)*10)
    np.testing.assert_allclose(r,[.05,.046])

def test_prefix_state_and_no_year_reset():
    m=StatefulActionMemory();assert m.observe(0,3000)==0;assert np.isclose(m.observe(1,2700),.1)
    m.record_realized_turnover(1,.3);assert m.cooldown_until==6
    with pytest.raises(ValueError):m.observe(3,2900)

def test_gross_and_uncertainty_keep_distinct_semantics():
    assert gross_value('VOL_TARGET',portfolio_vol=.3)==.5
    assert gross_value('DRAWDOWN',drawdown=.15,dd='DD1')==.5
    np.testing.assert_allclose(uncertainty_mu('Q10',[.1],q10=[-.2]),[-.2])
    with pytest.raises(ValueError):uncertainty_mu('LOWER_CONFIDENCE',[.1])

def test_mpc_cost_avoids_unrewarded_churn_and_counts_one_solve():
    events=[];evals=[]
    w=two_step_planner([.05,.05],[.1,0],[0,0],np.zeros((2,2)),cost_bps=10,on_solve=lambda k,n:events.append(n),on_evaluation=lambda k,n:evals.append(n))
    np.testing.assert_allclose(w,[.05,.05]);assert sum(events)==1;assert sum(evals)==9


def test_gross_reference_selection_uses_prior_forecast_and_complete_dates():
    from scripts.research.a2.training import joint_method_space_gross_r6 as g
    import pandas as pd
    rows=[]
    for i in range(21):
        rows.append(dict(signal_date='2023-02-01',ticker=f'T{i:02}',security_uid=f'UID{i}',asset_epoch=1,
            fit_cutoff='2023-01-01',execution_date='2023-02-02',label_end_date='2023-02-09',label_mature_date='2023-02-09',
            source_qualified=True,identity_qualified=True,genuine_chronological_oof=True,
            mu=float(i)/1000,sigma=.01,y_open5=.01 if i else 100.,realized_vol_20d=.01,downside_vol_20d=.008,avg_dollar_volume_20d=1e6))
    frame=pd.DataFrame(rows)
    out=g.aggregate_reference(frame,'2024-01-01')
    assert len(out)==1 and 'T00' not in out.iloc[0].reference_tickers
    frame.loc[20,'identity_qualified']=False
    with pytest.raises(ValueError,match='METADATA_UNQUALIFIED'):g.aggregate_reference(frame,'2024-01-01')
    frame.loc[20,'identity_qualified']=True
    frame.loc[20,'label_mature_date']='2024-01-01'
    with pytest.raises(ValueError,match='MATURE_TARGET_REQUIRED'):g.aggregate_reference(frame,'2024-01-01')
