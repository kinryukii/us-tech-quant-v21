#!/usr/bin/env python
"""V20.108-R2 missing factor-family contribution source expander.

Carries forward V20.108-R1 candidate-level contributions, searches additional
artifacts for real ticker-level numeric sources for missing families, and
classifies family-level-only or missing evidence without fabrication.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

R1_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
R1_SOURCE = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_CONTRIBUTION_SOURCE_AUDIT.csv"
R1_COVERAGE = CONSOLIDATION / "V20_108_R1_FACTOR_FAMILY_CONTRIBUTION_COVERAGE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
V50_BENCH = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
V98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_EXPANDED = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
OUT_SOURCE = CONSOLIDATION / "V20_108_R2_MISSING_FACTOR_FAMILY_SOURCE_AUDIT.csv"
OUT_MATERIAL = CONSOLIDATION / "V20_108_R2_FACTOR_FAMILY_MATERIALIZATION_AUDIT.csv"
OUT_READINESS = CONSOLIDATION / "V20_108_R2_SHADOW_RERANK_READINESS_AFTER_EXPANSION.csv"
REPORT = READ_CENTER / "V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_WITH_PARTIAL_CONTRIBUTION_COVERAGE"
MISSING_STATUS = "PARTIAL_PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_WITH_MISSING_CONTRIBUTION_DATA"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
MISSING_TARGETS = ["FUNDAMENTAL", "STRATEGY", "RISK", "MARKET_REGIME"]
FAMILY_COLUMNS = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}

EXPANDED_FIELDS = [
    "ticker", "baseline_rank", "baseline_score_source", "fundamental_contribution",
    "technical_contribution", "strategy_contribution", "risk_contribution",
    "market_regime_contribution", "data_trust_contribution", "contribution_sum",
    "contribution_normalization_status", "contribution_status", "missing_factor_families",
    "materialized_factor_families", "contribution_source_artifacts",
    "contribution_source_stages", "candidate_factor_granularity_status",
    "usable_for_shadow_rerank", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

SOURCE_FIELDS = [
    "factor_family", "source_artifact", "source_exists", "source_non_empty",
    "ticker_column_available", "numeric_candidate_level_columns_found",
    "family_level_only_columns_found", "source_rank_or_score_present",
    "source_rank_or_score_used_as_contribution", "source_classification_status",
    "materialization_allowed", "materialization_blocker_reason", "validation_status",
    "validation_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

MATERIAL_FIELDS = [
    "factor_family", "candidate_count", "r1_candidates_with_contribution",
    "new_candidates_materialized", "total_candidates_with_contribution",
    "coverage_ratio", "materialization_status", "source_artifacts",
    "materialization_blocker_reason", "source_rank_or_score_used_as_contribution",
    "baseline_rank_used_as_contribution", "contribution_scores_fabricated",
    "usable_for_shadow_rerank", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]

READINESS_FIELDS = [
    "readiness_check_id", "candidate_count",
    "complete_six_family_contribution_candidate_count",
    "partial_contribution_candidate_count", "missing_contribution_candidate_count",
    "usable_for_shadow_rerank_count", "technical_coverage_ratio",
    "data_trust_coverage_ratio", "fundamental_coverage_ratio",
    "strategy_coverage_ratio", "risk_coverage_ratio", "market_regime_coverage_ratio",
    "shadow_rerank_readiness_status", "shadow_rerank_blocker_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str, list[str]]:
    if not path.exists():
        return [], "MISSING", []
    if path.stat().st_size == 0:
        return [], "EMPTY", []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, "OK" if fields else "MALFORMED", fields


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def num(value: object) -> float | None:
    try:
        parsed = float(clean(value))
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def ticker_value(row: dict[str, str]) -> str:
    return clean(row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id") or row.get("display_name_or_ticker"))


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_"):
        parts = name.split("_", 2)
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else "V20"
    if name.startswith("V18_"):
        return "V18"
    if name.startswith("V19_"):
        return "V19"
    return "DISCOVERED"


def discover_sources() -> list[Path]:
    seeds = [
        R1_CONTRIB, R1_SOURCE, R1_COVERAGE, V107_WEIGHTS, R5_REGISTRY,
        V48_CANDIDATES, V48_FACTORS, V50_CANDIDATES, V50_FACTORS, V50_ENTRY,
        V50_BENCH, V98C_AUDIT, V106_FACTOR, V49_RESEARCH, V49_OFFICIAL,
    ]
    found: list[Path] = []
    for pattern in ("*RISK*.csv", "*REGIME*.csv", "*STRATEGY*.csv", "*FACTOR*.csv", "*BENCHMARK*.csv"):
        found.extend(CONSOLIDATION.glob(pattern))
        if EVIDENCE.exists():
            found.extend(EVIDENCE.glob(pattern))
    for root in (ROOT / "outputs" / "v18", ROOT / "outputs" / "v19", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_EXPANDED.resolve(), OUT_SOURCE.resolve(), OUT_MATERIAL.resolve(), OUT_READINESS.resolve()}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in seeds + sorted(found):
        resolved = path.resolve()
        if resolved in excluded:
            continue
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(path)
    return ordered


def classify_wide_column(column: str) -> str | None:
    name = column.lower()
    if name in {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "factor_pack_rank"}:
        return None
    if not any(token in name for token in ("score", "contribution", "metric", "signal")):
        return None
    if "technical" in name or "timing" in name:
        return "TECHNICAL"
    if "fundamental" in name or "valuation" in name or "quality" in name and "source_quality" not in name:
        return "FUNDAMENTAL"
    if "strategy" in name or "entry" in name or "setup" in name:
        return "STRATEGY"
    if "risk" in name or "drawdown" in name or "volatility" in name:
        return "RISK"
    if "market_regime" in name or "regime" in name:
        return "MARKET_REGIME"
    if "data_trust" in name or "trustworthiness" in name or "source_quality" in name:
        return "DATA_TRUST"
    return None


def classify_long_family(row: dict[str, str]) -> str | None:
    category = clean(row.get("factor_category")).lower()
    family = clean(row.get("factor_family")).lower()
    joined = f"{category} {family} {clean(row.get('score_type')).lower()} {clean(row.get('factor_id_or_name')).lower()}"
    if category in {"data_trustworthiness", "data_trust"} or family in {"data_trust", "data_trustworthiness"}:
        return "DATA_TRUST"
    if "fundamental" in joined:
        return "FUNDAMENTAL"
    if "technical" in joined:
        return "TECHNICAL"
    if "strategy" in joined:
        return "STRATEGY"
    if "risk" in joined:
        return "RISK"
    if "market_regime" in joined or "regime" in joined:
        return "MARKET_REGIME"
    return None


def normalize(values: dict[str, tuple[float, Path, str]]) -> dict[str, tuple[float, Path, str]]:
    if not values:
        return {}
    nums = [value for value, _, _ in values.values()]
    low, high = min(nums), max(nums)
    if high == low:
        return {ticker: (1.0, path, column) for ticker, (value, path, column) in values.items()}
    return {ticker: ((value - low) / (high - low), path, column) for ticker, (value, path, column) in values.items()}


def collect_missing_family_sources(candidate_tickers: set[str]) -> tuple[dict[str, dict[str, tuple[float, Path, str]]], list[dict[str, str]]]:
    collected: dict[str, dict[str, tuple[float, Path, str]]] = {family: {} for family in MISSING_TARGETS}
    audits: list[dict[str, str]] = []
    for path in discover_sources():
        rows, status, fields = read_csv(path)
        exists = path.exists()
        ticker_col_available = any(field in fields for field in ("ticker", "normalized_ticker", "ticker_or_candidate_id", "display_name_or_ticker"))
        source_rank_present = "source_rank_or_score" in fields
        family_level_only = any(field in fields for field in ("factor_family", "regime_classification", "etf_pair")) and not ticker_col_available
        wide = {field: classify_wide_column(field) for field in fields}
        wide = {field: family for field, family in wide.items() if family in MISSING_TARGETS}
        candidate_values: dict[str, dict[str, list[tuple[float, Path, str]]]] = {family: defaultdict(list) for family in MISSING_TARGETS}
        family_level_found: set[str] = set()
        if status == "OK" and rows:
            for row in rows:
                long_family = classify_long_family(row)
                if long_family in MISSING_TARGETS and not ticker_col_available:
                    family_level_found.add(long_family)
                ticker = ticker_value(row)
                if ticker not in candidate_tickers:
                    continue
                for column, family in wide.items():
                    value = num(row.get(column))
                    if value is not None:
                        candidate_values[family][ticker].append((value, path, column))
                long_value = num(row.get("factor_score_value"))
                if long_family in MISSING_TARGETS and long_value is not None:
                    created_ok = row.get("factor_score_created", "TRUE") != "FALSE"
                    official_ok = row.get("official_use_allowed", "FALSE") != "TRUE"
                    if created_ok and official_ok:
                        candidate_values[long_family][ticker].append((long_value, path, "factor_score_value"))
        for family in MISSING_TARGETS:
            numeric_cols = sorted({
                column
                for ticker_rows in candidate_values[family].values()
                for _, _, column in ticker_rows
            })
            for ticker, values in candidate_values[family].items():
                if ticker not in collected[family] and values:
                    avg = sum(value for value, _, _ in values) / len(values)
                    collected[family][ticker] = (avg, values[0][1], values[0][2])
            has_candidate_numeric = bool(numeric_cols)
            family_only = family in family_level_found or (family_level_only and family in clean(" ".join(rows[0].values()) if rows else "").upper())
            if has_candidate_numeric:
                classification = "CANDIDATE_LEVEL_NUMERIC_CONTRIBUTION_SOURCE"
                allowed = True
                blocker = ""
            elif family_only:
                classification = "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_CONTRIBUTION"
                allowed = False
                blocker = "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_CONTRIBUTION"
            else:
                classification = "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION"
                allowed = False
                blocker = "NO_REAL_TICKER_LEVEL_NUMERIC_SOURCE_COLUMNS"
            audits.append({
                "factor_family": family,
                "source_artifact": rel(path),
                "source_exists": tf(exists),
                "source_non_empty": tf(exists and path.stat().st_size > 0),
                "ticker_column_available": tf(ticker_col_available),
                "numeric_candidate_level_columns_found": ";".join(numeric_cols),
                "family_level_only_columns_found": "factor_family/regime_context" if family_only and not has_candidate_numeric else "",
                "source_rank_or_score_present": tf(source_rank_present),
                "source_rank_or_score_used_as_contribution": "FALSE",
                "source_classification_status": classification,
                "materialization_allowed": tf(allowed),
                "materialization_blocker_reason": blocker,
                "validation_status": "PASS",
                "validation_reason": "SOURCE_RANK_OR_SCORE_AND_BASELINE_RANK_NOT_USED",
                **safety(),
            })
    return {family: normalize(values) for family, values in collected.items()}, audits


def main() -> int:
    r1_rows, r1_status, _ = read_csv(R1_CONTRIB)
    if r1_status != "OK":
        r1_rows = []
    candidate_tickers = {row["ticker"] for row in r1_rows if row.get("ticker")}
    new_contribs, source_audit = collect_missing_family_sources(candidate_tickers)

    expanded_rows: list[dict[str, str]] = []
    for row in r1_rows:
        ticker = row["ticker"]
        out = {
            "ticker": ticker,
            "baseline_rank": row.get("baseline_rank", ""),
            "baseline_score_source": row.get("baseline_score_source", ""),
            "contribution_source_artifacts": row.get("contribution_source_artifact", ""),
            "contribution_source_stages": row.get("contribution_source_stage", ""),
            **safety(extra=True),
        }
        sources = {item for item in clean(out["contribution_source_artifacts"]).split(";") if item}
        stages = {item for item in clean(out["contribution_source_stages"]).split(";") if item}
        materialized: list[str] = []
        missing: list[str] = []
        contribution_sum = 0.0
        for family in FAMILIES:
            column = FAMILY_COLUMNS[family]
            value = row.get(column, "")
            if family in MISSING_TARGETS and value == "" and ticker in new_contribs[family]:
                normalized, path, _ = new_contribs[family][ticker]
                value = fmt(normalized)
                sources.add(rel(path))
                stages.add(source_stage(path))
            out[column] = value
            if value != "":
                materialized.append(family)
                contribution_sum += float(value)
            else:
                missing.append(family)
        if len(materialized) == len(FAMILIES):
            status = "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION"
            granularity = "CANDIDATE_FACTOR_FAMILY_COMPLETE_GRANULARITY"
        elif materialized:
            status = "PARTIAL_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION"
            granularity = "CANDIDATE_FACTOR_FAMILY_PARTIAL_GRANULARITY"
        else:
            status = "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION"
            granularity = "LIMITED_CANDIDATE_FACTOR_GRANULARITY"
        out.update({
            "contribution_sum": fmt(contribution_sum) if materialized else "",
            "contribution_normalization_status": "CARRIED_FORWARD_AND_EXPANDED_REAL_NUMERIC_CONTRIBUTIONS" if materialized else "NO_CONTRIBUTION_DATA_TO_NORMALIZE",
            "contribution_status": status,
            "missing_factor_families": ";".join(missing),
            "materialized_factor_families": ";".join(materialized),
            "contribution_source_artifacts": ";".join(sorted(sources)),
            "contribution_source_stages": ";".join(sorted(stages)),
            "candidate_factor_granularity_status": granularity,
            "usable_for_shadow_rerank": tf(len(materialized) == len(FAMILIES)),
        })
        expanded_rows.append(out)

    material_rows: list[dict[str, str]] = []
    coverage_ratios: dict[str, float] = {}
    for family in FAMILIES:
        column = FAMILY_COLUMNS[family]
        r1_count = sum(1 for row in r1_rows if row.get(column, "") != "")
        total_count = sum(1 for row in expanded_rows if row.get(column, "") != "")
        new_count = max(0, total_count - r1_count)
        ratio = total_count / len(expanded_rows) if expanded_rows else 0.0
        coverage_ratios[family] = ratio
        if family in MISSING_TARGETS:
            family_sources = sorted({
                rel(path)
                for _, path, _ in new_contribs[family].values()
            })
        else:
            family_sources = sorted({
                source
                for row in r1_rows
                if row.get(column, "") != ""
                for source in row.get("contribution_source_artifact", "").split(";")
                if source
            })
        material_rows.append({
            "factor_family": family,
            "candidate_count": str(len(expanded_rows)),
            "r1_candidates_with_contribution": str(r1_count),
            "new_candidates_materialized": str(new_count),
            "total_candidates_with_contribution": str(total_count),
            "coverage_ratio": fmt(ratio),
            "materialization_status": "COMPLETE_CANDIDATE_COVERAGE" if ratio == 1.0 else ("PARTIAL_CANDIDATE_COVERAGE" if total_count else "MISSING_CANDIDATE_COVERAGE"),
            "source_artifacts": ";".join(family_sources),
            "materialization_blocker_reason": "" if total_count else "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION",
            "source_rank_or_score_used_as_contribution": "FALSE",
            "baseline_rank_used_as_contribution": "FALSE",
            "contribution_scores_fabricated": "FALSE",
            "usable_for_shadow_rerank": tf(ratio == 1.0),
            **safety(),
        })

    complete_count = sum(1 for row in expanded_rows if row["contribution_status"] == "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION")
    partial_count = sum(1 for row in expanded_rows if row["contribution_status"] == "PARTIAL_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION")
    missing_count = sum(1 for row in expanded_rows if row["contribution_status"] == "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION")
    usable_count = sum(1 for row in expanded_rows if row["usable_for_shadow_rerank"] == "TRUE")
    ready = complete_count == len(expanded_rows) and bool(expanded_rows)
    readiness_rows = [{
        "readiness_check_id": "V20_108_R2_READINESS_001",
        "candidate_count": str(len(expanded_rows)),
        "complete_six_family_contribution_candidate_count": str(complete_count),
        "partial_contribution_candidate_count": str(partial_count),
        "missing_contribution_candidate_count": str(missing_count),
        "usable_for_shadow_rerank_count": str(usable_count),
        "technical_coverage_ratio": fmt(coverage_ratios.get("TECHNICAL", 0.0)),
        "data_trust_coverage_ratio": fmt(coverage_ratios.get("DATA_TRUST", 0.0)),
        "fundamental_coverage_ratio": fmt(coverage_ratios.get("FUNDAMENTAL", 0.0)),
        "strategy_coverage_ratio": fmt(coverage_ratios.get("STRATEGY", 0.0)),
        "risk_coverage_ratio": fmt(coverage_ratios.get("RISK", 0.0)),
        "market_regime_coverage_ratio": fmt(coverage_ratios.get("MARKET_REGIME", 0.0)),
        "shadow_rerank_readiness_status": "READY_FOR_SHADOW_RERANK" if ready else "NOT_READY_PARTIAL_CANDIDATE_FACTOR_FAMILY_COVERAGE",
        "shadow_rerank_blocker_reason": "" if ready else "MISSING_COMPLETE_SIX_FAMILY_CANDIDATE_LEVEL_CONTRIBUTIONS",
        **safety(extra=True),
    }]

    status = PASS_STATUS if ready else (PARTIAL_STATUS if partial_count else MISSING_STATUS)
    write_csv(OUT_EXPANDED, EXPANDED_FIELDS, expanded_rows)
    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_audit)
    write_csv(OUT_MATERIAL, MATERIAL_FIELDS, material_rows)
    write_csv(OUT_READINESS, READINESS_FIELDS, readiness_rows)

    lines = [
        "# V20.108-R2 Missing Factor-Family Contribution Source Expander",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_count: {len(expanded_rows)}",
        f"- complete_six_family_contribution_candidate_count: {complete_count}",
        f"- partial_contribution_candidate_count: {partial_count}",
        f"- usable_for_shadow_rerank_count: {usable_count}",
        "- source_rank_or_score_used_as_contribution: FALSE",
        "- baseline_rank_used_as_contribution: FALSE",
        "- contribution_scores_fabricated: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_ranking: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(status)
    print(f"CANDIDATE_COUNT={len(expanded_rows)}")
    print(f"COMPLETE_SIX_FAMILY_CONTRIBUTION_CANDIDATE_COUNT={complete_count}")
    print(f"PARTIAL_CONTRIBUTION_CANDIDATE_COUNT={partial_count}")
    print(f"USABLE_FOR_SHADOW_RERANK_COUNT={usable_count}")
    print("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE")
    print("BASELINE_RANK_USED_AS_CONTRIBUTION=FALSE")
    print("CONTRIBUTION_SCORES_FABRICATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_EXPANDED={rel(OUT_EXPANDED)}")
    print(f"OUTPUT_SOURCE_AUDIT={rel(OUT_SOURCE)}")
    print(f"OUTPUT_MATERIALIZATION_AUDIT={rel(OUT_MATERIAL)}")
    print(f"OUTPUT_READINESS={rel(OUT_READINESS)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
