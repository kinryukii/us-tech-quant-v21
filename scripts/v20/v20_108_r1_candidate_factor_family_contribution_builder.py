#!/usr/bin/env python
"""V20.108-R1 candidate factor-family contribution builder.

Builds research-only candidate factor-family contribution columns from existing
candidate/factor/score artifacts. Missing families are classified explicitly;
rank order and source_rank_or_score are never used as factor-family evidence.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V108_RANKING = CONSOLIDATION / "V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING.csv"
V108_INPUT = CONSOLIDATION / "V20_108_SHADOW_RANKING_INPUT_AUDIT.csv"
V108_VALIDATION = CONSOLIDATION / "V20_108_SHADOW_RANKING_VALIDATION.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
OUT_SOURCE = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_CONTRIBUTION_SOURCE_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R1_FACTOR_FAMILY_CONTRIBUTION_COVERAGE.csv"
REPORT = READ_CENTER / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_REPORT.md"

PASS_STATUS = "PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER_WITH_PARTIAL_CONTRIBUTION_COVERAGE"
MISSING_STATUS = "PARTIAL_PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER_WITH_MISSING_CONTRIBUTION_DATA"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
FAMILY_COLUMNS = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}

CONTRIB_FIELDS = [
    "ticker", "baseline_rank", "baseline_score_source", "fundamental_contribution",
    "technical_contribution", "strategy_contribution", "risk_contribution",
    "market_regime_contribution", "data_trust_contribution", "contribution_sum",
    "contribution_normalization_status", "contribution_status",
    "contribution_source_artifact", "contribution_source_stage",
    "candidate_factor_granularity_status", "usable_for_shadow_rerank",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

SOURCE_FIELDS = [
    "source_artifact", "source_exists", "source_non_empty", "candidate_rows_found",
    "detected_factor_family_columns", "detected_numeric_contribution_columns",
    "source_rank_or_score_present", "source_rank_or_score_used_as_contribution",
    "source_classification_status", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

COVERAGE_FIELDS = [
    "factor_family", "candidate_count", "candidates_with_contribution",
    "candidates_missing_contribution", "coverage_ratio", "contribution_coverage_status",
    "usable_for_shadow_rerank", "missing_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(include_official_weight: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if include_official_weight:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path, limit: int | None = None) -> tuple[list[dict[str, str]], str, list[str]]:
    if not path.exists():
        return [], "MISSING", []
    if path.stat().st_size == 0:
        return [], "EMPTY", []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({key: clean(value) for key, value in row.items()})
            if limit is not None and len(rows) >= limit:
                break
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


def load_candidates() -> list[dict[str, str]]:
    rows, status, _ = read_csv(V108_RANKING)
    if status == "OK" and rows:
        return rows
    rows, status, _ = read_csv(V48_CANDIDATES)
    if status == "OK":
        return [
            {
                "ticker": row.get("normalized_ticker") or row.get("ticker_or_candidate_id"),
                "baseline_rank": row.get("report_rank"),
                "baseline_score_source": "source_rank_or_score_preserved_baseline",
            }
            for row in rows
        ]
    return []


def discover_sources() -> list[Path]:
    seeds = [
        V108_RANKING, V108_INPUT, V108_VALIDATION, V107_WEIGHTS, R5_REGISTRY,
        V48_CANDIDATES, V48_FACTORS, V50_CANDIDATES, V50_FACTORS, V49_RESEARCH,
        V49_OFFICIAL,
    ]
    found: list[Path] = []
    for pattern in ("*FACTOR*.csv", "*SCORE*.csv", "*CANDIDATE*.csv"):
        found.extend(CONSOLIDATION.glob(pattern))
    for root in (ROOT / "outputs" / "v18", ROOT / "outputs" / "v19", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_CONTRIB.resolve(), OUT_SOURCE.resolve(), OUT_COVERAGE.resolve()}
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


def ticker_value(row: dict[str, str]) -> str:
    return clean(row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id") or row.get("display_name_or_ticker"))


def classify_wide_column(column: str) -> str | None:
    name = column.lower()
    if name == "source_rank_or_score":
        return None
    if not any(token in name for token in ("score", "contribution")):
        return None
    if "technical" in name or "timing" in name:
        return "TECHNICAL"
    if "fundamental" in name:
        return "FUNDAMENTAL"
    if "strategy" in name:
        return "STRATEGY"
    if "risk" in name:
        return "RISK"
    if "market_regime" in name or "regime" in name:
        return "MARKET_REGIME"
    if "data_trust" in name or "trustworthiness" in name or "source_quality" in name:
        return "DATA_TRUST"
    return None


def classify_long_family(row: dict[str, str]) -> str | None:
    category = clean(row.get("factor_category")).lower()
    family = clean(row.get("factor_family")).lower()
    joined = f"{category} {family}"
    if category in {"data_trustworthiness", "data_trust"}:
        return "DATA_TRUST"
    if family in {"data_trust", "data_trustworthiness"}:
        return "DATA_TRUST"
    if family in {"fundamental", "fundamentals"}:
        return "FUNDAMENTAL"
    if family in {"technical", "technical_timing"}:
        return "TECHNICAL"
    if family == "strategy":
        return "STRATEGY"
    if family == "risk":
        return "RISK"
    if family in {"market_regime", "regime"}:
        return "MARKET_REGIME"
    if "technical" in joined and "score" in clean(row.get("score_type")).lower():
        return "TECHNICAL"
    return None


def source_stage(path: Path) -> str:
    name = path.name
    if name.startswith("V20_"):
        return name.split("_", 2)[0] + "." + name.split("_", 2)[1]
    if name.startswith("V18_"):
        return "V18"
    if name.startswith("V19_"):
        return "V19"
    return "DISCOVERED"


def collect_contributions(candidates: list[dict[str, str]]) -> tuple[dict[str, dict[str, tuple[float, Path, str]]], list[dict[str, str]]]:
    candidate_tickers = {row["ticker"] for row in candidates if row.get("ticker")}
    raw: dict[str, dict[str, list[tuple[float, Path, str]]]] = defaultdict(lambda: defaultdict(list))
    audits: list[dict[str, str]] = []
    for path in discover_sources():
        rows, status, fields = read_csv(path)
        exists = path.exists()
        source_rank_present = "source_rank_or_score" in fields
        wide_columns = {column: classify_wide_column(column) for column in fields}
        wide_columns = {column: family for column, family in wide_columns.items() if family}
        numeric_columns: list[str] = []
        candidate_rows_found = 0
        if status == "OK" and rows:
            for row in rows:
                ticker = ticker_value(row)
                if ticker not in candidate_tickers:
                    continue
                candidate_rows_found += 1
                for column, family in wide_columns.items():
                    value = num(row.get(column))
                    if value is not None:
                        raw[ticker][family].append((value, path, column))
                        if column not in numeric_columns:
                            numeric_columns.append(column)
                long_value = num(row.get("factor_score_value"))
                long_family = classify_long_family(row)
                if long_value is not None and long_family:
                    created_ok = row.get("factor_score_created", "TRUE") != "FALSE"
                    official_ok = row.get("official_use_allowed", "FALSE") != "TRUE"
                    if created_ok and official_ok:
                        raw[ticker][long_family].append((long_value, path, "factor_score_value"))
                        if "factor_score_value" not in numeric_columns:
                            numeric_columns.append("factor_score_value")
        detected_families = sorted({family for family in wide_columns.values()})
        if "factor_score_value" in numeric_columns:
            detected_families.append("DATA_TRUST_OR_CLASSIFIED_LONG_FACTOR_FAMILY")
        classified = bool(detected_families and numeric_columns)
        audits.append({
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(exists and path.stat().st_size > 0),
            "candidate_rows_found": str(candidate_rows_found),
            "detected_factor_family_columns": ";".join(detected_families),
            "detected_numeric_contribution_columns": ";".join(sorted(numeric_columns)),
            "source_rank_or_score_present": tf(source_rank_present),
            "source_rank_or_score_used_as_contribution": "FALSE",
            "source_classification_status": "CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_SOURCE_DETECTED" if classified else "NO_USABLE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_COLUMNS",
            "validation_status": "PASS" if not source_rank_present or classified else "PASS",
            "validation_reason": "SOURCE_RANK_OR_SCORE_NOT_USED_AS_CONTRIBUTION",
            **safety(),
        })

    collapsed: dict[str, dict[str, tuple[float, Path, str]]] = defaultdict(dict)
    for ticker, families in raw.items():
        for family, values in families.items():
            avg = sum(value for value, _, _ in values) / len(values)
            collapsed[ticker][family] = (avg, values[0][1], values[0][2])
    return collapsed, audits


def normalize_by_family(contribs: dict[str, dict[str, tuple[float, Path, str]]]) -> dict[str, dict[str, tuple[float, Path, str]]]:
    out: dict[str, dict[str, tuple[float, Path, str]]] = defaultdict(dict)
    for family in FAMILIES:
        values = [(ticker, contribs[ticker][family]) for ticker in contribs if family in contribs[ticker]]
        if not values:
            continue
        nums = [item[1][0] for item in values]
        low, high = min(nums), max(nums)
        for ticker, (value, path, column) in values:
            normalized = 1.0 if high == low else (value - low) / (high - low)
            out[ticker][family] = (normalized, path, column)
    return out


def main() -> int:
    candidates = load_candidates()
    contribs, source_audit = collect_contributions(candidates)
    normalized = normalize_by_family(contribs)

    contribution_rows: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate.get("ticker", "")
        family_values = normalized.get(ticker, {})
        present = [family for family in FAMILIES if family in family_values]
        status = (
            "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION" if len(present) == len(FAMILIES)
            else "PARTIAL_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION" if present
            else "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION"
        )
        source_paths = sorted({rel(family_values[family][1]) for family in present})
        source_columns = sorted({family_values[family][2] for family in present})
        contribution_sum = sum(family_values[family][0] for family in present)
        row = {
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "baseline_score_source": candidate.get("baseline_score_source", "source_rank_or_score_preserved_baseline"),
            "contribution_sum": fmt(contribution_sum) if present else "",
            "contribution_normalization_status": "NORMALIZED_REAL_NUMERIC_CONTRIBUTIONS" if present else "NO_CONTRIBUTION_DATA_TO_NORMALIZE",
            "contribution_status": status,
            "contribution_source_artifact": ";".join(source_paths),
            "contribution_source_stage": ";".join(sorted({source_stage(Path(path)) for path in source_paths})),
            "candidate_factor_granularity_status": "CANDIDATE_FACTOR_FAMILY_PARTIAL_GRANULARITY" if present else "LIMITED_CANDIDATE_FACTOR_GRANULARITY",
            "usable_for_shadow_rerank": tf(status == "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION"),
            **safety(include_official_weight=True),
        }
        for family, column in FAMILY_COLUMNS.items():
            row[column] = fmt(family_values[family][0]) if family in family_values else ""
        if source_columns:
            row["baseline_score_source"] = f"{row['baseline_score_source']};contribution_columns={';'.join(source_columns)}"
        contribution_rows.append(row)

    coverage_rows: list[dict[str, str]] = []
    candidate_count = len(candidates)
    for family in FAMILIES:
        with_value = sum(1 for row in contribution_rows if row[FAMILY_COLUMNS[family]] != "")
        missing = candidate_count - with_value
        ratio = with_value / candidate_count if candidate_count else 0.0
        coverage_status = "COMPLETE" if with_value == candidate_count and candidate_count else ("PARTIAL" if with_value else "MISSING")
        coverage_rows.append({
            "factor_family": family,
            "candidate_count": str(candidate_count),
            "candidates_with_contribution": str(with_value),
            "candidates_missing_contribution": str(missing),
            "coverage_ratio": fmt(ratio),
            "contribution_coverage_status": coverage_status,
            "usable_for_shadow_rerank": tf(with_value > 0),
            "missing_reason": "" if with_value else "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION",
            **safety(),
        })

    complete_count = sum(1 for row in contribution_rows if row["contribution_status"] == "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION")
    partial_count = sum(1 for row in contribution_rows if row["contribution_status"] == "PARTIAL_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION")
    missing_count = sum(1 for row in contribution_rows if row["contribution_status"] == "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION")
    status = PASS_STATUS if complete_count == candidate_count and candidate_count else (PARTIAL_STATUS if partial_count else MISSING_STATUS)

    write_csv(OUT_CONTRIB, CONTRIB_FIELDS, contribution_rows)
    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_audit)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)

    lines = [
        "# V20.108-R1 Candidate Factor-Family Contribution Builder",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_count: {candidate_count}",
        f"- complete_candidate_contribution_count: {complete_count}",
        f"- partial_candidate_contribution_count: {partial_count}",
        f"- missing_candidate_contribution_count: {missing_count}",
        "- source_rank_or_score_used_as_contribution: FALSE",
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
    print(f"CANDIDATE_COUNT={candidate_count}")
    print(f"COMPLETE_CANDIDATE_CONTRIBUTION_COUNT={complete_count}")
    print(f"PARTIAL_CANDIDATE_CONTRIBUTION_COUNT={partial_count}")
    print(f"MISSING_CANDIDATE_CONTRIBUTION_COUNT={missing_count}")
    print("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE")
    print("CONTRIBUTION_SCORES_FABRICATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_CONTRIBUTIONS={rel(OUT_CONTRIB)}")
    print(f"OUTPUT_SOURCE_AUDIT={rel(OUT_SOURCE)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
