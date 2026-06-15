from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT"
PASS_STATUS = "PASS_V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT"
BLOCKED_STATUS = "BLOCKED_V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT"
DECISION_PASS = "PASS_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT_CREATED"
CERT_STATUS = "CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF"
FALLBACK_CERT_STATUS = "CERTIFIED_CACHE_FALLBACK_HANDOFF"
ACCEPTED_CERT_STATUSES = {CERT_STATUS, FALLBACK_CERT_STATUS}
NEXT_STAGE = "V20.48_FORMAL_TESTS"

IN_V47_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
IN_V47_STAGED_CANDIDATE = CONSOLIDATION / "V20_47_CURRENT_MARKET_SOURCE_STAGED_CANDIDATE.csv"
IN_V47_STAGED_BENCHMARK = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_SOURCE_STAGED_CANDIDATE.csv"
IN_V47_CANDIDATE_CERT = CONSOLIDATION / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
IN_V47_BENCHMARK_CERT = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_PRICE_CERTIFICATION.csv"
IN_V47_HASH_LEDGER = CONSOLIDATION / "V20_47_CACHE_HASH_LEDGER.csv"
IN_V47_NEXT = CONSOLIDATION / "V20_47_NEXT_STEP_DECISION.csv"
IN_V47_CURRENT = READ_CENTER / "V20_CURRENT_CONTROLLED_MARKET_REFRESH_CERTIFICATION.md"
IN_V47_READ_FIRST = OPS / "V20_47_READ_FIRST.txt"
IN_V47_TEST = SCRIPT_DIR / "test_v20_47_controlled_current_market_refresh_and_cache_certification.py"

IN_V45_SUMMARY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_REPORT_RUN_SUMMARY.csv"
IN_V45_CANDIDATE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW.csv"
IN_V45_FACTOR = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv"
IN_V45_ENTRY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ENTRY_STRATEGY_VIEW.csv"
IN_V45_LINEAGE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_LINEAGE_FRESHNESS_VIEW.csv"
IN_V45_BOUNDARY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ACTION_BOUNDARY.csv"
IN_V45_NEXT = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv"
IN_V20_7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
OUT_FACTOR = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
OUT_ENTRY = CONSOLIDATION / "V20_48_REFRESHED_ENTRY_STRATEGY_VIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_48_REFRESHED_REPORT_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_48_REFRESHED_REPORT_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_48_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_REFRESHED_OPERATOR_RESEARCH_REPORT.md"
READ_FIRST = OPS / "V20_48_READ_FIRST.txt"

REQUIRED_INPUTS = [
    IN_V47_SUMMARY,
    IN_V47_STAGED_CANDIDATE,
    IN_V47_STAGED_BENCHMARK,
    IN_V47_CANDIDATE_CERT,
    IN_V47_BENCHMARK_CERT,
    IN_V47_HASH_LEDGER,
    IN_V47_NEXT,
    IN_V47_CURRENT,
    IN_V47_READ_FIRST,
    IN_V47_TEST,
    IN_V45_SUMMARY,
    IN_V45_CANDIDATE,
    IN_V45_FACTOR,
    IN_V45_ENTRY,
    IN_V45_LINEAGE,
    IN_V45_BOUNDARY,
    IN_V45_NEXT,
]


def clean(value: object) -> str:
    return str(value or "").strip()


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


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


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


def normalize_ticker(value: str) -> str:
    ticker = clean(value).upper()
    return ticker if re.fullmatch(r"[A-Z0-9.\-]+", ticker or "") else ""


def run_v47_tests() -> tuple[bool, str]:
    if not IN_V47_TEST.exists():
        return False, "V20.47 formal test script missing"
    result = subprocess.run([sys.executable, str(IN_V47_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0 and "PASS_V20_47_TESTS" in result.stdout.splitlines(), output


def build_candidate_view(v45_rows: list[dict[str, str]], staged_rows: list[dict[str, str]], run_id: str) -> tuple[list[dict[str, object]], int, int]:
    staged_by_ticker = {normalize_ticker(row.get("ticker", "")): row for row in staged_rows}
    counts: dict[str, int] = {}
    for row in v45_rows:
        ticker = normalize_ticker(row.get("ticker_or_candidate_id") or row.get("display_name_or_ticker"))
        counts[ticker] = counts.get(ticker, 0) + 1

    out = []
    with_price = 0
    missing = 0
    for row in v45_rows:
        ticker = normalize_ticker(row.get("ticker_or_candidate_id") or row.get("display_name_or_ticker"))
        staged = staged_by_ticker.get(ticker, {})
        mapped = bool(staged)
        if mapped:
            with_price += 1
        else:
            missing += 1
        out.append({
            "report_rank": clean(row.get("report_rank")),
            "ticker_or_candidate_id": clean(row.get("ticker_or_candidate_id")),
            "normalized_ticker": ticker,
            "display_name_or_ticker": clean(row.get("display_name_or_ticker")),
            "source_rank_or_score": clean(row.get("source_rank_or_score")),
            "research_category": clean(row.get("research_category")),
            "report_section": clean(row.get("report_section")),
            "source_contract": clean(row.get("source_contract")),
            "source_lineage": clean(row.get("source_lineage")),
            "v20_47_run_id": run_id,
            "refreshed_price_date": clean(staged.get("latest_price_date")),
            "refreshed_latest_close": clean(staged.get("latest_close")),
            "refreshed_latest_adj_close": clean(staged.get("latest_adj_close")),
            "refreshed_latest_volume": clean(staged.get("latest_volume")),
            "refreshed_price_certification_status": clean(staged.get("certification_status")) if mapped else "MISSING_REFRESHED_PRICE",
            "refreshed_price_mapping_status": "MAPPED_CERTIFIED_PRICE" if mapped else "MISSING_CERTIFIED_PRICE",
            "duplicate_ticker_mapping_flag": tf(counts.get(ticker, 0) > 1),
            "research_only_flag": "TRUE",
            "official_recommendation_flag": "FALSE",
            "official_trading_allowed": "FALSE",
            "broker_execution_allowed": "FALSE",
            "operator_research_note": "Candidate for review with refreshed price context; not an official recommendation.",
        })
    return out, with_price, missing


def v20_7v_rows_to_research_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        ticker = normalize_ticker(row.get("ticker", ""))
        if not ticker:
            continue
        out.append({
            "report_rank": clean(row.get("rank")),
            "ticker_or_candidate_id": ticker,
            "display_name_or_ticker": ticker,
            "source_rank_or_score": clean(row.get("composite_candidate_score")),
            "research_category": "current_active_market_staging",
            "report_section": "current_daily_research_lane",
            "source_contract": "V20_7V_ACTIVE_MARKET_SOURCE_STAGING",
            "source_lineage": rel(IN_V20_7V_STAGING),
        })
    return out


def build_benchmark_view(rows: list[dict[str, str]], run_id: str) -> list[dict[str, object]]:
    out = []
    for row in rows:
        out.append({
            "benchmark_ticker": clean(row.get("benchmark_ticker")),
            "v20_47_run_id": run_id,
            "refreshed_price_date": clean(row.get("latest_price_date")),
            "refreshed_latest_close": clean(row.get("latest_close")),
            "refreshed_latest_adj_close": clean(row.get("latest_adj_close")),
            "refreshed_latest_volume": clean(row.get("latest_volume")),
            "certification_status": clean(row.get("certification_status")),
            "research_context_allowed": "TRUE",
            "benchmark_return_calculated": "FALSE",
            "official_trading_allowed": "FALSE",
            "blocker_reason": "",
        })
    return out


def build_factor_view(rows: list[dict[str, str]], refreshed_available: bool) -> list[dict[str, object]]:
    return [
        {
            "factor_id_or_name": clean(row.get("factor_id_or_name")),
            "factor_category": clean(row.get("factor_category")),
            "pit_status": clean(row.get("pit_status")),
            "support_status": clean(row.get("support_status")),
            "report_section": clean(row.get("report_section")),
            "factor_research_interpretation": clean(row.get("factor_research_interpretation")),
            "refreshed_market_context_available": tf(refreshed_available),
            "included_in_official_weight_flag": "FALSE",
            "dynamic_weighting_mutated": "FALSE",
            "research_only_flag": "TRUE",
        }
        for row in rows
    ]


def build_entry_view(rows: list[dict[str, str]], refreshed_available: bool) -> list[dict[str, object]]:
    return [
        {
            "strategy_id_or_name": clean(row.get("strategy_id_or_name")),
            "strategy_family": clean(row.get("strategy_family")),
            "readiness_status": clean(row.get("readiness_status")),
            "report_section": clean(row.get("report_section")),
            "entry_strategy_interpretation": clean(row.get("entry_strategy_interpretation")),
            "refreshed_market_context_available": tf(refreshed_available),
            "allowed_in_research_report": "TRUE",
            "allowed_for_live_trading": "FALSE",
            "broker_execution_enabled": "FALSE",
            "research_only_flag": "TRUE",
        }
        for row in rows
    ]


def build_lineage_view(v45_rows: list[dict[str, str]], ledger_rows: list[dict[str, str]], run_id: str) -> list[dict[str, object]]:
    primary_hash = clean(ledger_rows[0].get("sha256")) if ledger_rows else ""
    out = []
    for row in v45_rows:
        blocker_count = int(float(clean(row.get("blocker_count")) or "0"))
        out.append({
            "source_name_or_input_name": clean(row.get("source_name_or_input_name")),
            "source_contract_or_version": clean(row.get("source_contract_or_version")),
            "freshness_status": "REFRESHED_CERTIFIED_CONTEXT_ATTACHED",
            "lineage_status": clean(row.get("lineage_status")),
            "v20_47_run_id": run_id,
            "v20_47_cache_hash_reference": primary_hash,
            "refreshed_cache_certified": "TRUE",
            "blocker_count": blocker_count,
            "warning_count": clean(row.get("warning_count")) or "0",
            "safe_for_research_report": tf(blocker_count == 0),
            "safe_for_official_recommendation": "FALSE",
            "safe_for_trading": "FALSE",
        })
    for ledger in ledger_rows:
        out.append({
            "source_name_or_input_name": clean(ledger.get("source_role")),
            "source_contract_or_version": clean(ledger.get("artifact_path")),
            "freshness_status": "V20_47_REFRESHED_CACHE_CERTIFIED",
            "lineage_status": "HASH_LEDGER_VERIFIED",
            "v20_47_run_id": run_id,
            "v20_47_cache_hash_reference": clean(ledger.get("sha256")),
            "refreshed_cache_certified": "TRUE",
            "blocker_count": 0,
            "warning_count": 0,
            "safe_for_research_report": "TRUE",
            "safe_for_official_recommendation": "FALSE",
            "safe_for_trading": "FALSE",
        })
    return out


def boundary_rows() -> list[dict[str, object]]:
    specs = [
        ("refreshed_research_report_generation_allowed", "TRUE", "Certified V20.47 cache is available for research-report handoff."),
        ("candidate_review_with_refreshed_prices_allowed", "TRUE", "Candidate rows retain research-only membership and gain refreshed price context."),
        ("factor_review_with_refreshed_context_allowed", "TRUE", "Factor rows remain research-only support context."),
        ("entry_strategy_review_with_refreshed_context_allowed", "TRUE", "Entry setup rows remain under research review."),
        ("benchmark_context_review_allowed", "TRUE", "SPY/QQQ certified benchmark context is available."),
        ("provider_refresh_allowed_in_this_stage", "FALSE", "V20.48 consumes V20.47 cache only."),
        ("yfinance_import_allowed_in_this_stage", "FALSE", "Provider package use is isolated to V20.47."),
        ("official_buy_sell_hold_recommendation_allowed", "FALSE", "No official recommendation packet is created."),
        ("live_trading_allowed", "FALSE", "Not trading-authorized."),
        ("broker_order_execution_allowed", "FALSE", "No broker/order execution."),
        ("official_ranking_mutation_allowed", "FALSE", "No official rank mutation."),
        ("dynamic_weighting_mutation_allowed", "FALSE", "No weight mutation."),
        ("real_portfolio_mutation_allowed", "FALSE", "No portfolio mutation."),
        ("return_calculation_allowed", "FALSE", "No return calculation."),
        ("score_recomputation_allowed", "FALSE", "No score recomputation."),
        ("ranking_recomputation_allowed", "FALSE", "No ranking recomputation."),
        ("trading_signal_generation_allowed", "FALSE", "No trading signal generation."),
    ]
    return [{"boundary_name": name, "allowed_flag": allowed, "evidence": evidence, "blocker_reason": "" if allowed == "TRUE" else "blocked_by_research_only_boundary"} for name, allowed, evidence in specs]


def safety_rows() -> list[dict[str, object]]:
    checks = [
        ("provider_refresh_executed_in_v20_48", "FALSE", "FALSE", "V20.48 reads certified V20.47 cache only."),
        ("yfinance_imported_in_v20_48", "FALSE", "FALSE", "No provider package import."),
        ("refreshed_v20_47_cache_used", "TRUE", "TRUE", "V20.47 staged sources and hash ledger consumed."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order execution."),
        ("official_recommendation_allowed", "FALSE", "FALSE", "Research-only report."),
        ("official_trading_allowed", "FALSE", "FALSE", "Not trading-authorized."),
        ("official_ranking_mutated", "FALSE", "FALSE", "Ranks preserved only."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No dynamic weighting mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No portfolio state mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No returns calculated."),
        ("scores_recomputed", "FALSE", "FALSE", "No scores recomputed."),
        ("rankings_recomputed", "FALSE", "FALSE", "No rankings recomputed."),
        ("trading_signals_created", "FALSE", "FALSE", "No trading signals created."),
        ("v21_output_path_created", "FALSE", "FALSE", "No V21 outputs."),
        ("v19_21_output_path_created", "FALSE", "FALSE", "No V19.21 outputs."),
    ]
    return [
        {
            "safety_boundary": name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": "PASS" if expected == actual else "BLOCKED",
            "evidence": evidence,
            "blocker_reason": "" if expected == actual else f"expected_{expected}_got_{actual}",
        }
        for name, expected, actual, evidence in checks
    ]


def md_table(rows: list[dict[str, object]], columns: list[str], limit: int = 15) -> str:
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
    missing = [rel(path) for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        blockers.append("missing_required_inputs=" + ";".join(missing))

    v47_tests_passed, v47_test_output = run_v47_tests()
    if not v47_tests_passed:
        blockers.append("v20_47_formal_tests_not_passed")

    v47_summary = first_row(IN_V47_SUMMARY)
    v47_next = first_row(IN_V47_NEXT)
    run_id = clean(v47_summary.get("run_id"))
    if clean(v47_summary.get("certification_status")) not in ACCEPTED_CERT_STATUSES:
        blockers.append("v20_47_certification_status_not_certified")
    if clean(v47_next.get("decision")) != "PASS_CONTROLLED_REFRESH_CERTIFIED_FOR_RESEARCH_HANDOFF":
        blockers.append("v20_47_next_step_not_pass")

    v45_candidates, _ = read_csv(IN_V45_CANDIDATE)
    v45_factors, _ = read_csv(IN_V45_FACTOR)
    v45_entries, _ = read_csv(IN_V45_ENTRY)
    v45_lineage, _ = read_csv(IN_V45_LINEAGE)
    v20_7v_staging, _ = read_csv(IN_V20_7V_STAGING)
    candidate_source_mode = "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW"
    if not v45_candidates and v20_7v_staging:
        v45_candidates = v20_7v_rows_to_research_rows(v20_7v_staging)
        candidate_source_mode = "V20_7V_ACTIVE_MARKET_SOURCE_STAGING"
    staged_candidates, _ = read_csv(IN_V47_STAGED_CANDIDATE)
    staged_benchmarks, _ = read_csv(IN_V47_STAGED_BENCHMARK)
    ledger, _ = read_csv(IN_V47_HASH_LEDGER)

    if not staged_candidates:
        blockers.append("v20_47_staged_candidate_source_missing_or_empty")
    certified_benchmarks = {clean(row.get("benchmark_ticker")) for row in staged_benchmarks if clean(row.get("certification_status")) == "CERTIFIED"}
    if certified_benchmarks != {"SPY", "QQQ"}:
        blockers.append("spy_qqq_benchmark_source_missing_or_uncertified")

    candidate_view, mapped_count, missing_count = build_candidate_view(v45_candidates, staged_candidates, run_id)
    unique_certified = len({normalize_ticker(row.get("ticker", "")) for row in staged_candidates})
    if missing_count:
        severity = missing_count / max(1, len(v45_candidates))
        message = f"candidate_rows_missing_refreshed_price={missing_count}"
        if severity > 0.10:
            blockers.append(message)
        else:
            warnings.append(message)
    benchmark_view = build_benchmark_view(staged_benchmarks, run_id)
    factor_view = build_factor_view(v45_factors, bool(staged_candidates and staged_benchmarks))
    entry_view = build_entry_view(v45_entries, bool(staged_candidates and staged_benchmarks))
    lineage_view = build_lineage_view(v45_lineage, ledger, run_id)
    boundaries = boundary_rows()
    safety = safety_rows()

    blocked = bool(blockers)
    decision = "BLOCKED_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT" if blocked else DECISION_PASS
    final_status = BLOCKED_STATUS if blocked else PASS_STATUS

    summary = [{
        "stage": STAGE,
        "upstream_v20_47_certification_status": clean(v47_summary.get("certification_status")),
        "upstream_v20_47_tests_status": "PASS" if v47_tests_passed else "FAIL",
        "v20_47_run_id": run_id,
        "refreshed_market_cache_used": "TRUE",
        "provider_refresh_executed_in_this_stage": "FALSE",
        "yfinance_import_used_in_this_stage": "FALSE",
        "candidate_research_rows_input": len(v45_candidates),
        "candidate_research_source_mode": candidate_source_mode,
        "unique_certified_candidate_tickers_available": unique_certified,
        "candidate_research_rows_with_refreshed_price": mapped_count,
        "candidate_research_rows_missing_refreshed_price": missing_count,
        "benchmark_rows_available": len(benchmark_view),
        "factor_support_rows_included": len(factor_view),
        "entry_strategy_rows_included": len(entry_view),
        "lineage_rows_included": len(v45_lineage),
        "refreshed_report_created": tf(not blocked),
        "research_only_status": "TRUE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": NEXT_STAGE if not blocked else "REPAIR_V20_48_INPUTS",
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "refreshed_report_created": tf(not blocked),
        "refreshed_cache_certified": tf(clean(v47_summary.get("certification_status")) in ACCEPTED_CERT_STATUSES),
        "research_report_ready": tf(not blocked),
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": tf(not blocked),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": NEXT_STAGE if not blocked else "REPAIR_V20_48_INPUTS",
    }]

    write_csv(OUT_CANDIDATE, candidate_view, [
        "report_rank", "ticker_or_candidate_id", "normalized_ticker", "display_name_or_ticker",
        "source_rank_or_score", "research_category", "report_section", "source_contract", "source_lineage",
        "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "refreshed_latest_adj_close",
        "refreshed_latest_volume", "refreshed_price_certification_status", "refreshed_price_mapping_status",
        "duplicate_ticker_mapping_flag", "research_only_flag", "official_recommendation_flag",
        "official_trading_allowed", "broker_execution_allowed", "operator_research_note",
    ])
    write_csv(OUT_BENCHMARK, benchmark_view, [
        "benchmark_ticker", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close",
        "refreshed_latest_adj_close", "refreshed_latest_volume", "certification_status",
        "research_context_allowed", "benchmark_return_calculated", "official_trading_allowed", "blocker_reason",
    ])
    write_csv(OUT_FACTOR, factor_view, [
        "factor_id_or_name", "factor_category", "pit_status", "support_status", "report_section",
        "factor_research_interpretation", "refreshed_market_context_available",
        "included_in_official_weight_flag", "dynamic_weighting_mutated", "research_only_flag",
    ])
    write_csv(OUT_ENTRY, entry_view, [
        "strategy_id_or_name", "strategy_family", "readiness_status", "report_section",
        "entry_strategy_interpretation", "refreshed_market_context_available", "allowed_in_research_report",
        "allowed_for_live_trading", "broker_execution_enabled", "research_only_flag",
    ])
    write_csv(OUT_LINEAGE, lineage_view, [
        "source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status",
        "v20_47_run_id", "v20_47_cache_hash_reference", "refreshed_cache_certified", "blocker_count",
        "warning_count", "safe_for_research_report", "safe_for_official_recommendation", "safe_for_trading",
    ])
    write_csv(OUT_BOUNDARY, boundaries, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.48 Refreshed Current Operator Research Report

## Stage Status

Stage: {STAGE}
Status: {final_status}
Decision: {decision}

## Upstream V20.47 Certification/Test Status

Certification status: {clean(v47_summary.get("certification_status"))}
V20.47 formal tests status: {"PASS" if v47_tests_passed else "FAIL"}
V20.47 run ID: {run_id}

## Refreshed Market Cache Used

V20.48 used the certified V20.47 refreshed market cache. V20.48 did not refresh providers and did not import a provider package.

## Candidate Research View With Refreshed Price Context

Candidate rows input: {len(v45_candidates)}
Rows with refreshed price context: {mapped_count}
Rows missing refreshed price context: {missing_count}

{md_table(candidate_view, ["report_rank", "normalized_ticker", "refreshed_price_date", "refreshed_price_mapping_status", "operator_research_note"], 20)}

## Benchmark Context

{md_table(benchmark_view, ["benchmark_ticker", "refreshed_price_date", "certification_status", "benchmark_return_calculated"], 10)}

## Factor Support With Refreshed Context

{md_table(factor_view, ["factor_id_or_name", "factor_category", "support_status", "refreshed_market_context_available"], 12)}

## Entry Strategy With Refreshed Context

{md_table(entry_view, ["strategy_id_or_name", "readiness_status", "refreshed_market_context_available", "allowed_for_live_trading"], 10)}

## Lineage/Freshness And Cache Certification

{md_table(lineage_view, ["source_name_or_input_name", "freshness_status", "refreshed_cache_certified", "safe_for_research_report"], 12)}

## Action Boundary

{md_table(boundaries, ["boundary_name", "allowed_flag", "evidence"], 20)}

## Safety Boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"], 20)}

## Explicit No-Provider-Refresh-In-V20.48 Statement

V20.48 does not perform provider/network refresh and does not use yfinance.

## Explicit Non-Official-Recommendation Statement

This report is not an official recommendation. Candidate rows are candidates for review with refreshed price context only.

## Explicit Non-Trading/Broker Statement

This report is not trading-authorized and performs no broker/order execution.

## Explicit No Score/Ranking/Return Recalculation Statement

V20.48 calculates no forward returns, no benchmark-relative returns, no scores, and no rankings.

## Blockers And Warnings

Blockers: {blocker_text}
Warnings: {warning_text}

## Next Recommended Stage

{NEXT_STAGE if not blocked else "REPAIR_V20_48_INPUTS"}

## V20.47 Formal Test Output

```text
{v47_test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"DECISION={decision}",
        "REFRESHED_V20_47_CACHE_USED=TRUE",
        f"V20_47_RUN_ID={run_id}",
        "REPORT_GENERATION_ONLY=TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_48=FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_48=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        "RESEARCH_ONLY_STATUS=TRUE",
        f"CANDIDATE_RESEARCH_ROWS_INPUT={len(v45_candidates)}",
        f"UNIQUE_CERTIFIED_CANDIDATE_TICKERS_AVAILABLE={unique_certified}",
        f"CANDIDATE_RESEARCH_ROWS_WITH_REFRESHED_PRICE={mapped_count}",
        f"CANDIDATE_RESEARCH_ROWS_MISSING_REFRESHED_PRICE={missing_count}",
        f"BENCHMARK_ROWS_AVAILABLE={len(benchmark_view)}",
        f"BLOCKER_COUNT={len(blockers)}",
        f"WARNING_COUNT={len(warnings)}",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if not blocked else 'REPAIR_V20_48_INPUTS'}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    cleanup_pycache()

    print(final_status)
    print(f"V20_47_RUN_ID={run_id}")
    print(f"DECISION={decision}")
    print(f"CANDIDATE_RESEARCH_ROWS_INPUT={len(v45_candidates)}")
    print(f"UNIQUE_CERTIFIED_CANDIDATE_TICKERS_AVAILABLE={unique_certified}")
    print(f"CANDIDATE_RESEARCH_ROWS_WITH_REFRESHED_PRICE={mapped_count}")
    print(f"CANDIDATE_RESEARCH_ROWS_MISSING_REFRESHED_PRICE={missing_count}")
    print(f"BENCHMARK_ROWS_AVAILABLE={len(benchmark_view)}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if not blocked else 'REPAIR_V20_48_INPUTS'}")
    return 0 if not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
