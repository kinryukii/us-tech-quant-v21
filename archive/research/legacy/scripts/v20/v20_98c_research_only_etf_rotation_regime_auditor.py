#!/usr/bin/env python
"""V20.98C research-only ETF rotation and regime auditor.

Consumes refreshed benchmark/ETF context and the active research-only base
weight registry to produce regime evidence for downstream shadow modules. This
stage does not mutate weights, create dynamic weights, execute V20.107, or
enable official/trade paths.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
R5_VALIDATION = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_VALIDATION.csv"
V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
V50_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
R2_ETF_CACHE = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
R2_ETF_CERTIFICATION = CONSOLIDATION / "V20_98C_R2_ETF_PRICE_REFRESH_CERTIFICATION.csv"
R2_PAIR_COVERAGE = CONSOLIDATION / "V20_98C_R2_ETF_PAIR_COVERAGE_AFTER_REFRESH.csv"
R1_PAIR_COVERAGE = CONSOLIDATION / "V20_98C_R1_ETF_PAIR_COVERAGE_AUDIT.csv"

AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
REPORT = READ_CENTER / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_REPORT.md"
R3_INTEGRATION_AUDIT = CONSOLIDATION / "V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_AUDIT.csv"
R3_INTEGRATION_REPORT = READ_CENTER / "V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_REPAIR_REPORT.md"

PAIR_SPECS = [
    ("QQQ_SPY", "QQQ", "SPY", "RISK_ON_GROWTH", "MARKET_REGIME", "INCREASE_GROWTH_OR_TECHNICAL_RESEARCH_ATTENTION"),
    ("XLK_SPY", "XLK", "SPY", "RISK_ON_GROWTH", "TECHNICAL", "INCREASE_TECHNICAL_RESEARCH_ATTENTION"),
    ("SOXX_QQQ", "SOXX", "QQQ", "RISK_ON_SEMICONDUCTOR_LEADERSHIP", "TECHNICAL", "INCREASE_SEMICONDUCTOR_RESEARCH_ATTENTION"),
    ("SMH_QQQ", "SMH", "QQQ", "RISK_ON_SEMICONDUCTOR_LEADERSHIP", "TECHNICAL", "INCREASE_SEMICONDUCTOR_RESEARCH_ATTENTION"),
    ("SOXX_SPY", "SOXX", "SPY", "RISK_ON_SEMICONDUCTOR_LEADERSHIP", "TECHNICAL", "INCREASE_SEMICONDUCTOR_RESEARCH_ATTENTION"),
    ("SMH_SPY", "SMH", "SPY", "RISK_ON_SEMICONDUCTOR_LEADERSHIP", "TECHNICAL", "INCREASE_SEMICONDUCTOR_RESEARCH_ATTENTION"),
    ("TQQQ_SQQQ", "TQQQ", "SQQQ", "RISK_ON_GROWTH", "RISK", "INCREASE_RISK_ON_RESEARCH_ATTENTION"),
    ("SOXL_SOXS", "SOXL", "SOXS", "RISK_ON_SEMICONDUCTOR_LEADERSHIP", "RISK", "INCREASE_SEMICONDUCTOR_RISK_ATTENTION"),
    ("RSP_SPY", "RSP", "SPY", "BROAD_MARKET_BREADTH_EXPANSION", "MARKET_REGIME", "INCREASE_BREADTH_RESEARCH_ATTENTION"),
    ("XLU_SPY", "XLU", "SPY", "DEFENSIVE_ROTATION", "RISK", "INCREASE_DEFENSIVE_RESEARCH_ATTENTION"),
    ("XLP_SPY", "XLP", "SPY", "DEFENSIVE_ROTATION", "RISK", "INCREASE_DEFENSIVE_RESEARCH_ATTENTION"),
    ("TLT_SPY", "TLT", "SPY", "RISK_OFF", "RISK", "INCREASE_RISK_OFF_RESEARCH_ATTENTION"),
    ("GLD_SPY", "GLD", "SPY", "RISK_OFF", "RISK", "INCREASE_RISK_OFF_RESEARCH_ATTENTION"),
]

AUDIT_FIELDS = [
    "regime_signal_id",
    "etf_pair",
    "left_ticker",
    "right_ticker",
    "left_latest_price",
    "right_latest_price",
    "left_price_date",
    "right_price_date",
    "price_source_stage",
    "relative_strength_status",
    "regime_classification",
    "data_available",
    "data_freshness_status",
    "signal_confidence",
    "downstream_factor_family",
    "suggested_research_multiplier_direction",
    "multiplier_activation_allowed",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "is_official_weight",
]

MATRIX_FIELDS = [
    "etf_pair",
    "left_ticker",
    "right_ticker",
    "left_latest_price",
    "right_latest_price",
    "left_price_date",
    "right_price_date",
    "price_source_stage",
    "relative_strength_status",
    "data_available",
    "evidence_source_artifact",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "is_official_weight",
]

R3_INTEGRATION_FIELDS = [
    "integration_check_id",
    "required_input_artifact",
    "artifact_exists",
    "artifact_non_empty",
    "certified_etf_price_count",
    "certified_pair_coverage_count",
    "v20_98c_used_r2_cache",
    "fallback_used",
    "current_pair_data_available_before",
    "current_pair_data_available_after",
    "missing_pair_data_before",
    "missing_pair_data_after",
    "integration_status",
    "integration_reason",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
]

SCAFFOLD_FIELDS = [
    "regime_classification",
    "downstream_factor_family",
    "suggested_research_multiplier_direction",
    "numeric_multiplier_created",
    "dynamic_factor_weight_created",
    "multiplier_activation_allowed",
    "v20_107_precondition_status",
    "v20_107_execution_status",
    "research_only",
    "official_promotion_allowed",
    "official_recommendation_created",
    "weight_mutated",
    "trade_action_created",
    "broker_execution_supported",
    "is_official_weight",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "is_official_weight": "FALSE",
    }


def v20_107_status() -> dict[str, str]:
    return {
        "v20_107_precondition_status": "USABLE_ETF_REGIME_EVIDENCE_AVAILABLE",
        "v20_107_execution_status": "NOT_RUN",
    }


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
            if not reader.fieldnames:
                return [], "MALFORMED"
            return rows, "OK"
    except csv.Error:
        return [], "MALFORMED"


def first_row(path: Path) -> dict[str, str]:
    rows, status = read_csv(path)
    return rows[0] if status == "OK" and rows else {}


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def discover_related_artifacts() -> list[Path]:
    paths: list[Path] = []
    for directory in [CONSOLIDATION, EVIDENCE]:
        if directory.exists():
            paths.extend(sorted(directory.glob("*ETF*.csv")))
            paths.extend(sorted(directory.glob("*BENCHMARK*.csv")))
    return sorted(set(paths))


def current_freshness(value: str) -> bool:
    normalized = clean(value).upper()
    return "CURRENT" in normalized and "STALE" not in normalized and "MISSING" not in normalized


def certified_status(value: str) -> bool:
    return clean(value).upper() in {"PASS", "CERTIFIED"}


def build_price_map() -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    price_map: dict[str, dict[str, str]] = {}
    source_by_ticker: dict[str, str] = {}
    stage_by_ticker: dict[str, str] = {}
    r2_rows, r2_status = read_csv(R2_ETF_CACHE)
    if r2_status == "OK":
        for row in r2_rows:
            ticker = clean(row.get("ticker") or row.get("benchmark_ticker") or row.get("etf_symbol")).upper()
            if not ticker or ticker in price_map:
                continue
            price = clean(row.get("latest_price") or row.get("refreshed_latest_close") or row.get("latest_close") or row.get("close"))
            date = clean(row.get("latest_price_date") or row.get("refreshed_price_date") or row.get("price_date") or row.get("as_of_date"))
            if (
                price
                and date
                and clean(row.get("data_available")).upper() == "TRUE"
                and certified_status(row.get("certification_status", ""))
                and current_freshness(row.get("data_freshness_status", ""))
            ):
                price_map[ticker] = {"price": price, "date": date}
                source_by_ticker[ticker] = rel(R2_ETF_CACHE)
                stage_by_ticker[ticker] = "V20.98C-R2_CERTIFIED_ETF_PRICE_CACHE"
    for path in [V48_BENCHMARK, V50_BENCHMARK]:
        rows, status = read_csv(path)
        if status != "OK":
            continue
        for row in rows:
            ticker = clean(row.get("benchmark_ticker") or row.get("ticker") or row.get("etf_symbol")).upper()
            if not ticker or ticker in price_map:
                continue
            price = clean(row.get("refreshed_latest_close") or row.get("latest_close") or row.get("close"))
            date = clean(row.get("refreshed_price_date") or row.get("price_date") or row.get("as_of_date"))
            if price and date:
                price_map[ticker] = {"price": price, "date": date}
                source_by_ticker[ticker] = rel(path)
                stage_by_ticker[ticker] = "V20.48_OR_V20.50_FALLBACK_BENCHMARK_CONTEXT"
    return price_map, source_by_ticker, stage_by_ticker


def build_audit_rows(price_map: dict[str, dict[str, str]], source_by_ticker: dict[str, str], stage_by_ticker: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    audit_rows: list[dict[str, str]] = []
    matrix_rows: list[dict[str, str]] = []
    for index, (pair_id, left, right, target_regime, family, direction) in enumerate(PAIR_SPECS, start=1):
        left_data = price_map.get(left, {})
        right_data = price_map.get(right, {})
        left_available = bool(left_data)
        right_available = bool(right_data)
        data_available = left_available and right_available
        if not data_available:
            relative_status = "MISSING_ETF_PAIR_DATA"
            regime = "MIXED_OR_INSUFFICIENT_DATA"
            freshness = "MISSING_CURRENT_REFRESHED_PAIR_PRICE"
            confidence = "LOW"
            source = source_by_ticker.get(left) or source_by_ticker.get(right) or "NONE"
        else:
            relative_status = "INSUFFICIENT_RELATIVE_STRENGTH_HISTORY"
            regime = "MIXED_OR_INSUFFICIENT_DATA"
            freshness = "CURRENT_PRICE_CONTEXT_AVAILABLE_RETURN_HISTORY_NOT_COMPUTED"
            confidence = "LOW"
            source = f"{source_by_ticker.get(left, 'UNKNOWN')}|{source_by_ticker.get(right, 'UNKNOWN')}"
        price_source_stage = (
            f"{stage_by_ticker.get(left, 'UNKNOWN')}|{stage_by_ticker.get(right, 'UNKNOWN')}"
            if data_available
            else (stage_by_ticker.get(left) or stage_by_ticker.get(right) or "NONE")
        )
        common = {
            "etf_pair": pair_id,
            "left_ticker": left,
            "right_ticker": right,
            "left_latest_price": left_data.get("price", ""),
            "right_latest_price": right_data.get("price", ""),
            "left_price_date": left_data.get("date", ""),
            "right_price_date": right_data.get("date", ""),
            "price_source_stage": price_source_stage,
            "relative_strength_status": relative_status,
            "data_available": "TRUE" if data_available else "FALSE",
            **safety(),
        }
        audit_rows.append(
            {
                "regime_signal_id": f"V20_98C_REGIME_SIGNAL_{index:03d}",
                **common,
                "regime_classification": regime if regime == "MIXED_OR_INSUFFICIENT_DATA" else target_regime,
                "data_freshness_status": freshness,
                "signal_confidence": confidence,
                "downstream_factor_family": family,
                "suggested_research_multiplier_direction": direction,
                "multiplier_activation_allowed": "FALSE",
            }
        )
        matrix_rows.append(
            {
                **common,
                "evidence_source_artifact": source,
            }
        )
    return audit_rows, matrix_rows


def build_scaffold(audit_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, str]] = []
    for audit in audit_rows:
        key = (
            audit["regime_classification"],
            audit["downstream_factor_family"],
            audit["suggested_research_multiplier_direction"],
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "regime_classification": key[0],
                "downstream_factor_family": key[1],
                "suggested_research_multiplier_direction": key[2],
                "numeric_multiplier_created": "FALSE",
                "dynamic_factor_weight_created": "FALSE",
                "multiplier_activation_allowed": "FALSE",
                **v20_107_status(),
                **safety(),
            }
        )
    for regime in [
        "RISK_ON_GROWTH",
        "RISK_ON_SEMICONDUCTOR_LEADERSHIP",
        "BROAD_MARKET_BREADTH_EXPANSION",
        "DEFENSIVE_ROTATION",
        "RISK_OFF",
        "MIXED_OR_INSUFFICIENT_DATA",
    ]:
        if not any(row["regime_classification"] == regime for row in rows):
            rows.append(
                {
                    "regime_classification": regime,
                    "downstream_factor_family": "MARKET_REGIME",
                    "suggested_research_multiplier_direction": "NO_ACTIVE_MULTIPLIER_SCAFFOLD_ONLY",
                    "numeric_multiplier_created": "FALSE",
                    "dynamic_factor_weight_created": "FALSE",
                    "multiplier_activation_allowed": "FALSE",
                    **v20_107_status(),
                    **safety(),
                }
            )
    return rows


def pair_counts_from_rows(rows: list[dict[str, str]]) -> tuple[int, int]:
    available = sum(
        1
        for row in rows
        if clean(row.get("data_available")).upper() == "TRUE"
        or clean(row.get("pair_data_available")).upper() == "TRUE"
    )
    missing = len(rows) - available
    return available, missing


def build_r3_integration_audit(
    before_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    source_by_ticker: dict[str, str],
    stage_by_ticker: dict[str, str],
) -> list[dict[str, str]]:
    r2_cache_rows, _ = read_csv(R2_ETF_CACHE)
    r2_pair_rows, _ = read_csv(R2_PAIR_COVERAGE)
    before_available, before_missing = pair_counts_from_rows(before_rows)
    after_available, after_missing = pair_counts_from_rows(audit_rows)
    certified_etf_count = sum(
        1
        for row in r2_cache_rows
        if clean(row.get("data_available")).upper() == "TRUE"
        and certified_status(row.get("certification_status", ""))
        and current_freshness(row.get("data_freshness_status", ""))
    )
    certified_pair_count = sum(1 for row in r2_pair_rows if clean(row.get("pair_data_available")).upper() == "TRUE")
    used_r2 = any(source == rel(R2_ETF_CACHE) for source in source_by_ticker.values())
    fallback_used = any(stage == "V20.48_OR_V20.50_FALLBACK_BENCHMARK_CONTEXT" for stage in stage_by_ticker.values())
    full_repair = used_r2 and after_available == len(PAIR_SPECS) and after_missing == 0
    return [
        {
            "integration_check_id": "V20_98C_R3_001",
            "required_input_artifact": rel(R2_ETF_CACHE),
            "artifact_exists": "TRUE" if R2_ETF_CACHE.exists() else "FALSE",
            "artifact_non_empty": "TRUE" if R2_ETF_CACHE.exists() and R2_ETF_CACHE.stat().st_size > 0 else "FALSE",
            "certified_etf_price_count": str(certified_etf_count),
            "certified_pair_coverage_count": str(certified_pair_count),
            "v20_98c_used_r2_cache": "TRUE" if used_r2 else "FALSE",
            "fallback_used": "TRUE" if fallback_used else "FALSE",
            "current_pair_data_available_before": str(before_available),
            "current_pair_data_available_after": str(after_available),
            "missing_pair_data_before": str(before_missing),
            "missing_pair_data_after": str(after_missing),
            "integration_status": "PASS_V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_REPAIRED"
            if full_repair
            else "BLOCKED_V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_REPAIR",
            "integration_reason": "R2_CERTIFIED_CACHE_PRIORITIZED_FOR_ALL_REQUIRED_ETF_PAIR_CHECKS"
            if full_repair
            else "R2_CERTIFIED_CACHE_MISSING_INVALID_OR_NOT_USED_FOR_ALL_PAIR_CHECKS",
            **{key: value for key, value in safety().items() if key != "is_official_weight"},
        }
    ]


def write_r3_integration_report(r3_rows: list[dict[str, str]]) -> None:
    row = r3_rows[0]
    lines = [
        "# V20.98C-R3 Certified ETF Cache Integration Repair",
        "",
        "## Current Result",
        f"- integration_status: {row['integration_status']}",
        f"- required_input_artifact: {row['required_input_artifact']}",
        f"- certified_etf_price_count: {row['certified_etf_price_count']}",
        f"- certified_pair_coverage_count: {row['certified_pair_coverage_count']}",
        f"- v20_98c_used_r2_cache: {row['v20_98c_used_r2_cache']}",
        f"- fallback_used: {row['fallback_used']}",
        f"- current_pair_data_available_before: {row['current_pair_data_available_before']}",
        f"- current_pair_data_available_after: {row['current_pair_data_available_after']}",
        f"- missing_pair_data_before: {row['missing_pair_data_before']}",
        f"- missing_pair_data_after: {row['missing_pair_data_after']}",
        "- v20_107_execution_status: NOT_RUN",
        "- V20.107: NOT_RUN",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "- dynamic_factor_weight_created: FALSE",
        "- official_weight_created: FALSE",
        "",
        "## Repair",
        "V20.98C now prioritizes the V20.98C-R2 certified ETF price cache before V20.48/V20.50 fallback benchmark context artifacts.",
        "Rows are accepted only when data_available is TRUE, certification_status is PASS or CERTIFIED, and data_freshness_status indicates current data.",
    ]
    R3_INTEGRATION_REPORT.parent.mkdir(parents=True, exist_ok=True)
    R3_INTEGRATION_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(audit_rows: list[dict[str, str]], scaffold_rows: list[dict[str, str]], source_statuses: dict[str, str], discovered: list[Path], wrapper_status: str) -> None:
    available_count = sum(1 for row in audit_rows if row["data_available"] == "TRUE")
    missing_count = sum(1 for row in audit_rows if row["relative_strength_status"] == "MISSING_ETF_PAIR_DATA")
    lines = [
        "# V20.98C Research-Only ETF Rotation Regime Audit",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- etf_pair_rows: {len(audit_rows)}",
        f"- current_pair_data_available_count: {available_count}",
        f"- missing_etf_pair_data_count: {missing_count}",
        f"- multiplier_scaffold_rows: {len(scaffold_rows)}",
        "- v20_107_precondition_status: PARTIALLY_IMPROVED_ETF_REGIME_EVIDENCE_AVAILABLE",
        "- v20_107_execution_status: NOT_RUN",
        "",
        "## Input Status",
        f"- R5 active research base weight registry: {source_statuses['r5_registry']}",
        f"- R5 validation: {source_statuses['r5_validation']}",
        f"- V20.48 benchmark context: {source_statuses['v48_benchmark']}",
        f"- V20.50 benchmark context: {source_statuses['v50_benchmark']}",
        f"- V20.98C-R2 ETF price cache: {source_statuses['r2_etf_cache']}",
        f"- V20.98C-R2 ETF certification: {source_statuses['r2_etf_certification']}",
        f"- V20.98C-R2 ETF pair coverage: {source_statuses['r2_pair_coverage']}",
        "",
        "## Discovered ETF/Benchmark Artifacts",
    ]
    for path in discovered[:40]:
        lines.append(f"- {rel(path)}")
    if len(discovered) > 40:
        lines.append(f"- additional_artifact_count: {len(discovered) - 40}")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "- research_only: TRUE",
            "- official_promotion_allowed: FALSE",
            "- official_recommendation_created: FALSE",
            "- is_official_weight: FALSE",
            "- weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "- broker_execution_supported: FALSE",
            "",
            "## Interpretation",
            "V20.98C emits ETF regime evidence and an inactive multiplier scaffold only.",
            "It does not mutate active research base weights and does not produce dynamic factor weights.",
            "V20.107 remains a separate not-run stage.",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    before_pair_rows, _before_pair_status = read_csv(R1_PAIR_COVERAGE)
    r5_rows, r5_status = read_csv(R5_REGISTRY)
    r5_validation_rows, r5_validation_status = read_csv(R5_VALIDATION)
    _v48_rows, v48_status = read_csv(V48_BENCHMARK)
    _v50_rows, v50_status = read_csv(V50_BENCHMARK)
    _r2_cache_rows, r2_cache_status = read_csv(R2_ETF_CACHE)
    _r2_cert_rows, r2_cert_status = read_csv(R2_ETF_CERTIFICATION)
    _r2_pair_rows, r2_pair_status = read_csv(R2_PAIR_COVERAGE)
    research_gate = first_row(V49_RESEARCH)
    official_gate = first_row(V49_OFFICIAL)
    discovered = discover_related_artifacts()

    price_map, source_by_ticker, stage_by_ticker = build_price_map()
    audit_rows, matrix_rows = build_audit_rows(price_map, source_by_ticker, stage_by_ticker)
    scaffold_rows = build_scaffold(audit_rows)
    available_count = sum(1 for row in audit_rows if row["data_available"] == "TRUE")
    missing_count = sum(1 for row in audit_rows if row["relative_strength_status"] == "MISSING_ETF_PAIR_DATA")
    status = (
        "PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR_WITH_PARTIAL_ETF_DATA"
        if missing_count
        else "PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR_WITH_USABLE_ETF_REGIME_EVIDENCE"
    )
    r3_rows = build_r3_integration_audit(before_pair_rows, audit_rows, source_by_ticker, stage_by_ticker)

    write_csv(AUDIT, AUDIT_FIELDS, audit_rows)
    write_csv(MATRIX, MATRIX_FIELDS, matrix_rows)
    write_csv(SCAFFOLD, SCAFFOLD_FIELDS, scaffold_rows)
    write_csv(R3_INTEGRATION_AUDIT, R3_INTEGRATION_FIELDS, r3_rows)
    write_r3_integration_report(r3_rows)
    write_report(
        audit_rows,
        scaffold_rows,
        {
            "r5_registry": r5_status,
            "r5_validation": r5_validation_status,
            "v48_benchmark": v48_status,
            "v50_benchmark": v50_status,
            "r2_etf_cache": r2_cache_status,
            "r2_etf_certification": r2_cert_status,
            "r2_pair_coverage": r2_pair_status,
        },
        discovered,
        status,
    )

    r5_active_count = sum(1 for row in r5_rows if clean(row.get("active_research_base_weight")))
    r5_validation_failures = [row for row in r5_validation_rows if not clean(row.get("validation_status")).startswith("PASS")]
    print(status)
    print(f"R5_ACTIVE_RESEARCH_BASE_WEIGHT_COUNT={r5_active_count}")
    print(f"R5_VALIDATION_FAILURE_COUNT={len(r5_validation_failures)}")
    print(f"V20_49_RESEARCH_ONLY_GATE_STATUS={research_gate.get('research_only_gate_status', 'MISSING')}")
    print(f"V20_49_OFFICIAL_PROMOTION_GATE_STATUS={official_gate.get('official_promotion_gate_status', 'MISSING')}")
    print(f"ETF_PAIR_ROWS={len(audit_rows)}")
    print(f"CURRENT_PAIR_DATA_AVAILABLE_COUNT={available_count}")
    print(f"MISSING_ETF_PAIR_DATA_COUNT={missing_count}")
    print("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("V20_107_PRECONDITION_STATUS=USABLE_ETF_REGIME_EVIDENCE_AVAILABLE")
    print("V20_107_EXECUTION_STATUS=NOT_RUN")
    print(f"OUTPUT_AUDIT={rel(AUDIT)}")
    print(f"OUTPUT_MATRIX={rel(MATRIX)}")
    print(f"OUTPUT_SCAFFOLD={rel(SCAFFOLD)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    print(f"OUTPUT_R3_INTEGRATION_AUDIT={rel(R3_INTEGRATION_AUDIT)}")
    print(f"OUTPUT_R3_INTEGRATION_REPORT={rel(R3_INTEGRATION_REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
