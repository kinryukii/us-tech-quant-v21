from __future__ import annotations

from pathlib import Path

import pandas as pd


STAGE = "V21.151_R1_INVALID_PENDING_AUDIT"
OUT = Path("outputs/v21/V21.151_R1_INVALID_PENDING_AUDIT")
V151 = Path("outputs/v21/V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER")
LEDGER = V151 / "forward_execution_overlay_ledger.csv"
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
PRIMARY = {
    "strategy_name": "B_STATIC_MOMENTUM_BLEND",
    "bucket": "Top20",
    "execution_variant": "EXEC_OVERHEAT_SKIP",
    "horizon": "10D",
}


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def load_dates() -> list[pd.Timestamp]:
    df = pd.read_csv(PRICE, usecols=["date"])
    return [pd.Timestamp(d) for d in sorted(pd.to_datetime(df["date"]).dropna().unique())]


def next_trading_date(dates: list[pd.Timestamp], d: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    pos = {dt: i for i, dt in enumerate(dates)}
    i = pos.get(d)
    if i is None or i + offset >= len(dates):
        return None
    return dates[i + offset]


def classify(row: pd.Series, dates: list[pd.Timestamp]) -> tuple[str, bool, bool, bool, str]:
    status = str(row["maturity_status"]).lower()
    entry_allowed = bool(row["entry_allowed"])
    ranking_date = pd.Timestamp(row["ranking_date"])
    latest = pd.Timestamp(row["latest_price_date_used"])
    expected_execution = next_trading_date(dates, ranking_date, 1)
    expected_exit = next_trading_date(dates, ranking_date, 11)
    if status == "pending":
        if expected_execution is None or latest < ranking_date:
            return "PENDING_WAIT_EXECUTION_PRICE", True, False, False, "Expected: price panel has no post-ranking execution bar yet."
        if expected_exit is None or latest < expected_exit:
            return "PENDING_WAIT_FORWARD_EXIT_PRICE", True, False, False, "Expected: 10D exit price is not available yet."
        return "INVALID_OTHER_IMPLEMENTATION_WARN", False, True, True, "Pending row has enough apparent date coverage and needs code/data review."
    if status == "invalid":
        if not entry_allowed and str(row.get("invalid_reason", "")) == "SKIPPED_ENTRY_OVERHEAT_FILTER":
            return "INVALID_ENTRY_SKIPPED_OVERHEAT", True, False, False, "Legitimate overlay skip, not a data-quality failure."
        if pd.isna(row.get("entry_price")):
            return "INVALID_MISSING_ENTRY_PRICE", False, True, True, "Entry price missing for an entry-allowed row."
        if pd.isna(row.get("exit_price")):
            return "INVALID_MISSING_EXIT_PRICE", False, True, True, "Exit price missing for an entry-allowed invalid row."
        return "INVALID_OTHER_IMPLEMENTATION_WARN", False, True, True, "Invalid row does not match a known policy/data cause."
    return "INVALID_OTHER_IMPLEMENTATION_WARN", False, True, True, "Unexpected maturity status."


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = pd.read_csv(LEDGER)
    dates = load_dates()
    primary = ledger.copy()
    for col, val in PRIMARY.items():
        primary = primary[primary[col].eq(val)]
    rows = []
    pending_calendar = []
    invalid_detail = []
    for _, row in primary.iterrows():
        root, acceptable, blocks, repair, note = classify(row, dates)
        ranking_date = pd.Timestamp(row["ranking_date"])
        expected_execution = next_trading_date(dates, ranking_date, 1)
        expected_exit = next_trading_date(dates, ranking_date, 11)
        detail = row.to_dict()
        detail.update(
            {
                "root_cause": root,
                "expected_or_acceptable": acceptable,
                "blocks_forward_tracking": blocks,
                "requires_code_repair": repair,
                "audit_note": note,
                "expected_execution_date": str(expected_execution.date()) if expected_execution is not None else "",
                "earliest_possible_maturity_date": str(expected_exit.date()) if expected_exit is not None else "",
            }
        )
        rows.append(detail)
        if str(row["maturity_status"]).lower() == "pending":
            pending_calendar.append(detail)
        if str(row["maturity_status"]).lower() == "invalid":
            invalid_detail.append(detail)
    detail_df = pd.DataFrame(rows)
    root = detail_df.groupby("root_cause", dropna=False).agg(
        count=("ticker", "count"),
        affected_tickers=("ticker", lambda s: "|".join(sorted(map(str, s)))),
        affected_ranking_dates=("ranking_date", lambda s: "|".join(sorted(set(map(str, s))))),
        expected_or_acceptable=("expected_or_acceptable", "all"),
        blocks_forward_tracking=("blocks_forward_tracking", "any"),
        requires_code_repair=("requires_code_repair", "any"),
    ).reset_index()
    pending_df = pd.DataFrame(pending_calendar)
    invalid_df = pd.DataFrame(invalid_detail)
    original_top20 = len(primary)
    entry_allowed_count = int(primary["entry_allowed"].astype(bool).sum())
    valid_executable_holdings = int(primary[primary["maturity_status"].eq("matured")].shape[0])
    pending_count = int(primary["maturity_status"].eq("pending").sum())
    invalid_count = int(primary["maturity_status"].eq("invalid").sum())
    legitimate_skip_count = int(detail_df["root_cause"].eq("INVALID_ENTRY_SKIPPED_OVERHEAT").sum())
    true_data_invalid_count = int(detail_df["root_cause"].isin(["INVALID_MISSING_ENTRY_PRICE", "INVALID_MISSING_EXIT_PRICE", "INVALID_MISSING_TICKER_IN_PRICE_PANEL", "INVALID_DATE_ALIGNMENT"]).sum())
    alignment_warning_count = int(detail_df["root_cause"].eq("INVALID_DATE_ALIGNMENT").sum())
    breadth = pd.DataFrame(
        [
            {
                "strategy_name": PRIMARY["strategy_name"],
                "bucket": PRIMARY["bucket"],
                "execution_variant": PRIMARY["execution_variant"],
                "horizon": PRIMARY["horizon"],
                "original_top20_names": original_top20,
                "entry_allowed_names": entry_allowed_count,
                "valid_executable_holdings": valid_executable_holdings,
                "pending_count": pending_count,
                "invalid_count": invalid_count,
                "minimum_effective_top20_threshold": 15,
                "effective_holdings_below_threshold": entry_allowed_count < 15,
                "meaningful_top20_tracking_now": valid_executable_holdings >= 15,
            }
        ]
    )
    policy = pd.DataFrame(
        [
            {
                "issue": "OVERHEAT_FILTER_SKIPS",
                "current_representation": "invalid rows plus skipped rows",
                "recommended_representation": "skipped rows excluded from performance metrics; keep separate from data-invalid rows",
                "cash_zero_return_recommended": False,
                "mutate_v21_151": False,
            },
            {
                "issue": "PENDING_NO_POST_RANKING_PRICE",
                "current_representation": "pending rows",
                "recommended_representation": "pending until T+1 execution and 10D exit prices arrive",
                "cash_zero_return_recommended": False,
                "mutate_v21_151": False,
            },
        ]
    )
    data_or_alignment_warn = true_data_invalid_count > 0 or alignment_warning_count > 0 or root["requires_code_repair"].any()
    low_breadth = entry_allowed_count < 15
    if data_or_alignment_warn:
        final_status = "WARN_V21_151_R1_DATA_OR_ALIGNMENT_REPAIR_REQUIRED"
        decision = "REPAIR_V21_151_LEDGER_BEFORE_CONTINUING"
    elif low_breadth:
        final_status = "PARTIAL_PASS_V21_151_R1_LEGITIMATE_SKIPS_BUT_LOW_BREADTH"
        decision = "KEEP_FORWARD_TRACKING_WITH_LOW_BREADTH_WARN"
    else:
        final_status = "PASS_V21_151_R1_INVALIDS_EXPLAINED_WAIT_MATURITY"
        decision = "KEEP_FORWARD_TRACKING_WAIT_MATURITY"
    root.to_csv(OUT / "invalid_pending_root_cause_audit.csv", index=False)
    pending_df.to_csv(OUT / "primary_candidate_pending_maturity_calendar.csv", index=False)
    invalid_df.to_csv(OUT / "primary_candidate_invalid_detail.csv", index=False)
    breadth.to_csv(OUT / "valid_holdings_breadth_audit.csv", index=False)
    policy.to_csv(OUT / "skipped_vs_invalid_policy_recommendation.csv", index=False)
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|EXEC_OVERHEAT_SKIP|10D",
        f"pending_count={pending_count}",
        f"invalid_count={invalid_count}",
        f"legitimate_skip_count={legitimate_skip_count}",
        f"true_data_invalid_count={true_data_invalid_count}",
        f"alignment_warning_count={alignment_warning_count}",
        f"entry_allowed_names={entry_allowed_count}",
        f"effective_holdings_below_threshold={str(low_breadth).lower()}",
        "matured_observations_zero_expected=true",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.151_R1_INVALID_PENDING_AUDIT_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"pending_count={pending_count}",
        f"invalid_count={invalid_count}",
        f"legitimate_skip_count={legitimate_skip_count}",
        f"true_data_invalid_count={true_data_invalid_count}",
        f"alignment_warning_count={alignment_warning_count}",
        f"entry_allowed_names={entry_allowed_count}",
        f"effective_holdings_below_threshold={str(low_breadth).lower()}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"output directory={str(OUT).replace(chr(92), '/')}",
    ]
    (OUT / "compact_readable_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")
    for line in compact:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
