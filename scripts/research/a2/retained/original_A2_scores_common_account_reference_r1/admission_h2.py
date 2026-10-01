"""Narrow read-only admission for one original-A2-score 2025H2 reference.

No model imports, fitting, inference, replay, network, or new 2026 inspection.
Existing attribution evidence supplies model/vintage identity. This checks only
the remaining H2 shared-input dependencies and records their exact sources.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
WS = OUT.parent
OLD = WS / 'a2_ensemble_attribution_20260928_r1'
BATCH = WS / 'a2_buy_sell_cash_multimodel_20260928'
ORIG = Path('D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1')
START, END, TERMINAL = pd.Timestamp('2025-07-01'), pd.Timestamp('2025-12-29'), pd.Timestamp('2025-12-31')
KEY = ['signal_date', 'ticker']
SOURCES = {}


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def bind(p):
    p = Path(p).resolve()
    actual = sha(p)
    assert str(p) not in SOURCES or SOURCES[str(p)] == actual
    SOURCES[str(p)] = actual
    return p


def read_json(p):
    return json.loads(bind(p).read_text(encoding='utf-8-sig'))


def read_h2(p, **kwargs):
    return pd.read_parquet(bind(p), filters=[('signal_date', '>=', START), ('signal_date', '<=', END)], **kwargs)


def csv(name, frame):
    assert name.startswith('ADMISSION_')
    frame.to_csv(OUT / name, index=False, encoding='utf-8-sig')


def main():
    OUT.mkdir(exist_ok=True)
    inherited = read_json(OLD / 'qualification_original_a2_oof_admissibility.json')
    prior_identity = read_json(OLD / 'qualification_original_a2_identity.json')
    read_json(OLD / 'qualification_independent_checks.json')
    frozen = read_json(BATCH / 'ensemble_2025_H2/cost_10/FROZEN_BEFORE_REPLAY.json')
    audit = read_json(WS / 'a2_latest_effective_joint_20260927/data/JOINT_DATA_AUDIT.json')
    features = audit['features']
    assert len(features) == 32
    panel_path = WS / 'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
    price_path = WS / 'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
    engine_path = BATCH / 'engine_v2.py'
    for path in [panel_path, price_path, engine_path]:
        bind(path)
        assert SOURCES[str(path.resolve())] == frozen['sources'][str(path.resolve())]
    oof_path = Path(inherited['original_oof_path'])
    oof = read_h2(oof_path, columns=KEY + ['a2_prediction', 'a2_rank', 'split'])
    assert SOURCES[str(oof_path.resolve())] == inherited['frozen_expected_sha256']
    assert oof.split.eq('FINAL').all() and inherited['2025_frozen_stage_record']['train_target_end_max'] == '2024-12-31'
    panel = read_h2(panel_path)
    for frame in [panel, oof]:
        assert not frame.duplicated(KEY).any() and len(frame) == 57819
    score_source_path = ORIG / 'A/score_rank_ledger.parquet'
    stock_features = read_h2(score_source_path, columns=KEY + ['close'] + features)
    artifact_manifest = pd.read_csv(bind(ORIG / 'audit/freeze_r1/frozen_artifact_hashes.csv'))
    original_feature_expected = artifact_manifest.loc[artifact_manifest.artifact_id.eq('a_scores'), 'sha256'].item()
    assert SOURCES[str(score_source_path.resolve())] == original_feature_expected
    compared = panel[KEY + ['close'] + features].merge(stock_features, on=KEY, how='outer', validate='one_to_one', indicator=True, suffixes=('_panel', '_original'))
    assert compared._merge.eq('both').all()
    feature_stats = []
    for col in ['close'] + features:
        left, right = compared[col + '_panel'], compared[col + '_original']
        stat = {'field': col, 'rows': len(compared), 'mismatch_count': int(left.ne(right).sum()),
                'max_abs_difference': float((left - right).abs().max()), 'finite_rows': int(np.isfinite(left).sum())}
        assert stat['mismatch_count'] == 0 and stat['finite_rows'] == len(compared)
        feature_stats.append(stat)
    csv('ADMISSION_H2_FEATURE_VALUE_CHECKS.csv', pd.DataFrame(feature_stats))
    score_join = panel[KEY].merge(oof, on=KEY, how='outer', validate='one_to_one', indicator=True)
    assert score_join._merge.eq('both').all() and np.isfinite(score_join.a2_prediction).all()
    sorted_scores = oof.sort_values(['signal_date', 'a2_prediction', 'ticker'], ascending=[True, False, True])
    assert sorted_scores.a2_rank.eq(sorted_scores.groupby('signal_date').cumcount() + 1).all()

    members_path = ORIG / 'universe/daily_eligible_universe_membership.parquet'
    members = read_h2(members_path)
    joined_members = panel[KEY + ['active_13f_quarter', 'cusip', 'moomoo_transport_code']].merge(
        members[KEY + ['active_13f_quarter', 'cusip', 'moomoo_transport_code']], on=KEY,
        how='outer', validate='one_to_one', indicator=True, suffixes=('_panel', '_original'))
    assert joined_members._merge.eq('both').all()
    for c in ['active_13f_quarter', 'cusip', 'moomoo_transport_code']:
        assert joined_members[c + '_panel'].eq(joined_members[c + '_original']).all()
    assert panel.new_buy_eligible.eq(True).all()
    active_path = ORIG / 'universe/daily_active_quarter_ledger.parquet'
    active = read_h2(active_path)
    quarter_path = ORIG / 'universe/quarterly_universe_manifest.parquet'
    quarters = pd.read_parquet(bind(quarter_path))
    wanted = ['2025Q1', '2025Q2', '2025Q3']
    quarters = quarters.loc[quarters.quarter.isin(wanted)].copy()
    evidence_path = ORIG / 'audit/manager_quarter_source_evidence.parquet'
    evidence = pd.read_parquet(bind(evidence_path))
    evidence = evidence.loc[evidence.quarter.isin(wanted)].copy()
    for original_path in [members_path, active_path, quarter_path]:
        expected_hash = artifact_manifest.loc[artifact_manifest.absolute_path.eq(str(original_path)), 'sha256'].item()
        assert SOURCES[str(original_path.resolve())] == expected_hash
    price = pd.read_parquet(price_path, filters=[('trade_date', '>=', pd.Timestamp('2025-01-01')), ('trade_date', '<=', TERMINAL)])
    assert not price.duplicated(['ticker', 'trade_date']).any()
    calendar = pd.DatetimeIndex(price.loc[price.ticker.eq('QQQ'), 'trade_date'].sort_values().unique())
    calendar_h2 = calendar[calendar >= START]
    assert len(calendar_h2) == 128 and calendar_h2[-1] == TERMINAL
    quarter_rows = []
    for row in quarters.itertuples(index=False):
        quarter_evidence = evidence.loc[evidence.quarter.eq(row.quarter)]
        latest_filing = pd.to_datetime(quarter_evidence.filing_timestamp).max()
        expected_effective = calendar[calendar.searchsorted(latest_filing, side='right') + 4]
        actual = pd.Timestamp(row.effective_date)
        observed = panel.loc[panel.asof_quarter.eq(row.quarter)]
        assert quarter_evidence.manager.nunique() == len(quarter_evidence) == row.institution_count == 24
        assert latest_filing == pd.Timestamp(row.latest_actual_filing_timestamp)
        assert expected_effective == actual
        assert observed.quarter_effective_date.eq(actual).all() and observed.latest_filing_date.eq(latest_filing).all()
        assert observed.signal_date.ge(actual).all() and observed.signal_date.gt(latest_filing).all()
        quarter_rows.append({'quarter': row.quarter, 'manager_count': 24, 'latest_public_filing_date': latest_filing,
            'fifth_subsequent_QQQ_session': expected_effective, 'saved_effective_date': actual,
            'H2_first_used': observed.signal_date.min(), 'H2_last_used': observed.signal_date.max(),
            'signal_days': observed.signal_date.nunique(), 'candidate_rows': len(observed),
            'filing_time_granularity': row.filing_timestamp_granularity,
            'historical_vendor_actual_arrival_proven': False})
    clock = panel.groupby('signal_date', as_index=False).agg(asof_quarter=('asof_quarter', 'first'), candidate_rows=('ticker', 'size'))
    clock = clock.merge(active[['signal_date', 'active_13f_quarter', 'quarter_effective_date', 'quarter_latest_filing_timestamp', 'active_quarter_count']], on='signal_date', how='outer', validate='one_to_one')
    assert len(clock) == 126 and clock.asof_quarter.eq(clock.active_13f_quarter).all() and clock.active_quarter_count.eq(1).all()
    assert np.array_equal(pd.DatetimeIndex(clock.signal_date), calendar_h2[:-2])
    csv('ADMISSION_H2_QUARTER_CLOCK.csv', pd.DataFrame(quarter_rows))
    csv('ADMISSION_H2_DAILY_CLOCK.csv', clock)
    csv('ADMISSION_H2_MANAGER_FILING_EVIDENCE.csv', evidence)

    day_price = panel[KEY + ['close']].merge(price[['ticker', 'trade_date', 'close']], left_on=KEY,
        right_on=['trade_date', 'ticker'], how='left', validate='one_to_one', suffixes=('_panel', '_shared_price'))
    assert day_price.close_panel.eq(day_price.close_shared_price).all()
    execution = panel[KEY].copy()
    execution['execution_date'] = calendar[calendar.searchsorted(execution.signal_date) + 1]
    execution = execution.merge(price[['ticker', 'trade_date', 'open', 'close']], left_on=['ticker', 'execution_date'],
        right_on=['ticker', 'trade_date'], how='left', validate='many_to_one')
    execution['next_open_available'] = np.isfinite(execution.open) & execution.open.gt(0)
    execution['next_close_available'] = np.isfinite(execution.close) & execution.close.gt(0)
    assert execution.next_open_available.all() and execution.next_close_available.all()
    daily_availability = execution.groupby('signal_date', as_index=False).agg(candidate_rows=('ticker', 'size'),
        next_open_available=('next_open_available', 'sum'), next_close_available=('next_close_available', 'sum'), execution_date=('execution_date', 'first'))
    csv('ADMISSION_H2_PRICE_AVAILABILITY.csv', daily_availability)
    # Availability of every potential carried holding is recorded; the new
    # path must still pass its own complete 128-day valuation check after replay.
    all_pairs = pd.MultiIndex.from_product([calendar_h2, sorted(panel.ticker.unique())], names=['trade_date', 'ticker']).to_frame(index=False)
    possible_holds = all_pairs.merge(price[['ticker', 'trade_date', 'open', 'close']], on=['ticker', 'trade_date'], how='left', validate='one_to_one')
    missing_possible_holds = possible_holds.loc[~(np.isfinite(possible_holds.open) & possible_holds.open.gt(0) & np.isfinite(possible_holds.close) & possible_holds.close.gt(0))]
    csv('ADMISSION_H2_POTENTIAL_HOLDING_PRICE_GAPS.csv', missing_possible_holds)
    old_price_receipt = read_json(WS / 'a2_strict_method_retrain_20260926/results/evaluation.json')
    assert old_price_receipt['price_sha256'] == SOURCES[str(price_path.resolve())]
    assert old_price_receipt['methods']['hgb']['old_nav_max_abs_difference'] == 0
    bind(WS / 'a2_strict_method_retrain_20260926/evaluate.py')
    for name in ['ensemble_equal', 'ensemble_consensus_risk', 'ensemble_stacked']:
        existing_days = pd.read_parquet(bind(BATCH / 'ensemble_2025_H2/cost_10' / name / 'daily.parquet'))
        assert np.array_equal(pd.DatetimeIndex(existing_days.date), calendar_h2)
        assert existing_days.certified_nav.notna().all() and existing_days.valuation_status.eq('certified').all()
    assert all(sha(path) == digest for path, digest in SOURCES.items())
    csv('ADMISSION_H2_SOURCE_HASHES.csv', pd.DataFrame([{'path': p, 'sha256': h, 'unchanged_after_check': True} for p, h in SOURCES.items()]))
    result = {
        'status': 'PASS_FOR_FIXED_2025H2_COMMON_ACCOUNT_RESEARCH_REPLAY',
        'scope': 'original_A2_scores_common_account_reference_r1; one frozen saved-score reference only',
        'signal_start': START, 'signal_end': END, 'valuation_end': TERMINAL,
        'signal_days': 126, 'required_complete_account_days': 128, 'candidate_rows': 57819, 'candidate_tickers': 560,
        'inherited_2025_oof_identity_receipt': str(OLD / 'qualification_original_a2_oof_admissibility.json'),
        'oof_hash_match': True, 'oof_only_2025_FINAL_stage_consumed': True,
        'oof_stage_training_target_end_max': inherited['2025_frozen_stage_record']['train_target_end_max'],
        'original_feature_source_frozen_hash_match': True, '32_feature_values_plus_close_exact_match_rows': len(compared),
        'same_daily_candidate_keys_cusip_transport_and_quarter': True,
        'all_candidates_new_buy_eligible': True, 'saved_oof_rank_matches_score_descending_ticker_ascending': True,
        'all_three_quarters_24_managers_public_before_use': True, 'all_three_effective_dates_equal_fifth_subsequent_QQQ_session': True,
        'shared_price_file_matches_existing_H2_replay_freeze': True,
        'signal_close_exact_shared_price_match': True, 'candidate_next_open_and_close_missing_rows': 0,
        'all_potential_H2_holding_pairs': len(possible_holds), 'potential_holding_price_gap_rows': len(missing_possible_holds),
        'existing_three_ensemble_128_day_windows_certified_in_shared_coordinate': True,
        'reference_path_valuation_qualification': 'REQUIRES_POST_REPLAY_ALL_128_DAYS_CERTIFIED; no dropping bad dates',
        'common_account_contract': {'initial_cash': 1000000, 'initial_positions': {}, 'one_way_cost_bps': 10,
            'buy_ADV_fraction': 0.01, 'max_positions': 20, 'max_active_target_sum': 0.95,
            'flat_account_target_per_selected_name': 0.0475, 'cash_inherits_residual': True,
            'holdings_and_order_semantics': 'same frozen holding-aware engine as the three existing H2 ensembles'},
        'out_of_scope_non_blockers_for_this_comparison': [
            '2026 GLW conflict and 2026 full-pool unknowns are not consumed in this H2 dependency check',
            'frozen saved scores are consumed; drifting prereg source is not imported, refit, or used for inference',
            'historical vendor actual arrival and shareholder total return remain unproven; claim limited to common retrospective research-index account'],
        'limitations': ['not original native A2 unchanged', 'not new blind test', 'not causal model-component attribution',
                   'not certified raw-share/settled-dividend shareholder total return', 'no 2026 conclusion'],
        'blockers': [],
        'checks': {'original_saved_2025_OOF_identity_unchanged': True,
            'all_32_feature_values_and_close_match_original_OOF_feature_source': True,
            'daily_candidate_keys_identity_quarter_all_match': True,
            'original_membership_active_clock_and_quarter_tables_match_frozen_hashes': True,
            'quarter_public_clock_and_fifth_subsequent_session_verified': True,
            'same_frozen_H2_price_file_and_calendar': True,
            'every_candidate_next_open_and_close_available': True,
            'existing_three_H2_ensembles_have_same_complete_certified_calendar': True,
            'sources_unchanged': True},
        'source_sha256': SOURCES,
        'delegated_final_ledger_validation': 'Main runner verifies every saved ledger hash and metadata for each existing H2 ensemble, then the new reference full path',
        'new_fits': 0, 'new_predictions': 0, 'new_replays': 0, 'network_requests': 0,
        'source_count': len(SOURCES), 'all_sources_unchanged': True,
        'evidence_outputs': {p.name: sha(p) for p in sorted(OUT.glob('ADMISSION_H2_*.csv'))},
    }
    (OUT / 'ADMISSION_H2.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
