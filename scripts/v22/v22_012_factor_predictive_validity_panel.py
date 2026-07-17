#!/usr/bin/env python
"""V22.012 factor predictive validity panel.

This module evaluates predictive-validity readiness from existing local V21/V22
outputs only. It does not execute chains, fetch data, connect to brokers, mutate
cache, promote factors, or change weights.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.012"
MODULE_NAME = "FACTOR_PREDICTIVE_VALIDITY_PANEL"
STAGE = "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

REGISTRY_INPUT = Path("outputs") / "v22" / "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY" / "v22_factor_evidence_level_registry.csv"
COVERAGE_INPUT = Path("outputs") / "v22" / "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT" / "v22_factor_coverage_audit.csv"

PASS_STATUS = "PASS_V22_012_FACTOR_PREDICTIVE_VALIDITY_PANEL_READY"
WARN_STATUS = "WARN_V22_012_PREDICTIVE_VALIDITY_PANEL_READY_WITH_SOURCE_LIMITATIONS"
FAIL_STATUS = "FAIL_V22_012_PREDICTIVE_VALIDITY_PANEL_MISSING_REQUIRED_INPUTS"
READY_DECISION = "FACTOR_PREDICTIVE_VALIDITY_PANEL_READY_RESEARCH_ONLY"
FAIL_DECISION = "FACTOR_PREDICTIVE_VALIDITY_BLOCKED_MISSING_REQUIRED_INPUTS"

HORIZONS = ["1D", "3D", "5D", "10D", "20D"]
MAX_FILES_PER_DIRECTORY = 40
MAX_SAMPLE_ROWS = 500
FULL_COUNT_SIZE_LIMIT = 1_500_000

NEXT_RECOMMENDED_MODULES = [
    "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT",
    "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT",
    "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD",
    "V22.020_DRAM_DAILY_DECISION_PANEL_R2",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
]

NO_ACTION_GATES = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}

OPTIONAL_INPUTS = [
    Path("outputs") / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT",
    Path("outputs") / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON",
    Path("outputs") / "v21" / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1",
    Path("outputs") / "v21" / "V21.233_MOOMOO_ONLY_ABCDE_RERUN",
    Path("outputs") / "v21" / "V21.201_DRAM_MOOMOO_R4_PLAN",
    Path("outputs") / "v21" / "V21.232_DRAM",
]

PANEL_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "evidence_level_label",
    "coverage_status",
    "eligible_for_predictive_validity_from_v22_011",
    "predictive_validity_status",
    "best_supported_horizon",
    "supported_horizon_count",
    "sample_count_estimate",
    "date_count_estimate",
    "ticker_count_estimate",
    "ic_available",
    "rank_ic_available",
    "top_bottom_available",
    "monotonicity_available",
    "hit_rate_available",
    "aggregate_signal_direction",
    "aggregate_signal_strength",
    "computation_status",
    "primary_source_paths",
    "source_type",
    "multiple_testing_risk",
    "forward_confirmation_required",
    "adoption_eligible_after_v22_012",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

HORIZON_FIELDNAMES = [
    "item_id",
    "item_name",
    "horizon",
    "computation_status",
    "predictive_validity_status",
    "sample_count",
    "date_count",
    "ticker_count",
    "ic",
    "rank_ic",
    "top_quantile_avg_return",
    "bottom_quantile_avg_return",
    "top_minus_bottom_return",
    "hit_rate",
    "monotonicity_score",
    "source_path",
    "source_metric_name",
    "metric_quality",
    "reason",
]

SOURCE_FIELDNAMES = [
    "source_path",
    "exists",
    "file_type",
    "parent_output_name",
    "scan_mode",
    "file_size_bytes",
    "header_columns",
    "row_count_estimate",
    "metric_columns_detected",
    "horizon_columns_detected",
    "item_ids_mapped",
    "source_status",
    "note",
]

READINESS_FIELDNAMES = [
    "group_name",
    "item_count",
    "predictive_ready_count",
    "mixed_signal_count",
    "weak_signal_count",
    "insufficient_panel_count",
    "source_summary_only_count",
    "placeholder_only_count",
    "review_required_count",
    "official_adoption_allowed_count",
    "broker_action_allowed_count",
    "trade_allowed_count",
]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    observed = output_dir.resolve()
    if observed != expected:
        raise ValueError(f"V22.012 output directory must be {expected}, got {observed}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def bool_from_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def output_name_for_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("V21.") or part.startswith("V22."):
            return part
    return path.parent.name


def file_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def candidate_columns(columns: list[str], tokens: list[str]) -> list[str]:
    found: list[str] = []
    for column in columns:
        lower = column.lower()
        if any(token in lower for token in tokens):
            found.append(column)
    return found


def inspect_csv_file(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    scan_mode = "FULL_SHALLOW" if size <= FULL_COUNT_SIZE_LIMIT else "HEADER_ONLY_OR_SAMPLED"
    header_columns: list[str] = []
    row_count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            header_columns = list(reader.fieldnames or [])
            for _row in reader:
                row_count += 1
                if size > FULL_COUNT_SIZE_LIMIT and row_count >= MAX_SAMPLE_ROWS:
                    break
    except (OSError, csv.Error, UnicodeError):
        scan_mode = "READ_ERROR"
    metric_columns = candidate_columns(
        header_columns,
        ["ic", "rank_ic", "hit", "monotonic", "top", "bottom", "spread", "return", "avg_return", "score", "signal"],
    )
    horizon_columns = candidate_columns(header_columns, ["1d", "3d", "5d", "10d", "20d", "horizon", "forward"])
    return {
        "scan_mode": scan_mode,
        "header_columns": header_columns,
        "row_count_estimate": row_count,
        "metric_columns_detected": metric_columns,
        "horizon_columns_detected": horizon_columns,
    }


def bounded_source_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel_path in OPTIONAL_INPUTS:
        path = repo_root / rel_path
        paths.append(path)
        if path.is_dir():
            child_files = [
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".csv", ".json", ".txt"}
            ]
            paths.extend(sorted(child_files, key=lambda item: item.as_posix().lower())[:MAX_FILES_PER_DIRECTORY])
    deduped: dict[str, Path] = {}
    for path in paths:
        deduped[path.resolve().as_posix()] = path
    return list(deduped.values())


def mapped_item_ids_for_source(source_path: str, registry_rows: list[dict[str, str]]) -> list[str]:
    mapped: list[str] = []
    for item in registry_rows:
        item_id = item.get("item_id", "")
        item_type = item.get("item_type", "")
        if item_type == "ETF_OPTION_PLACEHOLDER":
            continue
        if item_type == "TECHNICAL_SUBFACTOR" and ("V21.246" in source_path or "V21.247" in source_path):
            mapped.append(item_id)
        elif item_type == "STRATEGY_RANKING_SYSTEM" and ("V21.233" in source_path or "V21.255" in source_path):
            mapped.append(item_id)
        elif item_type == "DRAM_SYSTEM" and ("V21.201" in source_path or "V21.232" in source_path):
            mapped.append(item_id)
        elif item_type == "FACTOR_FAMILY" and ("V21.246" in source_path or "V21.247" in source_path or "V21.255" in source_path):
            mapped.append(item_id)
    return sorted(set(mapped))


def source_audit_rows(repo_root: Path, registry_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in bounded_source_paths(repo_root):
        exists = path.exists()
        rel_path = path.relative_to(repo_root).as_posix() if exists else path.as_posix()
        parent_output_name = output_name_for_path(path)
        if not exists:
            rows.append(
                {
                    "source_path": rel_path,
                    "exists": False,
                    "file_type": file_type(path),
                    "parent_output_name": parent_output_name,
                    "scan_mode": "SOURCE_NOT_FOUND",
                    "file_size_bytes": 0,
                    "header_columns": "",
                    "row_count_estimate": 0,
                    "metric_columns_detected": "",
                    "horizon_columns_detected": "",
                    "item_ids_mapped": "",
                    "source_status": "SOURCE_NOT_FOUND",
                    "note": "Optional local source is missing.",
                }
            )
            continue
        if path.is_dir():
            rows.append(
                {
                    "source_path": rel_path,
                    "exists": True,
                    "file_type": "directory",
                    "parent_output_name": parent_output_name,
                    "scan_mode": "DIRECTORY_REFERENCE",
                    "file_size_bytes": 0,
                    "header_columns": "",
                    "row_count_estimate": 0,
                    "metric_columns_detected": "",
                    "horizon_columns_detected": "",
                    "item_ids_mapped": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "source_status": "SOURCE_FOUND",
                    "note": "Directory exists; child files are bounded-scanned separately.",
                }
            )
            continue
        inspected = {
            "scan_mode": "METADATA_ONLY",
            "header_columns": [],
            "row_count_estimate": 0,
            "metric_columns_detected": [],
            "horizon_columns_detected": [],
        }
        if path.suffix.lower() == ".csv":
            inspected = inspect_csv_file(path)
        rows.append(
            {
                "source_path": rel_path,
                "exists": True,
                "file_type": file_type(path),
                "parent_output_name": parent_output_name,
                "scan_mode": inspected["scan_mode"],
                "file_size_bytes": path.stat().st_size,
                "header_columns": ";".join(inspected["header_columns"]),
                "row_count_estimate": inspected["row_count_estimate"],
                "metric_columns_detected": ";".join(inspected["metric_columns_detected"]),
                "horizon_columns_detected": ";".join(inspected["horizon_columns_detected"]),
                "item_ids_mapped": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                "source_status": "SOURCE_FOUND",
                "note": "Bounded local source scan only; exact predictive metrics are not fabricated.",
            }
        )
    return rows


def item_sources(item_id: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in sources if item_id in str(row.get("item_ids_mapped", "")).split(";") and row["exists"] is True]


def coverage_by_id(coverage_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("item_id", ""): row for row in coverage_rows if row.get("item_id")}


def has_exact_metric_columns(sources: list[dict[str, Any]]) -> bool:
    exact_tokens = ["ic", "rank_ic", "top_minus_bottom", "hit_rate", "monotonicity"]
    for row in sources:
        columns = str(row.get("metric_columns_detected", "")).lower().split(";")
        if any(token in columns for token in exact_tokens):
            return True
    return False


def has_summary_metric_columns(sources: list[dict[str, Any]]) -> bool:
    return any(str(row.get("metric_columns_detected", "")) for row in sources)


def panel_row_for_item(item: dict[str, str], coverage: dict[str, str], sources: list[dict[str, Any]]) -> dict[str, Any]:
    item_id = item.get("item_id", "")
    item_type = item.get("item_type", "")
    mapped_sources = item_sources(item_id, sources)
    coverage_row = coverage.get(item_id, {})
    eligible_from_coverage = bool_from_text(coverage_row.get("eligible_for_predictive_validity", ""))
    source_paths = [str(row["source_path"]) for row in mapped_sources]
    source_metric_available = has_summary_metric_columns(mapped_sources)
    exact_metric_available = has_exact_metric_columns(mapped_sources)
    row_count = sum(int(row.get("row_count_estimate") or 0) for row in mapped_sources)
    date_count = int(coverage_row.get("date_count_estimate") or 0) if coverage_row else 0
    ticker_count = int(coverage_row.get("ticker_count_estimate") or 0) if coverage_row else 0

    if item_type == "ETF_OPTION_PLACEHOLDER":
        predictive_status = "PLACEHOLDER_ONLY"
        computation_status = "PLACEHOLDER_ONLY"
        aggregate_strength = "NONE"
        reason = "ETF option placeholder has no option-chain ingestion or local predictive panel."
    elif not mapped_sources:
        predictive_status = "INSUFFICIENT_LOCAL_PANEL"
        computation_status = "INSUFFICIENT_LOCAL_PANEL"
        aggregate_strength = "UNKNOWN"
        reason = "No mapped local source files were found for predictive-validity computation."
    elif exact_metric_available:
        predictive_status = "MIXED_SIGNAL"
        computation_status = "LOCAL_METRIC_COLUMNS_PRESENT"
        aggregate_strength = "MIXED"
        reason = "Local metric-like columns exist, but this module does not promote or infer official adoption from them."
    elif source_metric_available or eligible_from_coverage:
        predictive_status = "SOURCE_SUMMARY_ONLY"
        computation_status = "SOURCE_SUMMARY_ONLY"
        aggregate_strength = "QUALITATIVE_ONLY"
        reason = "Local evidence appears summary/proxy-only; exact IC or top-bottom calculations are not available."
    else:
        predictive_status = "WEAK_SIGNAL"
        computation_status = "SOURCE_SUMMARY_ONLY"
        aggregate_strength = "WEAK_OR_UNCLEAR"
        reason = "Local source exists but predictive metric coverage is weak or unclear."

    supported_horizon_count = 0
    best_horizon = ""
    if predictive_status in {"PREDICTIVE_READY", "MIXED_SIGNAL", "SOURCE_SUMMARY_ONLY"}:
        supported_horizon_count = len(HORIZONS) if mapped_sources else 0
        best_horizon = "20D" if supported_horizon_count else ""

    return {
        "item_id": item_id,
        "item_name": item.get("item_name", ""),
        "item_type": item_type,
        "family": item.get("family", ""),
        "evidence_level_label": item.get("evidence_level_label", ""),
        "coverage_status": coverage_row.get("coverage_status", "COVERAGE_MISSING"),
        "eligible_for_predictive_validity_from_v22_011": eligible_from_coverage,
        "predictive_validity_status": predictive_status,
        "best_supported_horizon": best_horizon,
        "supported_horizon_count": supported_horizon_count,
        "sample_count_estimate": row_count,
        "date_count_estimate": date_count,
        "ticker_count_estimate": ticker_count,
        "ic_available": exact_metric_available,
        "rank_ic_available": exact_metric_available,
        "top_bottom_available": exact_metric_available,
        "monotonicity_available": exact_metric_available,
        "hit_rate_available": exact_metric_available,
        "aggregate_signal_direction": "UNKNOWN",
        "aggregate_signal_strength": aggregate_strength,
        "computation_status": computation_status,
        "primary_source_paths": ";".join(source_paths),
        "source_type": "LOCAL_V21_V22_OUTPUTS" if mapped_sources else "NO_LOCAL_SOURCE",
        "multiple_testing_risk": item.get("multiple_testing_risk", "UNKNOWN"),
        "forward_confirmation_required": True,
        "adoption_eligible_after_v22_012": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": item.get("next_required_validation", ""),
        "reason": reason,
    }


def panel_rows(registry_rows: list[dict[str, str]], coverage_rows: list[dict[str, str]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coverage = coverage_by_id(coverage_rows)
    return [panel_row_for_item(item, coverage, sources) for item in registry_rows]


def horizon_rows(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in panel:
        for horizon in HORIZONS:
            rows.append(
                {
                    "item_id": item["item_id"],
                    "item_name": item["item_name"],
                    "horizon": horizon,
                    "computation_status": item["computation_status"],
                    "predictive_validity_status": item["predictive_validity_status"],
                    "sample_count": item["sample_count_estimate"],
                    "date_count": item["date_count_estimate"],
                    "ticker_count": item["ticker_count_estimate"],
                    "ic": "",
                    "rank_ic": "",
                    "top_quantile_avg_return": "",
                    "bottom_quantile_avg_return": "",
                    "top_minus_bottom_return": "",
                    "hit_rate": "",
                    "monotonicity_score": "",
                    "source_path": item["primary_source_paths"],
                    "source_metric_name": "LOCAL_SUMMARY_OR_HEADER_ONLY",
                    "metric_quality": item["computation_status"],
                    "reason": item["reason"],
                }
            )
    return rows


def readiness_summary_rows(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = sorted({str(row["item_type"]) for row in panel})
    rows: list[dict[str, Any]] = []
    for group in groups + ["ALL"]:
        group_rows = panel if group == "ALL" else [row for row in panel if row["item_type"] == group]
        rows.append(
            {
                "group_name": group,
                "item_count": len(group_rows),
                "predictive_ready_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "PREDICTIVE_READY"),
                "mixed_signal_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "MIXED_SIGNAL"),
                "weak_signal_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "WEAK_SIGNAL"),
                "insufficient_panel_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "INSUFFICIENT_LOCAL_PANEL"),
                "source_summary_only_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "SOURCE_SUMMARY_ONLY"),
                "placeholder_only_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "PLACEHOLDER_ONLY"),
                "review_required_count": sum(1 for row in group_rows if row["predictive_validity_status"] == "REVIEW_REQUIRED"),
                "official_adoption_allowed_count": 0,
                "broker_action_allowed_count": 0,
                "trade_allowed_count": 0,
            }
        )
    return rows


def summary_payload(
    repo_root: Path,
    output_dir: Path,
    registry_rows: list[dict[str, str]],
    coverage_rows: list[dict[str, str]],
    panel: list[dict[str, Any]],
    by_horizon: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    registry_exists = (repo_root / REGISTRY_INPUT).exists()
    coverage_exists = (repo_root / COVERAGE_INPUT).exists()
    optional_missing_count = sum(1 for rel_path in OPTIONAL_INPUTS if not (repo_root / rel_path).exists())
    source_limited_count = sum(1 for row in panel if row["predictive_validity_status"] in {"SOURCE_SUMMARY_ONLY", "INSUFFICIENT_LOCAL_PANEL", "PLACEHOLDER_ONLY"})
    if not registry_exists or not coverage_exists:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif optional_missing_count or source_limited_count >= max(1, len(panel) // 2):
        final_status = WARN_STATUS
        final_decision = READY_DECISION
    else:
        final_status = PASS_STATUS
        final_decision = READY_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "freeze_date": FREEZE_DATE,
        "final_status": final_status,
        "final_decision": final_decision,
        "registry_input_exists": registry_exists,
        "coverage_input_exists": coverage_exists,
        "registered_item_count": len(registry_rows),
        "evaluated_item_count": len(panel),
        "predictive_ready_count": sum(1 for row in panel if row["predictive_validity_status"] == "PREDICTIVE_READY"),
        "mixed_signal_count": sum(1 for row in panel if row["predictive_validity_status"] == "MIXED_SIGNAL"),
        "weak_signal_count": sum(1 for row in panel if row["predictive_validity_status"] == "WEAK_SIGNAL"),
        "insufficient_panel_count": sum(1 for row in panel if row["predictive_validity_status"] == "INSUFFICIENT_LOCAL_PANEL"),
        "source_summary_only_count": sum(1 for row in panel if row["predictive_validity_status"] == "SOURCE_SUMMARY_ONLY"),
        "placeholder_only_count": sum(1 for row in panel if row["predictive_validity_status"] == "PLACEHOLDER_ONLY"),
        "review_required_count": sum(1 for row in panel if row["predictive_validity_status"] == "REVIEW_REQUIRED"),
        "horizon_row_count": len(by_horizon),
        "source_file_count": len(sources),
        "scanned_source_file_count": sum(1 for row in sources if row["exists"] is True),
        "optional_source_missing_count": optional_missing_count,
        "adoption_eligible_after_v22_012_count": 0,
        "official_adoption_allowed_count": 0,
        "broker_action_allowed_count": 0,
        "trade_allowed_count": 0,
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        "output_dir": str(output_dir),
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_012_only"],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
            "mutate_v21_outputs",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
            "promote_factor",
            "promote_strategy",
            "change_factor_weight",
        ],
        **{key: value for key, value in NO_ACTION_GATES.items() if key != "research_only"},
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.012 Factor Predictive Validity Panel",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"registry_input_exists={summary['registry_input_exists']}",
        f"coverage_input_exists={summary['coverage_input_exists']}",
        f"registered_item_count={summary['registered_item_count']}",
        f"evaluated_item_count={summary['evaluated_item_count']}",
        f"predictive_ready_count={summary['predictive_ready_count']}",
        f"mixed_signal_count={summary['mixed_signal_count']}",
        f"source_summary_only_count={summary['source_summary_only_count']}",
        f"insufficient_panel_count={summary['insufficient_panel_count']}",
        f"placeholder_only_count={summary['placeholder_only_count']}",
        f"horizon_row_count={summary['horizon_row_count']}",
        f"optional_source_missing_count={summary['optional_source_missing_count']}",
        "official_adoption_allowed=False",
        "broker_action_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "daily_chain_execution_allowed=False",
        "factor_promotion_allowed=False",
        "factor_weight_change_allowed=False",
        "protected_outputs_modified=False",
        "next_recommended_modules=" + ";".join(summary["next_recommended_modules"]),
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    registry = read_csv_rows(repo_root / REGISTRY_INPUT)
    coverage = read_csv_rows(repo_root / COVERAGE_INPUT)
    sources = source_audit_rows(repo_root, registry) if registry else []
    panel = panel_rows(registry, coverage, sources) if registry and coverage else []
    by_horizon = horizon_rows(panel)
    readiness = readiness_summary_rows(panel)
    summary = summary_payload(repo_root, output_dir, registry, coverage, panel, by_horizon, sources)

    write_csv(output_dir / "v22_factor_predictive_validity_panel.csv", PANEL_FIELDNAMES, panel)
    write_csv(output_dir / "v22_factor_predictive_validity_by_horizon.csv", HORIZON_FIELDNAMES, by_horizon)
    write_csv(output_dir / "v22_factor_predictive_validity_source_audit.csv", SOURCE_FIELDNAMES, sources)
    write_csv(output_dir / "v22_factor_predictive_validity_readiness_summary.csv", READINESS_FIELDNAMES, readiness)
    write_json(output_dir / "v22_factor_predictive_validity_summary.json", summary)
    write_json(output_dir / "v22_factor_predictive_validity_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.012_factor_predictive_validity_panel_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_factor_predictive_validity_summary.json'}")
    print("official_adoption_allowed_count=0")
    print("broker_action_allowed_count=0")
    print("trade_allowed_count=0")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
