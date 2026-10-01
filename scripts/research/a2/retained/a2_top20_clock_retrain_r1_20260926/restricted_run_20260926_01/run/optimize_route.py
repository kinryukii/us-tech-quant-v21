"""Bounded pre-2026 target-weight research, sharing E5's shares/cash ledger."""
from __future__ import annotations

import json
import importlib.util
import inspect
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import prepare
import risk_aux

ROOT = Path(__file__).resolve().parent
import safe_inputs
import ledger

SPECS = {
    "HGB_DIAG_5": ("pred_hgb", "diagonal", 5.0, 0.0),
    "HGB_FACTOR_5": ("pred_hgb", "factor_shrink", 5.0, 0.0),
    "HGB_FACTOR_20": ("pred_hgb", "factor_shrink", 20.0, 0.0),
    "HGB_Q10_FACTOR_5": ("pred_hgb", "factor_shrink", 5.0, 0.10),
    "MLP_FACTOR_5": ("pred_mlp_mean", "factor_shrink", 5.0, 0.0),
}
COST_ONE_WAY = 0.0005
MAX_WEIGHT = 0.10
MAX_GROSS = 1.0
ZERO_CUTOFF = 0.0025
def load_e5():
    return ledger.replay


def solve(day: pd.DataFrame, shares: dict, pre_values: dict, nav: float,
          bundle: dict, spec: tuple, date: pd.Timestamp) -> tuple[dict, dict]:
    """Five-day return objective; five times frozen daily covariance."""
    pred_col, risk_kind, lam, downside_lambda = spec
    top = day.loc[day.raw_rank.le(20)].sort_values("raw_rank")
    eligible = top.ticker.astype(str).tolist()
    held = sorted(set(shares) - set(eligible))
    names = eligible + held
    assert len(names) == len(set(names))
    lookup = day.set_index("ticker")
    mean = np.array([float(lookup.at[t, pred_col]) if t in lookup.index else 0.0 for t in names])
    mean = np.nan_to_num(mean, nan=0.0).clip(-.20, .20)
    low = np.array([float(lookup.at[t, "pred_q10"]) if t in lookup.index else -.10 for t in names])
    low = np.nan_to_num(low, nan=-.10).clip(-.50, .20)
    old = np.array([pre_values.get(t, 0.0) / nav for t in names], float)
    cov = risk_aux.covariance_for(bundle, date, names)
    if risk_kind == "diagonal":
        cov = np.diag(np.diag(cov))
    # q10 is an individual-stock downside proxy, never a portfolio quantile.
    effective_mean = mean - downside_lambda * np.maximum(0.0, -low)
    def objective(w):
        return -(effective_mean @ w - lam * 5.0 * (w @ cov @ w)
                 - COST_ONE_WAY * np.abs(w - old).sum())
    x0 = np.clip(old, 0, MAX_WEIGHT)
    if x0.sum() > MAX_GROSS:
        x0 *= MAX_GROSS / x0.sum()
    result = minimize(objective, x0, method="SLSQP",
                      bounds=[(0.0, MAX_WEIGHT)] * len(names),
                      constraints=[{"type": "ineq", "fun": lambda w: MAX_GROSS - w.sum()}],
                      options={"maxiter": 80, "ftol": 1e-8})
    failed = (not result.success or not np.isfinite(result.x).all()
              or result.x.min() < -1e-7 or result.x.max() > MAX_WEIGHT + 1e-7
              or result.x.sum() > MAX_GROSS + 1e-7)
    if failed:
        # Safe fixed failure rule: retain actual positions; never infer a signal.
        target = {t: float(pre_values[t] / nav) for t in shares if pre_values.get(t, 0) > 0}
        return target, {"raw_targets": target.copy(), "solver_failed": True, "message": str(result.message),
                        "max_raw_target_sum": float(np.sum(x0)), "target_sum": sum(target.values())}
    raw = np.clip(result.x, 0, MAX_WEIGHT)
    final = np.where(raw < ZERO_CUTOFF, 0.0, raw)
    target = {t: float(w) for t, w in zip(names, final) if w > 0}
    return target, {"raw_targets": dict(zip(names, map(float, raw))), "solver_failed": False, "message": str(result.message),
                    "max_raw_target_sum": float(raw.sum()), "target_sum": float(final.sum())}


def dates_for(prices: pd.DataFrame, panel: pd.DataFrame, start: str, stop: str):
    cal = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    following = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(cal[:-1], cal[1:])}
    signals = [pd.Timestamp(d) for d in sorted(panel.signal_date.unique())
               if pd.Timestamp(start) <= d < pd.Timestamp(stop) and d in following]
    executions = [following[d] for d in signals]
    return signals, executions, dict(zip(executions, signals))


def replay_spec(name: str, spec: tuple | None, panel: pd.DataFrame,
                prices: pd.DataFrame, bundle: dict | None, start: str, stop: str):
    replay = load_e5()
    signals, executions, signal_by_execution = dates_for(prices, panel, start, stop)
    days = {d: x for d, x in panel.groupby("signal_date", sort=True)}
    decision_rows = []
    def callback(signal, shares, pre_values, nav):
        day = days[signal]
        if spec is None:
            target = dict(zip(day.loc[day.raw_rank.le(20)].ticker.astype(str), [0.05] * 20))
            diag = {"raw_targets": target.copy(), "solver_failed": False, "message": "RAW_FIXED", "max_raw_target_sum": 1.0,
                    "target_sum": 1.0}
        else:
            target, diag = solve(day, shares, pre_values, nav, bundle, spec, signal)
        raw_targets = diag.pop("raw_targets")
        for t in sorted(set(shares) | set(target) | set(raw_targets)):
            decision_rows.append({"candidate": name, "signal_date": signal, "ticker": t,
                                  "shares_before": shares.get(t, 0.0),
                                  "weight_before": pre_values.get(t, 0.0) / nav,
                                  "raw_target_weight": raw_targets.get(t, 0.0),
                                  "feasible_target_weight": target.get(t, 0.0),
                                  "planned_delta_weight": target.get(t, 0.0) - pre_values.get(t, 0.0) / nav,
                                  **diag})
        return target
    result = replay(name, callback, prices, executions, signal_by_execution)
    decisions = pd.DataFrame(decision_rows)
    return result, decisions


def summarize(replay) -> dict:
    day = replay.daily
    nav = day.nav.to_numpy(float)
    dd = nav / np.maximum.accumulate(nav) - 1
    return {"days": len(day), "end_nav": float(nav[-1]), "max_drawdown": float(dd.min()),
            "sum_cost": float(day.transaction_cost_amount.sum()),
            "sum_turnover": float(day.turnover.sum()), "mean_cash": float(day.cash_weight.mean()),
            "mean_gross_exposure": float(day.gross_exposure.mean()),
            "blocked_sells": int(day.blocked_sell_count.sum()),
            "skipped_buys": int(day.skipped_buy_count.sum()),
            "cash_scale_days": int((day.buy_cash_scale < 1 - 1e-9).sum()),
            "identity_error": float(max(day.nav_identity_error.abs().max(),
                                        day.cost_identity_error.abs().max()))}


def main():
    if os.environ.get("R1_VERIFIED_ISOLATION") != "1":
        raise RuntimeError("ISOLATED_RUNTIME_REQUIRED")
    out = ROOT / "opt_artifacts"
    out.mkdir(exist_ok=True)
    if (out / "pre2026_summary.csv").exists():
        raise RuntimeError("OPT_VALIDATION_ALREADY_RUN")
    panel = pd.read_parquet(ROOT / "pre2026_oof.parquet")
    _, prices, _, _ = safe_inputs.load_inputs()
    assert panel.signal_date.max() < pd.Timestamp("2026-01-01")
    rows = []
    for year, start, stop in ((2024, "2024-01-01", "2025-01-01"),
                              (2025, "2025-01-01", "2026-01-01")):
        bundle = risk_aux.load_bundle(ROOT / "risk_artifacts" / f"fold_{year}.joblib")
        for name, spec in (("RAW", None), *SPECS.items()):
            result, decisions = replay_spec(name, spec, panel, prices, bundle, start, stop)
            summary = summarize(result)
            summary.update({"year": year, "candidate": name,
                            "solver_fallbacks": int(decisions.loc[decisions.solver_failed, "signal_date"].nunique())})
            rows.append(summary)
            prefix = out / f"{year}_{name.lower()}"
            result.daily.to_parquet(str(prefix) + "_daily.parquet", index=False)
            result.trades.to_parquet(str(prefix) + "_trades.parquet", index=False)
            decisions.to_parquet(str(prefix) + "_decisions.parquet", index=False)
            print(f"OPT {year} {name} NAV={summary['end_nav']:.5f} fallback={summary['solver_fallbacks']}", flush=True)
    table = pd.DataFrame(rows)
    table.to_csv(out / "pre2026_summary.csv", index=False)
    (out / "specs.json").write_text(json.dumps({"specs": SPECS, "cost_one_way": COST_ONE_WAY,
        "max_weight": MAX_WEIGHT, "max_gross": MAX_GROSS, "zero_cutoff": ZERO_CUTOFF,
        "search_solves_upper_bound": int(2 * 251 * len(SPECS)),
        "objective": "5d expected return - lambda*5*daily_covariance_quadratic - 5bp*L1 turnover",
        "asof": "2026-09-25T15:34:48Z"}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
