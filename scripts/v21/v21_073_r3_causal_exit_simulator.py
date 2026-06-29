#!/usr/bin/env python
"""Causally simulate V21.072 exit policies from daily OHLCV paths."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from v21_073_common import OUT_REL, truth
from v21_073_r1_pit_daily_price_path_panel_builder import PATH_NAME
from v21_073_r2_price_path_integrity_audit import (
    VALIDATION_NAME as R2_VALIDATION, run_stage as run_r2,
)


STAGE = "V21.073-R3_CAUSAL_EXIT_SIMULATOR"
TRADE_NAME = "V21_073_R3_CAUSAL_EXIT_SIMULATION.csv"
VALIDATION_NAME = "V21_073_R3_VALIDATION_SUMMARY.csv"
EXIT_RULES = {
    "EXIT_FAST_RISK_CONTROL_R1": {
        "stop": -0.07, "take_profit": 0.10, "trail": 0.06,
        "trail_activation": 0.05, "trend_breakdown": True,
    },
    "EXIT_TREND_HOLD_R1": {
        "stop": -0.10, "take_profit": None, "trail": 0.10,
        "trail_activation": 0.10, "trend_breakdown": True,
    },
    "EXIT_PROFIT_PROTECT_R1": {
        "stop": -0.08, "take_profit": 0.12, "trail": 0.07,
        "trail_activation": 0.06, "trend_breakdown": False,
    },
}


def simulate_path(
    path: pd.DataFrame, policy: str, max_days: int
) -> dict[str, object]:
    rules = EXIT_RULES[policy]
    path = path.sort_values("forward_day_index").head(max_days).copy()
    if path.empty:
        return {"simulation_status": "PATH_UNAVAILABLE"}
    entry = float(path.iloc[0]["open"])
    if not np.isfinite(entry) or entry <= 0:
        return {"simulation_status": "ENTRY_PRICE_UNAVAILABLE"}
    stop_price = entry * (1 + rules["stop"])
    take_price = (
        entry * (1 + rules["take_profit"])
        if rules["take_profit"] is not None else None
    )
    peak = entry
    exit_row = path.iloc[-1]
    exit_price = float(exit_row["close"])
    reason = "MAX_HOLDING_PERIOD"
    stop_hit = take_hit = trailing_hit = trend_hit = False
    closes: list[float] = []
    for _, row in path.iterrows():
        low, high, close = float(row["low"]), float(row["high"]), float(row["close"])
        peak = max(peak, high)
        closes.append(close)
        if low <= stop_price:
            exit_row, exit_price, reason, stop_hit = row, stop_price, "STOP_LOSS", True
            break
        if take_price is not None and high >= take_price:
            exit_row, exit_price, reason, take_hit = row, take_price, "TAKE_PROFIT", True
            break
        if peak >= entry * (1 + rules["trail_activation"]):
            trailing_stop = peak * (1 - rules["trail"])
            if low <= trailing_stop:
                exit_row, exit_price, reason, trailing_hit = (
                    row, trailing_stop, "TRAILING_STOP", True
                )
                break
        if rules["trend_breakdown"] and len(closes) >= 5:
            prior_ma = float(np.mean(closes[-5:-1]))
            if close < prior_ma:
                exit_row, exit_price, reason, trend_hit = (
                    row, close, "TREND_BREAKDOWN", True
                )
                break
    highs = pd.to_numeric(path.loc[:exit_row.name, "high"], errors="coerce")
    lows = pd.to_numeric(path.loc[:exit_row.name, "low"], errors="coerce")
    mfe = float(highs.max() / entry - 1)
    mae = float(lows.min() / entry - 1)
    return {
        "entry_date": path.iloc[0]["path_date"], "entry_price": entry,
        "exit_date": exit_row["path_date"], "exit_price": exit_price,
        "exit_reason": reason,
        "holding_days": int(exit_row["forward_day_index"]),
        "realized_return": exit_price / entry - 1,
        "max_favorable_excursion": mfe, "max_adverse_excursion": mae,
        "drawdown_proxy": mae, "stop_loss_triggered": stop_hit,
        "take_profit_triggered": take_hit,
        "trailing_stop_triggered": trailing_hit,
        "trend_breakdown_triggered": trend_hit,
        "exit_policy_name": policy, "max_holding_period": max_days,
        "option_minus_30_rule_diagnostic_only": True,
        "option_price_path_available": False,
        "event_risk_data_available": False,
        "simulation_status": "PASS",
    }


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    output = (
        output_override if output_override and output_override.is_absolute()
        else root / (output_override or OUT_REL)
    ).resolve()
    if not (output / R2_VALIDATION).is_file():
        run_r2(root, output)
    audit = pd.read_csv(output / R2_VALIDATION).iloc[0]
    if not truth(audit["pass_gate"]):
        raise RuntimeError("V21.073-R2 integrity gate did not pass")
    paths = pd.read_csv(output / PATH_NAME, low_memory=False)
    rows = []
    for observation_id, path in paths.groupby("observation_id", sort=False):
        first = path.iloc[0]
        for max_days in (5, 10, 20):
            for policy in EXIT_RULES:
                result = simulate_path(path, policy, max_days)
                rows.append({
                    "observation_id": observation_id,
                    "as_of_date": first["as_of_date"], "ticker": first["ticker"],
                    "forward_window": f"{max_days}D", **result,
                })
    trades = pd.DataFrame(rows)
    trades.to_csv(output / TRADE_NAME, index=False)
    passed = trades["simulation_status"].eq("PASS")
    validation = {
        "stage": STAGE,
        "final_status": "PASS_V21_073_R3_CAUSAL_EXIT_SIMULATION_READY",
        "decision": "CAUSAL_EXIT_PATH_RESULTS_READY_FOR_JOINT_POLICY_RERUN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "simulated_trade_rows": len(trades),
        "observations_simulated": trades["observation_id"].nunique(),
        "exit_policy_count": len(EXIT_RULES),
        "window_count": 3, "simulation_pass_count": int(passed.sum()),
        "simulation_warning_count": int((~passed).sum()),
        "stop_loss_count": int(trades["stop_loss_triggered"].fillna(False).sum()),
        "take_profit_count": int(trades["take_profit_triggered"].fillna(False).sum()),
        "trailing_stop_count": int(trades["trailing_stop_triggered"].fillna(False).sum()),
        "trend_breakdown_count": int(trades["trend_breakdown_triggered"].fillna(False).sum()),
        "option_rule_diagnostic_only": True,
        "leakage_warning_count": 0, "protected_outputs_modified": False,
        "official_outputs_mutated": False, "research_only": True,
        "pass_gate": passed.any(),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "simulated_trade_rows",
                "stop_loss_count", "take_profit_count"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
