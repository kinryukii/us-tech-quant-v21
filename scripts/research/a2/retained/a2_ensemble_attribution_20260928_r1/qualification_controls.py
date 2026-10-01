"""Read-only qualification inventory; no fit, predict, download, or replay.

Reconstruct the already-frozen candidate qualification exactly, retain every
unknown row and original reason, and attach separate unresolved evidence flags.
All outputs are confined to this new revision directory.
"""
from pathlib import Path
import hashlib
import json
import shutil
import pandas as pd
import numpy as np

OUT = Path(__file__).resolve().parent
WS = OUT.parent
BATCH = WS / 'a2_buy_sell_cash_multimodel_20260928'
QUAL = WS / 'a2_qualification_holdings_v1_20260927'
ORIGINAL = Path('D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1')
IDENTITY = WS / 'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1/A2_IDENTITY_AUDIT.json'
GATE = WS / 'a2_strict_method_retrain_20260926/test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet'
SOURCE_HASHES = {}
OUTPUTS = {}
KEY = ['signal_date', 'ticker']


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def bind(path):
    path = Path(path).resolve()
    digest = sha(path)
    assert str(path) not in SOURCE_HASHES or SOURCE_HASHES[str(path)] == digest
    SOURCE_HASHES[str(path)] = digest
    return path


def pq(path, **kwargs):
    return pd.read_parquet(bind(path), **kwargs)


def js(path):
    return json.loads(bind(path).read_text(encoding='utf-8-sig'))


def save_json(name, obj):
    path = OUT / name
    assert name.startswith('qualification_')
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')
    OUTPUTS[name] = {'sha256': sha(path)}


def save_table(name, frame, csv=True):
    assert name.startswith('qualification_')
    path = OUT / (name + '.parquet')
    frame.to_parquet(path, index=False)
    OUTPUTS[path.name] = {'sha256': sha(path), 'rows': len(frame)}
    if csv:
        path = OUT / (name + '.csv')
        frame.to_csv(path, index=False, encoding='utf-8-sig')
        OUTPUTS[path.name] = {'sha256': sha(path), 'rows': len(frame)}


def snapshot(src, name):
    src = bind(src)
    path = OUT / name
    assert name.startswith('qualification_')
    shutil.copyfile(src, path)
    assert sha(path) == SOURCE_HASHES[str(src)]
    OUTPUTS[name] = {'sha256': sha(path), 'exact_byte_copy_of': str(src)}


def with_reference(df, path):
    df = df.copy()
    df['source_row_ordinal_0_based'] = np.arange(len(df))
    df['source_path'] = str(Path(path).resolve())
    df['source_sha256'] = SOURCE_HASHES[str(Path(path).resolve())]
    return df


def main():
    OUT.mkdir(exist_ok=True)
    source_receipt = js(QUAL / 'data/DATA_RECEIPT.json')
    gate = with_reference(pq(GATE), GATE)
    snapshot(GATE, 'qualification_original_candidate_gate.parquet')
    delta_path = QUAL / 'data/candidate_qualification_changes.parquet'
    delta = pq(delta_path)
    assert not gate.duplicated(KEY).any() and not delta.duplicated(KEY).any()
    delta = delta[KEY + ['new_qualified', 'qualification_change', 'qualification_reason', 'effective_cusip', 'unresolved_event_keys']]
    full = gate.merge(delta, on=KEY, how='left', validate='one_to_one')
    original_pass = full.final_input_gate.str.startswith('INPUT_VERIFIED')
    full['current_frozen_qualified'] = full.new_qualified.where(full.new_qualified.notna(), original_pass).astype(bool)
    full['current_frozen_proven_ineligible'] = full.final_input_gate.str.startswith('PROVEN')
    full['current_frozen_unknown'] = ~full.current_frozen_qualified & ~full.current_frozen_proven_ineligible
    full['current_frozen_status'] = np.select(
        [full.current_frozen_qualified, full.current_frozen_proven_ineligible],
        ['QUALIFIED', 'PROVEN_INELIGIBLE'], default='UNKNOWN')
    full['current_reason'] = full.qualification_reason.fillna(full.final_input_gate)
    full['qualification_delta_path'] = str(delta_path.resolve())
    full['qualification_delta_sha256'] = SOURCE_HASHES[str(delta_path.resolve())]
    # Preserve the pre-existing gate; conflict disclosure is an additional column.
    full['glw_known_conflict_outside_frozen_gate'] = full.ticker.eq('GLW') & full.signal_date.eq(pd.Timestamp('2026-02-26'))
    full['historical_vendor_arrival_proven_by_this_inventory'] = False
    full['economic_qualification_recertified_by_this_inventory'] = False
    counts = {'candidate_rows': len(full), 'qualified_rows': int(full.current_frozen_qualified.sum()),
              'unknown_rows': int(full.current_frozen_unknown.sum()),
              'proven_ineligible_rows': int(full.current_frozen_proven_ineligible.sum())}
    assert counts == source_receipt['full_pool']
    assert counts == dict(candidate_rows=111868, qualified_rows=62393, unknown_rows=47271, proven_ineligible_rows=2204)
    assert sum(counts[k] for k in ['qualified_rows', 'unknown_rows', 'proven_ineligible_rows']) == counts['candidate_rows']
    cov = full.groupby(['signal_date', 'quarter']).agg(
        original_candidates=('ticker', 'size'), qualified_current_pool=('current_frozen_qualified', 'sum'),
        unknown_candidates=('current_frozen_unknown', 'sum'), proven_ineligible=('current_frozen_proven_ineligible', 'sum')).reset_index()
    old_cov = pd.read_csv(bind(QUAL / 'data/coverage.csv'), parse_dates=['signal_date'])
    pd.testing.assert_frame_equal(cov, old_cov[cov.columns], check_dtype=False)
    full_days = int(cov.unknown_candidates.eq(0).sum())
    assert full_days == 0
    save_table('qualification_all_candidates', full, csv=False)
    save_table('qualification_unknown_candidates', full.loc[full.current_frozen_unknown])
    save_table('qualification_daily_candidate_coverage', old_cov)
    save_table('qualification_unknown_reason_counts', full.loc[full.current_frozen_unknown].groupby(
        ['final_input_gate', 'current_reason'], dropna=False).size().rename('rows').reset_index())

    event_path = QUAL / 'evidence/events/event_qualification.parquet'
    events = with_reference(pq(event_path), event_path)
    assert len(events) == 97 and int(events.status.eq('UNKNOWN').sum()) == 87
    save_table('qualification_events_all', events)
    save_table('qualification_events_unknown', events.loc[events.status.eq('UNKNOWN')])
    security_path = QUAL / 'evidence/events/security_day_qualification.parquet'
    security_days = with_reference(pq(security_path), security_path)
    save_table('qualification_security_day_evidence_all', security_days)
    for relative, dest in [
        ('data/DATA_RECEIPT.json', 'qualification_source_data_receipt.json'),
        ('data/DATA_FREEZE.json', 'qualification_source_data_freeze.json'),
        ('data/operational_exit_evidence.csv', 'qualification_operational_exit_evidence.csv'),
        ('evidence/identity/identity_lifecycle_qualification.json', 'qualification_identity_lifecycle_evidence.json'),
    ]:
        snapshot(QUAL / relative, dest)

    price_path = QUAL / 'data/test_prices.parquet'
    prices = with_reference(pq(price_path), price_path)
    prices['glw_conflict_override_disclosure'] = prices.ticker.eq('GLW') & prices.trade_date.isin(pd.to_datetime(['2026-02-26', '2026-02-27']))
    price_issues = prices.loc[prices.price_quality_warning | prices.glw_conflict_override_disclosure].copy()
    save_table('qualification_price_problem_rows', price_issues)
    save_table('qualification_price_daily_coverage', prices.groupby('trade_date').agg(
        total_price_rows=('ticker', 'size'), legacy_warning_rows=('price_quality_warning', 'sum'),
        glw_conflict_override_rows=('glw_conflict_override_disclosure', 'sum')).reset_index())

    scenario_path = BATCH / 'ALL_SCENARIOS.csv'
    scenarios = pd.read_csv(bind(scenario_path))
    test = scenarios.loc[scenarios.year.eq(2026)].copy()
    assert len(test) == 51
    daily_frames, position_frames, glw_frames, metadata_rows = [], [], [], []
    for row in test.itertuples(index=False):
        folder = Path(row.path)
        day_path, pos_path = folder / 'daily.parquet', folder / 'positions.parquet'
        days = with_reference(pq(day_path), day_path)
        positions = with_reference(pq(pos_path), pos_path)
        days['policy'] = row.policy
        days['cost_bps'] = row.cost_bps
        days['legacy_account_valuation_problem'] = days.valuation_status.ne('certified') | days.certified_nav.isna()
        assert int(days.legacy_account_valuation_problem.sum()) == row.uncertified_days
        assert len(days) == row.days == 183
        assert days.date.min() == pd.Timestamp('2026-01-02') and days.date.max() == pd.Timestamp('2026-09-24')
        days['full_original_pool_certified'] = False
        days['historical_vendor_actual_arrival_certified'] = False
        days['shareholder_total_return_certified'] = False
        days['candidate_coverage_reference'] = str(OUT / 'qualification_daily_candidate_coverage.parquet')
        target_path = folder / 'target_decisions.parquet'
        targets = pq(target_path, filters=[('ticker', '==', 'GLW'), ('signal_date', '==', pd.Timestamp('2026-02-26'))])
        targets['policy'], targets['cost_bps'] = row.policy, row.cost_bps
        targets['source_path'], targets['source_sha256'] = str(target_path), SOURCE_HASHES[str(target_path.resolve())]
        conflict_input = bool(targets.model_input_row_present.any()) if len(targets) else False
        days['glw_candidate_input_seen_20260226'] = conflict_input
        # This flags unresolved path dependence, not a calculated loss or known bad NAV.
        days['glw_common_input_conflict_window'] = conflict_input & days.date.ge(pd.Timestamp('2026-02-27'))
        days['constant_cash_no_stock_economic_sensitivity'] = row.policy == 'cash_control'
        days['glw_downstream_path_may_depend_on_conflicted_input'] = days.glw_common_input_conflict_window & ~days.constant_cash_no_stock_economic_sensitivity
        daily_frames.append(days)
        glw_frames.append(targets)
        positions['policy'], positions['cost_bps'] = row.policy, row.cost_bps
        badpos = positions.stale | positions.unknown
        position_frames.append(positions.loc[badpos])
        meta = js(folder / 'metadata.json')
        metadata_rows.append({'policy': row.policy, 'cost_bps': row.cost_bps, **meta})
    all_days = pd.concat(daily_frames, ignore_index=True)
    all_bad_positions = pd.concat(position_frames, ignore_index=True)
    all_glw = pd.concat(glw_frames, ignore_index=True)
    save_table('qualification_2026_all_account_days', all_days)
    save_table('qualification_2026_account_problem_days', all_days.loc[all_days.legacy_account_valuation_problem])
    save_table('qualification_2026_position_problem_rows', all_bad_positions)
    save_table('qualification_glw_consumption_records', all_glw)
    save_table('qualification_scenario_status', all_days.groupby(['policy', 'cost_bps']).agg(
        complete_original_window_days=('date', 'size'),
        legacy_uncertified_days=('legacy_account_valuation_problem', 'sum'),
        glw_downstream_uncertainty_days=('glw_downstream_path_may_depend_on_conflicted_input', 'sum'),
        full_original_pool_certified_days=('full_original_pool_certified', 'sum')).reset_index())
    save_json('qualification_2026_execution_metadata.json', metadata_rows)

    old_identity = js(IDENTITY)
    checks = []
    for role, path, expected in [
        ('original_A2_final_model', old_identity['frozen_final_model_path'], old_identity['frozen_final_model_sha256']),
        ('original_A2_producer', old_identity['producer_path'], old_identity['producer_sha256']),
        ('original_A2_quarter_universe', old_identity['quarterly_universe_path'], old_identity['quarterly_universe_sha256']),
        ('original_A2_feature_source', 'D:/us-tech-quant/scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py', old_identity['a2_feature_source_sha256']),
        ('original_A2_preregistered_source', 'D:/us-tech-quant/scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py', old_identity['a2_prereg_source_sha256']),
    ]:
        p = bind(path)
        actual = SOURCE_HASHES[str(p)]
        checks.append({'role': role, 'path': str(p), 'expected_sha256': expected, 'actual_sha256': actual, 'hash_match': actual == expected})
    assert all(x['hash_match'] for x in checks[:4])
    training_path = ORIGINAL / 'A2/training_matrix.parquet'
    training = pq(training_path, columns=['signal_date', 'target_end_date'])
    assert len(training) == 520328 and training.signal_date.max() < pd.Timestamp('2026-01-01')
    assert training.target_end_date.max() < pd.Timestamp('2026-01-01')
    oof_path = ORIGINAL / 'A2/oof_predictions.parquet'
    oof = pq(oof_path, columns=['signal_date', 'ticker', 'split', 'a2_prediction', 'a2_rank'])
    oof_summary = oof.groupby('split').signal_date.agg(['min', 'max', 'count']).reset_index().to_dict('records')
    frozen_manifest = js(ORIGINAL / 'audit/freeze_r1/frozen_baseline_manifest.json')
    artifact_hashes = pd.read_csv(bind(ORIGINAL / 'audit/freeze_r1/frozen_artifact_hashes.csv'))
    assert sha(ORIGINAL / 'audit/freeze_r1/frozen_artifact_hashes.csv') == frozen_manifest['artifact_hash_manifest']['sha256']
    score_hash = artifact_hashes.loc[artifact_hashes.artifact_id.eq('a2_predictions'), 'sha256'].item()
    assert sha(oof_path) == score_hash
    final_stage = next(x for x in frozen_manifest['contracts']['A2']['effective_model_vintages'] if x['year'] == 2025)
    fold_training = training.loc[training.signal_date.lt('2025-01-01') & training.target_end_date.lt('2025-01-02')]
    assert len(fold_training) == final_stage['training_row_count'] == 409674
    assert str(fold_training.target_end_date.max().date()) == final_stage['train_target_end_max'] == '2024-12-31'
    panel_path = WS / 'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
    panel_keys = pq(panel_path, columns=['signal_date', 'ticker'])
    panel_h2 = panel_keys.loc[panel_keys.signal_date.between('2025-07-01', '2025-12-29')]
    oof_h2 = oof.loc[oof.signal_date.between('2025-07-01', '2025-12-29')]
    joined_h2 = panel_h2.merge(oof_h2, on=KEY, how='outer', indicator=True, validate='one_to_one')
    assert joined_h2._merge.eq('both').all() and np.isfinite(joined_h2.a2_prediction).all()
    save_table('qualification_original_a2_h2_score_key_inventory', joined_h2, csv=False)
    oof_qualification = {'original_oof_path': str(oof_path), 'frozen_expected_sha256': score_hash,
        'actual_sha256': sha(oof_path), 'frozen_oof_hash_match': True,
        '2025_frozen_stage_record': final_stage,
        '2025_recomputed_training_rows': len(fold_training),
        'h2_candidate_join_counts': joined_h2._merge.value_counts().to_dict(),
        'h2_signal_window': ['2025-07-01', '2025-12-29'],
        'scores_are_original_saved_2025_oof_not_final_model_backprediction': True,
        'current_prereg_source_hash_drift': not checks[-1]['hash_match'],
        'current_prereg_source_must_not_be_used_to_silently_retrain_original': True,
        'common_account_replay_not_executed': True,
        'price_clock_and_feature_value_equivalence_not_fully_recertified_here': True}
    save_json('qualification_original_a2_oof_admissibility.json', oof_qualification)
    native_daily_path = ORIGINAL / 'A2/portfolio_daily.parquet'
    native_daily = pq(native_daily_path, columns=['execution_date', 'cash_before'])
    registry = js(WS / 'a2_latest_effective_joint_20260927/models/model_registry.json')
    baseline = registry['models']['hgb']
    baseline_sha = sha(bind(baseline['path']))
    assert baseline_sha == baseline['sha256']
    assert baseline_sha != old_identity['frozen_final_model_sha256']
    bind('D:/us-tech-quant/scripts/v22/fast_a2_r0f_corporate_action_and_nav_forensic_audit.py')
    bind(ORIGINAL / 'A2/pre_final_freeze.json')
    bind(ORIGINAL / 'audit/frozen_contracts_before_outcome_read.json')
    inherited = js(BATCH / 'audit/INHERITED_INPUT_AUDIT.json')
    for path in [
        WS / 'a2_capacity_in_training_paired_20260927/DATA_DEPENDENCY.md',
        WS / 'a2_complete_suite_nearest_effective_20260927/continuation_account_repair_r1/next_proof/ROUND2_GLW_ADJUDICATION_REPORT.md',
        BATCH / 'EXPERIMENT_CONTRACT.md', BATCH / 'ENSEMBLE_CONTRACT.md', BATCH / 'engine_v2.py',
        WS / 'a2_latest_effective_joint_20260927/data/quarter_timing.csv',
    ]:
        bind(path)
    save_json('qualification_original_a2_identity.json', {
        'status': 'ORIGINAL_A2_MODEL_PRODUCER_FEATURE_SOURCE_UNIVERSE_VERIFIED_CURRENT_PREREG_SOURCE_DRIFT_DISCLOSED',
        'identity_checks': checks, 'historical_identity_receipt': old_identity,
        'original_training_rows': len(training),
        'original_training_signal_min': training.signal_date.min(),
        'original_training_signal_max': training.signal_date.max(),
        'original_training_label_end_max': training.target_end_date.max(),
        'original_oof_stage_coverage': oof_summary,
        'original_2025_oof_admissibility': oof_qualification,
        'original_native_ledger_start': native_daily.execution_date.min(),
        'original_native_ledger_end': native_daily.execution_date.max(),
        'original_native_initial_cash': float(native_daily.cash_before.iloc[0]),
        'different_retrained_hgb_baseline': baseline,
        'different_retrained_hgb_baseline_actual_sha256': baseline_sha,
        'score_predictions_executed_here': 0, 'model_deserialization_executed_here': 0,
        'new_replays_executed_here': 0,
        'economic_increment_over_original_A2_certified': False,
    })
    save_json('qualification_revision_protocol.json', {
        'current_version': OUT.name,
        'current_scope': 'saved-evidence inventory only; no economic correction applied',
        'immutable_parent_batch': str(BATCH),
        'unknown_candidate_record_count_preserved': counts['unknown_rows'],
        'future_revision_required_fields': [
            'new_revision_id', 'parent_model_and_ensemble_weight_hashes', 'parent_data_hashes',
            'original_source_url_and_raw_body_hash', 'publication_time_and_vendor_arrival_time_separately',
            'security_identity_cusip_class_and_effective_interval', 'old_and_new_gate_per_original_row',
            'old_and_new_price_coordinate_event_dates_and_cash_settlement', 'all_unknown_rows_retained',
            'all_original_window_dates_retained', 'impacted_features_scores_and_accounts',
            'unchanged_model_no_fit_receipt', 'common_engine_cost_capacity_cash_contract',
            'revision_results_separate_from_original_results', 'remaining_unknown_evidence',
        ],
        'prohibited': ['overwrite old outputs', 'drop unknown candidates or bad dates to improve metrics',
                       'refit or choose weights using observed 2026', 'reopen closed capacity experiments',
                       'choose a preferred GLW event date using portfolio outcome',
                       'treat public availability as proven historical vendor arrival',
                       'credit EXAS cash before verified entitlement and settlement'],
    })
    assert all(sha(path) == digest for path, digest in SOURCE_HASHES.items())
    save_table('qualification_source_manifest', pd.DataFrame([
        {'path': p, 'sha256': digest, 'unchanged_after_inventory': True} for p, digest in SOURCE_HASHES.items()]))
    report = {
        'status': 'PASS_READ_ONLY_INVENTORY_WITH_UNRESOLVED_ECONOMIC_QUALIFICATION',
        'candidate_counts': counts, 'complete_original_pool_signal_days': full_days,
        'candidate_coverage_days': len(cov), 'coverage_matches_frozen_receipt_and_daily_csv': True,
        'unknown_full_records_preserved_in_parquet_and_csv': True,
        'events': {'all': len(events), 'unknown': int(events.status.eq('UNKNOWN').sum())},
        'price_rows_total': len(prices), 'price_problem_rows_including_glw_disclosure': len(price_issues),
        '2026_scenarios': len(test), 'all_account_days_preserved': len(all_days),
        'legacy_uncertified_account_days_preserved': int(all_days.legacy_account_valuation_problem.sum()),
        'problem_position_rows_preserved': len(all_bad_positions),
        'glw_candidate_record_count': len(all_glw),
        'ensemble_10bp_uncertified_days': all_days.loc[all_days.cost_bps.eq(10) & all_days.policy.str.startswith('ensemble_')].groupby('policy').legacy_account_valuation_problem.sum().astype(int).to_dict(),
        'known_glw_conflict': inherited['known_glw_conflict'],
        'original_A2_model_producer_feature_source_universe_hash_checks_pass': True,
        'original_A2_current_prereg_source_hash_matches_historical_freeze': checks[-1]['hash_match'],
        'original_A2_saved_2025_oof_hash_matches_historical_freeze': True,
        'original_A2_common_basis_economic_comparison_complete': False,
        'all_inputs_unchanged': True, 'source_count': len(SOURCE_HASHES),
        'new_fits': 0, 'new_predictions': 0, 'new_replays': 0, 'downloads': 0,
        'outputs': OUTPUTS.copy(),
    }
    save_json('qualification_verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'outputs'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
