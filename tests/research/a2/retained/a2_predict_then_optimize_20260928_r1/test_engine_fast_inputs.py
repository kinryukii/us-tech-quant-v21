import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from engine_fast_inputs import PreparedInputs, run_replay
from engine_v2 import run_replay as original, HoldingAwareDecision, OperationalExit
from test_engine_cached import inputs

LEDGERS = ('daily', 'positions', 'trades', 'target_decisions', 'execution_results',
           'diagnostics', 'signal_contexts', 'raw_model_outputs', 'operational_actions',
           'valuation_intervals')


def assert_exact(a, b):
    for name in LEDGERS:
        assert_frame_equal(getattr(a, name), getattr(b, name), check_exact=True)
    assert a.metadata == b.metadata


def policy(day, ctx):
    names = list(day.ticker)
    chosen = names[:ctx.available_slots]
    decisions = {t: 0. for t in names if t in ctx.current_units}
    decisions.update({t: min(.1, ctx.available_weight / max(1, len(chosen))) for t in chosen})
    # Callback writes must never mutate shared input or a later callback frame.
    original_names = list(day.ticker)
    day['callback_mutation'] = True
    return HoldingAwareDecision(model_decisions=decisions,
                                raw_model_outputs={'names': original_names, 'cash': ctx.cash})


def test_fast_all_ten_ledgers_exact_and_fresh_accounts():
    px, cal, f = inputs()
    asofs = {d: d + pd.Timedelta(hours=20) for d in cal}
    prepared = PreparedInputs(px, cal, f, signal_asof=asofs)
    kwargs = dict(candidate='same', capacity_fraction=.01, signal_end=f.signal_date.max(),
                  signal_asof=asofs)
    expected = original(px, cal, f, policy, **kwargs)
    for _ in range(2):
        result = run_replay(px, cal, f, policy, prepared_inputs=prepared, **kwargs)
        assert_exact(expected, result)
    assert prepared.selection_hits > 0
    assert all('callback_mutation' not in frame for frame in prepared.signal_frames.values())


def test_selection_cache_distinguishes_holdings_and_external_ops():
    px, cal, f = inputs()
    prepared = PreparedInputs(px, cal, f)
    restrictions = pd.DataFrame([dict(signal_date=cal[0], ticker='AAA', known_at=cal[0],
                                    source_id='known', reason='buy only', buy_restricted=True)])
    exit_action = OperationalExit('known exit', cal[0], 'exit evidence')
    for initial, ops in [({}, {}), ({'AAA': 50.}, {}),
                         ({'AAA': 50.}, {cal[0]: {'AAA': exit_action}}), ({}, {})]:
        kwargs = dict(candidate='same', capacity_fraction=.01, signal_end=f.signal_date.max(),
                      known_restrictions=restrictions, initial_positions=initial,
                      operational_exits_by_signal=ops)
        assert_exact(original(px, cal, f, policy, **kwargs),
                     run_replay(px, cal, f, policy, prepared_inputs=prepared, **kwargs))


def test_asof_mutation_is_not_cached_as_a_valid_old_time():
    px, cal, f = inputs()
    asofs = {d: d for d in cal}
    prepared = PreparedInputs(px, cal, f, signal_asof=asofs)
    run_replay(px, cal, f, policy, prepared_inputs=prepared, signal_asof=asofs)
    asofs[cal[0]] = cal[1]
    for function, extra in [(original, {}), (run_replay, {'prepared_inputs': prepared})]:
        with pytest.raises(ValueError, match='signal_asof'):
            function(px, cal, f, policy, signal_asof=asofs, **extra)


def test_no_prepared_branch_is_reference_and_rebinding_rejected():
    px, cal, f = inputs()
    assert_exact(original(px, cal, f, policy), run_replay(px, cal, f, policy))
    prepared = PreparedInputs(px, cal, f)
    with pytest.raises(ValueError, match='IDENTITY_MISMATCH'):
        run_replay(px.copy(), cal, f, policy, prepared_inputs=prepared)


def test_selection_lru_stores_only_indices_and_exact_copy():
    px, cal, f = inputs()
    prepared = PreparedInputs(px, cal, f)
    d = cal[0]
    day = prepared.signal_frame(d)
    for i in range(40):
        result = prepared.decision_frame(d, day, {f'other_{i}'}, {}, {'AAA'}, {})
        assert_frame_equal(result, day.loc[day.ticker.ne('AAA')].copy(deep=True), check_exact=True)
    assert len(prepared.selections[d]) == prepared.SELECTION_KEYS_PER_DAY
    assert all(isinstance(x, np.ndarray) for x in prepared.selections[d].values())
