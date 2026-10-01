"""Post-seal, pre-2026 fee stress of saved target weights; never selects a model.

Run in the fixed R1 Linux image with the sealed training output mounted read-only
at /bundle and a private diagnostic output mounted at /out.  This does not fit,
estimate, optimize, or alter the target schedule.  It only changes the execution
fee in the existing sealed ledger for all compared accounts in the same way.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/bundle")
OUT = Path("/out")
sys.path.insert(0, str(ROOT))
import ledger  # noqa: E402


YEARS = (2024, 2025)
POLICIES = ("raw", "hgb_diag_5", "hgb_factor_5")
SIDE_BPS = (0, 5, 10, 20, 50)
CUTOFF = pd.Timestamp("2026-01-01")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked_schedule(year: int, name: str) -> tuple[dict, list, dict, pd.DataFrame, list[Path]]:
    base = ROOT / "opt_artifacts" / f"{year}_{name}"
    daily_path = Path(str(base) + "_daily.parquet")
    decision_path = Path(str(base) + "_decisions.parquet")
    original = pd.read_parquet(daily_path)
    decisions = pd.read_parquet(decision_path)
    if original.empty or decisions.empty or original.signal_date.isna().any():
        raise RuntimeError(f"EMPTY_OR_MISSING_SCHEDULE:{year}:{name}")
    for frame, columns in ((original, ("signal_date", "execution_date")),
                           (decisions, ("signal_date",))):
        for col in columns:
            if pd.to_datetime(frame[col]).max() >= CUTOFF:
                raise RuntimeError(f"POST_CUTOFF_SCHEDULE:{year}:{name}:{col}")
    if not original.execution_date.is_monotonic_increasing or original.execution_date.duplicated().any():
        raise RuntimeError(f"BAD_EXECUTION_DATES:{year}:{name}")
    targets = {}
    for signal, day in decisions.groupby("signal_date", sort=True):
        if day.ticker.astype(str).duplicated().any():
            raise RuntimeError(f"DUPLICATE_TARGET:{year}:{name}:{signal}")
        weights = day.feasible_target_weight.to_numpy(float)
        if not np.isfinite(weights).all() or (weights < -1e-9).any() or weights.sum() > 1 + 1e-7:
            raise RuntimeError(f"INFEASIBLE_TARGET:{year}:{name}:{signal}")
        targets[pd.Timestamp(signal)] = {
            str(ticker): float(weight)
            for ticker, weight in zip(day.ticker, weights)
            if weight > 0
        }
    signals = {pd.Timestamp(d) for d in original.signal_date}
    if signals != set(targets):
        raise RuntimeError(f"TARGET_DATE_MISMATCH:{year}:{name}")
    execution_dates = [pd.Timestamp(d) for d in original.execution_date]
    signal_map = {
        pd.Timestamp(row.execution_date): pd.Timestamp(row.signal_date)
        for row in original.itertuples()
    }
    return targets, execution_dates, signal_map, original, [daily_path, decision_path]


def summarize(year: int, name: str, side_bp: int, result: ledger.Replay) -> dict:
    daily = result.daily
    if daily.empty:
        raise RuntimeError(f"EMPTY_REPLAY:{year}:{name}:{side_bp}")
    nav = daily.nav.to_numpy(float)
    if not np.isfinite(nav).all() or (nav <= 0).any():
        raise RuntimeError(f"INVALID_NAV:{year}:{name}:{side_bp}")
    if daily.nav_identity_error.abs().max() > 1e-9 or daily.cost_identity_error.abs().max() > 1e-9:
        raise RuntimeError(f"ACCOUNTING_IDENTITY:{year}:{name}:{side_bp}")
    return {
        "year": year,
        "policy": name.upper(),
        "execution_fee_bp_per_side": side_bp,
        "days": len(daily),
        "terminal_nav": float(nav[-1]),
        "terminal_return": float(nav[-1] - 1),
        "max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()),
        "turnover_sum_half_buy_plus_sell": float(daily.turnover.sum()),
        "fee_amount_sum_in_account_units": float(daily.transaction_cost_amount.sum()),
        "mean_cash_weight": float(daily.cash_weight.mean()),
        "blocked_sells": int(daily.blocked_sell_count.sum()),
        "skipped_buys": int(daily.skipped_buy_count.sum()),
        "cash_scale_days": int((daily.buy_cash_scale < 1 - 1e-9).sum()),
    }


def main() -> None:
    if not ROOT.is_dir() or not OUT.is_dir():
        raise RuntimeError("EXPECTED_ISOLATED_MOUNTS_MISSING")
    if any(OUT.iterdir()):
        raise RuntimeError("DIAGNOSTIC_OUTPUT_NOT_EMPTY")
    prices_path = ROOT / "data" / "prices.parquet"
    prices = pd.read_parquet(prices_path, columns=["trade_date", "ticker", "open", "close"])
    if prices.empty or pd.to_datetime(prices.trade_date).max() >= CUTOFF:
        raise RuntimeError("POST_CUTOFF_OR_EMPTY_PRICES")
    if prices.duplicated(["trade_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_PRICE_KEY")
    original_cost_rate = ledger.COST_RATE
    if original_cost_rate != 0.001:
        raise RuntimeError(f"UNEXPECTED_SEALED_COST_RATE:{original_cost_rate}")

    rows = []
    consumed = [prices_path, ROOT / "ledger.py", Path(__file__)]
    for year in YEARS:
        for name in POLICIES:
            targets, dates, signal_map, original, paths = checked_schedule(year, name)
            consumed.extend(paths)

            def callback(signal, shares, values, nav):
                return targets[pd.Timestamp(signal)]

            for side_bp in SIDE_BPS:
                # The sealed ledger charges 0.5 * COST_RATE on each filled side.
                ledger.COST_RATE = 2.0 * side_bp / 10000.0
                replay = ledger.replay(str(original.candidate.iloc[0]), callback,
                                       prices, dates, signal_map)
                if side_bp == 5:
                    nav_diff = np.max(np.abs(replay.daily.nav.to_numpy(float) - original.nav.to_numpy(float)))
                    if nav_diff > 1e-10:
                        raise RuntimeError(f"BASELINE_REPLAY_MISMATCH:{year}:{name}:{nav_diff}")
                rows.append(summarize(year, name, side_bp, replay))
                print(f"COST_DIAGNOSTIC {year} {name} {side_bp}bp NAV={rows[-1]['terminal_nav']:.8f}", flush=True)
    ledger.COST_RATE = original_cost_rate
    table = pd.DataFrame(rows)
    if len(table) != len(YEARS) * len(POLICIES) * len(SIDE_BPS):
        raise RuntimeError("MISSING_STRESS_CASE")
    raw = table.loc[table.policy.eq("RAW"), ["year", "execution_fee_bp_per_side", "terminal_nav"]]
    raw = raw.rename(columns={"terminal_nav": "raw_terminal_nav_at_same_fee"})
    table = table.merge(raw, on=["year", "execution_fee_bp_per_side"], validate="many_to_one")
    table["terminal_nav_minus_raw_at_same_fee"] = table.terminal_nav - table.raw_terminal_nav_at_same_fee
    table.to_csv(OUT / "cost_sensitivity.csv", index=False)
    receipt = {
        "status": "POST_SEAL_PRE2026_FIXED_TARGET_COST_DIAGNOSTIC",
        "scope": "price-coordinate proxy; no fit, target re-optimization, model selection, or 2026 read",
        "comparison": "Raw and both HGB policies stressed at the same per-side execution fee",
        "fee_bp_per_side": SIDE_BPS,
        "sealed_baseline_fee_bp_per_side": 5,
        "policy_count": len(POLICIES),
        "case_count": len(table),
        "baseline_5bp_nav_reproduced": True,
        "caveat": "Saved targets stay fixed, but changed fees alter filled shares, cash and later NAV. This tests fee tolerance of frozen actions; optimizer/RL cost assumptions are not retrained or retuned. No market impact or dividend certification is supplied.",
        "inputs_sha256": {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else "cost_sensitivity.py": sha256(path)
                          for path in consumed},
        "output_sha256": sha256(OUT / "cost_sensitivity.csv"),
    }
    (OUT / "cost_sensitivity_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "case_count": len(table),
                      "csv_sha256": receipt["output_sha256"]}), flush=True)


if __name__ == "__main__":
    main()
