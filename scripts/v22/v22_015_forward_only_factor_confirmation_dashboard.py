#!/usr/bin/env python
"""V22.015 forward-only factor confirmation dashboard.

This read-only module consolidates V22.010 through V22.014 outputs and assigns
conservative forward-confirmation readiness labels. It never fetches data,
connects to brokers, mutates caches or historical outputs, promotes factors,
changes weights, or executes any daily chain.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.015"
MODULE_NAME = "FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD"
STAGE = "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

REGISTRY_INPUT = Path("outputs") / "v22" / "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY" / "v22_factor_evidence_level_registry.csv"
COVERAGE_INPUT = Path("outputs") / "v22" / "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT" / "v22_factor_coverage_audit.csv"
PREDICTIVE_PANEL_INPUT = Path("outputs") / "v22" / "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL" / "v22_factor_predictive_validity_panel.csv"
PREDICTIVE_HORIZON_INPUT = Path("outputs") / "v22" / "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL" / "v22_factor_predictive_validity_by_horizon.csv"
REDUNDANCY_INPUT = Path("outputs") / "v22" / "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT" / "v22_factor_redundancy_cluster_audit.csv"
FALSE_DISCOVERY_INPUT = Path("outputs") / "v22" / "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT" / "v22_multiple_testing_false_discovery_audit.csv"

PASS_STATUS = "PASS_V22_015_FORWARD_ONLY_CONFIRMATION_DASHBOARD_READY"
WARN_STATUS = "WARN_V22_015_FORWARD_ONLY_CONFIRMATION_DASHBOARD_READY_WITH_SOURCE_LIMITATIONS"
FAIL_STATUS = "FAIL_V22_015_FORWARD_ONLY_CONFIRMATION_DASHBOARD_MISSING_REQUIRED_INPUTS"
READY_DECISION = "FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD_READY_RESEARCH_ONLY"
FAIL_DECISION = "FORWARD_ONLY_FACTOR_CONFIRMATION_BLOCKED_MISSING_REQUIRED_INPUTS"

FORWARD_HORIZONS = ["5D", "10D", "20D"]

NEXT_RECOMMENDED_MODULES = [
    "V22.020_DRAM_DAILY_DECISION_PANEL_R2",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
    "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY",
    "V22.050_DAILY_RESEARCH_CHAIN_WITH_ETF_OPTIONS_EXTENSION",
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
    Path("outputs") / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON",
    Path("outputs") / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT",
    Path("outputs") / "v21" / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1",
    Path("outputs") / "v21" / "V21.201",
    Path("outputs") / "v21" / "V21.232",
    Path("outputs") / "v21" / "V21.164",
    Path("outputs") / "v21" / "V21.173",
    Path("outputs") / "v21" / "V21.183",
    Path("outputs") / "v21" / "V21.184",
    Path("outputs") / "v21" / "V21.185",
]

MAX_FILES_PER_DIRECTORY = 35
FULL_COUNT_SIZE_LIMIT = 1_500_000

DASHBOARD_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "evidence_level_label",
    "coverage_status",
    "predictive_validity_status",
    "assigned_cluster",
    "redundancy_risk",
    "false_discovery_risk",
    "multiple_testing_adjustment_status",
    "forward_confirmation_status",
    "best_forward_horizon_confirmed",
    "forward_5d_status",
    "forward_10d_status",
    "forward_20d_status",
    "matured_forward_observation_count_estimate",
    "supportive_forward_observation_count_estimate",
    "forward_source_available",
    "historical_only_flag",
    "source_summary_only_flag",
    "placeholder_only_flag",
    "primary_blocker",
    "secondary_blockers",
    "adoption_eligible_after_v22_015",
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
    "forward_confirmation_status",
    "matured_observation_count_estimate",
    "supportive_observation_count_estimate",
    "forward_metric_available",
    "proxy_metric_available",
    "source_path",
    "source_metric_name",
    "source_quality",
    "blocker",
    "reason",
]

BLOCKER_FIELDNAMES = [
    "item_id",
    "item_name",
    "blocker_type",
    "blocker_severity",
    "blocker_source",
    "blocker_reason",
    "recommended_next_step",
]

GROUP_FIELDNAMES = [
    "group_name",
    "item_count",
    "forward_confirmed_count",
    "forward_partial_count",
    "forward_pending_maturity_count",
    "historical_only_count",
    "source_summary_only_count",
    "blocked_by_coverage_count",
    "blocked_by_false_discovery_count",
    "blocked_by_redundancy_count",
    "placeholder_only_count",
    "review_required_count",
    "adoption_eligible_after_v22_015_count",
    "official_adoption_allowed_count",
    "broker_action_allowed_count",
    "trade_allowed_count",
    "group_recommendation",
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
    "forward_horizon_columns_detected",
    "forward_return_columns_detected",
    "maturity_columns_detected",
    "mapped_item_ids",
    "source_status",
    "note",
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


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def keyed(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.015 output directory must be {expected}, got {output_dir.resolve()}")


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
    return [column for column in columns if any(token in column.lower() for token in tokens)]


def optional_matches(repo_root: Path, rel_path: Path) -> list[Path]:
    direct = repo_root / rel_path
    if direct.exists():
        return [direct]
    parent = direct.parent
    prefix = direct.name
    if not parent.exists():
        return [direct]
    matches = [child for child in parent.iterdir() if child.name.startswith(prefix)]
    return sorted(matches, key=lambda item: item.as_posix().lower()) or [direct]


def bounded_source_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel_path in OPTIONAL_INPUTS:
        for path in optional_matches(repo_root, rel_path):
            paths.append(path)
            if path.is_dir():
                child_files = [child for child in path.rglob("*") if child.is_file() and child.suffix.lower() in {".csv", ".json", ".txt"}]
                paths.extend(sorted(child_files, key=lambda item: item.as_posix().lower())[:MAX_FILES_PER_DIRECTORY])
    deduped: dict[str, Path] = {}
    for path in paths:
        deduped[path.resolve().as_posix()] = path
    return list(deduped.values())


def mapped_item_ids_for_source(source_path: str, registry_rows: list[dict[str, str]]) -> list[str]:
    lower = source_path.lower()
    mapped: list[str] = []
    for item in registry_rows:
        item_id = item.get("item_id", "")
        item_type = item.get("item_type", "")
        family = item.get("family", "")
        if item_id.lower() in lower:
            mapped.append(item_id)
        elif item_type == "TECHNICAL_SUBFACTOR" and ("technical" in lower or "subfactor" in lower or "v21.246" in lower or "v21.247" in lower):
            mapped.append(item_id)
        elif family == "DRAM" and ("dram" in lower or "v21.183" in lower or "v21.184" in lower or "v21.185" in lower or "v21.201" in lower or "v21.232" in lower):
            mapped.append(item_id)
        elif item_type == "STRATEGY_RANKING_SYSTEM" and ("strategy" in lower or "weight" in lower or "v21.255" in lower):
            mapped.append(item_id)
    return sorted(set(mapped))


def inspect_csv_file(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    scan_mode = "FULL_SHALLOW" if size <= FULL_COUNT_SIZE_LIMIT else "HEADER_ONLY_OR_SAMPLED"
    headers: list[str] = []
    row_count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            for _row in reader:
                row_count += 1
                if scan_mode == "HEADER_ONLY_OR_SAMPLED" and row_count >= 500:
                    break
    except (OSError, UnicodeError, csv.Error):
        scan_mode = "READ_ERROR"
    return {
        "scan_mode": scan_mode,
        "headers": headers,
        "row_count": row_count,
        "horizon_columns": candidate_columns(headers, ["horizon", "forward_window", "forward_horizon", "holding_period"]),
        "return_columns": candidate_columns(headers, ["forward_return", "return", "outcome", "hit_rate", "win_rate", "pnl"]),
        "maturity_columns": candidate_columns(headers, ["maturity", "matured", "date_count", "observation", "sample_count", "forward_date"]),
    }


def source_rows(repo_root: Path, registry_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in bounded_source_paths(repo_root):
        exists = path.exists()
        rel_path = path.relative_to(repo_root).as_posix() if exists and repo_root in path.resolve().parents else path.as_posix()
        parent = output_name_for_path(path)
        if not exists:
            rows.append(
                {
                    "source_path": rel_path,
                    "exists": False,
                    "file_type": file_type(path),
                    "parent_output_name": parent,
                    "scan_mode": "SOURCE_NOT_FOUND",
                    "file_size_bytes": 0,
                    "header_columns": "",
                    "row_count_estimate": 0,
                    "forward_horizon_columns_detected": "",
                    "forward_return_columns_detected": "",
                    "maturity_columns_detected": "",
                    "mapped_item_ids": "",
                    "source_status": "SOURCE_NOT_FOUND",
                    "note": "Optional forward source is missing; conservative statuses may be used.",
                }
            )
        elif path.is_dir():
            rows.append(
                {
                    "source_path": rel_path,
                    "exists": True,
                    "file_type": "directory",
                    "parent_output_name": parent,
                    "scan_mode": "DIRECTORY_REFERENCE",
                    "file_size_bytes": 0,
                    "header_columns": "",
                    "row_count_estimate": 0,
                    "forward_horizon_columns_detected": "",
                    "forward_return_columns_detected": "",
                    "maturity_columns_detected": "",
                    "mapped_item_ids": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "source_status": "SOURCE_FOUND",
                    "note": "Directory exists; child files are bounded-scanned separately.",
                }
            )
        else:
            inspected = {"scan_mode": "METADATA_ONLY", "headers": [], "row_count": 0, "horizon_columns": [], "return_columns": [], "maturity_columns": []}
            if path.suffix.lower() == ".csv":
                inspected = inspect_csv_file(path)
            rows.append(
                {
                    "source_path": rel_path,
                    "exists": True,
                    "file_type": file_type(path),
                    "parent_output_name": parent,
                    "scan_mode": inspected["scan_mode"],
                    "file_size_bytes": path.stat().st_size,
                    "header_columns": ";".join(inspected["headers"]),
                    "row_count_estimate": inspected["row_count"],
                    "forward_horizon_columns_detected": ";".join(inspected["horizon_columns"]),
                    "forward_return_columns_detected": ";".join(inspected["return_columns"]),
                    "maturity_columns_detected": ";".join(inspected["maturity_columns"]),
                    "mapped_item_ids": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "source_status": "SOURCE_FOUND",
                    "note": "Bounded local forward-source scan only; no unsupported forward statistic is inferred.",
                }
            )
    return rows


def required_flags(repo_root: Path) -> dict[str, bool]:
    return {
        "registry_input_exists": (repo_root / REGISTRY_INPUT).exists(),
        "coverage_input_exists": (repo_root / COVERAGE_INPUT).exists(),
        "predictive_panel_input_exists": (repo_root / PREDICTIVE_PANEL_INPUT).exists(),
        "predictive_horizon_input_exists": (repo_root / PREDICTIVE_HORIZON_INPUT).exists(),
        "redundancy_input_exists": (repo_root / REDUNDANCY_INPUT).exists(),
        "false_discovery_input_exists": (repo_root / FALSE_DISCOVERY_INPUT).exists(),
    }


def horizon_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row.get("item_id", ""), row.get("horizon", "")): row for row in rows if row.get("item_id") and row.get("horizon")}


def int_from_text(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def has_metric(row: dict[str, str]) -> bool:
    metric_fields = ["ic", "rank_ic", "top_minus_bottom_return", "hit_rate", "monotonicity_score"]
    return any(str(row.get(field, "")).strip() for field in metric_fields)


def proxy_available(row: dict[str, str]) -> bool:
    return bool(row) and row.get("computation_status", "") not in {"", "SOURCE_NOT_FOUND"}


def forward_source_available_for_item(item_id: str, family: str, sources: list[dict[str, Any]]) -> bool:
    for row in sources:
        if row.get("exists") is not True:
            continue
        mapped = str(row.get("mapped_item_ids", "")).split(";")
        if item_id in mapped:
            return True
        if family == "DRAM" and "dram" in str(row.get("source_path", "")).lower():
            return True
    return False


def blocker_rows_for_item(
    item: dict[str, str],
    coverage_status: str,
    redundancy_risk: str,
    false_discovery_risk: str,
    multiple_testing_status: str,
    source_summary_only: bool,
    forward_source_available: bool,
) -> list[dict[str, Any]]:
    item_id = item.get("item_id", "")
    item_name = item.get("item_name", item_id)
    item_type = item.get("item_type", "")
    family = item.get("family", "")
    rows: list[dict[str, Any]] = []
    if item_type == "ETF_OPTION_PLACEHOLDER":
        rows.append({"blocker_type": "PLACEHOLDER_ONLY", "blocker_severity": "BLOCKING", "blocker_source": "V22.010/V22.014", "blocker_reason": "ETF option placeholder has no forward evidence yet.", "recommended_next_step": "Create ETF option universe and contract spec registries."})
    if coverage_status not in {"COVERAGE_READY", "V21_OUTPUT_REFERENCE_ONLY", "TEST"} and not (family == "DRAM" and forward_source_available):
        rows.append({"blocker_type": "COVERAGE_MISSING", "blocker_severity": "BLOCKING", "blocker_source": "V22.011", "blocker_reason": f"Coverage status is {coverage_status}.", "recommended_next_step": "Resolve coverage and missingness before forward confirmation."})
    if source_summary_only:
        rows.append({"blocker_type": "SOURCE_SUMMARY_ONLY", "blocker_severity": "MAJOR", "blocker_source": "V22.012/V22.014", "blocker_reason": "Evidence is source-summary-only or lacks usable local forward rows.", "recommended_next_step": "Collect explicit 5D/10D/20D forward-only observations."})
    if false_discovery_risk in {"HIGH", "VERY_HIGH"} or multiple_testing_status == "ADJUSTMENT_REQUIRED_HIGH_RISK":
        rows.append({"blocker_type": "FALSE_DISCOVERY_HIGH", "blocker_severity": "BLOCKING", "blocker_source": "V22.014", "blocker_reason": f"False-discovery risk is {false_discovery_risk}.", "recommended_next_step": "Require forward-only confirmation and multiple-testing controls."})
    if redundancy_risk == "HIGH":
        rows.append({"blocker_type": "REDUNDANCY_HIGH", "blocker_severity": "MAJOR", "blocker_source": "V22.013", "blocker_reason": "High cluster/redundancy overlap.", "recommended_next_step": "Demonstrate incremental signal beyond cluster peers."})
    if item_type != "ETF_OPTION_PLACEHOLDER" and not forward_source_available:
        rows.append({"blocker_type": "FORWARD_MATURITY_MISSING", "blocker_severity": "MAJOR", "blocker_source": "V22.012/local sources", "blocker_reason": "No explicit local forward source was mapped.", "recommended_next_step": "Accumulate 5D/10D/20D forward maturity."})
    return [{"item_id": item_id, "item_name": item_name, **row} for row in rows]


def horizon_rows_for_item(item: dict[str, str], horizons: dict[tuple[str, str], dict[str, str]], item_status: str, primary_blocker: str) -> list[dict[str, Any]]:
    item_id = item.get("item_id", "")
    item_name = item.get("item_name", item_id)
    rows: list[dict[str, Any]] = []
    for horizon in FORWARD_HORIZONS:
        row = horizons.get((item_id, horizon), {})
        matured = max(int_from_text(row.get("date_count", "")), int_from_text(row.get("sample_count", "")))
        metric_available = has_metric(row)
        proxy = proxy_available(row)
        if item_status == "PLACEHOLDER_ONLY":
            horizon_status = "PLACEHOLDER_ONLY"
        elif metric_available:
            horizon_status = "FORWARD_PARTIAL"
        elif proxy:
            horizon_status = "FORWARD_PENDING_MATURITY"
        else:
            horizon_status = "SOURCE_SUMMARY_ONLY"
        rows.append(
            {
                "item_id": item_id,
                "item_name": item_name,
                "horizon": horizon,
                "forward_confirmation_status": horizon_status,
                "matured_observation_count_estimate": matured,
                "supportive_observation_count_estimate": 1 if metric_available and row.get("predictive_validity_status") == "PREDICTIVE_READY" else 0,
                "forward_metric_available": metric_available,
                "proxy_metric_available": proxy,
                "source_path": row.get("source_path", ""),
                "source_metric_name": row.get("source_metric_name", ""),
                "source_quality": row.get("metric_quality", row.get("computation_status", "")),
                "blocker": primary_blocker,
                "reason": "Forward horizon row from V22.012 when available; no unsupported forward statistic is fabricated.",
            }
        )
    return rows


def classify_dashboard_row(
    item: dict[str, str],
    coverage: dict[str, str],
    predictive: dict[str, str],
    redundancy: dict[str, str],
    false_discovery: dict[str, str],
    horizons: dict[tuple[str, str], dict[str, str]],
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    item_id = item.get("item_id", "")
    item_type = item.get("item_type", "")
    family = item.get("family", "")
    coverage_status = coverage.get("coverage_status", item.get("coverage_status", "COVERAGE_MISSING"))
    predictive_status = predictive.get("predictive_validity_status", "REVIEW_REQUIRED")
    assigned_cluster = redundancy.get("assigned_cluster", "UNKNOWN_REVIEW_CLUSTER")
    redundancy_risk = redundancy.get("redundancy_risk", item.get("redundancy_risk", "UNKNOWN_REVIEW_REQUIRED"))
    fdr = false_discovery.get("false_discovery_risk", "REVIEW_REQUIRED")
    mt_status = false_discovery.get("multiple_testing_adjustment_status", "REVIEW_REQUIRED")
    source_summary_only = false_discovery.get("source_summary_only_flag", "").lower() == "true" or predictive.get("computation_status", "") == "SOURCE_SUMMARY_ONLY"
    forward_source = forward_source_available_for_item(item_id, family, sources) or any(proxy_available(horizons.get((item_id, horizon), {})) for horizon in FORWARD_HORIZONS)
    blockers = blocker_rows_for_item(item, coverage_status, redundancy_risk, fdr, mt_status, source_summary_only, forward_source)
    blocker_types = [row["blocker_type"] for row in blockers]

    if item_type == "ETF_OPTION_PLACEHOLDER":
        status = "PLACEHOLDER_ONLY"
        reason = "ETF option placeholder remains research-only with no forward confirmation."
    elif "COVERAGE_MISSING" in blocker_types:
        status = "BLOCKED_BY_COVERAGE"
        reason = "Coverage or missingness blocks forward-only confirmation."
    elif item_id in {"D_WEIGHT_OPTIMIZED_R1", "NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} and "FALSE_DISCOVERY_HIGH" in blocker_types:
        status = "BLOCKED_BY_FALSE_DISCOVERY_RISK"
        reason = "Optimized/new factor item remains blocked by very high false-discovery risk without forward-only confirmation."
    elif "REDUNDANCY_HIGH" in blocker_types and not forward_source:
        status = "BLOCKED_BY_REDUNDANCY"
        reason = "High redundancy and no explicit forward source."
    elif source_summary_only and not forward_source:
        status = "SOURCE_SUMMARY_ONLY"
        reason = "Evidence is source-summary-only; explicit forward rows are not available."
    elif item_id == "A1_CONTROL" or item.get("evidence_level_label", "").startswith("LEVEL_1"):
        status = "HISTORICAL_ONLY"
        reason = "Baseline/control or historical reference only; not an adoption candidate."
    elif predictive_status == "PREDICTIVE_READY" and forward_source and not {"FALSE_DISCOVERY_HIGH", "REDUNDANCY_HIGH"} & set(blocker_types):
        status = "FORWARD_PARTIAL"
        reason = "Local forward-like evidence exists, but V22.015 keeps the item research-only pending maturity."
    elif forward_source:
        status = "FORWARD_PENDING_MATURITY"
        reason = "Forward source or horizon proxy exists but mature forward-only confirmation is incomplete."
    else:
        status = "REVIEW_REQUIRED"
        reason = "Insufficient local evidence to classify forward-only confirmation."

    primary_blocker = blocker_types[0] if blocker_types else ""
    horizon_rows = horizon_rows_for_item(item, horizons, status, primary_blocker)
    mature_total = sum(int(row["matured_observation_count_estimate"]) for row in horizon_rows)
    supportive_total = sum(int(row["supportive_observation_count_estimate"]) for row in horizon_rows)
    confirmed_horizons = [row["horizon"] for row in horizon_rows if row["forward_confirmation_status"] in {"FORWARD_CONFIRMED", "FORWARD_PARTIAL"}]
    dashboard = {
        "item_id": item_id,
        "item_name": item.get("item_name", item_id),
        "item_type": item_type,
        "family": family,
        "evidence_level_label": item.get("evidence_level_label", ""),
        "coverage_status": coverage_status,
        "predictive_validity_status": predictive_status,
        "assigned_cluster": assigned_cluster,
        "redundancy_risk": redundancy_risk,
        "false_discovery_risk": fdr,
        "multiple_testing_adjustment_status": mt_status,
        "forward_confirmation_status": status,
        "best_forward_horizon_confirmed": confirmed_horizons[-1] if confirmed_horizons else "",
        "forward_5d_status": next(row["forward_confirmation_status"] for row in horizon_rows if row["horizon"] == "5D"),
        "forward_10d_status": next(row["forward_confirmation_status"] for row in horizon_rows if row["horizon"] == "10D"),
        "forward_20d_status": next(row["forward_confirmation_status"] for row in horizon_rows if row["horizon"] == "20D"),
        "matured_forward_observation_count_estimate": mature_total,
        "supportive_forward_observation_count_estimate": supportive_total,
        "forward_source_available": forward_source,
        "historical_only_flag": status == "HISTORICAL_ONLY",
        "source_summary_only_flag": source_summary_only or status == "SOURCE_SUMMARY_ONLY",
        "placeholder_only_flag": status == "PLACEHOLDER_ONLY",
        "primary_blocker": primary_blocker,
        "secondary_blockers": ";".join(blocker_types[1:]),
        "adoption_eligible_after_v22_015": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": "Accumulate explicit 5D/10D/20D forward-only observations under frozen V22 research gates.",
        "reason": reason,
    }
    return dashboard, horizon_rows, blockers


def build_rows(
    registry: list[dict[str, str]],
    coverage: dict[str, dict[str, str]],
    predictive: dict[str, dict[str, str]],
    redundancy: dict[str, dict[str, str]],
    false_discovery: dict[str, dict[str, str]],
    horizons: dict[tuple[str, str], dict[str, str]],
    sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dashboard_rows: list[dict[str, Any]] = []
    horizon_rows: list[dict[str, Any]] = []
    blocker_rows: list[dict[str, Any]] = []
    for item in registry:
        row, item_horizons, item_blockers = classify_dashboard_row(
            item,
            coverage.get(item.get("item_id", ""), {}),
            predictive.get(item.get("item_id", ""), {}),
            redundancy.get(item.get("item_id", ""), {}),
            false_discovery.get(item.get("item_id", ""), {}),
            horizons,
            sources,
        )
        dashboard_rows.append(row)
        horizon_rows.extend(item_horizons)
        blocker_rows.extend(item_blockers)
    return dashboard_rows, horizon_rows, blocker_rows


def group_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for family in sorted({row["family"] for row in rows}):
        members = [row for row in rows if row["family"] == family]
        groups.append(
            {
                "group_name": family,
                "item_count": len(members),
                "forward_confirmed_count": sum(1 for row in members if row["forward_confirmation_status"] == "FORWARD_CONFIRMED"),
                "forward_partial_count": sum(1 for row in members if row["forward_confirmation_status"] == "FORWARD_PARTIAL"),
                "forward_pending_maturity_count": sum(1 for row in members if row["forward_confirmation_status"] == "FORWARD_PENDING_MATURITY"),
                "historical_only_count": sum(1 for row in members if row["forward_confirmation_status"] == "HISTORICAL_ONLY"),
                "source_summary_only_count": sum(1 for row in members if row["forward_confirmation_status"] == "SOURCE_SUMMARY_ONLY"),
                "blocked_by_coverage_count": sum(1 for row in members if row["forward_confirmation_status"] == "BLOCKED_BY_COVERAGE"),
                "blocked_by_false_discovery_count": sum(1 for row in members if row["forward_confirmation_status"] == "BLOCKED_BY_FALSE_DISCOVERY_RISK"),
                "blocked_by_redundancy_count": sum(1 for row in members if row["forward_confirmation_status"] == "BLOCKED_BY_REDUNDANCY"),
                "placeholder_only_count": sum(1 for row in members if row["forward_confirmation_status"] == "PLACEHOLDER_ONLY"),
                "review_required_count": sum(1 for row in members if row["forward_confirmation_status"] == "REVIEW_REQUIRED"),
                "adoption_eligible_after_v22_015_count": 0,
                "official_adoption_allowed_count": 0,
                "broker_action_allowed_count": 0,
                "trade_allowed_count": 0,
                "group_recommendation": "Keep research-only; require explicit forward-only maturity and unresolved blocker review.",
            }
        )
    return groups


def summary_payload(
    repo_root: Path,
    output_dir: Path,
    registry: list[dict[str, str]],
    dashboard: list[dict[str, Any]],
    horizon_rows: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    source_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    flags = required_flags(repo_root)
    optional_missing = sum(1 for row in source_audit if row.get("exists") is False)
    source_summary_count = sum(1 for row in dashboard if row.get("source_summary_only_flag") is True)
    if not all(flags.values()) or not dashboard:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif optional_missing or source_summary_count > len(dashboard) // 2:
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
        **flags,
        "registered_item_count": len(registry),
        "evaluated_item_count": len(dashboard),
        "forward_confirmed_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "FORWARD_CONFIRMED"),
        "forward_partial_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "FORWARD_PARTIAL"),
        "forward_pending_maturity_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "FORWARD_PENDING_MATURITY"),
        "historical_only_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "HISTORICAL_ONLY"),
        "source_summary_only_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "SOURCE_SUMMARY_ONLY"),
        "blocked_by_coverage_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "BLOCKED_BY_COVERAGE"),
        "blocked_by_false_discovery_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "BLOCKED_BY_FALSE_DISCOVERY_RISK"),
        "blocked_by_redundancy_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "BLOCKED_BY_REDUNDANCY"),
        "placeholder_only_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "PLACEHOLDER_ONLY"),
        "review_required_count": sum(1 for row in dashboard if row["forward_confirmation_status"] == "REVIEW_REQUIRED"),
        "horizon_row_count": len(horizon_rows),
        "blocker_row_count": len(blockers),
        "source_file_count": len(source_audit),
        "scanned_source_file_count": sum(1 for row in source_audit if row.get("exists") is True),
        "optional_source_missing_count": optional_missing,
        "adoption_eligible_after_v22_015_count": 0,
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
        "allowed_side_effects": ["create_outputs_v22_015_only"],
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
        "V22.015 Forward-Only Factor Confirmation Dashboard",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"registered_item_count={summary['registered_item_count']}",
        f"evaluated_item_count={summary['evaluated_item_count']}",
        f"forward_pending_maturity_count={summary['forward_pending_maturity_count']}",
        f"blocked_by_false_discovery_count={summary['blocked_by_false_discovery_count']}",
        f"placeholder_only_count={summary['placeholder_only_count']}",
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
    coverage = keyed(read_csv_rows(repo_root / COVERAGE_INPUT), "item_id")
    predictive = keyed(read_csv_rows(repo_root / PREDICTIVE_PANEL_INPUT), "item_id")
    horizon_rows_raw = read_csv_rows(repo_root / PREDICTIVE_HORIZON_INPUT)
    redundancy = keyed(read_csv_rows(repo_root / REDUNDANCY_INPUT), "item_id")
    false_discovery = keyed(read_csv_rows(repo_root / FALSE_DISCOVERY_INPUT), "item_id")
    source_audit = source_rows(repo_root, registry) if registry else []
    dashboard: list[dict[str, Any]] = []
    by_horizon: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    if all(required_flags(repo_root).values()):
        dashboard, by_horizon, blockers = build_rows(registry, coverage, predictive, redundancy, false_discovery, horizon_index(horizon_rows_raw), source_audit)
    groups = group_summary_rows(dashboard)
    summary = summary_payload(repo_root, output_dir, registry, dashboard, by_horizon, blockers, source_audit)

    write_csv(output_dir / "v22_forward_only_factor_confirmation_dashboard.csv", DASHBOARD_FIELDNAMES, dashboard)
    write_csv(output_dir / "v22_forward_confirmation_by_horizon.csv", HORIZON_FIELDNAMES, by_horizon)
    write_csv(output_dir / "v22_forward_confirmation_blocker_audit.csv", BLOCKER_FIELDNAMES, blockers)
    write_csv(output_dir / "v22_forward_confirmation_group_summary.csv", GROUP_FIELDNAMES, groups)
    write_csv(output_dir / "v22_forward_confirmation_source_audit.csv", SOURCE_FIELDNAMES, source_audit)
    write_json(output_dir / "v22_forward_only_factor_confirmation_summary.json", summary)
    write_json(output_dir / "v22_forward_only_factor_confirmation_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.015_forward_only_factor_confirmation_dashboard_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_forward_only_factor_confirmation_summary.json'}")
    print("official_adoption_allowed_count=0")
    print("broker_action_allowed_count=0")
    print("trade_allowed_count=0")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
