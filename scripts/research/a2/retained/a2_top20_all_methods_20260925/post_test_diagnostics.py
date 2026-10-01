"""Descriptive diagnostics after the frozen score; never changes a policy."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, mean_pinball_loss

import rl_policy

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "test2026"


def main():
    score = json.loads((OUT / "score_receipt.json").read_text(encoding="utf-8"))
    if score["status"] != "FROZEN_2026_SCORE_COMPLETE":
        raise RuntimeError("FROZEN_SCORE_MISSING")
    pred = pd.read_parquet(OUT / "predictions.parquet")
    e5 = rl_policy.load_module("a2_e5_post_test_diagnostic", rl_policy.E5)
    _, prices, _ = e5.load_2026_prices(set(pred.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le("2026-09-24")]
    cal = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    dates = pd.DataFrame({"signal_date": cal, "entry_date": pd.Series(cal).shift(-1),
                          "maturity_date": pd.Series(cal).shift(-6)})
    label = pred[["signal_date", "ticker", "raw_rank", "pred_ridge", "pred_elastic",
                  "pred_hgb", "pred_mlp_mean", "pred_logistic", "pred_q10", "pred_q50", "pred_q90"]]
    label = label.merge(dates, on="signal_date", how="left", validate="many_to_one")
    opens = prices[["trade_date", "ticker", "open"]]
    label = label.merge(opens.rename(columns={"trade_date": "entry_date", "open": "entry_open"}),
                        on=["entry_date", "ticker"], how="left", validate="many_to_one")
    label = label.merge(opens.rename(columns={"trade_date": "maturity_date", "open": "maturity_open"}),
                        on=["maturity_date", "ticker"], how="left", validate="many_to_one")
    label["y5"] = label.maturity_open / label.entry_open - 1
    label.loc[~np.isfinite(label.y5), "y5"] = np.nan
    matured = label.loc[label.y5.notna()].copy()
    rows = []
    for col in ("pred_ridge", "pred_elastic", "pred_hgb", "pred_mlp_mean"):
        rows.append({"model": col, "task": "return_mean", "mae": float(np.mean(abs(matured.y5 - matured[col]))),
                     "rows": len(matured)})
    event = matured.y5.gt(.001).astype(int)
    rows.append({"model": "pred_logistic", "task": "net_positive_probability",
                 "log_loss": float(log_loss(event, np.clip(matured.pred_logistic, 1e-6, 1-1e-6))),
                 "event_rate": float(event.mean()), "rows": len(matured)})
    for col, q in (("pred_q10", .1), ("pred_q50", .5), ("pred_q90", .9)):
        rows.append({"model": col, "task": "conditional_quantile", "pinball":
                     float(mean_pinball_loss(matured.y5, matured[col], alpha=q)),
                     "below_fraction": float((matured.y5 <= matured[col]).mean()), "rows": len(matured)})
    pd.DataFrame(rows).to_csv(OUT / "prediction_quality.csv", index=False)
    coverage = {"submitted_predictions": len(pred), "signal_dates": pred.signal_date.nunique(),
                "last_signal": str(pred.signal_date.max().date()),
                "first_matured_signal": str(matured.signal_date.min().date()),
                "last_matured_signal": str(matured.signal_date.max().date()),
                "matured_price_label_rows": len(matured), "unmatured_or_missing_price_rows": len(label)-len(matured),
                "quantile_crossing_rows": int((pred.pred_q10.gt(pred.pred_q50) | pred.pred_q50.gt(pred.pred_q90)).sum()),
                "price_last_execution": score["price_last_session"],
                "scope": "Post-freeze price-coordinate diagnostics; no retraining or selection"}
    (OUT / "coverage_diagnostics.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    raw = pd.read_parquet(OUT / "raw_daily.parquet").sort_values("execution_date")
    block = 20
    rng = np.random.default_rng(20260925)
    uncertainty = []
    for name in ("hgb_diag_5", "hgb_factor_5", "rl_seed_20260925", "rl_seed_20260926", "rl_ensemble"):
        x = pd.read_parquet(OUT / f"{name}_daily.parquet").sort_values("execution_date")
        if not x.execution_date.reset_index(drop=True).equals(raw.execution_date.reset_index(drop=True)):
            raise RuntimeError("DATE_MISMATCH")
        diff = np.log1p(x.net_return.to_numpy(float)) - np.log1p(raw.net_return.to_numpy(float))
        n = len(diff)
        sims = []
        for _ in range(500):
            starts = rng.integers(0, n, size=int(np.ceil(n / block)))
            idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
            sims.append(float(np.exp(diff[idx].sum()) - 1))
        uncertainty.append({"candidate": name.upper(), "relative_nav": float(np.exp(diff.sum()) - 1),
                            "date_block_bootstrap_lower_2p5": float(np.quantile(sims, .025)),
                            "date_block_bootstrap_upper_97p5": float(np.quantile(sims, .975)),
                            "block_sessions": block, "replicates": 500,
                            "interpretation": "descriptive; historical 2026 exposure and price proxy"})
    pd.DataFrame(uncertainty).to_csv(OUT / "paired_block_uncertainty.csv", index=False)
    print(coverage)
    print(pd.DataFrame(uncertainty).to_string(index=False))


if __name__ == "__main__":
    main()
