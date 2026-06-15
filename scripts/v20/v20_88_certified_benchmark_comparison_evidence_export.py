from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

STAGE = "V20.88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT"
PASS_PARTIAL = "PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE"
PASS_FULL = "PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE"
BLOCKED = "BLOCKED_V20_88_MISSING_REQUIRED_UPSTREAM_EVIDENCE"
UNSAFE = "BLOCKED_V20_88_UNSAFE_UPSTREAM_GUARDRAIL"

V20_85_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_EVIDENCE_GAP_CLOSURE_PLANNER_MANIFEST.json"
V20_85_PLAN = CONSOLIDATION / "V20_CURRENT_EVIDENCE_GAP_CLOSURE_PLAN.csv"
V20_87_SUMMARY = OPS / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT_SUMMARY.json"
V20_87_EVIDENCE = CONSOLIDATION / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv"
V20_84_MANIFEST = OPS / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json"
V20_82_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_MANIFEST.json"
V20_82_BENCHMARK = CONSOLIDATION / "V20_CURRENT_BENCHMARK_STRATEGY_COMPARISON.csv"
V20_82_NASDAQ = CONSOLIDATION / "V20_CURRENT_NASDAQ_EFFECTIVENESS_GATE.csv"

OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv",
    "coverage": CONSOLIDATION / "V20_88_BENCHMARK_COMPARISON_COMPONENT_COVERAGE.csv",
    "report": READ_CENTER / "V20_88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT_REPORT.md",
    "summary": OPS / "V20_88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT_SUMMARY.json",
    "manifest": OPS / "V20_88_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT_MANIFEST.json",
}

EVIDENCE_FIELDS = [
    "ticker",
    "signal_date",
    "as_of_date",
    "evidence_component_id",
    "path_id",
    "strategy_id",
    "benchmark_id",
    "benchmark_symbol",
    "forward_window",
    "row_level_return",
    "benchmark_return",
    "excess_return_vs_benchmark",
    "benchmark_outperformance_flag",
    "benchmark_underperformance_flag",
    "nasdaq_hurdle_passed",
    "spy_hurdle_passed",
    "qqq_hurdle_passed",
    "benchmark_comparison_usable_flag",
    "benchmark_comparison_certified_flag",
    "certification_source_field",
    "certification_source_stage",
    "missing_reason",
    "source_stage",
    "source_artifact",
    "source_run_id",
]
COVERAGE_FIELDS = [
    "evidence_component_id",
    "required_benchmark_fields",
    "available_benchmark_fields",
    "usable_row_count",
    "certified_row_count",
    "benchmark_count",
    "required_benchmark_count",
    "missing_required_benchmark_count",
    "benchmark_symbols_available",
    "benchmark_symbols_missing",
    "coverage_status",
    "can_contribute_to_v20_82_closure",
    "blocker_reason",
]

CERT_FIELDS = {
    "certification_status",
    "benchmark_comparison_certification_status",
    "nasdaq_hurdle_certification_status",
    "qqq_comparison_certification_status",
}
POSITIVE_CERTS = {
    "CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE",
    "CERTIFIED_NASDAQ_HURDLE_EVIDENCE",
    "CERTIFIED_QQQ_COMPARISON_EVIDENCE",
    "CERTIFIED",
}
REJECT_TOKENS = {"INSUFFICIENT", "DESIGN_ONLY", "NOT_READY", "MISSING", "BLOCKED", "RESEARCH_ONLY_GUARDRAIL"}
REQUIRED_FIELDS = ["row_level_return", "benchmark_return", "benchmark_id", "excess_return_vs_benchmark"]
REQUIRED_BENCHMARK_SYMBOLS = {"QQQ"}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id() -> str:
    return "V20_88_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def parse_float(value: object) -> float | None:
    text = clean(value)
    if text in {"", "NA", "NONE", "NULL"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt(value: float | None) -> str:
    return "NA" if value is None else f"{value:.6f}"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or []), "OK"


def read_json(path: Path) -> tuple[dict[str, object], str]:
    if not path.exists():
        return {}, "MISSING"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "OK"
    except json.JSONDecodeError:
        return {}, "INVALID_JSON"


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def alias_path(path: Path) -> Path:
    return path.with_name(path.name.replace("V20_88_", "V20_CURRENT_", 1))


def validate_guardrails(manifest: dict[str, object], required_status: str | None = None) -> bool:
    if required_status and manifest.get("status") != required_status:
        return False
    return (
        manifest.get("research_only") is True
        and manifest.get("official_recommendation_created") is False
        and manifest.get("official_weight_mutated") is False
        and manifest.get("trade_action_created") is False
    )


def benchmark_symbol(benchmark_id: str) -> str:
    text = benchmark_id.upper()
    for symbol in ["QQQ", "SPY", "SOXX", "ETF", "CASH"]:
        if symbol in text:
            return symbol
    return "UNKNOWN"


def certification_source(row: dict[str, str]) -> tuple[bool, str]:
    structured_values = [clean(row.get(field)).upper() for field in CERT_FIELDS]
    if any(token in value for value in structured_values for token in REJECT_TOKENS):
        return False, ""
    for field in CERT_FIELDS:
        if clean(row.get(field)).upper() in POSITIVE_CERTS:
            return True, field
    return False, ""


def transform_benchmark_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        strategy = clean(row.get("strategy_name")) or "NA"
        benchmark = clean(row.get("benchmark_name")) or "NA"
        strategy_return = parse_float(row.get("strategy_return"))
        bench_return = parse_float(row.get("benchmark_return"))
        excess = parse_float(row.get("excess_return"))
        source_artifact = clean(row.get("return_source"))
        symbol = benchmark_symbol(benchmark)
        missing = []
        if strategy_return is None:
            missing.append("ROW_LEVEL_RETURN")
        if bench_return is None:
            missing.append("BENCHMARK_RETURN")
        if benchmark in {"", "NA"}:
            missing.append("BENCHMARK_ID")
        if excess is None:
            missing.append("EXCESS_RETURN")
        usable = not missing and bool(source_artifact)
        structured_cert, cert_field = certification_source(row)
        certified = usable and structured_cert
        qqq_pass = symbol == "QQQ" and excess is not None and excess > 0
        spy_pass = symbol == "SPY" and excess is not None and excess > 0
        nasdaq_pass = qqq_pass
        output.append(
            {
                "ticker": clean(row.get("ticker")) or "NA",
                "signal_date": clean(row.get("signal_date")) or "NA",
                "as_of_date": clean(row.get("as_of_date")) or "NA",
                "evidence_component_id": f"{strategy}|{clean(row.get('evaluation_window')) or 'NA'}",
                "path_id": "BENCHMARK_COMPARISON",
                "strategy_id": strategy,
                "benchmark_id": benchmark,
                "benchmark_symbol": symbol,
                "forward_window": clean(row.get("evaluation_window")) or "NA",
                "row_level_return": fmt(strategy_return),
                "benchmark_return": fmt(bench_return),
                "excess_return_vs_benchmark": fmt(excess),
                "benchmark_outperformance_flag": tf(excess is not None and excess > 0) if excess is not None else "NA",
                "benchmark_underperformance_flag": tf(excess is not None and excess < 0) if excess is not None else "NA",
                "nasdaq_hurdle_passed": tf(nasdaq_pass) if excess is not None else "NA",
                "spy_hurdle_passed": tf(spy_pass) if excess is not None else "NA",
                "qqq_hurdle_passed": tf(qqq_pass) if excess is not None else "NA",
                "benchmark_comparison_usable_flag": tf(usable),
                "benchmark_comparison_certified_flag": tf(certified),
                "certification_source_field": cert_field or "NA",
                "certification_source_stage": "V20_82" if cert_field else "NA",
                "missing_reason": "NONE" if not missing else "MISSING_" + "_".join(missing),
                "source_stage": "V20_82",
                "source_artifact": source_artifact or "NA",
                "source_run_id": clean(row.get("source_run_id")) or "NA",
            }
        )
    return output


def build_coverage(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(clean(row.get("evidence_component_id")), []).append(row)
    coverage: list[dict[str, object]] = []
    for component_id, component_rows in sorted(grouped.items()):
        usable = sum(1 for row in component_rows if row["benchmark_comparison_usable_flag"] == "TRUE")
        certified = sum(1 for row in component_rows if row["benchmark_comparison_certified_flag"] == "TRUE")
        symbols = {clean(row.get("benchmark_symbol")) for row in component_rows if clean(row.get("benchmark_symbol")) not in {"", "UNKNOWN"}}
        missing_symbols = sorted(REQUIRED_BENCHMARK_SYMBOLS - symbols)
        available = set()
        for row in component_rows:
            for field in REQUIRED_FIELDS:
                csv_field = "excess_return_vs_benchmark" if field == "excess_return_vs_benchmark" else field
                if clean(row.get(csv_field)) not in {"", "NA"}:
                    available.add(field)
        missing_fields = [field for field in REQUIRED_FIELDS if field not in available]
        if certified > 0 and not missing_fields and not missing_symbols:
            status = "FULLY_COVERED"
            blocker = "NONE"
        elif usable > 0 or available or symbols:
            status = "PARTIAL_COVERAGE"
            blocker = "MISSING_REQUIRED_BENCHMARK_CERTIFICATION_OR_SYMBOLS"
        else:
            status = "MISSING_REQUIRED_BENCHMARK_EVIDENCE"
            blocker = "NO_USABLE_BENCHMARK_COMPARISON_EVIDENCE"
        coverage.append(
            {
                "evidence_component_id": component_id,
                "required_benchmark_fields": ";".join(REQUIRED_FIELDS),
                "available_benchmark_fields": ";".join(sorted(available)) if available else "NA",
                "usable_row_count": usable,
                "certified_row_count": certified,
                "benchmark_count": len(symbols),
                "required_benchmark_count": len(REQUIRED_BENCHMARK_SYMBOLS),
                "missing_required_benchmark_count": len(missing_symbols),
                "benchmark_symbols_available": ";".join(sorted(symbols)) if symbols else "NA",
                "benchmark_symbols_missing": ";".join(missing_symbols) if missing_symbols else "NONE",
                "coverage_status": status,
                "can_contribute_to_v20_82_closure": "FALSE",
                "blocker_reason": "V20.88 is research-only and cannot clear V20.82 by itself" if status == "FULLY_COVERED" else blocker,
            }
        )
    if not coverage:
        coverage.append(
            {
                "evidence_component_id": "NO_BENCHMARK_COMPARISON_EVIDENCE",
                "required_benchmark_fields": ";".join(REQUIRED_FIELDS),
                "available_benchmark_fields": "NA",
                "usable_row_count": 0,
                "certified_row_count": 0,
                "benchmark_count": 0,
                "required_benchmark_count": len(REQUIRED_BENCHMARK_SYMBOLS),
                "missing_required_benchmark_count": len(REQUIRED_BENCHMARK_SYMBOLS),
                "benchmark_symbols_available": "NA",
                "benchmark_symbols_missing": ";".join(sorted(REQUIRED_BENCHMARK_SYMBOLS)),
                "coverage_status": "MISSING_REQUIRED_BENCHMARK_EVIDENCE",
                "can_contribute_to_v20_82_closure": "FALSE",
                "blocker_reason": "NO_USABLE_BENCHMARK_COMPARISON_EVIDENCE",
            }
        )
    return coverage


def main() -> int:
    run_id = make_run_id()
    created_at = now_utc()
    input_paths = [V20_85_MANIFEST, V20_85_PLAN, V20_87_SUMMARY, V20_87_EVIDENCE, V20_84_MANIFEST, V20_82_MANIFEST, V20_82_BENCHMARK]
    if V20_82_NASDAQ.exists():
        input_paths.append(V20_82_NASDAQ)
    v85, s85 = read_json(V20_85_MANIFEST)
    v87, s87 = read_json(V20_87_SUMMARY)
    v84, s84 = read_json(V20_84_MANIFEST)
    v82, s82 = read_json(V20_82_MANIFEST)
    bench_rows, bench_fields, bench_status = read_csv(V20_82_BENCHMARK)
    _plan, plan_fields, plan_status = read_csv(V20_85_PLAN)
    _downside, downside_fields, downside_status = read_csv(V20_87_EVIDENCE)
    required_benchmark_fields = {"strategy_name", "benchmark_name", "evaluation_window", "return_source", "strategy_return", "benchmark_return", "excess_return"}
    inputs_ok = (
        s85 == "OK"
        and s87 == "OK"
        and s84 == "OK"
        and s82 == "OK"
        and bench_status == "OK"
        and plan_status == "OK"
        and downside_status == "OK"
        and required_benchmark_fields.issubset(set(bench_fields))
        and bool(plan_fields)
        and bool(downside_fields)
    )
    upstream_safe = (
        validate_guardrails(v85, "PASS_V20_85_GAP_PLAN_CREATED_WITH_PARTIAL_EVIDENCE")
        and v87.get("status") in {"PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE", "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE"}
        and v87.get("official_recommendation_created") is False
        and v87.get("weight_mutation_created") is False
        and v87.get("trade_action_created") is False
        and validate_guardrails(v84, "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS")
        and validate_guardrails(v82, None)
    )
    if not inputs_ok:
        status = BLOCKED
        evidence = []
    elif not upstream_safe:
        status = UNSAFE
        evidence = []
    else:
        evidence = transform_benchmark_rows(bench_rows)
        status = PASS_FULL
    coverage = build_coverage(evidence)
    full = sum(1 for row in coverage if row["coverage_status"] == "FULLY_COVERED")
    partial = sum(1 for row in coverage if row["coverage_status"] == "PARTIAL_COVERAGE")
    missing = sum(1 for row in coverage if row["coverage_status"] == "MISSING_REQUIRED_BENCHMARK_EVIDENCE")
    usable_count = sum(1 for row in evidence if row.get("benchmark_comparison_usable_flag") == "TRUE")
    certified_count = sum(1 for row in evidence if row.get("benchmark_comparison_certified_flag") == "TRUE")
    symbols_detected = sorted({clean(row.get("benchmark_symbol")) for row in evidence if clean(row.get("benchmark_symbol")) not in {"", "UNKNOWN"}})
    missing_symbols = sorted(REQUIRED_BENCHMARK_SYMBOLS - set(symbols_detected))
    if status == PASS_FULL and (partial > 0 or missing > 0 or full == 0):
        status = PASS_PARTIAL
    write_csv(OUTPUTS["evidence"], evidence or [{field: "NA" for field in EVIDENCE_FIELDS} | {"benchmark_comparison_usable_flag": "FALSE", "benchmark_comparison_certified_flag": "FALSE", "missing_reason": "MISSING_REQUIRED_UPSTREAM_EVIDENCE"}], EVIDENCE_FIELDS)
    write_csv(OUTPUTS["coverage"], coverage, COVERAGE_FIELDS)
    summary = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "upstream_v20_85_status": clean(v85.get("status")),
        "upstream_v20_87_status": clean(v87.get("status")),
        "upstream_v20_82_status": clean(v82.get("status")),
        "upstream_v20_84_integration_status": clean(v84.get("v20_82_integration_status")),
        "row_level_benchmark_evidence_count": len(evidence),
        "usable_benchmark_evidence_count": usable_count,
        "certified_benchmark_evidence_count": certified_count,
        "fully_covered_component_count": full,
        "partial_component_count": partial,
        "missing_component_count": missing,
        "benchmark_symbols_detected": symbols_detected,
        "benchmark_symbols_required": sorted(REQUIRED_BENCHMARK_SYMBOLS),
        "benchmark_symbols_missing": missing_symbols,
        "can_clear_v20_82_blocker_now": False,
        "official_recommendation_created": False,
        "weight_mutation_created": False,
        "portfolio_mutation_created": False,
        "trade_action_created": False,
    }
    write_text(OUTPUTS["summary"], json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report = f"""# V20.88 Certified Benchmark Comparison Evidence Export Report

## Status
Status: {status}
Run ID: {run_id}
Created UTC: {created_at}

## Research-Only Guardrail
V20.88 is research-only and does not clear V20.82's insufficient-evidence blocker.
No official recommendation, weight mutation, portfolio mutation, order, broker action, or trade action is created.

## Upstream Status
V20.85 status: {summary['upstream_v20_85_status']}
V20.87 status: {summary['upstream_v20_87_status']}
V20.82 status: {summary['upstream_v20_82_status']}
V20.84 integration status: {summary['upstream_v20_84_integration_status']}

## Benchmark Evidence Summary
Row-level benchmark evidence count: {len(evidence)}
Usable benchmark evidence count: {usable_count}
Certified benchmark evidence count: {certified_count}
Benchmark symbols detected: {", ".join(symbols_detected) if symbols_detected else "NA"}
Benchmark symbols required: {", ".join(sorted(REQUIRED_BENCHMARK_SYMBOLS))}
Benchmark symbols missing: {", ".join(missing_symbols) if missing_symbols else "NONE"}

## Component Coverage
Fully covered components: {full}
Partial components: {partial}
Missing components: {missing}
Can clear V20.82 blocker now: FALSE

## Certification Notes
Certification requires explicit structured certification fields. Free-text notes alone are not accepted as certification.
Rows with benchmark returns but no structured certification remain usable but not certified.
"""
    write_text(OUTPUTS["report"], report)
    manifest = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "input_files": [rel(path) for path in input_paths if path.exists()],
        "output_files": [rel(path) for path in OUTPUTS.values()],
        "row_counts": {"evidence": len(evidence) if evidence else 1, "coverage": len(coverage), "report": 1, "summary": 1, "manifest": 1},
        **summary,
        "research_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "weight_mutation_created": False,
        "portfolio_mutation_created": False,
        "trade_action_created": False,
    }
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    aliases: list[Path] = []
    for path in OUTPUTS.values():
        alias = alias_path(path)
        alias.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, alias)
        aliases.append(alias)
    manifest["output_files"].extend(rel(path) for path in aliases)
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    shutil.copyfile(OUTPUTS["manifest"], alias_path(OUTPUTS["manifest"]))
    print(status)
    return 0 if status in {PASS_PARTIAL, PASS_FULL} else 1


if __name__ == "__main__":
    raise SystemExit(main())
