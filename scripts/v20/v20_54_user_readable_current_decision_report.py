from __future__ import annotations

import ast
import csv
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.54_USER_READABLE_CURRENT_DECISION_REPORT"
PASS_STATUS = "PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT"
BLOCKED_STATUS = "BLOCKED_V20_54_USER_READABLE_CURRENT_DECISION_REPORT"
NEXT_STAGE = "V20.54_FORMAL_TESTS"
RUN_ID_FALLBACK = "V20_47_20260604T114058Z"

IN_V48_SUMMARY = CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"
IN_V48_CANDIDATE = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
IN_V48_FACTOR = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
IN_V48_ENTRY = CONSOLIDATION / "V20_48_REFRESHED_ENTRY_STRATEGY_VIEW.csv"
IN_V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
IN_V48_LINEAGE = CONSOLIDATION / "V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv"
IN_V48_REPORT = READ_CENTER / "V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT.md"
IN_V49_SUMMARY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
IN_V49_RESEARCH_GATE = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
IN_V49_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
IN_V49_CANDIDATE = CONSOLIDATION / "V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv"
IN_V50_SUMMARY = CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_SUMMARY.csv"
IN_V50_CANDIDATE = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
IN_V50_FACTOR = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_LINEAGE = CONSOLIDATION / "V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_NEXT = CONSOLIDATION / "V20_50_NEXT_STEP_DECISION.csv"
IN_V52_SUMMARY = CONSOLIDATION / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_SUMMARY.csv"
IN_V52_LANGUAGE = CONSOLIDATION / "V20_52_RECOMMENDATION_LANGUAGE_POLICY.csv"
IN_V52_SAFETY = CONSOLIDATION / "V20_52_POLICY_CONTRACT_SAFETY_BOUNDARY.csv"
IN_V53_SUMMARY = CONSOLIDATION / "V20_53_OFFICIAL_SCHEMA_DRY_RUN_SUMMARY.csv"
IN_V53_DRY_ROWS = CONSOLIDATION / "V20_53_CANDIDATE_SCHEMA_DRY_RUN_ROWS.csv"
IN_V53_LANGUAGE = CONSOLIDATION / "V20_53_LANGUAGE_POLICY_DRY_RUN_VALIDATION.csv"
IN_V53_SAFETY = CONSOLIDATION / "V20_53_SCHEMA_DRY_RUN_SAFETY_BOUNDARY.csv"
IN_V53_REPORT = READ_CENTER / "V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE_REPORT.md"

OUT_SUMMARY = CONSOLIDATION / "V20_54_USER_READABLE_REPORT_SUMMARY.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_54_USER_READABLE_CANDIDATE_VIEW.csv"
OUT_PRIORITY = CONSOLIDATION / "V20_54_PRIORITY_REVIEW_READABLE_VIEW.csv"
OUT_STANDARD = CONSOLIDATION / "V20_54_STANDARD_REVIEW_READABLE_VIEW.csv"
OUT_FACTOR = CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv"
OUT_ENTRY = CONSOLIDATION / "V20_54_ENTRY_STRATEGY_READABLE_VIEW.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_54_BENCHMARK_CONTEXT_READABLE_VIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_54_LINEAGE_FRESHNESS_READABLE_VIEW.csv"
OUT_POLICY = CONSOLIDATION / "V20_54_POLICY_LANGUAGE_BOUNDARY_CHECK.csv"
OUT_SAFETY = CONSOLIDATION / "V20_54_SAFETY_BOUNDARY_VALIDATION.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_54_REQUIRED_ARTIFACT_MANIFEST.csv"
REPORT = READ_CENTER / "V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md"
READ_FIRST = OPS / "V20_54_READ_FIRST.txt"

REQUIRED_INPUTS = [
    IN_V48_SUMMARY,
    IN_V48_CANDIDATE,
    IN_V48_FACTOR,
    IN_V48_ENTRY,
    IN_V48_BENCHMARK,
    IN_V48_LINEAGE,
    IN_V48_REPORT,
    IN_V49_SUMMARY,
    IN_V49_CANDIDATE,
    IN_V50_SUMMARY,
    IN_V50_CANDIDATE,
    IN_V50_FACTOR,
    IN_V50_ENTRY,
    IN_V50_BENCHMARK,
    IN_V50_LINEAGE,
    IN_V50_NEXT,
    IN_V52_SUMMARY,
    IN_V52_LANGUAGE,
    IN_V52_SAFETY,
    IN_V53_SUMMARY,
    IN_V53_DRY_ROWS,
    IN_V53_LANGUAGE,
    IN_V53_SAFETY,
    IN_V53_REPORT,
]

GENERATED_OUTPUTS = [
    OUT_SUMMARY,
    OUT_CANDIDATE,
    OUT_PRIORITY,
    OUT_STANDARD,
    OUT_FACTOR,
    OUT_ENTRY,
    OUT_BENCHMARK,
    OUT_LINEAGE,
    OUT_POLICY,
    OUT_SAFETY,
    OUT_MANIFEST,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


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


def first_available(row: dict[str, str], names: list[str]) -> str:
    lower = {key.lower(): key for key in row}
    for name in names:
        key = lower.get(name.lower())
        if key is not None and clean(row.get(key)):
            return clean(row.get(key))
    return ""


def by_ticker(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = first_available(row, ["normalized_ticker", "candidate_id_or_ticker", "ticker_or_candidate_id", "display_name_or_ticker"])
        if ticker and ticker not in mapping:
            mapping[ticker] = row
    return mapping


def safe_join(values: list[str]) -> str:
    return " | ".join(value for value in values if clean(value))


def source_has_forbidden_imports(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"yfinance", "requests", "urllib", "httpx", "alpaca_trade_api", "ibapi", "ccxt"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in forbidden for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden:
                return True
    return False


def actionable_hits(text: str) -> list[str]:
    lowered = text.lower()
    allowed = [
        r"not_a_trading_signal",
        r"no_broker_action",
        r"no_order_execution",
        r"no buy/sell/hold instruction",
        r"no buy/sell/hold instructions",
        r"does not create buy/sell/hold instructions",
        r"not a trading signal",
        r"no trading signal",
        r"no trading signals",
        r"does not connect to broker/order systems",
        r"no broker/order execution",
        r"preserved report order",
        r"report order",
        r"no real-world action",
        r"manual review is required before any real-world action",
        r"no provider refresh",
        r"does not refresh market providers",
        r"research-only",
        r"research_only",
        r"priority_review",
        r"standard_review",
        r"watch_for_review",
    ]
    for phrase in allowed:
        lowered = re.sub(phrase, "", lowered, flags=re.IGNORECASE)
    patterns = [
        r"\bstrong buy\b",
        r"\bauto trade\b",
        r"\bposition instruction\b",
        r"\btrading signal\b",
        r"\border\b",
        r"\bexecute\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\bhold\b",
    ]
    hits: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            start = max(0, match.start() - 35)
            end = min(len(lowered), match.end() + 35)
            hits.append(lowered[start:end].replace("\n", " "))
    return hits


PROMOTION_ONLY_INPUTS = {
    IN_V52_SUMMARY,
    IN_V52_LANGUAGE,
    IN_V52_SAFETY,
    IN_V53_SUMMARY,
    IN_V53_DRY_ROWS,
    IN_V53_LANGUAGE,
    IN_V53_SAFETY,
    IN_V53_REPORT,
}


def build_manifest(research_only_ready: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in REQUIRED_INPUTS:
        ok = exists_non_empty(path)
        promotion_optional = research_only_ready and path in PROMOTION_ONLY_INPUTS
        rows.append({
            "artifact_role": "promotion_only_optional_input" if promotion_optional else "required_upstream_input",
            "artifact_path": rel(path),
            "exists_non_empty": tf(ok),
            "validation_status": "PASS" if ok or promotion_optional else "BLOCKED",
            "blocker_reason": "" if ok or promotion_optional else "missing_or_empty",
        })
    return rows


def build_factor_view(factors: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, row in enumerate(factors, 1):
        rows.append({
            "factor_row_id": f"V20_54_FACTOR_{index:03d}",
            "factor_id_or_name": first_available(row, ["factor_id_or_name"]),
            "factor_category": first_available(row, ["factor_category"]),
            "support_status": first_available(row, ["support_status"]),
            "review_ready": first_available(row, ["review_ready"]),
            "research_only_flag": first_available(row, ["research_only_flag"]) or "TRUE",
            "factor_support_summary": first_available(row, ["factor_context_summary", "factor_research_interpretation"]),
            "included_in_official_weight_flag": first_available(row, ["included_in_official_weight_flag"]) or "FALSE",
            "dynamic_weighting_mutated": first_available(row, ["dynamic_weighting_mutated"]) or "FALSE",
            "readable_note": "Factor context is included for operator review only; no factor weight changed.",
        })
    return rows


def build_entry_view(entries: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, row in enumerate(entries, 1):
        rows.append({
            "entry_strategy_row_id": f"V20_54_ENTRY_{index:03d}",
            "strategy_id_or_name": first_available(row, ["strategy_id_or_name"]),
            "strategy_family": first_available(row, ["strategy_family"]),
            "readiness_status": first_available(row, ["readiness_status"]),
            "review_ready": first_available(row, ["review_ready"]),
            "research_only_flag": first_available(row, ["research_only_flag"]) or "TRUE",
            "entry_strategy_support_summary": first_available(row, ["entry_strategy_context_summary", "entry_strategy_interpretation"]),
            "allowed_for_live_trading": first_available(row, ["allowed_for_live_trading"]) or "FALSE",
            "broker_execution_enabled": first_available(row, ["broker_execution_enabled"]) or "FALSE",
            "trading_signal_created": first_available(row, ["trading_signal_created"]) or "FALSE",
            "readable_note": "Entry context is included for manual review only; NOT_A_TRADING_SIGNAL.",
        })
    return rows


def build_benchmark_view(benchmarks: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, row in enumerate(benchmarks, 1):
        rows.append({
            "benchmark_row_id": f"V20_54_BENCHMARK_{index:03d}",
            "benchmark_ticker": first_available(row, ["benchmark_ticker"]),
            "v20_47_run_id": first_available(row, ["v20_47_run_id"]),
            "refreshed_price_date": first_available(row, ["refreshed_price_date"]),
            "refreshed_latest_close": first_available(row, ["refreshed_latest_close"]),
            "certification_status": first_available(row, ["certification_status"]),
            "review_ready": first_available(row, ["review_ready"]),
            "benchmark_context_allowed": first_available(row, ["benchmark_context_allowed", "research_context_allowed"]),
            "benchmark_return_calculated": first_available(row, ["benchmark_return_calculated"]) or "FALSE",
            "research_context_summary": first_available(row, ["research_context_summary"]) or "Benchmark context available for research comparison only.",
            "official_trading_allowed": first_available(row, ["official_trading_allowed"]) or "FALSE",
        })
    return rows


def build_lineage_view(lineage: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, row in enumerate(lineage, 1):
        rows.append({
            "lineage_row_id": f"V20_54_LINEAGE_{index:03d}",
            "source_name_or_input_name": first_available(row, ["source_name_or_input_name"]),
            "source_contract_or_version": first_available(row, ["source_contract_or_version"]),
            "freshness_status": first_available(row, ["freshness_status"]),
            "lineage_status": first_available(row, ["lineage_status"]),
            "v20_47_run_id": first_available(row, ["v20_47_run_id"]),
            "refreshed_cache_certified": first_available(row, ["refreshed_cache_certified"]),
            "safe_for_research_report": first_available(row, ["safe_for_research_report"]),
            "safe_for_official_recommendation": first_available(row, ["safe_for_official_recommendation"]) or "FALSE",
            "safe_for_trading": first_available(row, ["safe_for_trading"]) or "FALSE",
            "lineage_context_summary": first_available(row, ["lineage_context_summary"]) or "Lineage retained for research review only.",
            "blocker_count": first_available(row, ["blocker_count"]) or "0",
            "warning_count": first_available(row, ["warning_count"]) or "0",
        })
    return rows


def build_candidate_view(candidates: list[dict[str, str]], refreshed: list[dict[str, str]], dry_rows: list[dict[str, str]], factor_summary: str, entry_summary: str, benchmark_summary: str, lineage_summary: str) -> list[dict[str, object]]:
    refreshed_by_ticker = by_ticker(refreshed)
    dry_by_ticker = by_ticker(dry_rows)
    rows: list[dict[str, object]] = []
    for index, row in enumerate(candidates, 1):
        ticker = first_available(row, ["normalized_ticker", "candidate_id_or_ticker", "ticker_or_candidate_id", "display_name_or_ticker"])
        refreshed_row = refreshed_by_ticker.get(ticker, {})
        dry_row = dry_by_ticker.get(ticker, {})
        category = first_available(row, ["research_decision_category"]) or "WATCH_FOR_REVIEW"
        rows.append({
            "candidate_row_id": f"V20_54_CANDIDATE_{index:03d}",
            "ticker": ticker,
            "company_or_name": first_available(row, ["display_name_or_ticker", "company_name", "name"]) or ticker,
            "decision_category": category,
            "research_only_status": "RESEARCH_ONLY",
            "manual_review_required": "MANUAL_REVIEW_REQUIRED",
            "latest_refreshed_price": first_available(row, ["refreshed_latest_close"]) or first_available(refreshed_row, ["refreshed_latest_close"]),
            "price_date_or_run_id": first_available(row, ["refreshed_price_date"]) or first_available(row, ["v20_47_run_id"]),
            "v20_47_run_id": first_available(row, ["v20_47_run_id"]) or RUN_ID_FALLBACK,
            "factor_support_summary": factor_summary,
            "entry_strategy_support_summary": entry_summary,
            "benchmark_context": benchmark_summary,
            "risk_freshness_lineage_notes": lineage_summary,
            "schema_status_flags": safe_join([
                f"schema_dry_run_only={first_available(dry_row, ['schema_dry_run_only']) or 'TRUE'}",
                f"label_assigned={first_available(dry_row, ['recommendation_label_assigned']) or 'FALSE'}",
                f"official_created={first_available(dry_row, ['official_recommendation_created']) or 'FALSE'}",
            ]),
            "safe_human_readable_rationale": first_available(row, ["research_rationale", "evidence_summary"]) or "Research-only context available for manual review.",
            "not_a_trading_signal": "NOT_A_TRADING_SIGNAL",
            "no_broker_action": "NO_BROKER_ACTION",
            "no_order_execution": "NO_ORDER_EXECUTION",
        })
    return rows


def build_safety_boundary() -> list[dict[str, object]]:
    specs = [
        ("no provider refresh", "FALSE", "FALSE", "No provider refresh performed in V20.54."),
        ("no yfinance import", "FALSE", "FALSE", "AST import scan blocks yfinance."),
        ("no broker/order execution path", "FALSE", "FALSE", "No broker/order execution path used."),
        ("no official recommendation generation", "FALSE", "FALSE", "Report is research-only."),
        ("no buy/sell/hold instruction generation", "FALSE", "FALSE", "No buy/sell/hold instructions generated."),
        ("no trading signal generation", "FALSE", "FALSE", "No trading signal generated."),
        ("no returns calculation", "FALSE", "FALSE", "No returns calculated."),
        ("no score/ranking recomputation", "FALSE", "FALSE", "No score or rank recomputation."),
        ("no ranking/weight mutation", "FALSE", "FALSE", "No ranking or factor weight mutation."),
        ("no dynamic weighting mutation", "FALSE", "FALSE", "No dynamic weighting mutation."),
        ("no V21 outputs", "FALSE", "FALSE", "No outputs/v21 path created."),
        ("no V19.21 outputs", "FALSE", "FALSE", "No outputs/v19_21 or outputs/v19/V19_21 path created."),
        ("report is research-only", "TRUE", "TRUE", "Report status is RESEARCH_ONLY."),
        ("manual review required", "TRUE", "TRUE", "Manual review required before real-world action."),
        ("no real-book action", "FALSE", "FALSE", "No real-book state mutation."),
    ]
    return [
        {
            "safety_check": name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": "PASS" if expected == actual else "BLOCKED",
            "evidence": evidence,
            "blocker_reason": "" if expected == actual else "safety_boundary_failed",
        }
        for name, expected, actual, evidence in specs
    ]


def build_policy_checks(paths: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        hits = actionable_hits(text)
        rows.append({
            "checked_artifact": rel(path),
            "forbidden_actionable_phrase_count": len(hits),
            "research_only_language_confirmed": tf(not hits),
            "validation_status": "PASS" if not hits else "BLOCKED",
            "blocker_reason": "" if not hits else "actionable_language_detected",
            "sample_hit": hits[0] if hits else "",
        })
    return rows


def md_table(rows: list[dict[str, object]], fields: list[str], limit: int | None = None) -> str:
    selected = rows if limit is None else rows[:limit]
    if not selected:
        return "_No rows._"
    header = "| " + " | ".join(fields) + " |"
    sep = "| " + " | ".join(["---"] * len(fields)) + " |"
    body = ["| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in fields) + " |" for row in selected]
    return "\n".join([header, sep, *body])


def cleanup_pycache() -> None:
    pycache = SCRIPT_DIR / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)


def main() -> int:
    v48_summary = first_row(IN_V48_SUMMARY)
    v49_research = first_row(IN_V49_RESEARCH_GATE)
    v49_promotion = first_row(IN_V49_PROMOTION_GATE)
    v50_summary = first_row(IN_V50_SUMMARY)
    v53_summary = first_row(IN_V53_SUMMARY)
    research_only_ready = clean(v49_research.get("research_only_gate_status")) == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
    candidates, _ = read_csv(IN_V50_CANDIDATE)
    refreshed_candidates, _ = read_csv(IN_V48_CANDIDATE)
    dry_rows, _ = read_csv(IN_V53_DRY_ROWS)
    factors, _ = read_csv(IN_V50_FACTOR)
    entries, _ = read_csv(IN_V50_ENTRY)
    benchmarks, _ = read_csv(IN_V50_BENCHMARK)
    lineage, _ = read_csv(IN_V50_LINEAGE)
    v20_47_run_id = (
        clean(v50_summary.get("v20_47_run_id"))
        or clean(v48_summary.get("v20_47_run_id"))
        or clean(v53_summary.get("v20_47_run_id"))
        or RUN_ID_FALLBACK
    )

    manifest = build_manifest(research_only_ready)
    factor_view = build_factor_view(factors)
    entry_view = build_entry_view(entries)
    benchmark_view = build_benchmark_view(benchmarks)
    lineage_view = build_lineage_view(lineage)

    factor_summary = f"{len(factor_view)} factor context rows available for research review."
    entry_summary = f"{len(entry_view)} entry context rows available for manual review; NOT_A_TRADING_SIGNAL."
    benchmark_summary = f"{len(benchmark_view)} benchmark context rows available; no return calculation."
    lineage_summary = f"{len(lineage_view)} lineage/freshness rows available; safe_for_trading remains FALSE."
    candidate_view = build_candidate_view(candidates, refreshed_candidates, dry_rows, factor_summary, entry_summary, benchmark_summary, lineage_summary)
    priority_view = [row for row in candidate_view if clean(row.get("decision_category")) == "PRIORITY_REVIEW"]
    standard_view = [row for row in candidate_view if clean(row.get("decision_category")) == "STANDARD_REVIEW"]
    safety = build_safety_boundary()

    blockers = [clean(row.get("blocker_reason")) for row in manifest if clean(row.get("validation_status")) == "BLOCKED"]
    if source_has_forbidden_imports(Path(__file__)):
        blockers.append("forbidden_runtime_import")
    if (ROOT / "outputs" / "v21").exists() or (ROOT / "outputs" / "v19_21").exists() or (ROOT / "outputs" / "v19" / "V19_21").exists():
        blockers.append("forbidden_future_output_path_exists")
    if clean(v53_summary.get("schema_dry_run_status")) != "PASS_SCHEMA_DRY_RUN_GATE_CREATED" and not research_only_ready:
        blockers.append("v20_53_schema_dry_run_not_pass")
    warnings: list[str] = []

    candidate_fields = ["candidate_row_id", "ticker", "company_or_name", "decision_category", "research_only_status", "manual_review_required", "latest_refreshed_price", "price_date_or_run_id", "v20_47_run_id", "factor_support_summary", "entry_strategy_support_summary", "benchmark_context", "risk_freshness_lineage_notes", "schema_status_flags", "safe_human_readable_rationale", "not_a_trading_signal", "no_broker_action", "no_order_execution"]
    write_csv(OUT_CANDIDATE, candidate_view, candidate_fields)
    write_csv(OUT_PRIORITY, priority_view, candidate_fields)
    write_csv(OUT_STANDARD, standard_view, candidate_fields)
    write_csv(OUT_FACTOR, factor_view, ["factor_row_id", "factor_id_or_name", "factor_category", "support_status", "review_ready", "research_only_flag", "factor_support_summary", "included_in_official_weight_flag", "dynamic_weighting_mutated", "readable_note"])
    write_csv(OUT_ENTRY, entry_view, ["entry_strategy_row_id", "strategy_id_or_name", "strategy_family", "readiness_status", "review_ready", "research_only_flag", "entry_strategy_support_summary", "allowed_for_live_trading", "broker_execution_enabled", "trading_signal_created", "readable_note"])
    write_csv(OUT_BENCHMARK, benchmark_view, ["benchmark_row_id", "benchmark_ticker", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "certification_status", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated", "research_context_summary", "official_trading_allowed"])
    write_csv(OUT_LINEAGE, lineage_view, ["lineage_row_id", "source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status", "v20_47_run_id", "refreshed_cache_certified", "safe_for_research_report", "safe_for_official_recommendation", "safe_for_trading", "lineage_context_summary", "blocker_count", "warning_count"])
    write_csv(OUT_SAFETY, safety, ["safety_check", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_MANIFEST, manifest, ["artifact_role", "artifact_path", "exists_non_empty", "validation_status", "blocker_reason"])

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    final_status = PASS_STATUS if not blockers else BLOCKED_STATUS
    report = f"""# V20.54 User-Readable Current Decision Report

## Stage status

Stage: {STAGE}
Status: {final_status}
Research-only status: TRUE
V20.47 run ID/cache reference: {v20_47_run_id}
V20.49 research-only gate: {clean(v49_research.get("research_only_gate_status"))}
V20.49 official promotion gate: {clean(v49_promotion.get("official_promotion_gate_status"))}
Official promotion blockers: {clean(v49_promotion.get("official_promotion_blockers"))}
Missing promotion lineage sources: {clean(v49_promotion.get("missing_promotion_lineage_sources"))}

## Upstream artifacts used

{md_table(manifest, ["artifact_path", "exists_non_empty", "validation_status"], 30)}

## Current run / refreshed price context

Refreshed candidate rows available: {len(refreshed_candidates)}
Candidate rows in research-only packet: {len(candidates)}
Latest refreshed context is carried from prior V20 gates without provider refresh in V20.54.

## Candidate overview

{len(candidate_view)} candidates are included for manual operator review. Categories are preserved from V20.50 and are not recomputed.

## Priority review candidates

{md_table(priority_view, ["ticker", "decision_category", "latest_refreshed_price", "safe_human_readable_rationale"], 20)}

## Standard review candidates

{md_table(standard_view, ["ticker", "decision_category", "latest_refreshed_price", "safe_human_readable_rationale"], 20)}

## Factor support summary

{md_table(factor_view, ["factor_id_or_name", "support_status", "factor_support_summary"], 12)}

## Entry strategy support summary

{md_table(entry_view, ["strategy_id_or_name", "readiness_status", "entry_strategy_support_summary"], 12)}

## Benchmark context

{md_table(benchmark_view, ["benchmark_ticker", "refreshed_price_date", "refreshed_latest_close", "research_context_summary"])}

## Lineage and freshness

{md_table(lineage_view, ["source_name_or_input_name", "freshness_status", "lineage_status", "safe_for_research_report"], 12)}

## Policy/language boundary

Generated content is constrained to RESEARCH_ONLY, MANUAL_REVIEW_REQUIRED, NOT_A_TRADING_SIGNAL, NO_BROKER_ACTION, and NO_ORDER_EXECUTION language.

## Safety boundary

{md_table(safety, ["safety_check", "expected_value", "actual_value", "validation_status"])}

## What this report is allowed to mean

This report may summarize refreshed research-only context for a human operator. It may preserve V20.50 PRIORITY_REVIEW and STANDARD_REVIEW categories for review workflow planning.

## What this report is not allowed to mean

This report is not an official recommendation. It is not a trading signal. It does not create buy/sell/hold instructions. It does not refresh market providers. It does not connect to broker/order systems. It does not mutate ranking, score, factor weight, dynamic weight, or real-book positions. Manual review is required before any real-world action.

## Recommended next gated stage

{NEXT_STAGE}

## Blockers and warnings

Blockers: {blocker_text}
Warnings: {warning_text}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        "REPORT_TYPE=USER_READABLE_RESEARCH_ONLY_CURRENT_DECISION_REPORT",
        "THIS_IS_NOT_AN_OFFICIAL_RECOMMENDATION=TRUE",
        "THIS_IS_NOT_A_TRADING_SIGNAL=TRUE",
        "BUY_SELL_HOLD_INSTRUCTIONS_CREATED=FALSE",
        "MARKET_PROVIDER_REFRESH_EXECUTED_IN_V20_54=FALSE",
        "BROKER_ORDER_SYSTEM_CONNECTED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "SCORE_RECOMPUTED=FALSE",
        "FACTOR_WEIGHT_MUTATED=FALSE",
        "DYNAMIC_WEIGHT_MUTATED=FALSE",
        "REAL_BOOK_POSITION_MUTATED=FALSE",
        "MANUAL_REVIEW_REQUIRED_BEFORE_REAL_WORLD_ACTION=TRUE",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    policy_checks = build_policy_checks([OUT_CANDIDATE, OUT_PRIORITY, OUT_STANDARD, OUT_FACTOR, OUT_ENTRY, OUT_BENCHMARK, OUT_LINEAGE, REPORT, CURRENT_REPORT, READ_FIRST])
    blockers.extend(clean(row.get("blocker_reason")) for row in policy_checks if clean(row.get("validation_status")) == "BLOCKED")
    blockers.extend(clean(row.get("blocker_reason")) for row in safety if clean(row.get("validation_status")) == "BLOCKED")
    blockers = [item for item in blockers if item]
    final_status = PASS_STATUS if not blockers else BLOCKED_STATUS
    blocker_count = len(blockers)
    warning_count = len(warnings)
    blocker_text = "None" if not blockers else "; ".join(blockers)
    if blockers:
        report = report.replace(f"Status: {PASS_STATUS}", f"Status: {BLOCKED_STATUS}").replace("Blockers: None", f"Blockers: {blocker_text}")
        write_text(REPORT, report)
        write_text(CURRENT_REPORT, report)
        read_first = read_first.replace(f"STATUS={PASS_STATUS}", f"STATUS={BLOCKED_STATUS}")
        write_text(READ_FIRST, read_first)
        policy_checks = build_policy_checks([OUT_CANDIDATE, OUT_PRIORITY, OUT_STANDARD, OUT_FACTOR, OUT_ENTRY, OUT_BENCHMARK, OUT_LINEAGE, REPORT, CURRENT_REPORT, READ_FIRST])
    write_csv(OUT_POLICY, policy_checks, ["checked_artifact", "forbidden_actionable_phrase_count", "research_only_language_confirmed", "validation_status", "blocker_reason", "sample_hit"])

    summary = [{
        "stage": STAGE,
        "status": final_status,
        "v20_47_run_id": v20_47_run_id,
        "upstream_v20_53_schema_dry_run_status": clean(v53_summary.get("schema_dry_run_status")),
        "required_artifacts_checked": len(manifest),
        "required_artifacts_passed": sum(1 for row in manifest if clean(row.get("validation_status")) == "PASS"),
        "candidate_rows_included": len(candidate_view),
        "priority_review_rows": len(priority_view),
        "standard_review_rows": len(standard_view),
        "factor_support_rows": len(factor_view),
        "entry_strategy_rows": len(entry_view),
        "benchmark_context_rows": len(benchmark_view),
        "lineage_freshness_rows": len(lineage_view),
        "policy_boundary_status": "PASS" if all(clean(row.get("validation_status")) == "PASS" for row in policy_checks) else "BLOCKED",
        "safety_boundary_status": "PASS" if all(clean(row.get("validation_status")) == "PASS" for row in safety) else "BLOCKED",
        "official_recommendation_created": "FALSE",
        "buy_sell_hold_instruction_created": "FALSE",
        "trading_signal_created": "FALSE",
        "provider_refresh_executed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "factor_weight_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "real_book_mutated": "FALSE",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "next_recommended_stage": NEXT_STAGE,
    }]
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))

    cleanup_pycache()
    print(final_status)
    print(f"CANDIDATE_ROWS_INCLUDED={len(candidate_view)}")
    print(f"PRIORITY_REVIEW_ROWS={len(priority_view)}")
    print(f"STANDARD_REVIEW_ROWS={len(standard_view)}")
    print(f"FACTOR_SUPPORT_ROWS={len(factor_view)}")
    print(f"ENTRY_STRATEGY_ROWS={len(entry_view)}")
    print(f"BENCHMARK_CONTEXT_ROWS={len(benchmark_view)}")
    print(f"LINEAGE_FRESHNESS_ROWS={len(lineage_view)}")
    print(f"POLICY_BOUNDARY_STATUS={summary[0]['policy_boundary_status']}")
    print(f"SAFETY_BOUNDARY_STATUS={summary[0]['safety_boundary_status']}")
    print(f"BLOCKER_COUNT={blocker_count}")
    print(f"WARNING_COUNT={warning_count}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}")
    return 0 if final_status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
