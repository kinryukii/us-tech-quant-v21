from __future__ import annotations

import csv
import shutil
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"
PASS_STATUS = "PASS_V20_45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"
BLOCKED_STATUS = "BLOCKED_V20_45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"
DECISION_PASS = "PASS_RESEARCH_ONLY_CURRENT_OPERATOR_REPORT_CREATED"
NEXT_STAGE = "V20.45_FORMAL_TESTS"

IN_V43_SECTION = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv"
IN_V43_CANDIDATE = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv"
IN_V43_FACTOR = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv"
IN_V43_ENTRY = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv"
IN_V43_LINEAGE = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv"
IN_V43_NEXT = CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"
IN_V43_REPORT = READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md"
IN_V43_CURRENT = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md"
IN_V43_READ_FIRST = OPS / "V20_43_READ_FIRST.txt"

IN_V44_SUMMARY = CONSOLIDATION / "V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_SUMMARY.csv"
IN_V44_ARTIFACTS = CONSOLIDATION / "V20_44_UPSTREAM_ARTIFACT_VALIDATION.csv"
IN_V44_COUNTS = CONSOLIDATION / "V20_44_DAILY_OPERATOR_REPORT_COUNT_RECHECK.csv"
IN_V44_SAFETY = CONSOLIDATION / "V20_44_DAILY_OPERATOR_REPORT_SAFETY_RECHECK.csv"
IN_V44_DECISION = CONSOLIDATION / "V20_44_CURRENT_RUN_READINESS_DECISION.csv"
IN_V44_REPORT = READ_CENTER / "V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN_REPORT.md"
IN_V44_CURRENT = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE.md"
IN_V44_READ_FIRST = OPS / "V20_44_READ_FIRST.txt"

OUT_SUMMARY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_REPORT_RUN_SUMMARY.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW.csv"
OUT_FACTOR = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv"
OUT_ENTRY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ENTRY_STRATEGY_VIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_LINEAGE_FRESHNESS_VIEW.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ACTION_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY.md"
READ_FIRST = OPS / "V20_45_READ_FIRST.txt"

REQUIRED_INPUTS = [
    IN_V43_SECTION,
    IN_V43_CANDIDATE,
    IN_V43_FACTOR,
    IN_V43_ENTRY,
    IN_V43_LINEAGE,
    IN_V43_NEXT,
    IN_V43_REPORT,
    IN_V43_CURRENT,
    IN_V43_READ_FIRST,
    IN_V44_SUMMARY,
    IN_V44_ARTIFACTS,
    IN_V44_COUNTS,
    IN_V44_SAFETY,
    IN_V44_DECISION,
    IN_V44_REPORT,
    IN_V44_CURRENT,
    IN_V44_READ_FIRST,
]

EXPECTED_COUNTS = {
    "candidate": 50,
    "factor": 21,
    "entry": 5,
    "lineage": 27,
}


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def read_flags(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[key.strip()] = value.strip()
    return flags


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(clean(value)[:10])
    except ValueError:
        return None


def source_snapshot_status(candidate_rows: list[dict[str, str]]) -> tuple[str, bool, int, str]:
    dates = [parse_iso_date(row.get("signal_date", "")) for row in candidate_rows]
    valid_dates = [item for item in dates if item is not None]
    if not valid_dates:
        return "UNKNOWN_SOURCE_DATE_WARNING", True, 1, "No candidate signal dates were available for currentness confirmation."
    newest = max(valid_dates)
    if newest == date.today():
        return "CURRENT_LOCAL_SNAPSHOT", False, 0, f"Newest candidate signal date is {newest.isoformat()}."
    return "STALE_LOCAL_SNAPSHOT_WARNING", True, 1, f"Newest candidate signal date is {newest.isoformat()}; market refresh required before operational use."


def build_candidate_view(rows: list[dict[str, str]], freshness: str) -> list[dict[str, object]]:
    out = []
    for idx, row in enumerate(rows, start=1):
        ticker = clean(row.get("ticker"))
        rank_or_score = clean(row.get("research_rank")) or clean(row.get("technical_score"))
        out.append({
            "report_rank": idx,
            "ticker_or_candidate_id": ticker,
            "display_name_or_ticker": ticker,
            "source_rank_or_score": rank_or_score,
            "research_category": clean(row.get("top_bucket")) or "candidate_research",
            "report_section": "candidate_research_view",
            "source_contract": rel(IN_V43_CANDIDATE),
            "source_lineage": clean(row.get("candidate_source_stage")) or "V20.43 candidate research table",
            "freshness_status": freshness,
            "operator_research_note": "Candidate for review; not an official recommendation.",
            "research_only_flag": "TRUE",
            "official_recommendation_flag": "FALSE",
        })
    return out


def build_factor_view(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        out.append({
            "factor_id_or_name": clean(row.get("factor_name")),
            "factor_category": clean(row.get("factor_category")),
            "pit_status": clean(row.get("pit_backtest_eligible_now")),
            "support_status": clean(row.get("stability_or_coverage_status")),
            "report_section": "factor_support_summary",
            "factor_research_interpretation": "Factor support evidence available for research review.",
            "included_in_official_weight_flag": "FALSE",
            "dynamic_weighting_mutated": "FALSE",
            "research_only_flag": "TRUE",
        })
    return out


def build_entry_view(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        family = clean(row.get("strategy_family"))
        out.append({
            "strategy_id_or_name": family,
            "strategy_family": family,
            "readiness_status": "RESEARCH_VIEW_READY",
            "report_section": "entry_strategy_readiness",
            "entry_strategy_interpretation": "Entry setup under research; not trading-authorized.",
            "allowed_in_research_report": "TRUE",
            "allowed_for_live_trading": "FALSE",
            "broker_execution_enabled": "FALSE",
            "research_only_flag": "TRUE",
        })
    return out


def build_lineage_view(rows: list[dict[str, str]], refresh_needed: bool) -> list[dict[str, object]]:
    out = []
    for row in rows:
        source_exists = upper(row.get("source_exists")) == "TRUE"
        blocker_count = 0 if source_exists else 1
        warning_count = 1 if refresh_needed else 0
        out.append({
            "source_name_or_input_name": clean(row.get("lineage_item")),
            "source_contract_or_version": clean(row.get("source_file")),
            "freshness_status": clean(row.get("freshness_status")),
            "lineage_status": clean(row.get("leakage_or_formula_status")),
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "current_market_refresh_needed": "TRUE" if refresh_needed else "CONDITIONAL",
            "safe_for_research_report": tf(blocker_count == 0),
            "safe_for_official_recommendation": "FALSE",
            "safe_for_trading": "FALSE",
        })
    return out


def boundary_rows() -> list[dict[str, object]]:
    specs = [
        ("research_report_generation_allowed", "TRUE", "V20.44 accepted V20.43 dry-run with research-only limits."),
        ("candidate_review_allowed", "TRUE", "Candidate view is copied from accepted local V20.43 rows."),
        ("factor_review_allowed", "TRUE", "Factor support view is copied from accepted local V20.43 rows."),
        ("entry_strategy_review_allowed", "TRUE", "Entry setup review is allowed inside the research-only report."),
        ("official_buy_sell_hold_recommendation_allowed", "FALSE", "No official recommendation packet is created."),
        ("live_trading_allowed", "FALSE", "This stage is not trading-authorized."),
        ("broker_order_execution_allowed", "FALSE", "No broker or order path is used."),
        ("official_ranking_mutation_allowed", "FALSE", "Source rank fields are displayed only; no ranking is recomputed or mutated."),
        ("dynamic_weighting_mutation_allowed", "FALSE", "No dynamic weight state is changed."),
        ("provider_network_refresh_allowed_in_this_stage", "FALSE", "This stage uses accepted local V20 artifacts only."),
        ("real_portfolio_mutation_allowed", "FALSE", "No portfolio state is changed."),
    ]
    return [
        {
            "boundary_name": name,
            "allowed_flag": allowed,
            "evidence": evidence,
            "blocker_reason": "" if allowed == "TRUE" else "blocked_by_research_only_boundary",
        }
        for name, allowed, evidence in specs
    ]


def md_table(rows: list[dict[str, object]], columns: list[str], limit: int = 12) -> str:
    if not rows:
        return "_No rows available._\n"
    text = "| " + " | ".join(columns) + " |\n"
    text += "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows[:limit]:
        text += "| " + " | ".join(clean(row.get(col)).replace("|", "/") for col in columns) + " |\n"
    if len(rows) > limit:
        text += f"\n_Showing {limit} of {len(rows)} rows._\n"
    return text


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    blockers: list[str] = []
    warnings: list[str] = []

    missing_or_empty = [rel(path) for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing_or_empty:
        blockers.append("missing_or_empty_required_inputs=" + ";".join(missing_or_empty))

    candidate_rows, _ = read_csv(IN_V43_CANDIDATE)
    factor_rows, _ = read_csv(IN_V43_FACTOR)
    entry_rows, _ = read_csv(IN_V43_ENTRY)
    lineage_rows, _ = read_csv(IN_V43_LINEAGE)

    v43_next = first_row(IN_V43_NEXT)
    v44_summary = first_row(IN_V44_SUMMARY)
    v44_decision = first_row(IN_V44_DECISION)

    if clean(v44_summary.get("acceptance_status")) != "ACCEPTED_WITH_RESEARCH_ONLY_LIMITS":
        blockers.append("v20_44_acceptance_status_not_accepted")
    if clean(v44_summary.get("ready_for_current_run_report")) != "TRUE":
        blockers.append("v20_44_not_ready_for_current_run_report")
    if clean(v44_decision.get("provider_refresh_allowed_in_this_stage")) != "FALSE":
        blockers.append("v20_44_provider_refresh_boundary_not_false")

    actual_counts = {
        "candidate": len(candidate_rows),
        "factor": len(factor_rows),
        "entry": len(entry_rows),
        "lineage": len(lineage_rows),
    }
    for name, expected in EXPECTED_COUNTS.items():
        if actual_counts[name] == 0:
            blockers.append(f"{name}_rows_missing")
        elif actual_counts[name] != expected:
            if clean(v44_summary.get("expected_counts_validated")) == "TRUE":
                warnings.append(f"{name}_row_count_differs_from_v20_45_expected_but_v20_44_accepted")
            else:
                blockers.append(f"{name}_row_count_mismatch")

    freshness_status, refresh_needed, freshness_warning_count, freshness_note = source_snapshot_status(candidate_rows)
    if freshness_warning_count:
        warnings.append(freshness_status)

    safety_ok = (
        clean(v43_next.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION")) == "FALSE"
        and clean(v43_next.get("OFFICIAL_RECOMMENDATION_CREATED")) == "FALSE"
        and clean(v43_next.get("BROKER_ORDER_PATH_CREATED")) == "FALSE"
        and clean(v43_next.get("PROVIDER_REFRESH_EXECUTED")) == "FALSE"
        and clean(v44_summary.get("ready_for_official_trading")) == "FALSE"
        and clean(v44_summary.get("ready_for_official_recommendation")) == "FALSE"
        and clean(v44_summary.get("ready_for_dynamic_weighting_mutation")) == "FALSE"
    )
    if not safety_ok:
        blockers.append("upstream_safety_boundary_not_valid")

    candidate_view = build_candidate_view(candidate_rows, freshness_status)
    factor_view = build_factor_view(factor_rows)
    entry_view = build_entry_view(entry_rows)
    lineage_view = build_lineage_view(lineage_rows, refresh_needed)
    boundaries = boundary_rows()

    blocked = bool(blockers)
    report_status = "BLOCKED" if blocked else "PASS"
    decision = "BLOCKED_CURRENT_OPERATOR_REPORT_NOT_CREATED" if blocked else DECISION_PASS
    final_status = BLOCKED_STATUS if blocked else PASS_STATUS
    blocker_count = len(blockers)
    warning_count = len(warnings)

    summary = [{
        "stage": STAGE,
        "upstream_v20_43_status": clean(v43_next.get("STATUS")),
        "upstream_v20_44_status": clean(v44_summary.get("acceptance_status")),
        "report_generation_status": report_status,
        "research_only_status": "TRUE",
        "source_snapshot_status": freshness_status,
        "current_market_refresh_needed_before_real_use": tf(refresh_needed),
        "candidate_rows_included": len(candidate_view),
        "factor_support_rows_included": len(factor_view),
        "entry_strategy_rows_included": len(entry_view),
        "lineage_freshness_rows_included": len(lineage_view),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "official_trading_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "provider_network_refresh_used": "FALSE",
        "broker_order_execution_used": "FALSE",
        "next_recommended_stage": NEXT_STAGE if not blocked else "REPAIR_V20_45_INPUTS",
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "report_created": tf(not blocked),
        "research_only_report_ready": tf(not blocked),
        "current_market_refresh_needed_before_real_use": tf(refresh_needed),
        "formal_tests_required_next": tf(not blocked),
        "provider_refresh_stage_required": tf(refresh_needed),
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "next_recommended_stage": NEXT_STAGE if not blocked else "REPAIR_V20_45_INPUTS",
    }]

    write_csv(OUT_CANDIDATE, candidate_view, [
        "report_rank", "ticker_or_candidate_id", "display_name_or_ticker", "source_rank_or_score",
        "research_category", "report_section", "source_contract", "source_lineage", "freshness_status",
        "operator_research_note", "research_only_flag", "official_recommendation_flag",
    ])
    write_csv(OUT_FACTOR, factor_view, [
        "factor_id_or_name", "factor_category", "pit_status", "support_status", "report_section",
        "factor_research_interpretation", "included_in_official_weight_flag", "dynamic_weighting_mutated",
        "research_only_flag",
    ])
    write_csv(OUT_ENTRY, entry_view, [
        "strategy_id_or_name", "strategy_family", "readiness_status", "report_section",
        "entry_strategy_interpretation", "allowed_in_research_report", "allowed_for_live_trading",
        "broker_execution_enabled", "research_only_flag",
    ])
    write_csv(OUT_LINEAGE, lineage_view, [
        "source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status",
        "blocker_count", "warning_count", "current_market_refresh_needed", "safe_for_research_report",
        "safe_for_official_recommendation", "safe_for_trading",
    ])
    write_csv(OUT_BOUNDARY, boundaries, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.45 Current Operator Report Research-Only Run

## Stage Status

Stage: {STAGE}
Status: {final_status}
Report generation status: {report_status}
Research-only status: TRUE

## Upstream Acceptance Status

V20.43 status: {clean(v43_next.get("STATUS"))}
V20.44 acceptance status: {clean(v44_summary.get("acceptance_status"))}
V20.44 current-run readiness: {clean(v44_summary.get("ready_for_current_run_report"))}

## Current Report Scope

This report is generated from the latest accepted local V20 artifacts. It is not a live market refresh, not broker-connected, and not an official recommendation packet.
It performs no provider/network refresh in this stage.

## Candidate Research View Summary

Rows included: {len(candidate_view)}

{md_table(candidate_view, ["report_rank", "ticker_or_candidate_id", "source_rank_or_score", "freshness_status", "operator_research_note"], 15)}

## Factor Support Summary

Rows included: {len(factor_view)}

{md_table(factor_view, ["factor_id_or_name", "factor_category", "pit_status", "support_status"], 12)}

## Entry Strategy Readiness Summary

Rows included: {len(entry_view)}

{md_table(entry_view, ["strategy_id_or_name", "readiness_status", "allowed_in_research_report", "allowed_for_live_trading"], 10)}

## Lineage And Freshness Summary

Rows included: {len(lineage_view)}
Source snapshot status: {freshness_status}
Freshness note: {freshness_note}

{md_table(lineage_view, ["source_name_or_input_name", "freshness_status", "warning_count", "current_market_refresh_needed"], 12)}

## Action Boundary

{md_table(boundaries, ["boundary_name", "allowed_flag", "evidence"], 12)}

## Explicit Non-Trading Statement

This report is not trading-authorized. It does not create trading signals, order instructions, broker paths, or portfolio state changes.

## Explicit Non-Official-Recommendation Statement

Rows are candidates for review and supporting research context only. They are not official recommendations.

## Current Market Refresh Needed Before Real Use

current_market_refresh_needed_before_real_use={tf(refresh_needed)}

## Blockers And Warnings

Blockers: {blocker_text}
Warnings: {warning_text}

## Next Recommended Stage

{NEXT_STAGE if not blocked else "REPAIR_V20_45_INPUTS"}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"DECISION={decision}",
        "REPORT_GENERATION_ONLY=TRUE",
        "RESEARCH_ONLY_STATUS=TRUE",
        f"UPSTREAM_V20_44_ACCEPTED={tf(clean(v44_summary.get('acceptance_status')) == 'ACCEPTED_WITH_RESEARCH_ONLY_LIMITS')}",
        f"CURRENT_MARKET_REFRESH_NEEDED_BEFORE_REAL_USE={tf(refresh_needed)}",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "PROVIDER_NETWORK_REFRESH_USED=FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_TRADING_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "REAL_PORTFOLIO_MUTATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "V21_OUTPUTS_CREATED=FALSE",
        "V19_21_OUTPUTS_CREATED=FALSE",
        f"CANDIDATE_ROWS_INCLUDED={len(candidate_view)}",
        f"FACTOR_SUPPORT_ROWS_INCLUDED={len(factor_view)}",
        f"ENTRY_STRATEGY_ROWS_INCLUDED={len(entry_view)}",
        f"LINEAGE_FRESHNESS_ROWS_INCLUDED={len(lineage_view)}",
        f"BLOCKER_COUNT={blocker_count}",
        f"WARNING_COUNT={warning_count}",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if not blocked else 'REPAIR_V20_45_INPUTS'}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    cleanup_pycache()

    print(final_status)
    print(f"DECISION={decision}")
    print(f"CANDIDATE_ROWS_INCLUDED={len(candidate_view)}")
    print(f"FACTOR_SUPPORT_ROWS_INCLUDED={len(factor_view)}")
    print(f"ENTRY_STRATEGY_ROWS_INCLUDED={len(entry_view)}")
    print(f"LINEAGE_FRESHNESS_ROWS_INCLUDED={len(lineage_view)}")
    print(f"CURRENT_MARKET_REFRESH_NEEDED_BEFORE_REAL_USE={tf(refresh_needed)}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if not blocked else 'REPAIR_V20_45_INPUTS'}")
    return 0 if not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
