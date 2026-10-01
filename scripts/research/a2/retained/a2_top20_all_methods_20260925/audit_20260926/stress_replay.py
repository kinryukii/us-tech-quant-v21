"""One symmetric prediction-pressure pair; no training or policy selection."""
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
import risk_aux
import rl_policy
from close_clock import close_clock_replay, replay_supervised


def main():
    if (AUDIT / "stress_replay.csv").exists():
        raise RuntimeError("ALREADY_RUN")
    pred = pd.read_parquet(ROOT / "test2026" / "predictions.parquet")
    trials = pd.read_csv(ROOT / "supervised_trials.csv")
    mae = float(trials.loc[trials.fold.eq("2025") & trials.model.eq("HGB"), "mae"].iloc[0])
    epsilon = .05 * mae
    e5 = rl_policy.load_module("audit_e5_stress", rl_policy.E5)
    replay = close_clock_replay(e5)
    _, prices, lineage = e5.load_2026_prices(set(pred.ticker.astype(str)))
    assert lineage == json.loads((ROOT / "test2026" / "score_receipt.json").read_text(encoding="utf-8"))["price_lineage"]
    prices = prices.loc[prices.trade_date.le("2026-09-24")]
    risk = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    rows = []
    for direction, label in ((-1, "MINUS"), (1, "PLUS")):
        shifted = pred.copy()
        shifted["pred_hgb"] = shifted.pred_hgb + direction * epsilon * np.where(
            shifted.raw_rank.astype(int) % 2 == 0, 1., -1.)
        result, target = replay_supervised(replay, f"STRESS_{label}",
                    optimize_route.SPECS["HGB_DIAG_5"], shifted, prices, risk,
                    "2026-01-01", "2026-09-25")
        result.daily.to_parquet(AUDIT / f"stress_{label.lower()}_daily.parquet", index=False)
        target.to_parquet(AUDIT / f"stress_{label.lower()}_targets.parquet", index=False)
        rows.append({"scenario": label, "pre2026_hgb_mae": mae, "symmetric_epsilon": epsilon,
                     "end_nav": float(result.daily.nav.iloc[-1]),
                     "mean_cash": float(result.daily.cash_weight.mean()),
                     "turnover": float(result.daily.turnover.sum()),
                     "fees": float(result.daily.transaction_cost_amount.sum()),
                     "max_drawdown": float((result.daily.nav / result.daily.nav.cummax() - 1).min())})
        print(label, rows[-1], flush=True)
    baseline = pd.read_parquet(AUDIT / "hgb_diag_5_daily.parquet")
    rows.append({"scenario": "UNPERTURBED", "pre2026_hgb_mae": mae, "symmetric_epsilon": epsilon,
                 "end_nav": float(baseline.nav.iloc[-1]), "mean_cash": float(baseline.cash_weight.mean()),
                 "turnover": float(baseline.turnover.sum()),
                 "fees": float(baseline.transaction_cost_amount.sum()),
                 "max_drawdown": float((baseline.nav / baseline.nav.cummax() - 1).min())})
    pd.DataFrame(rows).to_csv(AUDIT / "stress_replay.csv", index=False)


if __name__ == "__main__":
    main()
