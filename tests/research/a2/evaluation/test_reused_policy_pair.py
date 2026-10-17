"""Synthetic axis, source binding and private CA-clock counterexamples.

No market cache, trained state, prediction artifact, account result, or 2026
observation is opened. Values below are hand-constructed context fixtures.
"""
from dataclasses import fields

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation.continuous_research_account import PersistentPolicyContext
from scripts.research.a2.evaluation.reused_policy_pair import restrict_context
from scripts.research.a2.inference.reused_feasible_policy import (
    feasible_capacity, feasible_target, required_mask,
)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext


def fixture_context():
    return AccountContext(
        signal_index=12, signal_date=pd.Timestamp('2024-05-06'),
        signal_asof=pd.Timestamp('2024-05-06T20:00:00Z'), path_ids=('SYNTHETIC_PAIR',),
        tickers=np.array(['AAA', 'BBB', 'CCC', 'DDD', 'EEE']),
        current_units=np.array([[1., 2., 0., 0., 0.]]),
        current_weights=np.array([[.08, .12, 0., 0., 0.]]),
        cash=np.array([900.]), cash_weight=np.array([.3]), nav=np.array([3000.]),
        reserved_mask=np.array([[False, True, False, False, False]]),
        reserved_weight=np.array([.12]), reserved_slots=np.array([1]),
        available_budget=np.array([.88]), available_slots=np.array([19]),
        buy_allowed=np.array([[True, False, True, False, True]]),
        sell_restricted=np.array([[False, True, False, False, False]]),
        input_present=np.array([[True, True, True, False, True]]),
        decision_mask=np.array([[True, False, True, False, True]]),
        operational_mask=np.array([[False, False, False, True, False]]),
        max_positions=20, max_weight=.1, max_invested=1.,
    )


def test_ordered_axis_projection_preserves_all_account_scalars_and_masks():
    ctx = fixture_context()
    columns = np.array([4, 1, 0, 2])
    pool = np.array([True, False, True, False, True])
    narrow = restrict_context(ctx, columns, pool)
    np.testing.assert_array_equal(narrow.tickers, ['EEE', 'BBB', 'AAA', 'CCC'])
    for field in fields(ctx):
        value = getattr(ctx, field.name)
        actual = getattr(narrow, field.name)
        if field.name == 'tickers':
            continue
        if field.name in ('decision_mask', 'buy_allowed'):
            np.testing.assert_array_equal(actual, value[:, columns] & pool[columns][None, :])
        elif isinstance(value, np.ndarray) and value.shape == (1, len(ctx.tickers)):
            np.testing.assert_array_equal(actual, value[:, columns])
        elif isinstance(value, np.ndarray):
            np.testing.assert_array_equal(actual, value)
        else:
            assert actual == value


def test_persistent_wrapper_transports_actual_raw_shares_after_ca():
    ctx = fixture_context()
    actual_units = ctx.current_units * np.array([[2., 3., 1., 1., 1.]])
    persistent = PersistentPolicyContext(
        ctx, np.array([[3, 8, -1, -1, -1]]),
        np.full((1, 5), np.datetime64('2024-04-01')),
        np.full((1, 5), 20.), np.full((1, 5), 21.), actual_units,
        receivable_value_usd=np.array([1500.]), accounting_qualified=np.array([True]),
    )
    columns = np.array([1, 4, 0, 2])
    narrow = restrict_context(persistent, columns, np.array([True, False, True, False, True]))
    np.testing.assert_array_equal(narrow.current_units, actual_units[:, columns])
    np.testing.assert_array_equal(narrow.current_weights, ctx.current_weights[:, columns])
    np.testing.assert_array_equal(narrow.cash, ctx.cash)
    np.testing.assert_array_equal(narrow.nav, ctx.nav)
    assert feasible_capacity(narrow)['spendable_budget'] == pytest.approx(.5)


def test_outpool_actual_holding_stays_required_and_locked_not_dropped():
    ctx = fixture_context()
    columns = np.array([2, 1, 0, 4])
    narrow = restrict_context(ctx, columns, np.array([True, False, True, False, True]))
    b = list(narrow.tickers).index('BBB')
    assert narrow.current_units[0, b] == 2.
    assert narrow.current_weights[0, b] == .12
    assert narrow.reserved_mask[0, b]
    assert not narrow.decision_mask[0, b]
    assert not narrow.buy_allowed[0, b]
    assert required_mask(narrow)[b]
    assert feasible_capacity(narrow)['locked'][b]


def test_source_pool_cannot_create_decision_buy_permission_or_change_context():
    ctx = fixture_context()
    originals = {f.name: getattr(ctx, f.name).copy() for f in fields(ctx)
                 if isinstance(getattr(ctx, f.name), np.ndarray)}
    columns = np.arange(5)
    narrow = restrict_context(ctx, columns, np.ones(5, bool))
    assert not narrow.decision_mask[0, 3]
    assert not narrow.buy_allowed[0, 3]
    assert narrow.operational_mask[0, 3]
    narrow.current_units[0, 0] = 99.
    narrow.decision_mask[0, 0] = False
    for name, value in originals.items():
        np.testing.assert_array_equal(getattr(ctx, name), value)


@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_all_cash_zero_eligible_is_valid_zero_stock_target(kind):
    ctx = fixture_context()
    from dataclasses import replace
    ctx = replace(ctx, current_units=np.zeros((1, 5)), current_weights=np.zeros((1, 5)),
                  cash=np.array([3000.]), cash_weight=np.array([1.]),
                  reserved_mask=np.zeros((1, 5), bool), reserved_weight=np.array([0.]),
                  reserved_slots=np.array([0]), available_budget=np.array([1.]),
                  available_slots=np.array([20]))
    narrow = restrict_context(ctx, np.arange(5), np.zeros(5, bool))
    result = feasible_target(kind, np.full(5, np.nan), np.full(5, np.nan), np.eye(5),
                             narrow, covariance_psd_qualified=True)
    assert required_mask(narrow).sum() == 0
    assert result.target.weights.sum() == 0
    assert result.receipt['maximum_feasible_gross'] == 0
    assert result.receipt['residual_cash_weight'] == 1

@pytest.mark.parametrize('kind', ['SIMPLE_FEASIBLE', 'JOINT_REUSE'])
def test_empty_required_axis_from_risk_provider_is_valid_all_cash(kind):
    from dataclasses import replace
    ctx = fixture_context()
    ctx = replace(ctx, current_units=np.zeros((1, 5)), current_weights=np.zeros((1, 5)),
                  cash=np.array([3000.]), cash_weight=np.array([1.]),
                  reserved_mask=np.zeros((1, 5), bool), reserved_weight=np.array([0.]),
                  reserved_slots=np.array([0]), available_budget=np.array([1.]),
                  available_slots=np.array([20]))
    narrow = restrict_context(ctx, np.array([], dtype=int), np.zeros(5, bool))
    assert narrow.current_units.shape == (1, 0)
    result = feasible_target(kind, np.array([]), np.array([]), np.empty((0, 0)),
                             narrow, covariance_psd_qualified=True)
    assert result.target.weights.shape == (1, 0)
    assert result.target.explicit_mask.shape == (1, 0)
    assert result.receipt['required_asset_count'] == 0
    assert result.receipt['maximum_feasible_gross'] == 0
    assert result.receipt['residual_cash_weight'] == 1


@pytest.fixture(scope='module')
def frozen_ca_owner():
    from pathlib import Path
    from scripts.research.a2.evaluation.reused_policy_pair import module
    path = Path('D:/us-tech-quant-cache/V24/V24_B_FROZEN_HISTORY_JOINT_POLICY_RESEARCH_R1/source_audit/frozen_owner_loader.py')
    return module(path, '_synthetic_pair_exact_frozen_ca').load_owner()


def clone_function(function, **updates):
    from types import FunctionType
    clone = FunctionType(function.__code__, dict(function.__globals__, **updates),
                         function.__name__, function.__defaults__, function.__closure__)
    clone.__kwdefaults__ = function.__kwdefaults__
    return clone


def synthetic_cash_event(owner, **updates):
    ca = owner._frozen_ca_module
    values = dict(event_id='SYNTHETIC_ORDINARY_CASH', action_type='CASH_DIVIDEND',
        old_security_id='SYNTHETIC:AAA', ticker='AAA', ex_date='2023-01-19',
        record_date='2023-01-20', pay_date='2023-02-17',
        available_at='2022-12-16T00:00:00+00:00', cash_per_old_share=2., currency='USD',
        amount_unit=ca.USD_PER_RAW_OLD_SHARE, quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        source_type='TIER1_ISSUER_REGULATOR_EXCHANGE',
        source_reference='https://synthetic.invalid/ordinary-cash', source_fingerprint='a'*64)
    values.update(updates)
    return owner.SourceBackedEntitlementEvent(**values)


def apply_synthetic_session(owner, lifecycle, events, day, *, state=None, cash=100., positions=None):
    timestamp = pd.Timestamp(day)
    open_at = (timestamp + pd.Timedelta(hours=9, minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
    return lifecycle(events, positions if positions is not None else {'SYNTHETIC:AAA': 10.}, cash,
        execution_date=timestamp, session_open_at=open_at,
        security_tickers={e.old_security_id: e.ticker for e in events},
        quantity_coordinate=owner._frozen_ca_module.RAW_OLD_SHARE_COORDINATE,
        state=state, enabled=True)


@pytest.mark.parametrize('pay_date,next_session', [
    ('2023-02-16', '2023-02-17'),  # Weekday payment: cash starts the following session.
    ('2023-02-17', '2023-02-21'),  # Friday plus the supplied calendar's holiday/weekend gap.
    ('2023-02-18', '2023-02-21'),  # Weekend issuer pay date: no invented weekend account session.
])
def test_ordinary_cash_pay_day_end_and_after_sale_entitlement(frozen_ca_owner, pay_date, next_session):
    from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle, CASH_CLOCK
    owner = frozen_ca_owner
    event = synthetic_cash_event(owner, pay_date=pay_date)
    original_fingerprint = event.event_fingerprint
    lifecycle, receipt = ordinary_cash_lifecycle(owner, {'entitlement_events': (event,)},
                                                [original_fingerprint], clone=clone_function)
    ex = apply_synthetic_session(owner, lifecycle, (event,), event.ex_date)
    assert ex.cash == 100. and ex.receivable_value_usd == 20.
    assert ex.accounting_qualified
    # A later sale does not erase the ex-pretrade snapshot or the nonspendable claim.
    before = pay_date if pd.Timestamp(pay_date).weekday() < 5 else '2023-02-17'
    unpaid = apply_synthetic_session(owner, lifecycle, (event,), before,
                                    state=ex.state, cash=ex.cash, positions={event.old_security_id: 0.})
    assert unpaid.cash == 100. and unpaid.receivable_value_usd == 20.
    assert not any(r['phase'] == 'CASH_PAID' for r in unpaid.records)
    paid = apply_synthetic_session(owner, lifecycle, (event,), next_session,
                                  state=unpaid.state, cash=unpaid.cash, positions={event.old_security_id: 0.})
    assert paid.cash == 120. and paid.receivable_value_usd == 0.
    assert [r['session'] for r in paid.records if r['phase'] == 'CASH_PAID'] == [next_session]
    assert paid.state.paid_event_ids == (event.event_id,)
    assert event.pay_date == pay_date and event.event_fingerprint == original_fingerprint
    assert receipt['convention'] == CASH_CLOCK
    assert receipt['events'][0]['issuer_pay_date'] == pay_date
    assert receipt['events'][0]['broker_cash_available_at'] == 'UNKNOWN'
    assert ex.state.receivables[0].pay_date == str((pd.Timestamp(pay_date)+pd.Timedelta(days=1)).date())


def test_unapproved_cash_dividend_keeps_original_pay_day(frozen_ca_owner):
    from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle
    owner = frozen_ca_owner
    event = synthetic_cash_event(owner)
    original = owner.apply_entitlement_lifecycle
    helper = original.__globals__['_entitlement_pay_date']
    lifecycle, receipt = ordinary_cash_lifecycle(owner, {'entitlement_events': (event,)}, [], clone=clone_function)
    ex = apply_synthetic_session(owner, lifecycle, (event,), event.ex_date)
    pay = apply_synthetic_session(owner, lifecycle, (event,), event.pay_date, state=ex.state, cash=ex.cash)
    assert pay.cash == 120. and pay.receivable_value_usd == 0.
    assert receipt['events'] == []
    assert lifecycle.__code__ is original.__code__
    assert original.__globals__['_entitlement_pay_date'] is helper
    assert helper(event) == event.pay_date


@pytest.mark.parametrize('scope', ['MKFG', 'CASH_DISTRIBUTION', 'prewindow'])
def test_ordinary_clock_rejects_unverified_family_or_scope(frozen_ca_owner, scope):
    from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle
    updates = {'ticker': 'MKFG'} if scope == 'MKFG' else (
        {'action_type': 'CASH_DISTRIBUTION'} if scope == 'CASH_DISTRIBUTION' else
        {'ex_date': '2022-12-20', 'record_date': '2022-12-21'})
    event = synthetic_cash_event(frozen_ca_owner, **updates)
    with pytest.raises(ValueError, match='PAIR_ORDINARY_CASH_CLOCK_SCOPE_REQUIRED'):
        ordinary_cash_lifecycle(frozen_ca_owner, {'entitlement_events': (event,)},
                                [event.event_fingerprint], clone=clone_function)


def test_terminal_mkfg_unknown_settlement_stays_original_nonspendable(frozen_ca_owner):
    from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle
    owner, ca = frozen_ca_owner, frozen_ca_owner._frozen_ca_module
    event = owner.SourceBackedTerminalEvent(event_id='SYNTHETIC_MKFG_TERMINAL',
        old_security_id='SYNTHETIC:MKFG', ticker='MKFG', effective_at='2023-01-19T13:00:00Z',
        available_at='2023-01-18T00:00:00Z', cash_per_old_share=2., currency='USD',
        amount_unit=ca.USD_PER_RAW_OLD_SHARE, quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        quantity_source_reference='https://synthetic.invalid/raw-quantity', quantity_source_fingerprint='b'*64,
        source_type='TIER1_ISSUER_REGULATOR_EXCHANGE', source_reference='https://synthetic.invalid/terminal',
        source_fingerprint='c'*64)
    with pytest.raises(ValueError, match='PAIR_ORDINARY_CASH_CLOCK_SCOPE_REQUIRED'):
        ordinary_cash_lifecycle(owner, {'entitlement_events': (event,)},
                                [event.event_fingerprint], clone=clone_function)
    lifecycle, receipt = ordinary_cash_lifecycle(owner, {'entitlement_events': (event,)}, [], clone=clone_function)
    ex = apply_synthetic_session(owner, lifecycle, (event,), '2023-01-19', positions={event.old_security_id: 10.})
    later = apply_synthetic_session(owner, lifecycle, (event,), '2023-02-21',
                                   state=ex.state, cash=ex.cash, positions=ex.positions)
    assert ex.positions[event.old_security_id] == 0.
    assert ex.state.receivables[0].pay_date is None
    assert later.cash == 100. and later.receivable_value_usd == 20.
    assert not any(r['phase'] == 'CASH_PAID' for r in later.records)
    assert receipt['terminal_and_MKFG_rule'] == 'ORIGINAL_UNCHANGED'


def test_account_source_descendant_cannot_clear_original_decision_quality():
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import bind_account_sources
    market = SimpleNamespace(dates=pd.to_datetime(['2023-01-18', '2023-01-19']),
        tickers=np.array(['AAA']), quality=np.zeros((2, 1), bool),
        open=np.ones((2, 1)), close=np.ones((2, 1)))
    original_events = {'unsupported_cash_events': [('2023-01-19', 'AAA', 'SYNTHETIC_DEFECT')]}
    calls = []
    def bind_original(market, events):
        calls.append('ORIGINAL_QUALITY')
        market.quality[1, 0] = bool(events['unsupported_cash_events'])
        return market
    def usable(dates, tickers, quality, decisions, **kwargs):
        calls.append('QUOTE_RULE')
        assert quality[1, 0]
        return quality.copy(), {'original_quality': quality.copy()}
    def adapter(owner, events, bundle, *, account_dates):
        calls.append('CA_SOURCE_ONLY')
        assert market.quality[1, 0]
        events['unsupported_cash_events'].clear()
        return dict(events=events, receipt={'synthetic': True}, ordinary_cash_event_fingerprints=[])
    shared = SimpleNamespace(bind_original_wrapper_quality=bind_original,
                             quote=SimpleNamespace(build_usable_a_mask=usable))
    bound_market, events, mask, _, binding = bind_account_sources(None, market, original_events, [],
        shared=shared, bundle={'synthetic': True}, adapter=adapter)
    assert calls == ['ORIGINAL_QUALITY', 'QUOTE_RULE', 'CA_SOURCE_ONLY']
    assert bound_market.quality[1, 0] and mask[1, 0]
    assert original_events['unsupported_cash_events']
    assert events['unsupported_cash_events'] == [] and binding['receipt']['synthetic']


def test_legacy_source_binding_never_calls_descendant_adapter():
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import bind_account_sources
    market = SimpleNamespace(dates=pd.to_datetime(['2023-01-18']), tickers=np.array(['AAA']),
        quality=np.ones((1, 1), bool), open=np.ones((1, 1)), close=np.ones((1, 1)))
    events = {'unsupported_cash_events': ['SYNTHETIC']}
    shared = SimpleNamespace(bind_original_wrapper_quality=lambda m,e: m,
        quote=SimpleNamespace(build_usable_a_mask=lambda *a,**k: (np.ones((1, 1), bool), {})))
    def forbidden(*args, **kwargs):
        raise AssertionError('Legacy run must not use new source adapter')
    result = bind_account_sources(None, market, events, [], shared=shared, adapter=forbidden)
    assert result[1] is events and result[-1] is None



@pytest.mark.parametrize('failure_mode', ['KNOWN_ACCOUNT_FACT', 'UNEXPECTED_LIFECYCLE_ENGINEERING'])
def test_source_descendant_execution_failure_preserves_causal_signal_and_completed_prefix(tmp_path, monkeypatch, failure_mode):
    from dataclasses import replace
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    common = replace(fixture_context(), signal_date=pd.Timestamp('2023-01-18'),
                     signal_asof=pd.Timestamp('2023-01-18T21:00:00Z'))
    ctx = PersistentPolicyContext(common, np.zeros((1, 5), int),
        np.full((1, 5), np.datetime64('2023-01-17')), np.ones((1, 5)),
        np.ones((1, 5)), common.current_units, receivable_value_usd=np.array([0.]),
        accounting_qualified=np.array([True]))
    frames, receipts = {}, {}
    def save_frame(run, label, name, frame):
        frames[name] = frame.copy()
        return {'path': 'SYNTHETIC:' + name, 'sha256': 'a'*64}
    def write(path, value):
        receipts[Path(path).name] = value
        return {'path': 'SYNTHETIC:' + Path(path).name, 'sha256': 'b'*64}
    from pathlib import Path
    monkeypatch.setattr(pair, 'write', write)
    target = SimpleNamespace(weights=np.zeros((1, 5)), explicit_mask=np.zeros((1, 5), bool))
    monkeypatch.setattr(pair, 'feasible_target', lambda *a, **k: SimpleNamespace(target=target, receipt={}))
    def account(market, paths, checked, config, *, ledger_callback, **kwargs):
        checked(ctx.signal_date, ctx)
        ledger_callback('daily', pd.DataFrame([
            dict(date=pd.Timestamp('2023-01-18'), accounting_qualified=True,
                 cash=900., nav=3000., actual_name_count=0)]))
        for name in ('orders', 'operational_actions'):
            ledger_callback(name, pd.DataFrame([dict(signal_date=pd.Timestamp('2023-01-18'),
                execution_date=pd.Timestamp('2023-01-19'), decision_id='SYNTHETIC_DECISION')]))
        ledger_callback('contexts', pd.DataFrame([dict(signal_date=pd.Timestamp('2023-01-18'),
            decision_id='SYNTHETIC_DECISION', policy_called=True)]))
        if failure_mode == 'UNEXPECTED_LIFECYCLE_ENGINEERING':
            apply_entitlement_lifecycle(execution_date=pd.Timestamp('2023-01-19'))
        else:
            ledger_callback('daily', pd.DataFrame([
                dict(date=pd.Timestamp('2023-01-19'), accounting_qualified=False,
                     cash=900., nav=3000., actual_name_count=0)]))
        raise AssertionError('Failure must stop this synthetic account')
    def unexpected_lifecycle(*args, **kwargs):
        raise TypeError('SYNTHETIC_UNEXPECTED_LIFECYCLE_FAILURE')
    owner = SimpleNamespace(run_continuous_account=account, apply_entitlement_lifecycle=unexpected_lifecycle)
    shared = SimpleNamespace(clone=clone_function)
    risk = SimpleNamespace(for_decision=lambda ctx: SimpleNamespace(columns=np.arange(5),
        pool_mask=np.ones(5, bool), covariance=np.eye(5), covariance_psd_qualified=True, source_receipt={}))
    forecasts = SimpleNamespace(for_decision=lambda *a, **k: SimpleNamespace(mean=np.zeros(5),
        uncertainty=np.ones(5), source_receipt={'required_assets': list(ctx.tickers)}))
    result = pair.execute(tmp_path, {'task_id': pair.CA_TASK}, 'SIMPLE_FEASIBLE', owner, None,
        {}, None, shared, SimpleNamespace(ACCOUNT={}, save_frame=save_frame), risk, forecasts,
        source_context={'owner_ref': {'path': 'D:/synthetic_owner.py', 'sha256': 'a'*64}})
    failure = result['first_failure']
    expected_status = ('ENGINEERING_FAILURE_REQUIRES_DIAGNOSIS' if failure_mode == 'UNEXPECTED_LIFECYCLE_ENGINEERING'
                       else 'PAIRED_POLICY_BLOCKED_REAL_INPUT')
    assert result['status'] == expected_status
    assert failure['signal_date'] == '2023-01-18'
    assert failure['execution_date'] == failure['failure_session_date'] == '2023-01-19'
    assert list(frames['daily_prefix'].date) == [pd.Timestamp('2023-01-18')]
    if failure_mode == 'KNOWN_ACCOUNT_FACT':
        assert list(frames['daily_failure_session_partial'].date) == [pd.Timestamp('2023-01-19')]
    else:
        assert 'daily_failure_session_partial' not in frames
    causal = receipts['CAUSAL_ACCOUNT_AT_FIRST_FAILURE.json']
    assert causal['failure_session'] == pd.Timestamp('2023-01-19')
    assert pd.Timestamp(causal['clock_and_checks']['policy_signal_date']) == pd.Timestamp('2023-01-18')
    if failure_mode == 'KNOWN_ACCOUNT_FACT':
        assert causal['clock_and_checks']['observation_session_date'] == pd.Timestamp('2023-01-19')
    for name in ('orders', 'operational_actions'):
        assert name + '_prefix' not in frames
        assert list(frames[name + '_failure_session_partial'].execution_date) == [pd.Timestamp('2023-01-19')]
        assert result['partial_table_clock_roles'][name]['column'] == 'execution_date'
    assert list(frames['contexts_prefix'].signal_date) == [pd.Timestamp('2023-01-18')]
    assert causal['partial_table_clock_roles']['contexts']['role'] == 'COMPLETED_DECISION_RECORD_NOT_COMPLETED_EXECUTION'


def test_failure_receipt_keeps_legacy_labels_and_does_not_invent_missing_causal_signal():
    from scripts.research.a2.evaluation.reused_policy_pair import _failure_receipt, TASK, CA_TASK
    legacy = _failure_receipt(TASK, 'SYNTHETIC', 'ACTUAL_EXECUTION_FACT_UNAVAILABLE',
        '2023-01-19', {'signal_date': '2023-01-18'}, execution_session=True)
    assert legacy['signal_date'] == '2023-01-19'
    assert 'execution_date' not in legacy and 'failure_session_date' not in legacy
    new = _failure_receipt(CA_TASK, 'SYNTHETIC', 'REQUIRED_FROZEN_INPUT_UNAVAILABLE',
        '2023-01-19', None)
    assert new['signal_date'] is None and new['failure_session_date'] == '2023-01-19'
    assert 'execution_date' not in new


# New causal-held descendant only; all values are synthetic.
def causal_fixture_domain(ctx):
    from scripts.research.a2.inference.reused_r5_risk_inputs import causal_held_domain
    pool = np.array([False, False, True, False, True])
    result = causal_held_domain(ctx, pool)
    result['pool_mask'] = pool
    result['receipt'] = {'schema': 'SYNTHETIC_QUALIFIED_E_AND_ACTUAL_H',
                         'identity_qualified': True, 'historical_availability_authority': 'UNKNOWN'}
    return result


def test_causal_projection_keeps_outpool_held_management_without_buy_or_new_lock():
    from scripts.research.a2.evaluation.reused_policy_pair import restrict_causal_context
    ctx = fixture_context()
    domain = causal_fixture_domain(ctx)
    narrow = restrict_causal_context(ctx, domain)
    assert list(narrow.tickers) == ['AAA', 'BBB', 'CCC', 'EEE']
    assert narrow.current_units[0, 0] == 1.
    assert narrow.decision_mask[0, 0] and not narrow.buy_allowed[0, 0]
    assert not feasible_capacity(narrow)['locked'][0]
    assert narrow.reserved_mask[0, 1] and not narrow.decision_mask[0, 1]
    assert feasible_capacity(narrow)['locked'][1]
    np.testing.assert_array_equal(narrow.cash, ctx.cash)
    np.testing.assert_array_equal(narrow.nav, ctx.nav)
    assert ctx.decision_mask[0, 0] and ctx.buy_allowed[0, 0]


@pytest.mark.parametrize('defect', ['DROP_ACTUAL_H', 'NEW_HELD_LOCK', 'REOPEN_OUTPOOL_BUY'])
def test_causal_projection_refuses_missing_held_and_invented_action_masks(defect):
    from scripts.research.a2.evaluation.reused_policy_pair import restrict_causal_context
    ctx = fixture_context()
    domain = causal_fixture_domain(ctx)
    if defect == 'DROP_ACTUAL_H':
        domain['columns'] = np.array([1, 2, 4])
        domain['assets'] = ('BBB', 'CCC', 'EEE')
    elif defect == 'NEW_HELD_LOCK':
        domain['decision_mask'] = domain['decision_mask'].copy()
        domain['decision_mask'][0] = False
    else:
        domain['buy_allowed'] = domain['buy_allowed'].copy()
        domain['buy_allowed'][0] = True
    with pytest.raises(ValueError, match='CAUSAL_DOMAIN_DROPPED_REQUIRED_HELD_OR_CHANGED_ACTION_MASK'):
        restrict_causal_context(ctx, domain)


def causal_fake_inputs(ctx, *, refuse_numeric=False):
    from types import SimpleNamespace
    domain = causal_fixture_domain(ctx)
    calls = []
    class Risk:
        def qualified_causal_domain(self, actual):
            assert actual is ctx
            calls.append('qualified_domain')
            return domain
        def for_required_domain(self, actual, required):
            assert actual is ctx and required is domain
            calls.append('numeric_risk')
            if refuse_numeric:
                raise AssertionError('SIMPLE_MUST_NEVER_REQUEST_NUMERIC_RISK')
            return SimpleNamespace(assets=domain['assets'], columns=domain['columns'],
                covariance=np.eye(len(domain['assets']))*.01,
                covariance_psd_qualified=True, source_receipt={'schema': 'SYNTHETIC_EXACT_D_RISK'})
        def note_qualified_decision(self, actual, required):
            assert actual is ctx and required is domain
            calls.append('note_candidate_only')
        def observe_fills(self, frame):
            calls.append('actual_fills')
    def forecast(day, assets, eligible, units, *, decision_as_of, held_weights):
        calls.append('forecast')
        assert tuple(assets) == domain['assets']
        np.testing.assert_array_equal(eligible, [False, False, True, True])
        np.testing.assert_array_equal(units, [1., 2., 0., 0.])
        np.testing.assert_array_equal(held_weights, [.08, .12, 0., 0.])
        return SimpleNamespace(assets=tuple(assets), mean=np.arange(len(assets), dtype=float),
            uncertainty=np.ones(len(assets)), source_receipt={'required_assets': list(assets)})
    return Risk(), SimpleNamespace(for_decision=forecast), calls, domain


def test_causal_simple_never_calls_numeric_risk_and_retains_common_identity_forecast():
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision
    ctx = fixture_context()
    risk, forecasts, calls, domain = causal_fake_inputs(ctx, refuse_numeric=True)
    prepared = causal_policy_decision('SIMPLE_FEASIBLE', ctx, risk, forecasts)
    assert calls == ['qualified_domain', 'forecast', 'note_candidate_only']
    assert prepared['domain_receipt'] == domain['receipt']
    assert prepared['risk_receipt']['numeric_state_loaded'] is False
    assert prepared['result'].target.explicit_mask[0, 0]
    assert prepared['result'].target.weights[0, 0] <= ctx.current_weights[0, 0]


def test_causal_joint_consumes_only_exact_common_required_axis():
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision
    ctx = fixture_context()
    risk, forecasts, calls, domain = causal_fake_inputs(ctx)
    prepared = causal_policy_decision('JOINT_REUSE', ctx, risk, forecasts)
    assert calls == ['qualified_domain', 'forecast', 'numeric_risk', 'note_candidate_only']
    np.testing.assert_array_equal(prepared['columns'], domain['columns'])
    assert prepared['risk_receipt']['schema'] == 'SYNTHETIC_EXACT_D_RISK'


def test_causal_forecast_failure_does_not_note_candidate_admission():
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision
    from scripts.research.a2.inference.reused_policy_inputs import OpportunityInputUnavailable
    ctx = fixture_context()
    risk, _, calls, _ = causal_fake_inputs(ctx, refuse_numeric=True)
    def missing(*args, **kwargs):
        raise OpportunityInputUnavailable('SYNTHETIC_REQUIRED_KEY_MISSING')
    with pytest.raises(OpportunityInputUnavailable):
        causal_policy_decision('SIMPLE_FEASIBLE', ctx, risk, SimpleNamespace(for_decision=missing))
    assert calls == ['qualified_domain']


def test_causal_runtime_acceptance_gate_rejects_missing_or_unsigned_real_refs(monkeypatch):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    seen = []
    monkeypatch.setattr(pair, 'pin', lambda ref: seen.append(ref) or Path(ref['path']))
    with pytest.raises(ValueError, match='CAUSAL_ACTUAL_INPUT_REFERENCE_REQUIRED'):
        pair.guard_causal_input_freeze({})
    freeze = {key: {'path': 'D:/SYNTHETIC/'+key+'.json', 'sha256': 'a'*64}
              for key in pair.CAUSAL_INPUT_REFS}
    freeze['causal_lw_reuse_rule'] = 'SYNTHETIC_DECLARATION'
    monkeypatch.setattr(pair, 'read', lambda path: {'schema': 'B_CAUSAL_HELD_RUNTIME_INDEPENDENT_ACCEPTANCE_V1',
        'status': 'PASS_SOURCE_RUNTIME_READY_FOR_PAIRED_REPLAY', 'independent': False})
    with pytest.raises(ValueError, match='CAUSAL_INDEPENDENT_RUNTIME_ACCEPTANCE_REQUIRED'):
        pair.guard_causal_input_freeze(freeze)
    assert len(seen) == 6


def test_causal_input_factory_creates_independent_books_for_two_accounts():
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    shared = object()
    seen = []
    def factory(**kwargs):
        assert kwargs['base_shared'] is shared
        seen.append(kwargs)
        return SimpleNamespace(account_id=kwargs['account_id'], book={})
    market = SimpleNamespace(dates=pd.date_range('2023-01-03', periods=2), tickers=['AAA'])
    first = pair.make_causal_input_adapter({}, shared, 'SIMPLE', market, factory=factory)
    second = pair.make_causal_input_adapter({}, shared, 'JOINT', market, factory=factory)
    first.book['AAA'] = 'actual-own-fill'
    assert not second.book
    assert [row['account_id'] for row in seen] == ['SIMPLE', 'JOINT']


def test_causal_execute_forwards_only_actual_owner_raw_fills_after_qualified_decision(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    common = fixture_context()
    ctx = PersistentPolicyContext(common, np.zeros((1, 5), int),
        np.full((1, 5), np.datetime64('2024-05-03')), np.ones((1, 5)),
        np.ones((1, 5)), common.current_units,
        receivable_value_usd=np.array([0.]), accounting_qualified=np.array([True]))
    risk, forecasts, calls, _ = causal_fake_inputs(ctx, refuse_numeric=True)
    observed = []
    def observe(frame):
        calls.append('actual_fills')
        observed.append(frame.copy())
    risk.observe_fills = observe
    saved = {}
    def save_frame(run, label, name, frame):
        saved[name] = frame.copy()
        return {'path': 'SYNTHETIC:'+name, 'sha256': 'a'*64}
    monkeypatch.setattr(pair, 'write', lambda path, value: {'path': 'SYNTHETIC:'+Path(path).name, 'sha256': 'b'*64})
    def account(market, paths, checked, config, *, ledger_callback, **kwargs):
        checked(ctx.signal_date, ctx)
        ledger_callback('execution_results', pd.DataFrame([dict(status='REJECTED', reason='CAPACITY_LIMITED',
            signal_date=ctx.signal_date, execution_date=pd.Timestamp('2024-05-07'), ticker='EEE')]))
        ledger_callback('fills', pd.DataFrame([dict(path_id=paths[0], order_id='SYNTHETIC_REAL_FILL',
            signal_date=ctx.signal_date, execution_date=pd.Timestamp('2024-05-07'), ticker='CCC', side='BUY',
            fractional_shares=2., index_units_before=0., index_units_after=2.,
            engine_index_units_before=0., engine_index_units_after=1., quantity_coordinate_factor=2.)]))
        ledger_callback('daily', pd.DataFrame([dict(date=pd.Timestamp('2024-05-07'),
            accounting_qualified=False, cash=900., nav=3000., actual_name_count=1)]))
        raise AssertionError('Synthetic first failure must stop the path')
    owner = SimpleNamespace(run_continuous_account=account, apply_entitlement_lifecycle=lambda *a, **k: None,
        apply_transition_to_positions=lambda *a, **k: (None, None, None))
    result = pair.execute(tmp_path, {'task_id': pair.CAUSAL_HELD_TASK}, 'SIMPLE_FEASIBLE',
        owner, None, {}, None, SimpleNamespace(clone=clone_function),
        SimpleNamespace(ACCOUNT={}, save_frame=save_frame), risk, forecasts,
        source_context={'owner_ref': {'path': 'D:/synthetic_owner.py', 'sha256': 'a'*64}})
    assert calls == ['qualified_domain', 'forecast', 'note_candidate_only', 'actual_fills']
    assert len(observed) == 1
    assert observed[0].fractional_shares.iloc[0] == 2.
    assert observed[0].engine_index_units_after.iloc[0] == 1.
    assert result['status'] == 'PAIRED_POLICY_BLOCKED_REAL_INPUT'
    assert result['first_failure']['signal_date'] == '2024-05-06'
    assert result['first_failure']['execution_date'] == '2024-05-07'
    assert not result['full_window_completed']



def test_causal_physical_load_totals_do_not_double_count_shared_original_loader():
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import causal_adapter_load_totals
    base = SimpleNamespace(loads_count=5)
    paths = [SimpleNamespace(loads_count=999, supplemental_loads_count=2),
             SimpleNamespace(loads_count=999, supplemental_loads_count=3)]
    assert causal_adapter_load_totals(base, paths) == {
        'physical_existing_state_loads': 5, 'physical_supplemental_state_loads': 5,
        'physical_risk_state_loads_total': 10}


@pytest.mark.parametrize('phase', ['DOMAIN', 'FILL'])
def test_causal_typed_held_failure_preserves_source_status_and_actual_failure_clock(tmp_path, monkeypatch, phase):
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    from scripts.research.a2.inference.reused_r5_risk_inputs import HeldLineageUnavailable
    common = fixture_context()
    ctx = PersistentPolicyContext(common, np.zeros((1, 5), int),
        np.full((1, 5), np.datetime64('2024-05-03')), np.ones((1, 5)),
        np.ones((1, 5)), common.current_units,
        receivable_value_usd=np.array([0.]), accounting_qualified=np.array([True]))
    risk, forecasts, _, _ = causal_fake_inputs(ctx, refuse_numeric=True)
    def missing(*args):
        raise HeldLineageUnavailable('SYNTHETIC_HELD_SOURCE_MISSING', asset='CCC')
    if phase == 'DOMAIN': risk.qualified_causal_domain = missing
    else: risk.observe_fills = missing
    monkeypatch.setattr(pair, 'write', lambda path, value: {'path': 'SYNTHETIC:'+Path(path).name, 'sha256': 'b'*64})
    def account(market, paths, checked, config, *, ledger_callback, **kwargs):
        checked(ctx.signal_date, ctx)
        ledger_callback('fills', pd.DataFrame([dict(path_id=paths[0], order_id='SYNTHETIC_FILL',
            signal_date=ctx.signal_date, execution_date=pd.Timestamp('2024-05-07'), ticker='CCC', side='BUY',
            fractional_shares=2., index_units_before=0., index_units_after=2.)]))
        raise AssertionError('Typed source failure must stop this path')
    owner = SimpleNamespace(run_continuous_account=account, apply_entitlement_lifecycle=lambda *a, **k: None,
        apply_transition_to_positions=lambda *a, **k: (None, None, None))
    parent = SimpleNamespace(ACCOUNT={}, save_frame=lambda run,label,name,frame: {'path': 'SYNTHETIC:'+name, 'sha256':'a'*64})
    result = pair.execute(tmp_path, {'task_id': pair.CAUSAL_HELD_TASK}, 'SIMPLE_FEASIBLE',
        owner, None, {}, None, SimpleNamespace(clone=clone_function), parent, risk, forecasts,
        source_context={'owner_ref': {'path': 'D:/synthetic_owner.py', 'sha256': 'a'*64}})
    failure = result['first_failure']
    assert result['status'] == 'PAIRED_POLICY_BLOCKED_REAL_INPUT'
    assert failure['reason'] == 'REQUIRED_HELD_IDENTITY_UNAVAILABLE'
    assert failure['source_failure_type'] == 'HeldLineageUnavailable'
    assert failure['source_receipt']['status'] == 'BLOCKED_REQUIRED_HELD_IDENTITY'
    assert failure['signal_date'] == '2024-05-06'
    if phase == 'FILL':
        assert failure['failure_session_date'] == failure['execution_date'] == '2024-05-07'
    else:
        assert failure['failure_session_date'] == '2024-05-06'
        assert 'execution_date' not in failure


def test_causal_joint_axis_mismatch_is_engineering_and_never_commits_candidate():
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision
    ctx = fixture_context()
    risk, forecasts, calls, domain = causal_fake_inputs(ctx)
    risk.for_required_domain = lambda *a: SimpleNamespace(assets=tuple(reversed(domain['assets'])),
        columns=domain['columns'], covariance=np.eye(4), covariance_psd_qualified=True, source_receipt={})
    with pytest.raises(ValueError, match='CAUSAL_JOINT_RISK_REQUIRED_AXIS_CHANGED'):
        causal_policy_decision('JOINT_REUSE', ctx, risk, forecasts)
    assert 'note_candidate_only' not in calls


def test_causal_unit_observer_keeps_original_result_and_labels_unit_commitment():
    from types import SimpleNamespace
    from copy import deepcopy
    from scripts.research.a2.evaluation.reused_policy_pair import causal_unit_transition_observer
    record = dict(event_fingerprint='fp', effective_date=pd.Timestamp('2024-05-07'),
        action_type='SPLIT', old_ticker='AAA', new_ticker='AAA', old_security_id='SID',
        new_security_id='SID', source_reference='D:/synthetic_typed.json',
        source_fingerprint='b'*64, old_quantity=1., new_quantity=2., quantity_multiplier=2.,
        timing_rule='BEFORE_EFFECTIVE_SESSION_MARK_AND_BEFORE_TRADES', cash_delta=0.)
    returned = ({'AAA': 2.}, 0., record)
    calls, observed = [], []
    def original(*args):
        calls.append(args)
        return returned
    def observe(payload):
        observed.append(deepcopy(payload))
        payload['owner_ref']['sha256'] = '0'*64
        payload['unit_after_quantity'] = 999.
    owner_ref = {'path': 'D:/synthetic_owner.py', 'sha256': 'a'*64}
    wrapper = causal_unit_transition_observer(original,
        {'corporate_action_known_at': {'fp': pd.Timestamp('2024-05-06T12:00Z')}}, owner_ref, observe)
    event = SimpleNamespace(event_fingerprint='fp')
    positions = {'AAA': 1.}
    assert wrapper(event, positions, 0., pd.Timestamp('2024-05-07')) is returned
    assert len(calls) == 1 and calls[0][1] is positions
    assert returned[0] == {'AAA': 2.} and record['new_quantity'] == 2.
    assert owner_ref['sha256'] == 'a'*64
    payload = observed[0]
    assert payload['quantity_coordinate'] == 'ORIGINAL_OWNER_UNIT_FACTOR_COMMITMENT'
    assert payload['role'] == 'UNIT_COORDINATE_APPLIED'
    assert 'before_raw_quantity' not in payload and 'after_raw_quantity' not in payload
    assert 'cash_delta' not in payload


def test_causal_unit_observer_never_relabels_no_effect_or_swallows_observer_failure():
    from scripts.research.a2.evaluation.reused_policy_pair import causal_unit_transition_observer
    from scripts.research.a2.inference.reused_r5_risk_inputs import HeldLineageUnavailable
    seen = []
    wrapper = causal_unit_transition_observer(lambda *a: ({}, 0., None), {}, {}, seen.append)
    assert wrapper(None, {}, 0., pd.Timestamp('2024-05-07')) == ({}, 0., None)
    assert seen == []
    record = dict(event_fingerprint='fp', effective_date=pd.Timestamp('2024-05-07'),
        action_type='SPLIT', old_ticker='AAA', new_ticker='AAA', old_security_id='SID',
        new_security_id='SID', source_reference='D:/typed', source_fingerprint='b'*64,
        old_quantity=1., new_quantity=2., quantity_multiplier=2., timing_rule='PRE_OPEN')
    calls = []
    def original(*args):
        calls.append('original')
        return {'AAA': 2.}, 0., record
    def failed(payload):
        raise HeldLineageUnavailable('SYNTHETIC_OBSERVER_SOURCE_CONFLICT')
    wrapper = causal_unit_transition_observer(original, {}, {}, failed)
    with pytest.raises(HeldLineageUnavailable, match='OBSERVER_SOURCE_CONFLICT'):
        wrapper(None, {'AAA': 1.}, 0., pd.Timestamp('2024-05-07'))
    assert calls == ['original']


def test_causal_lifecycle_transport_is_direct_quantity_only_and_no_split_after_fabrication():
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import causal_lifecycle_quantity_payload
    before = {'SID_A': 7., 'SID_B': 3.}
    after = {'SID_A': 7., 'SID_B': 0.}
    result = SimpleNamespace(positions=after, cash=999., receivable_value_usd=100., records=(
        dict(phase='CASH_PAID', amount_usd=50., event_fingerprint='cash'),
        dict(phase='SECURITY_EXTINGUISHED', event_id='term', event_fingerprint='termfp',
             old_security_id='SID_B', ticker='BBB', session='2024-05-07',
             entitled_raw_shares=3., source_fingerprint='b'*64, amount_usd=15.)))
    kwargs = dict(execution_date=pd.Timestamp('2024-05-07'),
        session_open_at=pd.Timestamp('2024-05-07T13:30Z'), security_tickers={'SID_A':'AAA', 'SID_B':'BBB'})
    payload = causal_lifecycle_quantity_payload(((), before), kwargs, result, 'PAIR', {})
    assert payload['positions_before'] == before and payload['positions_after'] == after
    assert payload['positions_after']['SID_A'] == 7.  # Owner lifecycle has not applied SPLIT factor.
    assert not {'cash','receivable_value_usd','amount_usd','nav','price'} & set(payload)
    assert len(payload['terminal_effect_records']) == 1
    assert 'amount_usd' not in payload['terminal_effect_records'][0]
    payload['positions_after']['SID_B'] = 99.
    payload['security_tickers']['SID_A'] = 'WRONG'
    assert after['SID_B'] == 0. and kwargs['security_tickers']['SID_A'] == 'AAA'


def test_causal_source_context_transports_original_bound_metadata_without_prices(tmp_path):
    from types import SimpleNamespace
    from scripts.research.a2.evaluation.reused_policy_pair import causal_owner_source_context
    market = SimpleNamespace(dates=pd.date_range('2024-05-06', periods=2), tickers=['AAA'],
        row_present=np.ones((2,1), bool), open=np.full((2,1), 88.), close=np.full((2,1), 99.))
    events = {'corporate_actions': (), 'unsupported_events': ({'reason':'UNKNOWN'},),
              'entitlement_source_binding': {'source_fingerprint':'a'*64}}
    from hashlib import sha256
    typed_path = tmp_path/'synthetic_ca_owner.py'
    typed_path.write_text('# pure synthetic typed owner stub\n', encoding='utf-8')
    class SyntheticCash: pass
    class SyntheticTerminal: pass
    typed = SimpleNamespace(__file__=str(typed_path), SourceBackedEntitlementEvent=SyntheticCash,
        SourceBackedTerminalEvent=SyntheticTerminal)
    refs = {'code:scripts/v22/corporate_action_transition_r1.py':
        {'path':'D:/synthetic_inherited_logical.py','sha256':sha256(typed_path.read_bytes()).hexdigest()}}
    ctx = causal_owner_source_context({}, market, events, refs, {}, typed_ca_owner=typed)
    assert ctx['typed_entitlement_classes'] == {'cash':SyntheticCash,'terminal':SyntheticTerminal}
    assert ctx['typed_ca_owner_ref']['path'] == str(typed_path)
    with pytest.raises(ValueError, match='EXACT_INHERITED_TYPED'):
        causal_owner_source_context({}, market, events, {}, {}, typed_ca_owner=typed)
    wrong = SimpleNamespace(**vars(typed)); wrong.__file__ = 'E:/forbidden.py'
    with pytest.raises(ValueError, match='BEFORE_IO'):
        causal_owner_source_context({}, market, events, refs, {}, typed_ca_owner=wrong)
    assert not {'open','close','price','nav','weights','mu','sigma','feature_cube'} & set(ctx)
    assert ctx['events'] == events
    ctx['raw_row_present'][0,0] = False
    ctx['events']['entitlement_source_binding']['source_fingerprint'] = '0'*64
    assert market.row_present[0,0] and events['entitlement_source_binding']['source_fingerprint'] == 'a'*64


def test_causal_execute_observer_failure_stops_path_at_actual_preopen_clock(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    from scripts.research.a2.inference.reused_r5_risk_inputs import HeldLineageUnavailable
    def lifecycle(*args, **kwargs):
        return SimpleNamespace(positions=dict(args[1]), records=(), accounting_qualified=True)
    def account(market, paths, checked, config, **kwargs):
        apply_entitlement_lifecycle((), {'SID': 5.}, 10.,
            execution_date=pd.Timestamp('2024-05-07'), session_open_at=pd.Timestamp('2024-05-07T13:30Z'),
            security_tickers={'SID':'AAA'})
        raise AssertionError('Must stop after observer failure')
    def failed(payload):
        assert payload['positions_before'] == payload['positions_after'] == {'SID':5.}
        raise HeldLineageUnavailable('SYNTHETIC_ORIGINAL_QUANTITY_WITNESS_MISSING')
    owner = SimpleNamespace(run_continuous_account=account, apply_entitlement_lifecycle=lifecycle,
        apply_transition_to_positions=lambda *a: (None,None,None))
    parent = SimpleNamespace(ACCOUNT={}, save_frame=lambda *a: {'path':'SYNTHETIC', 'sha256':'a'*64})
    monkeypatch.setattr(pair, 'write', lambda path,value: {'path':'SYNTHETIC:'+Path(path).name,'sha256':'a'*64})
    result = pair.execute(tmp_path, {'task_id':pair.CAUSAL_HELD_TASK}, 'SIMPLE_FEASIBLE', owner,
        None, {}, None, SimpleNamespace(clone=clone_function), parent,
        SimpleNamespace(observe_owner_transitions=failed), None,
        source_context={'owner_ref': {'path':'D:/synthetic_owner.py','sha256':'a'*64}})
    failure = result['first_failure']
    assert result['status'] == 'PAIRED_POLICY_BLOCKED_REAL_INPUT'
    assert failure['reason'] == 'REQUIRED_HELD_IDENTITY_UNAVAILABLE'
    assert failure['execution_date'] == '2024-05-07' and failure['signal_date'] is None
    assert failure['source_observation_role'] == 'PRE_OPEN_LIFECYCLE_APPLIED'
    assert not result['full_window_completed']



def synthetic_output_paths(root):
    from scripts.common.storage_paths import StoragePaths
    return StoragePaths(**{name+'_root': root/name for name in
        ('repo', 'data', 'cache', 'daily', 'backtest', 'results', 'envs')})


def test_output_namespace_omission_preserves_legacy_paths_without_io(tmp_path):
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    run = tmp_path/'existing_original_run'
    for task in (pair.TASK, pair.CA_TASK, pair.CAUSAL_HELD_TASK):
        assert pair.claim_account_output_scope(run, {}, task) == run
    assert not run.exists()


def test_engineering_scope_is_atomic_and_preserves_all_original_evidence(tmp_path):
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    paths = synthetic_output_paths(tmp_path)
    run = paths.backtest_root/pair.CAUSAL_HELD_TASK/'unchanged-managed-run'
    originals = {
        'work/SIMPLE_FEASIBLE_S10/ATTEMPT_CLAIM.json': b'old-simple-claim',
        'work/JOINT_REUSE_S10/POLICY_RESULT.json': b'old-joint-first-failure',
        'PAIR_ACCOUNT_TRUTH_STAGE.json': b'old-terminal-stage',
        'FROZEN_PAIR_R1.json': b'old-freeze',
        'NATIVE_PROCESS_EXIT_R1.json': b'old-actual-exit-0',
    }
    for name, raw in originals.items():
        path = run/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    freeze = {'run': str(run), 'account_output_namespace': 'engineering-source-binding-r2'}
    output = pair.claim_account_output_scope(run, freeze, pair.CAUSAL_HELD_TASK, paths=paths)
    assert output == run/'account_invocations'/'engineering-source-binding-r2'
    marker = output/'new-synthetic-output.json'; marker.write_bytes(b'new-output')
    with pytest.raises(ValueError, match='ALREADY_CLAIMED'):
        pair.claim_account_output_scope(run, freeze, pair.CAUSAL_HELD_TASK, paths=paths)
    assert marker.read_bytes() == b'new-output'
    assert {name: (run/name).read_bytes() for name in originals} == originals
    assert not (run/'account_invocations'/'another-unapproved-scope').exists()


@pytest.mark.parametrize('namespace', [None, '', '.', '..', '../outside', 'a/b', r'a\b',
    ' leading', 'trailing ', 'CON', 'nul', 'COM1', 'LPT9', 'x'*65])
def test_unsafe_output_namespace_is_rejected_before_io(tmp_path, namespace):
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    run = tmp_path/'not-created'
    with pytest.raises(ValueError, match='SAFE_DECLARED'):
        pair.claim_account_output_scope(run, {'run': str(run), 'account_output_namespace': namespace},
                                        pair.CAUSAL_HELD_TASK)
    assert not run.exists()


@pytest.mark.parametrize('task_name', ['TASK', 'CA_TASK'])
def test_namespace_cannot_relabel_old_task_or_write_old_branch(tmp_path, task_name):
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    run = tmp_path/'not-created'
    with pytest.raises(ValueError, match='SAFE_DECLARED'):
        pair.claim_account_output_scope(run, {'run': str(run), 'account_output_namespace':'safe'},
                                        getattr(pair, task_name))
    assert not run.exists()


def test_namespace_rejects_other_managed_run_and_forbidden_drive_before_io(tmp_path):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    run = tmp_path/'not-created'
    with pytest.raises(ValueError, match='UNCHANGED_MANAGED_RUN_IDENTITY'):
        pair.claim_account_output_scope(run, {'run': str(tmp_path/'different-run'),
            'account_output_namespace':'safe'}, pair.CAUSAL_HELD_TASK)
    assert not run.exists()
    with pytest.raises(ValueError, match='LITERAL_D.*BEFORE_IO'):
        pair.claim_account_output_scope(Path('E:/forbidden'), {'run':'E:/forbidden',
            'account_output_namespace':'safe'}, pair.CAUSAL_HELD_TASK)


def test_namespace_physical_escape_is_rejected_without_creating_scope(tmp_path, monkeypatch):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    paths = synthetic_output_paths(tmp_path)
    run = paths.backtest_root/'original-run'
    resolved = type(run).resolve
    def simulated_junction(path, *args, **kwargs):
        if 'account_invocations' in path.parts:
            return tmp_path/'outside-other-run'
        return resolved(path, *args, **kwargs)
    monkeypatch.setattr(type(run), 'resolve', simulated_junction)
    with pytest.raises(ValueError, match='configured backtest root'):
        pair.claim_account_output_scope(run, {'run':str(run),'account_output_namespace':'safe'},
                                        pair.CAUSAL_HELD_TASK, paths=paths)
    assert not run.exists() and not (tmp_path/'outside-other-run').exists()


def test_run_pair_boundary_transport_scopes_material_writers_and_retains_scientific_identity(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    import scripts.research.a2.inference.reused_r5_risk_inputs as risk_module
    paths = synthetic_output_paths(tmp_path)
    run = paths.backtest_root/pair.CAUSAL_HELD_TASK/'original-managed-run'
    freeze_path, review_path = tmp_path/'freeze.json', tmp_path/'review.json'
    ref = {'path':'D:/synthetic-frozen-ref.json','sha256':'a'*64}
    freeze = dict(task_id=pair.CAUSAL_HELD_TASK,status='FROZEN',run=str(run),
        account_output_namespace='engineering-source-binding-r2', source_account_contract_ref=ref,
        source_pins=[],input_pins=[], shared_quote_config_ref={'path':'QUOTE_CONFIG'},
        accounting_freeze_ref={'path':'ACCOUNTING_FREEZE'}, scientific_identity='unchanged-science')
    input_refs = {'cash_kwargs':ref}
    config = {key:ref for key in ('source_binding_B_ref','rule_ref','classification_ref',
                                  'population_ref','clarification_ref')}
    bundle = {'parent_cash_kwargs_ref':ref}
    values = {str(freeze_path):freeze, str(review_path):{'status':'PASS',
        'freeze_ref':{'path':str(freeze_path),'sha256':'b'*64}}, ref['path']:bundle,
        'QUOTE_CONFIG':{'shared_quote_B':config}, 'ACCOUNTING_FREEZE':
        {key:ref for key in ('contract_ref','rule_ref','population_ref')}}
    # Classification shares a dummy ref; read by role rather than opening a real file.
    def read(path):
        if Path(path) == Path(ref['path']):
            return dict(bundle, branches={'B':{'decisions':[]}})
        return values[str(path)]
    monkeypatch.setattr(pair,'read',read)
    monkeypatch.setattr(pair,'sha',lambda path:'b'*64)
    monkeypatch.setattr(pair,'pin',lambda value:Path(value['path']))
    monkeypatch.setattr(pair,'PATHS',paths)
    monkeypatch.setattr(pair,'guard_causal_input_freeze',lambda value:None)
    original_claim = pair.claim_account_output_scope
    monkeypatch.setattr(pair,'claim_account_output_scope',lambda r,f,t:original_claim(r,f,t,paths=paths))
    writes, frames, calls, views = [], [], [], []
    parent = SimpleNamespace(save_frame=lambda root,label,name,frame:
        frames.append((Path(root),label,name)) or {'path':'SYNTHETIC:'+name,'sha256':'c'*64})
    shared = SimpleNamespace(load_parent=lambda:parent,clone=clone_function,adapt_owner=lambda private,mask,proofs:
        proofs.append(pd.DataFrame({'synthetic':[True]})) or private)
    contexts, owner_lists, owner_appends = [], [], []
    def project(owner,ref,commitments,boundary):
        assert contexts[-1]['account_boundary_context']['rows'] is boundary
        assert boundary == []
        owner_lists.append(boundary)
        def original_owner_append(day):
            row = {'path_id':contexts[-1]['account_boundary_context']['account_id'],
                   'effective_date':day,'disposition':'NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX'}
            boundary.append(row)
            owner_appends.append(row)
        return original_owner_append, {'synthetic':True}
    interface = SimpleNamespace(load_shared=lambda:shared,project_current_owner=project,
        convention_functions=lambda *a:{'load_research_ca_accounting_convention':lambda ref:None},
        runtime_event_binding=lambda *a:{'synthetic':True})
    custody = SimpleNamespace(load_interface=lambda:interface,
        relocation_descriptor=lambda:{'actual_execution_source_ref':ref})
    owner = SimpleNamespace(apply_entitlement_lifecycle=lambda *a,**k:None,_frozen_ca_module=object())
    market = SimpleNamespace(dates=pd.date_range('2023-01-01',periods=752),tickers=['AAA'])
    runtime = SimpleNamespace(runtime_inputs=lambda parent:(owner,market,{},input_refs))
    monkeypatch.setattr(pair,'module',lambda path,name:custody if 'custody' in name else runtime)
    monkeypatch.setattr(pair,'account_custody',lambda supplied_runtime:custody)
    monkeypatch.setattr(pair,'bind_account_sources',lambda *a,**k:(market,{},None,{},
        {'receipt':{},'ordinary_cash_event_fingerprints':[]}))
    monkeypatch.setattr(pair,'ordinary_cash_lifecycle',lambda *a,**k:(owner.apply_entitlement_lifecycle,{}))
    # This case isolates boundary ownership with a synthetic projection double.
    monkeypatch.setattr(pair,'project_causal_preopen_quantities',
        lambda interface,owner,ref,commitments,boundary,**k:
            interface.project_current_owner(owner,ref,commitments,boundary))
    monkeypatch.setattr(pair,'causal_owner_source_context',lambda *a,**k:{'owner_ref':ref})
    monkeypatch.setattr(pair,'causal_adapter_load_totals',lambda *a:{'synthetic_loads':0})
    monkeypatch.setattr(risk_module,'ExistingR5LWInputs',lambda **k:SimpleNamespace(loads_count=0))
    monkeypatch.setattr(pair,'FrozenAnnualOpportunityReader',lambda:object())
    def factory(freeze, base_shared, account_id, market, *, source_context):
        ctx = source_context['account_boundary_context']
        assert ctx['account_id'] == account_id
        assert ctx['owner_ref'] == ref and ctx['convention_ref'] == freeze['accounting_freeze_ref']
        assert ctx['rows'] == []
        assert set(ctx) == {'account_id','owner_ref','convention_ref','rows'}
        contexts.append(source_context)
        return SimpleNamespace(source_context=source_context)
    monkeypatch.setattr(pair,'make_causal_input_adapter',factory)
    def execute(root, actual_freeze, kind, *args, **kwargs):
        private, path_risk = args[0], args[6]
        context = kwargs['source_context']
        assert context is path_risk.source_context
        live = context['account_boundary_context']['rows']
        assert live is owner_lists[-1] and not live
        private.run_continuous_account('2023-01-03')
        first = live[0]
        assert first is owner_appends[-1]
        private.run_continuous_account('2023-01-04')
        # A later guard consumes the original earlier row; nothing re-copies,
        # replays, edits or replaces either owner observation.
        assert live[0] is first and live[1] is owner_appends[-1]
        assert [r['effective_date'] for r in live] == ['2023-01-03','2023-01-04']
        assert all(r['path_id'] == actual_freeze['task_id']+'::'+kind+'_S10' for r in live)
        calls.append((Path(root),kind)); views.append(dict(actual_freeze))
        return {'status':'PAIRED_POLICY_BLOCKED_REAL_INPUT','full_window_completed':False,
                'path_id':actual_freeze['task_id']+'::'+kind+'_S10'}
    monkeypatch.setattr(pair,'execute',execute)
    def write(path,value):
        writes.append((Path(path),value)); return {'path':str(path),'sha256':'c'*64}
    monkeypatch.setattr(pair,'write',write)
    stage_ref = pair.run_pair(freeze_path,review_path,task_id=pair.CAUSAL_HELD_TASK)
    scope = run/'account_invocations'/'engineering-source-binding-r2'
    assert [root for root,kind in calls] == [scope,scope]
    assert {path.name for path,value in writes} == {'SOURCE_ACCOUNT_DESCENDANT_BINDING.json',
        'RUNTIME_INPUT_AND_ACCOUNT_BINDING.json','PAIR_ACCOUNT_TRUTH_STAGE.json'}
    assert all(path.parent == scope for path,value in writes)
    assert len(frames) == 4 and all(root == scope for root,label,name in frames)
    assert views == [freeze,freeze] and freeze['run'] == str(run)
    assert len(contexts) == 2 and contexts[0] is not contexts[1]
    assert owner_lists[0] is not owner_lists[1]
    assert contexts[0]['account_boundary_context']['rows'] is owner_lists[0]
    assert contexts[1]['account_boundary_context']['rows'] is owner_lists[1]
    assert len(owner_appends) == 4 and all(len(rows) == 2 for rows in owner_lists)
    stage = writes[-1][1]
    assert stage['expected_sessions'] == 752 and stage['original_managed_run'] == str(run)
    assert stage['account_output_root'] == str(scope) and stage['engineering_continuation']
    assert stage_ref['path'] == str(scope/'PAIR_ACCOUNT_TRUTH_STAGE.json')
    assert [result['path_id'] for result in stage['results']] == [
        pair.CAUSAL_HELD_TASK+'::'+kind+'_S10' for kind in ('SIMPLE_FEASIBLE','JOINT_REUSE')]
    before = (len(writes),len(frames),len(calls))
    with pytest.raises(ValueError,match='ALREADY_CLAIMED'):
        pair.run_pair(freeze_path,review_path,task_id=pair.CAUSAL_HELD_TASK)
    assert before == (len(writes),len(frames),len(calls))


def test_execute_namespaced_view_and_claim_keep_original_managed_run(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    original = tmp_path/'original-managed-run'
    scope = original/'account_invocations'/'engineering-source-binding-r2'
    freeze = dict(task_id=pair.CAUSAL_HELD_TASK,run=str(original),parent_task_id='ORIGINAL_PARENT',
        identity_rule='ORIGINAL_RULE',scientific_identity='ORIGINAL_SCIENCE',
        account_output_namespace='engineering-source-binding-r2')
    pid = pair.CAUSAL_HELD_TASK+'::SIMPLE_FEASIBLE_S10'
    views, saves = [], []
    daily = pd.DataFrame({'mechanism_account_value':np.ones(752), 'cash':np.ones(752)})
    replay = SimpleNamespace(daily=daily,positions=pd.DataFrame(),audit={'synthetic':True})
    owner = SimpleNamespace(run_continuous_account=lambda *a,**k:replay,
        apply_entitlement_lifecycle=lambda *a,**k:None,apply_transition_to_positions=lambda *a,**k:(None,None,None))
    def qualify(replay,market,usable,view,diagnostics):
        views.append(view); return {pid:{'mechanism_accounting_consistent':True}}
    parent = SimpleNamespace(ACCOUNT={},_qualify=qualify,save_frame=lambda root,label,name,frame:
        saves.append(Path(root)) or {'path':'SYNTHETIC:'+name,'sha256':'a'*64})
    shared = SimpleNamespace(clone=clone_function,audit_pass=lambda *a:True)
    monkeypatch.setattr(pair,'write',lambda path,value:{'path':'SYNTHETIC:'+Path(path).name,'sha256':'b'*64})
    result = pair.execute(scope,freeze,'SIMPLE_FEASIBLE',owner,None,{},None,shared,parent,
        SimpleNamespace(observe_owner_transitions=lambda *a:None),None,
        source_context={'owner_ref':{'path':'D:/synthetic_owner.py','sha256':'a'*64}})
    assert result['status'] == 'PAIRED_POLICY_ACCOUNT_COMPLETE'
    assert result['path_id'] == pid and result['policy_calls'] == 0
    assert views[0].run_id == original.name and views[0].digest() == 'ORIGINAL_SCIENCE'
    assert views[0].research_id == pair.CAUSAL_HELD_TASK and saves == [scope,scope]
    claim = json.loads((scope/'work'/'SIMPLE_FEASIBLE_S10'/'ATTEMPT_CLAIM.json').read_text())
    assert claim['path_id'] == pid and claim['original_managed_run'] == str(original)
    assert claim['engineering_continuation'] and claim['scientific_retry'] is False
    # A direct duplicate execute also fails at its x-mode claim before account entry.
    with pytest.raises(FileExistsError):
        pair.execute(scope,freeze,'SIMPLE_FEASIBLE',owner,None,{},None,shared,parent,
            None,None,source_context={'owner_ref':{}})



# Fast-track descendant contracts and real execute public entry. All account
# arrays below are synthetic; no market, trained-model or outcome source opens.
def fast_track_synthetic_freeze():
    from scripts.research.a2.evaluation.reused_policy_pair import FLAGS
    inherited = {key: {'synthetic': key} for key in (
        'account_config', 'cost', 'research_window', 'joint_allocator_parameters',
        'common_feasibility', 'opportunity_annual_refs', 'decision_and_outcome',
        'execution', 'accounting_freeze_ref', 'shared_quote_config_ref', 'policies')}
    ref = {'path': 'D:/synthetic-parent.json', 'sha256': 'a'*64}
    rule = dict(required_domain='E_UNION_OWN_ACTUAL_H',
        estimation_domain='FULL_ORIGINAL_P_UNION_OWN_ACTUAL_H',
        max_new_outputs_per_decision_date=1, max_learned_units_per_output=9,
        max_physical_operations_per_output=14, window_learned_cap=6768,
        window_physical_cap=10528, matrix_mixing=False, future_state_allowed=False,
        unchanged_failed_estimate_retry_allowed=False)
    return dict(inherited, parent_freeze_ref=ref, continuous_lw_rule=rule,
        historical_CA_source_acquisition_authorized=True,
        held_identity_source_binding_ref=ref, supplemental_lw_state_ref=ref, **FLAGS), inherited


@pytest.mark.parametrize('scope,key,value,reason', [
    ('parent', 'cost', {'changed': 20}, 'ORIGINAL_ACCOUNT_POLICY_CHANGED:cost'),
    ('parent', 'policies', {'changed': 'OTHER_Q'}, 'ORIGINAL_ACCOUNT_POLICY_CHANGED:policies'),
    ('flag', 'strict_PIT', True, 'RESEARCH_FLAGS_REQUIRED'),
    ('rule', 'estimation_domain', 'TEMPORARY_E_UNION_H', 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'max_new_outputs_per_decision_date', 2, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'max_learned_units_per_output', 10, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'max_physical_operations_per_output', 15, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'window_learned_cap', 6769, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'window_physical_cap', 10529, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'matrix_mixing', True, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'future_state_allowed', True, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('rule', 'unchanged_failed_estimate_retry_allowed', True, 'CONTINUOUS_LW_CONTRACT_REQUIRED'),
    ('flag', 'historical_CA_source_acquisition_authorized', False,
        'HISTORICAL_SOURCE_AUTHORIZATION_REQUIRED'),
])
def test_fast_track_freeze_rejects_policy_authority_and_resource_drift(monkeypatch, scope, key, value, reason):
    from copy import deepcopy
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    freeze, parent = fast_track_synthetic_freeze()
    monkeypatch.setattr(pair, 'pin', lambda ref: Path(ref['path']))
    monkeypatch.setattr(pair, 'read', lambda path: deepcopy(parent))
    pair.guard_fast_track_freeze(freeze)
    modified = deepcopy(freeze)
    (modified['continuous_lw_rule'] if scope == 'rule' else modified)[key] = value
    with pytest.raises(ValueError, match=reason):
        pair.guard_fast_track_freeze(modified)
    assert freeze['continuous_lw_rule']['max_new_outputs_per_decision_date'] == 1


def test_fast_track_progress_replaces_live_observation_and_never_grants_resume(tmp_path, monkeypatch):
    import json
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'synthetic-run'; root.mkdir(parents=True)
    pair.update_account_progress(root, status='ACCOUNT_RUNNING', observed_daily_rows=1, policy_calls=1)
    pair.update_account_progress(root, status='ACCOUNT_RUNNING', observed_daily_rows=2, policy_calls=2)
    value = json.loads((root/'PAIR_PROGRESS.json').read_text())
    assert value['observed_daily_rows'] == value['policy_calls'] == 2
    assert value['resume_authority'] is False and value['observed_at']
    assert not (root/'PAIR_PROGRESS.json.tmp').exists()


@pytest.fixture(scope='module')
def original_pair_ten_gate_owner():
    # Execute the original pure gate function, not a copied gate implementation.
    import ast
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    source = Path('D:/us-tech-quant-cache/V24/V24_B_FINAL_JOINT_POLICY_ACCOUNT_AND_COVERAGE_R1/source_audit/run_final_joint_policy_account.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'original_qualification_gates']
    assert len(functions) == 1
    namespace = {'QUOTATION_FLAGS': pair.FLAGS}
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
                 str(source), 'exec'), namespace)
    return namespace['original_qualification_gates']


@pytest.mark.parametrize('defect', [None, 'raw_endpoints_finite', 'quality_source_only_or_clear',
    'execution_audit_pass', 'selection_input_complete', 'actual_execution_inputs_complete',
    'unresolved_economic_exception_count', 'status', 'continuous_account', 'annual_reset',
    'full_752_sessions'])
def test_fast_track_execute_requires_every_original_gate_and_keeps_metadata(
        tmp_path, monkeypatch, original_pair_ten_gate_owner, defect):
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    pid = pair.FAST_TRACK_TASK+'::SIMPLE_FEASIBLE_S10'
    days = pd.bdate_range('2023-01-03', '2025-12-31')
    dates = days[np.linspace(0, len(days)-1, 752).astype(int)]
    q = dict(mechanism_accounting_consistent=True, raw_endpoints_finite=True,
        quality_source_only_or_clear=True, execution_audit_pass=True,
        selection_input_complete=True, actual_execution_inputs_complete=True,
        unresolved_economic_exception_count=0, status='MECHANISM_ACCOUNT_CONSISTENT_UNCERTIFIED')
    metadata = dict(continuous_account=True, annual_reset=False)
    if defect in q:
        q[defect] = (1 if defect == 'unresolved_economic_exception_count' else
                     'WRONG_STATUS' if defect == 'status' else False)
    if defect in metadata:
        metadata[defect] = defect == 'annual_reset'
    daily = pd.DataFrame(dict(path_id=pid, date=dates, mechanism_account_value=3000.,
        cash=3000., nav=3000., accounting_qualified=True, actual_name_count=0))
    replay = SimpleNamespace(daily=daily, positions=pd.DataFrame(), audit={'synthetic': True},
        metadata=metadata)
    def account(market, ids, policy, config, **kwargs):
        assert ids == (pid,) and config['initial_cash'] == 3000.
        assert kwargs['execution_friction']['one_way_bps'] == 10
        for i in range(len(daily)):
            kwargs['ledger_callback']('daily', daily.iloc[[i]])
        return replay
    owner = SimpleNamespace(run_continuous_account=account,
        apply_entitlement_lifecycle=lambda *a, **k: None,
        apply_transition_to_positions=lambda *a, **k: (None, None, None))
    def qualify(replay, market, usable, view, gaps):
        assert view.research_id == pair.FAST_TRACK_TASK and gaps == {pid: []}
        return {pid: q}
    def save(root, label, name, frame):
        return {'path': 'SYNTHETIC:'+name, 'sha256': 'a'*64,
                'rows': 751 if name == 'daily' and defect == 'full_752_sessions' else len(frame)}
    parent = SimpleNamespace(ACCOUNT={'initial_cash': 3000.}, _qualify=qualify, save_frame=save)
    captures, progress = {}, []
    def write(path, value):
        captures[Path(path).name] = value
        return {'path': 'SYNTHETIC:'+Path(path).name, 'sha256': 'b'*64}
    monkeypatch.setattr(pair, 'write', write)
    monkeypatch.setattr(pair, 'update_account_progress', lambda root, **value: progress.append(value))
    freeze = dict(task_id=pair.FAST_TRACK_TASK, parent_task_id='SYNTHETIC_PARENT',
        identity_rule='SYNTHETIC_IDENTITY', scientific_identity='SYNTHETIC_CONFIGURATION')
    result = pair.execute(tmp_path, freeze, 'SIMPLE_FEASIBLE', owner, None, {}, None,
        SimpleNamespace(clone=clone_function, audit_pass=lambda *a: True), parent,
        SimpleNamespace(observe_owner_transitions=lambda *a: None), None,
        source_context={'owner_ref': {'path':'D:/synthetic_owner.py','sha256':'a'*64}},
        original_qualifier=original_pair_ten_gate_owner)
    assert result['metadata'] == metadata and result['full_window_completed'] is True
    assert len(result['research_account_gates']['literal_checks']) == 10
    assert result['research_account_qualified'] is (defect is None)
    assert result['status'] == ('PAIRED_POLICY_ACCOUNT_COMPLETE' if defect is None
                                else 'PAIRED_POLICY_ACCOUNT_UNQUALIFIED')
    assert progress[0]['status'] == 'ACCOUNT_STARTED'
    assert progress[-1]['observed_daily_rows'] == 752
    assert captures['POLICY_RESULT.json']['research_account_qualified'] is (defect is None)
    assert all(result[key] is False for key in pair.FLAGS)
    assert result['new_fits'] == result['new_predictions'] == 0


def test_fast_track_execute_missing_gate_owner_rejected_before_any_account_or_claim(tmp_path):
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    with pytest.raises(ValueError, match='ORIGINAL_TEN_ACCOUNT_GATES_REQUIRED'):
        pair.execute(tmp_path, {'task_id':pair.FAST_TRACK_TASK}, 'SIMPLE_FEASIBLE',
                     None, None, {}, None, None, None, None, None)
    assert not list(tmp_path.iterdir())


def test_fast_track_execute_failure_preserves_whole_required_domains_and_original_signal(tmp_path, monkeypatch, original_pair_ten_gate_owner):
    from copy import deepcopy
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    from scripts.research.a2.inference.reused_r5_risk_inputs import ExistingRiskInputUnavailable
    ctx = PersistentPolicyContext(fixture_context(), np.zeros((1,5), int),
        np.full((1,5), np.datetime64('2024-05-01')), np.ones((1,5)), np.ones((1,5)),
        fixture_context().current_units.copy(), receivable_value_usd=np.array([0.]),
        accounting_qualified=np.array([True]))
    risk, forecasts, calls, domain = causal_fake_inputs(ctx)
    snapshot = dict(P=['CCC','DDD','EEE'], E=['CCC','EEE'], H=['AAA','BBB'],
        D=['AAA','BBB','CCC','EEE'], U=['AAA','BBB','CCC','DDD','EEE'],
        signal_date='2024-05-06', decision_asof='2024-05-06T20:00:00Z')
    risk.describe_required_domains = lambda actual: deepcopy(snapshot)
    risk.last_request = dict(status='SOURCE_BLOCKED', selected_original_state='SYNTHETIC_PRIMARY',
                             missing_assets=['AAA'], D=snapshot['D'], U=snapshot['U'])
    def blocked(actual, requested):
        assert actual is ctx and requested is domain
        raise ExistingRiskInputUnavailable('SYNTHETIC_MATURE_PAST_SAMPLE_MISSING')
    backend_request = dict(current_identities={'AAA': {'security_id':'SYNTHETIC:AAA'}},
                           held_lineage_proofs={'AAA': {'raw_commitment':'SYNTHETIC_EXACT_ROW'}},
                           estimation_cutoff='2024-05-06T20:00:00Z')
    risk.estimate_callback = SimpleNamespace(last_request=deepcopy(backend_request))
    risk.for_required_domain = blocked
    def account(market, ids, policy, config, **kwargs):
        return policy(0, ctx)
    owner = SimpleNamespace(run_continuous_account=account,
        apply_entitlement_lifecycle=lambda *a, **k: None,
        apply_transition_to_positions=lambda *a, **k: (None, None, None))
    saved = {}
    def write(path, value):
        saved[Path(path).name] = value
        return {'path':'SYNTHETIC:'+Path(path).name, 'sha256':'a'*64}
    monkeypatch.setattr(pair, 'write', write)
    monkeypatch.setattr(pair, 'update_account_progress', lambda *a, **k: None)
    result = pair.execute(tmp_path, {'task_id':pair.FAST_TRACK_TASK}, 'JOINT_REUSE', owner,
        None, {}, None, SimpleNamespace(clone=clone_function), SimpleNamespace(ACCOUNT={}),
        risk, forecasts, source_context={'owner_ref':{'path':'D:/synthetic_owner.py','sha256':'a'*64}},
        original_qualifier=original_pair_ten_gate_owner)
    failure = saved['CAUSAL_ACCOUNT_AT_FIRST_FAILURE.json']
    assert result['status'] == 'PAIRED_POLICY_BLOCKED_REAL_INPUT'
    assert not result['full_window_completed'] and not result['research_account_qualified']
    assert failure['P_E_H_D_U_at_failure'] == snapshot
    assert failure['latest_adapter_request']['missing_assets'] == ['AAA']
    assert failure['latest_estimator_request'] == backend_request
    assert failure['last_policy_context']['signal_date'].startswith('2024-05-06')
    assert failure['no_partial_session_claimed_complete'] is True
    assert result['first_failure']['signal_date'] == '2024-05-06'
    assert result['first_failure']['failure_session_date'] == '2024-05-06'
    assert calls == ['qualified_domain', 'forecast']


@pytest.mark.parametrize('order', [None, ['JOINT_REUSE', 'SIMPLE_FEASIBLE'],
    ['SIMPLE_FEASIBLE', 'JOINT_REUSE']])
def test_fast_track_two_book_order_preserves_exact_population(order):
    from scripts.research.a2.evaluation.reused_policy_pair import fast_track_account_order
    freeze={} if order is None else {'account_execution_order':order}
    result=fast_track_account_order(freeze)
    assert len(result)==2 and set(result)=={'SIMPLE_FEASIBLE','JOINT_REUSE'}
    assert result==tuple(order or ('SIMPLE_FEASIBLE','JOINT_REUSE'))


@pytest.mark.parametrize('order', [[], ['JOINT_REUSE'], ['JOINT_REUSE','JOINT_REUSE'],
    ['JOINT_REUSE','OTHER_POLICY'], 'JOINT_REUSE', None])
def test_fast_track_two_book_order_cannot_drop_duplicate_or_add_policy(order):
    from scripts.research.a2.evaluation.reused_policy_pair import fast_track_account_order
    with pytest.raises(ValueError,match='EXACT_TWO_INDEPENDENT_BOOKS_REQUIRED'):
        fast_track_account_order({'account_execution_order':order})



def test_private_cash_module_registers_dataclass_namespace_without_replacing_other_module(tmp_path):
    import sys
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    name='_pair_frozen_history_cash_owner_SYNTHETIC_DATACLASS'
    unrelated='_SYNTHETIC_EXISTING_ACCOUNT_OWNER'
    original=SimpleNamespace(marker='unchanged');sys.modules[unrelated]=original
    source=tmp_path/'synthetic_cash.py'
    source.write_text('from __future__ import annotations\nfrom dataclasses import dataclass\n@dataclass\nclass Cash:\n    label: str\n',encoding='utf-8')
    other=tmp_path/'other.py';other.write_text('value=1\n',encoding='utf-8')
    try:
        loaded=pair.module(source,name,register=True)
        assert loaded.Cash('SOURCE_FACT').label=='SOURCE_FACT'
        assert sys.modules[name] is loaded and sys.modules[unrelated] is original
        assert pair.module(source,name,register=True) is loaded
        with pytest.raises(ValueError,match='PRIVATE_MODULE_NAMESPACE_COLLISION'):
            pair.module(other,name,register=True)
        assert sys.modules[name] is loaded
    finally:
        sys.modules.pop(name,None);sys.modules.pop(unrelated,None)


def test_private_cash_module_failed_load_cleans_only_own_namespace(tmp_path):
    import sys
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    name='_pair_frozen_history_cash_owner_SYNTHETIC_FAILED'
    source=tmp_path/'synthetic_bad_cash.py';source.write_text('raise ValueError("BAD_SOURCE")\n',encoding='utf-8')
    with pytest.raises(ValueError,match='BAD_SOURCE'):
        pair.module(source,name,register=True)
    assert name not in sys.modules


def test_causal_source_context_distinguishes_new_actual_cash_owner_from_original_logical_pin(monkeypatch):
    from types import SimpleNamespace
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    actual={'path':str(Path('D:/synthetic-new-cash.py')),'sha256':'a'*64}
    original={'path':str(Path('D:/synthetic-original-cash.py')),'sha256':'b'*64}
    market=SimpleNamespace(dates=pd.DatetimeIndex(['2023-01-03']),tickers=('X',),row_present=np.array([[True]]))
    typed=SimpleNamespace(__file__=actual['path'],SourceBackedEntitlementEvent=type('Cash',(),{}),
        SourceBackedTerminalEvent=type('Terminal',(),{}))
    monkeypatch.setattr(pair,'pin',lambda ref:Path(ref['path']))
    monkeypatch.setattr(pair,'sha',lambda path:'a'*64)
    refs={'code:scripts/v22/corporate_action_transition_r1.py':original}
    freeze={'frozen_history_cash_owner_ref':actual,'inherited_typed_ca_owner_ref':original}
    result=pair.causal_owner_source_context(freeze,market,{},refs,{},typed_ca_owner=typed)
    assert result['typed_ca_owner_ref']==actual and result['input_refs']==refs
    assert 'open' not in result and 'close' not in result
    with pytest.raises(ValueError,match='EXACT_INHERITED_TYPED_CA'):
        pair.causal_owner_source_context(dict(freeze,inherited_typed_ca_owner_ref=dict(original,sha256='c'*64)),
            market,{},refs,{},typed_ca_owner=typed)


# Progress atomic replacement: synthetic filesystem only, no market/account inputs.
def progress_retry_permission_error(winerror):
    exc = PermissionError(13, 'synthetic progress file sharing/access conflict')
    if winerror is not None:
        exc.winerror = winerror
    return exc


@pytest.mark.parametrize('winerror', [5, 32])
@pytest.mark.parametrize('status', ['ACCOUNT_RUNNING', 'SOURCE'])
def test_progress_retry_transient_replace_keeps_one_identical_write(tmp_path, monkeypatch, winerror, status):
    import json
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'progress-retry'; root.mkdir(parents=True)
    target = root/'PAIR_PROGRESS.json'; old = b'{"status":"PREVIOUS"}\n'; target.write_bytes(old)
    temporary = target.with_suffix('.json.tmp')
    real_replace, real_write = Path.replace, Path.write_text
    attempts, writes, sleeps = [], [], []
    def write_once(path, raw, *args, **kwargs):
        if path == temporary: writes.append(raw)
        return real_write(path, raw, *args, **kwargs)
    def replace_once(path, destination):
        if path == temporary:
            attempts.append((path, destination, path.read_bytes()))
            assert target.read_bytes() == old
            if len(attempts) <= 2: raise progress_retry_permission_error(winerror)
        return real_replace(path, destination)
    monkeypatch.setattr(Path, 'write_text', write_once)
    monkeypatch.setattr(Path, 'replace', replace_once)
    monkeypatch.setattr(pair.time, 'sleep', sleeps.append)
    pair.update_account_progress(root, status=status, path_id='SYNTHETIC', policy_calls=7, observed_daily_rows=8)
    assert len(writes) == 1 and len(attempts) == 3
    assert all(p == temporary and d == target and raw == attempts[0][2] for p, d, raw in attempts)
    assert sleeps == [0.05, 0.1] and target.read_bytes() == attempts[0][2]
    value = json.loads(target.read_text(encoding='utf-8'))
    assert value['status'] == status and value['policy_calls'] == 7 and value['observed_daily_rows'] == 8
    assert value['resume_authority'] is False and value['observed_at']
    assert set(value) == {'status', 'path_id', 'policy_calls', 'observed_daily_rows', 'resume_authority', 'observed_at'}
    assert not temporary.exists()


@pytest.mark.parametrize('winerror', [5, 32])
def test_progress_retry_exhaustion_preserves_last_error_old_payload_and_temp(tmp_path, monkeypatch, winerror):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'exhausted-progress'; root.mkdir(parents=True)
    target = root/'PAIR_PROGRESS.json'; old = b'{"status":"PREVIOUS"}\n'; target.write_bytes(old)
    temporary = target.with_suffix('.json.tmp'); attempts, errors, sleeps = [], [], []
    def fail(path, destination):
        assert path == temporary and destination == target
        attempts.append(path.read_bytes())
        exc = progress_retry_permission_error(winerror); errors.append(exc); raise exc
    monkeypatch.setattr(Path, 'replace', fail)
    monkeypatch.setattr(pair.time, 'sleep', sleeps.append)
    with pytest.raises(PermissionError) as raised:
        pair.update_account_progress(root, status='ENGINEERING_FAILURE', policy_calls=7)
    assert raised.value is errors[-1] and len(attempts) == 5
    assert all(raw == attempts[0] for raw in attempts)
    assert sleeps == [0.05, 0.1, 0.15000000000000002, 0.2]
    assert sum(sleeps) <= 0.5000000000000001 and target.read_bytes() == old
    assert temporary.read_bytes() == attempts[0]


@pytest.mark.parametrize('kind, winerror', [('permission', None), ('permission', 1), ('permission', 13),
    ('permission', 87), ('missing', None), ('other_oserror', 5)])
def test_progress_retry_other_errors_propagate_once_without_sleep(tmp_path, monkeypatch, kind, winerror):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'other-progress-error'; root.mkdir(parents=True)
    target = root/'PAIR_PROGRESS.json'; old = b'{"status":"PREVIOUS"}\n'; target.write_bytes(old)
    if kind == 'permission': error = progress_retry_permission_error(winerror)
    elif kind == 'missing': error = FileNotFoundError(2, 'synthetic temp disappearance')
    else:
        error = OSError(22, 'synthetic unrelated OS error'); error.winerror = winerror
    calls, sleeps = [], []
    def fail(path, destination): calls.append((path, destination)); raise error
    monkeypatch.setattr(Path, 'replace', fail)
    monkeypatch.setattr(pair.time, 'sleep', sleeps.append)
    with pytest.raises(type(error)) as raised:
        pair.update_account_progress(root, status='SOURCE', policy_calls=7)
    assert raised.value is error and len(calls) == 1 and sleeps == []
    assert target.read_bytes() == old


def test_progress_retry_does_not_retry_temp_write_failure(tmp_path, monkeypatch):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'temp-write-error'; root.mkdir(parents=True)
    target = root/'PAIR_PROGRESS.json'; old = b'{"status":"PREVIOUS"}\n'; target.write_bytes(old)
    error = progress_retry_permission_error(5); calls, sleeps = [], []
    def fail_write(*args, **kwargs): raise error
    monkeypatch.setattr(Path, 'write_text', fail_write)
    monkeypatch.setattr(Path, 'replace', lambda *args: calls.append(args))
    monkeypatch.setattr(pair.time, 'sleep', sleeps.append)
    with pytest.raises(PermissionError) as raised:
        pair.update_account_progress(root, status='SOURCE', policy_calls=7)
    assert raised.value is error and calls == sleeps == [] and target.read_bytes() == old


@pytest.mark.parametrize('status', ['ACCOUNT_STARTED', 'PAIRED_POLICY_ACCOUNT_COMPLETE'])
def test_progress_retry_success_first_try_preserves_payload_without_sleep(tmp_path, monkeypatch, status):
    import json
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'no-progress-conflict'; root.mkdir(parents=True)
    real_replace = Path.replace; calls, sleeps = [], []
    def replace_once(path, destination): calls.append((path, destination)); return real_replace(path, destination)
    monkeypatch.setattr(Path, 'replace', replace_once)
    monkeypatch.setattr(pair.time, 'sleep', sleeps.append)
    pair.update_account_progress(root, status=status, policy_calls=7, full_window_completed=True)
    value = json.loads((root/'PAIR_PROGRESS.json').read_text(encoding='utf-8'))
    assert len(calls) == 1 and sleeps == [] and value['status'] == status
    assert value['full_window_completed'] is True and value['resume_authority'] is False
    assert not (root/'PAIR_PROGRESS.json.tmp').exists()


def test_progress_retry_execute_never_replays_account_or_ledger_callback(tmp_path, monkeypatch, original_pair_ten_gate_owner):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair, 'PATHS', synthetic_output_paths(tmp_path))
    root = tmp_path/'backtest'/'synthetic-progress-entry'; root.mkdir(parents=True)
    pid = pair.FAST_TRACK_TASK+'::SIMPLE_FEASIBLE_S10'
    dates = pd.bdate_range('2023-01-03', periods=3)
    daily = pd.DataFrame(dict(path_id=pid, date=dates, mechanism_account_value=3000., cash=3000.,
        nav=3000., accounting_qualified=True, actual_name_count=0))
    replay = SimpleNamespace(daily=daily, positions=pd.DataFrame(), audit={'synthetic': True},
        metadata=dict(continuous_account=True, annual_reset=False))
    account_calls, ledger_calls, sleeps, replace_snapshots = [], [], [], []
    def account(market, ids, policy, config, **kwargs):
        account_calls.append(ids)
        for i in range(len(daily)):
            ledger_calls.append(str(dates[i].date()))
            kwargs['ledger_callback']('daily', daily.iloc[[i]])
        return replay
    owner = SimpleNamespace(run_continuous_account=account,apply_entitlement_lifecycle=lambda *a, **k: None,
        apply_transition_to_positions=lambda *a, **k: (None, None, None))
    q = dict(mechanism_accounting_consistent=True, raw_endpoints_finite=True, quality_source_only_or_clear=True,
        execution_audit_pass=True, selection_input_complete=True, actual_execution_inputs_complete=True,
        unresolved_economic_exception_count=0, status='MECHANISM_ACCOUNT_CONSISTENT_UNCERTIFIED')
    parent = SimpleNamespace(ACCOUNT={'initial_cash':3000.}, _qualify=lambda *a:{pid:q},
        save_frame=lambda root,label,name,frame:dict(path='SYNTHETIC:'+name,sha256='a'*64,rows=len(frame)))
    monkeypatch.setattr(pair, 'write', lambda path,value:dict(path='SYNTHETIC:'+Path(path).name,sha256='b'*64))
    real_replace = Path.replace
    def replace_maybe(path, destination):
        value = json.loads(path.read_text(encoding='utf-8'))
        if value['status']=='ACCOUNT_RUNNING' and value['observed_daily_rows']==1:
            replace_snapshots.append(path.read_bytes())
            if len(replace_snapshots)<=2: raise progress_retry_permission_error(32)
        return real_replace(path,destination)
    monkeypatch.setattr(Path,'replace',replace_maybe)
    monkeypatch.setattr(pair.time,'sleep',sleeps.append)
    freeze=dict(task_id=pair.FAST_TRACK_TASK,parent_task_id='SYNTHETIC_PARENT',identity_rule='SYNTHETIC_IDENTITY',scientific_identity='SYNTHETIC_CONFIGURATION')
    result=pair.execute(root,freeze,'SIMPLE_FEASIBLE',owner,None,{},None,
        SimpleNamespace(clone=clone_function,audit_pass=lambda *a:True),parent,
        SimpleNamespace(observe_owner_transitions=lambda *a:None),None,
        source_context={'owner_ref':{'path':'D:/synthetic_owner.py','sha256':'a'*64}},original_qualifier=original_pair_ten_gate_owner)
    assert account_calls==[(pid,)] and ledger_calls==[str(d.date()) for d in dates]
    assert len(replace_snapshots)==3 and all(raw==replace_snapshots[0] for raw in replace_snapshots)
    assert sleeps==[0.05,0.1] and result['policy_calls']==0
    assert result['status']=='ENGINEERING_FAILURE_REQUIRES_DIAGNOSIS'
    assert result['first_failure']['reason']=='PAIR_FULL_WINDOW_ACCOUNT_TRUTH_FAILED'
    value=json.loads((root/'work'/'SIMPLE_FEASIBLE_S10'/'PAIR_PROGRESS.json').read_text(encoding='utf-8'))
    assert value['observed_daily_rows']==3 and value['policy_calls']==0 and value['resume_authority'] is False


# Source/control fixture: no model/data/account callback is executed.
def _account_custody_fixture(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from scripts.research.a2.evaluation import reused_policy_pair as pair
    frozen=tmp_path/'frozen_account_custody.py';runtime=tmp_path/'original_runtime.py'
    recovered=tmp_path/'recovered_owner.py';receipt=tmp_path/'recovery_receipt.json'
    runtime.write_text('# immutable runtime\n',encoding='utf-8')
    recovered.write_text('# immutable original owner\n',encoding='utf-8')
    receipt.write_text('{}\n',encoding='utf-8')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    source=f"""
import pair_forbidden_unused_p2_kernel
raise AssertionError('unused P2 import-time graph must not execute')
_R5_ROOT=Path(__file__).parent
_CANONICAL_OWNER=Path({str(runtime)!r})
_RECOVERED_OWNER=Path({str(recovered)!r})
_OWNER_SHA={digest(recovered)!r}
_METADATA_OWNER_SHA='metadata-only'
_METADATA_ROLE='METADATA_HASH_DEPENDENCY_ONLY_NOT_ORIGINAL_SCIENTIFIC_AUTHORITY'
_RECOVERY={{'path':{str(receipt)!r},'sha256':{digest(receipt)!r}}}
def _r5_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _clone(fn,**updates):
    return fn
def _private_module_functions(module,**overrides):
    return dict(vars(module),**overrides)
def relocation_descriptor():
    return {{'path':str(_RECOVERED_OWNER),'sha256':_OWNER_SHA}}
def load_interface():
    return previous.old.load_interface()
def run_p2():
    raise AssertionError('unconsumed P2 callback')
"""
    frozen.write_text(source,encoding='utf-8')
    original=SimpleNamespace(marker=object())
    runtime_module=SimpleNamespace(__file__=str(runtime),load_interface=lambda:original)
    monkeypatch.setattr(pair,'CUSTODY',frozen);monkeypatch.setattr(pair,'CUSTODY_SHA',digest(frozen))
    monkeypatch.setattr(pair,'RUNTIME',runtime);monkeypatch.setattr(pair,'RUNTIME_SHA',digest(runtime))
    return pair,runtime_module,original,frozen,runtime,recovered,receipt


def test_account_custody_reuses_interface_without_p2_import_or_callback(tmp_path,monkeypatch):
    import sys
    pair,runtime,original,*_=_account_custody_fixture(tmp_path,monkeypatch)
    custody=pair.account_custody(runtime)
    assert custody.load_interface() is original
    assert 'pair_forbidden_unused_p2_kernel' not in sys.modules
    assert not hasattr(custody,'run_p2')
    assert not hasattr(custody,'QualifiedP2SlotLoader')
    assert custody.relocation_descriptor()['sha256']==custody.load_interface.__globals__['_OWNER_SHA']


@pytest.mark.parametrize('which',['frozen','runtime','recovered','receipt'])
def test_account_custody_requires_each_exact_physical_pin(tmp_path,monkeypatch,which):
    pair,runtime,original,frozen,runtime_path,recovered,receipt=_account_custody_fixture(tmp_path,monkeypatch)
    path={'frozen':frozen,'runtime':runtime_path,'recovered':recovered,'receipt':receipt}[which]
    path.write_bytes(path.read_bytes()+b'# changed')
    with pytest.raises(ValueError,match='PAIR_FROZEN_SOURCE_CHANGED'):
        pair.account_custody(runtime)


def test_account_custody_rejects_wrong_runtime_namespace(tmp_path,monkeypatch):
    from types import SimpleNamespace
    pair,runtime,*_=_account_custody_fixture(tmp_path,monkeypatch)
    fake=SimpleNamespace(__file__=str(tmp_path/'other.py'),load_interface=runtime.load_interface)
    with pytest.raises(ValueError,match='PAIR_EXACT_ORIGINAL_ACCOUNT_RUNTIME_REQUIRED'):
        pair.account_custody(fake)


@pytest.mark.parametrize('change',['missing','duplicate'])
def test_account_custody_rejects_incomplete_or_duplicate_selected_function_set(tmp_path,monkeypatch,change):
    import hashlib
    pair,runtime,original,frozen,*_=_account_custody_fixture(tmp_path,monkeypatch)
    source=frozen.read_text(encoding='utf-8')
    if change=='missing':source=source.replace('def _clone(fn,**updates):','def not_clone(fn,**updates):')
    else:source+='\ndef _clone(fn,**updates):\n    return fn\n'
    frozen.write_text(source,encoding='utf-8')
    monkeypatch.setattr(pair,'CUSTODY_SHA',hashlib.sha256(frozen.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='PAIR_FROZEN_ACCOUNT_CUSTODY_FUNCTION_SET_CHANGED'):
        pair.account_custody(runtime)


@pytest.mark.parametrize('changed',[False,True])
def test_account_custody_run_pair_pins_runtime_before_import(tmp_path,monkeypatch,changed):
    import ast,inspect
    pair,runtime,original,frozen,runtime_path,*_=_account_custody_fixture(tmp_path,monkeypatch)
    calls=[]
    def load(path,name):
        calls.append('module')
        assert Path(path)==runtime_path
        return runtime
    def custody(supplied):
        calls.append('custody')
        assert supplied is runtime
        return original
    from pathlib import Path
    monkeypatch.setattr(pair,'module',load)
    monkeypatch.setattr(pair,'account_custody',custody)
    tree=ast.parse(inspect.getsource(pair.run_pair))
    # Execute the actual two source loader statements, without account inputs.
    statements=[n for n in tree.body[0].body if isinstance(n,ast.Assign)
                and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
                and n.targets[0].id in ('runtime','custody')]
    assert len(statements)==2
    code=compile(ast.Module(body=statements,type_ignores=[]),'<actual-run-pair-loader>','exec')
    if changed:
        runtime_path.write_bytes(runtime_path.read_bytes()+b'# different')
        with pytest.raises(ValueError,match='PAIR_FROZEN_SOURCE_CHANGED'):
            exec(code,dict(vars(pair)))
        assert calls==[]
    else:
        exec(code,dict(vars(pair)))
        assert calls==['module','custody']



def test_causal_pto_requires_explicit_recipe_and_qualifies_exact_domain():
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision
    ctx=fixture_context()
    risk,forecasts,calls,domain=causal_fake_inputs(ctx)
    original=forecasts.for_decision
    def predict(*args,**kwargs):
        out=original(*args,**kwargs)
        out.source_receipt['forecast_recipe']='RIDGE_HGB_EQUAL'
        return out
    forecasts.for_decision=predict
    prepared=causal_policy_decision('PTO_REUSE_ROBUST_COST',ctx,risk,forecasts)
    assert calls==['qualified_domain','forecast','numeric_risk','note_candidate_only']
    assert prepared['result'].receipt['allocator']=='robust_cost_aware'
    risk,forecasts,calls,_=causal_fake_inputs(ctx)
    with pytest.raises(ValueError,match='PTO_EXPLICIT_TWO_MEMBER'):
        causal_policy_decision('PTO_REUSE_ROBUST_COST',ctx,risk,forecasts)
    assert 'note_candidate_only' not in calls



def test_pto_account_order_executes_only_declared_missing_books():
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    profile=pair.PTO_ACCOUNT_PROFILE
    f=dict(pto_account_profile=profile,account_execution_order=profile['policies'])
    assert pair.fast_track_account_order(f)==tuple(profile['policies'])
    f.update(qualified_account_reuse={pair.PTO_REUSE_KIND:{'path':'synthetic','sha256':'a'*64}},
        account_execution_order=[pair.RAW_SOURCE_REUSE_KIND])
    assert pair.fast_track_account_order(f)==(pair.RAW_SOURCE_REUSE_KIND,)
    f['account_execution_order']=profile['policies']
    with pytest.raises(ValueError,match='ONLY_MISSING'):
        pair.fast_track_account_order(f)


def test_pto_freeze_separates_new_policy_and_source_from_old_pair(monkeypatch):
    from copy import deepcopy
    from dataclasses import asdict
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    from scripts.research.a2.inference.reused_policy_inputs import P0_ANNUAL_REFERENCES,RIDGE_ANNUAL_REFERENCES
    f,parent=fast_track_synthetic_freeze()
    parent.update(scientific_identity='ORIGINAL',source_account_contract_ref={'path':'D:/source.json','sha256':'b'*64},cost={'one_way_bps':10})
    f.update(cost=parent['cost'],source_account_contract_ref=parent['source_account_contract_ref'],scientific_identity='EXPLICIT_NEW_PTO',
        pto_account_profile=pair.PTO_ACCOUNT_PROFILE,account_execution_order=pair.PTO_ACCOUNT_PROFILE['policies'],
        pto_design_ref={'path':'D:/design.json','sha256':'c'*64},registry_preflight_ref={'path':'D:/preflight.json','sha256':'d'*64},
        policies=pair.PTO_ACCOUNT_PROFILE['recipes'],joint_allocator_parameters=dict(method='robust_cost_aware',risk_penalty=4.,
            uncertainty_penalty=.5,iterations=128,tolerance=2e-6,execution_friction_bps=10,full_target=True,fixed_feasible_gross=True),
        opportunity_annual_refs={'HGB':{str(y):asdict(r) for y,r in P0_ANNUAL_REFERENCES.items()},
                                'RIDGE':{str(y):asdict(r) for y,r in RIDGE_ANNUAL_REFERENCES.items()}})
    design=dict(status='FROZEN_BEFORE_NEW_ACCOUNT_OUTCOME',scientific_identity=f['scientific_identity'],
        source_parent_ref=f['parent_freeze_ref'],source_account_contract_ref=f['source_account_contract_ref'])
    def read(path):
        return deepcopy(design if Path(path).name=='design.json' else {'status':'PASS'} if Path(path).name=='preflight.json' else parent)
    monkeypatch.setattr(pair,'pin',lambda ref:Path(ref['path']));monkeypatch.setattr(pair,'read',read)
    pair.guard_fast_track_freeze(f)
    for key,value in [('scientific_identity','ORIGINAL'),('cost',{'one_way_bps':20}),('policies',{'PTO':'WRONG'})]:
        bad=deepcopy(f);bad[key]=value
        with pytest.raises(ValueError):pair.guard_fast_track_freeze(bad)


def test_pto_comparison_never_reads_artifacts_before_all_original_ten_gates(monkeypatch,tmp_path):
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    monkeypatch.setattr(pair.pd,'read_parquet',lambda *a,**k:pytest.fail('unqualified artifacts read'))
    results=[dict(kind=kind,full_window_completed=True,research_account_qualified=False)
             for kind in pair.PTO_ACCOUNT_PROFILE['policies']]
    assert pair.publish_pto_account_comparison(tmp_path,{},results,[]) is None


def test_causal_raw_source_uses_original_recipe_and_no_numeric_risk():
    from scripts.research.a2.evaluation.reused_policy_pair import causal_policy_decision,RAW_SOURCE_REUSE_KIND
    ctx=fixture_context();risk,forecasts,calls,domain=causal_fake_inputs(ctx,refuse_numeric=True)
    original=forecasts.for_decision
    def raw(*a,**k):
        out=original(*a,**k);out.source_receipt['forecast_recipe']='ORIGINAL_RAW_A2';return out
    forecasts.for_decision=raw
    result=causal_policy_decision(RAW_SOURCE_REUSE_KIND,ctx,risk,forecasts)
    assert calls==['qualified_domain','forecast','note_candidate_only']
    assert result['result'].receipt['allocator']=='ORIGINAL_RAW_A2_POLICY'



def test_pto_raw_source_only_adapter_keeps_source_book_and_shared_budget_without_estimator(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    from scripts.research.a2.inference import reused_r5_risk_inputs as risk_inputs
    from scripts.research.a2.risk import continuous_lw_support as backend
    ctx=fixture_context();fake,forecasts,calls,domain=causal_fake_inputs(ctx,refuse_numeric=True)
    adapter=object.__new__(risk_inputs.ContinuousCausalLWInputs)
    for name in ('qualified_causal_domain','for_required_domain','note_qualified_decision','observe_fills'):
        setattr(adapter,name,getattr(fake,name))
    factory_calls=[]
    def source_factory(cls, **kwargs):
        factory_calls.append(kwargs)
        return adapter
    monkeypatch.setattr(risk_inputs.ContinuousCausalLWInputs,'_from_freeze',classmethod(source_factory))
    monkeypatch.setattr(backend,'make_continuous_lw_estimator',lambda *a,**k:pytest.fail('Raw estimator constructed'))
    monkeypatch.setattr(backend.ContinuousLWEstimator,'__init__',lambda *a,**k:pytest.fail('Raw estimator initialized'))
    ledger=tmp_path/'managed'/'work'/'FIT_STATUS.json';ledger.parent.mkdir(parents=True)
    status=dict(records=[dict(status='COMPLETE_WHOLE_LW_OUTPUT')],new_fit_units=9,
        physical_events=[dict(status='FIT_COMPLETE') for _ in range(14)],
        inherited_state_history=dict(publication_ref={'path':'D:/synthetic/paid.json','sha256':'a'*64},
            learned_units=9,physical_operations=14,charged_to_this_scope=False))
    ledger.write_text(json.dumps(status),encoding='utf-8')
    freeze=dict(task_id=pair.FAST_TRACK_TASK,pto_account_profile=pair.PTO_ACCOUNT_PROFILE,
        run=str(ledger.parent.parent),continuous_lw_rule=backend.CONTINUOUS_LW_RULE)
    account_id=pair.FAST_TRACK_TASK+'::'+pair.RAW_SOURCE_REUSE_KIND+'_S10'
    source_context={'same_source_context':True}
    actual=pair.make_causal_input_adapter(freeze,object(),account_id,
        SimpleNamespace(dates=['SYNTHETIC'],tickers=['A']),source_context=source_context)
    assert actual is adapter and factory_calls[0]['source_context'] is source_context
    assert factory_calls[0]['inherited_runtime_evidence_only'] is True
    budget=actual.budget_summary()
    assert budget['new_complete_outputs']==1 and budget['charged_new_learned_units']==9
    assert budget['charged_new_physical_operations']==14 and budget['authoritative_ledger_available'] is True
    assert budget['ledger_ref']['path']==str(ledger)
    with pytest.raises(pair.ExistingRiskInputUnavailable,match='RAW_SOURCE_ONLY_NUMERIC_RISK_DISABLED'):
        actual.estimate_callback({'synthetic':True})
    original=forecasts.for_decision
    def raw(*args,**kwargs):
        result=original(*args,**kwargs)
        result.source_receipt['forecast_recipe']=pair.PTO_ACCOUNT_PROFILE['recipes'][pair.RAW_SOURCE_REUSE_KIND]
        return result
    forecasts.for_decision=raw
    result=pair.causal_policy_decision(pair.RAW_SOURCE_REUSE_KIND,ctx,actual,forecasts)
    assert calls==['qualified_domain','forecast','note_candidate_only']
    assert result['result'].receipt['allocator']=='ORIGINAL_RAW_A2_POLICY'
    assert json.loads(ledger.read_text(encoding='utf-8'))==status


@pytest.mark.parametrize('comparison_ready',[True,False])
def test_pto_all_qualified_reuse_publishes_comparison_without_runtime(tmp_path,monkeypatch,comparison_ready):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    paths=synthetic_output_paths(tmp_path)
    run=paths.backtest_root/pair.FAST_TRACK_TASK/'managed'
    output=run/'account_invocations'/'reuse-only'
    ref={'path':'D:/synthetic/source.json','sha256':'a'*64}
    freeze=dict(task_id=pair.FAST_TRACK_TASK,status='FROZEN',run=str(run),source_account_contract_ref=ref,
        source_pins=[],input_pins=[],pto_account_profile=pair.PTO_ACCOUNT_PROFILE,
        qualified_account_reuse={kind:ref for kind in pair.PTO_ACCOUNT_PROFILE['policies']},account_execution_order=[])
    reused=[dict(kind=kind,full_window_completed=True,research_account_qualified=True,
        artifacts={'daily':dict(path='D:/synthetic/'+kind+'.parquet',sha256='b'*64)})
        for kind in pair.PTO_ACCOUNT_PROFILE['policies']]
    dates=pd.bdate_range('2023-01-03',periods=752)
    monkeypatch.setattr(pair,'PATHS',paths)
    monkeypatch.setattr(pair,'read',lambda path:freeze if str(path)=='FREEZE' else {})
    monkeypatch.setattr(pair,'pin',lambda ref:Path(ref['path']))
    monkeypatch.setattr(pair,'guard_fast_track_freeze',lambda freeze:None)
    monkeypatch.setattr(pair,'claim_account_output_scope',lambda *args:output)
    monkeypatch.setattr(pair,'load_pto_reused_accounts',lambda freeze:reused)
    monkeypatch.setattr(pair,'module',lambda *a,**k:pytest.fail('Reused books entered runtime'))
    def read_dates(path,*,columns):
        assert columns==['date']
        return pd.DataFrame({'date':dates})
    monkeypatch.setattr(pair.pd,'read_parquet',read_dates)
    comparisons=[];writes=[]
    comparison_ref={'path':'D:/synthetic/comparison.json','sha256':'c'*64}
    def publish(root, frozen, results, expected):
        assert root==output and frozen is freeze and results is reused
        assert pd.DatetimeIndex(expected).equals(dates)
        comparisons.append(results)
        return comparison_ref if comparison_ready else None
    monkeypatch.setattr(pair,'publish_pto_account_comparison',publish)
    monkeypatch.setattr(pair,'write',lambda path,value:writes.append((path,value)) or value)
    if not comparison_ready:
        with pytest.raises(ValueError,match='PTO_REUSED_ACCOUNTS_REQUIRE_COMPLETE_COMPARISON'):
            pair.run_pair('FREEZE',task_id=pair.FAST_TRACK_TASK)
        assert not writes
    else:
        stage=pair.run_pair('FREEZE',task_id=pair.FAST_TRACK_TASK)
        assert stage['comparison_ref']==comparison_ref and stage['complete_count']==stage['qualified_count']==2
        assert stage['new_real_account_runs']==stage['new_predictive_fits']==stage['new_risk_estimates']==0
        assert len(writes)==1
    assert len(comparisons)==1


def source_deferral_fixture(monkeypatch):
    from copy import deepcopy
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    def ref(name):return dict(path='D:/synthetic/'+name,sha256='a'*64)
    prior_ref,source_ref,missing_ref=ref('prior.json'),ref('source.json'),ref('missing.json')
    prior=dict(run='D:/us-tech-quant-backtests/synthetic/run',account_output_namespace='prior',
        scientific_identity='ORIGINAL_PTO_INPUT',pto_account_profile=deepcopy(pair.PTO_ACCOUNT_PROFILE),
        cost=dict(one_way_bps=10),account_config={'initial_cash':3000},source_account_contract_ref=source_ref)
    result_ref=dict(path=str(Path(prior['run'])/'account_invocations/prior/work/PTO_REUSE_ROBUST_COST_S10/POLICY_RESULT.json'),sha256='b'*64)
    key=dict(ticker='INTC',effective_date='2023-05-04',reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',
        source_reference='D:/synthetic/original-binding.json',source_fingerprint='c'*64)
    result=dict(kind=pair.PTO_REUSE_KIND,status='PAIRED_POLICY_BLOCKED_REAL_INPUT',
        scientific_identity=prior['scientific_identity'],pto_account_profile=deepcopy(pair.PTO_ACCOUNT_PROFILE),
        account_config=prior['account_config'],cost=prior['cost'],source_account_contract_ref=source_ref,
        full_window_completed=False,research_account_qualified=False,
        first_failure=dict(reason='ACTUAL_ACCOUNT_FACT_UNEXECUTABLE',failure_session_date='2023-05-04',candidate_event_keys=[key]))
    source=dict(events=[],source_completion_limits={'new_batch_unresolved_original_ex_dates':{'INTC':['2023-05-04']}})
    missing=dict(status='BLOCKED_MISSING_ISSUER_DECLARED_DIRECT_EX_DATE',source_account_contract_ref=source_ref,
        prior_result_ref=result_ref,candidate_event_keys=[key])
    refs=dict(prior_freeze_ref=prior_ref,prior_result_ref=result_ref,missing_source_ref=missing_ref)
    freeze=deepcopy(prior);freeze.update(scientific_identity='RAW_SOURCE_COMPLETION',account_output_namespace='new',
        deferred_account_blocks={pair.PTO_REUSE_KIND:refs},account_execution_order=[pair.RAW_SOURCE_REUSE_KIND])
    docs={str(Path(r['path'])):v for r,v in [(prior_ref,prior),(result_ref,result),(source_ref,source),(missing_ref,missing)]}
    monkeypatch.setattr(pair,'pin',lambda r:Path(r['path']))
    monkeypatch.setattr(pair,'read',lambda p:docs.get(str(Path(p)),{}))
    return pair,freeze,prior,result,source,missing,refs,docs


def test_pto_source_block_defers_only_missing_not_ready_book(monkeypatch):
    pair,f,prior,result,source,missing,refs,docs=source_deferral_fixture(monkeypatch)
    assert pair.fast_track_account_order(f)==(pair.RAW_SOURCE_REUSE_KIND,)
    deferred=pair.load_pto_deferred_source_blocks(f)
    assert deferred[pair.PTO_REUSE_KIND]['qualified'] is False
    assert deferred[pair.PTO_REUSE_KIND]['complete'] is False
    assert deferred[pair.PTO_REUSE_KIND]['prior_result_ref']==refs['prior_result_ref']


@pytest.mark.parametrize('change',['qualified','admitted_source','wrong_cost','wrong_event','wrong_path','wrong_kind','reuse_overlap'])
def test_pto_source_deferral_cannot_hide_resolved_or_unrelated_failure(monkeypatch,change):
    from copy import deepcopy
    from pathlib import Path
    pair,f,prior,result,source,missing,refs,docs=source_deferral_fixture(monkeypatch)
    if change=='qualified':result['research_account_qualified']=True
    elif change=='admitted_source':source['events']=[dict(original_unsupported_keys=deepcopy(missing['candidate_event_keys']))]
    elif change=='wrong_cost':f['cost']={'one_way_bps':20}
    elif change=='wrong_event':result['first_failure']['candidate_event_keys']=[dict(missing['candidate_event_keys'][0],source_fingerprint='d'*64)]
    elif change=='wrong_path':
        refs['prior_result_ref']=dict(path='D:/synthetic/wrong-result.json',sha256='b'*64)
        docs[str(Path(refs['prior_result_ref']['path']))]=result
    elif change=='wrong_kind':f['deferred_account_blocks']={pair.RAW_SOURCE_REUSE_KIND:refs}
    elif change=='reuse_overlap':f['qualified_account_reuse']={pair.PTO_REUSE_KIND:refs['prior_result_ref']}
    with pytest.raises(ValueError):pair.load_pto_deferred_source_blocks(f)


def test_pto_zero_runnable_source_block_stage_never_reads_prefix_or_runtime(tmp_path,monkeypatch):
    from pathlib import Path
    import scripts.research.a2.evaluation.reused_policy_pair as pair
    paths=synthetic_output_paths(tmp_path);run=paths.backtest_root/pair.FAST_TRACK_TASK/'managed'
    source_ref={'path':'D:/synthetic/source.json','sha256':'a'*64}
    f=dict(task_id=pair.FAST_TRACK_TASK,status='FROZEN',run=str(run),source_account_contract_ref=source_ref,
        source_pins=[],input_pins=[],pto_account_profile=pair.PTO_ACCOUNT_PROFILE,
        qualified_account_reuse={pair.RAW_SOURCE_REUSE_KIND:source_ref},
        deferred_account_blocks={pair.PTO_REUSE_KIND:{}},account_execution_order=[])
    raw=dict(kind=pair.RAW_SOURCE_REUSE_KIND,full_window_completed=True,research_account_qualified=True)
    deferred={pair.PTO_REUSE_KIND:{'status':'DEFERRED_UNRESOLVED_SOURCE_NOT_QUALIFIED'}}
    monkeypatch.setattr(pair,'PATHS',paths)
    monkeypatch.setattr(pair,'read',lambda path:f if str(path)=='FREEZE' else {})
    monkeypatch.setattr(pair,'pin',lambda ref:Path(ref['path']))
    monkeypatch.setattr(pair,'guard_fast_track_freeze',lambda freeze:None)
    monkeypatch.setattr(pair,'claim_account_output_scope',lambda *a:run/'account_invocations/new')
    monkeypatch.setattr(pair,'load_pto_reused_accounts',lambda freeze:[raw])
    monkeypatch.setattr(pair,'load_pto_deferred_source_blocks',lambda freeze:deferred)
    monkeypatch.setattr(pair,'module',lambda *a,**k:pytest.fail('runtime for deferred/reused'))
    monkeypatch.setattr(pair.pd,'read_parquet',lambda *a,**k:pytest.fail('prefix/daily for deferred/reused'))
    monkeypatch.setattr(pair,'publish_pto_account_comparison',lambda *a:pytest.fail('incomplete comparison'))
    monkeypatch.setattr(pair,'write',lambda path,value:value)
    stage=pair.run_pair('FREEZE',task_id=pair.FAST_TRACK_TASK)
    assert stage['status']=='PTO_NO_RUNNABLE_ACCOUNT_SOURCE_BLOCKS_RETAINED'
    assert stage['qualified_count']==stage['complete_count']==1
    assert stage['expected_account_count']==2 and stage['pair_complete'] is False
    assert stage['comparison_ref'] is None and stage['new_real_account_runs']==0
