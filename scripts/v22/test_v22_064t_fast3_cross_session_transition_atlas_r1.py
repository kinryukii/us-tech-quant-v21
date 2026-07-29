from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_064t_fast3_cross_session_transition_atlas_r1 as mod


def valid_064():
    return {
        'final_status':'PASS',
        'final_decision':mod.EXPECTED_V22_064_DECISION,
        'next_stage':mod.EXPECTED_NEXT_STAGE,
        'historical_candidate_architecture_count':1,
        'historically_rejected_architecture_count':5,
        'inconclusive_architecture_count':1,
        'forward_replication_pending':True,
        'forward_replication_passed':False,
        'multi_session_state_machine_allowed':False,
        'premarket_forward_chain_modified':False,
        'market_data_read':False,
        'strategy_backtest_executed':False,
        'signal_regeneration_executed':False,
        'parameter_sweep_executed':False,
        'threshold_optimization_executed':False,
        'canonical_files_modified':False,
        'raw_files_modified':False,
        'new_market_data_cache_created':False,
        'broker_action_allowed':False,
        'paper_trading_allowed':False,
        'official_adoption_allowed':False,
    }


def synthetic_day(base=100.0):
    ranges = [
        pd.date_range('2026-01-05 04:00', periods=330, freq='min', tz='America/New_York'),
        pd.date_range('2026-01-05 09:30', periods=390, freq='min', tz='America/New_York'),
        pd.date_range('2026-01-05 16:00', periods=240, freq='min', tz='America/New_York'),
        pd.date_range('2026-01-05 20:00', periods=240, freq='min', tz='America/New_York'),
        pd.date_range('2026-01-06 00:00', periods=240, freq='min', tz='America/New_York'),
    ]
    ts = ranges[0]
    for current in ranges[1:]:
        ts = ts.append(current)
    price = base + np.arange(len(ts))*0.001
    return pd.DataFrame({'timestamp_utc':ts.tz_convert('UTC'),'open':price,'high':price+0.02,'low':price-0.02,'close':price,'volume':100.0})


def test_validate_064():
    mod.validate_v22_064(valid_064())


def test_validate_064_rejects():
    summary = valid_064(); summary['multi_session_state_machine_allowed'] = True
    with pytest.raises(mod.AtlasError):
        mod.validate_v22_064(summary)


def test_study_period():
    assert mod.study_period(2020) == '2018-2022_DEVELOPMENT'
    assert mod.study_period(2024) == '2023-2024_VALIDATION'
    assert mod.study_period(2026) == '2025-2026_YTD_CONFIRMATION'


def test_symbol_month_path():
    path = mod.Path('x')/'symbol=US.QQQ'/'year=2026'/'month=7'/'part.parquet'
    assert mod.symbol_month_from_path(path) == ('QQQ','2026','07')


def test_split_snap():
    assert mod.snap_split_factor(10.0)[0] == pytest.approx(10.0)
    assert mod.snap_split_factor(1.37) is None


def test_normalize():
    normalized, recognized, unresolved = mod.normalize_scale(synthetic_day())
    assert 'local_date' in normalized
    assert recognized.empty and unresolved.empty


def test_standard_and_overnight_sessions():
    normalized, _, unresolved = mod.normalize_scale(synthetic_day())
    rth = mod.build_standard_session(normalized, unresolved, 'QQQ', 'RTH', 9*60+30, 15*60+59)
    overnight = mod.build_overnight_session(normalized, unresolved, 'QQQ')
    assert len(rth) == 1
    assert len(overnight) == 1
    assert overnight.iloc[0]['session_date'] == '2026-01-06'


def test_all_sessions():
    normalized, _, unresolved = mod.normalize_scale(synthetic_day())
    frame = mod.build_sessions_for_symbol(normalized, unresolved, 'QQQ')
    assert set(frame['session']) == {'RTH','AFTER_HOURS','OVERNIGHT','PREMARKET'}


def test_pair_transition():
    normalized, _, unresolved = mod.normalize_scale(synthetic_day())
    sessions = mod.build_sessions_for_symbol(normalized, unresolved, 'QQQ')
    paired = mod.pair_transition_for_symbol(sessions, 'QQQ', 'RTH', 'AFTER_HOURS', 'RTH_TO_AFTER_HOURS')
    assert len(paired) == 1


def test_combine_pairs():
    base = pd.DataFrame({
        'transition':['A','A'],'symbol':['QQQ','SOXX'],'source_session':['RTH','RTH'],
        'target_session':['AFTER_HOURS','AFTER_HOURS'],'source_session_date':['2026-01-05']*2,
        'target_session_date':['2026-01-05']*2,'target_calendar_year':[2026]*2,
        'study_period':['2025-2026_YTD_CONFIRMATION']*2,
        'source_start_timestamp_utc':pd.to_datetime(['2026-01-05 14:30Z']*2),
        'source_end_timestamp_utc':pd.to_datetime(['2026-01-05 20:59Z']*2),
        'target_start_timestamp_utc':pd.to_datetime(['2026-01-05 21:00Z']*2),
        'target_end_timestamp_utc':pd.to_datetime(['2026-01-06 00:59Z']*2),
        'transition_gap_hours':[1/60]*2,'source_return':[0.01,0.02],'target_return':[0.005,0.006],
    })
    combined = mod.combine_symbol_pairs(base)
    assert combined.iloc[0]['source_consensus'] == 'UP'
    assert bool(combined.iloc[0]['directional_persistence'])


def test_correlation_and_bootstrap():
    assert mod.pearson_correlation(pd.Series([1,2,3]), pd.Series([2,4,6])) == pytest.approx(1.0)
    low, high = mod.bootstrap_difference(np.array([0.02,0.03,0.04]), np.array([-0.02,-0.03,-0.04]), 1)
    assert low > 0 and high > 0


def atlas_frame(ci_positive=True):
    rows=[]
    for _,_,transition in mod.TRANSITIONS:
        for period in ('2023-2024_VALIDATION','2025-2026_YTD_CONFIRMATION'):
            rows.append({
                'transition':transition,'study_period':period,'sample_count':200,
                'source_up_count':80,'source_down_count':70,
                'qqq_source_target_correlation':0.1,'soxx_source_target_correlation':0.1,
                'qqq_up_minus_down_target_mean':0.01,
                'qqq_difference_ci_low':0.001 if ci_positive else -0.001,
                'qqq_difference_ci_high':0.02,
                'soxx_up_minus_down_target_mean':0.02,
                'soxx_difference_ci_low':0.001 if ci_positive else -0.001,
                'soxx_difference_ci_high':0.03,
            })
    return pd.DataFrame(rows)


def test_qualification():
    assert mod.build_qualification(atlas_frame())['diagnostic_transition_for_frozen_followup'].all()
    assert not mod.build_qualification(atlas_frame(False))['diagnostic_transition_for_frozen_followup'].any()


def test_choose_decision():
    q = pd.DataFrame({'transition':['A','B'],'diagnostic_transition_for_frozen_followup':[True,False]})
    decision, survivors, next_stage = mod.choose_decision(q)
    assert 'STRUCTURE_DETECTED' in decision and survivors == ['A'] and '064T1' in next_stage
    q['diagnostic_transition_for_frozen_followup'] = False
    decision, survivors, next_stage = mod.choose_decision(q)
    assert decision == 'NO_CROSS_SESSION_TRANSITION_STRUCTURE_DETECTED'
    assert survivors == [] and 'WAIT_FOR_V22.062PR' in next_stage


def test_parse_args_and_constants():
    args = mod.parse_args(['--execute'])
    assert 'V22.064_FAST3' in args.v22_064_summary
    assert mod.BOOTSTRAP_REPETITIONS == 1000
    assert len(mod.TRANSITIONS) == 4
