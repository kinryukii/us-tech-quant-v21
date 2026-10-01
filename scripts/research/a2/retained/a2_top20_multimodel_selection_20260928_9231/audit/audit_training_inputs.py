"""Read-only input audit; no model outcomes, fitting, or 2026 prices are read."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = ROOT / 'a2_latest_effective_joint_20260927/data'
QUAL = ROOT / 'a2_qualification_holdings_v1_20260927/data'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def date(value):
    return str(value.date())


def main():
    features = json.loads((OLD/'JOINT_DATA_AUDIT.json').read_text(encoding='utf-8'))['features']
    pre = pd.read_parquet(OLD/'pre2026_joint_context.parquet', columns=[
        'signal_date', 'ticker', 'cusip', 'active_13f_quarter', 'new_buy_eligible',
        'execution_date', 'label_end_date', 'label_available', 'target_end_date',
        'target_context_available', 'y_next_open', 'latest_filing_date',
        'quarter_effective_date', *features])
    test_columns = ['signal_date', 'ticker', 'quarter', 'asof_quarter', 'new_buy_eligible',
                    'latest_filing_date', 'quarter_effective_date', *features]
    test = pd.read_parquet(QUAL/'test_features_context.parquet', columns=[
        *test_columns, 'context_only_if_held'])
    timing = pd.read_csv(OLD/'quarter_timing.csv', parse_dates=[
        'latest_filing_date', 'quarter_effective_date']).sort_values('quarter_effective_date')
    for frame, quarter, eligible in [(pre, 'active_13f_quarter', np.ones(len(pre), dtype=bool)),
                                      (test, 'quarter', test.new_buy_eligible.to_numpy(bool))]:
        assert not frame.duplicated(['signal_date', 'ticker']).any()
        assert np.isfinite(frame[features].to_numpy(float)).all()
        assert frame.signal_date.gt(frame.latest_filing_date).all()
        assert frame.signal_date.ge(frame.quarter_effective_date).all()
        positions = np.searchsorted(timing.quarter_effective_date.to_numpy(),
                                    frame.signal_date.to_numpy(), side='right') - 1
        assert (positions >= 0).all()
        expected = timing.quarter.to_numpy()[positions]
        assert (frame.loc[eligible, quarter].to_numpy() == expected[eligible]).all()
    assert pre.signal_date.lt('2026-01-01').all()
    mature = pre.label_available & pre.label_end_date.lt('2026-01-01')
    assert np.isfinite(pre.loc[mature, 'y_next_open']).all()
    assert pre.loc[mature, 'execution_date'].gt(pre.loc[mature, 'signal_date']).all()
    assert pre.loc[mature, 'label_end_date'].gt(pre.loc[mature, 'execution_date']).all()
    assert not (test.context_only_if_held & test.new_buy_eligible).any()
    assert test.loc[test.context_only_if_held, 'quarter'].ne(
        test.loc[test.context_only_if_held, 'asof_quarter']).all()
    folds = {}
    for cutoff in ['2024-01-01', '2025-01-01', '2026-01-01']:
        prior = pre.loc[pre.signal_date.lt(cutoff)]
        one = prior.label_available & prior.label_end_date.lt(cutoff)
        multi = prior.target_context_available & prior.target_end_date.lt(cutoff)
        folds[cutoff] = {
            'feature_rows_before_cutoff': len(prior),
            'mature_one_step_rows': int(one.sum()),
            'one_step_rows_removed': int((~one).sum()),
            'mature_multihorizon_context_rows': int(multi.sum()),
            'max_mature_one_step_label_end': date(prior.loc[one, 'label_end_date'].max()),
        }
    cov = pd.read_csv(QUAL/'coverage.csv')
    # Read qualification flags only, never the realized numeric 2026 price path.
    price_flags = pd.read_parquet(QUAL/'test_prices.parquet', columns=[
        'ticker', 'trade_date', 'price_quality_warning'])
    glw_feature = test.loc[test.ticker.eq('GLW') & test.signal_date.eq('2026-02-26')]
    glw_flags = price_flags.loc[price_flags.ticker.eq('GLW') &
                               price_flags.trade_date.eq('2026-02-26')]
    consumed = [OLD/'pre2026_joint_context.parquet', OLD/'quarter_timing.csv',
                OLD/'JOINT_DATA_AUDIT.json', QUAL/'test_features_context.parquet',
                QUAL/'test_prices.parquet', QUAL/'coverage.csv',
                ROOT/'a2_qualification_holdings_v1_20260927/engine_v2.py',
                ROOT/'a2_qualification_holdings_v1_20260927/adapters_v2.py',
                ROOT/'a2_capacity_in_training_paired_20260927/DATA_DEPENDENCY.md']
    report = {
        'status': 'PASS_WITH_EXPLICIT_DATA_LIMITATIONS',
        'source_data_modified': False, 'model_fit_calls': 0,
        'reads_model_result_files': False, 'reads_2026_numeric_prices': False,
        'prior_returns_used_for_selection': False,
        'features': features, 'signal_time_feature_count': len(features),
        'pre2026': {'rows': len(pre), 'signal_days': int(pre.signal_date.nunique()),
                    'first_signal': date(pre.signal_date.min()),
                    'last_signal': date(pre.signal_date.max()),
                    'years': pre.groupby(pre.signal_date.dt.year).agg(
                        rows=('ticker', 'size'), days=('signal_date', 'nunique'),
                        tickers=('ticker', 'nunique')).to_dict(orient='index'),
                    'fold_maturity': folds},
        'test2026': {'context_rows': len(test), 'new_buy_rows': int(test.new_buy_eligible.sum()),
                     'held_only_rows': int(test.context_only_if_held.sum()),
                     'held_only_by_ticker': test.loc[test.context_only_if_held].groupby('ticker').size().to_dict(),
                     'signal_days': int(test.signal_date.nunique()),
                     'first_signal': date(test.signal_date.min()), 'last_signal': date(test.signal_date.max()),
                     'original_candidate_rows': int(cov.original_candidates.sum()),
                     'unknown_candidate_rows': int(cov.unknown_candidates.sum()),
                     'proven_ineligible_rows': int(cov.proven_ineligible.sum()),
                     'complete_signal_days': int(cov.unknown_candidates.eq(0).sum()),
                     'formal_full_pool_test_allowed': False, 'blind_test': False},
        'clock': {'universe': 'latest publicly filed and effective 13F quarter; fifth subsequent session lag inherited',
                  'new_buy_quarter_searchsorted_check': 'PASS',
                  'training_feature_and_label_cutoff_exclusive': '2026-01-01',
                  'last_test_execution': '2026-09-23', 'terminal_valuation': '2026-09-24'},
        'known_glw_conflict': {'source': 'a2_capacity_in_training_paired_20260927/DATA_DEPENDENCY.md',
                               'signal_date': '2026-02-26',
                               'feature_row_present': bool(len(glw_feature)),
                               'old_price_warning_flag': bool(glw_flags.price_quality_warning.iloc[0]),
                               'resolution': 'unresolved event-date/adjusted-feature conflict; flag diagnostic path even if account NAV gate says certified'},
        'limitations': [
            'Retrospectively qualified 2026 subpool; qualification/availability/survivorship bias is not eliminated.',
            'Historical vendor actual arrival timestamps remain unproven.',
            '13F filing/effective clocks are checked; this is not a full source rebuild or original-universe survivorship proof.',
            'Affine price-index units are not raw tradable shares or certified shareholder total return.',
            'Holding context repair is partial; engine_v2 preserves units/capital/slots where model inputs remain missing.',
            '2025/2026 windows were previously observed, so new fixed recipes cannot restore an untouched holdout.',
        ],
        'input_sha256': {str(path): sha(path) for path in consumed},
    }
    (OUT/'INPUT_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['status', 'pre2026', 'test2026', 'known_glw_conflict']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
