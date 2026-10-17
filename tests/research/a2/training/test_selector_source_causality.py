"""Synthetic causality audit of the actual frozen forward-rehab producer.

Only selected original pure AST definitions execute. No source module imports,
provider readers, parquet bodies, label values, estimators or accounts execute.
This evidence does not qualify source vintage, availability or shareholder cash.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[4]
BUILDER = Path('D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/scripts/run_rebuild.py')
FEATURE = REPO / 'scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py'
PINS = {
    str(BUILDER): '68f4eb6599638db4c6af51b0ff8894f757b78a60dba27ce03e5c798e9508cc0e',
    str(FEATURE): 'fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19',
}
CASES = ('NO_CA', 'FUTURE_SPLIT', 'FUTURE_CASH_DIVIDEND', 'TICKER_CHANGE',
         'SECURITY_ID_CHANGE', 'REVERSE_SPLIT', 'TERMINAL_MERGER')


def originals():
    """Run current original function bodies without their unsafe module loaders."""
    namespace = dict(pd=pd, np=np, END_EXCLUSIVE=pd.Timestamp('2026-01-01'))
    selections = {
        BUILDER: {'Stop', 'require', 'adjusted_price_frame'},
        FEATURE: {'FEATURE_COLUMNS', '_rolling_max_drawdown', 'build_stock_state_features'},
    }
    for path, names in selections.items():
        source_bytes = path.read_bytes()
        assert hashlib.sha256(source_bytes).hexdigest() == PINS[str(path)]
        parsed = ast.parse(source_bytes.decode('utf-8'), filename=str(path))
        selected = []
        found = set()
        for node in parsed.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names:
                selected.append(node)
                found.add(node.name)
            elif isinstance(node, ast.Assign):
                targets = {x.id for x in node.targets if isinstance(x, ast.Name)}
                if targets & names:
                    selected.append(node)
                    found.update(targets & names)
        assert found == names
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[
            ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(path), 'exec'), namespace)
    return namespace


def fixtures():
    days = pd.bdate_range('2024-01-02', periods=160)
    value = 90 + np.arange(len(days)) * .19 + np.sin(np.arange(len(days)) / 7)
    raw = pd.DataFrame(dict(trade_date=days, open=value - .2, close=value,
                            high=value + .5, low=value - .5,
                            volume=10000 + np.arange(len(days)) * 3))
    cutoff = days[120]
    return raw, cutoff, days[130]


def factor(date, a=1., b=0., **extra):
    return dict(code='US.SYNTH', ex_div_date=date, forward_adj_factorA=a,
                forward_adj_factorB=b, **extra)


def events(rows):
    return pd.DataFrame(rows, columns=list(dict.fromkeys([
        'code', 'ex_div_date', 'forward_adj_factorA', 'forward_adj_factorB',
        *[k for row in rows for k in row]])))


def history(namespace, raw, rows, cutoff, ticker='SYNTH'):
    adjusted, audit = namespace['adjusted_price_frame'](
        'US.SYNTH', ticker, raw, events(rows),
        {'event_date': '2099-01-01', 'quantity_multiplier': 1.})
    built = namespace['build_stock_state_features'](
        adjusted[['ticker', 'trade_date', 'close', 'volume']])
    pre = built.loc[built.trade_date.lt(cutoff), ['trade_date', 'ticker', 'close', 'ret_1d']].tail(63)
    data = pre.to_csv(index=False, lineterminator='\n', float_format='%.17g').encode('utf-8')
    return data, pre, adjusted, audit


def append_case(case, anchored=False):
    namespace = originals()
    raw, cutoff, future_date = fixtures()
    prior = [factor(raw.trade_date.iloc[20], a=.8, b=-.7)] if anchored else []
    before, _, _, _ = history(namespace, raw.loc[raw.trade_date.lt(cutoff)], prior, cutoff)
    after_raw = raw.copy()
    future = []
    semantic_support = 'NOT_APPLICABLE'
    if case == 'FUTURE_SPLIT':
        future = [factor(future_date, a=.5, split_ratio=2.)]
        semantic_support = 'AFFINE_FACTOR_ARITHMETIC_ONLY'
    elif case == 'FUTURE_CASH_DIVIDEND':
        future = [factor(future_date, b=-1., total_cash_div=1.)]
        semantic_support = 'AFFINE_FACTOR_ARITHMETIC_ONLY_NOT_SHAREHOLDER_CASH'
    elif case == 'TICKER_CHANGE':
        after_raw['identity_ticker'] = np.where(after_raw.trade_date.lt(future_date), 'SYNTH', 'NEW')
        future = [factor(future_date, old_ticker='SYNTH', new_ticker='NEW')]
        semantic_support = 'IDENTITY_FIELDS_IGNORED_BY_ORIGINAL_PRODUCER'
    elif case == 'SECURITY_ID_CHANGE':
        after_raw['security_uid'] = np.where(after_raw.trade_date.lt(future_date), 'UID:OLD', 'UID:NEW')
        future = [factor(future_date, old_uid='UID:OLD', new_uid='UID:NEW')]
        semantic_support = 'UID_FIELDS_IGNORED_BY_ORIGINAL_PRODUCER'
    elif case == 'REVERSE_SPLIT':
        future = [factor(future_date, a=8., join_base=8.)]
        semantic_support = 'AFFINE_FACTOR_ARITHMETIC_ONLY'
    elif case == 'TERMINAL_MERGER':
        # Terminal notice and cessation are append-only inputs, not a paid price.
        after_raw = after_raw.loc[after_raw.trade_date.le(future_date)].copy()
        future = [factor(future_date, terminal=True, terminal_cash=5.)]
        semantic_support = 'TERMINAL_FIELDS_IGNORED_NO_SETTLEMENT_OR_IDENTITY_AUTHORITY'
    elif case != 'NO_CA':
        raise ValueError(case)
    after, _, _, _ = history(namespace, after_raw, prior + future, cutoff)
    return dict(case=case, historic_affine_anchor=anchored,
        prior_history_sha256=hashlib.sha256(before).hexdigest(),
        appended_history_sha256=hashlib.sha256(after).hexdigest(),
        prior_bytes=len(before), appended_bytes=len(after), bytes_equal=before == after,
        cutoff_exclusive=cutoff.isoformat(), future_event_date=future_date.isoformat(),
        observation_scope='SYNTHETIC_2024_ONLY', semantics=semantic_support,
        source_qualified=False, authority_activated=False)


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('anchored', [False, True])
def test_original_producer_future_append_exact_history_bytes(case, anchored):
    assert append_case(case, anchored)['bytes_equal']


def revision_counterexample(kind):
    namespace = originals()
    raw, cutoff, future_date = fixtures()
    original = factor(raw.trade_date.iloc[60], a=.8, b=-.7,
                      available_at=raw.trade_date.iloc[60].isoformat())
    prior, _, _, _ = history(namespace, raw, [original], cutoff)
    changed_raw = raw.copy()
    changed_events = [dict(original)]
    if kind == 'LATE_EVENT_REVISION':
        changed_events[0].update(forward_adj_factorB=-3., available_at=future_date.isoformat(), revision=2)
    elif kind == 'LATE_RAW_REVISION':
        changed_raw.loc[60, 'close'] += 7.
        changed_raw['available_at'] = future_date.isoformat()
        changed_raw['revision'] = 2
    else:
        raise ValueError(kind)
    revised, _, _, _ = history(namespace, changed_raw, changed_events, cutoff)
    return dict(case=kind, unchanged_effective_date=True,
                prior_history_sha256=hashlib.sha256(prior).hexdigest(),
                revised_history_sha256=hashlib.sha256(revised).hexdigest(),
                bytes_equal=prior == revised,
                available_at_after_cutoff_ignored=True,
                producer_rejected=False, source_qualified=False)


@pytest.mark.parametrize('kind', ['LATE_EVENT_REVISION', 'LATE_RAW_REVISION'])
def test_original_producer_does_not_enforce_later_revision_availability(kind):
    assert revision_counterexample(kind)['bytes_equal'] is False


def test_transform_does_not_use_complete_history_terminal_anchor():
    namespace = originals()
    raw, cutoff, future_date = fixtures()
    rows = [factor(raw.trade_date.iloc[20], a=.8, b=-.7)]
    first, _, _, _ = history(namespace, raw, rows, cutoff)
    namespace['END_EXCLUSIVE'] = future_date + pd.Timedelta(days=1)
    second, _, _, _ = history(namespace, raw, rows + [factor(future_date, a=.5)], cutoff)
    assert first == second


def test_source_event_aligns_to_next_raw_session_never_prior_session():
    namespace = originals()
    raw, cutoff, _ = fixtures()
    friday = raw.loc[raw.trade_date.dt.dayofweek.eq(4), 'trade_date'].iloc[4]
    weekend = friday + pd.Timedelta(days=1)
    _, _, adjusted, audit = history(namespace, raw,
        [factor(weekend, a=.5, split_ratio=2.)], cutoff)
    applied = [x for x in audit if x['audit_kind'] == 'APPLIED_CORPORATE_ACTION'][0]
    assert applied['source_event_date'] == weekend
    assert applied['event_date'] == friday + pd.Timedelta(days=3)
    assert applied['aligned_to_next_session'] is True
    prior = adjusted.loc[adjusted.trade_date.le(friday)]
    np.testing.assert_array_equal(prior.close.to_numpy(), raw.loc[raw.trade_date.le(friday), 'close'].to_numpy())


def test_truncating_original_history_loses_affine_start_anchor():
    namespace = originals()
    raw, cutoff, _ = fixtures()
    rows = [factor(raw.trade_date.iloc[20], b=-7.)]
    full, _, _, _ = history(namespace, raw, rows, cutoff)
    truncated = raw.loc[raw.trade_date.ge(raw.trade_date.iloc[50])]
    short, _, _, audit = history(namespace, truncated, rows, cutoff)
    assert not audit and short != full


def test_original_uid_boundary_is_not_quarantined_by_transform_or_features():
    namespace = originals()
    raw, cutoff, _ = fixtures()
    boundary = raw.trade_date.iloc[90]
    raw['security_uid'] = np.where(raw.trade_date.lt(boundary), 'UID:OLD', 'UID:NEW')
    _, pre, _, _ = history(namespace, raw, [], cutoff)
    assert np.isfinite(pre.loc[pre.trade_date.eq(boundary), 'ret_1d'].iloc[0])


def receipt_rows():
    return ([append_case(case, anchored) for anchored in (False, True) for case in CASES],
            [revision_counterexample(kind) for kind in ('LATE_EVENT_REVISION', 'LATE_RAW_REVISION')])