"""2025-only zero-update ensemble control using the frozen action formula."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import rl_policy as rl  # noqa: E402
from rl_initial_test import combined  # noqa: E402
from rl_reconstruct import make_initial  # noqa: E402


def main():
    torch.set_num_threads(1)
    panel, _ = rl.load_research_panel()
    norm = np.load(rl.OUT / "normalization.npz")
    days = rl.build_days(panel, norm["mean"], norm["scale"])
    dates = sorted(panel.loc[panel.signal_date.ge(rl.TRAIN_END), "signal_date"].unique())
    safe = rl.load_module("audit_rl_safe_init_val", rl.OLD / "safe_inputs.py")
    _, prices, _, _ = safe.load_inputs()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    next_day = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(calendar[:-1], calendar[1:])}
    executions = [next_day[pd.Timestamp(d)] for d in dates if pd.Timestamp(d) in next_day]
    by_execution = {next_day[pd.Timestamp(d)]: pd.Timestamp(d) for d in dates if pd.Timestamp(d) in next_day}
    models = [make_initial(s).eval() for s in rl.SEEDS]
    def callback(signal, shares, pre_values, nav):
        with torch.no_grad():
            return combined(models, days[pd.Timestamp(signal)], shares, pre_values, nav)[2]
    e5 = rl.load_module("audit_rl_e5_init_val", rl.E5)
    replay = rl.dynamic_e5_replay(e5)
    result = replay("AUDIT_RL_INIT_ENSEMBLE_2025", callback, prices, executions, by_execution)
    frozen = pd.read_parquet(rl.OUT / "validation_ensemble_daily.parquet")
    assert result.daily.execution_date.equals(frozen.execution_date)
    metrics = {"zero_update_ensemble_final_nav": float(result.daily.nav.iloc[-1]),
               "selected_ensemble_final_nav": float(frozen.nav.iloc[-1]),
               "zero_update_mean_cash": float(result.daily.cash_weight.mean()),
               "selected_mean_cash": float(frozen.cash_weight.mean()),
               "zero_update_turnover": float(result.daily.turnover.sum()),
               "selected_turnover": float(frozen.turnover.sum()),
               "dates": len(frozen)}
    (OUT / "rl_initial_validation_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
