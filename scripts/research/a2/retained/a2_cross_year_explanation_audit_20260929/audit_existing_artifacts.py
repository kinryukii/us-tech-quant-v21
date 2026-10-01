"""Read existing parameters, predictions and ledgers only; create a separate explanatory audit."""
from pathlib import Path
import sys, json, hashlib
from datetime import datetime, timezone

sys.dont_write_bytecode = True
WORKSPACE = Path(r'C:\Users\Lenovo\Documents\CODING开发')
ROOT = WORKSPACE / 'a2_pto_full_compat_20260928_r1'
OUT = Path(__file__).resolve().parent
assert OUT.is_relative_to(WORKSPACE) and not OUT.is_relative_to(ROOT)
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.append(r'D:\us-tech-quant-envs\us-tech-quant-main\Lib\site-packages')
import numpy as np
import pandas as pd
import joblib

def sha(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()

sources = {}
def bind(path):
    path = Path(path)
    files = sorted(path.glob('*.parquet')) if path.is_dir() else [path]
    for file in files:
        sources[str(file.relative_to(ROOT)).replace('\\', '/')] = sha(file)
    return path

blocked_calls = {'fit', 'partial_fit', 'predict', 'predict_proba', 'solve_quadratic', 'solve_cvar', 'replay', 'simulate'}
def guard(frame, event, arg):
    if event == 'call' and frame.f_code.co_name in blocked_calls:
        raise RuntimeError('FORBIDDEN_LEARNING_PREDICTION_OPTIMIZATION_OR_REPLAY:' + frame.f_code.co_name)

def main():
    destination = OUT / 'AUDIT.json'
    assert not destination.exists(), 'REFUSE_OVERWRITE_EXISTING_AUDIT'
    sys.setprofile(guard)
    for name in ['FREEZE.json', 'REPORT.md', 'DELIVERY_VALIDATION.json', 'EXPERIMENT_CONTRACT.md', 'fusion.py', 'policy.py', 'models/base/BASE_TRAINING_COVERAGE.csv', 'models/fusion/validation/RECEIPT.json', 'models/fusion/final/RECEIPT.json']:
        bind(ROOT / name)
    diagnostic = pd.read_csv(bind(ROOT / 'analysis/PREDICTION_DIAGNOSTICS.csv'))
    all_results = pd.read_csv(bind(ROOT / 'analysis/ALL_STRATEGY_RESULTS.csv'))
    calibration, opportunity, daily_summary, checkpoints = [], [], [], []
    members = ['mlp', 'resnet', 'hgb', 'dist_ngboost', 'lgb']
    ids = [member + '__diagonal__mean_variance__joint' for member in members]
    daily_frames = {}
    for year, stage, input_name in [(2025, 'validation', 'pre'), (2026, 'final', 'test')]:
        folder = ROOT / f'results/{year}/batch_000'
        daily = pd.read_parquet(bind(folder / 'daily'), columns=['strategy_id', 'date', 'nav', 'gross_exposure', 'net_return', 'actual_name_count', 'transaction_cost_amount', 'valuation_status'], filters=[('strategy_id', 'in', ids)])
        daily_frames[year] = daily
        context = pd.read_parquet(bind(ROOT / f'data/{input_name}.parquet'), columns=['signal_date', 'ticker', 'new_buy_eligible'])
        context = context.loc[context.signal_date.dt.year.eq(year)]
        decision_dates = pd.read_parquet(bind(folder / 'raw_model_outputs'), columns=['strategy_id', 'signal_date'], filters=[('strategy_id', '=', ids[0])]).signal_date.drop_duplicates()
        for member in ['mlp', 'resnet']:
            adapter = joblib.load(bind(ROOT / f'models/fusion/{stage}/{member}_adapter.joblib'))
            scaler = adapter['model'].named_steps['standardscaler']
            ridge = adapter['model'].named_steps['ridge']
            coefficient = float(ridge.coef_[0])
            slope = coefficient / float(scaler.scale_[0])
            intercept = float(ridge.intercept_) - slope * float(scaler.mean_[0])
            assert slope > 0 and ridge.alpha == 10.0
            row = diagnostic.loc[diagnostic.year.eq(year) & diagnostic.stream.eq(member)].iloc[0]
            cov = coefficient * float(scaler.scale_[0]) * (1 + ridge.alpha / adapter['n'])
            target_std = np.sqrt(adapter['scale'] ** 2 + coefficient ** 2 * (1 + 2 * ridge.alpha / adapter['n']))
            calibration.append({'year': year, 'stage': stage, 'member': member, 'adapter_sample_rows': adapter['n'], 'ridge_alpha': ridge.alpha, 'intercept': intercept, 'slope': slope, 'calibrated_mean_bp': float(row.prediction_mean * 1e4), 'calibrated_std_bp': float(row.prediction_std * 1e4), 'implied_raw_std_bp_same_diagnostic_support': float(row.prediction_std / abs(slope) * 1e4), 'oof_raw_std': float(scaler.scale_[0]), 'oof_raw_target_covariance_restored_from_parameters': cov, 'oof_clipped_target_std_restored_from_parameters': float(target_std), 'pooled_oof_correlation_restored_from_parameters': float(cov / scaler.scale_[0] / target_std)})
            pred = pd.read_parquet(bind(ROOT / f'predictions/streams/{stage}/{member}.parquet'))
            raw = pd.read_parquet(bind(ROOT / f'predictions/base/{stage}/{member}.parquet'), columns=['signal_date', 'ticker', 'mu'])
            affine = pred.merge(raw, on=['signal_date', 'ticker'], validate='one_to_one', suffixes=('', '_raw'))
            error = np.abs(affine.mu - (intercept + slope * affine.mu_raw))
            assert len(affine) == len(pred) == len(raw) and error.max() < 1e-10
            calibration[-1]['stored_affine_output_validation_max_error'] = float(error.max())
            pred = pred.merge(context, on=['signal_date', 'ticker'], validate='one_to_one')
            pred = pred.loc[pred.new_buy_eligible & pred.signal_date.isin(decision_dates)]
            by_day = pred.groupby('signal_date', sort=False)
            stats = by_day.mu.agg(['std', 'max'])
            top20 = by_day.apply(lambda group: group.nlargest(20, 'mu').mu.gt(.001).mean(), include_groups=False)
            opportunity.append({'year': year, 'member': member, 'rows': len(pred), 'days': len(stats), 'scope': 'existing actual policy signal dates, new-buy-eligible prediction rows; not future-maturity-filtered, not actual selected/filled holdings', 'fraction_mu_gt_10bp': float(pred.mu.gt(.001).mean()), 'daily_cross_section_std_median_bp': float(stats['std'].median() * 1e4), 'top20_by_mu_fraction_gt_10bp_daily_mean': float(top20.mean()), 'top20_by_mu_fraction_gt_10bp_daily_median': float(top20.median())})
        for sid, group in daily.groupby('strategy_id'):
            group = group.sort_values('date').copy()
            group['pnl_usd'] = group.nav - group.nav.shift(1, fill_value=1000000)
            result = all_results.loc[all_results.year.eq(year) & all_results.strategy.eq(sid)].iloc[0]
            assert len(group) == result.days
            assert abs(group.pnl_usd.sum() - result.indicative_return * 1000000) < 1e-6
            assert abs(group.gross_exposure.mean() - result.mean_gross_exposure) < 1e-12
            daily_summary.append({'year': year, 'strategy': sid, 'days': len(group), 'mean_gross_exposure': float(result.mean_gross_exposure), 'gross_exposure_median': float(group.gross_exposure.median()), 'days_gross_over_50pct': int(group.gross_exposure.gt(.5).sum()), 'days_gross_below_1pct': int(group.gross_exposure.lt(.01).sum()), 'original_window_return': float(result.indicative_return), 'total_net_profit_usd': float(group.pnl_usd.sum()), 'fees_usd': float(result.fees), 'uncertified_quote_quality_days': int(result.uncertified_days)})
            checkpoint = group.loc[group.date.le(pd.Timestamp(f'{year}-09-24'))]
            checkpoints.append({'year': year, 'strategy': sid, 'date': str(checkpoint.iloc[-1].date)[:10], 'account_days': len(checkpoint), 'recorded_nav': float(checkpoint.iloc[-1].nav), 'recorded_return': float(checkpoint.iloc[-1].nav / 1000000 - 1), 'interpretation': 'post-hoc reading of existing ledger checkpoint; no new account, evaluation selection or equal-period causal experiment'})
    ratios = []
    for member in ['mlp', 'resnet']:
        a, b = [next(r for r in calibration if r['year'] == year and r['member'] == member) for year in [2025, 2026]]
        slope_ratio = b['slope'] / a['slope']
        raw_ratio = b['implied_raw_std_bp_same_diagnostic_support'] / a['implied_raw_std_bp_same_diagnostic_support']
        output_ratio = b['calibrated_std_bp'] / a['calibrated_std_bp']
        assert abs(output_ratio - slope_ratio * raw_ratio) < 1e-12
        ratios.append({'member': member, 'slope_ratio': slope_ratio, 'raw_output_std_ratio': raw_ratio, 'calibrated_output_std_ratio': output_ratio, 'not_account_return_causal_contribution': True})
    dates = [pd.Timestamp(s) for s in ['2025-10-17', '2025-10-20', '2025-10-21']]
    chosen = ids[:4]
    folder = ROOT / 'results/2025/batch_000'
    positions = pd.read_parquet(bind(folder / 'positions'), columns=['strategy_id', 'date', 'ticker', 'market_value'], filters=[('strategy_id', 'in', chosen), ('date', 'in', dates)])
    trades = pd.read_parquet(bind(folder / 'trades'), columns=['strategy_id', 'execution_date', 'ticker', 'side', 'notional', 'transaction_cost'], filters=[('strategy_id', 'in', chosen), ('execution_date', 'in', dates[1:])])
    assert not positions.duplicated(['strategy_id', 'date', 'ticker']).any()
    concentration = []
    for sid in chosen:
        parts, closure = [], []
        for prior, current in zip(dates, dates[1:]):
            old = positions.loc[positions.strategy_id.eq(sid) & positions.date.eq(prior)].set_index('ticker').market_value
            new = positions.loc[positions.strategy_id.eq(sid) & positions.date.eq(current)].set_index('ticker').market_value
            tx = trades.loc[trades.strategy_id.eq(sid) & trades.execution_date.eq(current)].copy()
            side = tx.side.str.upper()
            assert side.isin(['BUY', 'SELL']).all()
            tx['net_trade_cash'] = np.where(side.eq('SELL'), tx.notional, -tx.notional)
            pnl = new.subtract(old, fill_value=0).add(tx.groupby('ticker').net_trade_cash.sum(), fill_value=0).subtract(tx.groupby('ticker').transaction_cost.sum(), fill_value=0)
            d = daily_frames[2025]
            nav_delta = float(d.loc[d.strategy_id.eq(sid) & d.date.eq(current), 'nav'].iloc[0] - d.loc[d.strategy_id.eq(sid) & d.date.eq(prior), 'nav'].iloc[0])
            difference = float(pnl.sum() - nav_delta)
            assert abs(difference) < 1e-6
            parts.append(pnl)
            closure.append({'date': str(current)[:10], 'nav_change_usd': nav_delta, 'ticker_pnl_closure_error_usd': difference})
        summed = parts[0].add(parts[1], fill_value=0).sort_values(ascending=False)
        full_profit = next(r['total_net_profit_usd'] for r in daily_summary if r['year'] == 2025 and r['strategy'] == sid)
        concentration.append({'strategy': sid, 'dates': ['2025-10-20', '2025-10-21'], 'two_day_net_account_gain_usd': float(summed.sum()), 'original_window_net_profit_usd': full_profit, 'two_day_gain_fraction_of_net_profit': float(summed.sum() / full_profit) if full_profit > 0 else None, 'BYND_net_pnl_usd': float(summed.get('BYND', 0)), 'top_ticker_contributions': [{'ticker': ticker, 'net_pnl_usd': float(value)} for ticker, value in summed.head(4).items()], 'daily_accounting_closure': closure, 'interpretation': 'realized research-ledger attribution including fees; not a rerun excluding the stock/dates and not a claim of causal annual-gap attribution or shareholder total-return certification'})
    for name, digest in sources.items():
        assert sha(ROOT / name) == digest, 'SOURCE_CHANGED:' + name
    sys.setprofile(None)
    record = {'status': 'PASS_READ_ONLY_EXISTING_ARTIFACT_EXPLANATION', 'created_utc': datetime.now(timezone.utc).isoformat(), 'base_batch': str(ROOT), 'calibration': calibration, 'dispersion_factorization': ratios, 'cost_boundary_opportunity_diagnostics': opportunity, 'account_summaries': daily_summary, 'recorded_same_month_day_checkpoints': checkpoints, 'two_day_ticker_accounting_attribution': concentration, 'scope': {'fit_calls': 0, 'predict_api_calls': 0, 'optimization_calls': 0, 'new_account_replays': 0, 'new_candidates_seeds_horizons_or_weight_searches': 0, 'original_files_modified': 0, 'no_complete_causal_cross_year_decomposition_claimed': True, 'formal_full_pool_status': 'BLOCKED_DATA'}, 'source_sha256': sources, 'producer_sha256': sha(__file__), 'primary_literature_context_only': ['https://arxiv.org/abs/1710.08005', 'https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf']}
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status': record['status'], 'source_files_verified_unchanged': len(sources), 'affine_maps_checked': len(calibration), 'cost_boundary_groups': len(opportunity), 'account_paths_checked': len(daily_summary), 'two_day_attribution_paths': len(concentration), 'output': str(destination)}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
