"""Thin cooperative policies over the original frozen experts and allocator."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE_ROOT = ROOT.parent / 'a2_top20_multimodel_selection_20260928_9231'
sys.path.insert(0, str(BASE_ROOT))
import ensemble as original
import values as vm
from engine_v2 import HoldingAwareDecision

BASE_NAMES = original.BASE_NAMES
FIXED = np.array([.05, .15, .10, .35, .20, .15])
NAMES = ['fusion_fixed_non_equal', 'fusion_learned_weights',
         'fusion_nonlinear_stacking', 'fusion_conditional_gate',
         'fusion_hgb_then_linear', 'fusion_linear_then_hgb', 'fusion_target_decisions']


def inference_frame(day, ranks, downside, current, cash, age):
    n = len(day)
    frame = pd.DataFrame(ranks.reshape(-1, 6), columns=original.RANK_COLUMNS)
    frame['q10_downside_rank'] = downside.reshape(-1)
    frame['current_weight'] = np.repeat(np.broadcast_to(np.asarray(current), (n,)), 5)
    frame['cash_weight'] = np.repeat(np.broadcast_to(np.asarray(cash), (n,)), 5)
    frame['age'] = np.repeat(np.broadcast_to(np.asarray(age), (n,)), 5)
    frame['action'] = np.tile(vm.ACTIONS, n)
    for name in ['realized_vol_20d', 'ret_20d']:
        frame[name] = np.repeat(day[name].to_numpy(float), 5)
    return frame


def allocate(scores, tickers, current, eligible, slots=20, exposure=.95):
    allowed = eligible[:, None] | (vm.ACTIONS[None, :] <= current[:, None] + 1e-10)
    _, chosen = vm.allocate_joint_scores(scores, tickers, max_names=slots,
        max_units=min(38, int(np.floor((exposure + 1e-12) / .025))), allowed=allowed)
    return vm.ACTIONS[chosen], allowed


class CooperativePolicy:
    def __init__(self, name, stage='final'):
        if name not in NAMES or stage not in vm.STAGES:
            raise ValueError('UNKNOWN_COOPERATIVE_POLICY_OR_STAGE')
        self.name, self.stage = name, stage
        self.base = original.BasePredictions(stage)
        self.age = {}
        self.meta = None
        if name in ['fusion_learned_weights', 'fusion_nonlinear_stacking',
                    'fusion_hgb_then_linear', 'fusion_linear_then_hgb']:
            from meta_models import MetaModels
            self.meta = MetaModels(name, stage)
        elif name == 'fusion_conditional_gate':
            from gate import GateModel
            self.meta = GateModel(stage)

    def score(self, day, current=0., cash=.95, age=0., *, slots=20, exposure=.95, restricted=(), base_outputs=None):
        """No labels/future prices accepted; scores are conditional preferences."""
        n = len(day)
        current = np.broadcast_to(np.asarray(current, float), (n,)).copy()
        age = np.broadcast_to(np.asarray(age, float), (n,)).copy()
        if base_outputs is None:
            base_outputs = self.base.predict(day, current, cash, age,
                max_names=slots, max_exposure=exposure, restricted=restricted)
        ranks, downside, raw, projected = base_outputs
        frame = inference_frame(day, ranks, downside, current, cash, age)
        diagnostic = {}
        eligible = day.new_buy_eligible.to_numpy(bool) & ~day.ticker.isin(restricted).to_numpy()
        if self.name == 'fusion_fixed_non_equal':
            terms = ranks * FIXED[None, None, :]
            scores = terms.sum(axis=-1)
            diagnostic['weights'] = np.broadcast_to(FIXED, (n, 5, 6))
            diagnostic['contributions'] = terms
        elif self.name == 'fusion_conditional_gate':
            scores, weights = self.meta.predict(frame)
            scores = np.asarray(scores).reshape(n, 5)
            weights = np.asarray(weights).reshape(n, 5, 6)
            assert np.allclose(weights, weights[:, :1, :], atol=1e-7)
            diagnostic['weights'] = weights
            diagnostic['contributions'] = ranks * weights * self.meta.output_scale
            assert np.allclose(diagnostic['contributions'].sum(axis=-1), scores, atol=1e-8)
            diagnostic['gate_output_scale'] = float(self.meta.output_scale)
        elif self.name == 'fusion_target_decisions':
            experts = []
            for base in BASE_NAMES:
                if base == 'mlp':
                    target = projected.copy()
                else:
                    target, _ = allocate(raw[base], day.ticker.tolist(), current, eligible, slots, exposure)
                experts.append(target)
            targets = np.column_stack(experts)
            contributions = targets * FIXED[None, :]
            mixed = contributions.sum(axis=-1)
            scores = -((vm.ACTIONS[None, :] - mixed[:, None]) / .1) ** 2
            diagnostic['expert_target_weights'] = targets
            diagnostic['target_contributions'] = contributions
            diagnostic['mixed_target'] = mixed
        else:
            prediction, info = self.meta.predict(frame)
            scores = np.asarray(prediction, float).reshape(n, 5)
            for key, value in info.items():
                array = np.asarray(value)
                diagnostic[key] = array.reshape((n, 5) + array.shape[1:]) if array.ndim and len(array) == n * 5 else value
        scores = np.asarray(scores, float)
        scores = scores - scores[:, :1]
        for key, value in list(diagnostic.items()):
            if isinstance(value, np.ndarray) and value.ndim >= 2 and value.shape[:2] == (n, 5):
                if 'prediction' in key or 'contribution' in key or 'sensitivity' in key:
                    diagnostic[key] = value - value[:, :1, ...]
        if not np.isfinite(scores).all() or not np.allclose(scores[:, 0], 0.):
            raise ValueError('INVALID_COOPERATIVE_SCORES')
        return scores, ranks, downside, raw, projected, diagnostic

    def __call__(self, day, ctx):
        self.age = {t: self.age.get(t, 0) + 1 for t, w in ctx.current_weights.items() if w > 0}
        day = day.loc[day.new_buy_eligible.astype(bool)
                      | day.ticker.map(ctx.current_weights).fillna(0).gt(0)]
        day = day.sort_values('ticker', kind='stable').reset_index(drop=True)
        if day.empty:
            return HoldingAwareDecision()
        current = np.array([ctx.current_weights.get(t, 0.) for t in day.ticker])
        age = np.array([self.age.get(t, 0.) for t in day.ticker])
        scores, ranks, downside, raw, projected, extra = self.score(day, current, ctx.cash_weight, age,
            slots=ctx.available_slots, exposure=ctx.available_weight, restricted=ctx.buy_restricted_tickers)
        eligible = day.new_buy_eligible.to_numpy(bool) & ~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
        weights, _ = allocate(scores, day.ticker.tolist(), current, eligible,
                              ctx.available_slots, ctx.available_weight)
        decisions = dict(zip(day.ticker, weights))
        outputs = {}
        for i, ticker in enumerate(day.ticker):
            row = {'base_action_values': {key: value[i].tolist() for key, value in raw.items()},
                   'base_rank_advantages': {key: ranks[i, :, j].tolist() for j, key in enumerate(BASE_NAMES)},
                   'base_disagreement': ranks[i].std(axis=-1).tolist(),
                   'q10_downside_rank': downside[i].tolist(),
                   'fused_action_values': scores[i].tolist(),
                   'mlp_projected_weight': float(projected[i]), 'chosen_weight': float(weights[i]),
                   'cooperation_design': self.name}
            for key, value in extra.items():
                if isinstance(value, np.ndarray) and value.ndim and len(value) == len(day):
                    row[key] = value[i].tolist()
                elif np.isscalar(value):
                    row[key] = float(value) if isinstance(value, (int, float, np.number)) else value
            outputs[str(ticker)] = row
        return HoldingAwareDecision(model_decisions={str(k): float(v) for k, v in decisions.items()},
                                    raw_model_outputs=outputs)
