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

STAGE = "V20.87_DOWNSIDE_RISK_EVIDENCE_EXPORT"
PASS_PARTIAL = "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE"
PASS_FULL = "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE"
BLOCKED = "BLOCKED_V20_87_MISSING_REQUIRED_UPSTREAM_EVIDENCE"
UNSAFE = "BLOCKED_V20_87_UNSAFE_UPSTREAM_GUARDRAIL"

V20_85_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_EVIDENCE_GAP_CLOSURE_PLANNER_MANIFEST.json"
V20_85_PLAN = CONSOLIDATION / "V20_CURRENT_EVIDENCE_GAP_CLOSURE_PLAN.csv"
V20_85_MATRIX = CONSOLIDATION / "V20_CURRENT_COMPONENT_MISSING_EVIDENCE_MATRIX.csv"
V20_84_MANIFEST = OPS / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json"
V20_84_EVIDENCE = CONSOLIDATION / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv"
V20_84_COVERAGE = CONSOLIDATION / "V20_CURRENT_COMPONENT_EVIDENCE_COVERAGE_TABLE.csv"
V20_82_MANIFEST = OPS / "V20_CURRENT_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_MANIFEST.json"
V20_82_BENCHMARK = CONSOLIDATION / "V20_CURRENT_BENCHMARK_STRATEGY_COMPARISON.csv"

OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv",
    "coverage": CONSOLIDATION / "V20_87_DOWNSIDE_RISK_COMPONENT_COVERAGE.csv",
    "report": READ_CENTER / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT_REPORT.md",
    "summary": OPS / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT_SUMMARY.json",
    "manifest": OPS / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT_MANIFEST.json",
}

EVIDENCE_FIELDS = [
    "ticker",
    "signal_date",
    "as_of_date",
    "evidence_component_id",
    "path_id",
    "strategy_id",
    "benchmark_id",
    "forward_window",
    "row_level_return",
    "benchmark_return",
    "excess_return_vs_benchmark",
    "negative_return_flag",
    "benchmark_underperformance_flag",
    "downside_threshold_breach_flag",
    "drawdown_proxy",
    "downside_proxy",
    "downside_evidence_usable_flag",
    "downside_evidence_certified_flag",
    "missing_reason",
    "source_stage",
    "source_artifact",
    "source_run_id",
]
COVERAGE_FIELDS = [
    "evidence_component_id",
    "required_downside_fields",
    "available_downside_fields",
    "usable_row_count",
    "certified_row_count",
    "missing_required_field_count",
    "coverage_status",
    "can_contribute_to_v20_82_closure",
    "blocker_reason",
]

CERTIFICATION_FIELDS = {
    "certification_status",
    "downside_risk_certification_status",
    "risk_certification_status",
    "evidence_certification_status",
}
POSITIVE_CERTIFICATIONS = {"CERTIFIED", "CERTIFIED_DOWNSIDE_RISK_EVIDENCE"}
REJECT_TOKENS = {"INSUFFICIENT", "DESIGN_ONLY", "NOT_READY", "RESEARCH_ONLY_GUARDRAIL", "MISSING", "BLOCKED", "PROXY"}
REQUIRED_DOWNSIDE_FIELDS = [
    "row_level_return",
    "benchmark_return",
    "excess_return_vs_benchmark",
    "negative_return_flag",
    "benchmark_underperformance_flag",
    "drawdown_proxy_or_downside_proxy",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id() -> str:
    return "V20_87_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fmt(value: float | None) -> str:
    return "NA" if value is None else f"{value:.6f}"


def parse_float(value: object) -> float | None:
    text = clean(value)
    if text in {"", "NA", "NONE", "NULL"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


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
    return path.with_name(path.name.replace("V20_87_", "V20_CURRENT_", 1))


def validate_manifest_guardrails(manifest: dict[str, object], required_status: str | None = None) -> bool:
    if required_status and manifest.get("status") != required_status:
        return False
    return (
        manifest.get("research_only") is True
        and manifest.get("official_recommendation_created") is False
        and manifest.get("official_weight_mutated") is False
        and manifest.get("trade_action_created") is False
    )


def row_has_reject_status(row: dict[str, str]) -> bool:
    values = [clean(row.get(field)).upper() for field in CERTIFICATION_FIELDS]
    values.extend([clean(row.get("certification_reason")).upper(), clean(row.get("usable_for_v20_82")).upper()])
    return any(token in value for value in values for token in REJECT_TOKENS)


def structured_certified(row: dict[str, str]) -> bool:
    if row_has_reject_status(row):
        return False
    return any(clean(row.get(field)).upper() in POSITIVE_CERTIFICATIONS for field in CERTIFICATION_FIELDS)


def row_return(row: dict[str, str]) -> float | None:
    metric_name = clean(row.get("metric_name")).lower()
    metric_unit = clean(row.get("metric_unit")).upper()
    value = parse_float(row.get("metric_value"))
    if value is None:
        return None
    if "return" in metric_name or metric_unit in {"RETURN_DECIMAL", "RETURN_PCT", "PCT"}:
        return value
    return None


def build_missing_reason(values: dict[str, object]) -> str:
    missing: list[str] = []
    for field in ["row_level_return", "benchmark_return", "excess_return_vs_benchmark"]:
        if values.get(field) is None:
            missing.append(field.upper())
    if values.get("drawdown_proxy") is None and values.get("downside_proxy") is None:
        missing.append("DRAWDOWN_OR_DOWNSIDE_PROXY")
    if missing:
        return "MISSING_" + "_".join(missing)
    return ""


def evidence_component_id(row: dict[str, str]) -> str:
    parts = [
        clean(row.get("component_name")) or "UNKNOWN_COMPONENT",
        clean(row.get("evidence_path")) or "UNKNOWN_PATH",
        clean(row.get("evaluation_window")) or "UNKNOWN_WINDOW",
    ]
    return "|".join(parts)


def transform_evidence_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        if clean(row.get("research_only")).upper() != "TRUE":
            continue
        official_flags = [row.get("official_recommendation_created"), row.get("official_weight_mutated"), row.get("trade_action_created")]
        if any(clean(flag).upper() == "TRUE" for flag in official_flags):
            continue
        r_return = row_return(row)
        bench_return = parse_float(row.get("benchmark_return"))
        excess = parse_float(row.get("excess_return"))
        drawdown = parse_float(row.get("drawdown"))
        downside = drawdown
        negative = r_return is not None and r_return < 0
        underperforms = excess is not None and excess < 0
        threshold = (r_return is not None and r_return <= -0.05) or (drawdown is not None and drawdown <= -0.05) or (excess is not None and excess <= -0.05)
        values = {
            "row_level_return": r_return,
            "benchmark_return": bench_return,
            "excess_return_vs_benchmark": excess,
            "drawdown_proxy": drawdown,
            "downside_proxy": downside,
        }
        missing = build_missing_reason(values)
        usable = clean(row.get("usable_for_v20_82")).upper() == "TRUE" and r_return is not None and excess is not None
        certified = usable and structured_certified(row) and bench_return is not None and (drawdown is not None or downside is not None)
        output.append(
            {
                "ticker": clean(row.get("ticker")) or "NA",
                "signal_date": clean(row.get("signal_date")) or "NA",
                "as_of_date": clean(row.get("as_of_date")) or "NA",
                "evidence_component_id": evidence_component_id(row),
                "path_id": clean(row.get("evidence_path")) or "NA",
                "strategy_id": clean(row.get("component_name")) or "NA",
                "benchmark_id": clean(row.get("benchmark_name")) or "NA",
                "forward_window": clean(row.get("evaluation_window")) or "NA",
                "row_level_return": fmt(r_return),
                "benchmark_return": fmt(bench_return),
                "excess_return_vs_benchmark": fmt(excess),
                "negative_return_flag": tf(negative) if r_return is not None else "NA",
                "benchmark_underperformance_flag": tf(underperforms) if excess is not None else "NA",
                "downside_threshold_breach_flag": tf(threshold) if (r_return is not None or excess is not None or drawdown is not None) else "NA",
                "drawdown_proxy": fmt(drawdown),
                "downside_proxy": fmt(downside),
                "downside_evidence_usable_flag": tf(usable),
                "downside_evidence_certified_flag": tf(certified),
                "missing_reason": missing or "NONE",
                "source_stage": clean(row.get("source_stage")) or "NA",
                "source_artifact": clean(row.get("source_file")) or "NA",
                "source_run_id": clean(row.get("source_run_id")) or "NA",
            }
        )
    return output


def build_component_coverage(evidence_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in evidence_rows:
        grouped.setdefault(clean(row.get("evidence_component_id")), []).append(row)
    coverage: list[dict[str, object]] = []
    for component_id, rows in sorted(grouped.items()):
        usable_count = sum(1 for row in rows if row["downside_evidence_usable_flag"] == "TRUE")
        certified_count = sum(1 for row in rows if row["downside_evidence_certified_flag"] == "TRUE")
        available = set()
        for row in rows:
            for field in ["row_level_return", "benchmark_return", "excess_return_vs_benchmark", "negative_return_flag", "benchmark_underperformance_flag"]:
                if clean(row.get(field)) not in {"", "NA"}:
                    available.add(field)
            if clean(row.get("drawdown_proxy")) not in {"", "NA"} or clean(row.get("downside_proxy")) not in {"", "NA"}:
                available.add("drawdown_proxy_or_downside_proxy")
        missing = [field for field in REQUIRED_DOWNSIDE_FIELDS if field not in available]
        if certified_count > 0 and not missing:
            status = "FULLY_COVERED"
            blocker = "NONE"
        elif usable_count > 0 or available:
            status = "PARTIAL_COVERAGE"
            blocker = "MISSING_REQUIRED_DOWNSIDE_FIELDS_OR_CERTIFICATION"
        else:
            status = "MISSING_REQUIRED_EVIDENCE"
            blocker = "NO_USABLE_DOWNSIDE_EVIDENCE"
        coverage.append(
            {
                "evidence_component_id": component_id,
                "required_downside_fields": ";".join(REQUIRED_DOWNSIDE_FIELDS),
                "available_downside_fields": ";".join(sorted(available)) if available else "NA",
                "usable_row_count": usable_count,
                "certified_row_count": certified_count,
                "missing_required_field_count": len(missing),
                "coverage_status": status,
                "can_contribute_to_v20_82_closure": "FALSE",
                "blocker_reason": "V20.87 is research-only and cannot clear V20.82 by itself" if status == "FULLY_COVERED" else blocker,
            }
        )
    if not coverage:
        coverage.append(
            {
                "evidence_component_id": "NO_DOWNSIDE_EVIDENCE",
                "required_downside_fields": ";".join(REQUIRED_DOWNSIDE_FIELDS),
                "available_downside_fields": "NA",
                "usable_row_count": 0,
                "certified_row_count": 0,
                "missing_required_field_count": len(REQUIRED_DOWNSIDE_FIELDS),
                "coverage_status": "MISSING_REQUIRED_EVIDENCE",
                "can_contribute_to_v20_82_closure": "FALSE",
                "blocker_reason": "NO_USABLE_DOWNSIDE_EVIDENCE",
            }
        )
    return coverage


def main() -> int:
    run_id = make_run_id()
    created_at = now_utc()
    input_files = [V20_85_MANIFEST, V20_85_PLAN, V20_85_MATRIX, V20_84_MANIFEST, V20_84_EVIDENCE, V20_84_COVERAGE, V20_82_MANIFEST]
    if V20_82_BENCHMARK.exists():
        input_files.append(V20_82_BENCHMARK)

    v20_85_manifest, v20_85_status = read_json(V20_85_MANIFEST)
    v20_84_manifest, v20_84_status = read_json(V20_84_MANIFEST)
    v20_82_manifest, v20_82_status = read_json(V20_82_MANIFEST)
    evidence_rows, evidence_fields, evidence_status = read_csv(V20_84_EVIDENCE)
    _plan_rows, plan_fields, plan_status = read_csv(V20_85_PLAN)
    _matrix_rows, matrix_fields, matrix_status = read_csv(V20_85_MATRIX)

    required_evidence_fields = {
        "component_name",
        "evidence_path",
        "metric_name",
        "metric_value",
        "benchmark_return",
        "excess_return",
        "drawdown",
        "certification_status",
        "usable_for_v20_82",
        "research_only",
        "official_recommendation_created",
        "official_weight_mutated",
        "trade_action_created",
    }
    inputs_ok = (
        v20_85_status == "OK"
        and v20_84_status == "OK"
        and v20_82_status == "OK"
        and evidence_status == "OK"
        and plan_status == "OK"
        and matrix_status == "OK"
        and required_evidence_fields.issubset(set(evidence_fields))
        and bool(plan_fields)
        and bool(matrix_fields)
    )
    upstream_safe = (
        validate_manifest_guardrails(v20_85_manifest, "PASS_V20_85_GAP_PLAN_CREATED_WITH_PARTIAL_EVIDENCE")
        and validate_manifest_guardrails(v20_84_manifest, "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS")
        and validate_manifest_guardrails(v20_82_manifest, None)
    )

    if not inputs_ok:
        status = BLOCKED
        evidence_output: list[dict[str, object]] = []
    elif not upstream_safe:
        status = UNSAFE
        evidence_output = []
    else:
        evidence_output = transform_evidence_rows(evidence_rows)
        status = PASS_FULL

    coverage_output = build_component_coverage(evidence_output)
    fully_covered = sum(1 for row in coverage_output if row["coverage_status"] == "FULLY_COVERED")
    partial = sum(1 for row in coverage_output if row["coverage_status"] == "PARTIAL_COVERAGE")
    missing = sum(1 for row in coverage_output if row["coverage_status"] == "MISSING_REQUIRED_EVIDENCE")
    usable_count = sum(1 for row in evidence_output if row.get("downside_evidence_usable_flag") == "TRUE")
    certified_count = sum(1 for row in evidence_output if row.get("downside_evidence_certified_flag") == "TRUE")
    if status == PASS_FULL and (partial > 0 or missing > 0 or fully_covered == 0):
        status = PASS_PARTIAL

    write_csv(OUTPUTS["evidence"], evidence_output or [{field: "NA" for field in EVIDENCE_FIELDS} | {"downside_evidence_usable_flag": "FALSE", "downside_evidence_certified_flag": "FALSE", "missing_reason": "MISSING_REQUIRED_UPSTREAM_EVIDENCE"}], EVIDENCE_FIELDS)
    write_csv(OUTPUTS["coverage"], coverage_output, COVERAGE_FIELDS)

    summary = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "upstream_v20_85_status": clean(v20_85_manifest.get("status")),
        "upstream_v20_82_status": clean(v20_82_manifest.get("status")),
        "upstream_v20_84_integration_status": clean(v20_84_manifest.get("v20_82_integration_status")),
        "row_level_downside_evidence_count": len(evidence_output),
        "usable_downside_evidence_count": usable_count,
        "certified_downside_evidence_count": certified_count,
        "fully_covered_component_count": fully_covered,
        "partial_component_count": partial,
        "missing_component_count": missing,
        "can_clear_v20_82_blocker_now": False,
        "official_recommendation_created": False,
        "weight_mutation_created": False,
        "trade_action_created": False,
    }
    write_text(OUTPUTS["summary"], json.dumps(summary, indent=2, sort_keys=True) + "\n")

    report = f"""# V20.87 Downside Risk Evidence Export Report

## Status
Status: {status}
Run ID: {run_id}
Created UTC: {created_at}

## Research-Only Guardrail
V20.87 is research-only and does not clear V20.82's insufficient-evidence blocker.
No official recommendation, weight mutation, portfolio mutation, order, broker action, or trade action is created.

## Upstream Status
V20.85 status: {summary['upstream_v20_85_status']}
V20.82 status: {summary['upstream_v20_82_status']}
V20.84 integration status: {summary['upstream_v20_84_integration_status']}

## Downside Evidence Summary
Row-level downside evidence count: {len(evidence_output)}
Usable downside evidence count: {usable_count}
Certified downside evidence count: {certified_count}

## Component Coverage
Fully covered components: {fully_covered}
Partial components: {partial}
Missing components: {missing}
Can clear V20.82 blocker now: FALSE

## Certification Notes
Certification requires explicit structured certification fields. Free-text notes alone are not accepted as certification.
Missing benchmark-relative or drawdown/downside evidence remains missing.
"""
    write_text(OUTPUTS["report"], report)

    manifest = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "input_files": [rel(path) for path in input_files if path.exists()],
        "output_files": [rel(path) for path in OUTPUTS.values()],
        "row_counts": {
            "evidence": len(evidence_output) if evidence_output else 1,
            "coverage": len(coverage_output),
            "report": 1,
            "summary": 1,
            "manifest": 1,
        },
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
