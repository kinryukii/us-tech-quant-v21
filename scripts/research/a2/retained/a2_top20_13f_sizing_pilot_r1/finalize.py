"""Emit native position/trade/cash ledgers using the existing R0F path."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from run import OUT, R4, SOURCE, get_module, load_prices, save_manifest, sha


def main() -> None:
    manifest = json.loads((OUT / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["stages"]["policy_replay"] == "B0_B2_COMPLETE_INDEX_COORDINATE_DIAGNOSTIC"
    script = Path("D:/us-tech-quant/scripts/v22/fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
    r0f = get_module(script)
    signals = pd.read_parquet(SOURCE / "A2/top20_selections.parquet")
    weights = pd.read_csv(OUT / "WEIGHTS.csv")
    weights.signal_date = pd.to_datetime(weights.signal_date)
    targets = {"B0_RAW": {}, "B2_OBSERVED_TOP100": {}}
    for date, group in weights.groupby("signal_date"):
        for policy in targets:
            targets[policy][pd.Timestamp(date)] = dict(zip(group.ticker, group[policy]))
    prices = load_prices({"US." + x for x in signals.ticker.unique()})
    summary = {}
    positions = {}
    for policy, target in targets.items():
        replay = r0f.reconstruct_path(model=policy, target_map=target, qfq=prices,
                                      signal_dates=signals.signal_date.unique(), cost_bps=10)
        r4_daily = pd.read_parquet(OUT / f"{policy.split('_')[0]}_DAILY.parquet").sort_values("execution_date")
        daily = replay.daily.sort_values("execution_date")
        assert daily.execution_date.reset_index(drop=True).equals(r4_daily.execution_date.reset_index(drop=True))
        error = float(np.max(np.abs(daily.reconstructed_daily_return.to_numpy() - r4_daily.net_return.to_numpy())))
        assert error <= 1e-12, (policy, error)
        for field in ["NAV_ACCOUNTING_IDENTITY_ERROR", "CASH_IDENTITY_ERROR",
                      "POSITION_VALUE_IDENTITY_ERROR", "TURNOVER_IDENTITY_ERROR",
                      "TRANSACTION_COST_IDENTITY_ERROR"]:
            assert daily[field].abs().max() <= 1e-10, (policy, field)
        prefix = policy.split("_")[0]
        pos = replay.positions.copy()
        pos["portfolio"] = policy
        pos["source_path"] = manifest["inputs"]["price_surface"]["path"]
        trade = replay.trades.copy()
        daily.to_parquet(OUT / f"{prefix}_CASH_DAILY.parquet", index=False)
        pos.to_parquet(OUT / f"{prefix}_POSITIONS.parquet", index=False)
        trade.to_parquet(OUT / f"{prefix}_TRADES.parquet", index=False)
        positions[policy] = pos
        summary[policy] = {"daily_rows": len(daily), "position_rows": len(pos), "trade_rows": len(trade),
                           "r4_vs_r0f_max_return_error": error,
                           "terminal_nav": float(daily.reconstructed_nav.iloc[-1]),
                           "total_cost_amount": float(daily.reconstructed_transaction_cost.sum())}
    b0 = positions["B0_RAW"].groupby("ticker").net_pnl_contribution.sum()
    b2 = positions["B2_OBSERVED_TOP100"].groupby("ticker").net_pnl_contribution.sum()
    contribution = b2.sub(b0, fill_value=0).sort_values(ascending=False)
    nav_diff = summary["B2_OBSERVED_TOP100"]["terminal_nav"] - summary["B0_RAW"]["terminal_nav"]
    assert abs(float(contribution.sum()) - nav_diff) <= 1e-10
    contribution.rename("delta_terminal_nav").to_csv(OUT / "B2_MINUS_B0_SECURITY_CONTRIBUTION.csv")
    d0 = positions["B0_RAW"].groupby(["date", "ticker"]).net_pnl_contribution.sum()
    d2 = positions["B2_OBSERVED_TOP100"].groupby(["date", "ticker"]).net_pnl_contribution.sum()
    daily_contrib = d2.sub(d0, fill_value=0).sort_values(ascending=False)
    daily_contrib.rename("delta_terminal_nav_on_date").to_csv(OUT / "B2_MINUS_B0_DATE_SECURITY_CONTRIBUTION.csv")
    metric_path = OUT / "POLICY_METRICS.csv"
    metrics = pd.read_csv(metric_path)
    for idx, row in metrics.iterrows():
        cohort = weights if row.year == "ALL" else weights.loc[weights.signal_date.dt.year.eq(int(row.year))]
        by_day = cohort.groupby("signal_date")
        series = row.policy
        metrics.loc[idx, "mean_target_positive_names"] = by_day[series].apply(lambda s: int((s > 0).sum())).mean()
        metrics.loc[idx, "max_target_single_weight"] = cohort[series].max()
        metrics.loc[idx, "mean_target_max_weight"] = by_day[series].max().mean()
        metrics.loc[idx, "mean_target_effective_n"] = by_day[series].apply(lambda s: 1 / s.pow(2).sum()).mean()
        metrics.loc[idx, "mean_half_l1_from_B0"] = by_day.apply(lambda z: abs(z[series] - z.B0_RAW).sum() / 2).mean()
    metrics.to_csv(metric_path, index=False)
    manifest["stages"]["native_ledgers"] = "COMPLETE_R0F_R4_RECONCILED"
    manifest["r0f_source"] = {"path": str(script), "sha256": sha(script)}
    manifest["native_ledger_counts"] = summary
    manifest["terminal_nav_difference_B2_minus_B0"] = nav_diff
    manifest["stages"]["review"] = "PENDING"
    manifest["next_command"] = "Review POLICY_METRICS.csv and B2_MINUS_B0_SECURITY_CONTRIBUTION.csv, then write REPORT.md and README.md"
    save_manifest(manifest)


if __name__ == "__main__":
    main()
