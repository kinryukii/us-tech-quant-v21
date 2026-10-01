"""Predictive and target-level collaboration through one frozen account context."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np

ENGINE = Path(__file__).resolve().parent.parent / "a2_buy_sell_cash_multimodel_20260928"
sys.path.insert(0, str(ENGINE))
from engine_v2 import HoldingAwareDecision

BASES = ["ridge", "hgb", "mlp"]
COMBINATIONS = ["fixed_pred", "learned_fixed", "stack_ridge", "stack_mlp", "conditional_gate",
                "ridge_then_hgb", "hgb_then_ridge", "decision_blend"]
POLICIES = ["base_ridge", "base_hgb", "base_mlp", *COMBINATIONS]


def checked_context(slots, budget):
    if not np.isfinite(slots) or int(slots) != slots or slots < 0 or not np.isfinite(budget) or budget < 0:
        raise ValueError("INVALID_CONTEXT_BUDGET")
    return min(20, int(slots)), float(budget)


def checked_coefficients(coefficients):
    c = np.asarray(coefficients, float)
    if c.shape != (3,) or not np.isfinite(c).all() or (c < 0).any() or abs(c.sum() - 1) > 1e-7:
        raise ValueError("INVALID_FROZEN_COEFFICIENTS")
    return c


def rank_targets(scores, names, slots, budget):
    scores = np.asarray(scores, float)
    if scores.shape != (len(names),) or not np.isfinite(scores).all():
        raise ValueError("INVALID_COMMON_TARGET_FORECAST")
    if len(set(names)) != len(names):
        raise ValueError("DUPLICATE_DECISION_NAME")
    slots, budget = checked_context(slots, budget)
    k = min(slots, len(names))
    selected = sorted(range(len(names)), key=lambda i: (-scores[i], names[i]))[:k]
    target = np.zeros(len(names))
    if k:
        target[selected] = min(.0475, float(budget) / k)
    return target


def fuse_targets(matrix, coefficients, names, slots, budget):
    slots, budget = checked_context(slots, budget)
    matrix, c = np.asarray(matrix, float), checked_coefficients(coefficients)
    if matrix.shape != (len(names), 3) or c.shape != (3,) or not np.isfinite(matrix).all():
        raise ValueError("INVALID_MEMBER_TARGETS")
    if (matrix < 0).any() or (matrix > .0475 + 1e-8).any() or len(set(names)) != len(names):
        raise ValueError("INVALID_MEMBER_TARGETS")
    target = matrix @ c
    keep = sorted(range(len(names)), key=lambda i: (-target[i], names[i]))[:int(slots)]
    mask = np.zeros(len(names)); mask[keep] = 1
    target *= mask
    if target.sum() > budget and target.sum() > 0:
        target *= budget / target.sum()
    return target


class CollaborationPolicy:
    def __init__(self, name, coefficients):
        if name not in POLICIES:
            raise ValueError("UNKNOWN_FIXED_DESIGN")
        self.name = name
        self.coefficients = checked_coefficients(coefficients)

    def __call__(self, day, ctx):
        forbidden = {"target", "target_end_date", "target_context_available", "y_next_open", "next_open", "following_open",
                     "label_end_date", "label_available"}
        if forbidden.intersection(day.columns) or any(str(c).startswith("future_") for c in day.columns):
            raise ValueError("FUTURE_OR_LABEL_FIELDS_IN_DECISION_INPUT")
        names = day.ticker.astype(str).tolist()
        if set(names) != set(ctx.decision_tickers):
            raise ValueError("DECISION_DAY_CONTEXT_MISMATCH")
        raw = {}
        predictions = day[[f"p_{b}" for b in BASES]].to_numpy(float)
        if self.name == "decision_blend":
            matrix = np.column_stack([rank_targets(day[f"p_{b}"], names, ctx.available_slots, ctx.available_weight) for b in BASES])
            weights = fuse_targets(matrix, self.coefficients, names, ctx.available_slots, ctx.available_weight)
            raw = {ticker: {"base_targets": matrix[i].tolist(), "coefficients": self.coefficients.tolist(),
                            "mapped_weight": float(weights[i])} for i, ticker in enumerate(names)}
        else:
            col = "p_" + self.name.removeprefix("base_") if self.name.startswith("base_") else "f_" + self.name
            scores = day[col].to_numpy(float)
            weights = rank_targets(scores, names, ctx.available_slots, ctx.available_weight)
            gate = day[[f"gate_{b}" for b in BASES]].to_numpy(float) if self.name == "conditional_gate" else None
            for i, ticker in enumerate(names):
                item = {"score": float(scores[i]), "base_predictions": predictions[i].tolist(),
                        "mapped_weight": float(weights[i])}
                if self.name == "conditional_gate":
                    item["gate_coefficients"] = gate[i].tolist()
                raw[ticker] = item
        return HoldingAwareDecision(model_decisions=dict(zip(names, map(float, weights))), raw_model_outputs=raw)
