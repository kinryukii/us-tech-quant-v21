"""Uniform implementation repair: E5 targets observe its actual share state."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import test2026 as original

ROOT = Path(__file__).resolve().parent


def dynamic_e5_replay(e5: object):
    """Reuse E5 accounting verbatim, changing only its target lookup seam."""
    source = inspect.getsource(e5.replay)
    old = "target = targets.get(signal, {}) if signal is not None else {}"
    new = "target = targets(signal, shares.copy(), pre_values.copy(), pretrade_nav) if signal is not None else {}"
    if source.count(old) != 1:
        raise RuntimeError("E5_TARGET_LOOKUP_SEAM_CHANGED")
    source = source.replace("def replay(", "def dynamic_replay(", 1).replace(old, new, 1)
    namespace = vars(e5)
    exec(compile(source, str(original.E5), "exec"), namespace)
    return namespace["dynamic_replay"]


def callback_for(pred: pd.DataFrame, column: str | None, mode: str, name: str):
    days = {pd.Timestamp(d): group.sort_values(["raw_rank", "ticker"]) for d, group in pred.groupby("signal_date")}
    actions = []

    def target(signal: pd.Timestamp, shares: dict, pre_values: dict, nav: float) -> dict[str, float]:
        held = set(shares)
        day = days.get(pd.Timestamp(signal))
        if day is None or len(day) < 40 or int(day.raw_rank.le(20).sum()) != 20:
            actions.append({"candidate": name, "signal_date": signal, "ticker": None,
                            "mode": mode, "action": "CARRY_INCOMPLETE_RANKING", "actual_held": len(held)})
            return {t: float(v / nav) for t, v in pre_values.items() if v > 0}
        raw = set(day.loc[day.raw_rank.le(20), "ticker"])
        wanted = set()
        for row in day.itertuples():
            old = row.ticker in held
            new = row.ticker in raw and not old
            p = float(getattr(row, column)) if column else np.nan
            if mode == "RAW":
                allow = row.ticker in raw
            elif mode == "BUY_ONLY":
                allow = (old and row.ticker in raw) or (new and p > 0.001)
            elif mode == "EXIT_ONLY":
                allow = new or (old and p > 0.0005)
            elif mode == "JOINT":
                allow = (new and p > 0.001) or (old and p > 0.0005)
            else:
                raise ValueError(mode)
            if allow:
                wanted.add(row.ticker)
            if new or old:
                actions.append({"candidate": name, "signal_date": signal, "ticker": row.ticker,
                                "mode": mode, "action": "BUY" if allow and new else "HOLD" if allow else "EXIT" if old else "WAIT",
                                "raw_rank": row.raw_rank, "prediction": p})
        # A held security outside the available Top40 has no current score;
        # the frozen policy forces it out, and E5 records any blocked sell.
        return {t: 0.05 for t in sorted(wanted)}

    return target, actions


def main() -> None:
    freeze = original.freeze()  # verifies all original frozen model and evaluator hashes
    receipt = json.loads((ROOT / "2026_prediction_receipt.json").read_text(encoding="utf-8"))
    assert original.digest(ROOT / "2026_predictions.parquet") == receipt["prediction_sha256"]
    assert (ROOT / "2026_metrics.csv").is_file() and not (ROOT / "2026_metrics_corrected.csv").exists()
    pred = pd.read_parquet(ROOT / "2026_predictions.parquet")
    spec = importlib.util.spec_from_file_location("a2_e5_actual_state", original.E5)
    assert spec and spec.loader
    e5 = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = e5
    spec.loader.exec_module(e5)
    dynamic_replay = dynamic_e5_replay(e5)
    _, prices, lineage = e5.load_2026_prices(set(pred.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le(original.ASOF_DAY)].copy()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    next_day = {pd.Timestamp(calendar[i]): pd.Timestamp(calendar[i + 1]) for i in range(len(calendar) - 1)}
    all_signals = pd.DatetimeIndex(sorted(pred.signal_date.unique()))
    execution = [next_day[pd.Timestamp(d)] for d in all_signals if pd.Timestamp(d) in next_day]
    signal_by_execution = {next_day[pd.Timestamp(d)]: pd.Timestamp(d) for d in all_signals if pd.Timestamp(d) in next_day}
    specs = [("RAW", None, "RAW"), ("RIDGE", "p_RIDGE_20260925", "JOINT"),
             ("HGB", "p_HGB_20260925", "JOINT"),
             ("MLP_JOINT", "p_MLP_MEAN", "JOINT"),
             ("MLP_BUY_ONLY", "p_MLP_MEAN", "BUY_ONLY"),
             ("MLP_EXIT_ONLY", "p_MLP_MEAN", "EXIT_ONLY")]
    metrics, paths, trades, actions = [], [], [], []
    for name, column, mode in specs:
        callback, log = callback_for(pred, column, mode, name)
        result = dynamic_replay(name, callback, prices, execution, signal_by_execution)
        x = result.daily
        metrics.append({"candidate": name, "status": "SCORED_ACTUAL_STATE", "sessions": len(x),
                        "first_execution": x.execution_date.min(), "last_execution": x.execution_date.max(),
                        "net_return": float(x.nav.iloc[-1] - 1),
                        "max_drawdown": float((x.nav / x.nav.cummax() - 1).min()),
                        "turnover_sum": float(x.turnover.sum()),
                        "cost_sum_nav_fraction": float(x.transaction_cost_fraction.sum()),
                        "mean_cash_weight": float(x.cash_weight.mean()),
                        "skipped_buys": int(x.skipped_buy_count.sum()),
                        "blocked_sells": int(x.blocked_sell_count.sum()),
                        "final_nav": float(x.nav.iloc[-1])})
        paths.append(x)
        trades.append(result.trades)
        actions.append(pd.DataFrame(log))
    pd.DataFrame(metrics).to_csv(ROOT / "2026_metrics_corrected.csv", index=False)
    pd.concat(paths, ignore_index=True).to_parquet(ROOT / "2026_daily_paths_corrected.parquet", index=False)
    pd.concat(trades, ignore_index=True).to_parquet(ROOT / "2026_trades_corrected.parquet", index=False)
    pd.concat(actions, ignore_index=True).to_parquet(ROOT / "2026_actions_corrected.parquet", index=False)
    record = {"status": "UNIFORM_IMPLEMENTATION_REPAIR", "original_evaluator_sha256": freeze["evaluation_code_sha256"],
              "original_metrics_sha256": original.digest(ROOT / "2026_metrics.csv"),
              "corrected_source_sha256": original.digest(Path(__file__)),
              "e5_source_sha256": original.digest(original.E5),
              "prediction_sha256": receipt["prediction_sha256"],
              "repair": "E5 target callback receives actual shares after prior executions; skipped buys cannot become fictional holdings. All candidate models, thresholds, cost, dates and price source unchanged.",
              "source_lineage": lineage,
              "test_last_price_session": str(calendar.max().date()),
              "fit_calls": 0, "selection_after_2026": False,
              "total_return_status": "UNVERIFIED_QFQ_PRICE_COORDINATE"}
    (ROOT / "2026_correction_receipt.json").write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(pd.DataFrame(metrics).to_string(index=False))


if __name__ == "__main__":
    main()
