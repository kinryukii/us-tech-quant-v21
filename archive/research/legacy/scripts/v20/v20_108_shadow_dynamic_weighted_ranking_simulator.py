#!/usr/bin/env python
"""V20.108 research-only shadow dynamic weighted ranking simulator.

Simulates candidate ranking under V20.107 shadow factor-family weights. When
candidate-level factor-family contribution columns are unavailable, this stage
preserves the current baseline order and explicitly records limited candidate
factor granularity instead of fabricating candidate factor scores.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
V107_CHANGE = CONSOLIDATION / "V20_107_SHADOW_WEIGHT_CHANGE_AUDIT.csv"
V107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_RANKING = CONSOLIDATION / "V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING.csv"
OUT_CHANGE = CONSOLIDATION / "V20_108_SHADOW_RANK_CHANGE_AUDIT.csv"
OUT_INPUT = CONSOLIDATION / "V20_108_SHADOW_RANKING_INPUT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_SHADOW_RANKING_VALIDATION.csv"
REPORT = READ_CENTER / "V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_REPORT.md"

PASS_STATUS = "PASS_V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR"
PARTIAL_GRANULARITY = "PARTIAL_PASS_V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR_WITH_LIMITED_CANDIDATE_FACTOR_GRANULARITY"
BLOCKED_STATUS = "BLOCKED_V20_108_NO_VALID_SHADOW_DYNAMIC_WEIGHTS"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
SCOPE = "RESEARCH_ONLY_SHADOW_FACTOR_FAMILY"

RANKING_FIELDS = [
    "ticker", "baseline_rank", "baseline_score_source", "baseline_score",
    "shadow_dynamic_rank", "shadow_dynamic_score", "rank_change",
    "rank_change_direction", "shadow_ranking_method",
    "candidate_factor_granularity_status", "dynamic_weight_scope",
    "shadow_weight_confidence", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

CHANGE_FIELDS = [
    "ticker", "baseline_rank", "shadow_dynamic_rank", "rank_change",
    "absolute_rank_change", "rank_change_bucket", "rank_change_reason",
    "dynamic_weight_source_stage", "candidate_score_source_status",
    "validation_status", "validation_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

INPUT_FIELDS = [
    "input_check_id", "source_artifact", "artifact_exists", "artifact_non_empty",
    "row_count", "input_status", "input_reason", "shadow_weights_recognized",
    "v20_107_limited_factor_granularity_recognized",
    "candidate_factor_family_columns_available",
    "source_rank_or_score_used_as_factor_weight",
    "candidate_factor_scores_fabricated", "factor_level_weights_created",
    "authoritative_ranking_overwritten", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count", "unique_ticker_count",
    "shadow_rank_count", "duplicate_ticker_count", "shadow_weights_available",
    "shadow_weight_sum_valid", "factor_level_weights_created",
    "candidate_factor_granularity_status", "official_ranking_created",
    "authoritative_ranking_overwritten", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
    "validation_status", "validation_reason", "research_only",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "is_official_ranking": "FALSE",
        "is_official_weight": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }


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


def fmt(value: float, places: int = 10) -> str:
    return f"{value:.{places}f}"


def load_shadow_weight_state() -> tuple[bool, bool, str, dict[str, float], str]:
    weight_rows, weight_status, _ = read_csv(V107_WEIGHTS)
    validation_rows, validation_status, _ = read_csv(V107_VALIDATION)
    valid_rows = [
        row for row in weight_rows
        if row.get("factor_family") in FAMILIES
        and row.get("shadow_weight_activation_scope") == "RESEARCH_ONLY_SHADOW"
        and row.get("is_official_weight") == "FALSE"
    ]
    weights = {
        row["factor_family"]: (num(row.get("normalized_shadow_dynamic_weight")) or 0.0)
        for row in valid_rows
    }
    validation = validation_rows[0] if validation_rows else {}
    weight_sum_valid = (
        validation.get("shadow_weight_sum_valid") == "TRUE"
        or validation.get("weight_sum_valid") == "TRUE"
    )
    scope_valid = validation.get("dynamic_factor_weight_scope") == SCOPE
    factor_level_created = validation.get("factor_level_weights_created") == "TRUE"
    available = (
        weight_status == "OK"
        and validation_status == "OK"
        and set(weights) == set(FAMILIES)
        and abs(sum(weights.values()) - 1.0) <= 1e-8
        and weight_sum_valid
        and scope_valid
        and not factor_level_created
    )
    limited = any(row.get("factor_granularity_status") == "LIMITED_FACTOR_GRANULARITY" for row in valid_rows)
    confidence_values = {row.get("shadow_weight_confidence") for row in valid_rows}
    confidence = "PARTIAL" if "PARTIAL" in confidence_values or limited else "HIGH"
    return available, limited, confidence, weights, validation.get("dynamic_factor_weight_scope", "")


def candidate_rows() -> tuple[list[dict[str, str]], list[str], str]:
    rows, status, fields = read_csv(V48_CANDIDATES)
    if status == "OK" and rows:
        return rows, fields, "V20.48_REFRESHED_CANDIDATE_RESEARCH_VIEW"
    rows, status, fields = read_csv(V50_CANDIDATES)
    return rows, fields, "V20.50_CANDIDATE_RESEARCH_DECISION_PACKET" if status == "OK" and rows else "MISSING_CANDIDATE_SOURCE"


def contribution_columns(fields: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    lowered = {field.lower(): field for field in fields}
    for family in FAMILIES:
        tokens = [
            f"{family.lower()}_contribution",
            f"{family.lower()}_score",
            f"{family.lower()}_normalized_contribution",
            f"{family.lower()}_factor_family_score",
        ]
        for token in tokens:
            if token in lowered:
                out[family] = lowered[token]
                break
    return out


def baseline_rank(row: dict[str, str], index: int) -> int:
    for key in ("report_rank", "baseline_rank", "rank"):
        value = num(row.get(key))
        if value is not None:
            return int(value)
    return index


def baseline_score(row: dict[str, str], rank: int) -> float:
    score = num(row.get("source_rank_or_score"))
    if score is not None:
        return score
    # Deterministic preserved-order score; this is not used as a factor weight.
    return float(-rank)


def direction(change: int) -> str:
    if change > 0:
        return "RANK_IMPROVED"
    if change < 0:
        return "RANK_DECLINED"
    return "UNCHANGED"


def bucket(abs_change: int) -> str:
    if abs_change == 0:
        return "NO_CHANGE"
    if abs_change <= 5:
        return "SMALL_1_5"
    if abs_change <= 20:
        return "MEDIUM_6_20"
    return "LARGE_GT_20"


def input_audit(
    shadow_available: bool,
    limited_v107: bool,
    candidate_factor_columns: bool,
    candidate_count: int,
) -> list[dict[str, str]]:
    sources = [
        V107_WEIGHTS, V107_CHANGE, V107_VALIDATION, R5_REGISTRY, V48_CANDIDATES,
        V48_FACTORS, V50_CANDIDATES, V50_FACTORS, V49_RESEARCH, V49_OFFICIAL,
    ]
    rows = []
    for idx, path in enumerate(sources, start=1):
        data, status, _ = read_csv(path)
        if path == V48_CANDIDATES:
            row_count = candidate_count
        else:
            row_count = len(data) if status == "OK" else 0
        rows.append({
            "input_check_id": f"V20_108_INPUT_{idx:03d}",
            "source_artifact": rel(path),
            "artifact_exists": tf(path.exists()),
            "artifact_non_empty": tf(path.exists() and path.stat().st_size > 0),
            "row_count": str(row_count),
            "input_status": "PASS" if status == "OK" and (data or path == V48_FACTORS) else "WARN_MISSING_OR_EMPTY",
            "input_reason": "READ_ONLY_INPUT_FOR_RESEARCH_ONLY_SHADOW_RANKING",
            "shadow_weights_recognized": tf(shadow_available),
            "v20_107_limited_factor_granularity_recognized": tf(limited_v107),
            "candidate_factor_family_columns_available": tf(candidate_factor_columns),
            "source_rank_or_score_used_as_factor_weight": "FALSE",
            "candidate_factor_scores_fabricated": "FALSE",
            "factor_level_weights_created": "FALSE",
            "authoritative_ranking_overwritten": "FALSE",
            **safety(),
        })
    return rows


def main() -> int:
    shadow_available, limited_v107, shadow_confidence, weights, scope = load_shadow_weight_state()
    candidates, fields, candidate_source = candidate_rows()
    family_columns = contribution_columns(fields)
    factor_columns_available = set(family_columns) == set(FAMILIES)
    candidate_granularity = (
        "CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS_AVAILABLE"
        if factor_columns_available
        else "LIMITED_CANDIDATE_FACTOR_GRANULARITY"
    )

    if not shadow_available:
        ranking_rows: list[dict[str, str]] = []
        change_rows: list[dict[str, str]] = []
        validation_status = "BLOCKED"
        validation_reason = "NO_VALID_V20_107_RESEARCH_ONLY_SHADOW_FACTOR_FAMILY_WEIGHTS"
        status = BLOCKED_STATUS
    else:
        scored: list[dict[str, object]] = []
        for index, row in enumerate(candidates, start=1):
            ticker = row.get("normalized_ticker") or row.get("ticker") or row.get("ticker_or_candidate_id") or row.get("display_name_or_ticker")
            base_rank = baseline_rank(row, index)
            base_score = baseline_score(row, base_rank)
            if factor_columns_available:
                contribution_values = {
                    family: num(row.get(column))
                    for family, column in family_columns.items()
                }
                if all(value is not None for value in contribution_values.values()):
                    shadow_score = sum((contribution_values[family] or 0.0) * weights[family] for family in FAMILIES)
                    method = "WEIGHTED_FACTOR_FAMILY_CONTRIBUTION_SCORE"
                    score_status = "CANDIDATE_FACTOR_FAMILY_SCORE_AVAILABLE"
                else:
                    shadow_score = base_score
                    method = "BASELINE_ORDER_PRESERVED_MISSING_CANDIDATE_FACTOR_VALUES"
                    score_status = "CANDIDATE_FACTOR_FAMILY_SCORE_MISSING_VALUES"
            else:
                shadow_score = base_score
                method = "BASELINE_ORDER_PRESERVED_LIMITED_CANDIDATE_FACTOR_GRANULARITY"
                score_status = "BASELINE_SCORE_PRESERVED_NOT_USED_AS_FACTOR_WEIGHT"
            scored.append({
                "ticker": clean(ticker),
                "baseline_rank": base_rank,
                "baseline_score": base_score,
                "shadow_score": shadow_score,
                "method": method,
                "score_status": score_status,
            })

        if factor_columns_available:
            ordered = sorted(scored, key=lambda item: (-float(item["shadow_score"]), int(item["baseline_rank"]), str(item["ticker"])))
            shadow_rank = {str(item["ticker"]): index for index, item in enumerate(ordered, start=1)}
        else:
            shadow_rank = {str(item["ticker"]): int(item["baseline_rank"]) for item in scored}

        ranking_rows = []
        change_rows = []
        for item in sorted(scored, key=lambda item: int(item["baseline_rank"])):
            ticker = str(item["ticker"])
            base_rank = int(item["baseline_rank"])
            dyn_rank = shadow_rank[ticker]
            rank_change = base_rank - dyn_rank
            abs_change = abs(rank_change)
            ranking_rows.append({
                "ticker": ticker,
                "baseline_rank": str(base_rank),
                "baseline_score_source": "source_rank_or_score_preserved_baseline",
                "baseline_score": fmt(float(item["baseline_score"])),
                "shadow_dynamic_rank": str(dyn_rank),
                "shadow_dynamic_score": fmt(float(item["shadow_score"])),
                "rank_change": str(rank_change),
                "rank_change_direction": direction(rank_change),
                "shadow_ranking_method": str(item["method"]),
                "candidate_factor_granularity_status": candidate_granularity,
                "dynamic_weight_scope": SCOPE if scope == SCOPE else clean(scope),
                "shadow_weight_confidence": shadow_confidence,
                **safety(),
            })
            change_rows.append({
                "ticker": ticker,
                "baseline_rank": str(base_rank),
                "shadow_dynamic_rank": str(dyn_rank),
                "rank_change": str(rank_change),
                "absolute_rank_change": str(abs_change),
                "rank_change_bucket": bucket(abs_change),
                "rank_change_reason": "NO_RANK_CHANGE_BASELINE_PRESERVED_DUE_TO_LIMITED_CANDIDATE_FACTOR_GRANULARITY" if abs_change == 0 and not factor_columns_available else "SHADOW_WEIGHTED_RANK_CHANGE_SIMULATED",
                "dynamic_weight_source_stage": "V20.107_RESEARCH_ONLY_SHADOW_FACTOR_FAMILY_WEIGHTS",
                "candidate_score_source_status": str(item["score_status"]),
                "validation_status": "PASS",
                "validation_reason": "RESEARCH_ONLY_SHADOW_RANKING_NO_AUTHORITATIVE_ARTIFACT_OVERWRITE",
                **safety(),
            })

        validation_status = "PASS"
        validation_reason = (
            "SHADOW_RANKING_PRESERVED_BASELINE_ORDER_DUE_TO_LIMITED_CANDIDATE_FACTOR_GRANULARITY"
            if not factor_columns_available
            else "SHADOW_RANKING_SIMULATED_WITH_FACTOR_FAMILY_CONTRIBUTIONS"
        )
        status = PARTIAL_GRANULARITY if not factor_columns_available or limited_v107 else PASS_STATUS

    tickers = [row.get("ticker", "") for row in ranking_rows]
    duplicate_count = len(tickers) - len(set(tickers))
    validation_rows = [{
        "validation_check_id": "V20_108_VALIDATION_001",
        "candidate_count": str(len(candidates)),
        "unique_ticker_count": str(len(set(tickers))),
        "shadow_rank_count": str(len(ranking_rows)),
        "duplicate_ticker_count": str(duplicate_count),
        "shadow_weights_available": tf(shadow_available),
        "shadow_weight_sum_valid": tf(shadow_available),
        "factor_level_weights_created": "FALSE",
        "candidate_factor_granularity_status": candidate_granularity,
        "official_ranking_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
    }]

    input_rows = input_audit(shadow_available, limited_v107, factor_columns_available, len(candidates))

    write_csv(OUT_RANKING, RANKING_FIELDS, ranking_rows)
    write_csv(OUT_CHANGE, CHANGE_FIELDS, change_rows)
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)

    lines = [
        "# V20.108 Shadow Dynamic Weighted Ranking Simulator",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_source: {candidate_source}",
        f"- candidate_count: {len(candidates)}",
        f"- shadow_rank_count: {len(ranking_rows)}",
        f"- shadow_weights_available: {tf(shadow_available)}",
        f"- shadow_weight_sum_valid: {tf(shadow_available)}",
        f"- v20_107_limited_factor_granularity_recognized: {tf(limited_v107)}",
        f"- candidate_factor_granularity_status: {candidate_granularity}",
        "- factor_level_weights_created: FALSE",
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
    print(f"CANDIDATE_COUNT={len(candidates)}")
    print(f"SHADOW_RANK_COUNT={len(ranking_rows)}")
    print(f"SHADOW_WEIGHTS_AVAILABLE={tf(shadow_available)}")
    print(f"SHADOW_WEIGHT_SUM_VALID={tf(shadow_available)}")
    print(f"V20_107_LIMITED_FACTOR_GRANULARITY_RECOGNIZED={tf(limited_v107)}")
    print(f"CANDIDATE_FACTOR_GRANULARITY_STATUS={candidate_granularity}")
    print("FACTOR_LEVEL_WEIGHTS_CREATED=FALSE")
    print("CANDIDATE_FACTOR_SCORES_FABRICATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_RANKING={rel(OUT_RANKING)}")
    print(f"OUTPUT_RANK_CHANGE_AUDIT={rel(OUT_CHANGE)}")
    print(f"OUTPUT_INPUT_AUDIT={rel(OUT_INPUT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0 if shadow_available else 1


if __name__ == "__main__":
    raise SystemExit(main())
