"""Post-score descriptive diagnostics; does not select or refit a model."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import test2026 as frozen

ROOT = Path(__file__).resolve().parent


def mean_daily_ic(x: pd.DataFrame, column: str) -> float:
    values = []
    for _, day in x.groupby("signal_date"):
        if len(day) >= 8 and day[column].nunique() > 1 and day.label_return.nunique() > 1:
            values.append(float(spearmanr(day[column], day.label_return).statistic))
    return float(np.mean(values)) if values else float("nan")


def main() -> None:
    frozen.freeze()
    pred = pd.read_parquet(ROOT / "2026_predictions.parquet")
    receipt = json.loads((ROOT / "2026_prediction_receipt.json").read_text(encoding="utf-8"))
    assert frozen.digest(ROOT / "2026_predictions.parquet") == receipt["prediction_sha256"]
    spec = importlib.util.spec_from_file_location("a2_e5_diagnostics", frozen.E5)
    assert spec and spec.loader
    e5 = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = e5
    spec.loader.exec_module(e5)
    _, prices, lineage = e5.load_2026_prices(set(pred.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le(frozen.ASOF_DAY)].copy()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    table = pd.DataFrame({"signal_date": calendar,
                          "entry_date": pd.Series(calendar).shift(-1),
                          "label_end_date": pd.Series(calendar).shift(-21)})
    pred = pred.merge(table, on="signal_date", how="left", validate="many_to_one")
    opens = prices[["trade_date", "ticker", "open"]]
    pred = pred.merge(opens.rename(columns={"trade_date": "entry_date", "open": "entry_open"}),
                      on=["entry_date", "ticker"], how="left", validate="many_to_one")
    pred = pred.merge(opens.rename(columns={"trade_date": "label_end_date", "open": "exit_open"}),
                      on=["label_end_date", "ticker"], how="left", validate="many_to_one")
    pred["label_return"] = pred.exit_open / pred.entry_open - 1.0
    pred["label_status"] = np.where(pred.label_end_date.isna(), "PENDING_20_SESSIONS",
                                    np.where(pred.entry_open.isna() | pred.exit_open.isna(), "MISSING_PRICE", "MATURE"))
    pred.to_parquet(ROOT / "2026_prediction_label_status.parquet", index=False)
    mature = pred.loc[pred.label_status.eq("MATURE")].copy()
    rows = []
    for name, col in (("RIDGE", "p_RIDGE_20260925"), ("HGB", "p_HGB_20260925"),
                      ("MLP_SEED_1", "p_MLP_20260925"), ("MLP_SEED_2", "p_MLP_20260926"),
                      ("MLP_MEAN", "p_MLP_MEAN")):
        x = mature[["signal_date", col, "label_return"]].dropna()
        rows.append({"model": name, "mature_rows": len(x), "dates": x.signal_date.nunique(),
                     "mae": float(np.mean(np.abs(x[col] - x.label_return))),
                     "mean_prediction": float(x[col].mean()), "mean_label": float(x.label_return.mean()),
                     "direction_accuracy": float(np.mean((x[col] > 0) == (x.label_return > 0))),
                     "mean_daily_spearman_ic": mean_daily_ic(x, col)})
    pd.DataFrame(rows).to_csv(ROOT / "2026_prediction_diagnostics.csv", index=False)
    actions = pd.read_parquet(ROOT / "2026_actions_corrected.parquet")
    mlp = actions.loc[actions.candidate.eq("MLP_JOINT") & actions.ticker.notna()]
    mlp = mlp.merge(pred[["signal_date", "ticker", "label_status", "label_return"]],
                    on=["signal_date", "ticker"], how="left", validate="many_to_one")
    mature_act = mlp.loc[mlp.label_status.eq("MATURE")]
    action_counts = {"executed_decision_rows": len(mlp), "mature_action_rows": len(mature_act),
                     "pending_or_missing_action_rows": len(mlp) - len(mature_act),
                     "wait_positive_20d": int((mature_act.action.eq("WAIT") & mature_act.label_return.gt(0)).sum()),
                     "wait_negative_20d": int((mature_act.action.eq("WAIT") & mature_act.label_return.lt(0)).sum()),
                     "exit_positive_20d": int((mature_act.action.eq("EXIT") & mature_act.label_return.gt(0)).sum()),
                     "exit_negative_20d": int((mature_act.action.eq("EXIT") & mature_act.label_return.lt(0)).sum())}
    path = pd.read_parquet(ROOT / "2026_daily_paths_corrected.parquet")
    wide = path.pivot(index="execution_date", columns="candidate", values="net_return")
    raw = np.log1p(wide.RAW.to_numpy(float))
    rng = np.random.default_rng(20260925)
    ci = {}
    block = 20
    for name in ("RIDGE", "HGB", "MLP_JOINT", "MLP_BUY_ONLY", "MLP_EXIT_ONLY"):
        delta = np.log1p(wide[name].to_numpy(float)) - raw
        starts = np.arange(max(1, len(delta) - block + 1))
        values = []
        for _ in range(500):
            indices = np.concatenate([np.arange(s, min(s + block, len(delta))) for s in rng.choice(starts, size=int(np.ceil(len(delta) / block)))])[:len(delta)]
            values.append(float(np.expm1(delta[indices].sum())))
        ci[name] = {"observed_relative_wealth": float(np.expm1(delta.sum())),
                    "block_bootstrap_95pct": [float(v) for v in np.quantile(values, [0.025, 0.975])]}
    summary = {"scope": "POST_SCORE_DESCRIPTIVE_NO_SELECTION", "mature_rows": len(mature),
               "prediction_rows": len(pred), "mature_dates": mature.signal_date.nunique(),
               "label_status_counts": pred.label_status.value_counts().to_dict(),
               "action_counts": action_counts, "block_bootstrap": ci,
               "bootstrap_note": "20-session moving blocks of aligned daily log-return differences; descriptive, historically exposed sample",
               "price_lineage": lineage, "label_coordinate": "2026 QFQ raw open-to-open, distinct from pre2026 PIT_FORWARD_REHAB_INDEX label coordinate",
               "fit_calls": 0, "selection_after_2026": False}
    (ROOT / "2026_diagnostic_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("mature_rows", "prediction_rows", "mature_dates", "label_status_counts", "action_counts")}, indent=2))


if __name__ == "__main__":
    main()
