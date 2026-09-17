"""One frozen conditional raw-bar diagnostic; existing ledger/statistics reused.

Separate CLI phases enforce blind fixed-key coverage before one no-fit evaluation.
This is not an execution backtester or a certified historical trading result.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np
import pandas as pd

REPO = Path('D:/us-tech-quant')
WORK = Path('C:/Users/Lenovo/Documents/CODING开发/strategy-lab-20260913')
SOURCE = REPO / 'scripts/research/a2/factors'
RESULT = Path('D:/us-tech-quant-results/A2_INTRADAY_CONTINUATION_20260913')
CACHE = Path('D:/us-tech-quant-cache/a2_intraday_continuation_20260913')
SEED = 20260913


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    def encode(item):
        if isinstance(item, (pd.Timestamp, datetime, Path)):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(type(item).__name__)
    Path(path).write_text(json.dumps(value, indent=2, default=encode, allow_nan=False) + '\n', encoding='utf-8')


def setup():
    freeze_path = RESULT / 'experiment_freeze.json'
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    required = [Path(__file__).resolve(), *[SOURCE / name for name in (
        'intraday_continuation.py', 'lottery_max_features.py', 'economic_return_inputs.py',
        'economic_return_preflight.py', 'tail_research_inputs.py', 'systematic_tail_research.py')],
        REPO / 'scripts/v22/a2_open_research_engine.py',
        REPO / 'scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py',
        RESULT.parent / 'A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913/paired_comparisons.csv',
        *[RESULT / name for name in ('preregistration.json', 'research_spec.json', 'data_contract.json', 'evaluation_keys.tsv',
            'start_gate.json', 'intraday_source_review.md', 'intraday_runner_review.md',
            'intraday_preregistration_review.md', 'intraday_data_execution_evidence.md', 'off_calendar_action_review.md')]]
    if not {str(path.resolve()) for path in required}.issubset(freeze['files']):
        raise RuntimeError('REQUIRED_FREEZE_DEPENDENCY_MISSING')
    for path, digest in freeze['files'].items():
        if sha(path) != digest:
            raise RuntimeError(f'INTRADAY_FROZEN_SOURCE_CHANGED:{path}')
    if freeze['files'].get(str(Path(__file__).resolve())) != sha(__file__):
        raise RuntimeError('RUNNER_NOT_FROZEN')
    prereg = json.loads((RESULT / 'preregistration.json').read_text(encoding='utf-8'))
    if freeze['candidate_value_evaluations_before_freeze'] != 0:
        raise RuntimeError('INTRADAY_NOT_PRE_EVALUATION_FREEZE')
    if freeze['decision'] != 'ALLOW_NEW_RESEARCH':
        raise RuntimeError('INTRADAY_START_NOT_ALLOWED')
    sys.path.insert(0, str(REPO))
    modules = {
        'reader': load_module('intraday_raw_reader', SOURCE / 'economic_return_inputs.py'),
        'factor': load_module('intraday_pure', SOURCE / 'intraday_continuation.py'),
        'keys': load_module('intraday_key_contract', SOURCE / 'economic_return_preflight.py'),
        'helpers': load_module('intraday_frozen_helpers', SOURCE / 'systematic_tail_research.py'),
    }
    return freeze, prereg, modules


def read_stage(freeze, prereg, modules):
    raw, events, full, calendar, lineage = modules['reader'].load_economic_return_inputs(
        contract_path=RESULT / 'data_contract.json')
    modules['keys'].validate_cohort(full, freeze['full_cohort'])
    panel = full.loc[full.signal_date.dt.year.isin([2023, 2024, 2025])].copy().reset_index(drop=True)
    modules['keys'].validate_cohort(panel, prereg['cohort'])
    encoded_keys = pd.read_csv(RESULT / 'evaluation_keys.tsv', sep='\t', header=None,
                               names=['signal_date', 'ticker'], parse_dates=['signal_date'])
    modules['keys'].validate_cohort(encoded_keys, prereg['cohort'])
    for frame in (full, panel):
        frame['source_qualification'] = 'PINNED_VENDOR_RAW_REGULAR_DAILY_BAR'
        frame['identity_qualification'] = 'INHERITED_TRANSPORT_CONTINUITY_NOT_DATED_ECONOMIC_CERTIFICATION'
        frame['pit_qualification'] = 'INHERITED_CHECKPOINT_LAG_CONVENTION_PUBLICATION_TIME_UNCERTIFIED'
    if raw.trade_date.ge('2026-01-01').any() or events.ex_div_date.ge('2026-01-01').any():
        raise RuntimeError('POST2025_ROW_BOUNDARY_FAILURE')
    return raw, full, panel, calendar, lineage


def recheck(freeze, lineage):
    for path, digest in {**freeze['files'], **lineage['source_and_input_hashes']}.items():
        if sha(path) != digest:
            raise RuntimeError(f'POST_PROCESSING_SOURCE_CHANGED:{path}')


def coverage_stage():
    target = RESULT / 'coverage_summary.json'
    if target.exists():
        raise RuntimeError('COVERAGE_ALREADY_RECORDED')
    freeze, prereg, modules = setup()
    raw, full, panel, calendar, lineage = read_stage(freeze, prereg, modules)
    coverage = modules['factor'].build_intraday_continuation(raw, calendar, full, compute_values=False)
    modules['keys'].validate_cohort(coverage, freeze['full_cohort'])
    if coverage[list(modules['factor'].VALUE_COLUMNS)].notna().any().any() or coverage.values_computed.any():
        raise RuntimeError('FORBIDDEN_VALUES_DURING_COVERAGE')
    evaluation = coverage.loc[coverage.signal_date.dt.year.isin([2023, 2024, 2025])].copy()
    modules['keys'].validate_cohort(evaluation, prereg['cohort'])
    complete = bool(evaluation.feature_available.all() and evaluation.target_available.all())
    summary = {
        'status': 'CONDITIONAL_BAR_COVERAGE_COMPLETE' if complete else 'UNTESTABLE_DATA_CONTRACT_INCOMPLETE',
        'evaluation_admitted': complete, 'full_cohort': freeze['full_cohort'], 'evaluation_cohort': prereg['cohort'],
        'evaluation_feature_available_rows': int(evaluation.feature_available.sum()),
        'evaluation_target_available_rows': int(evaluation.target_available.sum()),
        'evaluation_missing_feature_rows': int((~evaluation.feature_available).sum()),
        'evaluation_missing_target_rows': int((~evaluation.target_available).sum()),
        'full_panel_missing_feature_rows': int((~coverage.feature_available).sum()),
        'full_panel_missing_target_rows': int((~coverage.target_available).sum()),
        'factor_or_target_values_computed': False,
        'known_action_warning': 'TAC2021-05-31 archive date conflicts with issuer common-share calendar. Separate source-backed audit; event is outside2023-2025 signal formation/target scope. No date repair or row exclusion.',
        'qualification': 'Bar availability only; economic identity, publication-PIT and actual fills remain unconfirmed.',
        'new_predictive_fits': 0, 'new_candidate_comparisons': 0,
        'experiment_freeze_sha256': sha(RESULT / 'experiment_freeze.json'),
        'post2025_row_values_materialized': 0, 'completed_utc': datetime.now(timezone.utc).isoformat(),
    }
    recheck(freeze, lineage)
    mask_path = CACHE / 'coverage_masks.parquet'
    coverage.to_parquet(mask_path, index=False)
    summary['coverage_masks_sha256'] = sha(mask_path)
    write_json(RESULT / 'coverage_lineage.json', lineage)
    write_json(target, summary)
    print(json.dumps(summary), flush=True)


def append_trial(engine, ledger, *, suffix, status, count, runtime, input_hash, code_hash, metrics, failure=''):
    ledger.append([engine.trial_row(
        identifier=engine.trial_id('INTRADAY_CONTINUATION_20260913', suffix),
        parent='A2_INTRADAY_CONTINUATION_20260913', family='NO_MODEL_FIXED_FORMULA',
        spec={'feature_set_id': 'PRIOR_COMPLETED_MONTH_SAME_SESSION_CONTINUATION',
              'parameters': {'formation': 'one_complete_calendar_month', 'direction': 'positive'}, 'seed': SEED},
        threshold=20, outer_fold='EXPOSED_2023_2024_2025', inner_fold='NONE',
        audit={'validation_start': '2023-01-03', 'validation_end': '2025-12-02'},
        row_count=count, feature_count=1, status=status, failure=failure, runtime=runtime,
        predictive={}, economic=metrics, complexity={'predictive_fits': 0,
            'candidate_comparisons_started': int(status == 'STARTED'),
            'candidate_comparisons_completed': int(status == 'COMPLETED')},
        input_hash=input_hash, code_hash=code_hash)])


def evaluate_stage():
    start = time.perf_counter()
    if (RESULT / 'summary.json').exists() or (RESULT / 'trial_ledger.parquet').exists():
        raise RuntimeError('EVALUATION_ALREADY_STARTED_NO_DUPLICATE')
    freeze, prereg, modules = setup()
    coverage = json.loads((RESULT / 'coverage_summary.json').read_text(encoding='utf-8'))
    if coverage['experiment_freeze_sha256'] != sha(RESULT / 'experiment_freeze.json'):
        raise RuntimeError('FREEZE_CHANGED_AFTER_COVERAGE')
    if pd.Timestamp(coverage['completed_utc']) < pd.Timestamp(freeze['frozen_utc']):
        raise RuntimeError('COVERAGE_PREDATES_FREEZE')
    if coverage['evaluation_admitted'] is not True or coverage['status'] != 'CONDITIONAL_BAR_COVERAGE_COMPLETE':
        raise RuntimeError('FIXED_COHORT_COVERAGE_FAILED')
    if sha(CACHE / 'coverage_masks.parquet') != coverage['coverage_masks_sha256']:
        raise RuntimeError('COVERAGE_MASK_CHANGED')
    masks = pd.read_parquet(CACHE / 'coverage_masks.parquet')
    modules['keys'].validate_cohort(masks, freeze['full_cohort'])
    eval_masks = masks.loc[masks.signal_date.dt.year.isin([2023, 2024, 2025])]
    modules['keys'].validate_cohort(eval_masks, prereg['cohort'])
    if not eval_masks.feature_available.all() or not eval_masks.target_available.all():
        raise RuntimeError('COVERAGE_MASK_NOT_COMPLETE')
    raw, full, panel, calendar, lineage = read_stage(freeze, prereg, modules)
    engine = modules['helpers'].import_path('intraday_existing_engine', REPO / 'scripts/v22/a2_open_research_engine.py')
    r5, _, _ = modules['reader'].load_tail_definitions().load_sources()
    ledger = engine.TrialLedger(RESULT / 'trial_ledger.parquet')
    append_trial(engine, ledger, suffix='START', status='STARTED', count=len(panel), runtime=0,
                 input_hash=sha(RESULT / 'data_contract.json'), code_hash=sha(__file__), metrics={})
    try:
        return evaluate_started(freeze, prereg, modules, raw, panel, calendar, lineage, engine, r5, ledger, start)
    except Exception as error:
        failure = f'{type(error).__name__}:{error}'
        already_completed = bool(ledger.frame.status.eq('COMPLETED').any())
        append_trial(engine, ledger, suffix='FAILED', status='REPORTING_FAILED' if already_completed else 'FAILED', count=len(panel),
                     runtime=time.perf_counter() - start, input_hash=sha(RESULT / 'data_contract.json'),
                     code_hash=sha(__file__), metrics={}, failure=failure)
        write_json(RESULT / 'evaluation_failure.json', {
            'status': 'FAILED_ATTEMPT_PRESERVED_NO_SILENT_RETRY', 'failure': failure,
            'candidate_comparisons_started': 1, 'candidate_comparisons_completed': int(already_completed),
            'new_predictive_fits': 0, 'failed_utc': datetime.now(timezone.utc).isoformat()})
        raise


def evaluate_started(freeze, prereg, modules, raw, panel, calendar, lineage, engine, r5, ledger, start):
    measured = modules['factor'].build_intraday_continuation(raw, calendar, panel, compute_values=True)
    modules['keys'].validate_cohort(measured, prereg['cohort'])
    if not measured.feature_available.all() or not measured.target_available.all():
        raise RuntimeError('EVALUATION_COVERAGE_CHANGED')
    if not np.isfinite(measured[list(modules['factor'].VALUE_COLUMNS)].to_numpy(float)).all():
        raise RuntimeError('INCOMPLETE_MEASURED_VALUES')
    # Rank input deliberately excludes all future target/coverage fields.
    ranking = measured[['signal_date', 'ticker', 'intraday_continuation_score']].rename(columns={'intraday_continuation_score': 'prediction'})
    measured['candidate_rank'] = engine.stable_rank(ranking)
    measured['group'] = np.where(measured.candidate_rank.le(20), 'TOP20', 'BOTTOM20')
    records = []
    for date, day in measured.groupby('signal_date', sort=True):
        if len(day) != 40 or day.ticker.nunique() != 40 or set(day.candidate_rank) != set(range(1, 41)):
            raise RuntimeError('PAIRED_UNIVERSE_CHANGED')
        for group, group_rows in day.groupby('group', sort=True):
            returns = group_rows.set_index('ticker').next_session_gross_return
            for cost in (10, 20):
                scenario = modules['factor'].one_session_group_return(returns, cost_bps=cost)
                if scenario['status'] != 'CONDITIONAL_BAR_FEE_SCENARIO':
                    raise RuntimeError('GROUP_COST_SCENARIO_UNAVAILABLE')
                records.append({'signal_date': date, 'execution_date': group_rows.next_market_session.iloc[0],
                                'group': group, 'cost_bps': cost, **scenario})
    daily = pd.DataFrame(records)
    paired = daily.pivot(index=['signal_date', 'execution_date', 'cost_bps'], columns='group',
                         values='bar_return_cost_scenario').reset_index()
    paired['delta'] = paired.TOP20 - paired.BOTTOM20
    if len(paired) != 732 * 2 or paired.isna().any().any():
        raise RuntimeError('PAIRED_DAILY_SCOPE_CHANGED')
    primary = paired.loc[paired.cost_bps.eq(10)].sort_values('signal_date')
    delta = primary.delta.to_numpy(float)
    first_stats = pd.read_csv(RESULT.parent / 'A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913/paired_comparisons.csv')
    statistics = []
    for block in (20, 40, 60):
        pvalue = r5.block_bootstrap_pvalue(delta, repetitions=5000, block=block, seed=SEED)
        lower, upper = r5.block_bootstrap_mean_interval(delta, repetitions=5000, block=block, seed=SEED)
        earlier = first_stats.loc[first_stats.block.eq(block), 'p_one_sided'].to_list()
        if len(earlier) != 3:
            raise RuntimeError('PRIOR_CANDIDATE_PVALUE_FAMILY_CHANGED')
        adjusted = float(modules['helpers'].holm(earlier + [pvalue])[-1])
        statistics.append({'block_sessions': block, 'mean_delta': float(delta.mean()),
                           'nominal_one_sided_p': pvalue, 'cumulative_four_holm_p': adjusted,
                           'nominal_mean_interval_lower': lower, 'nominal_mean_interval_upper': upper})
    yearly = paired.assign(year=paired.signal_date.dt.year).groupby(['year', 'cost_bps']).agg(
        dates=('delta', 'size'), mean_delta=('delta', 'mean'),
        top_mean_bar_cost_scenario=('TOP20', 'mean'), bottom_mean_bar_cost_scenario=('BOTTOM20', 'mean')).reset_index()
    group_means = daily.groupby(['group', 'cost_bps']).agg(
        dates=('signal_date', 'size'), mean_gross_bar_return=('gross_bar_return', 'mean'),
        mean_bar_return_cost_scenario=('bar_return_cost_scenario', 'mean'),
        mean_total_cost_initial_capital=('total_cost_initial_capital', 'mean')).reset_index()
    autocorrelations = {str(lag): float(pd.Series(delta).autocorr(lag)) for lag in (1, 5, 20)}
    summary = {
        'status': 'COMPLETED_CONDITIONAL_RAW_BAR_DIAGNOSTIC', 'evidence_role': prereg['evidence_role'],
        'primary_mean_daily_delta': float(delta.mean()), 'statistics': statistics,
        'yearly': yearly.to_dict('records'), 'group_means': group_means.to_dict('records'),
        'delta_autocorrelation': {key: value if np.isfinite(value) else None for key, value in autocorrelations.items()},
        'autocorrelation_null_meaning': 'Undefined at the requested lag, including zero variance; not imputed as zero.',
        'new_predictive_fits': 0, 'new_candidate_comparisons': 1,
        'campaign_predictive_fits': 12, 'campaign_candidate_comparisons': 4,
        'nominal_primary_and_all_years_direction_positive': bool(statistics[0]['cumulative_four_holm_p'] <= .05 and yearly.mean_delta.gt(0).all()),
        'automatic_advancement': False, 'certified_historical_trading_result': False,
        'post2025_row_values_materialized': 0,
        'limitations': ['Unknown historical adaptive trial count; repeated history',
                        'Conditional vendor bars/checkpoint/transport identity, not certified publication-PIT',
                        'Hypothetical bar-price costs, no auction fills or actual broker NAV',
                        'Bootstrap nominal only; every fixed block reported; no sign/window/TopN rescue'],
        'completed_utc': datetime.now(timezone.utc).isoformat(),
    }
    recheck(freeze, lineage)
    measured.to_parquet(CACHE / 'measured_panel.parquet', index=False)
    daily.to_parquet(CACHE / 'daily_group_cost_scenarios.parquet', index=False)
    paired.to_csv(RESULT / 'paired_daily.csv', index=False)
    yearly.to_csv(RESULT / 'yearly_summary.csv', index=False)
    pd.DataFrame(statistics).to_csv(RESULT / 'nominal_statistics.csv', index=False)
    group_means.to_csv(RESULT / 'group_summary.csv', index=False)
    write_json(RESULT / 'data_lineage.json', lineage)
    # Verify JSON serializability before committing a successful ledger event.
    json.dumps(summary, allow_nan=False)
    append_trial(engine, ledger, suffix='COMPLETE', status='COMPLETED', count=len(panel),
                 runtime=time.perf_counter() - start, input_hash=sha(RESULT / 'data_contract.json'),
                 code_hash=sha(__file__), metrics={'primary_mean_daily_delta': float(delta.mean())})
    summary['artifact_hashes'] = {str(path): sha(path) for path in [CACHE / 'measured_panel.parquet',
        CACHE / 'daily_group_cost_scenarios.parquet', RESULT / 'paired_daily.csv', RESULT / 'trial_ledger.parquet']}
    write_json(RESULT / 'summary.json', summary)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['coverage', 'evaluate'], required=True)
    args = parser.parse_args()
    {'coverage': coverage_stage, 'evaluate': evaluate_stage}[args.phase]()
