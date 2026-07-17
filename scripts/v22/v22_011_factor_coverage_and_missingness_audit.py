#!/usr/bin/env python
"""V22.011 factor coverage and missingness audit.

This module reads the local V22.010 evidence registry and performs a bounded,
read-only audit of local source coverage. It does not execute chains, fetch
market data, connect to brokers, fetch option chains, mutate cache, or modify
historical outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.011"
MODULE_NAME = "FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT"
STAGE = "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

REGISTRY_INPUT = Path("outputs") / "v22" / "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY" / "v22_factor_evidence_level_registry.csv"

PASS_STATUS = "PASS_V22_011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT_READY"
WARN_STATUS = "WARN_V22_011_FACTOR_COVERAGE_AUDIT_READY_WITH_MISSING_OPTIONAL_SOURCES"
FAIL_STATUS = "FAIL_V22_011_FACTOR_COVERAGE_AUDIT_MISSING_REGISTRY"
READY_DECISION = "FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT_READY_RESEARCH_ONLY"
FAIL_DECISION = "FACTOR_COVERAGE_AUDIT_BLOCKED_MISSING_REGISTRY"

NEXT_RECOMMENDED_MODULES = [
    "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL",
    "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT",
    "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT",
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
    Path("outputs") / "v22" / "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST" / "v21_output_classification_manifest.csv",
    Path("outputs") / "v22" / "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST" / "v21_active_output_manifest.csv",
    Path("outputs") / "v21" / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1",
    Path("outputs") / "v21" / "V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT",
    Path("outputs") / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON",
    Path("outputs") / "v21" / "V21.201_DRAM_MOOMOO_R4_PLAN",
    Path("outputs") / "v21" / "V21.232_DRAM",
    Path("outputs") / "v21" / "V21.233_MOOMOO_ONLY_ABCDE_RERUN",
]

IMPORTANT_OPTIONAL_INPUTS = OPTIONAL_INPUTS[2:]
MAX_FILES_PER_DIRECTORY = 40
MAX_SAMPLE_ROWS = 500
FULL_COUNT_SIZE_LIMIT = 1_500_000

COVERAGE_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "evidence_level_label",
    "coverage_source_status",
    "coverage_status",
    "missingness_risk",
    "eligible_for_predictive_validity",
    "local_source_count",
    "primary_source_paths",
    "detected_columns",
    "date_column_detected",
    "ticker_column_detected",
    "score_or_signal_column_detected",
    "row_count_estimate",
    "ticker_count_estimate",
    "date_count_estimate",
    "latest_date_detected",
    "source_scan_mode",
    "adoption_eligible",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

MISSINGNESS_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "missingness_risk",
    "missingness_reason",
    "likely_missing_dimensions",
    "required_fields_missing",
    "source_not_found_flag",
    "placeholder_only_flag",
    "stale_source_flag",
    "insufficient_panel_flag",
    "review_required_flag",
    "recommended_repair_or_next_step",
]

SOURCE_FIELDNAMES = [
    "source_path",
    "exists",
    "file_type",
    "parent_output_name",
    "classification_from_v22_002",
    "scan_mode",
    "file_size_bytes",
    "header_columns",
    "row_count_estimate",
    "date_column_candidates",
    "ticker_column_candidates",
    "signal_column_candidates",
    "latest_date_detected",
    "mapped_item_ids",
    "source_status",
    "note",
]

READINESS_FIELDNAMES = [
    "group_name",
    "item_count",
    "coverage_ready_count",
    "coverage_partial_count",
    "coverage_missing_count",
    "placeholder_only_count",
    "review_required_count",
    "eligible_for_predictive_validity_count",
    "high_missingness_risk_count",
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
        raise ValueError(f"V22.011 output directory must be {expected}, got {observed}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def load_registry(repo_root: Path) -> list[dict[str, str]]:
    return read_csv_rows(repo_root / REGISTRY_INPUT)


def load_v22_002_classifications(repo_root: Path) -> dict[str, str]:
    classification_path = repo_root / OPTIONAL_INPUTS[0]
    rows = read_csv_rows(classification_path)
    return {row.get("output_name", ""): row.get("classification", "") for row in rows if row.get("output_name")}


def output_name_for_path(path: Path) -> str:
    parts = path.parts
    for part in parts:
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


def looks_like_date(value: str) -> bool:
    text = value.strip()
    return len(text) >= 8 and text[:4].isdigit() and ("-" in text[:10] or "/" in text[:10])


def inspect_csv_file(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    scan_mode = "FULL_SHALLOW" if size <= FULL_COUNT_SIZE_LIMIT else "HEADER_ONLY_OR_SAMPLED"
    header_columns: list[str] = []
    row_count = 0
    latest_date = ""
    ticker_values: set[str] = set()
    date_values: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            header_columns = list(reader.fieldnames or [])
            date_cols = candidate_columns(header_columns, ["date", "time", "as_of", "timestamp"])
            ticker_cols = candidate_columns(header_columns, ["ticker", "symbol", "code"])
            for row in reader:
                row_count += 1
                if row_count <= MAX_SAMPLE_ROWS:
                    for column in ticker_cols:
                        value = (row.get(column) or "").strip()
                        if value:
                            ticker_values.add(value)
                    for column in date_cols:
                        value = (row.get(column) or "").strip()
                        if looks_like_date(value):
                            normalized = value[:10].replace("/", "-")
                            date_values.add(normalized)
                            if normalized > latest_date:
                                latest_date = normalized
                if size > FULL_COUNT_SIZE_LIMIT and row_count >= MAX_SAMPLE_ROWS:
                    break
    except (OSError, csv.Error, UnicodeError):
        scan_mode = "READ_ERROR"
    return {
        "scan_mode": scan_mode,
        "header_columns": header_columns,
        "row_count_estimate": row_count,
        "date_column_candidates": candidate_columns(header_columns, ["date", "time", "as_of", "timestamp"]),
        "ticker_column_candidates": candidate_columns(header_columns, ["ticker", "symbol", "code"]),
        "signal_column_candidates": candidate_columns(header_columns, ["score", "signal", "rank", "weight", "factor", "return", "momentum", "rsi", "macd", "kdj"]),
        "latest_date_detected": latest_date,
        "ticker_count_estimate": len(ticker_values),
        "date_count_estimate": len(date_values),
    }


def inspect_source_file(repo_root: Path, path: Path, classifications: dict[str, str]) -> dict[str, Any]:
    exists = path.exists()
    rel_path = path.relative_to(repo_root).as_posix() if exists else path.as_posix()
    parent_output_name = output_name_for_path(path)
    if not exists:
        return {
            "source_path": rel_path,
            "exists": False,
            "file_type": file_type(path),
            "parent_output_name": parent_output_name,
            "classification_from_v22_002": classifications.get(parent_output_name, ""),
            "scan_mode": "SOURCE_NOT_FOUND",
            "file_size_bytes": 0,
            "header_columns": "",
            "row_count_estimate": 0,
            "date_column_candidates": "",
            "ticker_column_candidates": "",
            "signal_column_candidates": "",
            "latest_date_detected": "",
            "mapped_item_ids": "",
            "source_status": "SOURCE_NOT_FOUND",
            "note": "Expected optional source path is missing.",
            "ticker_count_estimate": 0,
            "date_count_estimate": 0,
        }
    if path.is_dir():
        return {
            "source_path": rel_path,
            "exists": True,
            "file_type": "directory",
            "parent_output_name": parent_output_name,
            "classification_from_v22_002": classifications.get(parent_output_name, ""),
            "scan_mode": "DIRECTORY_REFERENCE",
            "file_size_bytes": 0,
            "header_columns": "",
            "row_count_estimate": 0,
            "date_column_candidates": "",
            "ticker_column_candidates": "",
            "signal_column_candidates": "",
            "latest_date_detected": "",
            "mapped_item_ids": "",
            "source_status": "SOURCE_FOUND",
            "note": "Directory exists; bounded scan records child data files separately.",
            "ticker_count_estimate": 0,
            "date_count_estimate": 0,
        }
    size = path.stat().st_size
    inspected = {
        "scan_mode": "METADATA_ONLY",
        "header_columns": [],
        "row_count_estimate": 0,
        "date_column_candidates": [],
        "ticker_column_candidates": [],
        "signal_column_candidates": [],
        "latest_date_detected": "",
        "ticker_count_estimate": 0,
        "date_count_estimate": 0,
    }
    if path.suffix.lower() == ".csv":
        inspected = inspect_csv_file(path)
    return {
        "source_path": rel_path,
        "exists": True,
        "file_type": file_type(path),
        "parent_output_name": parent_output_name,
        "classification_from_v22_002": classifications.get(parent_output_name, ""),
        "scan_mode": inspected["scan_mode"],
        "file_size_bytes": size,
        "header_columns": ";".join(inspected["header_columns"]),
        "row_count_estimate": inspected["row_count_estimate"],
        "date_column_candidates": ";".join(inspected["date_column_candidates"]),
        "ticker_column_candidates": ";".join(inspected["ticker_column_candidates"]),
        "signal_column_candidates": ";".join(inspected["signal_column_candidates"]),
        "latest_date_detected": inspected["latest_date_detected"],
        "mapped_item_ids": "",
        "source_status": "SOURCE_FOUND",
        "note": "Bounded local source scan only.",
        "ticker_count_estimate": inspected["ticker_count_estimate"],
        "date_count_estimate": inspected["date_count_estimate"],
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


def source_file_rows(repo_root: Path, registry_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    classifications = load_v22_002_classifications(repo_root)
    rows = [inspect_source_file(repo_root, path, classifications) for path in bounded_source_paths(repo_root)]
    for row in rows:
        mapped = mapped_item_ids_for_source(row["source_path"], registry_rows)
        row["mapped_item_ids"] = ";".join(mapped)
    return rows


def mapped_item_ids_for_source(source_path: str, registry_rows: list[dict[str, str]]) -> list[str]:
    mapped: list[str] = []
    for item in registry_rows:
        item_id = item.get("item_id", "")
        item_type = item.get("item_type", "")
        family = item.get("family", "")
        if "ETF_OPTION" in item_id:
            continue
        if item_type == "TECHNICAL_SUBFACTOR" and ("V21.246" in source_path or "V21.247" in source_path):
            mapped.append(item_id)
        elif item_type == "DRAM_SYSTEM" and ("V21.201" in source_path or "V21.232" in source_path):
            mapped.append(item_id)
        elif item_type == "STRATEGY_RANKING_SYSTEM" and ("V21.233" in source_path or "V21.255" in source_path):
            mapped.append(item_id)
        elif item_type == "FACTOR_FAMILY" and (
            "V21.246" in source_path or "V21.247" in source_path or "V21.255" in source_path or "V22.002" in source_path
        ):
            if family in {"TECHNICAL", "STRATEGY", "RISK", "DATA_TRUST", "FUNDAMENTAL", "MARKET_REGIME"}:
                mapped.append(item_id)
    return sorted(set(mapped))


def item_source_rows(item: dict[str, str], source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_id = item.get("item_id", "")
    return [row for row in source_rows if item_id in str(row.get("mapped_item_ids", "")).split(";") and row["exists"] is True]


def bool_from_text(value: str) -> bool:
    return str(value).strip().lower() == "true"


def coverage_row_for_item(item: dict[str, str], source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    item_id = item.get("item_id", "")
    item_type = item.get("item_type", "")
    sources = item_source_rows(item, source_rows)
    file_sources = [row for row in sources if row["file_type"] != "directory"]
    source_count = len(file_sources) if file_sources else len(sources)
    if item_type == "ETF_OPTION_PLACEHOLDER":
        coverage_source_status = "SOURCE_PLACEHOLDER_ONLY"
        coverage_status = "COVERAGE_PLACEHOLDER_ONLY"
        missingness_risk = "HIGH"
        eligible = False
        reason = "ETF option placeholder has no local option-chain ingestion or forward evidence."
    elif source_count == 0:
        coverage_source_status = "SOURCE_NOT_FOUND"
        coverage_status = "COVERAGE_MISSING"
        missingness_risk = "HIGH"
        eligible = False
        reason = "No mapped local source files were found in the bounded audit."
    else:
        has_signal = any(str(row["signal_column_candidates"]) for row in sources)
        has_date = any(str(row["date_column_candidates"]) for row in sources)
        has_ticker = any(str(row["ticker_column_candidates"]) for row in sources)
        if has_signal and has_date and (has_ticker or item_type == "DRAM_SYSTEM"):
            coverage_source_status = "SOURCE_FOUND"
            coverage_status = "COVERAGE_READY"
            missingness_risk = "LOW"
            eligible = item_type in {"TECHNICAL_SUBFACTOR", "STRATEGY_RANKING_SYSTEM", "DRAM_SYSTEM"}
            reason = "Mapped local source files include useful date/ticker/signal coverage for predictive-validity research."
        else:
            coverage_source_status = "SOURCE_MIXED"
            coverage_status = "COVERAGE_PARTIAL"
            missingness_risk = "MEDIUM"
            eligible = item_type in {"TECHNICAL_SUBFACTOR", "DRAM_SYSTEM"} and has_signal
            reason = "Mapped local sources exist, but coverage fields are partial or require review."
    detected_columns = sorted({column for row in sources for column in str(row["header_columns"]).split(";") if column})
    source_paths = [str(row["source_path"]) for row in sources]
    row_count_estimate = sum(int(row.get("row_count_estimate") or 0) for row in sources)
    ticker_count_estimate = max([int(row.get("ticker_count_estimate") or 0) for row in sources] or [0])
    date_count_estimate = max([int(row.get("date_count_estimate") or 0) for row in sources] or [0])
    latest_date = max([str(row.get("latest_date_detected") or "") for row in sources] or [""])
    return {
        "item_id": item_id,
        "item_name": item.get("item_name", ""),
        "item_type": item_type,
        "family": item.get("family", ""),
        "evidence_level_label": item.get("evidence_level_label", ""),
        "coverage_source_status": coverage_source_status,
        "coverage_status": coverage_status,
        "missingness_risk": missingness_risk,
        "eligible_for_predictive_validity": eligible,
        "local_source_count": source_count,
        "primary_source_paths": ";".join(source_paths),
        "detected_columns": ";".join(detected_columns),
        "date_column_detected": any(str(row["date_column_candidates"]) for row in sources),
        "ticker_column_detected": any(str(row["ticker_column_candidates"]) for row in sources),
        "score_or_signal_column_detected": any(str(row["signal_column_candidates"]) for row in sources),
        "row_count_estimate": row_count_estimate,
        "ticker_count_estimate": ticker_count_estimate,
        "date_count_estimate": date_count_estimate,
        "latest_date_detected": latest_date,
        "source_scan_mode": ";".join(sorted({str(row["scan_mode"]) for row in sources})) if sources else "NO_SOURCE_SCAN",
        "adoption_eligible": bool_from_text(item.get("adoption_eligible", "")),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": item.get("next_required_validation", ""),
        "reason": reason,
    }


def coverage_rows(registry_rows: list[dict[str, str]], source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [coverage_row_for_item(item, source_rows) for item in registry_rows]


def missingness_rows(coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in coverage:
        source_not_found = row["coverage_source_status"] == "SOURCE_NOT_FOUND"
        placeholder_only = row["coverage_source_status"] == "SOURCE_PLACEHOLDER_ONLY"
        insufficient_panel = row["coverage_status"] in {"COVERAGE_MISSING", "COVERAGE_PARTIAL", "COVERAGE_PLACEHOLDER_ONLY"}
        review_required = row["coverage_status"] == "COVERAGE_REVIEW_REQUIRED"
        missing_dimensions: list[str] = []
        required_missing: list[str] = []
        if source_not_found:
            missing_dimensions.append("LOCAL_SOURCE")
            required_missing.append("source_file")
        if placeholder_only:
            missing_dimensions.append("OPTION_CHAIN_PANEL")
            required_missing.append("option_chain_source")
        if not row["date_column_detected"]:
            missing_dimensions.append("DATE")
            required_missing.append("date")
        if not row["ticker_column_detected"] and row["item_type"] != "DRAM_SYSTEM":
            missing_dimensions.append("TICKER")
            required_missing.append("ticker")
        if not row["score_or_signal_column_detected"]:
            missing_dimensions.append("SCORE_OR_SIGNAL")
            required_missing.append("score_or_signal")
        rows.append(
            {
                "item_id": row["item_id"],
                "item_name": row["item_name"],
                "item_type": row["item_type"],
                "family": row["family"],
                "missingness_risk": row["missingness_risk"],
                "missingness_reason": row["reason"],
                "likely_missing_dimensions": ";".join(sorted(set(missing_dimensions))) or "NONE_DETECTED_IN_SHALLOW_SCAN",
                "required_fields_missing": ";".join(sorted(set(required_missing))) or "NONE_DETECTED_IN_SHALLOW_SCAN",
                "source_not_found_flag": source_not_found,
                "placeholder_only_flag": placeholder_only,
                "stale_source_flag": False,
                "insufficient_panel_flag": insufficient_panel,
                "review_required_flag": review_required,
                "recommended_repair_or_next_step": recommended_next_step(row),
            }
        )
    return rows


def recommended_next_step(row: dict[str, Any]) -> str:
    if row["item_type"] == "ETF_OPTION_PLACEHOLDER":
        return "Wait for V22.030 universe registry and later option-chain ingestion before predictive-validity work."
    if row["coverage_status"] == "COVERAGE_READY":
        return "Proceed to V22.012 predictive validity panel as research-only."
    if row["coverage_status"] == "COVERAGE_PARTIAL":
        return "Review mapped source columns and repair missing panel fields before V22.012."
    return "Locate or create a future research-only local source artifact; do not run daily chain or fetch data in V22.011."


def readiness_summary_rows(coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = sorted({str(row["item_type"]) for row in coverage})
    rows: list[dict[str, Any]] = []
    for group in groups + ["ALL"]:
        group_rows = coverage if group == "ALL" else [row for row in coverage if row["item_type"] == group]
        rows.append(
            {
                "group_name": group,
                "item_count": len(group_rows),
                "coverage_ready_count": sum(1 for row in group_rows if row["coverage_status"] == "COVERAGE_READY"),
                "coverage_partial_count": sum(1 for row in group_rows if row["coverage_status"] == "COVERAGE_PARTIAL"),
                "coverage_missing_count": sum(1 for row in group_rows if row["coverage_status"] == "COVERAGE_MISSING"),
                "placeholder_only_count": sum(1 for row in group_rows if row["coverage_status"] == "COVERAGE_PLACEHOLDER_ONLY"),
                "review_required_count": sum(1 for row in group_rows if row["coverage_status"] == "COVERAGE_REVIEW_REQUIRED"),
                "eligible_for_predictive_validity_count": sum(1 for row in group_rows if row["eligible_for_predictive_validity"] is True),
                "high_missingness_risk_count": sum(1 for row in group_rows if row["missingness_risk"] == "HIGH"),
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
    coverage: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    registry_exists = (repo_root / REGISTRY_INPUT).exists()
    optional_missing_count = sum(1 for rel_path in OPTIONAL_INPUTS if not (repo_root / rel_path).exists())
    if not registry_exists:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif optional_missing_count:
        final_status = WARN_STATUS
        final_decision = READY_DECISION
    else:
        final_status = PASS_STATUS
        final_decision = READY_DECISION
    etf_rows = [row for row in coverage if row["item_type"] == "ETF_OPTION_PLACEHOLDER"]
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "freeze_date": FREEZE_DATE,
        "final_status": final_status,
        "final_decision": final_decision,
        "registry_input_path": REGISTRY_INPUT.as_posix(),
        "registry_input_exists": registry_exists,
        "registered_item_count": len(registry_rows),
        "audited_item_count": len(coverage),
        "coverage_ready_count": sum(1 for row in coverage if row["coverage_status"] == "COVERAGE_READY"),
        "coverage_partial_count": sum(1 for row in coverage if row["coverage_status"] == "COVERAGE_PARTIAL"),
        "coverage_missing_count": sum(1 for row in coverage if row["coverage_status"] == "COVERAGE_MISSING"),
        "placeholder_only_count": sum(1 for row in coverage if row["coverage_status"] == "COVERAGE_PLACEHOLDER_ONLY"),
        "review_required_count": sum(1 for row in coverage if row["coverage_status"] == "COVERAGE_REVIEW_REQUIRED"),
        "eligible_for_predictive_validity_count": sum(1 for row in coverage if row["eligible_for_predictive_validity"] is True),
        "high_missingness_risk_count": sum(1 for row in coverage if row["missingness_risk"] == "HIGH"),
        "source_file_count": len(source_rows),
        "scanned_source_file_count": sum(1 for row in source_rows if row["exists"] is True),
        "source_found_item_count": sum(1 for row in coverage if row["coverage_source_status"] in {"SOURCE_FOUND", "SOURCE_MIXED"}),
        "source_not_found_item_count": sum(1 for row in coverage if row["coverage_source_status"] == "SOURCE_NOT_FOUND"),
        "optional_source_missing_count": optional_missing_count,
        "etf_option_placeholder_count": len(etf_rows),
        "etf_option_placeholder_eligible_count": 0,
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
        "allowed_side_effects": ["create_outputs_v22_011_only"],
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
        "V22.011 Factor Coverage and Missingness Audit",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"registry_input_path={summary['registry_input_path']}",
        f"registry_input_exists={summary['registry_input_exists']}",
        f"registered_item_count={summary['registered_item_count']}",
        f"audited_item_count={summary['audited_item_count']}",
        f"coverage_ready_count={summary['coverage_ready_count']}",
        f"coverage_partial_count={summary['coverage_partial_count']}",
        f"coverage_missing_count={summary['coverage_missing_count']}",
        f"placeholder_only_count={summary['placeholder_only_count']}",
        f"eligible_for_predictive_validity_count={summary['eligible_for_predictive_validity_count']}",
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

    registry = load_registry(repo_root)
    sources = source_file_rows(repo_root, registry) if registry else []
    coverage = coverage_rows(registry, sources)
    missingness = missingness_rows(coverage)
    readiness = readiness_summary_rows(coverage)
    summary = summary_payload(repo_root, output_dir, registry, coverage, sources)

    write_csv(output_dir / "v22_factor_coverage_audit.csv", COVERAGE_FIELDNAMES, coverage)
    write_csv(output_dir / "v22_factor_missingness_audit.csv", MISSINGNESS_FIELDNAMES, missingness)
    write_csv(output_dir / "v22_factor_coverage_source_file_audit.csv", SOURCE_FIELDNAMES, sources)
    write_csv(output_dir / "v22_factor_coverage_readiness_summary.csv", READINESS_FIELDNAMES, readiness)
    write_json(output_dir / "v22_factor_coverage_and_missingness_summary.json", summary)
    write_json(output_dir / "v22_factor_coverage_and_missingness_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.011_factor_coverage_and_missingness_audit_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_factor_coverage_and_missingness_summary.json'}")
    print("official_adoption_allowed_count=0")
    print("broker_action_allowed_count=0")
    print("trade_allowed_count=0")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
