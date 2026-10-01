"""Read-only accounting attribution of the 14 frozen ensemble ledger paths.

No model imports, fitting, policy calls, replay or parameter selection occurs here.
The recorded path is explained; all dollar sums of constraints are repeated order
flows, never a causal terminal-cash attribution or a cost-free strategy replay.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / "a2_buy_sell_cash_multimodel_20260928"
TOL = 1e-6
LEDGERS = ["daily", "trades", "target_decisions", "execution_results",
           "positions", "operational_actions", "signal_contexts", "valuation_intervals"]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def require_close(actual, expected, name, atol=TOL):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if not np.allclose(a, b, rtol=1e-10, atol=atol, equal_nan=False):
        raise AssertionError(f"{name}: max error {np.nanmax(np.abs(a-b))}")


def buy_fill_attribution(trades, targets, daily, capacity_fraction):
    """Exact ledger arithmetic for FILLED buys; actual open is recorded in trades."""
    buys = trades.loc[trades.side.eq("BUY")].copy()
    if buys.order_id.duplicated().any() or targets.order_id.duplicated().any():
        raise AssertionError("order IDs must identify unique orders/fills")
    buys = buys.merge(targets[["order_id", "adapted_target_weight", "signal_day_adv"]],
                      on="order_id", validate="one_to_one")
    buys = buys.merge(daily[["date", "buy_cash_scale", "open_stale_count", "open_unknown_count"]],
                      left_on="execution_date", right_on="date", validate="many_to_one")
    buys["requested_buy_notional"] = np.maximum(
        0, buys.adapted_target_weight * buys.pretrade_nav - buys.index_units_before * buys.price)
    if capacity_fraction is None:
        buys["capacity_capped_buy_notional"] = buys.requested_buy_notional
    else:
        if not (buys.signal_day_adv.gt(0) & buys.signal_day_adv.notna()).all():
            raise AssertionError("Filled buy lacks signal ADV")
        buys["capacity_capped_buy_notional"] = np.minimum(
            buys.requested_buy_notional, buys.signal_day_adv * capacity_fraction)
    buys["capacity_withheld_notional"] = buys.requested_buy_notional - buys.capacity_capped_buy_notional
    buys["funding_withheld_notional"] = buys.capacity_capped_buy_notional * (1 - buys.buy_cash_scale)
    buys["reconstructed_actual_notional"] = buys.capacity_capped_buy_notional * buys.buy_cash_scale
    buys["actual_reconstruction_error"] = buys.notional - buys.reconstructed_actual_notional
    require_close(buys.notional, buys.reconstructed_actual_notional, "filled buy bridge")
    require_close(buys.requested_buy_notional,
                  buys.notional + buys.capacity_withheld_notional + buys.funding_withheld_notional,
                  "requested = actual + capacity + funding")
    buys["notional_interpretation"] = np.where(
        buys.open_stale_count.eq(0) & buys.open_unknown_count.eq(0),
        "exact_recorded_open_NAV_arithmetic", "exact_recorded_arithmetic_with_uncertified_open_NAV")
    return buys


def constrained_events(execution, targets, daily, positions):
    """Keep rejected and preserved events without converting unknown values to 0."""
    events = execution.loc[~execution.status.isin(["NO_ACTION", "FILLED"])].copy()
    td = targets[["order_id", "adapted_target_weight", "current_units", "current_weight",
                  "signal_close_nav", "signal_reservation_reasons", "signal_day_adv"]]
    events = events.merge(td, on="order_id", how="left", validate="many_to_one")
    events = events.merge(daily[["date", "pretrade_nav", "valuation_status", "open_stale_count", "open_unknown_count"]],
                          left_on="execution_date", right_on="date", how="left", validate="many_to_one")
    # The engine's outcome default notional=0 is the fill amount, not the request.
    events = events.rename(columns={"notional": "ledger_filled_notional"})
    events["requested_notional_exact_from_ledger"] = np.nan
    events["request_amount_status"] = "UNESTIMABLE_FROM_LEDGER_WITHOUT_EXECUTION_OPEN"
    fresh = (events.status.eq("REJECTED") & events.side.eq("BUY") & events.current_units.eq(0)
             & events.pretrade_nav.gt(0) & events.adapted_target_weight.notna())
    events.loc[fresh, "requested_notional_exact_from_ledger"] = (
        events.loc[fresh, "adapted_target_weight"] * events.loc[fresh, "pretrade_nav"])
    events.loc[fresh, "request_amount_status"] = "EXACT_NEW_BUY_REQUEST_AT_RECORDED_NAV_NOT_FILLABLE_VALUE"
    preserved = events.status.eq("PRESERVED_UNITS")
    events.loc[preserved, "request_amount_status"] = "PRESERVED_UNITS_HAS_NO_TRADE_REQUEST"
    events["signal_position_marked_value"] = events.current_weight * events.signal_close_nav
    held = positions[["date", "ticker", "market_value", "stale", "unknown", "mark_date"]].rename(
        columns={"date": "execution_date", "market_value": "execution_close_position_marked_value",
                 "stale": "position_close_stale", "unknown": "position_close_unknown"})
    events = events.merge(held, on=["execution_date", "ticker"], how="left", validate="many_to_one")
    return events


def accounting_row(daily, initial_cash):
    fees = float(daily.transaction_cost_amount.sum())
    net_pnl = float(daily.iloc[-1].nav - initial_cash)
    return {"initial_cash": float(initial_cash), "final_recorded_nav": float(daily.iloc[-1].nav),
            "net_pnl": net_pnl, "cumulative_fees": fees,
            "gross_bookkeeping_pnl": net_pnl + fees,
            "recorded_return": net_pnl / initial_cash,
            "traded_notional": float(daily.traded_notional.sum()),
            "half_turnover": float(daily.turnover.sum()),
            "mean_cash_weight": float(daily.cash_weight.mean()),
            "uncertified_days": int(daily.valuation_status.ne("certified").sum())}


def pairwise_decomposition(rows):
    frame = pd.DataFrame(rows).set_index("policy")
    result = []
    for left, right in itertools.combinations(sorted(frame.index), 2):
        a, b = frame.loc[left], frame.loc[right]
        if a.initial_cash != b.initial_cash:
            raise AssertionError("pairwise dollar decomposition requires equal starting capital")
        row = {"left_policy": left, "right_policy": right, "direction": "left_minus_right"}
        for col in ["final_recorded_nav", "net_pnl", "gross_bookkeeping_pnl", "cumulative_fees",
                    "traded_notional", "half_turnover", "mean_cash_weight"]:
            row[col + "_difference"] = float(a[col] - b[col])
        row["fee_saving_contribution_to_net_difference"] = float(b.cumulative_fees-a.cumulative_fees)
        row["identity_error"] = (row["net_pnl_difference"] - row["gross_bookkeeping_pnl_difference"]
                                  - row["fee_saving_contribution_to_net_difference"])
        require_close([row["identity_error"]], [0], "H2 pairwise PnL identity")
        row["causal_diversification_or_cash_substitution_identified"] = False
        row["interpretation"] = "accounting_identity_on_observed_paths_not_no_cost_counterfactual"
        result.append(row)
    return pd.DataFrame(result)


def main():
    folders = []
    for cohort in ["ensemble_2025", "ensemble_2025_H2", "ensemble_2026"]:
        folders.extend(sorted((SOURCE / cohort).glob("cost_*/*/PATH_COMPLETE.json")))
    if len(folders) != 14:
        raise AssertionError(f"Expected the frozen 14 ensemble paths, got {len(folders)}")
    input_hashes, summaries, bridges, fills, events_all, ops_all = {}, [], [], [], [], []
    reason_summaries, h2, interval_rows = [], [], []
    audit = {"scenario_count": len(folders), "fit_calls": 0, "replay_calls": 0,
             "no_single_model_or_capacity_pairing_ledgers_read": True,
             "rejected_unknown_amounts_preserved_as_missing": True}
    for receipt_path in folders:
        folder = receipt_path.parent
        scenario = folder.relative_to(SOURCE).as_posix()
        cohort, cost, policy = scenario.split("/")
        paths = [receipt_path, folder / "metadata.json"] + [folder / (n + ".parquet") for n in LEDGERS]
        for p in paths:
            input_hashes[str(p)] = sha(p)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        for n in LEDGERS:
            if sha(folder / (n + ".parquet")) != receipt["ledger_sha256"][n]:
                raise AssertionError(f"Original receipt mismatch: {scenario}/{n}")
        ledger = {n: pd.read_parquet(folder / (n + ".parquet")) for n in LEDGERS}
        daily, trades, targets = ledger["daily"], ledger["trades"], ledger["target_decisions"]
        if daily.date.duplicated().any():
            raise AssertionError("duplicate daily dates")
        buy = buy_fill_attribution(trades, targets, daily, metadata["capacity_fraction"])
        ev = constrained_events(ledger["execution_results"], targets, daily, ledger["positions"])
        bridge = daily.copy()
        bridge["previous_cash"] = bridge.cash.shift(1).fillna(metadata["initial_cash"])
        bridge["recomputed_cash"] = bridge.previous_cash + bridge.sell_notional - bridge.buy_notional - bridge.transaction_cost_amount
        bridge["independent_cash_error"] = bridge.cash - bridge.recomputed_cash
        require_close(bridge.cash, bridge.recomputed_cash, "independent daily cash identity")
        aggregate_cols = ["requested_buy_notional", "capacity_capped_buy_notional", "capacity_withheld_notional", "funding_withheld_notional"]
        totals = buy.groupby("execution_date")[aggregate_cols].sum()
        bridge = bridge.merge(totals, left_on="date", right_index=True, how="left", validate="one_to_one")
        bridge[aggregate_cols] = bridge[aggregate_cols].fillna(0)
        bridge["capacity_cash_spend_avoided_including_fee_on_filled_buy_orders"] = (
            bridge.capacity_withheld_notional * (1 + metadata["cost_bps_one_way"] / 10000))
        bridge["funding_cash_spend_avoided_including_fee_on_filled_buy_orders"] = (
            bridge.funding_withheld_notional * (1 + metadata["cost_bps_one_way"] / 10000))
        # Trade sums are independently matched to every recorded daily row.
        by_day = trades.groupby(["execution_date", "side"]).notional.sum().unstack(fill_value=0)
        check = daily[["date", "buy_notional", "sell_notional"]].merge(by_day, left_on="date", right_index=True, how="left").fillna(0)
        require_close(check.buy_notional, check.get("BUY", pd.Series(0., index=check.index)), "daily buy sum")
        require_close(check.sell_notional, check.get("SELL", pd.Series(0., index=check.index)), "daily sell sum")
        require_close(trades.transaction_cost.sum(), daily.transaction_cost_amount.sum(), "total fees")
        # Each signal's target cash is a close-time budget, not same-day realized cash.
        ctx = ledger["signal_contexts"][["signal_date", "active_target_weight", "final_reserved_weight", "final_reserved_slots"]].copy()
        ctx["signal_target_cash_weight"] = 1 - ctx.active_target_weight - ctx.final_reserved_weight
        bridge = bridge.merge(ctx, on="signal_date", how="left", validate="many_to_one")
        bridge["qualification"] = np.where(bridge.valuation_status.eq("certified"),
            "recorded_price_path_certified_not_original_pool_or_total_return_certification",
            "indicative_only_uncertified_recorded_valuation")
        bridge["complete_original_pool_certified"] = False if cohort == "ensemble_2026" else np.nan
        bridge["shareholder_total_return_certified"] = metadata["shareholder_total_return_certified"]
        for df in [bridge, buy, ev]:
            df.insert(0, "scenario", scenario)
        bridges.append(bridge); fills.append(buy); events_all.append(ev)
        op = ledger["operational_actions"].copy()
        if len(op):
            op = op.merge(ledger["execution_results"][["order_id", "status", "reason", "side", "notional"]],
                          on="order_id", how="left", suffixes=("_operation", "_execution"), validate="one_to_many")
            op.insert(0, "scenario", scenario)
            ops_all.append(op)
        intervals = ledger["valuation_intervals"].copy()
        if len(intervals):
            intervals.insert(0, "scenario", scenario); interval_rows.append(intervals)
        rej = ev.loc[ev.status.eq("REJECTED")]
        pre = ev.loc[ev.status.eq("PRESERVED_UNITS")]
        row = dict(scenario=scenario, cohort=cohort, cost_bps=metadata["cost_bps_one_way"], policy=policy,
            days=len(daily), start_date=str(daily.date.min().date()), end_date=str(daily.date.max().date()),
            filled_buy_orders=len(buy), capacity_limited_filled_buy_orders=int(buy.capacity_withheld_notional.gt(TOL).sum()),
            requested_filled_buy_notional=float(buy.requested_buy_notional.sum()),
            actual_buy_notional=float(buy.notional.sum()),
            capacity_withheld_order_flow=float(buy.capacity_withheld_notional.sum()),
            funding_withheld_order_flow=float(buy.funding_withheld_notional.sum()),
            cash_scaled_days=int(daily.buy_cash_scale.lt(1-TOL).sum()),
            rejected_orders=len(rej), rejected_request_amount_estimable=int(rej.requested_notional_exact_from_ledger.notna().sum()),
            rejected_request_amount_unestimable=int(rej.requested_notional_exact_from_ledger.isna().sum()),
            rejected_estimable_requested_notional=float(rej.requested_notional_exact_from_ledger.sum(min_count=1)) if len(rej) else np.nan,
            preserved_unit_events=len(pre), preserved_unique_tickers=pre.ticker.nunique(),
            preserved_signal_marked_value_event_sum=float(pre.signal_position_marked_value.sum()),
            operational_action_rows=len(ledger["operational_actions"]),
            operational_actions_with_position=int(ledger["operational_actions"].get("had_position", pd.Series(dtype=bool)).sum()),
            last_cash=float(daily.iloc[-1].cash), last_cash_weight=float(daily.iloc[-1].cash_weight),
            open_stale_days=int(daily.open_stale_count.gt(0).sum()),
            max_buy_reconstruction_error=float(buy.actual_reconstruction_error.abs().max()),
            max_cash_reconstruction_error=float(bridge.independent_cash_error.abs().max()),
            **accounting_row(daily, metadata["initial_cash"]))
        summaries.append(row)
        for (status, reason, side), g in ev.groupby(["status", "reason", "side"], dropna=False):
            reason_summaries.append(dict(scenario=scenario, status=status, reason=reason, side=side, event_count=len(g),
                estimable_request_count=int(g.requested_notional_exact_from_ledger.notna().sum()),
                unestimable_request_count=int(g.requested_notional_exact_from_ledger.isna().sum()) if status == "REJECTED" else 0,
                known_requested_notional=g.requested_notional_exact_from_ledger.sum(min_count=1),
                signal_marked_position_value_event_sum=g.signal_position_marked_value.sum(min_count=1)))
        if cohort == "ensemble_2025_H2":
            if row["uncertified_days"] != 0:
                raise AssertionError("H2 accounting comparison unexpectedly uncertified")
            h2.append(row)
    # Hash every consumed original file again after all calculations.
    changed = [p for p, old in input_hashes.items() if sha(p) != old]
    if changed:
        raise AssertionError(f"Original source files changed: {changed}")
    all_events = pd.concat(events_all, ignore_index=True)
    preserved_events = all_events.loc[all_events.status.eq("PRESERVED_UNITS")]
    preservation_sources = preserved_events.groupby(["scenario", "signal_reservation_reasons"], dropna=False).agg(
        event_count=("order_id", "size"), unique_tickers=("ticker", "nunique"),
        signal_marked_position_value_event_sum=("signal_position_marked_value", lambda s: s.sum(min_count=1)),
        signal_marked_value_unknown_count=("signal_position_marked_value", lambda s: s.isna().sum())).reset_index()
    outputs = {
        "execution_scenario_summary.csv": pd.DataFrame(summaries),
        "execution_daily_cash_bridge.csv": pd.concat(bridges, ignore_index=True),
        "execution_filled_buy_attribution.csv": pd.concat(fills, ignore_index=True),
        "execution_rejected_preserved_detail.csv": all_events,
        "execution_preservation_sources.csv": preservation_sources,
        "execution_reason_summary.csv": pd.DataFrame(reason_summaries),
        "execution_operational_actions.csv": pd.concat(ops_all, ignore_index=True),
        "execution_valuation_intervals.csv": pd.concat(interval_rows, ignore_index=True),
        "execution_2025H2_accounting.csv": pd.DataFrame(h2),
        "execution_2025H2_pairwise.csv": pairwise_decomposition(h2),
    }
    for name, df in outputs.items():
        df.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    audit.update(status="PASS", original_ledger_receipt_hashes_match=True, inputs_unchanged=True,
        consumed_input_count=len(input_hashes), input_sha256=input_hashes,
        output_rows={k: len(v) for k, v in outputs.items()},
        output_sha256={k: sha(OUT/k) for k in outputs},
        scope="14 already-recorded ensemble scenarios; accounting only; no new experiment",
        qualifications=["2026 all daily rows and valuation intervals retained",
            "certified ledger price marks do not certify original pool or shareholder total return",
            "constraint dollar sums are repeated order flow, not terminal cash stock",
            "net PnL plus fees is bookkeeping gross, not cost-free policy counterfactual",
            "no causal cash substitution or member complementarity estimate is claimed"])
    (OUT / "execution_receipt.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in audit.items() if k not in ["input_sha256", "output_sha256"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
