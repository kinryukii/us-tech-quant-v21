"""Read-only cost diagnostics for the joint batch's existing 2025 replay.

This intentionally reads evaluation_2025 only. It does not refit, infer,
change the account, or inspect any 2026 economic outcome.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "evaluation_2025"
OUT = Path(__file__).resolve().parent
RATE = 10 / 10_000
INITIAL_NAV = 1_000_000.0


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_float(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def main() -> None:
    contract = (ROOT / "JOINT_CONTRACT.md").read_text(encoding="utf-8")
    assert "100万美元" in contract and "10bp" in contract and "5bp、25bp" in contract
    assert "1%容量代理" in contract
    roster = [
        "joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb",
        "joint_q10", "joint_q50", "joint_q90", "joint_quantile_risk",
        "joint_mlp", "joint_rl_ensemble", "joint_rl_zero_control",
        "hgb_return_baseline",
    ]
    rows: list[dict] = []
    input_hashes: dict[str, str] = {}
    for name in roster:
        directory = EVAL / f"{name}_10bps"
        files = {key: directory / f"{key}.parquet" for key in
                 ("daily", "trades", "target_decisions", "diagnostics")}
        for key, path in files.items():
            input_hashes[str(path.relative_to(ROOT))] = sha256(path)
        daily = pd.read_parquet(files["daily"])
        trades = pd.read_parquet(files["trades"])
        target = pd.read_parquet(files["target_decisions"])
        diagnostics = pd.read_parquet(files["diagnostics"])
        # Parquet has no timestamp inference for an all-empty trades table.
        trades["signal_date"] = pd.to_datetime(trades["signal_date"])
        assert daily.date.max() < pd.Timestamp("2026-01-01")
        assert trades.empty or trades.execution_date.max() < pd.Timestamp("2026-01-01")
        assert target.empty or target.signal_date.max() < pd.Timestamp("2026-01-01")
        assert len(daily) == 250
        assert trades.cost_bps.eq(10).all()

        # Compare all three representations, independently of the engine's
        # saved cost_identity_error column.
        expected_trade_fees = trades.notional.mul(RATE)
        trade_fee_error = (trades.transaction_cost - expected_trade_fees).abs().max()
        if pd.isna(trade_fee_error):
            trade_fee_error = 0.0
        by_day = trades.groupby("execution_date", sort=False).agg(
            trade_fees=("transaction_cost", "sum"),
            trade_notional=("notional", "sum"),
        )
        joined = daily.join(by_day, on="date")
        joined[["trade_fees", "trade_notional"]] = joined[
            ["trade_fees", "trade_notional"]].fillna(0.0)
        daily_fee_error = (joined.transaction_cost_amount - joined.trade_fees).abs().max()
        daily_notional_error = (joined.traded_notional - joined.trade_notional).abs().max()
        no_trade_fee_days = int((joined.trade_notional.eq(0) & joined.transaction_cost_amount.ne(0)).sum())
        same_ticker_two_sides = int(trades.groupby(
            ["execution_date", "ticker"]).side.nunique().gt(1).sum())

        # Grid target unchanged on adjacent signal days. This is a diagnostic
        # of target maintenance trading, not proof that the grid alone caused it:
        # previous capacity underfill and intervening price drift also matter.
        target = target.loc[target.ticker.notna() & target.status.eq("submitted")].copy()
        assert not target.duplicated(["signal_date", "ticker"]).any()
        ordered_dates = sorted(target.signal_date.unique())
        rank = {date: index for index, date in enumerate(ordered_dates)}
        target["signal_rank"] = target.signal_date.map(rank)
        target = target.sort_values(["ticker", "signal_date"])
        target["prior_target"] = target.groupby("ticker", sort=False).target_weight.shift()
        target["prior_rank"] = target.groupby("ticker", sort=False).signal_rank.shift()
        target["same_positive_grid_target"] = (
            target.target_weight.gt(0)
            & target.target_weight.sub(target.prior_target).abs().lt(1e-10)
            & target.signal_rank.sub(target.prior_rank).eq(1)
            & target.current_weight.gt(0)
        )
        trade_with_target = trades.merge(
            target[["signal_date", "ticker", "target_weight", "current_weight",
                    "same_positive_grid_target"]],
            on=["signal_date", "ticker"], how="left", validate="many_to_one",
        )
        maintained = trade_with_target.same_positive_grid_target.fillna(False).astype(bool)
        small_maintained = maintained & trade_with_target.notional.div(
            trade_with_target.pretrade_nav).lt(0.005)
        held_actions = trades.action.value_counts().to_dict()
        fee_by_action = trades.groupby("action").transaction_cost.sum().to_dict()

        code_counts = Counter(diagnostics.code.astype(str))
        limited = diagnostics.loc[diagnostics.code.eq("capacity_limited")]
        limited_requested = float(limited.requested_notional.sum()) if not limited.empty else 0.0
        limited_allowed = float(limited.allowed_notional.sum()) if not limited.empty else 0.0
        buys = trades.loc[trades.side.eq("BUY")]
        known_buy_cap = buys.capacity_enforced.astype(bool) & buys.capacity_adv.notna()
        buy_cap_breaches = int((buys.loc[known_buy_cap, "notional"]
                                > buys.loc[known_buy_cap, "capacity_adv"] * .01 + 1e-6).sum())

        row = dict(
            policy=name,
            completed_2025_days=len(daily),
            uncertified_days=int(daily.valuation_status.ne("certified").sum()),
            gross_traded_notional=float(trades.notional.sum()),
            realized_fees=float(trades.transaction_cost.sum()),
            fees_pct_initial_nav=100 * float(trades.transaction_cost.sum()) / INITIAL_NAV,
            total_half_turnover=float(daily.turnover.sum()),
            terminal_indicative_return=safe_float(daily.nav.iloc[-1] / INITIAL_NAV - 1),
            trades=len(trades),
            buys=int(trades.side.eq("BUY").sum()),
            sells=int(trades.side.eq("SELL").sum()),
            trade_actions={key: int(value) for key, value in held_actions.items()},
            fees_by_action={key: float(value) for key, value in fee_by_action.items()},
            same_positive_grid_target_trade_count=int(maintained.sum()),
            same_positive_grid_target_trade_notional=float(trades.loc[maintained, "notional"].sum()),
            same_positive_grid_target_fees=float(trades.loc[maintained, "transaction_cost"].sum()),
            same_positive_grid_target_small_trade_count=int(small_maintained.sum()),
            same_positive_grid_target_small_trade_fees=float(
                trades.loc[small_maintained, "transaction_cost"].sum()),
            capacity_limited_events=int(code_counts["capacity_limited"]),
            capacity_limited_requested_notional=limited_requested,
            capacity_limited_allowed_notional=limited_allowed,
            capacity_limited_requested_minus_allowed=limited_requested - limited_allowed,
            missing_signal_day_adv_events=int(code_counts["missing_signal_day_adv"]),
            sell_capacity_unknown_exit_allowed_events=int(
                code_counts["sell_capacity_unknown_exit_allowed"]),
            buy_capacity_limit_breaches=buy_cap_breaches,
            max_abs_trade_fee_error=float(trade_fee_error),
            max_abs_daily_fee_error=float(daily_fee_error),
            max_abs_daily_notional_error=float(daily_notional_error),
            max_abs_cash_flow_error=float(daily.cash_flow_identity_error.abs().max()),
            max_abs_cost_identity_error=float(daily.cost_identity_error.abs().max()),
            max_abs_open_self_finance_error=float(daily.open_self_finance_error.abs().max()),
            no_trade_fee_days=no_trade_fee_days,
            same_ticker_two_sides_one_day=same_ticker_two_sides,
        )
        rows.append(row)
        print(json.dumps({key: row[key] for key in
                          ("policy", "realized_fees", "capacity_limited_events",
                           "same_positive_grid_target_trade_count")}), flush=True)

    assert len(rows) == 12
    audit = dict(
        status="PRE2026_READ_ONLY_COST_DIAGNOSTIC",
        batch="a2_latest_effective_joint_20260927",
        evaluation_year=2025,
        original_contract=dict(initial_account_dollars=INITIAL_NAV, cost_bps_each_side=10,
                               frozen_pressure_bps_each_side=[5, 25],
                               buy_capacity_fraction_signal_day_adv=.01,
                               sell_capacity_default="unrestricted risk exit"),
        limitation=("The unchanged-target classification does not identify causal grid cost. "
                    "Previous underfill, price drift, and next-open target sizing may contribute. "
                    "ADV is a raw-dollar proxy while position units are price-index units."),
        no_new_fit=True,
        no_2026_economic_input=True,
        source_sha256=input_hashes,
        code_sha256={key: sha256(ROOT / key) for key in
                     ("JOINT_CONTRACT.md", "engine.py", "run_suite.py",
                      "joint_linear_tree.py", "joint_neural.py")},
        policies=rows,
    )
    (OUT / "PRE2026_COST_AUDIT.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("PRE2026_COST_AUDIT_COMPLETE", len(rows), flush=True)


if __name__ == "__main__":
    main()
