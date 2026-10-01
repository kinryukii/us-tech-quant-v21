"""Isolated timing repair: signal-close targets, next-open fills, original E5 ledger.

No fitted model, policy parameter, feature, constraint, fee or evaluation date is
changed. Original artifacts remain untouched; this code lives only in audit.
"""
from __future__ import annotations

import argparse
import inspect
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


def close_clock_replay(e5):
    source = inspect.getsource(e5.replay)
    anchor = "signal = signal_by_execution.get(date)"
    old = "target = targets.get(signal, {}) if signal is not None else {}"
    stale = "price = marks.get(ticker, opening(date, ticker))"
    if source.count(anchor) != 1 or source.count(old) != 1 or source.count(stale) != 2:
        raise RuntimeError("E5_SOURCE_SEAM_CHANGED")
    inject = '''signal = signal_by_execution.get(date)
        # Audit repair: decide using the latest close available at signal time.
        # The subsequent execution-open marks may size/fill orders, never revise targets.
        decision_values = {}
        if signal is not None:
            for ticker, qty in shares.items():
                if ticker not in close_wide.columns:
                    raise RuntimeError(f"no signal-close series:{ticker}:{signal}")
                hist = close_wide.loc[close_wide.index <= signal, ticker].dropna()
                hist = hist.loc[np.isfinite(hist.to_numpy(float)) & (hist.to_numpy(float) > 0)]
                if hist.empty:
                    raise RuntimeError(f"no prior signal-close mark:{ticker}:{signal}")
                decision_values[ticker] = qty * float(hist.iloc[-1])
            decision_nav = cash + sum(decision_values.values())
            target = targets(signal, shares.copy(), decision_values.copy(), decision_nav)
        else:
            target = {}'''
    source = source.replace("def replay(", "def close_clock_replay(", 1)
    source = source.replace(anchor, inject, 1)
    source = source.replace(old, "# target fixed at signal close above", 1)
    source = source.replace(stale, "price = opening(date, ticker)")
    exec(compile(source, str(rl_policy.E5), "exec"), vars(e5))
    return e5.close_clock_replay


def replay_supervised(replay, name, spec, panel, prices, bundle, start, stop):
    _, executions, signal_by_execution = optimize_route.dates_for(prices, panel, start, stop)
    days = {pd.Timestamp(d): group for d, group in panel.groupby("signal_date", sort=True)}
    decisions = []
    def target(signal, shares, values, nav):
        group = days[signal]
        if spec is None:
            wanted = {str(t): .05 for t in group.loc[group.raw_rank.le(20), "ticker"]}
            diag = {"solver_failed": False, "raw_targets": wanted.copy()}
        else:
            wanted, diag = optimize_route.solve(group, shares, values, nav, bundle, spec, signal)
        raw = diag["raw_targets"]
        for ticker in sorted(set(shares) | set(wanted) | set(raw)):
            decisions.append({"candidate": name, "signal_date": signal, "ticker": ticker,
                              "signal_close_shares": shares.get(ticker, 0.),
                              "signal_close_weight": values.get(ticker, 0.) / nav,
                              "raw_target_weight": raw.get(ticker, 0.),
                              "target_weight": wanted.get(ticker, 0.),
                              "solver_failed": diag["solver_failed"]})
        return wanted
    result = replay(name, target, prices, executions, signal_by_execution)
    return result, pd.DataFrame(decisions)


def save(name, result, decisions, original_dir):
    base = AUDIT / name.lower()
    result.daily.to_parquet(str(base) + "_daily.parquet", index=False)
    result.trades.to_parquet(str(base) + "_trades.parquet", index=False)
    decisions.to_parquet(str(base) + "_targets.parquet", index=False)
    original = pd.read_parquet(original_dir / f"{name.lower()}_daily.parquet")
    if not original.execution_date.reset_index(drop=True).equals(result.daily.execution_date.reset_index(drop=True)):
        raise RuntimeError(f"REPAIRED_DATE_MISMATCH:{name}")
    return {"candidate": name, "original_nav": float(original.nav.iloc[-1]),
            "close_clock_nav": float(result.daily.nav.iloc[-1]),
            "nav_change": float(result.daily.nav.iloc[-1] - original.nav.iloc[-1]),
            "target_rows": len(decisions), "days": len(result.daily),
            "mean_cash": float(result.daily.cash_weight.mean()),
            "turnover": float(result.daily.turnover.sum()),
            "max_drawdown": float((result.daily.nav / result.daily.nav.cummax() - 1).min()),
            "skipped_buys": int(result.daily.skipped_buy_count.sum()),
            "blocked_sells": int(result.daily.blocked_sell_count.sum()),
            "max_identity_error": float(max(result.daily.nav_identity_error.abs().max(),
                                             result.daily.cost_identity_error.abs().max()))}


def run2026():
    if (AUDIT / "close_clock_2026_summary.csv").exists():
        raise RuntimeError("AUDIT_REPAIR_ALREADY_RUN")
    manifest = json.loads((ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
    pred = pd.read_parquet(ROOT / "test2026" / "predictions.parquet")
    e5 = rl_policy.load_module("audit_e5_2026", rl_policy.E5)
    replay = close_clock_replay(e5)
    _, prices, lineage = e5.load_2026_prices(set(pred.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le("2026-09-24")]
    recorded = json.loads((ROOT / "test2026" / "score_receipt.json").read_text(encoding="utf-8"))
    if lineage != recorded["price_lineage"]:
        raise RuntimeError("PRICE_LINEAGE_CHANGED")
    bundle = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    rows = []
    for name, spec in (("RAW", None),
                       ("HGB_DIAG_5", optimize_route.SPECS["HGB_DIAG_5"]),
                       ("HGB_FACTOR_5", optimize_route.SPECS["HGB_FACTOR_5"])):
        result, decisions = replay_supervised(replay, name, spec, pred, prices, bundle,
                                               "2026-01-01", "2026-09-25")
        rows.append(save(name, result, decisions, ROOT / "test2026"))
        print("CLOSE_CLOCK", name, rows[-1]["close_clock_nav"], flush=True)
    norm = np.load(ROOT / "rl_artifacts" / "normalization.npz")
    days = rl_policy.build_days(pred, norm["mean"], norm["scale"])
    _, executions, signal_by_execution = optimize_route.dates_for(prices, pred,
                                                                    "2026-01-01", "2026-09-25")
    for name, seed in manifest["rl_test_policies"].items():
        records = []
        callback = rl_policy.frozen_callback(days, seed=seed, records=records)
        result = replay(name, callback, prices, executions, signal_by_execution)
        targets = pd.DataFrame(records)
        targets["candidate"] = name
        rows.append(save(name, result, targets, ROOT / "test2026"))
        print("CLOSE_CLOCK", name, rows[-1]["close_clock_nav"], flush=True)
    summary = pd.DataFrame(rows)
    summary.to_csv(AUDIT / "close_clock_2026_summary.csv", index=False)
    if abs(summary.set_index("candidate").at["RAW", "nav_change"]) > 1e-12:
        raise RuntimeError("RAW_CONTROL_MUST_MATCH")
    print(summary.to_string(index=False))


def run_pre2026():
    if (AUDIT / "close_clock_pre2026_summary.csv").exists():
        raise RuntimeError("AUDIT_REPAIR_ALREADY_RUN")
    old = ROOT.parent / "a2_top20_action_nn_20260925"
    sys.path.insert(0, str(old))
    import safe_inputs
    _, prices, _, _ = safe_inputs.load_inputs()
    panel = pd.read_parquet(ROOT / "pre2026_oof.parquet")
    e5 = rl_policy.load_module("audit_e5_pre2026", rl_policy.E5)
    replay = close_clock_replay(e5)
    rows = []
    for year, start, stop in ((2024, "2024-01-01", "2025-01-01"),
                              (2025, "2025-01-01", "2026-01-01")):
        bundle = risk_aux.load_bundle(ROOT / "risk_artifacts" / f"fold_{year}.joblib")
        for name, spec in (("RAW", None), *optimize_route.SPECS.items()):
            result, decisions = replay_supervised(replay, name, spec, panel, prices, bundle, start, stop)
            prefix = AUDIT / f"{year}_{name.lower()}"
            result.daily.to_parquet(str(prefix) + "_daily.parquet", index=False)
            decisions.to_parquet(str(prefix) + "_targets.parquet", index=False)
            original = pd.read_parquet(ROOT / "opt_artifacts" / f"{year}_{name.lower()}_daily.parquet")
            row = {"year": year, "candidate": name, "original_nav": float(original.nav.iloc[-1]),
                   "close_clock_nav": float(result.daily.nav.iloc[-1]),
                   "nav_change": float(result.daily.nav.iloc[-1] - original.nav.iloc[-1]),
                   "days": len(result.daily)}
            rows.append(row)
            print("CLOSE_CLOCK", year, name, row["close_clock_nav"], flush=True)
    pd.DataFrame(rows).to_csv(AUDIT / "close_clock_pre2026_summary.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("2026", "pre2026"))
    args = parser.parse_args()
    run2026() if args.phase == "2026" else run_pre2026()
