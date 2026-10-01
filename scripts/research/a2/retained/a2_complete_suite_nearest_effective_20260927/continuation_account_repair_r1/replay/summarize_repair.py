"""Compact, read-only comparison of certified repaired prefixes with old ledgers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "evaluation_2026"


def _first_changed_day(old: pd.DataFrame, new: pd.DataFrame) -> str | None:
    left = old.set_index("date")
    right = new.set_index("date")
    for date in right.index:
        if date not in left.index:
            return date.date().isoformat()
        a, b = left.loc[date], right.loc[date]
        for field in ("cash", "nav", "actual_name_count", "buy_notional", "sell_notional", "transaction_cost_amount"):
            x, y = float(a[field]), float(b[field])
            if not np.isclose(x, y, rtol=0, atol=1e-8):
                return date.date().isoformat()
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    complete = json.loads((out / "COMPLETE.json").read_text(encoding="utf-8"))
    progress, changes, next_inputs = [], [], []
    for item in complete["paths"]:
        run_id = item["run_id"]
        cost = int(run_id.rsplit("_", 1)[1].removesuffix("bps"))
        old_dir = OLD / f"cost_{cost}" / run_id
        new_dir = out / run_id
        checkpoint = json.loads((new_dir / "CHECKPOINT.json").read_text(encoding="utf-8"))
        old_daily = pd.read_parquet(old_dir / "daily.parquet")
        old_diag = pd.read_parquet(old_dir / "diagnostics.parquet")
        advanced = bool(item["account_advanced_beyond_old_bad"])
        new_daily = pd.read_parquet(new_dir / "daily.parquet") if advanced else None
        new_trades = pd.read_parquet(new_dir / "trades.parquet") if advanced else None
        new_positions = pd.read_parquet(new_dir / "positions.parquet") if advanced else None
        first_old = item["historical_first_bad"]
        first_change = _first_changed_day(old_daily, new_daily) if new_daily is not None else None
        old_first_date = pd.Timestamp(first_old) if first_old else None
        old_at_first = old_daily.loc[old_daily.date.eq(old_first_date)].iloc[0] if first_old else None
        new_at_first = (new_daily.loc[new_daily.date.eq(old_first_date)].iloc[0]
                        if new_daily is not None and old_first_date in set(new_daily.date) else None)
        old_first_blocks = (old_diag.loc[old_diag.date.eq(old_first_date) &
                                         old_diag.code.isin(["missing_open_buy", "missing_open_sell"])]
                            if first_old else old_diag.iloc[:0])
        old_first_trades = pd.read_parquet(old_dir / "trades.parquet")
        for block in old_first_blocks.itertuples(index=False):
            side = "BUY" if block.code == "missing_open_buy" else "SELL"
            actual = (new_trades.loc[new_trades.execution_date.eq(old_first_date) &
                                     new_trades.ticker.eq(block.ticker) & new_trades.side.eq(side)]
                      if new_trades is not None else pd.DataFrame())
            any_side = (new_trades.loc[new_trades.execution_date.eq(old_first_date) &
                                       new_trades.ticker.eq(block.ticker)]
                        if new_trades is not None else pd.DataFrame())
            changes.append({"run_id": run_id, "old_first_block_date": first_old,
                            "ticker": block.ticker, "old_block_code": block.code,
                            "new_same_security_side_actual_trade": not actual.empty,
                            "new_same_security_any_side_actual_trade": not any_side.empty,
                            "new_actual_sides": "|".join(sorted(any_side.side.unique())) if not any_side.empty else "",
                            "new_any_side_trade_notional": float(any_side.notional.sum()) if not any_side.empty else None,
                            "new_any_side_trade_index_units": float(any_side.index_units.sum()) if not any_side.empty else None,
                            "new_any_side_trade_cost": float(any_side.transaction_cost.sum()) if not any_side.empty else None,
                            "new_trade_notional": float(actual.notional.sum()) if not actual.empty else None,
                            "new_trade_index_units": float(actual.index_units.sum()) if not actual.empty else None,
                            "new_trade_cost": float(actual.transaction_cost.sum()) if not actual.empty else None,
                            "interpretation": "actual fill under frozen policy" if not actual.empty else
                              "frozen-policy order direction changed" if not any_side.empty else
                              "no same-security fill in certified prefix; demand may have changed or path paused"})
        row = {"run_id": run_id, "historical_first_bad": first_old,
               "certified_through": item["certified_through"], "next_date": item["next_date"],
               "status": item["status"], "first_account_change_date": first_change,
               "advanced_beyond_old_first_bad": advanced,
               "approved_fields_actually_consumed": item["approved_fields_consumed_in_certified_prefix"],
               "old_first_day_cash": None if old_at_first is None else float(old_at_first.cash),
               "new_first_day_cash": None if new_at_first is None else float(new_at_first.cash),
               "old_first_day_indicative_nav": None if old_at_first is None else float(old_at_first.nav),
               "new_first_day_certified_nav": None if new_at_first is None else float(new_at_first.certified_nav),
               "old_first_day_valuation_status": None if old_at_first is None else old_at_first.valuation_status,
               "new_first_day_valuation_status": None if new_at_first is None else new_at_first.valuation_status,
               "old_first_day_trade_count": (None if first_old is None else
                  int(old_first_trades.execution_date.eq(old_first_date).sum())),
               "new_first_day_trade_count": (None if new_at_first is None else
                  int(new_trades.execution_date.eq(old_first_date).sum())),
               "new_certified_days": checkpoint["certified_account_invariants"]["days"],
               "old_uncertified_days_within_new_prefix": int(old_daily.loc[
                  old_daily.date.le(pd.Timestamp(item["certified_through"])), "valuation_status"].ne("certified").sum())
                  if item["certified_through"] else 0,
               "prefix_exact_reconciliation_through": checkpoint["prefix_agrees_with_original"]["through"],
               "max_abs_cash_flow_identity_error": checkpoint["certified_account_invariants"].get("max_abs_cash_flow_identity_error"),
               "max_abs_cost_identity_error": checkpoint["certified_account_invariants"].get("max_abs_cost_identity_error")}
        progress.append(row)
        for need in item["next_required_inputs"]:
            next_inputs.append({"run_id": run_id, **need})
    pd.DataFrame(progress).to_csv(out / "PATH_PROGRESS.csv", index=False)
    pd.DataFrame(changes).to_csv(out / "FIRST_BLOCK_ACTUAL_FILL.csv", index=False)
    pd.DataFrame(next_inputs).to_csv(out / "NEXT_REQUIRED_INPUTS.csv", index=False)
    summary = {"paths": len(progress), "advanced_beyond_old_first_bad": sum(r["advanced_beyond_old_first_bad"] for r in progress),
               "certified_to_terminal": sum(r["status"] == "certified_to_terminal" for r in progress),
               "first_old_block_replaced_by_actual_trade": sum(r["new_same_security_side_actual_trade"] for r in changes),
               "first_old_block_recomputed_to_opposite_side_trade": sum(
                   r["new_same_security_any_side_actual_trade"] and not r["new_same_security_side_actual_trade"]
                   for r in changes),
               "total_approved_fields_consumed_across_paths": sum(r["approved_fields_actually_consumed"] for r in progress),
               "basis": "post-2026 evidence repair diagnostic; old indicative NAV is not a certified performance comparison"}
    (out / "REPAIR_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
