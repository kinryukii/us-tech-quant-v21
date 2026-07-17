#!/usr/bin/env python
"""V22.013 factor redundancy cluster audit.

This module clusters registered factors and strategy research items using local
V21/V22 artifacts only. It does not compute unsupported correlations, execute
chains, fetch data, connect to brokers, mutate cache, promote factors, or change
weights.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.013"
MODULE_NAME = "FACTOR_REDUNDANCY_CLUSTER_AUDIT"
STAGE = "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

REGISTRY_INPUT = Path("outputs") / "v22" / "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY" / "v22_factor_evidence_level_registry.csv"
COVERAGE_INPUT = Path("outputs") / "v22" / "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT" / "v22_factor_coverage_audit.csv"
PREDICTIVE_PANEL_INPUT = Path("outputs") / "v22" / "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL" / "v22_factor_predictive_validity_panel.csv"
PREDICTIVE_HORIZON_INPUT = Path("outputs") / "v22" / "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL" / "v22_factor_predictive_validity_by_horizon.csv"

PASS_STATUS = "PASS_V22_013_FACTOR_REDUNDANCY_CLUSTER_AUDIT_READY"
WARN_STATUS = "WARN_V22_013_REDUNDANCY_CLUSTER_AUDIT_READY_WITH_SOURCE_LIMITATIONS"
FAIL_STATUS = "FAIL_V22_013_REDUNDANCY_CLUSTER_AUDIT_MISSING_REQUIRED_INPUTS"
READY_DECISION = "FACTOR_REDUNDANCY_CLUSTER_AUDIT_READY_RESEARCH_ONLY"
FAIL_DECISION = "FACTOR_REDUNDANCY_CLUSTER_AUDIT_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
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
    Path("outputs") / "v21" / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1",
    Path("outputs") / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON",
    Path("outputs") / "v21" / "V21.233_MOOMOO_ONLY_ABCDE_RERUN",
]

MAX_FILES_PER_DIRECTORY = 40
FULL_COUNT_SIZE_LIMIT = 1_500_000

CLUSTER_LABELS = {
    "TREND_MOMENTUM_CLUSTER": "Trend, momentum, moving-average, and breakout overlap cluster.",
    "OSCILLATOR_MEAN_REVERSION_CLUSTER": "Oscillator and mean-reversion overlap cluster.",
    "LIQUIDITY_VOLUME_CLUSTER": "Volume and liquidity-specific cluster.",
    "RISK_VOLATILITY_CLUSTER": "Volatility, risk, and regime cluster.",
    "DATA_QUALITY_CLUSTER": "Data trust and quality governance cluster.",
    "FUNDAMENTAL_QUALITY_CLUSTER": "Fundamental and quality-oriented cluster.",
    "STRATEGY_COMPOSITE_CLUSTER": "Composite strategy and ranking-system cluster.",
    "DRAM_SPECIFIC_CLUSTER": "DRAM-specific research cluster.",
    "ETF_OPTION_PLACEHOLDER_CLUSTER": "ETF option placeholder cluster.",
    "UNKNOWN_REVIEW_CLUSTER": "Review-required fallback cluster.",
}

ITEM_CLUSTER_OVERRIDES = {
    "MOMENTUM": "TREND_MOMENTUM_CLUSTER",
    "RELATIVE_STRENGTH": "TREND_MOMENTUM_CLUSTER",
    "BREAKOUT": "TREND_MOMENTUM_CLUSTER",
    "MA20": "TREND_MOMENTUM_CLUSTER",
    "MA50": "TREND_MOMENTUM_CLUSTER",
    "EMA": "TREND_MOMENTUM_CLUSTER",
    "MACD": "TREND_MOMENTUM_CLUSTER",
    "RSI": "OSCILLATOR_MEAN_REVERSION_CLUSTER",
    "KDJ": "OSCILLATOR_MEAN_REVERSION_CLUSTER",
    "BOLLINGER_BAND_7_LINE": "OSCILLATOR_MEAN_REVERSION_CLUSTER",
    "PULLBACK": "OSCILLATOR_MEAN_REVERSION_CLUSTER",
    "VOLUME": "LIQUIDITY_VOLUME_CLUSTER",
    "VOLATILITY": "RISK_VOLATILITY_CLUSTER",
    "RISK": "RISK_VOLATILITY_CLUSTER",
    "MARKET_REGIME": "RISK_VOLATILITY_CLUSTER",
    "DATA_TRUST": "DATA_QUALITY_CLUSTER",
    "FUNDAMENTAL": "FUNDAMENTAL_QUALITY_CLUSTER",
    "E_R3_QUALITY_RISK_REPAIR_BASE": "FUNDAMENTAL_QUALITY_CLUSTER",
    "A1_CONTROL": "STRATEGY_COMPOSITE_CLUSTER",
    "B_STATIC_MOMENTUM_BLEND": "STRATEGY_COMPOSITE_CLUSTER",
    "C_DYNAMIC_MOMENTUM_BLEND": "STRATEGY_COMPOSITE_CLUSTER",
    "D_WEIGHT_OPTIMIZED_R1": "STRATEGY_COMPOSITE_CLUSTER",
    "E_R1": "STRATEGY_COMPOSITE_CLUSTER",
    "E_R2_CONSERVATIVE_DEFENSIVE_RETURN": "STRATEGY_COMPOSITE_CLUSTER",
    "NEW_FACTOR_LITE": "STRATEGY_COMPOSITE_CLUSTER",
    "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL": "STRATEGY_COMPOSITE_CLUSTER",
    "ABCDE_MOOMOO_ONLY_RERUN": "STRATEGY_COMPOSITE_CLUSTER",
    "DRAM_DAILY_PLAN": "DRAM_SPECIFIC_CLUSTER",
    "DRAM_INTRADAY_TRIGGER": "DRAM_SPECIFIC_CLUSTER",
    "DRAM_NO_TRADE_GATE": "DRAM_SPECIFIC_CLUSTER",
    "DRAM_FORWARD_OUTCOME_TRACKING": "DRAM_SPECIFIC_CLUSTER",
    "ETF_OPTION_LONG_CALL": "ETF_OPTION_PLACEHOLDER_CLUSTER",
    "ETF_OPTION_LONG_PUT": "ETF_OPTION_PLACEHOLDER_CLUSTER",
    "ETF_OPTION_DEBIT_CALL_SPREAD": "ETF_OPTION_PLACEHOLDER_CLUSTER",
    "ETF_OPTION_DEBIT_PUT_SPREAD": "ETF_OPTION_PLACEHOLDER_CLUSTER",
    "ETF_OPTION_LONG_STRADDLE_RESEARCH": "ETF_OPTION_PLACEHOLDER_CLUSTER",
    "ETF_OPTION_LONG_STRANGLE_RESEARCH": "ETF_OPTION_PLACEHOLDER_CLUSTER",
}

HIGH_OVERLAP_PAIRS = [
    ("MOMENTUM", "RELATIVE_STRENGTH"),
    ("MOMENTUM", "BREAKOUT"),
    ("MA20", "MA50"),
    ("MA20", "EMA"),
    ("MA50", "EMA"),
    ("MACD", "MOMENTUM"),
    ("RSI", "KDJ"),
    ("RSI", "BOLLINGER_BAND_7_LINE"),
    ("KDJ", "BOLLINGER_BAND_7_LINE"),
    ("B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND"),
    ("D_WEIGHT_OPTIMIZED_R1", "B_STATIC_MOMENTUM_BLEND"),
    ("NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"),
    ("DRAM_DAILY_PLAN", "DRAM_FORWARD_OUTCOME_TRACKING"),
    ("ETF_OPTION_LONG_CALL", "ETF_OPTION_DEBIT_CALL_SPREAD"),
    ("ETF_OPTION_LONG_PUT", "ETF_OPTION_DEBIT_PUT_SPREAD"),
]

CLUSTER_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "assigned_cluster",
    "assigned_cluster_label",
    "redundancy_risk",
    "likely_duplicate_signal_group",
    "unique_signal_candidate",
    "overlap_drivers",
    "evidence_level_label",
    "coverage_status",
    "predictive_validity_status",
    "computation_basis",
    "correlation_metric_available",
    "pairwise_correlation_available",
    "source_summary_only",
    "adoption_eligible_after_v22_013",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

PAIRWISE_FIELDNAMES = [
    "item_id_a",
    "item_name_a",
    "item_id_b",
    "item_name_b",
    "cluster_a",
    "cluster_b",
    "same_cluster",
    "pairwise_overlap_risk",
    "pairwise_correlation",
    "correlation_available",
    "overlap_reason",
    "recommended_handling",
]

SUMMARY_FIELDNAMES = [
    "cluster_name",
    "cluster_label",
    "item_count",
    "high_redundancy_count",
    "medium_redundancy_count",
    "low_redundancy_count",
    "placeholder_only_count",
    "unique_signal_candidate_count",
    "predictive_ready_count",
    "mixed_signal_count",
    "source_summary_only_count",
    "official_adoption_allowed_count",
    "broker_action_allowed_count",
    "trade_allowed_count",
    "cluster_recommendation",
]

UNIQUE_FIELDNAMES = [
    "item_id",
    "item_name",
    "assigned_cluster",
    "unique_signal_candidate",
    "uniqueness_reason",
    "redundancy_risk",
    "predictive_validity_status",
    "coverage_status",
    "forward_confirmation_required",
    "adoption_eligible_after_v22_013",
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
    "mapped_item_ids",
    "correlation_columns_detected",
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


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.013 output directory must be {expected}, got {output_dir.resolve()}")


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


def bounded_source_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel_path in OPTIONAL_INPUTS:
        path = repo_root / rel_path
        paths.append(path)
        if path.is_dir():
            child_files = [child for child in path.rglob("*") if child.is_file() and child.suffix.lower() in {".csv", ".json", ".txt"}]
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
        if item_type == "TECHNICAL_SUBFACTOR" and ("V21.246" in source_path or "V21.247" in source_path):
            mapped.append(item_id)
        elif item_type == "STRATEGY_RANKING_SYSTEM" and ("V21.233" in source_path or "V21.255" in source_path):
            mapped.append(item_id)
        elif item_type == "FACTOR_FAMILY" and ("V21.246" in source_path or "V21.247" in source_path or "V21.255" in source_path):
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
        "correlation_columns": candidate_columns(headers, ["corr", "correlation", "rho", "redundancy", "overlap"]),
    }


def source_rows(repo_root: Path, registry_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in bounded_source_paths(repo_root):
        exists = path.exists()
        rel_path = path.relative_to(repo_root).as_posix() if exists else path.as_posix()
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
                    "mapped_item_ids": "",
                    "correlation_columns_detected": "",
                    "source_status": "SOURCE_NOT_FOUND",
                    "note": "Optional redundancy source is missing.",
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
                    "mapped_item_ids": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "correlation_columns_detected": "",
                    "source_status": "SOURCE_FOUND",
                    "note": "Directory exists; child files are bounded-scanned separately.",
                }
            )
        else:
            inspected = {"scan_mode": "METADATA_ONLY", "headers": [], "row_count": 0, "correlation_columns": []}
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
                    "mapped_item_ids": ";".join(mapped_item_ids_for_source(rel_path, registry_rows)),
                    "correlation_columns_detected": ";".join(inspected["correlation_columns"]),
                    "source_status": "SOURCE_FOUND",
                    "note": "Bounded local source scan only; correlation is not fabricated.",
                }
            )
    return rows


def cluster_for_item(item: dict[str, str]) -> str:
    item_id = item.get("item_id", "")
    if item_id in ITEM_CLUSTER_OVERRIDES:
        return ITEM_CLUSTER_OVERRIDES[item_id]
    item_type = item.get("item_type", "")
    family = item.get("family", "")
    if item_type == "ETF_OPTION_PLACEHOLDER":
        return "ETF_OPTION_PLACEHOLDER_CLUSTER"
    if item_type == "DRAM_SYSTEM":
        return "DRAM_SPECIFIC_CLUSTER"
    if item_type == "STRATEGY_RANKING_SYSTEM":
        return "STRATEGY_COMPOSITE_CLUSTER"
    if family == "TECHNICAL":
        return "TREND_MOMENTUM_CLUSTER"
    return "UNKNOWN_REVIEW_CLUSTER"


def redundancy_risk(item_id: str, cluster: str) -> str:
    if cluster == "ETF_OPTION_PLACEHOLDER_CLUSTER":
        return "PLACEHOLDER_ONLY"
    high_ids = {
        "MOMENTUM",
        "RELATIVE_STRENGTH",
        "BREAKOUT",
        "MA20",
        "MA50",
        "EMA",
        "MACD",
        "RSI",
        "KDJ",
        "BOLLINGER_BAND_7_LINE",
        "NEW_FACTOR_LITE",
        "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
    }
    if item_id in high_ids:
        return "HIGH"
    if cluster in {"STRATEGY_COMPOSITE_CLUSTER", "DRAM_SPECIFIC_CLUSTER", "RISK_VOLATILITY_CLUSTER"}:
        return "MEDIUM"
    if cluster == "UNKNOWN_REVIEW_CLUSTER":
        return "UNKNOWN_REVIEW_REQUIRED"
    return "LOW"


def cluster_rows(registry: list[dict[str, str]], coverage: dict[str, dict[str, str]], predictive: dict[str, dict[str, str]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    correlation_available = any(str(row.get("correlation_columns_detected", "")) for row in sources)
    rows: list[dict[str, Any]] = []
    for item in registry:
        item_id = item.get("item_id", "")
        cluster = cluster_for_item(item)
        risk = redundancy_risk(item_id, cluster)
        unique_candidate = risk in {"LOW", "MEDIUM"} and cluster not in {"ETF_OPTION_PLACEHOLDER_CLUSTER", "UNKNOWN_REVIEW_CLUSTER"}
        rows.append(
            {
                "item_id": item_id,
                "item_name": item.get("item_name", ""),
                "item_type": item.get("item_type", ""),
                "family": item.get("family", ""),
                "assigned_cluster": cluster,
                "assigned_cluster_label": CLUSTER_LABELS[cluster],
                "redundancy_risk": risk,
                "likely_duplicate_signal_group": cluster,
                "unique_signal_candidate": unique_candidate,
                "overlap_drivers": overlap_drivers(item_id, cluster),
                "evidence_level_label": item.get("evidence_level_label", ""),
                "coverage_status": coverage.get(item_id, {}).get("coverage_status", "COVERAGE_MISSING"),
                "predictive_validity_status": predictive.get(item_id, {}).get("predictive_validity_status", "REVIEW_REQUIRED"),
                "computation_basis": "LOCAL_CORRELATION_COLUMNS_PRESENT" if correlation_available else "STRUCTURAL_SEMANTIC_CLUSTERING",
                "correlation_metric_available": correlation_available,
                "pairwise_correlation_available": False,
                "source_summary_only": not correlation_available,
                "adoption_eligible_after_v22_013": False,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "research_only": True,
                "next_required_validation": "V22.014 multiple-testing false-discovery audit before any role review.",
                "reason": "Read-only redundancy classification; no factor promotion or weight change allowed.",
            }
        )
    return rows


def overlap_drivers(item_id: str, cluster: str) -> str:
    if cluster == "TREND_MOMENTUM_CLUSTER":
        return "trend;momentum;moving_average;breakout"
    if cluster == "OSCILLATOR_MEAN_REVERSION_CLUSTER":
        return "oscillator;mean_reversion;overbought_oversold"
    if cluster == "STRATEGY_COMPOSITE_CLUSTER":
        return "composite_strategy;shared_factor_inputs;multiple_testing"
    if cluster == "ETF_OPTION_PLACEHOLDER_CLUSTER":
        return "option_strategy_placeholder;no_chain_ingestion"
    if item_id == "DATA_TRUST":
        return "data_quality;coverage"
    return cluster.lower()


def pairwise_rows(clustered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["item_id"]: row for row in clustered}
    rows: list[dict[str, Any]] = []
    for item_a, item_b in HIGH_OVERLAP_PAIRS:
        if item_a not in by_id or item_b not in by_id:
            continue
        a = by_id[item_a]
        b = by_id[item_b]
        same_cluster = a["assigned_cluster"] == b["assigned_cluster"]
        rows.append(
            {
                "item_id_a": item_a,
                "item_name_a": a["item_name"],
                "item_id_b": item_b,
                "item_name_b": b["item_name"],
                "cluster_a": a["assigned_cluster"],
                "cluster_b": b["assigned_cluster"],
                "same_cluster": same_cluster,
                "pairwise_overlap_risk": "HIGH" if same_cluster else "MEDIUM",
                "pairwise_correlation": "",
                "correlation_available": False,
                "overlap_reason": "Known structural overlap pair; exact local pairwise correlation unavailable.",
                "recommended_handling": "Treat as redundant until V22.014/V22.015 provide independent confirmation.",
            }
        )
    return rows


def cluster_summary_rows(clustered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster in sorted({row["assigned_cluster"] for row in clustered}):
        group = [row for row in clustered if row["assigned_cluster"] == cluster]
        rows.append(
            {
                "cluster_name": cluster,
                "cluster_label": CLUSTER_LABELS[cluster],
                "item_count": len(group),
                "high_redundancy_count": sum(1 for row in group if row["redundancy_risk"] == "HIGH"),
                "medium_redundancy_count": sum(1 for row in group if row["redundancy_risk"] == "MEDIUM"),
                "low_redundancy_count": sum(1 for row in group if row["redundancy_risk"] == "LOW"),
                "placeholder_only_count": sum(1 for row in group if row["redundancy_risk"] == "PLACEHOLDER_ONLY"),
                "unique_signal_candidate_count": sum(1 for row in group if row["unique_signal_candidate"] is True),
                "predictive_ready_count": sum(1 for row in group if row["predictive_validity_status"] == "PREDICTIVE_READY"),
                "mixed_signal_count": sum(1 for row in group if row["predictive_validity_status"] == "MIXED_SIGNAL"),
                "source_summary_only_count": sum(1 for row in group if row["source_summary_only"] is True),
                "official_adoption_allowed_count": 0,
                "broker_action_allowed_count": 0,
                "trade_allowed_count": 0,
                "cluster_recommendation": "Keep research-only; require redundancy and false-discovery review before any role review.",
            }
        )
    return rows


def unique_rows(clustered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "item_id": row["item_id"],
            "item_name": row["item_name"],
            "assigned_cluster": row["assigned_cluster"],
            "unique_signal_candidate": row["unique_signal_candidate"],
            "uniqueness_reason": "Candidate only if redundancy risk is not high and item is not a placeholder.",
            "redundancy_risk": row["redundancy_risk"],
            "predictive_validity_status": row["predictive_validity_status"],
            "coverage_status": row["coverage_status"],
            "forward_confirmation_required": True,
            "adoption_eligible_after_v22_013": False,
            "reason": row["reason"],
        }
        for row in clustered
        if row["unique_signal_candidate"] is True
    ]


def keyed(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row.get(key, ""): row for row in rows if row.get(key)}


def summary_payload(repo_root: Path, output_dir: Path, registry: list[dict[str, str]], clustered: list[dict[str, Any]], pairwise: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, Any]:
    registry_exists = (repo_root / REGISTRY_INPUT).exists()
    coverage_exists = (repo_root / COVERAGE_INPUT).exists()
    predictive_exists = (repo_root / PREDICTIVE_PANEL_INPUT).exists()
    horizon_exists = (repo_root / PREDICTIVE_HORIZON_INPUT).exists()
    required_ok = registry_exists and coverage_exists and predictive_exists and horizon_exists
    correlation_pair_count = sum(1 for row in pairwise if row["correlation_available"] is True)
    if not required_ok:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif correlation_pair_count == 0:
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
        "predictive_panel_input_exists": predictive_exists,
        "predictive_horizon_input_exists": horizon_exists,
        "registered_item_count": len(registry),
        "clustered_item_count": len(clustered),
        "cluster_count": len({row["assigned_cluster"] for row in clustered}),
        "pairwise_row_count": len(pairwise),
        "high_redundancy_count": sum(1 for row in clustered if row["redundancy_risk"] == "HIGH"),
        "medium_redundancy_count": sum(1 for row in clustered if row["redundancy_risk"] == "MEDIUM"),
        "low_redundancy_count": sum(1 for row in clustered if row["redundancy_risk"] == "LOW"),
        "placeholder_only_count": sum(1 for row in clustered if row["redundancy_risk"] == "PLACEHOLDER_ONLY"),
        "unique_signal_candidate_count": sum(1 for row in clustered if row["unique_signal_candidate"] is True),
        "correlation_available_pair_count": correlation_pair_count,
        "structural_overlap_pair_count": len(pairwise),
        "adoption_eligible_after_v22_013_count": 0,
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
        "allowed_side_effects": ["create_outputs_v22_013_only"],
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
        "V22.013 Factor Redundancy Cluster Audit",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"registered_item_count={summary['registered_item_count']}",
        f"clustered_item_count={summary['clustered_item_count']}",
        f"cluster_count={summary['cluster_count']}",
        f"pairwise_row_count={summary['pairwise_row_count']}",
        f"correlation_available_pair_count={summary['correlation_available_pair_count']}",
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
    sources = source_rows(repo_root, registry) if registry else []
    clustered = cluster_rows(registry, coverage, predictive, sources) if registry and coverage and predictive else []
    pairwise = pairwise_rows(clustered)
    summary = summary_payload(repo_root, output_dir, registry, clustered, pairwise, sources)

    write_csv(output_dir / "v22_factor_redundancy_cluster_audit.csv", CLUSTER_FIELDNAMES, clustered)
    write_csv(output_dir / "v22_factor_redundancy_pairwise_audit.csv", PAIRWISE_FIELDNAMES, pairwise)
    write_csv(output_dir / "v22_factor_cluster_summary.csv", SUMMARY_FIELDNAMES, cluster_summary_rows(clustered))
    write_csv(output_dir / "v22_factor_unique_signal_candidate_summary.csv", UNIQUE_FIELDNAMES, unique_rows(clustered))
    write_csv(output_dir / "v22_factor_redundancy_source_audit.csv", SOURCE_FIELDNAMES, sources)
    write_json(output_dir / "v22_factor_redundancy_cluster_summary.json", summary)
    write_json(output_dir / "v22_factor_redundancy_cluster_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.013_factor_redundancy_cluster_audit_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_factor_redundancy_cluster_summary.json'}")
    print("official_adoption_allowed_count=0")
    print("broker_action_allowed_count=0")
    print("trade_allowed_count=0")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
