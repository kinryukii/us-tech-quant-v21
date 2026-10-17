"""R6/R7 synthetic boundary and causal-state acceptance; no research readers/fits."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import stateful_decision as decision


def synthetic_panel(sessions=50):
    calendar = pd.bdate_range('2024-01-02', periods=sessions)
    names = [f'A{i:02d}' for i in range(21)]
    pred, labels = [], []
    for di, date in enumerate(calendar):
        members = names[:20] if di == 0 else names[1:21]
        for j, ticker in enumerate(names):
            top = ticker in members
            rank = members.index(ticker) + 1 if top else 21
            row = dict(signal_date=date, ticker=ticker, security_id='SID_' + ticker,
                feature_available=True, is_raw_top20=top, new_buy_eligible=top,
                raw_top20_set_complete=True, raw_top20_set_count=20,
                raw_a2_rank=float(rank), raw_a2_prediction=.25 - rank / 1000. + di / 10000.,
                raw_a2_oof_split='SYNTHETIC_PAST_MODEL_OOF', raw_selector_input_present=True,
                is_max_group=True, stock_forecast_input_present=True)
            row.update({feature: .01 + j / 1000. + di / 10000. for feature in decision.inputs.FEATURES})
            pred.append(row)
            labels.append(dict(signal_date=date, ticker=ticker, security_id='SID_' + ticker,
                feature_available=True, label_available=di + 6 < len(calendar),
                account_event_unhandled=False, label_unsupported_common_event=False,
                label_mature_date=calendar[min(di + 6, len(calendar) - 1)], y_open5=.02 + j / 1000.))
    return pd.DataFrame(pred), pd.DataFrame(labels), calendar


def rows_with_inputs(frame, columns, cutoff=None):
    keep = ['sample_id', 'signal_date', *columns]
    if frame.empty:
        return pd.DataFrame(columns=keep)
    result = frame.loc[:, keep]
    if cutoff is not None:
        result = result.loc[result.signal_date <= cutoff]
    return result.sort_values('sample_id').reset_index(drop=True)


def first_cohort(frame, ticker='A01'):
    rows = frame.loc[frame.ticker.eq(ticker)]
    return rows.loc[rows.cohort_id.eq(rows.iloc[0].cohort_id)].copy()


@pytest.mark.parametrize('y', [-1., 0., .03, .50])
def test_local_edges_reconcile_same_unit_capital_and_cash(y):
    edge = decision.counterfactual_edges(np.array([y]), np.array([.02]))
    buy_debit = 1.001
    exit_cash = (1. + y) * .999
    assert edge['buy'][0] == pytest.approx(exit_cash / buy_debit - 1., abs=1e-12)
    assert edge['hold'][0] == pytest.approx(exit_cash - .999, abs=1e-12)
    replace_cash = .999 / 1.001 * (1. + y) * .999
    keep_cash = 1.02 * .999
    assert edge['replace'][0] == pytest.approx(replace_cash - keep_cash, abs=1e-12)


@pytest.mark.parametrize('bad', [-1.000001, np.nan, np.inf, -np.inf])
def test_local_edge_rejects_invalid_shareholder_return(bad):
    with pytest.raises(ValueError):
        decision.counterfactual_edges([bad])
    with pytest.raises(ValueError):
        decision.counterfactual_edges([.01], [bad])


@pytest.mark.parametrize('prior', [0., .25, .5, .75, 1.])
def test_gross_utility_is_scalar_local_return_not_nav(prior):
    returns = np.array([-1., -.03, 0., .02, .30])
    actual = decision.gross_utilities(returns, np.full(len(returns), prior))
    expected = np.array([[g*y - .001*abs(g-prior) - .001*g*(1+y) - 5*g*g*y*y
                          for g in (0., .25, .5, .75, 1.)] for y in returns])
    np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=1e-12)
    assert actual.shape == (len(returns), 5)


@pytest.mark.parametrize('bad', [-.25, 1.25, np.nan, np.inf])
def test_gross_rejects_leverage_short_and_unknown_previous_state(bad):
    with pytest.raises(ValueError):
        decision.gross_utilities(np.array([.01]), np.array([bad]))


@pytest.mark.parametrize('bad', [-1.01, np.nan, np.inf])
def test_gross_rejects_invalid_terminal_return(bad):
    with pytest.raises(ValueError):
        decision.gross_utilities(np.array([bad]), np.array([.5]))


def test_gross_target_ties_use_current_state_before_low_gross():
    np.testing.assert_array_equal(decision.gross_targets(np.array([0., 0.]), np.array([0., 1.])), [0, 4])


@pytest.mark.parametrize('edges', [None, [0., 0., 0., 0., 0.], [0., 0., .01, -.02, .03]])
def test_date_equal_weights_keep_zero_edge_days(edges):
    dates = pd.to_datetime(['2024-01-02']*2 + ['2024-01-03']*3)
    weights = decision.date_weights(dates, edges)
    assert np.isfinite(weights).all() and (weights >= 0).all()
    assert weights.mean() == pytest.approx(1.)
    totals = pd.Series(weights).groupby(pd.Series(dates)).sum()
    assert totals.iloc[0] == pytest.approx(totals.iloc[1])
    assert totals.min() > 0


def test_encoding_preserves_missing_rank_without_reordering():
    source = pd.DataFrame({'raw_rank': [np.nan, 12.], 'raw_score': [.02, np.nan]})
    original = source.copy(deep=True)
    array, names = decision.encode_features(source, ('raw_rank', 'raw_score'))
    np.testing.assert_array_equal(array, [[0., .02, 1., 0.], [12., 0., 0., 1.]])
    assert names == ('raw_rank', 'raw_score', 'raw_rank__missing', 'raw_score__missing')
    pd.testing.assert_frame_equal(source, original)
    with pytest.raises(ValueError):
        decision.encode_features(pd.DataFrame({'raw_rank': [np.inf]}), ('raw_rank',))


def test_future_rank_and_score_append_does_not_change_past_features():
    pred, labels, calendar = synthetic_panel()
    cut = calendar[10]
    before, _ = decision.build_samples(pred, labels, calendar)
    changed = pred.copy()
    changed.loc[changed.signal_date.gt(cut), ['raw_a2_rank', 'raw_a2_prediction']] = [999., -100.]
    after, _ = decision.build_samples(changed, labels, calendar)
    for objective, columns in [('buy', decision.SINGLE), ('hold', decision.SINGLE),
            ('replace', decision.PAIR), ('distribution', decision.SINGLE), ('gross', decision.GROSS)]:
        pd.testing.assert_frame_equal(rows_with_inputs(before[objective], columns, cut),
                                      rows_with_inputs(after[objective], columns, cut))
    truncated, _ = decision.build_samples(pred.loc[pred.signal_date.le(cut)],
                                          labels.loc[labels.signal_date.le(cut)], calendar)
    pd.testing.assert_frame_equal(rows_with_inputs(before['hold'], decision.SINGLE, cut),
                                  rows_with_inputs(truncated['hold'], decision.SINGLE, cut))


def test_future_missing_label_cannot_change_cohort_or_opportunity_features():
    pred, labels, calendar = synthetic_panel()
    before, _ = decision.build_samples(pred, labels, calendar)
    changed = labels.copy()
    changed.loc[changed.signal_date.ge(calendar[4]), ['label_available', 'y_open5']] = [False, np.nan]
    after, _ = decision.build_samples(pred, changed, calendar)
    for objective, columns in [('buy', decision.SINGLE), ('hold', decision.SINGLE),
            ('replace', decision.PAIR), ('distribution', decision.SINGLE), ('gross', decision.GROSS)]:
        pd.testing.assert_frame_equal(rows_with_inputs(before[objective], columns),
                                      rows_with_inputs(after[objective], columns))


def test_pair_is_chosen_before_labels_and_failed_pair_is_not_substituted():
    pred, labels, calendar = synthetic_panel()
    baseline, _ = decision.build_samples(pred, labels, calendar)
    day = baseline['replace'].loc[baseline['replace'].signal_date.eq(calendar[1])]
    assert set(day.incumbent) == {'A01', 'A02'} and set(day.ticker) == {'A20'}
    changed = labels.copy()
    selected = changed.signal_date.eq(calendar[1]) & changed.ticker.eq('A01')
    changed.loc[selected, ['label_available', 'y_open5']] = [False, np.nan]
    altered, audit = decision.build_samples(pred, changed, calendar)
    failed = altered['replace'].loc[altered['replace'].signal_date.eq(calendar[1])]
    assert set(failed.sample_id) == set(day.sample_id)
    assert set(failed.incumbent) == {'A01', 'A02'}
    assert not bool(failed.loc[failed.incumbent.eq('A01'), 'label_qualified'].iloc[0])
    assert audit['pair_invalid_not_replaced'] >= 1


def test_pair_label_maturity_is_maximum_of_both_sides():
    pred, labels, calendar = synthetic_panel()
    incumbent = labels.signal_date.eq(calendar[1]) & labels.ticker.eq('A01')
    labels.loc[incumbent, 'label_mature_date'] = calendar[10]
    samples, _ = decision.build_samples(pred, labels, calendar)
    pair = samples['replace'].loc[samples['replace'].signal_date.eq(calendar[1]) & samples['replace'].incumbent.eq('A01')].iloc[0]
    assert pair.label_mature_date == calendar[10]


@pytest.mark.parametrize('sid', [None, np.nan, '', 'UNKNOWN', 'UNBOUND'])
def test_unknown_sid_is_never_qualified_or_a_bound_gross_component(sid):
    pred, labels, calendar = synthetic_panel()
    pred.loc[pred.ticker.eq('A01'), 'security_id'] = sid
    labels.loc[labels.ticker.eq('A01'), 'security_id'] = sid
    samples, _ = decision.build_samples(pred, labels, calendar)
    rows = samples['distribution'].loc[samples['distribution'].ticker.eq('A01')]
    assert not rows.label_qualified.any()
    assert not samples['gross'].label_qualified.any()


@pytest.mark.parametrize('column, bad', [('feature_available', np.nan),
    ('feature_available', 'False'), ('label_available', np.nan), ('label_available', 'False'),
    ('account_event_unhandled', None), ('label_unsupported_common_event', None)])
def test_unknown_label_flags_are_not_silently_booleanized(column, bad):
    pred, labels, calendar = synthetic_panel()
    mask = labels.signal_date.eq(calendar[1]) & labels.ticker.eq('A01')
    labels[column] = labels[column].astype(object)
    labels.loc[mask, column] = bad
    samples, _ = decision.build_samples(pred, labels, calendar)
    row = samples['hold'].loc[samples['hold'].signal_date.eq(calendar[1]) & samples['hold'].ticker.eq('A01')].iloc[0]
    assert not bool(row.label_qualified)


def test_sid_change_cuts_cohort_and_does_not_reuse_old_lag():
    pred, labels, calendar = synthetic_panel()
    mask = pred.ticker.eq('A01') & pred.signal_date.ge(calendar[9])
    pred.loc[mask, 'security_id'] = 'SID_A01_NEW'
    labels.loc[labels.ticker.eq('A01') & labels.signal_date.ge(calendar[9]), 'security_id'] = 'SID_A01_NEW'
    samples, audit = decision.build_samples(pred, labels, calendar)
    new = samples['buy'].loc[samples['buy'].ticker.eq('A01') & samples['buy'].signal_date.eq(calendar[9])].iloc[0]
    assert audit['sid_breaks'] == 1
    assert pd.isna(new.rank_change) and pd.isna(new.score_change)
    assert new.cohort_age_sessions == 0


def test_cohort_survives_membership_exit_without_claiming_account_age():
    pred, labels, calendar = synthetic_panel()
    samples, audit = decision.build_samples(pred, labels, calendar)
    departed = samples['hold'].loc[samples['hold'].ticker.eq('A00') & samples['hold'].signal_date.eq(calendar[2])].iloc[0]
    assert departed.raw_member == 0 and departed.cohort_age_sessions == 1
    assert audit['cohort_type'] == 'EXOGENOUS_UNIT_LOT_NOT_ACCOUNT'
    assert not {'cash', 'nav', 'physical_quantity', 'actual_fill', 'holding_age'}.intersection(samples['hold'].columns)


def test_duration_uses_three_fixed_probes_and_strictly_past_maturity():
    pred, labels, calendar = synthetic_panel()
    samples, _ = decision.build_samples(pred, labels, calendar)
    cohort = first_cohort(samples['duration'])
    assert cohort.probe_age.tolist() == [0, 7, 14]
    assert cohort.signal_date.tolist() == [calendar[1], calendar[8], calendar[15]]
    assert cohort.target.eq(0).all()
    for previous, current in zip(cohort.itertuples(index=False), list(cohort.itertuples(index=False))[1:]):
        assert previous.label_mature_date < current.signal_date
    equal = labels.copy()
    equal.loc[equal.signal_date.eq(calendar[1]) & equal.ticker.eq('A01'), 'label_mature_date'] = calendar[8]
    censored, _ = decision.build_samples(pred, equal, calendar)
    assert first_cohort(censored['duration']).probe_age.tolist() == [0]


@pytest.mark.parametrize('kind', ['negative', 'unknown', 'unsupported'])
def test_duration_failure_or_unknown_censors_later_probes_without_fabrication(kind):
    pred, labels, calendar = synthetic_panel()
    first = labels.signal_date.eq(calendar[1]) & labels.ticker.eq('A01')
    if kind == 'negative':
        labels.loc[first, 'y_open5'] = -.02
    elif kind == 'unknown':
        labels.loc[first, ['label_available', 'y_open5']] = [False, np.nan]
    else:
        labels.loc[first, 'label_unsupported_common_event'] = True
    samples, _ = decision.build_samples(pred, labels, calendar)
    cohort = first_cohort(samples['duration'])
    assert cohort.probe_age.tolist() == [0]
    assert cohort.target.iloc[0] == 1 if kind == 'negative' else pd.isna(cohort.target.iloc[0])
    assert cohort.censor_endpoint.iloc[0] == calendar[7]


def test_gross_requires_all_twenty_labels_and_keeps_all_five_prior_states():
    pred, labels, calendar = synthetic_panel()
    samples, _ = decision.build_samples(pred, labels, calendar)
    day = samples['gross'].loc[samples['gross'].signal_date.eq(calendar[2])]
    assert len(day) == 5 and set(day.gross_previous_proxy) == {0., .25, .5, .75, 1.}
    assert day.label_qualified.all()
    labels.loc[labels.signal_date.eq(calendar[2]) & labels.ticker.eq('A01'), ['label_available', 'y_open5']] = [False, np.nan]
    blocked, audit = decision.build_samples(pred, labels, calendar)
    day = blocked['gross'].loc[blocked['gross'].signal_date.eq(calendar[2])]
    assert len(day) == 5 and not day.label_qualified.any()
    assert day.basket_y.isna().all() and audit['gross_incomplete_label_dates'] >= 1


@pytest.mark.parametrize('surface', ['pred', 'labels', 'calendar'])
def test_2026_surface_is_rejected_before_sample_construction(surface):
    pred, labels, calendar = synthetic_panel()
    if surface == 'pred':
        pred.loc[pred.index[0], 'signal_date'] = pd.Timestamp('2026-01-02')
    elif surface == 'labels':
        labels.loc[labels.index[0], 'signal_date'] = pd.Timestamp('2026-01-02')
    else:
        calendar = calendar.append(pd.DatetimeIndex(['2026-01-02']))
    with pytest.raises(ValueError, match='2026_LOCKED'):
        decision.build_samples(pred, labels, calendar)


def test_split_uses_signal_and_target_maturity_boundaries_and_preserves_inference():
    frame = pd.DataFrame(dict(signal_date=pd.to_datetime(['2023-09-27', '2023-09-28', '2023-10-02', '2023-10-03', '2024-01-02']),
        label_mature_date=pd.to_datetime(['2023-09-29', '2023-10-02', '2023-12-29', '2024-01-01', None]),
        label_qualified=[True, True, True, True, False], target=[1., 0., 1., 0., np.nan], sample_id=list('abcde')))
    fold = dict(year=2024, cutoff_exclusive=pd.Timestamp('2024-01-01'), calibration_start=pd.Timestamp('2023-10-02'), calibration_sessions=pd.to_datetime(['2023-10-02', '2023-10-03']))
    train, calibration, inference = decision.split_sample(frame, fold)
    assert train.sample_id.tolist() == ['a']
    assert calibration.sample_id.tolist() == ['c']
    assert inference.sample_id.tolist() == ['e'] and inference.target.isna().all()


def test_frozen_slots_and_account_candidates_do_not_reset_history_or_activate_accounts():
    spec = decision.specification()
    assert sum(slot['stage'] == 'R6' for slot in spec['schedule']) == 45
    assert sum(slot['stage'] == 'R7' for slot in spec['schedule']) == 9
    assert len({slot['slot_id'] for slot in spec['schedule']}) == 54
    assert len(spec['R6_future_account_candidates']) == 15
    assert len(spec['R7_future_account_candidates']) == 3
    assert spec['budget']['prior_model_year_exposure'] == 201
    assert spec['budget']['prior_physical_fits'] == 455
    assert spec['budget']['scientific_retry'] == 0
    assert spec['budget']['new_account_paths_authorized'] == 0
    assert spec['2026_locked'] is True and spec['source_activated'] is False and spec['Branch_N_adopted'] is False
    for key, fallback in [('R6_future_account_candidates', 'REFERENCE_NO_R6_MODEL'), ('R7_future_account_candidates', 'REFERENCE_NO_R7_MODEL')]:
        candidates = spec[key]
        assert [c['order'] for c in candidates] == list(range(1, len(candidates) + 1))
        assert all(c['year_2023'] == fallback and c['failure_replacement'] is False and c['friction_bps'] == 10 for c in candidates)
        assert all(c['account_status'] == 'NOT_AUTHORIZED_SOURCE_UNBOUND' for c in candidates)

@pytest.mark.parametrize('objective', ['buy', 'hold'])
def test_half_probability_keeps_declared_buy_hold_reference(monkeypatch, objective):
    from types import SimpleNamespace
    pred, labels, calendar = synthetic_panel()
    samples, _ = decision.build_samples(pred, labels, calendar)
    frame = samples[objective].iloc[:3].copy()
    model = SimpleNamespace(objective=objective)
    monkeypatch.setattr(decision.models, 'predict', lambda m, x: {'p_superior': np.full(len(x), .5)})
    out = decision._publication(model, frame, decision.SINGLE)
    assert out.action.eq(1).all() and out.reference_action.eq(1).all()


def test_distribution_replace_uses_same_model_and_strict_native_tail_margin(monkeypatch):
    from types import SimpleNamespace
    pred, labels, calendar = synthetic_panel()
    samples, _ = decision.build_samples(pred, labels, calendar)
    frame = samples['replace'].loc[samples['replace'].signal_date.eq(calendar[1])].copy()
    assert len(frame) == 2
    model = SimpleNamespace(objective='distribution')
    seen = []
    k = .999 / 1.001
    def native_prediction(m, x):
        seen.append(m)
        if len(seen) == 1:
            return {'q10': np.array([0., .05])}
        return {'q90': np.array([k - 1., k - 1.])}
    monkeypatch.setattr(decision.models, 'predict', native_prediction)
    out = decision.distribution_replace_publication(model, frame)
    assert seen == [model, model]
    assert out.tail_replace_margin.iloc[0] == 0.
    assert out.tail_replace_margin.iloc[1] > 0
    assert out.action.tolist() == [0, 1] and out.reference_action.eq(0).all()
    assert out.sample_id.tolist() == frame.sample_id.tolist()
    np.testing.assert_array_equal(out.edge, frame.edge)


def test_native_publication_adds_no_new_model_or_fit_slot():
    spec = decision.specification()
    fit_units = spec['model_specifications']['fit_units']
    totals = {'R6': 0, 'R7': 0}
    for slot in spec['schedule']:
        family = 'distribution' if slot['objective'] == 'distribution' else 'classification'
        totals[slot['stage']] += fit_units[family][slot['learner']]
    assert totals == {'R6': 81, 'R7': 15}
    assert spec['budget']['R6_physical_fit_cap'] == totals['R6']
    assert spec['budget']['R7_physical_fit_cap'] == totals['R7']
    assert spec['model_specifications']['calibrator_fits'] == 0
