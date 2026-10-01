"""Reuse learned artifacts; replay a single predeclared baseline intervention."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gc
from pathlib import Path
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / 'a2_pto_full_compat_20260928_r2'
sys.path.insert(1, str(OLD))
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from integrity import read, write, sha, verify_freeze

def make_roster():
    from shared import paths, RISKS, OPTIMIZERS
    original = pd.read_csv(OLD / 'PREDECLARED_PATHS.csv')
    if not original.equals(paths()) or len(original) != 8194:
        raise RuntimeError('ORIGINAL_ROSTER_IDENTITY_FAILED')
    a2 = pd.DataFrame([{
        'path_id': f'a2_reference__identity__{risk}__{opt}',
        'members': 'RAW_A2_ORIGINAL_ARTIFACT_WITH_ONE_DAY_OOF_ADAPTER',
        'group': 'a2_reference', 'fusion': 'identity', 'risk': risk,
        'optimizer': opt, 'layer': 'pto'} for risk in RISKS for opt in OPTIMIZERS])
    raw_reference = pd.DataFrame([{'path_id': 'a2_raw_score_common_account_reference',
        'members': 'RAW_A2_SCORE_WITH_OLD_H2_REFERENCE_ALLOCATION',
        'group': 'a2_raw_score_reference', 'fusion': 'identity', 'risk': 'none',
        'optimizer': 'old_h2_reference_top20', 'layer': 'a2_raw_score_reference'}])
    roster = pd.concat([original, a2, raw_reference], ignore_index=True)
    if len(roster) != 8247 or roster.path_id.duplicated().any():
        raise RuntimeError('NEW_ROSTER_INVALID')
    target = ROOT / 'PREDECLARED_PATHS.csv'
    if target.exists():
        if not pd.read_csv(target).equals(roster):
            draft = pd.read_csv(target)
            if ((ROOT / 'FROZEN_BEFORE_2026.json').exists() or len(draft) != 8246 or
                    not draft.equals(roster.iloc[:8246].reset_index(drop=True))):
                raise RuntimeError('PRESERVE_PREDECLARED_ROSTER')
            backup = ROOT / 'PREDECLARED_PATHS_DRAFT_8246.csv'
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            roster.to_csv(target, index=False)
    else:
        roster.to_csv(target, index=False)
    return roster

def build_predictions(year):
    verify_freeze()
    from baseline_correction import make_predictions
    from a2_adapter import make_a2_predictions
    from run_suite import forbidden_fit_guard
    restore = forbidden_fit_guard()
    try:
        receipt = make_predictions(year)
        a2_receipt = make_a2_predictions(year)
    finally:
        restore()
    folder = ROOT / 'predictions' / f'evaluation_{year}'
    marker = folder / 'JOINT_COMPLETE.json'
    if marker.exists():
        result = read(marker)
        for name, digest in result['artifacts'].items():
            if sha(folder / name) != digest:
                raise RuntimeError('JOINT_PREDICTIONS_DRIFT:' + name)
        return result
    base = np.load(folder / 'forecast_cube.npz', allow_pickle=False)
    cube = base['mu']
    dates, tickers, streams = base['dates'], base['tickers'], base['stream_ids']
    scores = pd.read_parquet(folder / 'a2_scores.parquet')
    if scores.duplicated(['signal_date', 'ticker']).any():
        raise RuntimeError('DUPLICATE_A2_EVALUATION_KEYS')
    forecast_keys = pd.read_parquet(folder / 'streams.parquet', columns=['signal_date', 'ticker'])
    joined = forecast_keys.merge(scores, on=['signal_date', 'ticker'], how='outer',
                                 validate='one_to_one', indicator=True)
    if not joined._merge.eq('both').all():
        raise RuntimeError('A2_MUST_COVER_SAME_FULL_AVAILABLE_CONTEXT')
    di = {pd.Timestamp(date): i for i, date in enumerate(dates)}
    ti = {str(ticker): i for i, ticker in enumerate(tickers)}
    a2_cube = np.full((len(dates), 1, len(tickers)), np.nan)
    ri = scores.signal_date.map(di).to_numpy(int)
    ci = scores.ticker.map(ti).to_numpy(int)
    a2_cube[ri, 0, ci] = scores.a2__mu.to_numpy(float)
    complete_cube = np.concatenate([cube, a2_cube], axis=1)
    keys = np.r_[streams, np.asarray(['a2_reference__identity'])]
    np.savez_compressed(folder / 'forecast_with_a2.npz', mu=complete_cube,
                        dates=dates, tickers=tickers, stream_ids=keys)
    raw_cube = np.full((len(dates), len(tickers)), np.nan)
    raw_cube[ri, ci] = scores.raw_a2_score.to_numpy(float)
    np.savez_compressed(folder / 'a2_raw_score_cube.npz', score=raw_cube, dates=dates, tickers=tickers)
    coverage = pd.read_csv(folder / 'STREAM_COVERAGE.csv')
    finite = np.isfinite(scores.a2__mu.to_numpy(float))
    a2_record = {'stream_id': 'a2_reference__identity',
                 'status': 'AVAILABLE' if finite.all() else 'FAILED_A2_ADAPTER_OR_SOURCE',
                 'predictable_rows': int(finite.sum()), 'candidate_context_rows': len(scores),
                 'failure': a2_receipt.get('failure', '')}
    raw_record = dict(a2_record)
    raw_finite = np.isfinite(scores.raw_a2_score.to_numpy(float))
    raw_record.update(stream_id='a2_raw_score_reference__identity',
                      status='AVAILABLE' if raw_finite.all() else 'FAILED_RAW_SCORE_UNAVAILABLE',
                      predictable_rows=int(raw_finite.sum()),
                      failure='' if raw_finite.all() else
                      'raw scores were not materialized by A2 adapter pipeline; ' + a2_receipt.get('failure', ''))
    pd.concat([coverage, pd.DataFrame([a2_record, raw_record])], ignore_index=True).to_csv(
        folder / 'JOINT_STREAM_COVERAGE.csv', index=False)
    result = {'status': 'FROZEN_CORRECTED_PREDICTIONS_COMPLETE', 'year': year,
              'declared_mu_streams': 153, 'additional_raw_score_reference': 1, 'base_source_receipt': receipt,
              'a2_source_receipt': a2_receipt,
              'RISK_CACHE_SOURCE': receipt['RISK_CACHE_SOURCE'],
              'artifacts': {name: sha(folder / name) for name in [
                  'forecast_with_a2.npz', 'a2_raw_score_cube.npz', 'JOINT_STREAM_COVERAGE.csv',
                  'COMPLETE.json', 'A2_COMPLETE.json', 'a2_scores.parquet']}}
    write(marker, result)
    base.close()
    del cube, complete_cube, a2_cube, raw_cube
    gc.collect()
    verify_freeze()
    print(year, 'JOINT_PREDICTIONS_COMPLETE', flush=True)
    return result

def reuse_rl(year, roster):
    folder = OLD / 'results' / f'evaluation_{year}' / 'rl_control'
    receipt = read(folder / 'DONE.json')
    for name, digest in receipt['artifacts'].items():
        if sha(folder / name) != digest:
            raise RuntimeError('UNCHANGED_RL_ACCOUNT_DRIFT:' + name)
    summary = pd.read_csv(folder / 'SUMMARY.csv')
    expected = set(roster.loc[roster.layer.eq('rl_control'), 'path_id'])
    if set(summary.path_id) != expected:
        raise RuntimeError('RL_REUSE_ROSTER_MISMATCH')
    summary['result_origin'] = 'UNCHANGED_RL_ACCOUNT_ARTIFACT_REUSED'
    summary['baseline_intervention_applies'] = False
    destination = ROOT / 'results' / f'evaluation_{year}' / 'rl_control'
    destination.mkdir(parents=True, exist_ok=True)
    summary.to_csv(destination / 'SUMMARY.csv', index=False)
    reuse = {'status': 'IDENTICAL_RL_INPUT_POLICY_AND_LEDGER_REUSED', 'paths': 4,
             'source_folder': str(folder), 'source_done_sha256': sha(folder / 'DONE.json'),
             'ledger_sources': {str(folder / name): digest for name, digest in receipt['artifacts'].items()},
             'new_fit_calls': 0, 'new_replay_calls': 0,
             'reason': 'RL observes market/account state, never corrected predictor mu; every actor, input and execution rule unchanged.'}
    write(destination / 'REUSE_RECEIPT.json', reuse)
    return summary, reuse

def run_year(year):
    verify_freeze()
    destination = ROOT / 'results' / f'evaluation_{year}'
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / 'COMPLETE.json').exists():
        result = read(destination / 'COMPLETE.json')
        if sha(destination / 'ALL_PATHS.csv') != result['coverage_sha256']:
            raise RuntimeError('PRESERVE_COMPLETE_RETEST')
        return result
    prediction = ROOT / 'predictions' / f'evaluation_{year}'
    receipt = read(prediction / 'JOINT_COMPLETE.json')
    for name, digest in receipt['artifacts'].items():
        if sha(prediction / name) != digest:
            raise RuntimeError('CORRECTED_PREDICTION_DRIFT:' + name)
    risk_source = receipt['RISK_CACHE_SOURCE']
    if sha(risk_source['path']) != risk_source['sha256']:
        raise RuntimeError('FROZEN_RISK_CACHE_CHANGED')
    roster = pd.read_csv(ROOT / 'PREDECLARED_PATHS.csv')
    coverage = pd.read_csv(prediction / 'JOINT_STREAM_COVERAGE.csv')
    available = set(coverage.loc[coverage.status.eq('AVAILABLE'), 'stream_id'])
    stream_keys = roster.group + '__' + roster.fusion
    pto = roster.layer.ne('rl_control')
    runnable = roster.loc[pto & stream_keys.isin(available)].copy()
    failed = roster.loc[pto & ~stream_keys.isin(available)].copy()
    failed['year'] = year
    failed['research_status'] = 'FAILED_PREDICTION_OR_FUSION'
    reasons = coverage.set_index('stream_id')['failure'].fillna('').to_dict()
    failed['failure_reason'] = [(reasons.get(key) or 'required declared member/calibration/fusion unavailable; no substitute member')
                                for key in (failed.group + '__' + failed.fusion)]
    from market_runtime import prepare_market
    from portfolio_policy import PortfolioPolicy
    from fast_account import run_many
    from run_suite import LedgerWriter, summarize, forbidden_fit_guard
    from cached_replay import eager_risk_load
    from fast_replay import numeric_work_elimination
    market = prepare_market(year).market
    forecast = np.load(prediction / 'forecast_with_a2.npz', allow_pickle=False)
    if not np.array_equal(forecast['tickers'], market.tickers) or not np.array_equal(
            forecast['dates'], market.dates.to_numpy()):
        raise RuntimeError('MARKET_FORECAST_ALIGNMENT_FAILED')
    summaries, receipts = [], []
    with eager_risk_load() as archives, numeric_work_elimination():
        risk_cache = np.load(risk_source['path'], allow_pickle=False)
        for category in ['pto', 'target_fusion', 'a2_raw_score_reference']:
            selected = runnable.loc[runnable.layer.eq(category)].copy()
            if selected.empty:
                continue
            folder = destination / category
            if (folder / 'DONE.json').exists():
                prior = read(folder / 'DONE.json')
                for name, digest in prior['artifacts'].items():
                    if sha(folder / name) != digest:
                        raise RuntimeError('COMPLETED_NEW_ACCOUNT_DRIFT:' + str(folder / name))
                summaries.append(pd.read_csv(folder / 'SUMMARY.csv'))
                receipts.append(prior)
                continue
            if folder.exists():
                raise RuntimeError('PRESERVE_INTERRUPTED_LEDGER:' + str(folder))
            writer = LedgerWriter(folder)
            if category == 'a2_raw_score_reference':
                from raw_a2_reference import RawA2ScoreReferencePolicy
                raw_archive = np.load(prediction / 'a2_raw_score_cube.npz', allow_pickle=False)
                policy = RawA2ScoreReferencePolicy(raw_archive['score'])
            else:
                policy = PortfolioPolicy(selected, forecast, risk_cache,
                                         diagnostic_callback=lambda frame: writer('optimization', frame))
            start = time.monotonic()
            restore = forbidden_fit_guard()
            print(year, category, len(selected), 'START', flush=True)
            try:
                with threadpool_limits(limits=2):
                    result = run_many(market, selected.path_id.tolist(), policy,
                                      collect_ledgers=False, ledger_callback=writer)
            except Exception:
                write(folder / 'FAILED_ATTEMPT.json', {'status': 'RUNTIME_FAILURE',
                      'traceback': traceback.format_exc(), 'record_counts': writer.counts,
                      'seconds': time.monotonic() - start})
                raise
            finally:
                restore()
                writer.close()
            daily = pd.concat(writer.daily, ignore_index=True)
            solver = writer.solver_summary()
            solver.to_csv(folder / 'SOLVER_SUMMARY.csv', index=False)
            summary = summarize(daily, selected, year, solver)
            is_raw_reference = category == 'a2_raw_score_reference'
            summary['result_origin'] = ('NEW_ORIGINAL_A2_SCORE_COMMON_ACCOUNT_REFERENCE' if is_raw_reference
                                        else 'NEW_BASELINE_INTERVENTION_ACCOUNT_REPLAY')
            summary['baseline_intervention_applies'] = not is_raw_reference
            summary.to_csv(folder / 'SUMMARY.csv', index=False)
            forecast_path = prediction / ('a2_raw_score_cube.npz' if is_raw_reference else 'forecast_with_a2.npz')
            source_binding = {str(OLD / name): sha(OLD / name) for name in [
                'fast_account.py', 'portfolio_policy.py', 'market_runtime.py',
                'optimization.py', 'run_suite.py', 'fast_numeric.py', 'fast_cvar_numeric.py',
                'fast_replay.py', 'cached_replay.py']}
            if is_raw_reference:
                source_binding[str(ROOT / 'raw_a2_reference.py')] = sha(ROOT / 'raw_a2_reference.py')
            done = {'status': 'ACCOUNT_REPLAY_COMPLETE', 'year': year, 'category': category,
                    'paths': len(selected), 'fit_calls': 0, 'seconds': time.monotonic() - start,
                    'records': writer.counts, 'engine_audit': result.audit,
                    'metadata': result.metadata, 'forecast_source': str(forecast_path),
                    'forecast_sha256': sha(forecast_path),
                    'baseline_intervention_applies': not is_raw_reference,
                    'risk_source': None if is_raw_reference else risk_source,
                    'frozen_marker_sha256': sha(ROOT / 'FROZEN_BEFORE_2026.json'),
                    'source_binding': source_binding,
                    'artifacts': {path.name: sha(path) for path in folder.iterdir() if path.is_file()}}
            write(folder / 'DONE.json', done)
            summaries.append(summary)
            receipts.append(done)
            print(year, category, 'COMPLETE', round(done['seconds'], 2), flush=True)
            del policy, writer, daily, solver, result
            if category == 'a2_raw_score_reference':
                raw_archive.close()
            gc.collect()
        risk_cache.close()
    write(destination / 'IMPLEMENTATION_EQUIVALENCE_USED.json', {
        'status': 'EXISTING_BIT_IDENTICAL_NUMERIC_ADAPTERS_REUSED', 'year': year,
        'mathematical_spec_changed': False, 'model_parameters_changed': False,
        'risk_archives': [{'source': item.source, 'decompression_counts': dict(item.decompression_counts)} for item in archives],
        'source_binding': {str(OLD / name): sha(OLD / name) for name in [
            'fast_replay.py', 'cached_replay.py', 'fast_numeric.py', 'fast_cvar_numeric.py']}})
    forecast.close()
    rl_summary, rl_reuse = reuse_rl(year, roster)
    combined = pd.concat([*summaries, rl_summary, failed], ignore_index=True)
    if len(combined) != len(roster) or combined.path_id.duplicated().any():
        raise RuntimeError('FIXED_ROSTER_COVERAGE_INCOMPLETE')
    combined.to_csv(destination / 'ALL_PATHS.csv', index=False)
    verify_freeze()
    result = {'status': 'ALL_PREDECLARED_PATHS_RESOLVED', 'year': year,
              'declared': len(roster), 'new_account_replays': sum(item['paths'] for item in receipts),
              'unchanged_accounts_reused': 4, 'failed_prediction_paths': len(failed),
              'all_results_included': True, 'blind_test': False,
              'formal_full_pool_status': 'BLOCKED_DATA' if year == 2026 else 'HISTORICAL_INPUT_LIMITATIONS',
              'receipts': receipts, 'rl_reuse': rl_reuse,
              'coverage_sha256': sha(destination / 'ALL_PATHS.csv')}
    write(destination / 'COMPLETE.json', result)
    return result

def audit_year(year):
    verify_freeze()
    from market_runtime import prepare_market
    from verify_ledgers import verify_folder
    market = prepare_market(year).market
    reports = []
    for category in ['pto', 'target_fusion', 'a2_raw_score_reference']:
        folder = ROOT / 'results' / f'evaluation_{year}' / category
        if not (folder / 'DONE.json').exists():
            continue
        marker = folder / 'INDEPENDENT_AUDIT.json'
        if marker.exists():
            report = read(marker)
        else:
            started = time.monotonic()
            report = verify_folder(folder, market=market)
            report['seconds'] = time.monotonic() - started
            write(marker, report)
        reports.append(report)
        print(year, category, 'INDEPENDENT_AUDIT', report.get('status'), flush=True)
        if report.get('status') != 'PASS' or report.get('mismatch_count', 0) != 0:
            raise RuntimeError('INDEPENDENT_LEDGER_AUDIT_FAILED:' + str(marker))
    write(ROOT / 'results' / f'evaluation_{year}' / 'INDEPENDENT_AUDIT_COMPLETE.json',
          {'status': 'COMPLETE', 'reports': reports,
           'unchanged_rl_audit_source': str(OLD / 'results' / f'evaluation_{year}' / 'rl_control')})
    return reports

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--predict', type=int, choices=[2025, 2026])
    parser.add_argument('--run', type=int, choices=[2025, 2026])
    parser.add_argument('--audit', type=int, choices=[2025, 2026])
    args = parser.parse_args()
    if args.prepare:
        print('PREDECLARED_PATHS', len(make_roster()), flush=True)
    if args.predict:
        print(build_predictions(args.predict)['status'], flush=True)
    if args.run:
        print(run_year(args.run)['status'], flush=True)
    if args.audit:
        audit_year(args.audit)
