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

STAGE = "V20.86_REGIME_CONDITIONED_EVIDENCE_EXPORT"
PASS_PARTIAL = "PASS_V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE"
PASS_FULL = "PASS_V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE"
BLOCKED = "BLOCKED_V20_86_MISSING_REQUIRED_UPSTREAM_EVIDENCE"
UNSAFE = "BLOCKED_V20_86_UNSAFE_UPSTREAM_GUARDRAIL"

V20_85_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_EVIDENCE_GAP_CLOSURE_PLANNER_MANIFEST.json"
V20_87_SUMMARY = OPS / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT_SUMMARY.json"
V20_88_SUMMARY = OPS / "V20_CURRENT_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT_SUMMARY.json"
V20_84_MANIFEST = OPS / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json"
V20_82_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_MANIFEST.json"
V20_82_BENCHMARK = CONSOLIDATION / "V20_CURRENT_BENCHMARK_STRATEGY_COMPARISON.csv"
V20_88_EVIDENCE = CONSOLIDATION / "V20_CURRENT_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv"
V20_87_EVIDENCE = CONSOLIDATION / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv"
V20_79_REGIME = CONSOLIDATION / "V20_79_MARKET_REGIME_SNAPSHOT.csv"
V20_57_REGIME = CONSOLIDATION / "V20_57_MARKET_REGIME_SHADOW_PROPOSALS.csv"

OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv",
    "coverage": CONSOLIDATION / "V20_86_REGIME_CONDITIONED_COMPONENT_COVERAGE.csv",
    "bucket": CONSOLIDATION / "V20_86_REGIME_BUCKET_SUMMARY.csv",
    "report": READ_CENTER / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT_REPORT.md",
    "summary": OPS / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT_SUMMARY.json",
    "manifest": OPS / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT_MANIFEST.json",
}

EVIDENCE_FIELDS = [
    "ticker", "signal_date", "as_of_date", "evidence_component_id", "path_id", "strategy_id", "benchmark_id",
    "benchmark_symbol", "forward_window", "row_level_return", "benchmark_return", "excess_return_vs_benchmark",
    "negative_return_flag", "benchmark_underperformance_flag", "downside_threshold_breach_flag", "regime_id",
    "regime_label", "market_regime", "qqq_trend_regime", "spy_trend_regime", "semiconductor_regime",
    "soxx_regime", "volatility_regime", "vix_bucket", "risk_on_off_state", "macro_event_window_flag",
    "earnings_season_flag", "regime_evidence_usable_flag", "regime_evidence_certified_flag",
    "certification_source_field", "certification_source_stage", "missing_reason", "source_stage", "source_artifact",
    "source_run_id",
]
COVERAGE_FIELDS = [
    "evidence_component_id", "required_regime_fields", "available_regime_fields", "usable_row_count",
    "certified_row_count", "regime_count", "required_regime_count", "missing_required_regime_count",
    "regime_labels_available", "regime_labels_missing", "benchmark_symbols_available", "coverage_status",
    "can_contribute_to_v20_82_closure", "blocker_reason",
]
BUCKET_FIELDS = [
    "regime_label", "market_regime", "qqq_trend_regime", "spy_trend_regime", "semiconductor_regime",
    "volatility_regime", "usable_row_count", "certified_row_count", "positive_return_count", "negative_return_count",
    "benchmark_outperformance_count", "benchmark_underperformance_count", "downside_threshold_breach_count",
    "average_row_level_return", "average_benchmark_return", "average_excess_return_vs_benchmark", "coverage_status",
]

CERT_FIELDS = {
    "certification_status",
    "regime_conditioned_certification_status",
    "risk_on_certification_status",
    "risk_off_certification_status",
    "qqq_regime_certification_status",
}
POSITIVE_CERTS = {"CERTIFIED_REGIME_CONDITIONED_EVIDENCE", "CERTIFIED_RISK_ON_EVIDENCE", "CERTIFIED_RISK_OFF_EVIDENCE", "CERTIFIED_QQQ_REGIME_EVIDENCE", "CERTIFIED"}
REJECT_TOKENS = {"INSUFFICIENT", "DESIGN_ONLY", "NOT_READY", "MISSING", "BLOCKED", "RESEARCH_ONLY_GUARDRAIL"}
REQUIRED_FIELDS = ["row_level_return", "regime_label", "source_stage", "source_artifact", "qqq_trend_regime"]
REQUIRED_REGIME_LABELS = {"RISK_ON", "RISK_OFF"}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id() -> str:
    return "V20_86_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


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
    return path.with_name(path.name.replace("V20_86_", "V20_CURRENT_", 1))


def validate_guardrails(manifest: dict[str, object], required_status: str | set[str] | None = None) -> bool:
    if isinstance(required_status, str) and manifest.get("status") != required_status:
        return False
    if isinstance(required_status, set) and manifest.get("status") not in required_status:
        return False
    return (
        manifest.get("research_only") is True
        and manifest.get("official_recommendation_created") is False
        and (manifest.get("official_weight_mutated") is False or manifest.get("weight_mutation_created") is False)
        and manifest.get("trade_action_created") is False
    )


def validate_summary_guardrails(summary: dict[str, object], required_status: str | set[str]) -> bool:
    if isinstance(required_status, str) and summary.get("status") != required_status:
        return False
    if isinstance(required_status, set) and summary.get("status") not in required_status:
        return False
    return (
        summary.get("official_recommendation_created") is False
        and summary.get("weight_mutation_created") is False
        and summary.get("trade_action_created") is False
    )


def benchmark_symbol(benchmark_id: str) -> str:
    text = benchmark_id.upper()
    for symbol in ["QQQ", "SPY", "SOXX", "ETF", "CASH"]:
        if symbol in text:
            return symbol
    return "UNKNOWN"


def risk_state(label: str) -> str:
    upper = label.upper()
    if "RISK_ON" in upper or "UPTREND" in upper or "BULL" in upper:
        return "RISK_ON"
    if "RISK_OFF" in upper or "DOWNTREND" in upper or "BEAR" in upper:
        return "RISK_OFF"
    return "UNKNOWN"


def certification_source(row: dict[str, str]) -> tuple[bool, str]:
    values = [clean(row.get(field)).upper() for field in CERT_FIELDS]
    if any(token in value for value in values for token in REJECT_TOKENS):
        return False, ""
    for field in CERT_FIELDS:
        if clean(row.get(field)).upper() in POSITIVE_CERTS:
            return True, field
    return False, ""


def regime_snapshot(rows: list[dict[str, str]]) -> dict[str, str]:
    snap: dict[str, str] = {}
    for row in rows:
        item = clean(row.get("regime_item")).lower()
        value = clean(row.get("regime_value"))
        if item and value:
            snap[item] = value
    return snap


def transform_rows(rows: list[dict[str, str]], snapshot: dict[str, str]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        strategy = clean(row.get("strategy_name")) or "NA"
        benchmark = clean(row.get("benchmark_name")) or "NA"
        source_artifact = clean(row.get("return_source"))
        regime_label = clean(row.get("regime")) or clean(row.get("regime_label")) or clean(row.get("market_regime"))
        market = clean(row.get("market_regime")) or snapshot.get("market_regime", regime_label)
        qqq_regime = clean(row.get("qqq_trend_regime")) or (regime_label if benchmark_symbol(benchmark) == "QQQ" else snapshot.get("growth_regime", ""))
        spy_regime = clean(row.get("spy_trend_regime")) or (regime_label if benchmark_symbol(benchmark) == "SPY" else "")
        semi_regime = clean(row.get("semiconductor_regime")) or clean(row.get("soxx_regime")) or snapshot.get("semiconductor_regime", "")
        row_ret = parse_float(row.get("strategy_return") or row.get("row_level_return"))
        bench_ret = parse_float(row.get("benchmark_return"))
        excess = parse_float(row.get("excess_return") or row.get("excess_return_vs_benchmark"))
        certified, cert_field = certification_source(row)
        source_stage = clean(row.get("source_stage")) or "V20_82"
        missing = []
        if row_ret is None:
            missing.append("ROW_LEVEL_RETURN")
        if not regime_label:
            missing.append("REGIME_LABEL")
        if not source_stage:
            missing.append("SOURCE_STAGE")
        if not source_artifact:
            missing.append("SOURCE_ARTIFACT")
        if not qqq_regime:
            missing.append("QQQ_REGIME_CONTEXT")
        usable = row_ret is not None and bool(regime_label) and bool(source_stage) and bool(source_artifact)
        output.append(
            {
                "ticker": clean(row.get("ticker")) or "NA",
                "signal_date": clean(row.get("signal_date")) or "NA",
                "as_of_date": clean(row.get("as_of_date")) or "NA",
                "evidence_component_id": f"{strategy}|{clean(row.get('evaluation_window')) or clean(row.get('forward_window')) or 'NA'}",
                "path_id": "REGIME_CONDITIONED",
                "strategy_id": strategy,
                "benchmark_id": benchmark,
                "benchmark_symbol": benchmark_symbol(benchmark),
                "forward_window": clean(row.get("evaluation_window") or row.get("forward_window")) or "NA",
                "row_level_return": fmt(row_ret),
                "benchmark_return": fmt(bench_ret),
                "excess_return_vs_benchmark": fmt(excess),
                "negative_return_flag": tf(row_ret is not None and row_ret < 0) if row_ret is not None else "NA",
                "benchmark_underperformance_flag": tf(excess is not None and excess < 0) if excess is not None else "NA",
                "downside_threshold_breach_flag": tf((row_ret is not None and row_ret <= -5) or (excess is not None and excess <= -5)) if (row_ret is not None or excess is not None) else "NA",
                "regime_id": regime_label or "NA",
                "regime_label": regime_label or "NA",
                "market_regime": market or "NA",
                "qqq_trend_regime": qqq_regime or "NA",
                "spy_trend_regime": spy_regime or "NA",
                "semiconductor_regime": semi_regime or "NA",
                "soxx_regime": semi_regime or "NA",
                "volatility_regime": clean(row.get("volatility_regime")) or snapshot.get("volatility_regime", "NA"),
                "vix_bucket": clean(row.get("vix_bucket")) or "NA",
                "risk_on_off_state": risk_state(regime_label or market),
                "macro_event_window_flag": clean(row.get("macro_event_window_flag")) or "NA",
                "earnings_season_flag": clean(row.get("earnings_season_flag")) or "NA",
                "regime_evidence_usable_flag": tf(usable),
                "regime_evidence_certified_flag": tf(usable and certified),
                "certification_source_field": cert_field or "NA",
                "certification_source_stage": source_stage if cert_field else "NA",
                "missing_reason": "NONE" if not missing else "MISSING_" + "_".join(missing),
                "source_stage": source_stage or "NA",
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
        usable = sum(1 for row in component_rows if row["regime_evidence_usable_flag"] == "TRUE")
        certified = sum(1 for row in component_rows if row["regime_evidence_certified_flag"] == "TRUE")
        labels = {clean(row.get("risk_on_off_state")) for row in component_rows if clean(row.get("risk_on_off_state")) not in {"", "UNKNOWN", "NA"}}
        benchmarks = {clean(row.get("benchmark_symbol")) for row in component_rows if clean(row.get("benchmark_symbol")) not in {"", "UNKNOWN"}}
        available = set()
        for row in component_rows:
            for field in REQUIRED_FIELDS:
                if clean(row.get(field)) not in {"", "NA"}:
                    available.add(field)
        missing_labels = sorted(REQUIRED_REGIME_LABELS - labels)
        missing_fields = [field for field in REQUIRED_FIELDS if field not in available]
        if certified > 0 and not missing_fields and not missing_labels:
            status = "FULLY_COVERED"
            blocker = "NONE"
        elif usable > 0 or labels:
            status = "PARTIAL_COVERAGE"
            blocker = "MISSING_REQUIRED_REGIME_CERTIFICATION_OR_LABELS"
        else:
            status = "MISSING_REQUIRED_REGIME_EVIDENCE"
            blocker = "NO_USABLE_REGIME_CONDITIONED_EVIDENCE"
        coverage.append(
            {
                "evidence_component_id": component_id,
                "required_regime_fields": ";".join(REQUIRED_FIELDS),
                "available_regime_fields": ";".join(sorted(available)) if available else "NA",
                "usable_row_count": usable,
                "certified_row_count": certified,
                "regime_count": len(labels),
                "required_regime_count": len(REQUIRED_REGIME_LABELS),
                "missing_required_regime_count": len(missing_labels),
                "regime_labels_available": ";".join(sorted(labels)) if labels else "NA",
                "regime_labels_missing": ";".join(missing_labels) if missing_labels else "NONE",
                "benchmark_symbols_available": ";".join(sorted(benchmarks)) if benchmarks else "NA",
                "coverage_status": status,
                "can_contribute_to_v20_82_closure": "FALSE",
                "blocker_reason": "V20.86 is research-only and cannot clear V20.82 by itself" if status == "FULLY_COVERED" else blocker,
            }
        )
    if not coverage:
        coverage.append({field: "NA" for field in COVERAGE_FIELDS} | {"coverage_status": "MISSING_REQUIRED_REGIME_EVIDENCE", "can_contribute_to_v20_82_closure": "FALSE", "blocker_reason": "NO_USABLE_REGIME_CONDITIONED_EVIDENCE"})
    return coverage


def avg(values: list[float]) -> str:
    return "NA" if not values else fmt(sum(values) / len(values))


def build_buckets(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(clean(row.get("regime_label")) or "NA", []).append(row)
    buckets: list[dict[str, object]] = []
    for label, bucket_rows in sorted(grouped.items()):
        row_returns = [parse_float(row.get("row_level_return")) for row in bucket_rows]
        bench_returns = [parse_float(row.get("benchmark_return")) for row in bucket_rows]
        excess = [parse_float(row.get("excess_return_vs_benchmark")) for row in bucket_rows]
        row_returns = [value for value in row_returns if value is not None]
        bench_returns = [value for value in bench_returns if value is not None]
        excess = [value for value in excess if value is not None]
        buckets.append(
            {
                "regime_label": label,
                "market_regime": clean(bucket_rows[0].get("market_regime")),
                "qqq_trend_regime": clean(bucket_rows[0].get("qqq_trend_regime")),
                "spy_trend_regime": clean(bucket_rows[0].get("spy_trend_regime")),
                "semiconductor_regime": clean(bucket_rows[0].get("semiconductor_regime")),
                "volatility_regime": clean(bucket_rows[0].get("volatility_regime")),
                "usable_row_count": sum(1 for row in bucket_rows if row["regime_evidence_usable_flag"] == "TRUE"),
                "certified_row_count": sum(1 for row in bucket_rows if row["regime_evidence_certified_flag"] == "TRUE"),
                "positive_return_count": sum(1 for value in row_returns if value > 0),
                "negative_return_count": sum(1 for value in row_returns if value < 0),
                "benchmark_outperformance_count": sum(1 for value in excess if value > 0),
                "benchmark_underperformance_count": sum(1 for value in excess if value < 0),
                "downside_threshold_breach_count": sum(1 for row in bucket_rows if row["downside_threshold_breach_flag"] == "TRUE"),
                "average_row_level_return": avg(row_returns),
                "average_benchmark_return": avg(bench_returns),
                "average_excess_return_vs_benchmark": avg(excess),
                "coverage_status": "PARTIAL_COVERAGE",
            }
        )
    return buckets or [{field: "NA" for field in BUCKET_FIELDS} | {"coverage_status": "MISSING_REQUIRED_REGIME_EVIDENCE"}]


def main() -> int:
    run_id = make_run_id()
    created_at = now_utc()
    input_paths = [V20_85_MANIFEST, V20_87_SUMMARY, V20_88_SUMMARY, V20_84_MANIFEST, V20_82_MANIFEST, V20_82_BENCHMARK, V20_88_EVIDENCE, V20_87_EVIDENCE]
    if V20_79_REGIME.exists():
        input_paths.append(V20_79_REGIME)
    if V20_57_REGIME.exists():
        input_paths.append(V20_57_REGIME)
    v85, s85 = read_json(V20_85_MANIFEST)
    v87, s87 = read_json(V20_87_SUMMARY)
    v88, s88 = read_json(V20_88_SUMMARY)
    v84, s84 = read_json(V20_84_MANIFEST)
    v82, s82 = read_json(V20_82_MANIFEST)
    bench_rows, bench_fields, bench_status = read_csv(V20_82_BENCHMARK)
    _v88_rows, v88_fields, v88_status = read_csv(V20_88_EVIDENCE)
    _v87_rows, v87_fields, v87_status = read_csv(V20_87_EVIDENCE)
    regime_rows, _regime_fields, _regime_status = read_csv(V20_79_REGIME)
    inputs_ok = all(status == "OK" for status in [s85, s87, s88, s84, s82, bench_status, v88_status, v87_status]) and {"strategy_name", "benchmark_name", "strategy_return", "benchmark_return", "excess_return", "regime", "return_source"}.issubset(set(bench_fields)) and bool(v88_fields) and bool(v87_fields)
    upstream_safe = validate_guardrails(v85, "PASS_V20_85_GAP_PLAN_CREATED_WITH_PARTIAL_EVIDENCE") and validate_summary_guardrails(v87, {"PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE", "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE"}) and validate_summary_guardrails(v88, {"PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE", "PASS_V20_88_BENCHMARK_COMPARISON_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE"}) and validate_guardrails(v84, "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS") and validate_guardrails(v82, None)
    if not inputs_ok:
        status = BLOCKED
        evidence_rows: list[dict[str, object]] = []
    elif not upstream_safe:
        status = UNSAFE
        evidence_rows = []
    else:
        evidence_rows = transform_rows(bench_rows, regime_snapshot(regime_rows))
        status = PASS_FULL
    coverage_rows = build_coverage(evidence_rows)
    bucket_rows = build_buckets(evidence_rows)
    full = sum(1 for row in coverage_rows if row["coverage_status"] == "FULLY_COVERED")
    partial = sum(1 for row in coverage_rows if row["coverage_status"] == "PARTIAL_COVERAGE")
    missing = sum(1 for row in coverage_rows if row["coverage_status"] == "MISSING_REQUIRED_REGIME_EVIDENCE")
    usable = sum(1 for row in evidence_rows if row.get("regime_evidence_usable_flag") == "TRUE")
    certified = sum(1 for row in evidence_rows if row.get("regime_evidence_certified_flag") == "TRUE")
    labels = sorted({clean(row.get("risk_on_off_state")) for row in evidence_rows if clean(row.get("risk_on_off_state")) not in {"", "UNKNOWN", "NA"}})
    missing_labels = sorted(REQUIRED_REGIME_LABELS - set(labels))
    benchmarks = sorted({clean(row.get("benchmark_symbol")) for row in evidence_rows if clean(row.get("benchmark_symbol")) not in {"", "UNKNOWN"}})
    if status == PASS_FULL and (partial > 0 or missing > 0 or full == 0):
        status = PASS_PARTIAL
    write_csv(OUTPUTS["evidence"], evidence_rows or [{field: "NA" for field in EVIDENCE_FIELDS} | {"regime_evidence_usable_flag": "FALSE", "regime_evidence_certified_flag": "FALSE", "missing_reason": "MISSING_REQUIRED_UPSTREAM_EVIDENCE"}], EVIDENCE_FIELDS)
    write_csv(OUTPUTS["coverage"], coverage_rows, COVERAGE_FIELDS)
    write_csv(OUTPUTS["bucket"], bucket_rows, BUCKET_FIELDS)
    summary = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "upstream_v20_85_status": clean(v85.get("status")),
        "upstream_v20_87_status": clean(v87.get("status")),
        "upstream_v20_88_status": clean(v88.get("status")),
        "upstream_v20_82_status": clean(v82.get("status")),
        "upstream_v20_84_integration_status": clean(v84.get("v20_82_integration_status")),
        "row_level_regime_evidence_count": len(evidence_rows),
        "usable_regime_evidence_count": usable,
        "certified_regime_evidence_count": certified,
        "fully_covered_component_count": full,
        "partial_component_count": partial,
        "missing_component_count": missing,
        "regime_labels_detected": labels,
        "required_regime_labels": sorted(REQUIRED_REGIME_LABELS),
        "missing_regime_labels": missing_labels,
        "benchmark_symbols_detected": benchmarks,
        "can_clear_v20_82_blocker_now": False,
        "official_recommendation_created": False,
        "weight_mutation_created": False,
        "portfolio_mutation_created": False,
        "trade_action_created": False,
    }
    write_text(OUTPUTS["summary"], json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report = f"""# V20.86 Regime Conditioned Evidence Export Report

## Status
Status: {status}
Run ID: {run_id}
Created UTC: {created_at}

## Research-Only Guardrail
V20.86 is research-only and does not clear V20.82's insufficient-evidence blocker.
No official recommendation, weight mutation, portfolio mutation, order, broker action, or trade action is created.

## Upstream Status
V20.85 status: {summary['upstream_v20_85_status']}
V20.87 status: {summary['upstream_v20_87_status']}
V20.88 status: {summary['upstream_v20_88_status']}
V20.82 status: {summary['upstream_v20_82_status']}
V20.84 integration status: {summary['upstream_v20_84_integration_status']}

## Regime Evidence Summary
Row-level regime evidence count: {len(evidence_rows)}
Usable regime evidence count: {usable}
Certified regime evidence count: {certified}
Regime labels detected: {", ".join(labels) if labels else "NA"}
Required regime labels: {", ".join(sorted(REQUIRED_REGIME_LABELS))}
Missing regime labels: {", ".join(missing_labels) if missing_labels else "NONE"}
Benchmark symbols detected: {", ".join(benchmarks) if benchmarks else "NA"}

## Component Coverage
Fully covered components: {full}
Partial components: {partial}
Missing components: {missing}
Can clear V20.82 blocker now: FALSE

## Certification Notes
Certification requires explicit structured certification fields. Free-text notes alone are not accepted as certification.
Rows with generic market regime but no QQQ-linked regime context remain partial when QQQ-linked regime evidence is required.
"""
    write_text(OUTPUTS["report"], report)
    manifest = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "input_files": [rel(path) for path in input_paths if path.exists()],
        "output_files": [rel(path) for path in OUTPUTS.values()],
        "row_counts": {"evidence": len(evidence_rows) if evidence_rows else 1, "coverage": len(coverage_rows), "bucket": len(bucket_rows), "report": 1, "summary": 1, "manifest": 1},
        **summary,
        "research_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "weight_mutation_created": False,
        "portfolio_mutation_created": False,
        "trade_action_created": False,
    }
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    aliases = []
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
