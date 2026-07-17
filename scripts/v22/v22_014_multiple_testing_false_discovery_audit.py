#!/usr/bin/env python
"""V22.014 multiple-testing and false-discovery audit.

Read-only audit of research overfit, data-snooping, and false-discovery risk
across registered V21/V22 research items. This module uses existing local
outputs only and never fetches data, connects to brokers, mutates caches,
promotes factors, changes weights, or executes any daily chain.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.014"
MODULE_NAME = "MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT"
STAGE = "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

REGISTRY_INPUT = Path("outputs") / "v22" / "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY" / "v22_factor_evidence_level_registry.csv"
COVERAGE_INPUT = Path("outputs") / "v22" / "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT" / "v22_factor_coverage_audit.csv"
PREDICTIVE_PANEL_INPUT = Path("outputs") / "v22" / "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL" / "v22_factor_predictive_validity_panel.csv"
PREDICTIVE_HORIZON_INPUT = Path("outputs") / "v22" / "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL" / "v22_factor_predictive_validity_by_horizon.csv"
REDUNDANCY_CLUSTER_INPUT = Path("outputs") / "v22" / "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT" / "v22_factor_redundancy_cluster_audit.csv"
REDUNDANCY_PAIRWISE_INPUT = Path("outputs") / "v22" / "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT" / "v22_factor_redundancy_pairwise_audit.csv"

PASS_STATUS = "PASS_V22_014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT_READY"
WARN_STATUS = "WARN_V22_014_FALSE_DISCOVERY_AUDIT_READY_WITH_SOURCE_LIMITATIONS"
FAIL_STATUS = "FAIL_V22_014_FALSE_DISCOVERY_AUDIT_MISSING_REQUIRED_INPUTS"
READY_DECISION = "MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT_READY_RESEARCH_ONLY"
FAIL_DECISION = "MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD",
    "V22.020_DRAM_DAILY_DECISION_PANEL_R2",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
    "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY",
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
    Path("outputs") / "v21" / "V21.233_MOOMOO_ONLY_ABCDE_RERUN",
    Path("outputs") / "v21" / "V21.060",
    Path("outputs") / "v21" / "V21.164",
    Path("outputs") / "v21" / "V21.173",
    Path("outputs") / "v21" / "V21.197",
    Path("outputs") / "v21" / "V21.201",
    Path("outputs") / "v21" / "V21.246",
]

MAX_FILES_PER_DIRECTORY = 35
FULL_COUNT_SIZE_LIMIT = 1_500_000

AUDIT_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "evidence_level_label",
    "coverage_status",
    "predictive_validity_status",
    "assigned_cluster",
    "redundancy_risk",
    "estimated_related_variant_count",
    "tested_horizon_count",
    "tested_regime_or_period_split_count",
    "tested_weight_or_strategy_variant_count",
    "source_summary_only_flag",
    "forward_confirmation_available",
    "selected_after_performance_flag",
    "false_discovery_risk",
    "multiple_testing_adjustment_status",
    "effective_evidence_after_false_discovery_penalty",
    "adoption_eligible_after_v22_014",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

GROUP_FIELDNAMES = [
    "group_name",
    "group_type",
    "item_count",
    "estimated_variant_count",
    "high_or_very_high_fdr_count",
    "medium_fdr_count",
    "low_fdr_count",
    "placeholder_only_count",
    "source_limited_count",
    "forward_confirmed_count",
    "adjustment_required_count",
    "official_adoption_allowed_count",
    "broker_action_allowed_count",
    "trade_allowed_count",
    "group_recommendation",
]

VARIANT_FIELDNAMES = [
    "source_family_or_module",
    "source_path",
    "exists",
    "detected_variant_type",
    "estimated_variant_count",
    "detected_horizon_count",
    "detected_period_split_count",
    "detected_strategy_count",
    "detected_factor_count",
    "scan_mode",
    "source_status",
    "note",
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
    "variant_columns_detected",
    "horizon_columns_detected",
    "period_split_columns_detected",
    "strategy_columns_detected",
    "factor_columns_detected",
    "mapped_item_ids",
    "source_status",
    "note",
]

TECHNICAL_IDS = {
    "RSI",
    "KDJ",
    "MACD",
    "BOLLINGER_BAND_7_LINE",
    "MA20",
    "MA50",
    "EMA",
    "VOLUME",
    "VOLATILITY",
    "MOMENTUM",
    "RELATIVE_STRENGTH",
    "BREAKOUT",
    "PULLBACK",
}


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
        raise ValueError(f"V22.014 output directory must be {expected}, got {output_dir.resolve()}")


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
        elif item_type == "TECHNICAL_SUBFACTOR" and ("technical" in lower or "subfactor" in lower or "v21.247" in lower):
            mapped.append(item_id)
        elif item_type == "STRATEGY_RANKING_SYSTEM" and ("strategy" in lower or "weight" in lower or "abcde" in lower or "v21.255" in lower):
            mapped.append(item_id)
        elif family == "DRAM" and ("dram" in lower or "v21.201" in lower):
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
        "variant_columns": candidate_columns(headers, ["variant", "trial", "grid", "parameter", "topn", "window"]),
        "horizon_columns": candidate_columns(headers, ["horizon", "forward_window", "lookahead"]),
        "period_columns": candidate_columns(headers, ["period", "regime", "pre_", "post_", "split", "window"]),
        "strategy_columns": candidate_columns(headers, ["strategy", "baseline", "rerun"]),
        "factor_columns": candidate_columns(headers, ["factor", "subfactor", "signal", "score"]),
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
                    "variant_columns_detected": "",
                    "horizon_columns_detected": "",
                    "period_split_columns_detected": "",
                    "strategy_columns_detected": "",
                    "factor_columns_detected": "",
                    "mapped_item_ids": "",
                    "source_status": "SOURCE_NOT_FOUND",
                    "note": "Optional source is missing; source-summary-only defaults may be used.",
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
                    "variant_columns_detected": "",
                    "horizon_columns_detected": "",
                    "period_split_columns_detected": "",
                    "strategy_columns_detected": "",
                    "factor_columns_detected": "",
                    "mapped_item_ids": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "source_status": "SOURCE_FOUND",
                    "note": "Directory exists; child files are bounded-scanned separately.",
                }
            )
        else:
            inspected = {
                "scan_mode": "METADATA_ONLY",
                "headers": [],
                "row_count": 0,
                "variant_columns": [],
                "horizon_columns": [],
                "period_columns": [],
                "strategy_columns": [],
                "factor_columns": [],
            }
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
                    "variant_columns_detected": ";".join(inspected["variant_columns"]),
                    "horizon_columns_detected": ";".join(inspected["horizon_columns"]),
                    "period_split_columns_detected": ";".join(inspected["period_columns"]),
                    "strategy_columns_detected": ";".join(inspected["strategy_columns"]),
                    "factor_columns_detected": ";".join(inspected["factor_columns"]),
                    "mapped_item_ids": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "source_status": "SOURCE_FOUND",
                    "note": "Bounded local source scan only; exact p-values/q-values are not inferred.",
                }
            )
    return rows


def unique_horizon_counts(horizon_rows: list[dict[str, str]]) -> dict[str, int]:
    values: dict[str, set[str]] = {}
    for row in horizon_rows:
        item_id = row.get("item_id", "")
        horizon = row.get("horizon", "")
        if item_id and horizon:
            values.setdefault(item_id, set()).add(horizon)
    return {item_id: len(horizons) for item_id, horizons in values.items()}


def source_signal_counts(source_audit: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"variant": 0, "horizon": 0, "period": 0, "strategy": 0, "factor": 0}
    for row in source_audit:
        if row.get("exists") is not True:
            continue
        counts["variant"] += len(str(row.get("variant_columns_detected", "")).split(";")) if row.get("variant_columns_detected") else 0
        counts["horizon"] += len(str(row.get("horizon_columns_detected", "")).split(";")) if row.get("horizon_columns_detected") else 0
        counts["period"] += len(str(row.get("period_split_columns_detected", "")).split(";")) if row.get("period_split_columns_detected") else 0
        counts["strategy"] += len(str(row.get("strategy_columns_detected", "")).split(";")) if row.get("strategy_columns_detected") else 0
        counts["factor"] += len(str(row.get("factor_columns_detected", "")).split(";")) if row.get("factor_columns_detected") else 0
    return counts


def variant_audit_rows(source_audit: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in source_audit:
        variant_cols = str(row.get("variant_columns_detected", ""))
        horizon_cols = str(row.get("horizon_columns_detected", ""))
        period_cols = str(row.get("period_split_columns_detected", ""))
        strategy_cols = str(row.get("strategy_columns_detected", ""))
        factor_cols = str(row.get("factor_columns_detected", ""))
        detected_variant_count = sum(1 for value in [variant_cols, horizon_cols, period_cols, strategy_cols, factor_cols] if value)
        estimated = max(1, detected_variant_count)
        if row.get("exists") is not True:
            estimated = 0
        rows.append(
            {
                "source_family_or_module": row.get("parent_output_name", ""),
                "source_path": row.get("source_path", ""),
                "exists": row.get("exists", False),
                "detected_variant_type": "HEADER_VARIANT_SIGNALS" if detected_variant_count else "SOURCE_SUMMARY_ONLY",
                "estimated_variant_count": estimated,
                "detected_horizon_count": len(horizon_cols.split(";")) if horizon_cols else 0,
                "detected_period_split_count": len(period_cols.split(";")) if period_cols else 0,
                "detected_strategy_count": len(strategy_cols.split(";")) if strategy_cols else 0,
                "detected_factor_count": len(factor_cols.split(";")) if factor_cols else 0,
                "scan_mode": row.get("scan_mode", ""),
                "source_status": row.get("source_status", ""),
                "note": "Header/filename variant estimate; no exact multiple-testing statistic is fabricated.",
            }
        )
    return rows


def forward_confirmation_available(item: dict[str, str], predictive_row: dict[str, str]) -> bool:
    text = " ".join(
        [
            item.get("forward_maturity_status", ""),
            item.get("regime_robustness_status", ""),
            predictive_row.get("predictive_validity_status", ""),
            predictive_row.get("computation_status", ""),
        ]
    ).upper()
    return "FORWARD_CONFIRMED" in text or "FORWARD_ONLY_CONFIRMED" in text


def selected_after_performance(item_id: str, item_type: str) -> bool:
    if item_id in {"A1_CONTROL"}:
        return False
    if item_id in {"D_WEIGHT_OPTIMIZED_R1", "NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"}:
        return True
    return item_type in {"STRATEGY_RANKING_SYSTEM", "TECHNICAL_SUBFACTOR"}


def estimates_for_item(item: dict[str, str], horizon_count: int, source_counts: dict[str, int]) -> dict[str, Any]:
    item_id = item.get("item_id", "")
    item_type = item.get("item_type", "")
    family = item.get("family", "")
    if item_type == "ETF_OPTION_PLACEHOLDER":
        return {"variant": 0, "horizon": 0, "period": 0, "strategy": 0, "source_summary_only": True}
    horizon = max(1, horizon_count)
    period = 1
    strategy = 1
    variant = 1
    source_summary_only = source_counts["variant"] == 0 and source_counts["strategy"] == 0 and source_counts["factor"] == 0
    if item_id == "A1_CONTROL":
        variant, strategy = 1, 1
    elif item_id == "D_WEIGHT_OPTIMIZED_R1":
        variant = max(8, source_counts["variant"] + source_counts["strategy"])
        strategy = max(4, source_counts["strategy"])
    elif item_id in {"NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"}:
        variant = max(6, source_counts["variant"] + 2)
        strategy = max(3, source_counts["strategy"])
    elif item_type == "TECHNICAL_SUBFACTOR" or item_id in TECHNICAL_IDS:
        variant = max(3, source_counts["factor"] // 4)
        period = max(2, source_counts["period"])
    elif item_type == "STRATEGY_RANKING_SYSTEM":
        variant = max(4, source_counts["strategy"])
        strategy = max(2, source_counts["strategy"])
    elif family == "DRAM":
        variant = max(2, source_counts["strategy"] // 2)
    else:
        variant = max(1, source_counts["factor"] // 5)
    return {"variant": variant, "horizon": horizon, "period": period, "strategy": strategy, "source_summary_only": source_summary_only}


def classify_risk(item: dict[str, str], redundancy: str, predictive_status: str, estimates: dict[str, Any], forward_ok: bool, selected_after_perf: bool) -> tuple[str, str, str, str]:
    item_id = item.get("item_id", "")
    item_type = item.get("item_type", "")
    if item_type == "ETF_OPTION_PLACEHOLDER":
        return (
            "PLACEHOLDER_ONLY",
            "PLACEHOLDER_ONLY",
            "NO_EMPIRICAL_EVIDENCE_PLACEHOLDER_ONLY",
            "ETF option placeholder has no evidence yet; keep out of adoption and trading.",
        )
    if item_id == "A1_CONTROL":
        return (
            "LOW",
            "ADJUSTMENT_NOT_NEEDED_CONTROL_OR_BASELINE",
            "BASELINE_CONTROL_REFERENCE_ONLY",
            "Baseline/control reference; no selection uplift is granted.",
        )
    high_trigger = (
        estimates["variant"] >= 6
        or estimates["horizon"] >= 4
        or estimates["strategy"] >= 4
        or redundancy == "HIGH"
        or selected_after_perf
    )
    very_high_trigger = estimates["variant"] >= 10 or (selected_after_perf and redundancy == "HIGH")
    if item_id in {"NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} and not forward_ok:
        very_high_trigger = True
    if item_id == "D_WEIGHT_OPTIMIZED_R1" and not forward_ok:
        high_trigger = True
    if estimates["source_summary_only"]:
        if high_trigger or very_high_trigger:
            risk = "VERY_HIGH" if very_high_trigger else "HIGH"
            return (risk, "SOURCE_LIMITED_CANNOT_ADJUST", "SOURCE_LIMITED_RESEARCH_ONLY", "Source-limited variant estimate with elevated multiple-testing risk.")
        return ("MEDIUM", "SOURCE_LIMITED_CANNOT_ADJUST", "SOURCE_LIMITED_RESEARCH_ONLY", "Source-limited estimate; require explicit multiple-testing plan.")
    if very_high_trigger:
        return ("VERY_HIGH", "ADJUSTMENT_REQUIRED_HIGH_RISK", "DOWNGRADED_PENDING_FORWARD_CONFIRMATION", "Multiple testing and selection-after-performance risk are very high.")
    if high_trigger:
        return ("HIGH", "ADJUSTMENT_REQUIRED_HIGH_RISK", "DOWNGRADED_PENDING_FORWARD_CONFIRMATION", "Multiple testing adjustment required before any role review.")
    if item_type == "TECHNICAL_SUBFACTOR" or redundancy == "MEDIUM" or predictive_status == "MIXED_SIGNAL":
        return ("MEDIUM", "ADJUSTMENT_REQUIRED", "RESEARCH_ONLY_WITH_FALSE_DISCOVERY_PENALTY", "Moderate false-discovery risk from horizons, redundancy, or mixed signal.")
    return ("LOW", "ADJUSTMENT_REQUIRED", "RESEARCH_ONLY_WITH_FALSE_DISCOVERY_PENALTY", "Low categorical risk, but still research-only under V22 policy.")


def audit_rows(
    registry: list[dict[str, str]],
    coverage: dict[str, dict[str, str]],
    predictive: dict[str, dict[str, str]],
    redundancy: dict[str, dict[str, str]],
    horizon_counts: dict[str, int],
    source_counts: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in registry:
        item_id = item.get("item_id", "")
        item_type = item.get("item_type", "")
        coverage_status = coverage.get(item_id, {}).get("coverage_status", item.get("coverage_status", "COVERAGE_MISSING"))
        predictive_row = predictive.get(item_id, {})
        predictive_status = predictive_row.get("predictive_validity_status", "REVIEW_REQUIRED")
        red_row = redundancy.get(item_id, {})
        assigned_cluster = red_row.get("assigned_cluster", "UNKNOWN_REVIEW_CLUSTER")
        redundancy_risk = red_row.get("redundancy_risk", item.get("redundancy_risk", "UNKNOWN_REVIEW_REQUIRED"))
        estimates = estimates_for_item(item, horizon_counts.get(item_id, 0), source_counts)
        forward_ok = forward_confirmation_available(item, predictive_row)
        selected_after_perf = selected_after_performance(item_id, item_type)
        risk, adjustment, effective_evidence, risk_reason = classify_risk(item, redundancy_risk, predictive_status, estimates, forward_ok, selected_after_perf)
        rows.append(
            {
                "item_id": item_id,
                "item_name": item.get("item_name", item_id),
                "item_type": item_type,
                "family": item.get("family", ""),
                "evidence_level_label": item.get("evidence_level_label", ""),
                "coverage_status": coverage_status,
                "predictive_validity_status": predictive_status,
                "assigned_cluster": assigned_cluster,
                "redundancy_risk": redundancy_risk,
                "estimated_related_variant_count": estimates["variant"],
                "tested_horizon_count": estimates["horizon"],
                "tested_regime_or_period_split_count": estimates["period"],
                "tested_weight_or_strategy_variant_count": estimates["strategy"],
                "source_summary_only_flag": estimates["source_summary_only"],
                "forward_confirmation_available": forward_ok,
                "selected_after_performance_flag": selected_after_perf,
                "false_discovery_risk": risk,
                "multiple_testing_adjustment_status": adjustment,
                "effective_evidence_after_false_discovery_penalty": effective_evidence,
                "adoption_eligible_after_v22_014": False,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "research_only": True,
                "next_required_validation": "V22.015 forward-only confirmation before any adoption role review.",
                "reason": risk_reason,
            }
        )
    return rows


def group_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    keys = sorted({row["family"] for row in rows} | {row["assigned_cluster"] for row in rows})
    for key in keys:
        group_type = "FAMILY" if any(row["family"] == key for row in rows) else "CLUSTER"
        members = [row for row in rows if row["family"] == key] if group_type == "FAMILY" else [row for row in rows if row["assigned_cluster"] == key]
        groups.append(
            {
                "group_name": key,
                "group_type": group_type,
                "item_count": len(members),
                "estimated_variant_count": sum(int(row["estimated_related_variant_count"]) for row in members),
                "high_or_very_high_fdr_count": sum(1 for row in members if row["false_discovery_risk"] in {"HIGH", "VERY_HIGH"}),
                "medium_fdr_count": sum(1 for row in members if row["false_discovery_risk"] == "MEDIUM"),
                "low_fdr_count": sum(1 for row in members if row["false_discovery_risk"] == "LOW"),
                "placeholder_only_count": sum(1 for row in members if row["false_discovery_risk"] == "PLACEHOLDER_ONLY"),
                "source_limited_count": sum(1 for row in members if row["multiple_testing_adjustment_status"] == "SOURCE_LIMITED_CANNOT_ADJUST"),
                "forward_confirmed_count": sum(1 for row in members if row["forward_confirmation_available"] is True),
                "adjustment_required_count": sum(1 for row in members if str(row["multiple_testing_adjustment_status"]).startswith("ADJUSTMENT_REQUIRED")),
                "official_adoption_allowed_count": 0,
                "broker_action_allowed_count": 0,
                "trade_allowed_count": 0,
                "group_recommendation": "Keep research-only; require multiple-testing controls and forward-only confirmation.",
            }
        )
    return groups


def required_flags(repo_root: Path) -> dict[str, bool]:
    return {
        "registry_input_exists": (repo_root / REGISTRY_INPUT).exists(),
        "coverage_input_exists": (repo_root / COVERAGE_INPUT).exists(),
        "predictive_panel_input_exists": (repo_root / PREDICTIVE_PANEL_INPUT).exists(),
        "predictive_horizon_input_exists": (repo_root / PREDICTIVE_HORIZON_INPUT).exists(),
        "redundancy_cluster_input_exists": (repo_root / REDUNDANCY_CLUSTER_INPUT).exists(),
        "redundancy_pairwise_input_exists": (repo_root / REDUNDANCY_PAIRWISE_INPUT).exists(),
    }


def summary_payload(repo_root: Path, output_dir: Path, registry: list[dict[str, str]], audited: list[dict[str, Any]], groups: list[dict[str, Any]], variants: list[dict[str, Any]], source_audit: list[dict[str, Any]]) -> dict[str, Any]:
    flags = required_flags(repo_root)
    required_ok = all(flags.values())
    source_summary_count = sum(1 for row in audited if row.get("source_summary_only_flag") is True)
    optional_missing = sum(1 for row in source_audit if row.get("exists") is False)
    if not required_ok:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif not audited:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif optional_missing or source_summary_count > len(audited) // 2:
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
        "audited_item_count": len(audited),
        "group_summary_count": len(groups),
        "variant_audit_row_count": len(variants),
        "false_discovery_low_count": sum(1 for row in audited if row["false_discovery_risk"] == "LOW"),
        "false_discovery_medium_count": sum(1 for row in audited if row["false_discovery_risk"] == "MEDIUM"),
        "false_discovery_high_count": sum(1 for row in audited if row["false_discovery_risk"] == "HIGH"),
        "false_discovery_very_high_count": sum(1 for row in audited if row["false_discovery_risk"] == "VERY_HIGH"),
        "placeholder_only_count": sum(1 for row in audited if row["false_discovery_risk"] == "PLACEHOLDER_ONLY"),
        "adjustment_required_count": sum(1 for row in audited if row["multiple_testing_adjustment_status"] == "ADJUSTMENT_REQUIRED"),
        "adjustment_required_high_risk_count": sum(1 for row in audited if row["multiple_testing_adjustment_status"] == "ADJUSTMENT_REQUIRED_HIGH_RISK"),
        "source_limited_cannot_adjust_count": sum(1 for row in audited if row["multiple_testing_adjustment_status"] == "SOURCE_LIMITED_CANNOT_ADJUST"),
        "adoption_eligible_after_v22_014_count": 0,
        "official_adoption_allowed_count": 0,
        "broker_action_allowed_count": 0,
        "trade_allowed_count": 0,
        "optional_source_missing_count": optional_missing,
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        "output_dir": str(output_dir),
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_014_only"],
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
        "V22.014 Multiple-Testing False-Discovery Audit",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"registered_item_count={summary['registered_item_count']}",
        f"audited_item_count={summary['audited_item_count']}",
        f"false_discovery_high_count={summary['false_discovery_high_count']}",
        f"false_discovery_very_high_count={summary['false_discovery_very_high_count']}",
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

    flags = required_flags(repo_root)
    registry = read_csv_rows(repo_root / REGISTRY_INPUT)
    coverage = keyed(read_csv_rows(repo_root / COVERAGE_INPUT), "item_id")
    predictive = keyed(read_csv_rows(repo_root / PREDICTIVE_PANEL_INPUT), "item_id")
    horizons = read_csv_rows(repo_root / PREDICTIVE_HORIZON_INPUT)
    redundancy = keyed(read_csv_rows(repo_root / REDUNDANCY_CLUSTER_INPUT), "item_id")
    source_audit = source_rows(repo_root, registry) if registry else []
    variant_rows = variant_audit_rows(source_audit)
    source_counts = source_signal_counts(source_audit)
    audited: list[dict[str, Any]] = []
    if all(flags.values()):
        audited = audit_rows(registry, coverage, predictive, redundancy, unique_horizon_counts(horizons), source_counts)
    groups = group_summary_rows(audited)
    summary = summary_payload(repo_root, output_dir, registry, audited, groups, variant_rows, source_audit)

    write_csv(output_dir / "v22_multiple_testing_false_discovery_audit.csv", AUDIT_FIELDNAMES, audited)
    write_csv(output_dir / "v22_false_discovery_group_summary.csv", GROUP_FIELDNAMES, groups)
    write_csv(output_dir / "v22_research_variant_count_audit.csv", VARIANT_FIELDNAMES, variant_rows)
    write_csv(output_dir / "v22_false_discovery_source_audit.csv", SOURCE_FIELDNAMES, source_audit)
    write_json(output_dir / "v22_multiple_testing_false_discovery_summary.json", summary)
    write_json(output_dir / "v22_multiple_testing_false_discovery_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.014_multiple_testing_false_discovery_audit_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_multiple_testing_false_discovery_summary.json'}")
    print("official_adoption_allowed_count=0")
    print("broker_action_allowed_count=0")
    print("trade_allowed_count=0")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
