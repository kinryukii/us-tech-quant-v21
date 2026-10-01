import numpy as np
import pandas as pd
from comparison_analysis import factor_decomposition,hac_mean,comparison
from common import RISKS,OPTIMIZERS

def test_balanced_additive_and_interaction_recovery():
    rows=[]
    for i,f in enumerate(['a','b','c']):
        for j,r in enumerate(RISKS):
            for k,o in enumerate(OPTIMIZERS):rows.append(dict(forecast_id=f,risk=r,optimizer=o,net_return=.1+i*.01+j*.002+k*.005))
    frame=pd.DataFrame(rows);result=factor_decomposition(frame)
    assert np.abs(result[['forecast_risk_interaction','forecast_optimizer_interaction','risk_optimizer_interaction','three_way_interaction']].to_numpy()).max()<1e-12
    frame.loc[(frame.forecast_id=='a')&(frame.risk=='diag'),'net_return']+=.03
    result=factor_decomposition(frame)
    assert result.forecast_risk_interaction.abs().max()>.01
    assert result.three_way_interaction.abs().max()<1e-12

def test_incomplete_factorial_does_not_impute_failed_route():
    import pytest
    with pytest.raises(ValueError,match='INCOMPLETE'):
        factor_decomposition(pd.DataFrame([dict(forecast_id='a',risk='diag',optimizer='mv',net_return=0)]))

def test_shared_date_is_statistical_unit():
    result=hac_mean(np.zeros(10))
    assert result['days']==10 and result['hac_se_lag5']==0 and result['mean_daily_log_difference']==0

def test_invalid_labels_cannot_masquerade_as_complete_factor_grid():
    import pytest
    rows=[dict(forecast_id='a',risk=('unregistered' if r=='diag' else r),optimizer=o,net_return=0.)
          for r in RISKS for o in OPTIMIZERS]
    with pytest.raises(ValueError,match='PRESPECIFIED_CARTESIAN'):
        factor_decomposition(pd.DataFrame(rows))

def test_failed_paired_cells_are_counted_and_zero_matches_retained():
    left=pd.DataFrame([dict(key='a',strategy_id='la',net_return=.3),dict(key='b',strategy_id='lb',net_return=.4)])
    right=pd.DataFrame([dict(key='a',strategy_id='ra',net_return=.1)])
    daily=pd.DataFrame({'la':[np.nan,.03,.02,.04],'lb':[np.nan,.08,.06,.04],'ra':[np.nan,.01,np.nan,.02]},
                       index=pd.date_range('2025-01-01',periods=4))
    result=comparison(left,right,daily,['key'],expected_cells=3,left='learned',right='baseline',comparison='risk')
    assert (result['left'],result['right'],result['comparison'])==('learned','baseline','risk')
    assert (result['matched_cells'],result['left_only_success_cells'],result['both_missing_cells'])==(1,1,1)
    assert result['right_only_success_cells']==0 and not result['complete_matched_grid']
    assert result['common_valid_return_days']==2 and result['omitted_return_days']==2
    assert np.isclose(result['delta_net_return'],.2) and np.isclose(result['mean_daily_log_difference'],.02)
    empty=comparison(left.iloc[:0],right.iloc[:0],daily,['key'],expected_cells=3)
    assert empty['matched_cells']==0 and empty['both_missing_cells']==3
    assert empty['days']==0 and empty['delta_net_return'] is None and empty['hac_se_lag5'] is None

def test_duplicated_factor_paths_do_not_multiply_hac_sample_size():
    dates=pd.date_range('2025-01-01',periods=10)
    series=np.arange(10)*.001
    daily=pd.DataFrame({'la':series,'lb':series,'ra':np.zeros(10),'rb':np.zeros(10)},index=dates)
    left=pd.DataFrame([dict(key='a',strategy_id='la'),dict(key='b',strategy_id='lb')])
    right=pd.DataFrame([dict(key='a',strategy_id='ra'),dict(key='b',strategy_id='rb')])
    one=comparison(left.iloc[:1],right.iloc[:1],daily,['key'],expected_cells=1)
    two=comparison(left,right,daily,['key'],expected_cells=2)
    assert one['days']==two['days']==10
    assert one['hac_se_lag5']==two['hac_se_lag5'] and one['mean_daily_log_difference']==two['mean_daily_log_difference']
