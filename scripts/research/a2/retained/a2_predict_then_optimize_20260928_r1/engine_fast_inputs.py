"""Cache immutable signal inputs without changing the reference account.

The compiled function uses the already verified ``engine_cached`` builder.
Only source-frame lookup, as-of parsing, eligibility parsing and row selection
are replaced. Cash, units, marks, orders, fills and account contexts remain the
same reference statements. Every callback receives its own deep frame copy.
"""
from __future__ import annotations

from collections import OrderedDict
import inspect

import numpy as np
import pandas as pd

import engine_cached as cached


class PreparedInputs(cached.PreparedInputs):
    """Bind one immutable input batch and cache account-dependent row indices.

    Selection keys include the signal, reserved names, external operations,
    and buy-restricted names that are not currently held. No account state or
    target value is cached. The last distinction is needed for buy-only
    restrictions: the same name remains a valid sell input if already held.
    """

    SELECTION_KEYS_PER_DAY = 16

    def __init__(self, prices, calendar, features, *, signal_asof=None):
        super().__init__(prices, calendar, features)
        self.empty_frame = self.fs.iloc[:0]
        self.signal_frames = {d: self.frames.get(d, self.empty_frame)
                              for d in self.calendar}
        self.input_order = {d: tuple(g.ticker) for d, g in self.signal_frames.items()}
        self.eligible = {}
        for d, day in self.signal_frames.items():
            self.eligible[d] = (
                dict(zip(day.ticker, day.new_buy_eligible.fillna(False).astype(bool)))
                if "new_buy_eligible" in day else dict.fromkeys(self.input_names[d], True))
        self.selections = {d: OrderedDict() for d in self.calendar}
        self.selection_hits = self.selection_misses = 0
        self._asof_snapshot = None
        self._parsed_asofs = None
        if signal_asof is not None:
            self.parsed_asofs(signal_asof)

    def signal_frame(self, date):
        return self.signal_frames[date]

    def parsed_asofs(self, signal_asof):
        source = signal_asof or {}
        # Compare values so mutation of a supplied map cannot reuse stale time.
        if self._asof_snapshot is None or source != self._asof_snapshot:
            self._asof_snapshot = dict(source)
            self._parsed_asofs = {pd.Timestamp(d): pd.Timestamp(v)
                                  for d, v in source.items()}
        return self._parsed_asofs.copy()

    def decision_frame(self, date, source_day, reserved, external_ops,
                       buy_restricted, holdings):
        if source_day is not self.signal_frames[date]:
            raise ValueError("PREPARED_SIGNAL_FRAME_IDENTITY_MISMATCH")
        reserved_key = frozenset(reserved)
        ops_key = frozenset(external_ops)
        blocked_new_key = frozenset(buy_restricted) - frozenset(holdings)
        key = (reserved_key, ops_key, blocked_new_key)
        cache = self.selections[date]
        positions = cache.get(key)
        if positions is None:
            self.selection_misses += 1
            removed = reserved_key | ops_key | blocked_new_key
            positions = np.fromiter((i for i, ticker in enumerate(self.input_order[date])
                                     if ticker not in removed), dtype=np.int64)
            cache[key] = positions
            if len(cache) > self.SELECTION_KEYS_PER_DAY:
                cache.popitem(last=False)
        else:
            self.selection_hits += 1
            cache.move_to_end(key)
        if len(positions) == len(source_day):
            return source_day.copy(deep=True)
        return source_day.iloc[positions].copy(deep=True)


def _replace_one(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("REFERENCE_INPUT_BLOCK_CHANGED")
    return source.replace(old, new)


def _fast_input_branches(source):
    source = _replace_one(source,
        '    asofs = {pd.Timestamp(d): pd.Timestamp(v) for d, v in (signal_asof or {}).items()}',
        '    asofs = ({pd.Timestamp(d): pd.Timestamp(v) for d, v in (signal_asof or {}).items()}\n'
        '             if prepared_inputs is None else prepared_inputs.parsed_asofs(signal_asof))')
    source = _replace_one(source,
        '        source_day = frames.get(date, fs.iloc[:0])',
        '        source_day = (frames.get(date, fs.iloc[:0]) if prepared_inputs is None\n'
        '                      else prepared_inputs.signal_frame(date))')
    old = ('            decision_day = source_day.loc[~source_day.ticker.isin(reserved | set(external_ops)) & ~(\n'
           '                source_day.ticker.isin(buy_restricted) & ~source_day.ticker.isin(holdings))].copy(deep=True)')
    source = _replace_one(source, old,
        '            if prepared_inputs is None:\n' +
        ''.join('    '+line+'\n' for line in old.splitlines()).rstrip('\n') +
        '\n            else:\n'
        '                decision_day = prepared_inputs.decision_frame(\n'
        '                    date, source_day, reserved, external_ops, buy_restricted, holdings)')
    old = ('            eligible = dict(zip(source_day.ticker, source_day.new_buy_eligible.fillna(False).astype(bool))) '
           'if "new_buy_eligible" in source_day else dict.fromkeys(input_names, True)')
    source = _replace_one(source, old,
        '            if prepared_inputs is None:\n    ' + old +
        '\n            else:\n                eligible = prepared_inputs.eligible[date].copy()')
    return source


def _compile_fast_reference():
    builder = inspect.getsource(cached._compile_cached_reference)
    builder = _replace_one(builder, '    namespace=reference.__dict__.copy()',
                           '    source=_fast_input_branches(source)\n'
                           '    namespace=reference.__dict__.copy()')
    namespace = cached.__dict__.copy()
    namespace['_fast_input_branches'] = _fast_input_branches
    exec(compile(builder, __file__, 'exec'), namespace)
    return namespace['_compile_cached_reference']()


run_replay = _compile_fast_reference()
