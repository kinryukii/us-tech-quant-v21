"""Frozen RL policy on corrected signal-close clock in original 2025 validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
sys.path.insert(0, str(ROOT))
import optimize_route
import rl_policy
from close_clock import close_clock_replay


def main():
    if (AUDIT / "rl_close_validation.csv").exists():
        raise RuntimeError("ALREADY_RUN")
    old = ROOT.parent / "a2_top20_action_nn_20260925"
    sys.path.insert(0, str(old))
    import safe_inputs
    _, prices, _, _ = safe_inputs.load_inputs()
    panel = pd.read_parquet(ROOT / "pre2026_panel.parquet")
    panel = panel.loc[panel.signal_date.ge("2025-01-01")].copy()
    norm = np.load(ROOT / "rl_artifacts" / "normalization.npz")
    days = rl_policy.build_days(panel, norm["mean"], norm["scale"])
    _, executions, mapping = optimize_route.dates_for(prices, panel, "2025-01-01", "2026-01-01")
    e5 = rl_policy.load_module("audit_e5_rl_close_validation", rl_policy.E5)
    replay = close_clock_replay(e5)
    rows = []
    for label, seed in (("RL_SEED_20260925", 20260925),
                        ("RL_SEED_20260926", 20260926), ("RL_ENSEMBLE", None)):
        callback = rl_policy.frozen_callback(days, seed=seed)
        result = replay(label, callback, prices, executions, mapping)
        result.daily.to_parquet(AUDIT / f"2025_{label.lower()}_close_daily.parquet", index=False)
        original_path = ROOT / "rl_artifacts" / ("validation_ensemble_daily.parquet" if seed is None else f"validation_{seed}_daily.parquet")
        original = pd.read_parquet(original_path)
        assert original.execution_date.reset_index(drop=True).equals(result.daily.execution_date.reset_index(drop=True))
        rows.append({"candidate": label, "original_nav": float(original.nav.iloc[-1]),
                     "close_clock_nav": float(result.daily.nav.iloc[-1]),
                     "nav_change": float(result.daily.nav.iloc[-1] - original.nav.iloc[-1]),
                     "days": len(result.daily)})
    pd.DataFrame(rows).to_csv(AUDIT / "rl_close_validation.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
