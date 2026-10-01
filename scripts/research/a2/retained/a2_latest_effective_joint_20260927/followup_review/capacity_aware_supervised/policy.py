"""Thin loader for the frozen capacity-aware joint HGB; no account logic."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

import joint_linear_tree as original


class CapacityAwareHGBPolicy:
    def __init__(self, stage: str, artifacts_root: Path):
        if stage not in ("validation", "final"):
            raise ValueError("UNKNOWN_CAPACITY_HGB_STAGE")
        self.stage = stage
        self.artifacts_root = Path(artifacts_root).resolve()
        receipt = json.loads((self.artifacts_root / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
        if receipt["status"] != "PASS" or receipt["revision"] != "CAPACITY_AWARE_HGB_ONE_STEP_R1" or \
           receipt["fit_calls"] != 2:
            raise RuntimeError("CAPACITY_HGB_FIT_RECEIPT_INCOMPLETE")
        matching = [r for r in receipt["fits"] if r["stage"] == stage and r["name"] == "hgb"]
        if len(matching) != 1:
            raise RuntimeError("CAPACITY_HGB_STAGE_MISSING")
        record = matching[0]
        self.design_columns = int(record["design_columns"])
        artifact = self.artifacts_root / Path(record["artifact"]).name
        if original.sha(artifact) != record["artifact_sha256"]:
            raise RuntimeError("CAPACITY_HGB_ARTIFACT_HASH_CHANGED")
        self.model = joblib.load(artifact)
        self.last_actions = None

    def __call__(self, day: pd.DataFrame, weights: dict[str, float], cash: float,
                 held_age: dict[str, int] | None = None) -> dict[str, float]:
        if day.empty or day.signal_date.nunique() != 1 or day.ticker.duplicated().any():
            raise ValueError("EXPECTED_UNIQUE_SIGNAL_DAY_POOL")
        nav = float(day.attrs.get("signal_close_nav", np.nan))
        if not np.isfinite(nav) or nav <= 0:
            raise RuntimeError("SIGNAL_CLOSE_NAV_CONTEXT_MISSING")
        if not np.isfinite(cash) or cash < -1e-8 or cash > 1 + 1e-8:
            raise ValueError("INVALID_CASH_WEIGHT")
        day = day.sort_values("ticker", kind="mergesort").reset_index(drop=True)
        x = day[original.FEATURES].to_numpy(float)
        if not np.isfinite(x).all():
            raise RuntimeError("NONFINITE_POLICY_FEATURES")
        current = day.ticker.map(weights).fillna(0).to_numpy(float)
        age = day.ticker.map(held_age or {}).fillna(0).to_numpy(float)
        action = np.tile(original.ACTIONS, len(day))
        n_actions = len(original.ACTIONS)
        design = original.mapped_features(
            np.repeat(x, n_actions, axis=0), np.repeat(current, n_actions),
            np.full(len(action), cash), np.repeat(age, n_actions), action)
        adv = pd.to_numeric(day.avg_dollar_volume_20d, errors="coerce").to_numpy(float)
        capacity_weight = np.where(np.isfinite(adv) & (adv > 0), .01 * adv / nav, 0.)
        design = np.column_stack((design, np.repeat(capacity_weight, n_actions)))
        if design.shape[1] != self.design_columns or not np.isfinite(design).all():
            raise RuntimeError("CAPACITY_HGB_DESIGN_MISMATCH")
        with threadpool_limits(limits=2):
            scores = self.model.predict(design).reshape(len(day), n_actions)
        if not np.isfinite(scores).all():
            raise RuntimeError("NONFINITE_CAPACITY_HGB_SCORE")
        eligible = day.new_buy_eligible.to_numpy(bool) if "new_buy_eligible" in day else np.ones(len(day), bool)
        allowed = eligible[:, None] | (original.ACTIONS[None, :] <= current[:, None] + 1e-10)
        targets, selected = original.allocate_joint_scores(scores, day.ticker.tolist(), allowed=allowed)
        self.last_actions = day[["signal_date", "ticker"]].copy()
        self.last_actions["current_weight"] = current
        self.last_actions["cash_weight"] = cash
        self.last_actions["signal_close_nav"] = nav
        self.last_actions["capacity_weight"] = capacity_weight
        self.last_actions["target_weight"] = original.ACTIONS[selected]
        self.last_actions["selected_action_value"] = scores[np.arange(len(day)), selected]
        self.last_actions["action_zero_value"] = scores[:, 0]
        return targets


def load_policy_capacity_hgb(stage: str, artifacts_root: Path) -> CapacityAwareHGBPolicy:
    return CapacityAwareHGBPolicy(stage=stage, artifacts_root=artifacts_root)
