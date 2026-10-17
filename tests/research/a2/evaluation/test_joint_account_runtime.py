"""Strict whole-replay equivalence using synthetic inputs only."""
import math
import time

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import joint_account_runtime as indexed
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition, SourceBackedEntitlementEvent,
    RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE,
)


def current_indexed(*args, **kwargs):
    return indexed.run_continuous_account_indexed(*args, source_sha256=indexed.NEW_SOURCE_SHA256, **kwargs)


def config():
    return dict(base_currency="USD", initial_nav=3000, initial_cash=3000, initial_holdings=[],
                fractional_shares=True, integer_share_rounding=False, cash_interest=0,
                transaction_cost_bps=0, financing=False, borrowed_cash=False, long_only=True,
                max_positions=20, max_weight=1., max_invested=1., capacity_fraction=.01)


def market(dates=None):
    dates = pd.bdate_range("2024-01-02", periods=8) if dates is None else pd.to_datetime(dates)
    values = np.full((len(dates), 3), 100.)
    return MarketArrays(dates, ["A", "B", "C"], values.copy(), values.copy(),
                        adv=np.full(values.shape, 1e9))


def policy(buy_at=0):
    def call(j, ctx):
        target = np.array([[.4, .2, 0], [0, .3, .2]])[:len(ctx.path_ids)]
        if j == buy_at:
            return TargetDecision(target, ctx.decision_mask)
        return TargetDecision(np.zeros_like(target), np.zeros_like(target, dtype=bool))
    return call


def same(a, b):
    if isinstance(a, pd.DataFrame):
        pd.testing.assert_frame_equal(a, b, check_exact=True)
    elif isinstance(a, np.ndarray):
        np.testing.assert_array_equal(a, b)
    elif isinstance(a, dict):
        assert list(a) == list(b)
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert type(a) is type(b) and len(a) == len(b)
        for x, y in zip(a, b):
            same(x, y)
    elif isinstance(a, float) and math.isnan(a):
        assert isinstance(b, float) and math.isnan(b)
    else:
        assert a == b


def paired(m, factory=policy, **kwargs):
    callbacks = [[], []]
    outputs = []
    for number, run in enumerate((run_continuous_account, current_indexed)):
        outputs.append(run(
            m, ["P0", "P1"], factory(), config(), **kwargs,
            ledger_callback=lambda name, frame, k=number: callbacks[k].append((name, frame.copy())),
        ))
    same(vars(outputs[0]), vars(outputs[1]))
    same(callbacks[0], callbacks[1])
    return outputs


def test_no_events_and_all_observable_callback_tables_are_exactly_equal():
    outputs = paired(market())
    assert outputs[0].accounting_exceptions.empty


def test_original_ticker_group_order_duplicate_keys_and_multiple_paths_are_preserved():
    events = [
        dict(ticker="C", effective_date="2024-01-04", reason="C-first"),
        dict(ticker="A", effective_date="2024-01-04", reason="A-first"),
        dict(ticker="C", effective_date="2024-01-04", reason="C-duplicate"),
        dict(ticker="B", effective_date="2024-01-04", reason="B-first"),
        dict(ticker="A", effective_date="2024/01/04", reason="A-alternate-string"),
        dict(ticker="A", effective_date="2024-01-05", reason="A-next-day"),
    ]
    outputs = paired(market(), unsupported_events=events)
    rows = outputs[0].accounting_exceptions
    assert rows.reason.tolist() == ["A-first", "A-alternate-string", "B-first", "C-first", "B-first", "A-next-day"]
    assert outputs[0].final_state["accounting_qualified"].tolist() == [False, False]


def test_prior_future_unknown_ticker_intraday_and_nat_events_keep_original_semantics():
    events = [
        dict(ticker="A", effective_date="2023-01-02", reason="prior"),
        dict(ticker="A", effective_date="2025-01-02", reason="future"),
        dict(ticker="UNKNOWN", effective_date="not-a-date", reason="unknown-ticker-skips-parse"),
        dict(ticker="A", effective_date="2024-01-04 12:00", reason="intraday-no-session-match"),
        dict(ticker="A", effective_date="NaT", reason="nat-no-session-match"),
    ]
    outputs = paired(market(), unsupported_events=events)
    assert outputs[0].accounting_exceptions.empty
    assert outputs[0].final_state["accounting_qualified"].all()


def test_later_first_buy_after_past_exception_remains_qualified():
    outputs = paired(market(), factory=lambda: policy(buy_at=3),
                     unsupported_events=[dict(ticker="A", effective_date="2024-01-04", reason="past")])
    assert outputs[0].accounting_exceptions.empty
    assert outputs[0].final_state["accounting_qualified"].all()


def test_share_transform_and_unsupported_cash_events_are_exactly_equal():
    m = market()
    m.open[2:, 0] *= .5
    m.close[2:, 0] *= .5
    split = CorporateActionTransition(
        "2024-01-04", "FORWARD_SPLIT", "old_A", "new_A", "A", "A",
        2., 0., "TIER2_LOCAL_CANONICAL", "synthetic://split", "a"*64)
    cash = CorporateActionTransition(
        "2024-01-04", "OTHER_SHARE_COUNT_TRANSFORM", "old_C", "new_C", "C", "C",
        1., 1., "TIER2_LOCAL_CANONICAL", "synthetic://cash", "c"*64)
    kwargs = dict(corporate_actions=[split, cash], corporate_action_known_at={
        split.event_fingerprint: "2024-01-03 16:00:00+00:00",
        cash.event_fingerprint: "2024-01-03 16:00:00+00:00"})
    outputs = paired(m, **kwargs)
    assert len(outputs[0].metadata["corporate_action_receipts"]) == 1
    assert outputs[0].final_state["accounting_qualified"].tolist() == [True, False]
    assert outputs[0].final_state["fractional_shares"][0, 0] == pytest.approx(24.)


def test_locked_synthetic_2026_prefix_and_mismatch_guard_are_unchanged():
    pre = market(["2025-12-30", "2025-12-31"])
    first = paired(pre)[0]
    full = market(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"])
    outputs = paired(full, previous_prefix=first.prefix_identity,
                     locked_evaluation_receipt={"status":"FINALIST_FROZEN", "sha256":"f"*64})
    assert outputs[0].prefix_identity == first.prefix_identity
    bad = {**first.prefix_identity, "sha256": "0"*64}
    for run in (run_continuous_account, current_indexed):
        with pytest.raises(AssertionError, match="changed frozen"):
            run(full, ["P0", "P1"], policy(), config(), previous_prefix=bad,
                locked_evaluation_receipt={"status":"FINALIST_FROZEN", "sha256":"f"*64})


@pytest.mark.parametrize("dates,match", [
    (["2022-12-29", "2023-01-03"], "first legal 2023"),
    (["2025-12-31", "2026-01-02"], "finalist freeze"),
])
def test_initial_floor_and_locked_test_gates_preserved(dates, match):
    for run in (run_continuous_account, current_indexed):
        with pytest.raises(ValueError, match=match):
            run(market(dates), ["P0", "P1"], policy(), config())


def test_source_bound_projection_rejects_changed_source_and_engine_identities(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(indexed, "SOURCE_SHA256", "0"*64)
        with pytest.raises(RuntimeError, match="source identity"):
            indexed._projection()
    with monkeypatch.context() as scoped:
        scoped.setattr(indexed, "ENGINE_SHA256", "0"*64)
        with pytest.raises(RuntimeError, match="engine identity"):
            indexed._projection(indexed.NEW_SOURCE_SHA256)
    lineage = indexed.source_lineage(source_sha256=indexed.NEW_SOURCE_SHA256)
    assert len(lineage["ast_edits"]) == 2
    assert lineage["frozen_source_bytes_modified"] is False


def test_bounded_7200_event_performance_pair_is_strictly_equivalent():
    m = market(pd.bdate_range("2024-01-02", periods=48))
    events = [dict(ticker=("A", "B", "C")[i%3], effective_date="2023-12-29",
                   reason=f"synthetic-prior-{i}") for i in range(7200)]
    results, seconds = [], []
    for run in (run_continuous_account, current_indexed):
        start = time.perf_counter()
        results.append(run(m, ["P0", "P1"], policy(), config(), unsupported_events=events))
        seconds.append(time.perf_counter()-start)
    same(vars(results[0]), vars(results[1]))
    print(f"SYNTHETIC_PERF original={seconds[0]:.6f} indexed={seconds[1]:.6f} speedup={seconds[0]/seconds[1]:.4f} sessions=48 paths=2 events=7200")



def friction(bps=10):
    return dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE',scenario_id=f'synthetic_{bps}bps',
        one_way_bps=bps,fee_bps=0,benchmark='NEXT_RAW_OPEN',authority='HYPOTHETICAL_RESEARCH_SCENARIO')


def dividend(**changes):
    fields=dict(event_id='divA',action_type='CASH_DIVIDEND',old_security_id='idA',ticker='A',
        ex_date='2024-01-04',record_date='2024-01-04',pay_date='2024-01-05',
        available_at='2024-01-03 12:00:00+00:00',cash_per_old_share=10.,currency='USD',
        amount_unit=USD_PER_RAW_OLD_SHARE,quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
        source_type='TIER2_LOCAL_CANONICAL',source_reference='synthetic://declared-dividend',source_fingerprint='d'*64)
    fields.update(changes)
    return SourceBackedEntitlementEvent(**fields)


def entitlement_args(events):
    mapping={'idA':'A'}
    return dict(entitlement_enabled=True,entitlement_events=events,entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',
            source_fingerprint='e'*64,event_fingerprints=[e.event_fingerprint for e in events],
            security_tickers=mapping,quantity_coordinate=RAW_OLD_SHARE_COORDINATE))


@pytest.mark.parametrize('bps',[0,10])
def test_explicit_new_source_friction_entitlement_claims_and_all_callbacks_are_equal(bps):
    m=market();m.open[2:,0]=90.;m.close[2:,0]=90.
    outputs=paired(m,execution_friction=friction(bps),**entitlement_args([dividend()]))
    daily=outputs[0].daily
    assert daily.loc[daily.path_id.eq('P0') & daily.date.eq(pd.Timestamp('2024-01-04')),'receivable_value_usd'].iloc[0]==pytest.approx(120)
    assert daily.loc[daily.path_id.eq('P0') & daily.date.eq(pd.Timestamp('2024-01-05')),'entitlement_cash_flow_usd'].iloc[0]==pytest.approx(120)
    assert outputs[0].audit['actual_cash_flow_identity_error_max']<1e-8
    assert outputs[0].daily.accounting_qualified.all()


def test_new_source_same_day_split_and_cash_lifecycle_are_equal():
    m=market();m.open[2:,0]=45.;m.close[2:,0]=45.
    split=CorporateActionTransition('2024-01-04','FORWARD_SPLIT','oldA','newA','A','A',2.,0.,
        'TIER2_LOCAL_CANONICAL','synthetic://split','a'*64)
    outputs=paired(m,corporate_actions=[split],corporate_action_known_at={split.event_fingerprint:'2024-01-03 12:00:00+00:00'},
        execution_friction=friction(10),**entitlement_args([dividend()]))
    snapshot=outputs[0].entitlements.loc[outputs[0].entitlements.phase.eq('EX_PRETRADE_RAW_SHARE_SNAPSHOT')]
    assert snapshot.entitled_raw_shares.tolist()==[12.]
    assert outputs[0].final_state['fractional_shares'][0,0]==24.


def test_new_source_late_cash_terms_and_preheld_unknown_events_keep_exact_qualification():
    m=market();m.open[2:,0]=90.;m.close[2:,0]=90.
    unknown=[dict(ticker='C',effective_date='2024-01-04',reason='unknown-held-C'),
             dict(ticker='A',effective_date='2023-12-29',reason='past-unused'),
             dict(ticker='C',effective_date='2024/01/04',reason='same-day-alternate-key')]
    outputs=paired(m,unsupported_events=unknown,execution_friction=friction(10),
        **entitlement_args([dividend(available_at='2024-01-04 15:00:00+00:00')]))
    assert outputs[0].final_state['accounting_qualified'].tolist()==[False,False]
    assert outputs[0].daily.entitlement_cash_flow_usd.eq(0).all()


def test_legacy_default_is_not_silently_rebound_and_both_hashes_have_separate_cache(monkeypatch):
    from pathlib import Path
    indexed._compiled.cache_clear()
    old=Path('D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/receipts/source_audit/continuous_research_account_99038f036431c91b1070fe52d5bdbbd057c617356a8b839c295c6c4bf0742d00.py')
    if not old.exists():pytest.skip('task-local old source audit unavailable')
    direct=run_continuous_account(market(),['P0','P1'],policy(),config())
    with monkeypatch.context() as scoped:
        scoped.setattr(indexed,'_SOURCE',old)
        legacy=indexed.run_continuous_account_indexed(market(),['P0','P1'],policy(),config())
        same(vars(direct),vars(legacy))
        assert indexed.source_lineage()['source_sha256']==indexed.SOURCE_SHA256
    current=current_indexed(market(),['P0','P1'],policy(),config())
    same(vars(direct),vars(current))
    assert indexed._compiled.cache_info().currsize==2
    assert indexed._compiled(indexed.SOURCE_SHA256)[0] is not indexed._compiled(indexed.NEW_SOURCE_SHA256)[0]
    with pytest.raises(RuntimeError,match='source identity'):
        indexed.run_continuous_account_indexed(market(),['P0','P1'],policy(),config())
    with pytest.raises(RuntimeError,match='source identity'):
        indexed.source_lineage()
    with pytest.raises(RuntimeError,match='source identity'):
        indexed.run_continuous_account_indexed(market(),['P0','P1'],policy(),config(),source_sha256='f'*64)
    with monkeypatch.context() as scoped:
        scoped.setattr(indexed,'ENGINE_SHA256','0'*64)
        with pytest.raises(RuntimeError,match='engine identity'):
            current_indexed(market(),['P0','P1'],policy(),config())
