"""Read-only audit of saved capacity decisions and fills.

This script deliberately does not call training, scoring, or the replay engine.
It inspects each previously saved path independently and writes only to this
continuation directory.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
BATCH = HERE.parent
INPUT_NAMES = (
    "diagnostics.parquet",
    "trades.parquet",
    "target_decisions.parquet",
    "positions.parquet",
    "daily.parquet",
    "metadata.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iso(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()


def main() -> None:
    paths = sorted((BATCH / "evaluation_2025").glob("*/diagnostics.parquet"))
    paths += sorted((BATCH / "evaluation_2026").glob("cost_*/*/diagnostics.parquet"))
    assert len(paths) == 54, f"Expected original 54 saved paths, found {len(paths)}"
    details: list[dict] = []
    summaries: list[dict] = []
    manifest: list[dict] = []
    missing_adv_events = 0
    unrestricted_exit_missing_adv_events = 0

    for diagnostic_path in paths:
        root = diagnostic_path.parent
        stage = "2025_validation" if root.parent.name == "evaluation_2025" else "2026_R6_subset"
        strategy = root.name.rsplit("_", 1)[0]
        cost_bps = int(root.name.rsplit("_", 1)[1].removesuffix("bps"))
        for name in INPUT_NAMES:
            path = root / name
            assert path.is_file(), path
            manifest.append({
                "stage": stage,
                "strategy": strategy,
                "cost_bps": cost_bps,
                "source_file": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["capacity_fraction"] == 0.01, root
        assert metadata["capacity_on_sells"] is False, root
        diagnostic = pd.read_parquet(diagnostic_path)
        trades = pd.read_parquet(root / "trades.parquet")
        decisions = pd.read_parquet(root / "target_decisions.parquet")
        positions = pd.read_parquet(root / "positions.parquet")
        daily = pd.read_parquet(root / "daily.parquet")
        limited = diagnostic.loc[diagnostic["code"] == "capacity_limited"].copy()
        other_codes = diagnostic.loc[diagnostic["code"] != "capacity_limited", "code"].value_counts().to_dict()
        missing_adv_count = int((diagnostic["code"] == "missing_signal_day_adv").sum())
        unrestricted_exit_missing_adv_count = int((diagnostic["code"] == "sell_capacity_unknown_exit_allowed").sum())
        missing_adv_events += missing_adv_count
        unrestricted_exit_missing_adv_events += unrestricted_exit_missing_adv_count
        buys = trades.loc[trades["side"] == "BUY"].copy()
        assert not buys.duplicated(["signal_date", "execution_date", "ticker"]).any(), root
        buy_lookup = {
            (r.signal_date, r.execution_date, r.ticker): r
            for r in buys.itertuples(index=False)
        }
        decision_lookup = {
            (r.signal_date, r.ticker): r
            for r in decisions.itertuples(index=False)
            if isinstance(r.ticker, str)
        }
        position_lookup = {
            (r.date, r.ticker): r
            for r in positions.itertuples(index=False)
        }
        day_lookup = {r.date: r for r in daily.itertuples(index=False)}
        trade_dates = trades.groupby("ticker")["execution_date"].apply(list).to_dict() if len(trades) else {}

        local: list[dict] = []
        for event in limited.itertuples(index=False):
            signal_date, execution_date, ticker = event.signal_date, event.date, event.ticker
            buy = buy_lookup.get((signal_date, execution_date, ticker))
            actual = float(buy.notional) if buy is not None else 0.0
            requested = float(event.requested_notional)
            allowed = float(event.allowed_notional)
            if not (requested > allowed >= 0 and actual <= allowed + 1e-5):
                raise AssertionError(f"Capacity accounting mismatch: {root} {event}")
            same_day_decision = decision_lookup.get((execution_date, ticker))
            same_day_position = position_lookup.get((execution_date, ticker))
            later_trades = [d for d in trade_dates.get(ticker, []) if d > execution_date]
            execution_daily = day_lookup.get(execution_date)
            row = {
                "stage": stage,
                "strategy": strategy,
                "cost_bps": cost_bps,
                "signal_date": iso(signal_date),
                "execution_date": iso(execution_date),
                "ticker": ticker,
                "requested_notional": requested,
                "capacity_allowed_notional": allowed,
                "actual_buy_notional": actual,
                "capacity_pre_cash_haircut": requested - allowed,
                "total_target_to_fill_gap": requested - actual,
                "post_cap_cash_gap": allowed - actual,
                "execution_price": float(buy.price) if buy is not None else np.nan,
                "unfilled_index_units_at_execution": (requested - actual) / float(buy.price) if buy is not None else np.nan,
                "actual_position_units_after_fill": float(buy.index_units_after) if buy is not None else np.nan,
                "buy_cash_scale": float(execution_daily.buy_cash_scale) if execution_daily is not None else np.nan,
                "same_day_close_position_exists": same_day_position is not None,
                "same_day_close_index_units": float(same_day_position.index_units) if same_day_position is not None else 0.0,
                "same_day_close_decision_has_ticker": same_day_decision is not None,
                "same_day_close_decision_current_weight": float(same_day_decision.current_weight) if same_day_decision is not None else np.nan,
                "same_day_close_decision_target_weight": float(same_day_decision.target_weight) if same_day_decision is not None else np.nan,
                "later_same_ticker_trade_count": len(later_trades),
                "first_later_same_ticker_trade_date": iso(min(later_trades)) if later_trades else "",
            }
            details.append(row)
            local.append(row)

        summary = {
            "stage": stage,
            "strategy": strategy,
            "cost_bps": cost_bps,
            "saved_trades": len(trades),
            "all_actual_buy_notional": float(buys["notional"].sum()),
            "capacity_limited_events": len(local),
            "missing_signal_day_adv_events": missing_adv_count,
            "sell_capacity_unknown_exit_allowed_events": unrestricted_exit_missing_adv_count,
            "capacity_limited_execution_days": len({r["execution_date"] for r in local}),
            "capacity_limited_signal_days": len({r["signal_date"] for r in local}),
            "capacity_limited_tickers": len({r["ticker"] for r in local}),
            "requested_notional_on_limited_events": sum(r["requested_notional"] for r in local),
            "allowed_notional_on_limited_events": sum(r["capacity_allowed_notional"] for r in local),
            "actual_buy_notional_on_limited_events": sum(r["actual_buy_notional"] for r in local),
            "capacity_pre_cash_haircut": sum(r["capacity_pre_cash_haircut"] for r in local),
            "total_target_to_fill_gap": sum(r["total_target_to_fill_gap"] for r in local),
            "post_cap_cash_gap": sum(r["post_cap_cash_gap"] for r in local),
            "limited_events_with_actual_fill": sum(r["actual_buy_notional"] > 0 for r in local),
            "limited_events_with_cash_scaling": sum(r["post_cap_cash_gap"] > 1e-5 for r in local),
            "limited_events_in_same_day_close_position": sum(r["same_day_close_position_exists"] for r in local),
            "limited_events_seen_in_same_day_decision": sum(r["same_day_close_decision_has_ticker"] for r in local),
            "limited_events_with_later_same_ticker_trades": sum(r["later_same_ticker_trade_count"] > 0 for r in local),
            "later_same_ticker_trade_occurrences": sum(r["later_same_ticker_trade_count"] for r in local),
            "other_diagnostic_codes": json.dumps(other_codes, sort_keys=True),
        }
        summaries.append(summary)

    details_frame = pd.DataFrame(details).sort_values(["stage", "cost_bps", "strategy", "execution_date", "ticker"])
    summaries_frame = pd.DataFrame(summaries).sort_values(["stage", "cost_bps", "strategy"])
    manifest_frame = pd.DataFrame(manifest).sort_values(["stage", "cost_bps", "strategy", "source_file"])
    details_frame.to_csv(HERE / "CAPACITY_LIMITED_EVENTS.csv", index=False)
    summaries_frame.to_csv(HERE / "CAPACITY_PATH_SUMMARY.csv", index=False)
    manifest_frame.to_csv(HERE / "SOURCE_MANIFEST.csv", index=False)
    security = details_frame.groupby(["stage", "cost_bps", "strategy", "ticker"], as_index=False).agg(
        limited_events=("ticker", "size"),
        first_execution_date=("execution_date", "min"),
        last_execution_date=("execution_date", "max"),
        requested_notional=("requested_notional", "sum"),
        allowed_notional=("capacity_allowed_notional", "sum"),
        actual_buy_notional=("actual_buy_notional", "sum"),
        capacity_pre_cash_haircut=("capacity_pre_cash_haircut", "sum"),
    )
    security.to_csv(HERE / "CAPACITY_SECURITY_SUMMARY.csv", index=False)
    aggregate = summaries_frame.groupby(["stage", "cost_bps"], as_index=False).agg({
        "strategy": "count",
        "all_actual_buy_notional": "sum",
        "capacity_limited_events": "sum",
        "missing_signal_day_adv_events": "sum",
        "sell_capacity_unknown_exit_allowed_events": "sum",
        "capacity_limited_execution_days": "sum",
        "capacity_pre_cash_haircut": "sum",
        "total_target_to_fill_gap": "sum",
        "post_cap_cash_gap": "sum",
        "limited_events_with_actual_fill": "sum",
        "limited_events_with_cash_scaling": "sum",
        "limited_events_seen_in_same_day_decision": "sum",
        "limited_events_with_later_same_ticker_trades": "sum",
    }).rename(columns={"strategy": "path_count"})
    aggregate.to_csv(HERE / "CAPACITY_AGGREGATE.csv", index=False)
    receipt = {
        "audit": "read_only_saved_target_fill_capacity_audit",
        "scope": "12 saved 2025 validation paths and 42 saved 2026 R6 subset paths",
        "saved_path_count": len(paths),
        "input_file_count": len(manifest),
        "limited_event_count": len(details),
        "missing_signal_day_adv_events": missing_adv_events,
        "sell_capacity_unknown_exit_allowed_events": unrestricted_exit_missing_adv_events,
        "fitting_calls": 0,
        "replay_calls": 0,
        "price_or_target_revisions": 0,
        "definitions": {
            "capacity_pre_cash_haircut": "sum(requested_notional - allowed_notional) at capacity_limited diagnostics; repeated requests are not independent capital",
            "total_target_to_fill_gap": "sum(requested_notional - actual buy fill), on those same events",
            "post_cap_cash_gap": "sum(allowed_notional - actual buy fill); includes cash scaling, not a capacity-specific causal effect",
            "downstream_trace": "same-day close position/current weight and later same-ticker trades demonstrate accounting path, not counterfactual order causality",
        },
    }
    (HERE / "AUDIT_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(aggregate.to_string(index=False))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
