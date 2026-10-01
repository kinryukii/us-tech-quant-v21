"""Read-only audit of the frozen R6 2026 accounting paths.

This script reads the existing 42 policy/cost ledgers and the separately
versioned R7 candidate gate. It does not approve prices, replay accounts,
fit models, or modify any pre-existing output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
STAGE = ROOT.parent / "a2_strict_method_retrain_20260926" / "test2026_stage"
R6 = STAGE / "r6_contract_correction" / "R6_FULL_CANDIDATE_INPUT_GATE.parquet"
R7 = STAGE / "r7_applied" / "R7_FINAL_CANDIDATE_INPUT_GATE.parquet"
R7_EVENT = STAGE / "r7_cash_first_event_proposal" / "R7_TWELVE_CASH_EVENT_VERDICTS.csv"
PRICE = ROOT / "data" / "test_prices.parquet"
EVENT_COLS = ["unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump"]
ISSUE_COLS = ["stale", "unknown"]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def day(value: object) -> str | None:
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def main() -> None:
    prices = pd.read_parquet(PRICE)
    prices = prices.rename(columns={"trade_date": "date"})
    assert not prices.duplicated(["ticker", "date"]).any()
    price_cols = ["ticker", "date", "open", "close", "price_coordinate", "original_transport",
                  "transport_used", "price_quality_warning", *EVENT_COLS]
    prices = prices[price_cols].copy()
    prices["saved_price_row"] = True
    first_rows: list[dict] = []
    interval_rows: list[dict] = []
    propagation_rows: list[dict] = []
    ledger_hash_rows: list[dict] = []
    all_affected: list[pd.DataFrame] = []

    for cost in (5, 10, 25):
        folders = sorted((ROOT / "evaluation_2026" / f"cost_{cost}").glob("*bps"))
        assert len(folders) == 14, (cost, len(folders))
        for folder in folders:
            policy = folder.name.removesuffix(f"_{cost}bps")
            run_id = f"{policy}_{cost}bps"
            ledger_names = ("daily", "positions", "trades", "target_decisions", "diagnostics")
            ledger_paths = {name: folder / f"{name}.parquet" for name in ledger_names}
            assert len(ledger_paths) == 5 and all(path.is_file() for path in ledger_paths.values()), run_id
            for name, path in ledger_paths.items():
                ledger_hash_rows.append({
                    "run_id": run_id, "policy": policy, "cost_bps": cost,
                    "ledger": name, "source_path": str(path), "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                })
            daily = pd.read_parquet(folder / "daily.parquet")
            positions = pd.read_parquet(folder / "positions.parquet")
            targets = pd.read_parquet(folder / "target_decisions.parquet")
            trades = pd.read_parquet(folder / "trades.parquet")
            diagnostic = pd.read_parquet(folder / "diagnostics.parquet")
            assert not positions.duplicated(["date", "ticker"]).any(), run_id
            affected = positions.loc[positions[ISSUE_COLS].any(axis=1)].copy()
            affected["run_id"] = run_id
            affected["policy"] = policy
            affected["cost_bps"] = cost
            all_affected.append(affected[["run_id", "policy", "cost_bps", "ticker", "date", "stale", "unknown"]])
            uncert = daily.loc[daily.valuation_status.ne("certified")].sort_values("date")
            first = uncert.date.min() if len(uncert) else pd.NaT
            first_bad = affected.loc[affected.date.eq(first)].sort_values("ticker")
            first_target = targets.loc[targets.signal_date.eq(first)] if pd.notna(first) else targets.iloc[:0]
            first_trade = trades.loc[trades.signal_date.eq(first)] if pd.notna(first) else trades.iloc[:0]
            first_diag = diagnostic.loc[diagnostic.date.eq(first)] if pd.notna(first) else diagnostic.iloc[:0]
            first_rows.append({
                "run_id": run_id, "policy": policy, "cost_bps": cost,
                "first_uncertified_valuation_date": day(first),
                "first_affected_tickers": "|".join(first_bad.ticker.astype(str)),
                "first_mark_dates": "|".join(f"{row.ticker}:{day(row.mark_date)}:{row.mark_source}" for row in first_bad.itertuples()),
                "uncertified_valuation_days": len(uncert),
                "first_day_target_submitted_rows": int(first_target.status.eq("submitted").sum()),
                "first_day_next_execution_trades": len(first_trade),
                "first_day_missing_open_sell": int(first_diag.code.eq("missing_open_sell").sum()),
                "first_day_missing_open_buy": int(first_diag.code.eq("missing_open_buy").sum()),
                "first_day_unknown_nav_block": int(first_diag.code.eq("execution_blocked_unknown_nav").sum()),
            })

            session = dict(zip(daily.date, range(len(daily))))
            for ticker, grp in affected.sort_values("date").groupby("ticker", sort=True):
                grp = grp.copy()
                grp["session_index"] = grp.date.map(session)
                grp["segment"] = grp.session_index.diff().ne(1).cumsum()
                for _, seg in grp.groupby("segment"):
                    start, end = seg.date.min(), seg.date.max()
                    same_signal = targets.loc[targets.signal_date.between(start, end)]
                    same_trades = trades.loc[trades.signal_date.between(start, end)]
                    ticker_signal = same_signal.loc[same_signal.ticker.eq(ticker)]
                    ticker_first = ticker_signal.loc[ticker_signal.signal_date.eq(start)]
                    ticker_first_row = ticker_first.iloc[0] if len(ticker_first) else None
                    ticker_trades_after_start = trades.loc[trades.ticker.eq(ticker) & trades.execution_date.gt(start)]
                    diag = diagnostic.loc[diagnostic.date.between(start, end)]
                    interval_rows.append({
                        "run_id": run_id, "policy": policy, "cost_bps": cost, "ticker": ticker,
                        "start_date": day(start), "end_date": day(end), "sessions": len(seg),
                        "stale_days": int(seg.stale.sum()), "unknown_days": int(seg.unknown.sum()),
                        "submitted_target_rows_during_interval": int(same_signal.status.eq("submitted").sum()),
                        "trades_from_interval_signals": len(same_trades),
                        "first_day_ticker_decision_status": ticker_first_row.status if ticker_first_row is not None else None,
                        "first_day_ticker_current_weight": ticker_first_row.current_weight if ticker_first_row is not None else None,
                        "first_day_ticker_target_weight": ticker_first_row.target_weight if ticker_first_row is not None else None,
                        "ticker_submitted_target_rows_during_interval": int(ticker_signal.status.eq("submitted").sum()),
                        "ticker_trades_after_start_execution": len(ticker_trades_after_start),
                        "missing_open_sell_events_for_ticker": int((diag.code.eq("missing_open_sell") & diag.ticker.eq(ticker)).sum()),
                        "missing_open_buy_events_for_ticker": int((diag.code.eq("missing_open_buy") & diag.ticker.eq(ticker)).sum()),
                    })

            bad_dates = set(uncert.date)
            bad_targets = targets.loc[targets.signal_date.isin(bad_dates)]
            bad_trades = trades.loc[trades.signal_date.isin(bad_dates)]
            bad_diag = diagnostic.loc[diagnostic.date.isin(bad_dates)]
            propagation_rows.append({
                "run_id": run_id, "policy": policy, "cost_bps": cost,
                "first_uncertified_valuation_date": day(first),
                "uncertified_valuation_days": len(uncert),
                "all_affected_holding_rows": len(affected),
                "affected_unique_tickers": affected.ticker.nunique(),
                "submitted_target_rows_on_uncertified_days": int(bad_targets.status.eq("submitted").sum()),
                "submitted_signal_days_with_uncertified_nav": int(bad_targets.loc[bad_targets.status.eq("submitted"), "signal_date"].nunique()),
                "trades_from_uncertified_day_signals": len(bad_trades),
                "missing_open_sell_events_on_uncertified_days": int(bad_diag.code.eq("missing_open_sell").sum()),
                "missing_open_buy_events_on_uncertified_days": int(bad_diag.code.eq("missing_open_buy").sum()),
                "unknown_nav_execution_blocks_on_uncertified_days": int(bad_diag.code.eq("execution_blocked_unknown_nav").sum()),
            })

    path_first = pd.DataFrame(first_rows).sort_values(["cost_bps", "policy"])
    ledger_manifest = pd.DataFrame(ledger_hash_rows).sort_values(["cost_bps", "policy", "ledger"])
    assert len(path_first) == 42 and len(ledger_manifest) == 42 * 5
    assert not ledger_manifest.duplicated(["run_id", "ledger"]).any()
    intervals = pd.DataFrame(interval_rows).sort_values(["cost_bps", "policy", "ticker", "start_date"])
    propagation = pd.DataFrame(propagation_rows).sort_values(["cost_bps", "policy"])
    affected_all = pd.concat(all_affected, ignore_index=True)
    affected_keys = affected_all[["ticker", "date"]].drop_duplicates().sort_values(["ticker", "date"])
    union = affected_keys.merge(prices, on=["ticker", "date"], how="left", validate="one_to_one")
    union["saved_price_row"] = union.saved_price_row.fillna(False).astype(bool)
    for col in ["price_quality_warning", *EVENT_COLS]:
        union[col] = union[col].fillna(False).astype(bool)
    union["valuation_block_class"] = "other"
    union.loc[~union.saved_price_row, "valuation_block_class"] = "raw_price_row_absent"
    union.loc[union.unresolved_event_on_or_before, "valuation_block_class"] = "unresolved_event_warning"
    union.loc[union.lifecycle_ended, "valuation_block_class"] = "lifecycle_warning"
    union.loc[union.extreme_adjusted_jump, "valuation_block_class"] = "extreme_jump_warning"
    assert union.valuation_block_class.ne("other").all()
    run_members = affected_all.groupby(["ticker", "date"]).run_id.apply(lambda x: "|".join(sorted(set(x)))).rename("affected_runs").reset_index()
    union = union.merge(run_members, on=["ticker", "date"], validate="one_to_one")

    gates = []
    for version, path in (("r6", R6), ("r7", R7)):
        gate = pd.read_parquet(path, columns=["signal_date", "ticker", "final_input_gate"])
        assert not gate.duplicated(["ticker", "signal_date"]).any()
        gate = gate.rename(columns={"signal_date": "date", "final_input_gate": f"{version}_candidate_gate"})
        gates.append(gate)
        union = union.merge(gate, on=["ticker", "date"], how="left", validate="one_to_one")

    event = pd.read_csv(R7_EVENT)
    event["ticker"] = event.event_code.str.removeprefix("US.")
    event = event[["ticker", "source_public_date", "record_and_original_vendor_exdate",
                   "next_unproved_event_exclusive", "exact_candidate_keys", "source_publication_tier",
                   "historical_vendor_actual_receipt_observed"]]
    summary_rows = []
    for ticker, grp in union.groupby("ticker", sort=True):
        r7_yes = grp.loc[grp.r7_candidate_gate.fillna("").str.startswith("INPUT_VERIFIED")]
        r7_unknown_after = grp.loc[grp.date.gt(r7_yes.date.max()) &
                                   grp.r7_candidate_gate.fillna("").str.startswith("UNKNOWN")] if len(r7_yes) else grp.iloc[:0]
        ev = event.loc[event.ticker.eq(ticker)]
        first_event = ev.iloc[0] if len(ev) else None
        summary_rows.append({
            "ticker": ticker, "first_affected_valuation_date": day(grp.date.min()),
            "last_affected_valuation_date": day(grp.date.max()),
            "affected_unique_valuation_days": len(grp),
            "affected_runs": len(set("|".join(grp.affected_runs).split("|"))),
            "unresolved_event_warning_days": int(grp.unresolved_event_on_or_before.sum()),
            "raw_price_row_absent_days": int((~grp.saved_price_row).sum()),
            "lifecycle_warning_days": int(grp.lifecycle_ended.sum()),
            "extreme_jump_warning_days": int(grp.extreme_adjusted_jump.sum()),
            "r6_exact_candidate_verified_days": int(grp.r6_candidate_gate.fillna("").str.startswith("INPUT_VERIFIED").sum()),
            "r7_exact_candidate_verified_days": len(r7_yes),
            "r7_first_exact_candidate_verified_date": day(r7_yes.date.min()) if len(r7_yes) else None,
            "r7_last_exact_candidate_verified_date": day(r7_yes.date.max()) if len(r7_yes) else None,
            "r7_first_subsequent_unknown_candidate_date": day(r7_unknown_after.date.min()) if len(r7_unknown_after) else None,
            "r7_first_cash_event_next_unproved_exclusive": first_event.next_unproved_event_exclusive if first_event is not None else None,
            "r7_first_cash_event_original_vendor_receipt_observed": bool(first_event.historical_vendor_actual_receipt_observed) if first_event is not None else None,
            "entire_actual_valuation_suffix_qualified": False,
            "price_restoration_permitted_by_this_audit": False,
        })
    ticker_summary = pd.DataFrame(summary_rows).sort_values("ticker")

    path_first.to_csv(OUT / "PATH_FIRST_UNCERTIFIED.csv", index=False)
    intervals.to_csv(OUT / "HOLDING_IMPACT_INTERVALS.csv", index=False)
    propagation.to_csv(OUT / "PATH_PROPAGATION.csv", index=False)
    ledger_manifest.to_csv(OUT / "SOURCE_LEDGER_SHA256.csv", index=False)
    union.to_csv(OUT / "AFFECTED_TICKER_DATE_UNION.csv", index=False)
    ticker_summary.to_csv(OUT / "TICKER_EVIDENCE_SUMMARY.csv", index=False)

    affected_paths = path_first.loc[path_first.uncertified_valuation_days.gt(0)]
    info = {
        "status": "READ_ONLY_EXISTING_R6_PATH_AUDIT_NO_PRICE_RESTORATION",
        "scope": "14 frozen policies x 3 cost scenarios; R6 2026 verified subset, not full original pool",
        "paths": len(path_first), "affected_paths": len(affected_paths),
        "unaffected_paths": len(path_first) - len(affected_paths),
        "affected_ticker_union": ticker_summary.ticker.tolist(),
        "affected_ticker_count": len(ticker_summary),
        "affected_unique_ticker_valuation_days": len(union),
        "old_ledger_source_files_hashed": len(ledger_manifest),
        "old_ledger_source_manifest_sha256": sha256(OUT / "SOURCE_LEDGER_SHA256.csv"),
        "saved_but_warning_ticker_valuation_days": int(union.price_quality_warning.sum()),
        "absent_price_row_ticker_valuation_days": int((~union.saved_price_row).sum()),
        "absent_price_by_ticker": union.loc[~union.saved_price_row].ticker.value_counts().to_dict(),
        "warning_flag_counts_on_affected_days": {c: int(union[c].sum()) for c in EVENT_COLS},
        "r7_limited_cash_event_tickers_in_affected_union": ticker_summary.loc[ticker_summary.r7_exact_candidate_verified_days.gt(0), "ticker"].tolist(),
        "r6_affected_ticker_days_with_exact_verified_candidate_gate": int(union.r6_candidate_gate.fillna("").str.startswith("INPUT_VERIFIED").sum()),
        "r7_affected_ticker_days_with_exact_verified_candidate_gate": int(union.r7_candidate_gate.fillna("").str.startswith("INPUT_VERIFIED").sum()),
        "affected_ticker_days_without_matching_candidate_key": int(union.r7_candidate_gate.isna().sum()),
        "all_affected_paths_have_submitted_first_day_target": bool(affected_paths.first_day_target_submitted_rows.gt(0).all()),
        "all_affected_paths_have_trades_from_first_day_target": bool(affected_paths.first_day_next_execution_trades.gt(0).all()),
        "all_affected_ticker_segments_extend_to_terminal": bool(intervals.end_date.eq("2026-09-24").all()),
        "affected_ticker_segments": len(intervals),
        "affected_ticker_segments_with_positive_first_current_weight": int(intervals.first_day_ticker_current_weight.gt(0).sum()),
        "affected_ticker_segments_with_zero_first_target_weight": int(intervals.first_day_ticker_target_weight.eq(0).sum()),
        "affected_ticker_trades_after_first_impact": int(intervals.ticker_trades_after_start_execution.sum()),
        "missing_open_sell_events_for_affected_tickers": int(intervals.missing_open_sell_events_for_ticker.sum()),
        "r6_candidate_input_version_sha256": sha256(R6),
        "r7_candidate_input_version_sha256": sha256(R7),
        "r6_joint_test_prices_sha256": sha256(PRICE),
        "decisions": [
            "No saved numeric price is upgraded merely because a parquet row exists.",
            "R7 exact candidate approvals do not silently replace the R6 joint-branch input or qualify the full position suffix.",
            "Missing EXAS and DTP price rows need independently qualified exit/valuation handling; positions are not removed.",
            "No original accounting ledger is overwritten and no strategy is replayed by this audit.",
        ],
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: info[k] for k in ["status", "paths", "affected_paths", "affected_ticker_count",
                                           "affected_unique_ticker_valuation_days", "saved_but_warning_ticker_valuation_days",
                                           "absent_price_row_ticker_valuation_days"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
