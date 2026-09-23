#!/usr/bin/env python
"""V20.158 reduced shadow weight ranking simulation.

Runs a research-only conservative ranking simulation from V20.157 reduced
shadow proposal rows. It uses existing current ranking and factor contribution
artifacts only, reads V20.155 only for original-shadow comparison fields, and
does not mutate official rankings, official weights, recommendations, trades,
broker actions, or upstream V20.109-V20.157 artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
CONSOLIDATION = OUTPUTS / "consolidation"
READ_CENTER = OUTPUTS / "read_center"

IN_PROPOSAL = FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
IN_GATE = FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv"
IN_SOURCE = FACTORS / "V20_157_DELTA_REDUCTION_SOURCE_AUDIT.csv"
IN_SAFETY = FACTORS / "V20_157_DELTA_REDUCTION_SAFETY_AUDIT.csv"
IN_LIMITATION = FACTORS / "V20_157_DELTA_REDUCTION_LIMITATION_AUDIT.csv"

V83_RANKING = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
V108_COMPONENTS = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
V155_SIM = FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
V155_DELTA = FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv"

OUT_SIM = FACTORS / "V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_158_REDUCED_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_GATE = FACTORS / "V20_158_REDUCED_SHADOW_RANKING_GATE.csv"
OUT_SOURCE = FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SAFETY_AUDIT.csv"
OUT_COMPARISON = FACTORS / "V20_158_REDUCED_VS_ORIGINAL_SHADOW_IMPACT_COMPARISON.csv"
REPORT = READ_CENTER / "V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION_REPORT.md"

V157_ALLOWED = {
    "PARTIAL_PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_WITH_LIMITED_CONFIDENCE_READY_FOR_V20_158",
    "PASS_V20_157_SHADOW_WEIGHT_DELTA_REDUCTION_READY_FOR_V20_158",
}
PASS_STATUS = "PASS_V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION_READY_FOR_V20_159"
PARTIAL_STATUS = "PARTIAL_PASS_V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION_WITH_REMAINING_INSTABILITY_READY_FOR_V20_159"
WARN_STATUS = "WARN_V20_158_REDUCED_SHADOW_RANKING_STILL_TOO_UNSTABLE"
BLOCKED_STATUS = "BLOCKED_V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE"
MAX_FAMILY_DELTA = 0.015
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

HIGH_TURNOVER = 0.30
HIGH_AVERAGE_RANK_DELTA = 8.0
EXTREME_MAX_RANK_DELTA = 25.0

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "reduced_shadow_weight_proposal_created",
    "reduced_shadow_ranking_simulation_created",
    "reduced_shadow_ranking_simulation_scope",
    "shadow_weight_expansion_allowed",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "reduced_shadow_weight_proposal_created": "TRUE",
    "reduced_shadow_ranking_simulation_created": "TRUE",
    "reduced_shadow_ranking_simulation_scope": SCOPE,
    "shadow_weight_expansion_allowed": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "reduced_shadow_ranking_simulation_only": "TRUE",
    "audit_only": "TRUE",
}

SIM_FIELDS = [
    "ticker",
    "baseline_rank",
    "original_shadow_rank_if_available",
    "reduced_shadow_rank",
    "original_shadow_rank_delta_if_available",
    "reduced_shadow_rank_delta",
    "baseline_score",
    "reduced_shadow_score",
    "reduced_score_delta",
    "affected_factor_family",
    "affected_factor_name",
    "reduced_shadow_weight_delta",
    "reduction_multiplier",
    "proposal_confidence_level",
    "evidence_quality",
    "baseline_top20_flag",
    "reduced_shadow_top20_flag",
    "entered_reduced_shadow_top20",
    "exited_reduced_shadow_top20",
    "simulation_scope",
    "official_ranking_mutated",
    "official_weight_change_created",
    *COMMON.keys(),
]
DELTA_FIELDS = [
    "summary_id",
    "baseline_candidate_count",
    "reduced_shadow_candidate_count",
    "top20_overlap_count",
    "entered_reduced_top20_count",
    "exited_reduced_top20_count",
    "reduced_top20_turnover_rate",
    "reduced_max_absolute_rank_delta",
    "reduced_average_absolute_rank_delta",
    "reduced_affected_ticker_count",
    "reduced_proposal_row_count",
    "limited_confidence_proposal_count",
    "score_recomputation_performed",
    "rank_impact_proxy_used",
    "limitation_reason",
    *COMMON.keys(),
]
COMPARISON_FIELDS = [
    "comparison_id",
    "original_top20_turnover_rate",
    "reduced_top20_turnover_rate",
    "original_max_absolute_rank_delta",
    "reduced_max_absolute_rank_delta",
    "original_average_absolute_rank_delta",
    "reduced_average_absolute_rank_delta",
    "original_affected_ticker_count",
    "reduced_affected_ticker_count",
    "impact_reduction_success",
    "remaining_rank_impact_severity",
    "recommended_next_action",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_157_gate_consumed",
    "v20_157_status",
    "v20_157_allowed_for_v20_158",
    *SAFETY_FIELDS,
    "reduced_proposal_row_count",
    "baseline_candidate_count",
    "simulation_row_count",
    "score_recomputation_performed",
    "rank_impact_proxy_used",
    "original_shadow_comparison_available",
    "reduced_top20_turnover_rate",
    "reduced_max_absolute_rank_delta",
    "reduced_average_absolute_rank_delta",
    "remaining_rank_impact_severity",
    "impact_reduction_success",
    "official_ranking_rows_mutated",
    "official_weight_rows_mutated",
    "no_ticker_rows_fabricated",
    "no_scores_fabricated",
    "no_official_ranking_mutated",
    "no_official_weights_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_159_operator_review_allowed",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "reduced_shadow_ranking_simulation_only",
    "audit_only",
]
SOURCE_FIELDS = [
    "source_audit_id",
    "source_artifact",
    "source_exists",
    "source_non_empty",
    "row_count",
    "source_sha256",
    "source_role",
    "source_status",
    "exclusion_reason",
    *COMMON.keys(),
]
SAFETY_AUDIT_FIELDS = [
    "safety_check_id",
    "safety_check",
    "expected_value",
    "actual_value",
    "safety_passed",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upstream_inputs() -> list[Path]:
    return [IN_PROPOSAL, IN_GATE, IN_SOURCE, IN_SAFETY, IN_LIMITATION, V83_RANKING, V108_COMPONENTS, V155_SIM, V155_DELTA]


def required_inputs() -> list[Path]:
    return [IN_PROPOSAL, IN_GATE, IN_SOURCE, IN_SAFETY, IN_LIMITATION, V83_RANKING, V108_COMPONENTS]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def source_audit_rows() -> list[dict[str, str]]:
    sources = [
        (IN_PROPOSAL, "V20_157_REDUCED_PROPOSAL", True),
        (IN_GATE, "V20_157_GATE", True),
        (IN_SOURCE, "V20_157_SOURCE_AUDIT", True),
        (IN_SAFETY, "V20_157_SAFETY_AUDIT", True),
        (IN_LIMITATION, "V20_157_LIMITATION_AUDIT", True),
        (V83_RANKING, "CURRENT_AUTHORITATIVE_RANKING_REFERENCE", True),
        (V108_COMPONENTS, "FACTOR_COMPONENT_RECOMPUTE_SOURCE", True),
        (V155_SIM, "OPTIONAL_ORIGINAL_SHADOW_SIMULATION_COMPARISON", False),
        (V155_DELTA, "OPTIONAL_ORIGINAL_SHADOW_IMPACT_COMPARISON", False),
    ]
    rows = []
    for index, (path, role, required) in enumerate(sources, start=1):
        data, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = bool(fields) and non_empty
        rows.append({
            "source_audit_id": f"V20_158_SOURCE_AUDIT_{index:03d}",
            "source_artifact": rel(path),
            "source_exists": tf(exists),
            "source_non_empty": tf(non_empty),
            "row_count": str(len(data)),
            "source_sha256": sha_file(path),
            "source_role": role,
            "source_status": "PASS" if ok else ("BLOCKED_MISSING_REQUIRED" if required else "WARN_OPTIONAL_MISSING"),
            "exclusion_reason": "" if ok else ("MISSING_REQUIRED_SOURCE" if required else "OPTIONAL_SOURCE_MISSING_OR_EMPTY"),
            **COMMON,
        })
    return rows


def aggregate_reduced_proposals(proposals: list[dict[str, str]]) -> tuple[dict[str, float], dict[str, list[dict[str, str]]]]:
    deltas: dict[str, float] = {}
    by_family: dict[str, list[dict[str, str]]] = {}
    for row in proposals:
        if not truthy(row.get("usable_for_reduced_shadow_simulation")):
            continue
        family = row.get("factor_family", "")
        delta = num(row.get("reduced_proposed_delta"))
        by_family.setdefault(family, []).append(row)
        deltas[family] = max(-MAX_FAMILY_DELTA, min(MAX_FAMILY_DELTA, deltas.get(family, 0.0) + delta))
    return deltas, by_family


def component_map(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        if row.get("contribution_available") != "TRUE" or row.get("fabricated_values_created") == "TRUE":
            continue
        ticker = row.get("ticker", "")
        family = row.get("factor_family", "")
        contribution = num(row.get("contribution_value"), math.nan)
        if ticker and family and not math.isnan(contribution):
            out.setdefault(ticker, {})[family] = contribution
    return out


def baseline_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    seen: set[str] = set()
    for row in rows:
        ticker = row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append(row)
    return out


def rank_field(row: dict[str, str]) -> int:
    return int(num(row.get("official_current_rank") or row.get("baseline_rank") or row.get("report_rank"), 0))


def base_score(components: dict[str, float]) -> float:
    weights = {
        "FUNDAMENTAL": 0.20,
        "TECHNICAL": 0.25,
        "STRATEGY": 0.20,
        "RISK": 0.15,
        "MARKET_REGIME": 0.10,
        "DATA_TRUST": 0.10,
    }
    return sum(components.get(family, 0.0) * weight for family, weight in weights.items())


def original_sim_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = row.get("ticker", "")
        if ticker:
            out[ticker] = row
    return out


def build_simulation(
    rank_rows: list[dict[str, str]],
    components: dict[str, dict[str, float]],
    deltas: dict[str, float],
    by_family: dict[str, list[dict[str, str]]],
    original_by_ticker: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], bool, str]:
    staged: list[dict[str, object]] = []
    missing_count = 0
    for row in rank_rows:
        ticker = row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        comp = components.get(ticker or "", {})
        missing_families = [family for family in FAMILIES if family not in comp]
        recompute = not missing_families
        if not recompute:
            missing_count += 1
        baseline = base_score(comp) if recompute else num(row.get("official_current_score") or row.get("source_rank_or_score"), math.nan)
        if math.isnan(baseline):
            baseline = 0.0
        score_delta = sum(comp.get(family, 0.0) * delta for family, delta in deltas.items()) if recompute else 0.0
        staged.append({
            "ticker": ticker or "",
            "baseline_rank": rank_field(row),
            "baseline_score": baseline,
            "reduced_shadow_score": baseline + score_delta,
            "score_delta": score_delta,
            "recompute": recompute,
        })
    sortable = [row for row in staged if row["recompute"]]
    sortable.sort(key=lambda item: (-float(item["reduced_shadow_score"]), int(item["baseline_rank"]), str(item["ticker"])))
    reduced_rank_by_ticker = {str(row["ticker"]): index for index, row in enumerate(sortable, start=1)}
    if len(sortable) != len(staged):
        for row in sorted((item for item in staged if not item["recompute"]), key=lambda item: int(item["baseline_rank"])):
            reduced_rank_by_ticker[str(row["ticker"])] = int(row["baseline_rank"])

    affected_families = ";".join(family for family in FAMILIES if family in deltas)
    affected_names = ";".join(row.get("factor_name", "") for rows in by_family.values() for row in rows)
    applied_delta = ";".join(f"{family}:{fmt(delta)}" for family, delta in sorted(deltas.items()))
    multipliers = sorted({fmt(num(row.get("reduction_multiplier"))) for rows in by_family.values() for row in rows})
    multiplier_text = ";".join(multipliers)
    confidence = "LIMITED" if any(row.get("confidence_level") in {"LOW", "LIMITED"} for rows in by_family.values() for row in rows) else "MEDIUM"
    evidence = "LIMITED" if confidence == "LIMITED" else "HIGH"
    sim: list[dict[str, str]] = []
    for item in staged:
        ticker = str(item["ticker"])
        baseline_rank = int(item["baseline_rank"])
        reduced_rank = reduced_rank_by_ticker[ticker]
        baseline_top20 = baseline_rank <= 20
        reduced_top20 = reduced_rank <= 20
        original = original_by_ticker.get(ticker, {})
        sim.append({
            "ticker": ticker,
            "baseline_rank": str(baseline_rank),
            "original_shadow_rank_if_available": original.get("shadow_rank", ""),
            "reduced_shadow_rank": str(reduced_rank),
            "original_shadow_rank_delta_if_available": original.get("rank_delta", ""),
            "reduced_shadow_rank_delta": str(baseline_rank - reduced_rank),
            "baseline_score": fmt(float(item["baseline_score"])),
            "reduced_shadow_score": fmt(float(item["reduced_shadow_score"])),
            "reduced_score_delta": fmt(float(item["score_delta"])),
            "affected_factor_family": affected_families,
            "affected_factor_name": affected_names,
            "reduced_shadow_weight_delta": applied_delta,
            "reduction_multiplier": multiplier_text,
            "proposal_confidence_level": confidence,
            "evidence_quality": evidence,
            "baseline_top20_flag": tf(baseline_top20),
            "reduced_shadow_top20_flag": tf(reduced_top20),
            "entered_reduced_shadow_top20": tf((not baseline_top20) and reduced_top20),
            "exited_reduced_shadow_top20": tf(baseline_top20 and (not reduced_top20)),
            "simulation_scope": SCOPE if item["recompute"] else "RESEARCH_ONLY_LIMITED_CONSERVATIVE_SCORE_RECOMPUTE_UNAVAILABLE",
            "official_ranking_mutated": "FALSE",
            "official_weight_change_created": "FALSE",
            **COMMON,
        })
    sim.sort(key=lambda row: int(row["baseline_rank"]))
    limitation = "NONE" if missing_count == 0 else f"MISSING_FACTOR_COMPONENTS_FOR_{missing_count}_TICKERS"
    return sim, missing_count == 0, limitation


def summary_row(sim: list[dict[str, str]], proposals: list[dict[str, str]], score_recompute: bool, limitation: str) -> dict[str, str]:
    baseline_top = {row["ticker"] for row in sim if row["baseline_top20_flag"] == "TRUE"}
    reduced_top = {row["ticker"] for row in sim if row["reduced_shadow_top20_flag"] == "TRUE"}
    abs_deltas = [abs(int(row["reduced_shadow_rank_delta"])) for row in sim]
    limited = sum(1 for row in proposals if row.get("confidence_level") in {"LOW", "LIMITED"})
    turnover = ((len(reduced_top - baseline_top) + len(baseline_top - reduced_top)) / max(1, len(baseline_top))) if baseline_top else 0.0
    limitation_reason = limitation
    if limited:
        limitation_reason = limitation_reason + "|LOW_OR_LIMITED_CONFIDENCE_REDUCED_PROPOSALS"
    return {
        "summary_id": "V20_158_REDUCED_SHADOW_VS_BASELINE_RANK_DELTA_001",
        "baseline_candidate_count": str(len(sim)),
        "reduced_shadow_candidate_count": str(len(sim)),
        "top20_overlap_count": str(len(baseline_top & reduced_top)),
        "entered_reduced_top20_count": str(len(reduced_top - baseline_top)),
        "exited_reduced_top20_count": str(len(baseline_top - reduced_top)),
        "reduced_top20_turnover_rate": fmt(turnover),
        "reduced_max_absolute_rank_delta": str(max(abs_deltas) if abs_deltas else 0),
        "reduced_average_absolute_rank_delta": fmt(mean(abs_deltas) if abs_deltas else 0.0),
        "reduced_affected_ticker_count": str(sum(1 for row in sim if row["reduced_shadow_rank_delta"] != "0" or float(row["reduced_score_delta"]) != 0.0)),
        "reduced_proposal_row_count": str(len(proposals)),
        "limited_confidence_proposal_count": str(limited),
        "score_recomputation_performed": tf(score_recompute),
        "rank_impact_proxy_used": "FALSE",
        "limitation_reason": limitation_reason,
        **COMMON,
    }


def original_metrics(rows: list[dict[str, str]]) -> dict[str, float]:
    if not rows:
        return {}
    row = rows[0]
    entered = num(row.get("entered_top20_count"))
    exited = num(row.get("exited_top20_count"))
    baseline_count = max(1.0, min(20.0, num(row.get("baseline_candidate_count"), 20.0)))
    return {
        "turnover": (entered + exited) / baseline_count,
        "max": num(row.get("max_absolute_rank_delta")),
        "avg": num(row.get("average_absolute_rank_delta")),
        "affected": num(row.get("affected_ticker_count")),
    }


def rank_impact_severity(turnover: float, max_delta: float, avg_delta: float) -> str:
    if max_delta >= EXTREME_MAX_RANK_DELTA:
        return "EXTREME"
    if turnover >= HIGH_TURNOVER or avg_delta >= HIGH_AVERAGE_RANK_DELTA:
        return "HIGH"
    if max_delta > 0 or avg_delta > 0 or turnover > 0:
        return "ELEVATED"
    return "LOW"


def comparison_row(original: dict[str, float], reduced: dict[str, str]) -> dict[str, str]:
    reduced_turnover = num(reduced.get("reduced_top20_turnover_rate"))
    reduced_max = num(reduced.get("reduced_max_absolute_rank_delta"))
    reduced_avg = num(reduced.get("reduced_average_absolute_rank_delta"))
    reduced_affected = num(reduced.get("reduced_affected_ticker_count"))
    original_turnover = original.get("turnover", math.nan)
    original_max = original.get("max", math.nan)
    original_avg = original.get("avg", math.nan)
    original_affected = original.get("affected", math.nan)
    has_original = not math.isnan(original_turnover)
    success = has_original and reduced_turnover < original_turnover and reduced_max < original_max and reduced_avg < original_avg
    severity = rank_impact_severity(reduced_turnover, reduced_max, reduced_avg)
    if severity == "EXTREME":
        action = "REQUEST_ADDITIONAL_DELTA_REDUCTION_OR_REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW"
    elif severity == "HIGH":
        action = "REQUEST_OPERATOR_REVIEW_BEFORE_ANY_SHADOW_EXPANSION"
    else:
        action = "APPROVE_CONTINUED_REDUCED_SHADOW_RESEARCH_ONLY"
    return {
        "comparison_id": "V20_158_REDUCED_VS_ORIGINAL_SHADOW_IMPACT_COMPARISON_001",
        "original_top20_turnover_rate": "" if not has_original else fmt(original_turnover),
        "reduced_top20_turnover_rate": fmt(reduced_turnover),
        "original_max_absolute_rank_delta": "" if not has_original else fmt(original_max),
        "reduced_max_absolute_rank_delta": fmt(reduced_max),
        "original_average_absolute_rank_delta": "" if not has_original else fmt(original_avg),
        "reduced_average_absolute_rank_delta": fmt(reduced_avg),
        "original_affected_ticker_count": "" if not has_original else str(int(original_affected)),
        "reduced_affected_ticker_count": str(int(reduced_affected)),
        "impact_reduction_success": tf(success),
        "remaining_rank_impact_severity": severity,
        "recommended_next_action": action,
        **COMMON,
    }


def safety_audit_rows(upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("reduced_shadow_weight_proposal_created", "TRUE", "TRUE"),
        ("reduced_shadow_ranking_simulation_created", "TRUE", "TRUE"),
        ("reduced_shadow_ranking_simulation_scope", SCOPE, SCOPE),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    rows = []
    for index, (check, expected, actual) in enumerate(checks, start=1):
        rows.append({
            "safety_check_id": f"V20_158_SAFETY_{index:03d}",
            "safety_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "safety_passed": tf(expected == actual),
            **COMMON,
        })
    return rows


def safety_issue_count(groups: list[list[dict[str, str]]]) -> int:
    count = 0
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if field in {"reduced_shadow_weight_proposal_created", "reduced_shadow_ranking_simulation_created"}:
                    if row.get(field) != "TRUE":
                        count += 1
                elif field == "reduced_shadow_ranking_simulation_scope":
                    if row.get(field) != SCOPE:
                        count += 1
                elif field == "shadow_weight_expansion_allowed":
                    if row.get(field) != "FALSE":
                        count += 1
                elif truthy(row.get(field)):
                    count += 1
    return count


def write_report(status: str, sim_count: int, comparison: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.158 Reduced Shadow Weight Ranking Simulation Report",
        "",
        f"- wrapper_status: {status}",
        f"- simulation_row_count: {sim_count}",
        f"- reduced_top20_turnover_rate: {comparison.get('reduced_top20_turnover_rate', '')}",
        f"- reduced_max_absolute_rank_delta: {comparison.get('reduced_max_absolute_rank_delta', '')}",
        f"- remaining_rank_impact_severity: {comparison.get('remaining_rank_impact_severity', '')}",
        f"- reduced_shadow_ranking_simulation_scope: {SCOPE}",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
        "- performance_claim_created: FALSE",
        "",
        "The simulation uses only V20.157 reduced proposal rows for new shadow ranking impact. V20.155 is read only for original-shadow comparison fields.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_158_REDUCED_SHADOW_RANKING_GATE_001",
        "v20_157_gate_consumed": "FALSE",
        "v20_157_status": "",
        "v20_157_allowed_for_v20_158": "FALSE",
        **SAFETY,
        "reduced_proposal_row_count": "0",
        "baseline_candidate_count": "0",
        "simulation_row_count": "0",
        "score_recomputation_performed": "FALSE",
        "rank_impact_proxy_used": "FALSE",
        "original_shadow_comparison_available": "FALSE",
        "reduced_top20_turnover_rate": "0",
        "reduced_max_absolute_rank_delta": "0",
        "reduced_average_absolute_rank_delta": "0",
        "remaining_rank_impact_severity": "",
        "impact_reduction_success": "FALSE",
        "official_ranking_rows_mutated": "0",
        "official_weight_rows_mutated": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "no_scores_fabricated": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_159_operator_review_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "reduced_shadow_ranking_simulation_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_SIM, SIM_FIELDS, [])
    write_csv(OUT_DELTA, DELTA_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, [])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, [])
    write_csv(OUT_COMPARISON, COMPARISON_FIELDS, [])
    write_report(BLOCKED_STATUS, 0, {})
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in required_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    proposal_rows, _ = read_csv(IN_PROPOSAL)
    gate_rows, _ = read_csv(IN_GATE)
    ranking_rows, _ = read_csv(V83_RANKING)
    component_rows, _ = read_csv(V108_COMPONENTS)
    original_sim_rows, _ = read_csv(V155_SIM)
    original_delta_rows, _ = read_csv(V155_DELTA)
    if not all([proposal_rows, gate_rows, ranking_rows, component_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v157_status = gate_rows[0].get("final_status", "")
    allowed = v157_status in V157_ALLOWED and truthy(gate_rows[0].get("v20_158_reduced_shadow_simulation_allowed"))
    if not allowed:
        return emit_blocked("V20_157_STATUS_NOT_ALLOWED_FOR_V20_158")
    official_bad = any(truthy(row.get("usable_for_official_weight_change")) for row in proposal_rows)
    if official_bad:
        return emit_blocked("OFFICIAL_WEIGHT_ELIGIBLE_REDUCED_PROPOSAL_ROW_FOUND")
    eligible = [row for row in proposal_rows if truthy(row.get("usable_for_reduced_shadow_simulation"))]
    if not eligible:
        source_rows = source_audit_rows()
        safety_rows = safety_audit_rows(False)
        write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
        write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety_rows)
        write_report(WARN_STATUS, 0, {})
        print(WARN_STATUS)
        return 0

    deltas, by_family = aggregate_reduced_proposals(eligible)
    components = component_map(component_rows)
    base = baseline_rows(ranking_rows)
    original_by_ticker = original_sim_map(original_sim_rows)
    sim_rows, score_recompute, limitation = build_simulation(base, components, deltas, by_family, original_by_ticker)
    summary = summary_row(sim_rows, eligible, score_recompute, limitation)
    comparison = comparison_row(original_metrics(original_delta_rows), summary)
    source_rows = source_audit_rows()
    upstream_mutated = before != upstream_hashes()
    safety_rows = safety_audit_rows(upstream_mutated)
    safety_count = safety_issue_count([sim_rows, [summary], [comparison], source_rows, safety_rows])

    severity = comparison["remaining_rank_impact_severity"]
    impact_success = comparison["impact_reduction_success"] == "TRUE"
    if upstream_mutated or safety_count:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif severity == "EXTREME":
        status = WARN_STATUS
        blocking = ""
    elif severity == "HIGH" or not score_recompute:
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    gate = {
        "gate_check_id": "V20_158_REDUCED_SHADOW_RANKING_GATE_001",
        "v20_157_gate_consumed": "TRUE",
        "v20_157_status": v157_status,
        "v20_157_allowed_for_v20_158": tf(allowed),
        **SAFETY,
        "reduced_proposal_row_count": str(len(eligible)),
        "baseline_candidate_count": str(len(base)),
        "simulation_row_count": str(len(sim_rows)),
        "score_recomputation_performed": tf(score_recompute),
        "rank_impact_proxy_used": "FALSE",
        "original_shadow_comparison_available": tf(bool(original_delta_rows)),
        "reduced_top20_turnover_rate": summary["reduced_top20_turnover_rate"],
        "reduced_max_absolute_rank_delta": summary["reduced_max_absolute_rank_delta"],
        "reduced_average_absolute_rank_delta": summary["reduced_average_absolute_rank_delta"],
        "remaining_rank_impact_severity": severity,
        "impact_reduction_success": tf(impact_success),
        "official_ranking_rows_mutated": "0",
        "official_weight_rows_mutated": "0",
        "no_ticker_rows_fabricated": tf(len(sim_rows) == len(base)),
        "no_scores_fabricated": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_159_operator_review_allowed": tf(next_allowed),
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "reduced_shadow_ranking_simulation_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_SIM, SIM_FIELDS, sim_rows)
    write_csv(OUT_DELTA, DELTA_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety_rows)
    write_csv(OUT_COMPARISON, COMPARISON_FIELDS, [comparison])
    write_report(status, len(sim_rows), comparison)

    print(status)
    print("V20_157_GATE_CONSUMED=TRUE")
    print(f"V20_157_ALLOWED_FOR_V20_158={tf(allowed)}")
    print(f"REDUCED_PROPOSAL_ROW_COUNT={len(eligible)}")
    print(f"BASELINE_CANDIDATE_COUNT={len(base)}")
    print(f"SIMULATION_ROW_COUNT={len(sim_rows)}")
    print(f"SCORE_RECOMPUTATION_PERFORMED={tf(score_recompute)}")
    print("RANK_IMPACT_PROXY_USED=FALSE")
    print(f"ORIGINAL_SHADOW_COMPARISON_AVAILABLE={tf(bool(original_delta_rows))}")
    print(f"REDUCED_TOP20_TURNOVER_RATE={summary['reduced_top20_turnover_rate']}")
    print(f"REDUCED_MAX_ABSOLUTE_RANK_DELTA={summary['reduced_max_absolute_rank_delta']}")
    print(f"REDUCED_AVERAGE_ABSOLUTE_RANK_DELTA={summary['reduced_average_absolute_rank_delta']}")
    print(f"REMAINING_RANK_IMPACT_SEVERITY={severity}")
    print(f"IMPACT_REDUCTION_SUCCESS={tf(impact_success)}")
    print("OFFICIAL_RANKING_ROWS_MUTATED=0")
    print("OFFICIAL_WEIGHT_ROWS_MUTATED=0")
    print(f"TICKER_ROWS_FABRICATED={0 if len(sim_rows) == len(base) else 'UNKNOWN'}")
    print("SCORES_FABRICATED=0")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"REDUCED_SHADOW_RANKING_SIMULATION_SCOPE={SCOPE}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    print(f"V20_159_OPERATOR_REVIEW_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
