"""Materialize the existing held-price and blocked-order demand, without replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
STRICT = ROOT.parent / "a2_strict_method_retrain_20260926" / "test2026_stage"
VALUATION = ROOT / "continuation_valuation_r1"
EVAL = ROOT / "evaluation_2026"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dates(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()


def joined(values) -> str:
    return "|".join(sorted(set(map(str, values))))


def main() -> None:
    summary_path = VALUATION / "TICKER_EVIDENCE_SUMMARY.csv"
    intervals_path = VALUATION / "HOLDING_IMPACT_INTERVALS.csv"
    union_path = VALUATION / "AFFECTED_TICKER_DATE_UNION.csv"
    events_path = STRICT / "r4_event_pit" / "ALL_1094_EVENT_PRIORITY.csv"
    verdict_path = STRICT / "r7_cash_first_event_proposal" / "R7_TWELVE_CASH_EVENT_VERDICTS.csv"
    prices_path = ROOT / "data" / "test_prices.parquet"
    summary = pd.read_csv(summary_path).fillna("")
    intervals = pd.read_csv(intervals_path)
    union = pd.read_csv(union_path)
    events = pd.read_csv(events_path).fillna("")
    verdicts = pd.read_csv(verdict_path).fillna("")
    prices = pd.read_parquet(prices_path)
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    assert len(summary) == 45 and summary.ticker.is_unique
    assert len(intervals) == 162 and intervals.run_id.nunique() == 27
    assert union.ticker.nunique() == 45

    event_by_key = {}
    for r in events.itertuples(index=False):
        event_by_key.setdefault((str(r.ticker), str(r.event_date)), []).append(r)
    verdict_by_code = {r.event_code: r for r in verdicts.itertuples(index=False)}
    first_union = union.sort_values(["ticker", "date"]).drop_duplicates("ticker")
    first_union = first_union.set_index("ticker")
    held_rows = []
    for r in summary.itertuples(index=False):
        first = str(r.first_affected_valuation_date)
        u = first_union.loc[r.ticker]
        group = intervals[intervals.ticker.eq(r.ticker)]
        event_candidates = event_by_key.get((r.ticker, first), [])
        event = event_candidates[0] if event_candidates else None
        verdict = verdict_by_code.get("US." + r.ticker)
        if r.ticker == "EXAS":
            need = "merger_105_cash_right_effective_time_payment_or_receivable_clock_and_index_unit_to_share_entitlement"
            source = "REMAINING75_RESOLUTION.csv:US.EXAS; SEC 2026-03-23 8-K Item 2.01/3.01; no post-2026-03-20 Raw"
            state = "MISSING_SETTLEMENT_PROOF_NO_PRICE_ROW"
        elif r.ticker == "DTP":
            need = "US.DTE_event_clock_adjusted_open_close_and_2026-09-23_24_raw_if_held"
            source = "REMAINING75_RESOLUTION.csv:US.DTP=>US.DTE; ALL_1094_EVENT_PRIORITY.csv; original same-source Raw"
            state = "EVENT_UNPROVED_AND_TERMINAL_RAW_GAP"
        else:
            need = "event_publication_clock_vendor_adjustment_coordinate_and_qualified_open_close"
            source = "ALL_1094_EVENT_PRIORITY.csv; saved original same-source Raw and event proof"
            state = "R7_FIRST_EVENT_CANDIDATE_RELEASE_NEEDS_ACCOUNT_USE_CHECK" if verdict else "NO_R7_EVENT_RELEASE"
        held_rows.append(dict(
            ticker=r.ticker, original_code=str(u.original_transport), transport_used=str(u.transport_used),
            first_held_need_date=first, last_old_held_need_date=str(r.last_affected_valuation_date),
            affected_run_count=int(r.affected_runs), old_run_ids=joined(group.run_id),
            old_unique_held_days=int(r.affected_unique_valuation_days),
            first_need="pending_open_execution_if_order_then_close_valuation",
            first_block_class=str(u.valuation_block_class), old_first_saved_raw_row=bool(u.saved_price_row),
            first_event_date=str(event.event_date) if event else "",
            first_event_factor_a=str(event.factor_a) if event else "",
            first_event_historical_vendor_status=str(event.historical_vendor_version_status) if event else "",
            r7_candidate_verified_days=int(r.r7_exact_candidate_verified_days),
            r7_first_event_public_date=str(verdict.source_public_date) if verdict else "",
            r7_first_event_exdate=str(verdict.record_and_original_vendor_exdate) if verdict else "",
            r7_next_unproved_event_exclusive=str(verdict.next_unproved_event_exclusive) if verdict else "",
            r7_historical_vendor_actual_receipt_observed=bool(verdict.historical_vendor_actual_receipt_observed) if verdict else "",
            next_evidence_item=need, existing_evidence_anchor=source, current_account_use_status=state,
            scope="R6_FIXED_CANDIDATE_ACCOUNT_REPAIR_NOT_R7_CANDIDATE_MERGE",
        ))
    held = pd.DataFrame(held_rows).sort_values(["first_held_need_date", "ticker"])
    assert held.ticker.nunique() == 45
    held.to_csv(OUT / "INITIAL_HELD_INPUT_QUEUE.csv", index=False)

    diagnostics_paths = sorted(EVAL.glob("cost_*/*/diagnostics.parquet"))
    assert len(diagnostics_paths) == 42
    missing_buy = []
    for path in diagnostics_paths:
        d = pd.read_parquet(path)
        d = d[d.code.eq("missing_open_buy")]
        for row in d.itertuples(index=False):
            missing_buy.append(dict(run_id=path.parent.name, policy=str(row.candidate),
                                    execution_date=dates(row.date), ticker=str(row.ticker),
                                    signal_date=dates(row.signal_date)))
    buys = pd.DataFrame(missing_buy)
    assert len(buys) == 132 and buys.ticker.nunique() == 39
    buy_queue = buys.groupby(["ticker", "execution_date", "signal_date"], as_index=False).agg(
        old_blocked_buy_run_ids=("run_id", joined), old_blocked_buy_path_count=("run_id", "nunique"))
    first_price = prices.sort_values(["ticker", "trade_date"]).drop_duplicates(["ticker", "trade_date"])
    first_price["execution_date"] = first_price.trade_date.dt.date.astype(str)
    buy_queue = buy_queue.merge(first_price[["ticker", "execution_date", "open", "close",
                                              "price_quality_warning", "unresolved_event_on_or_before",
                                              "lifecycle_ended", "extreme_adjusted_jump"]],
                                how="left", on=["ticker", "execution_date"], validate="many_to_one")
    buy_queue["in_initial_held_union"] = buy_queue.ticker.isin(set(held.ticker))
    buy_queue["needed_field"] = "qualified_execution_open; then close valuation if filled"
    buy_queue["proof_needed"] = buy_queue.apply(
        lambda x: "consume_saved_FLYX_same_class_true_jump_proof_for_execution_open_and_close" if x.ticker == "FLYX"
        else "extreme_adjusted_jump_source_and_coordinate" if x.extreme_adjusted_jump
        else "event_clock_and_adjustment_version" if x.unresolved_event_on_or_before
        else "missing_raw_or_other_price_gate", axis=1)
    buy_queue["existing_evidence_anchor"] = buy_queue.ticker.apply(
        lambda t: "r4_identity/FLYX_ISSUER_PROSPECTUS_20260109.html; JUMP_TWO_CODE_RAW_OVERLAP_CHECK.csv; r4_continuation/R4_FLYX_APPLICATION_REPORT.json"
        if t == "FLYX" else "r4_event_pit/ALL_1094_EVENT_PRIORITY.csv; saved original same-source Raw")
    buy_queue["account_use_status"] = buy_queue.ticker.apply(
        lambda t: "SAVED_PROOF_AVAILABLE_ACCOUNT_EXECUTION_REVIEW_PENDING" if t == "FLYX"
        else "ORIGINAL_EVENT_AND_VERSION_PROOF_UNRESOLVED")
    buy_queue = buy_queue.sort_values(["execution_date", "ticker"])
    buy_queue.to_csv(OUT / "KNOWN_BLOCKED_BUY_DEMAND.csv", index=False)

    first_stale_path = VALUATION / "PATH_FIRST_UNCERTIFIED.csv"
    stale = pd.read_csv(first_stale_path)
    path_rows = []
    for path in diagnostics_paths:
        run_id = path.parent.name
        diag = pd.read_parquet(path)
        relevant = diag[diag.code.isin(["missing_open_buy", "missing_open_sell"])].copy()
        stale_this = stale[stale.run_id.eq(run_id) & stale.first_uncertified_valuation_date.notna()]
        choices = []
        if not relevant.empty:
            first_order = relevant.date.min()
            first_order_rows = relevant[relevant.date.eq(first_order)]
            choices.append((pd.Timestamp(first_order), "blocked_execution_open",
                            joined(first_order_rows.ticker.dropna()), joined(first_order_rows.code)))
        if not stale_this.empty:
            s = stale_this.iloc[0]
            choices.append((pd.Timestamp(s.first_uncertified_valuation_date), "uncertified_held_close",
                            str(s.first_affected_tickers), "stale_or_unknown_mark"))
        if choices:
            first_date = min(c[0] for c in choices)
            same_day = [c for c in choices if c[0] == first_date]
            first_type = joined(c[1] for c in same_day)
            tickers = joined(t for c in same_day for t in c[2].split("|"))
            diagnostics = joined(c[3] for c in same_day)
            status = "PAUSE_BEFORE_FIRST_INPUT_CONSUMPTION_IF_NOT_PROVEN"
        else:
            first_date = pd.NaT
            first_type = tickers = diagnostics = ""
            status = "NO_OLD_MISSING_OPEN_OR_HELD_VALUATION"
        path_rows.append(dict(run_id=run_id, policy=path.parent.name.rsplit("_", 1)[0],
                              cost_scenario=path.parent.parent.name,
                              first_old_input_block_date=dates(first_date) if pd.notna(first_date) else "",
                              first_old_input_block_kind=first_type, first_old_input_block_tickers=tickers,
                              first_old_diagnostic_codes=diagnostics, status=status))
    path_first = pd.DataFrame(path_rows).sort_values(["first_old_input_block_date", "run_id"])
    assert len(path_first) == 42 and path_first.run_id.is_unique
    path_first.to_csv(OUT / "PATH_FIRST_INPUT_BLOCK.csv", index=False)

    # Engine emits a zero for held tickers omitted from positive targets.
    # That diagnostic does not retain the policy's reason for omission.
    actions = intervals[["run_id", "policy", "cost_bps", "ticker", "start_date",
                         "first_day_ticker_decision_status", "first_day_ticker_current_weight",
                         "first_day_ticker_target_weight"]].copy()
    actions = actions.rename(columns={"start_date": "first_stale_date"})
    actions["persisted_source"] = "target_decisions.parquet; engine.py positive-target filter"
    actions["actor_records_applicable"] = False
    actions["per_ticker_action_reason_retained"] = False
    actions["interpretation"] = "zero_target_observed; active_exit_reason_unverified"
    actions["source_detail"] = actions.policy.apply(
        lambda p: "run_suite.py hgb baseline computes TOP20, but exclusion reason not saved"
        if p == "hgb_return_baseline" else
        "joint_linear_tree.py last_actions exists in memory but run_suite.py did not persist it"
        if p.startswith("joint_") and p not in {"joint_mlp", "joint_rl_ensemble", "joint_rl_zero_control"}
        else "neural projected weights/top20 output not persisted at ticker action-reason level")
    assert len(actions) == 162 and actions.first_day_ticker_target_weight.eq(0).all()
    actions.to_csv(OUT / "OLD_ZERO_TARGET_SOURCE.csv", index=False)

    source_paths = [summary_path, intervals_path, union_path, first_stale_path,
                    events_path, verdict_path, prices_path]
    source_paths += diagnostics_paths
    receipt = dict(
        scope="existing_union_demand_only_no_replay_no_fit",
        held_union_tickers=int(held.ticker.nunique()), held_affected_paths=int(intervals.run_id.nunique()),
        first_held_intervals=int(len(intervals)), missing_open_buy_events=int(len(buys)),
        known_blocked_buy_exact_ticker_execution_signal_keys=int(len(buy_queue)),
        known_blocked_buy_tickers=int(buy_queue.ticker.nunique()),
        first_input_blocked_paths=int(path_first.first_old_input_block_date.ne("").sum()),
        blocked_buy_tickers_outside_held_union=sorted(set(buy_queue.ticker) - set(held.ticker)),
        output_sha256={p.name: sha(p) for p in sorted(OUT.glob("*.csv"))},
        source_sha256={str(p): sha(p) for p in source_paths},
        model_fit_calls=0, preprocessor_fit_calls=0, account_replay_calls=0,
    )
    (OUT / "QUEUE_RECEIPT.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ["held_union_tickers", "missing_open_buy_events",
                                                 "known_blocked_buy_exact_ticker_execution_signal_keys",
                                                 "blocked_buy_tickers_outside_held_union"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
