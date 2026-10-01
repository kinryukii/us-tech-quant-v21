"""Two predeclared HGB information controls on repaired signal-close clock."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
sys.path.insert(0, str(ROOT))
import optimize_route
import risk_aux
import rl_policy
from close_clock import close_clock_replay, replay_supervised


def summarize(name, result):
    x = result.daily
    return {"candidate": name, "end_nav": float(x.nav.iloc[-1]),
            "mean_cash": float(x.cash_weight.mean()), "turnover": float(x.turnover.sum()),
            "fees": float(x.transaction_cost_amount.sum()),
            "max_drawdown": float((x.nav / x.nav.cummax() - 1).min()),
            "days": len(x), "max_name_count": int(x.actual_name_count.max())}


def main():
    if (AUDIT / "information_controls.csv").exists():
        raise RuntimeError("CONTROLS_ALREADY_RUN")
    pred = pd.read_parquet(ROOT / "test2026" / "predictions.parquet")
    e5 = rl_policy.load_module("audit_e5_information_controls", rl_policy.E5)
    replay = close_clock_replay(e5)
    _, prices, lineage = e5.load_2026_prices(set(pred.ticker.astype(str)))
    original = json.loads((ROOT / "test2026" / "score_receipt.json").read_text(encoding="utf-8"))
    assert lineage == original["price_lineage"]
    prices = prices.loc[prices.trade_date.le("2026-09-24")]
    bundle = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    spec = optimize_route.SPECS["HGB_DIAG_5"]

    # Control A: retain each date's common predicted level, remove stock differences.
    common = pred.copy()
    common["pred_hgb"] = common.groupby("signal_date").pred_hgb.transform("mean")
    a, a_target = replay_supervised(replay, "CONTROL_A_COMMON_MU", spec,
                                    common, prices, bundle, "2026-01-01", "2026-09-25")
    a.daily.to_parquet(AUDIT / "control_a_daily.parquet", index=False)
    a.trades.to_parquet(AUDIT / "control_a_trades.parquet", index=False)
    a_target.to_parquet(AUDIT / "control_a_targets.parquet", index=False)
    print("CONTROL_A", float(a.daily.nav.iloc[-1]), flush=True)

    # Control B: condition on original corrected HGB target set and target gross.
    # This inherits the HGB selection/cash signal; it tests only fine sizing.
    shadow = pd.read_parquet(AUDIT / "hgb_diag_5_targets.parquet")
    by_day = {}
    caps = []
    for date, group in shadow.groupby("signal_date", sort=True):
        selected = sorted(group.loc[group.target_weight.gt(0), "ticker"].astype(str))
        gross = float(group.target_weight.sum())
        if selected:
            each = min(.10, gross / len(selected))
            target = {t: each for t in selected}
        else:
            target = {}
        by_day[pd.Timestamp(date)] = target
        caps.append({"signal_date": date, "shadow_names": len(selected), "shadow_gross": gross,
                     "equal_gross": sum(target.values()), "cap_unallocatable": gross - sum(target.values())})
    _, executions, signal_by_execution = optimize_route.dates_for(prices, pred,
                                                                    "2026-01-01", "2026-09-25")
    b = replay("CONTROL_B_SHADOW_EQUAL", lambda signal, *_: by_day[signal],
               prices, executions, signal_by_execution)
    b.daily.to_parquet(AUDIT / "control_b_daily.parquet", index=False)
    b.trades.to_parquet(AUDIT / "control_b_trades.parquet", index=False)
    pd.DataFrame(caps).to_csv(AUDIT / "control_b_shadow_budget.csv", index=False)
    print("CONTROL_B", float(b.daily.nav.iloc[-1]), flush=True)

    raw = pd.read_parquet(AUDIT / "raw_daily.parquet")
    hgb = pd.read_parquet(AUDIT / "hgb_diag_5_daily.parquet")
    table = pd.DataFrame([summarize("RAW_CLOSE_CLOCK", type("R", (), {"daily": raw})()),
                          summarize("HGB_CLOSE_CLOCK", type("R", (), {"daily": hgb})()),
                          summarize("CONTROL_A_COMMON_MU", a),
                          summarize("CONTROL_B_SHADOW_EQUAL", b)])
    table.to_csv(AUDIT / "information_controls.csv", index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
