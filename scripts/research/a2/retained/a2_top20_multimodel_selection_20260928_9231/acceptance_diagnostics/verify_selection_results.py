"""Independent checks of exported rankings, coverage, contributions and metrics."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'selection'


def close(left, right):
    assert np.allclose(np.asarray(left, float), np.asarray(right, float),
                       rtol=1e-10, atol=1e-12, equal_nan=True)


def check(year):
    receipt = json.loads((SOURCE / f'COMPLETE_{year}.json').read_text(encoding='utf-8'))
    assert receipt['fit_attempts'] == 0
    candidates = pd.read_parquet(SOURCE / f'candidates_{year}.parquet')
    candidates = candidates[candidates.ranking_eligible]
    scores = pd.read_parquet(SOURCE / f'scores_{year}.parquet')
    daily = pd.read_parquet(SOURCE / f'daily_{year}.parquet')
    keys = ['policy', 'signal_date', 'ticker']
    assert not scores.duplicated(keys).any()
    assert not candidates.duplicated(['signal_date', 'ticker']).any()
    assert len(scores) == len(candidates) * receipt['policies']
    joined = scores.merge(candidates[['signal_date', 'ticker', 'label_available', 'forward_return']],
                          on=['signal_date', 'ticker'], suffixes=('', '_candidate'),
                          how='left', validate='many_to_one', indicator=True)
    assert joined['_merge'].eq('both').all()
    assert joined.label_available.eq(joined.label_available_candidate).all()
    close(joined.forward_return, joined.forward_return_candidate)
    counts = scores.groupby(['policy', 'signal_date']).size().reset_index(name='n')
    expected = candidates.groupby('signal_date').size().rename('expected_n')
    counts = counts.join(expected, on='signal_date')
    assert counts.n.eq(counts.expected_n).all()
    active = scores[scores.policy.ne('cash_control')].copy()
    assert np.isfinite(active.reference_score).all()
    ordered = active.sort_values(['policy', 'signal_date', 'reference_score', 'ticker'],
                                 ascending=[True, True, False, True], kind='stable')
    expected_rank = ordered.groupby(['policy', 'signal_date']).cumcount() + 1
    assert ordered.reference_rank.eq(expected_rank).all()
    assert active.reference_top20.eq(active.reference_rank.le(20)).all()
    cash = scores[scores.policy.eq('cash_control')]
    assert cash.reference_rank.isna().all() and not cash.reference_top20.any()
    assert daily.groupby('signal_date').complete_common_pool.nunique().eq(1).all()

    checked_metrics = 0
    rows = []
    for (policy, date), group in scores.groupby(['policy', 'signal_date'], sort=False):
        selected = group[group.reference_top20]
        remaining = group[~group.reference_top20]
        gross = .0475 * selected.forward_return.sum() if selected.label_available.all() else np.nan
        net = gross - .002 * .0475 * len(selected)
        spread = selected.forward_return.mean() - remaining.forward_return.mean()
        rows.append({'policy': policy, 'signal_date': date, 'gross': gross, 'net': net, 'spread': spread})
    derived = pd.DataFrame(rows).merge(daily, on=['policy', 'signal_date'], validate='one_to_one')
    close(derived.gross, derived.simple_gross_if_selected_labels_complete)
    close(derived.net, derived.simple_net_if_selected_labels_complete)
    close(derived.spread, derived.observed_top20_minus_rest)
    complete = derived.complete_common_pool
    close(derived.loc[complete, 'net'], derived.loc[complete, 'main_simple_net'])
    assert derived.loc[~complete, 'main_simple_net'].isna().all()
    chosen_dates = sorted(candidates.signal_date.unique())[::31]
    for (policy, date), group in active[active.signal_date.isin(chosen_dates)].groupby(['policy', 'signal_date']):
        usable = group[group.label_available]
        if len(usable) < 3 or usable.reference_score.nunique() < 2 or usable.forward_return.nunique() < 2:
            expected_ic = np.nan
        else:
            expected_ic = spearmanr(usable.reference_score, usable.forward_return).statistic
        observed_ic = daily.loc[daily.policy.eq(policy) & daily.signal_date.eq(date), 'observed_ic'].item()
        close([expected_ic], [observed_ic])
        checked_metrics += 1
    contributions = pd.read_parquet(SOURCE / f'ensemble_contributions_{year}.parquet')
    columns = [c for c in contributions if c.startswith('contribution_')]
    assert len(columns) == 6
    reconstructed = contributions[columns].sum(axis=1) - contributions.disagreement_penalty - contributions.downside_penalty
    close(reconstructed, contributions.reference_score)
    compare = contributions.merge(scores[keys + ['reference_score']], on=keys,
                                  validate='one_to_one', suffixes=('_contributions', '_score'))
    assert len(compare) == len(contributions)
    close(compare.reference_score_contributions, compare.reference_score_score)
    for alias in ['joint_hgb_lw', 'joint_hgb_pca']:
        a = scores[scores.policy.eq(alias)].set_index(['signal_date', 'ticker']).reference_score.sort_index()
        b = scores[scores.policy.eq('joint_hgb')].set_index(['signal_date', 'ticker']).reference_score.sort_index()
        assert a.index.equals(b.index)
        close(a, b)
    return {'year': year, 'status': 'PASS', 'score_rows': len(scores),
            'candidate_rows': len(candidates), 'daily_metric_rows_recomputed': len(derived),
            'ic_rows_independently_recomputed': checked_metrics,
            'contribution_rows_reconciled': len(compare), 'fit_attempts': receipt['fit_attempts']}


if __name__ == '__main__':
    result = {'status': 'PASS', 'years': [check(2025), check(2026)],
              'scope': 'Independent exported-table checks; not source-price or return certification.'}
    (HERE / 'SELECTION_INDEPENDENT_VERIFICATION.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
