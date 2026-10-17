"""Synthetic-only regression for the sole shared NAV statistics owner."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import stateful_frozen_six_path as six
CASES = [{'name': 'cross_month', 'dates': ['2025-01-29', '2025-01-30', '2025-01-31', '2025-02-03', '2025-02-04', '2025-02-05'], 'nav': [3000.0, 3030.0, 2940.0, 3000.0, 3060.0, 3045.0], 'expected_original': {'cumulative_return': 0.014999999999999902, 'MaxDD': -0.02970297029702973, 'existing_metric_sentinel': 17, 'annualized_geometric_return': 0.8688471150709629, 'annualized_volatility': 0.29961762476714693, 'Sharpe_rf0': 2.215276061420848, 'Sortino_MAR0': 3.40201022814763, 'Calmar': 29.251186207389058, 'drawdown_duration_max_sessions': 2, 'daily_positive_fraction': 0.5, 'calendar_month_return': {'2025-01': -0.020000000000000018, '2025-02': 0.03571428571428581}, 'rejected_execution_count': 1, 'execution_status_counts': {'ACCEPTED': 1, 'REJECTED': 1}, 'initial_cash_usd': 3000.0, 'initial_cash_session_included': True, 'inference': 'DESCRIPTIVE_ONLY_NO_WINNER_SELECTION', 'action_consumer_status_counts': {}}}, {'name': 'flat', 'dates': ['2025-01-29', '2025-01-30', '2025-01-31'], 'nav': [3000.0, 3000.0, 3000.0], 'expected_original': {'cumulative_return': 0.0, 'MaxDD': 0.0, 'existing_metric_sentinel': 17, 'annualized_geometric_return': 0.0, 'annualized_volatility': 0.0, 'Sharpe_rf0': None, 'Sortino_MAR0': None, 'Calmar': None, 'drawdown_duration_max_sessions': 0, 'daily_positive_fraction': 0.0, 'calendar_month_return': {'2025-01': 0.0}, 'rejected_execution_count': 1, 'execution_status_counts': {'ACCEPTED': 1, 'REJECTED': 1}, 'initial_cash_usd': 3000.0, 'initial_cash_session_included': True, 'inference': 'DESCRIPTIVE_ONLY_NO_WINNER_SELECTION', 'action_consumer_status_counts': {}}}, {'name': 'first_cost', 'dates': ['2025-01-29'], 'nav': [2998.5], 'expected_original': {'cumulative_return': -0.0004999999999999449, 'MaxDD': -0.0004999999999999449, 'existing_metric_sentinel': 17, 'annualized_geometric_return': -0.11841293290699573, 'annualized_volatility': None, 'Sharpe_rf0': None, 'Sortino_MAR0': -15.874507866387544, 'Calmar': -236.82586581401753, 'drawdown_duration_max_sessions': 1, 'daily_positive_fraction': 0.0, 'calendar_month_return': {'2025-01': -0.0004999999999999449}, 'rejected_execution_count': 1, 'execution_status_counts': {'ACCEPTED': 1, 'REJECTED': 1}, 'initial_cash_usd': 3000.0, 'initial_cash_session_included': True, 'inference': 'DESCRIPTIVE_ONLY_NO_WINNER_SELECTION', 'action_consumer_status_counts': {}}}, {'name': 'positive', 'dates': ['2025-01-29', '2025-01-30', '2025-01-31'], 'nav': [3000.0, 3030.0, 3090.0], 'expected_original': {'cumulative_return': 0.030000000000000027, 'MaxDD': 0.0, 'existing_metric_sentinel': 17, 'annualized_geometric_return': 10.976416067508014, 'annualized_volatility': 0.15717596474568227, 'Sharpe_rf0': 15.927157442196869, 'Sortino_MAR0': None, 'Calmar': None, 'drawdown_duration_max_sessions': 0, 'daily_positive_fraction': 0.6666666666666666, 'calendar_month_return': {'2025-01': 0.030000000000000027}, 'rejected_execution_count': 1, 'execution_status_counts': {'ACCEPTED': 1, 'REJECTED': 1}, 'initial_cash_usd': 3000.0, 'initial_cash_session_included': True, 'inference': 'DESCRIPTIVE_ONLY_NO_WINNER_SELECTION', 'action_consumer_status_counts': {}}}]

@pytest.mark.parametrize("case", CASES, ids=[x["name"] for x in CASES])
def test_existing_descriptive_results_exact_after_nav_extraction(case, monkeypatch):
    expected=case["expected_original"]
    monkeypatch.setattr(six,"_full_metrics",lambda c,f:{k:expected[k] for k in ["cumulative_return","MaxDD","existing_metric_sentinel"]})
    d=pd.DataFrame({"date":pd.to_datetime(case["dates"]),"path_id":"SYNTH","TOTAL_ECONOMIC_NAV":case["nav"]})
    actual=six.descriptive_metrics({"candidate_id":"SYNTH"},{"daily":d,"execution_results":pd.DataFrame({"status":["ACCEPTED","REJECTED"]})})
    assert actual==expected


def test_native_unit_initial_loss_is_not_lost_and_undefined_is_none():
    v=six.nav_descriptive_metrics(["2025-01-02"],[.9995],initial_cash=1.)
    assert v["cumulative_return"]==pytest.approx(-.0005)
    assert v["MaxDD"]==pytest.approx(-.0005)
    assert v["drawdown_duration_max_sessions"]==1
    assert v["annualized_volatility"] is None and v["Sharpe_rf0"] is None
    f=six.nav_descriptive_metrics(pd.bdate_range("2025-01-02",periods=3),[1.,1.,1.],initial_cash=1.)
    assert f["Sharpe_rf0"] is None and f["Sortino_MAR0"] is None and f["Calmar"] is None


def test_native_and_currency_units_share_metric_definition():
    dates=pd.bdate_range("2025-01-29",periods=5);nav=np.array([1.,1.05,.95,1.01,1.1])
    a=six.nav_descriptive_metrics(dates,nav,initial_cash=1.)
    b=six.nav_descriptive_metrics(dates,nav*3000.,initial_cash=3000.)
    assert a.keys()==b.keys()
    for k in a:
        if isinstance(a[k],dict):assert a[k]==pytest.approx(b[k])
        else:assert a[k]==pytest.approx(b[k])

@pytest.mark.parametrize("dates,nav,capital", [([],[],1.),(["2025-01-02"],[0.],1.),(["2025-01-02"],[1.],0.),(["2025-01-03","2025-01-02"],[1.,1.],1.),(["2025-01-02","2025-01-02"],[1.,1.],1.),(["2025-01-02"],[1.,1.],1.),(["2025-01-02"],[float("nan")],1.)])
def test_invalid_native_nav_is_rejected(dates,nav,capital):
    with pytest.raises(ValueError,match="DESCRIPTIVE_NAV_INPUT_INVALID"):
        six.nav_descriptive_metrics(dates,nav,initial_cash=capital)
