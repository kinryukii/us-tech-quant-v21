"""Original A2 scores, extending the old H2 common-account reference rule."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from pathlib import Path
OLD = Path(__file__).resolve().parent.parent / 'a2_pto_full_compat_20260928_r2'
if str(OLD) not in sys.path:
    sys.path.insert(1, str(OLD))
import numpy as np
from fast_account import TargetDecision

class RawA2ScoreReferencePolicy:
    """Score ranks only; no one-day-mu threshold or inferred return units."""
    def __init__(self, raw_scores):
        self.raw_scores = np.asarray(raw_scores, dtype=float)

    def __call__(self, day, ctx):
        count, names = ctx.current_units.shape
        if count != 1:
            raise ValueError('RAW_A2_REFERENCE_IS_ONE_INDEPENDENT_ACCOUNT')
        active = np.isfinite(ctx.nav) & (ctx.nav > 0) & np.isfinite(ctx.current_weights).all(axis=1)
        mask = ctx.decision_mask & active[:, None]
        score = self.raw_scores[day]
        if not np.isfinite(score[mask[0]]).all():
            raise ValueError('MISSING_RAW_A2_SCORE_IS_NOT_A_ZERO_SCORE')
        candidates = mask[0] & (ctx.buy_allowed[0] | (ctx.current_units[0] > 1e-10))
        selected = np.argsort(-np.where(candidates, score, -np.inf), kind='stable')
        selected = selected[candidates[selected]][:min(20, int(ctx.available_slots[0]))]
        target = np.zeros((1, names))
        if len(selected):
            per_name = min(.0475, max(0., float(ctx.available_budget[0])) / len(selected))
            target[0, selected] = per_name
            sell_only = ~ctx.buy_allowed[0, selected]
            target[0, selected[sell_only]] = np.minimum(
                target[0, selected[sell_only]], ctx.current_weights[0, selected[sell_only]])
        return TargetDecision(target, mask,
                              np.asarray([f'original_a2_raw_score|old_h2_reference_rule|{ctx.signal_date.date()}'], dtype=object))
