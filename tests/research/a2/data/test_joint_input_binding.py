"""Synthetic information-boundary tests for the input-only reuse adapter."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data.joint_input_binding import (
    FEATURES, TRAIN_COLUMNS, guard_parquet, sha256,
    load_training_inputs, existing_feature_functions,
)

def source_fixture(tmp_path):
    data=[]
    for ticker,end,available in [('A','2024-12-31',True),('B','2025-01-01',True),('C','2024-12-31',False)]:
        row={column:None for column in TRAIN_COLUMNS}
        row.update({feature:float(i+1)/100 for i,feature in enumerate(FEATURES)})
        row.update(signal_date=pd.Timestamp('2024-12-20'),ticker=ticker,
                   is_max_group=True,feature_available=True,all_features_finite=True,
                   feature_source='FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION',
                   execution_date=pd.Timestamp('2024-12-23'),label_end_date=pd.Timestamp(end),
                   label_mature_date=pd.Timestamp(end),label_available=available,y_open5=.01,
                   label_unsupported_common_event=False)
        data.append(row)
    panel=tmp_path/'panel.parquet';pd.DataFrame(data).to_parquet(panel,index=False)
    raw=tmp_path/'raw.parquet'
    pd.DataFrame({'ticker':['A','B','C'],'trade_date':[pd.Timestamp('2024-12-20')]*3}).to_parquet(raw,index=False)
    return {'sources':{
        'accepted_five_day_panel':{'path':str(panel),'sha256':sha256(panel)},
        'raw_prices':{'path':str(raw),'sha256':sha256(raw)}},
        'training_projection_columns':TRAIN_COLUMNS}

def test_trade_eligibility_is_not_future_label_selection_and_maturity_is_strict(tmp_path):
    binding=source_fixture(tmp_path)
    frame=load_training_inputs(binding,'2025-01-01').set_index('ticker')
    assert frame.trade_eligible.to_dict()=={'A':True,'B':True,'C':True}
    assert frame.fit_eligible.to_dict()=={'A':True,'B':False,'C':False}
    assert frame.loc['A','sample_weight_date_equal']==1

def test_forbidden_result_projection_rejected(tmp_path):
    binding=source_fixture(tmp_path)
    binding['training_projection_columns']=[*TRAIN_COLUMNS,'raw_a2_prediction']
    with pytest.raises(ValueError,match='Forbidden model/selector result column'):
        load_training_inputs(binding)

def test_mixed_test_date_container_rejected_before_projection(tmp_path):
    path=tmp_path/'mixed.parquet'
    pd.DataFrame({'trade_date':pd.to_datetime(['2025-12-31','2026-01-02']),
                  'ticker':['X','X']}).to_parquet(path,index=False)
    with pytest.raises(ValueError,match='Forbidden mixed/test input'):
        guard_parquet(path,sha256(path),['trade_date'])

def test_existing_pure_feature_function_is_future_append_invariant():
    source=Path(__file__).resolve().parents[4]/'scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py'
    build=existing_feature_functions(source)
    dates=pd.bdate_range('2024-01-02',periods=180)
    prices=pd.DataFrame({'ticker':'X','trade_date':dates,
                         'close':100+np.arange(180)*.2+np.sin(np.arange(180)),
                         'volume':1000+np.arange(180)*3})
    past=build(prices.iloc[:150].copy())[FEATURES].to_numpy(float)
    full=build(prices)[FEATURES].iloc[:150].to_numpy(float)
    np.testing.assert_array_equal(past,full)


def test_fixed_five_session_targets_reuse_share_windows_and_missing_endpoint_mask():
    from scripts.research.a2.data.joint_input_binding import (
        shareholder_open_targets,existing_event_functions,
    )
    source=Path(r'D:\us-tech-quant-results\A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1\LABEL_REPAIR_R1.py')
    apply,checks=existing_event_functions(source)
    assert len(checks())==5
    calendar=pd.bdate_range('2024-01-02',periods=9)
    keys=pd.DataFrame({'signal_date':[calendar[0],calendar[-1]],'ticker':['X','X']})
    raw=pd.DataFrame({'ticker':['X','X'],'trade_date':[calendar[1],calendar[6]],'open':[100.,55.]})
    events=[{'ticker':'X','event_date':str(calendar[3].date()),
             'status':'SHARE_ONLY_SUPPORTED','quantity_multiplier':2.}]
    labels=shareholder_open_targets(keys,raw,calendar,events,apply)
    assert labels.loc[0,'label_end_date']==calendar[6]
    assert labels.loc[0,'label_available']
    assert np.isclose(labels.loc[0,'y_open5'],.1)
    assert not labels.loc[1,'label_available']
    assert pd.isna(labels.loc[1,'y_open5'])
