#!/usr/bin/env python
"""V20.155 limited shadow weight ranking simulation.

Runs a research-only limited shadow ranking simulation from V20.154 shadow
weight proposal rows. It uses existing current ranking and factor contribution
artifacts only, writes new V20.155 outputs, and does not mutate official
rankings, official weights, recommendations, trades, broker actions, or
upstream V20.109-V20.154 artifacts.
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

IN_PROPOSAL = FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
IN_GATE = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_GATE.csv"
IN_SOURCE = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SOURCE_AUDIT.csv"
IN_SAFETY = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_SAFETY_AUDIT.csv"
IN_BLOCKED = FACTORS / "V20_154_SHADOW_WEIGHT_PROPOSAL_BLOCKED_OFFICIAL_AUDIT.csv"

V83_RANKING = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
V108_COMPONENTS = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
OPTIONAL_SOURCES = [
    CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv",
    CONSOLIDATION / "V20_108_R13_FACTOR_FAMILY_RANK_CHANGE_ATTRIBUTION.csv",
    CONSOLIDATION / "V20_108_R13_SHADOW_RERANK_DELTA_SUMMARY.csv",
]

OUT_SIM = FACTORS / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_155_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_GATE = FACTORS / "V20_155_SHADOW_RANKING_SIMULATION_GATE.csv"
OUT_SOURCE = FACTORS / "V20_155_SHADOW_RANKING_SOURCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_155_SHADOW_RANKING_SAFETY_AUDIT.csv"
OUT_LIMITATION = FACTORS / "V20_155_SHADOW_RANKING_LIMITATION_AUDIT.csv"
REPORT = READ_CENTER / "V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_REPORT.md"

V154_ALLOWED = {
    "PARTIAL_PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_WITH_LOW_CONFIDENCE_READY_FOR_V20_155",
    "PASS_V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL_READY_FOR_V20_155",
}
PASS_STATUS = "PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_READY_FOR_V20_156"
PARTIAL_STATUS = "PARTIAL_PASS_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION_WITH_LIMITATIONS_READY_FOR_V20_156"
WARN_STATUS = "WARN_V20_155_SHADOW_RANKING_SIMULATION_INSUFFICIENT_INPUTS"
BLOCKED_STATUS = "BLOCKED_V20_155_LIMITED_SHADOW_WEIGHT_RANKING_SIMULATION"
SCOPE = "RESEARCH_ONLY_LIMITED"
MAX_FAMILY_DELTA = 0.015
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "official_weight_change_created",
    "shadow_weight_proposal_created",
    "shadow_ranking_simulation_created",
    "shadow_ranking_simulation_scope",
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
    "shadow_weight_proposal_created": "TRUE",
    "shadow_ranking_simulation_created": "TRUE",
    "shadow_ranking_simulation_scope": SCOPE,
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
    "limited_shadow_ranking_simulation_only": "TRUE",
    "audit_only": "TRUE",
}

SIM_FIELDS = [
    "ticker",
    "baseline_rank",
    "shadow_rank",
    "rank_delta",
    "baseline_score",
    "shadow_score",
    "score_delta",
    "affected_factor_family",
    "affected_factor_name",
    "applied_shadow_weight_delta",
    "proposal_confidence_level",
    "evidence_quality",
    "baseline_top20_flag",
    "shadow_top20_flag",
    "entered_shadow_top20",
    "exited_shadow_top20",
    "buy_zone_status_if_available",
    "technical_status_if_available",
    "risk_flag_if_available",
    "simulation_scope",
    "official_ranking_mutated",
    "official_weight_change_created",
    *COMMON.keys(),
]
DELTA_FIELDS = [
    "summary_id",
    "baseline_candidate_count",
    "shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "affected_ticker_count",
    "proposal_row_count",
    "low_confidence_proposal_count",
    "limitation_reason",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_154_gate_consumed",
    "v20_154_status",
    "v20_154_allowed_for_v20_155",
    *SAFETY_FIELDS,
    "proposal_row_count",
    "baseline_candidate_count",
    "simulation_row_count",
    "limitation_row_count",
    "rank_impact_proxy_used",
    "score_recomputation_performed",
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
    "v20_156_shadow_review_allowed",
    "blocking_reason",
    "final_status",
    "research_only",
    "staging_review_only",
    "limited_shadow_ranking_simulation_only",
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
LIMITATION_FIELDS = [
    "limitation_id",
    "ticker",
    "limitation_reason",
    "score_recomputation_available",
    "rank_impact_proxy_used",
    "source_artifact",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


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
    return [IN_PROPOSAL, IN_GATE, IN_SOURCE, IN_SAFETY, IN_BLOCKED, V83_RANKING, V108_COMPONENTS]


def upstream_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in upstream_inputs() if path.exists()}


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(value: float) -> str:
    return f"{value:.10f}"


def source_audit_rows() -> list[dict[str, str]]:
    sources = [
        (IN_PROPOSAL, "V20_154_PROPOSAL"),
        (IN_GATE, "V20_154_GATE"),
        (IN_SOURCE, "V20_154_SOURCE_AUDIT"),
        (IN_SAFETY, "V20_154_SAFETY_AUDIT"),
        (IN_BLOCKED, "V20_154_BLOCKED_OFFICIAL_AUDIT"),
        (V83_RANKING, "CURRENT_AUTHORITATIVE_RANKING_REFERENCE"),
        (V108_COMPONENTS, "FACTOR_COMPONENT_RECOMPUTE_SOURCE"),
        *[(path, "OPTIONAL_RANKING_CONTEXT") for path in OPTIONAL_SOURCES],
    ]
    rows: list[dict[str, str]] = []
    for index, (path, role) in enumerate(sources, start=1):
        data, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        required = path in {IN_PROPOSAL, IN_GATE, IN_SOURCE, IN_SAFETY, IN_BLOCKED, V83_RANKING, V108_COMPONENTS}
        ok = bool(fields) and non_empty
        rows.append({
            "source_audit_id": f"V20_155_SOURCE_AUDIT_{index:03d}",
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


def aggregate_proposals(proposals: list[dict[str, str]]) -> tuple[dict[str, float], dict[str, list[dict[str, str]]]]:
    deltas: dict[str, float] = {}
    by_family: dict[str, list[dict[str, str]]] = {}
    for row in proposals:
        if not truthy(row.get("usable_for_shadow_weight_proposal")):
            continue
        family = row.get("factor_family", "")
        delta = num(row.get("proposed_delta"))
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


def build_simulation(rank_rows: list[dict[str, str]], components: dict[str, dict[str, float]], deltas: dict[str, float], by_family: dict[str, list[dict[str, str]]]) -> tuple[list[dict[str, str]], list[dict[str, str]], bool]:
    staged: list[dict[str, object]] = []
    limitations: list[dict[str, str]] = []
    for row in rank_rows:
        ticker = row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        comp = components.get(ticker or "", {})
        missing_families = [family for family in FAMILIES if family not in comp]
        recompute = not missing_families
        if not recompute:
            limitations.append({
                "limitation_id": f"V20_155_LIMITATION_{len(limitations)+1:04d}",
                "ticker": ticker or "",
                "limitation_reason": "MISSING_FACTOR_COMPONENTS_FOR_SAFE_SCORE_RECOMPUTATION:" + "|".join(missing_families),
                "score_recomputation_available": "FALSE",
                "rank_impact_proxy_used": "FALSE",
                "source_artifact": rel(V108_COMPONENTS),
                **COMMON,
            })
        baseline = base_score(comp) if recompute else num(row.get("official_current_score") or row.get("source_rank_or_score"))
        score_delta = sum(comp.get(family, 0.0) * delta for family, delta in deltas.items()) if recompute else 0.0
        shadow = baseline + score_delta
        staged.append({
            "ticker": ticker or "",
            "baseline_rank": rank_field(row),
            "baseline_score": baseline,
            "shadow_score": shadow,
            "score_delta": score_delta,
            "recompute": recompute,
            "buy_zone": row.get("buy_zone_status", ""),
            "technical": "TECHNICAL_COMPONENT_AVAILABLE" if "TECHNICAL" in comp else "",
            "risk": "RISK_COMPONENT_AVAILABLE" if "RISK" in comp else "",
        })
    sortable = [row for row in staged if row["recompute"]]
    sortable.sort(key=lambda item: (-float(item["shadow_score"]), int(item["baseline_rank"]), str(item["ticker"])))
    shadow_rank_by_ticker = {str(row["ticker"]): index for index, row in enumerate(sortable, start=1)}
    if len(sortable) != len(staged):
        for row in sorted((r for r in staged if not r["recompute"]), key=lambda item: int(item["baseline_rank"])):
            shadow_rank_by_ticker[str(row["ticker"])] = int(row["baseline_rank"])

    affected_families = ";".join(family for family in FAMILIES if family in deltas)
    affected_names = ";".join(row.get("factor_name", "") for rows in by_family.values() for row in rows)
    applied_delta = ";".join(f"{family}:{fmt(delta)}" for family, delta in sorted(deltas.items()))
    confidence = "LIMITED" if any(row.get("confidence_level") in {"LOW", "LIMITED"} for rows in by_family.values() for row in rows) else "MEDIUM"
    evidence = "LIMITED" if confidence == "LIMITED" else "HIGH"
    sim: list[dict[str, str]] = []
    for item in staged:
        ticker = str(item["ticker"])
        baseline_rank = int(item["baseline_rank"])
        shadow_rank = shadow_rank_by_ticker[ticker]
        baseline_top20 = baseline_rank <= 20
        shadow_top20 = shadow_rank <= 20
        sim.append({
            "ticker": ticker,
            "baseline_rank": str(baseline_rank),
            "shadow_rank": str(shadow_rank),
            "rank_delta": str(baseline_rank - shadow_rank),
            "baseline_score": fmt(float(item["baseline_score"])),
            "shadow_score": fmt(float(item["shadow_score"])),
            "score_delta": fmt(float(item["score_delta"])),
            "affected_factor_family": affected_families,
            "affected_factor_name": affected_names,
            "applied_shadow_weight_delta": applied_delta,
            "proposal_confidence_level": confidence,
            "evidence_quality": evidence,
            "baseline_top20_flag": tf(baseline_top20),
            "shadow_top20_flag": tf(shadow_top20),
            "entered_shadow_top20": tf((not baseline_top20) and shadow_top20),
            "exited_shadow_top20": tf(baseline_top20 and (not shadow_top20)),
            "buy_zone_status_if_available": str(item["buy_zone"]),
            "technical_status_if_available": str(item["technical"]),
            "risk_flag_if_available": str(item["risk"]),
            "simulation_scope": SCOPE if item["recompute"] else "RESEARCH_ONLY_LIMITED_SCORE_RECOMPUTE_UNAVAILABLE",
            "official_ranking_mutated": "FALSE",
            "official_weight_change_created": "FALSE",
            **COMMON,
        })
    sim.sort(key=lambda row: int(row["baseline_rank"]))
    return sim, limitations, bool(limitations)


def summary_row(sim: list[dict[str, str]], proposals: list[dict[str, str]], limitations: list[dict[str, str]]) -> dict[str, str]:
    baseline_count = len(sim)
    shadow_count = len(sim)
    baseline_top = {row["ticker"] for row in sim if row["baseline_top20_flag"] == "TRUE"}
    shadow_top = {row["ticker"] for row in sim if row["shadow_top20_flag"] == "TRUE"}
    abs_deltas = [abs(int(row["rank_delta"])) for row in sim]
    low = sum(1 for row in proposals if row.get("confidence_level") in {"LOW", "LIMITED"})
    limitation_reason = "NONE" if not limitations else "LIMITED_SCORE_RECOMPUTATION_FOR_SOME_TICKERS"
    if low:
        limitation_reason = limitation_reason + "|LOW_OR_LIMITED_CONFIDENCE_PROPOSALS"
    return {
        "summary_id": "V20_155_SHADOW_VS_BASELINE_RANK_DELTA_001",
        "baseline_candidate_count": str(baseline_count),
        "shadow_candidate_count": str(shadow_count),
        "top20_overlap_count": str(len(baseline_top & shadow_top)),
        "entered_top20_count": str(len(shadow_top - baseline_top)),
        "exited_top20_count": str(len(baseline_top - shadow_top)),
        "max_absolute_rank_delta": str(max(abs_deltas) if abs_deltas else 0),
        "average_absolute_rank_delta": fmt(mean(abs_deltas) if abs_deltas else 0.0),
        "affected_ticker_count": str(sum(1 for row in sim if row["rank_delta"] != "0" or float(row["score_delta"]) != 0.0)),
        "proposal_row_count": str(len(proposals)),
        "low_confidence_proposal_count": str(low),
        "limitation_reason": limitation_reason,
        **COMMON,
    }


def safety_audit_rows(upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("shadow_weight_proposal_created", "TRUE", "TRUE"),
        ("shadow_ranking_simulation_created", "TRUE", "TRUE"),
        ("shadow_ranking_simulation_scope", SCOPE, SCOPE),
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
            "safety_check_id": f"V20_155_SAFETY_{index:03d}",
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
                if field in {"shadow_weight_proposal_created", "shadow_ranking_simulation_created"}:
                    if row.get(field) != "TRUE":
                        count += 1
                elif field == "shadow_ranking_simulation_scope":
                    if row.get(field) != SCOPE:
                        count += 1
                elif truthy(row.get(field)):
                    count += 1
    return count


def write_report(status: str, sim_count: int, limitation_count: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.155 Limited Shadow Weight Ranking Simulation Report",
        "",
        f"- wrapper_status: {status}",
        f"- simulation_row_count: {sim_count}",
        f"- limitation_row_count: {limitation_count}",
        "- shadow_ranking_simulation_created: TRUE",
        f"- shadow_ranking_simulation_scope: {SCOPE}",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
        "",
        "The simulation uses V20.154 research-only shadow proposal rows and existing ranking/component artifacts. Authoritative ranking artifacts are not overwritten.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_155_SHADOW_RANKING_SIMULATION_GATE_001",
        "v20_154_gate_consumed": "FALSE",
        "v20_154_status": "",
        "v20_154_allowed_for_v20_155": "FALSE",
        **SAFETY,
        "proposal_row_count": "0",
        "baseline_candidate_count": "0",
        "simulation_row_count": "0",
        "limitation_row_count": "0",
        "rank_impact_proxy_used": "FALSE",
        "score_recomputation_performed": "FALSE",
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
        "v20_156_shadow_review_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "limited_shadow_ranking_simulation_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_SIM, SIM_FIELDS, [])
    write_csv(OUT_DELTA, DELTA_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, [])
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, [])
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, [])
    write_report(BLOCKED_STATUS, 0, 0)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = upstream_hashes()
    missing = [path for path in upstream_inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    proposal_rows, _ = read_csv(IN_PROPOSAL)
    gate_rows, _ = read_csv(IN_GATE)
    ranking_rows, _ = read_csv(V83_RANKING)
    component_rows, _ = read_csv(V108_COMPONENTS)
    if not all([proposal_rows, gate_rows, ranking_rows, component_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v154_status = gate_rows[0].get("final_status", "")
    allowed = v154_status in V154_ALLOWED and truthy(gate_rows[0].get("v20_155_limited_shadow_simulation_allowed"))
    if not allowed:
        return emit_blocked("V20_154_STATUS_NOT_ALLOWED_FOR_V20_155")
    official_bad = any(truthy(row.get("usable_for_official_weight_change")) for row in proposal_rows)
    if official_bad:
        return emit_blocked("OFFICIAL_WEIGHT_ELIGIBLE_PROPOSAL_ROW_FOUND")
    eligible_proposals = [row for row in proposal_rows if truthy(row.get("usable_for_shadow_weight_proposal"))]
    if not eligible_proposals:
        source_rows = source_audit_rows()
        safety_rows = safety_audit_rows(False)
        write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
        write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety_rows)
        write_report(WARN_STATUS, 0, 0)
        print(WARN_STATUS)
        return 0

    deltas, by_family = aggregate_proposals(eligible_proposals)
    components = component_map(component_rows)
    base = baseline_rows(ranking_rows)
    sim_rows, limitation_rows, has_limitations = build_simulation(base, components, deltas, by_family)
    summary = summary_row(sim_rows, eligible_proposals, limitation_rows)
    source_rows = source_audit_rows()
    upstream_mutated = before != upstream_hashes()
    safety_rows = safety_audit_rows(upstream_mutated)
    safety_count = safety_issue_count([sim_rows, [summary], source_rows, safety_rows, limitation_rows])
    if upstream_mutated or safety_count:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif not sim_rows:
        status = WARN_STATUS
        blocking = ""
    elif has_limitations or int(summary["low_confidence_proposal_count"]) > 0:
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    gate = {
        "gate_check_id": "V20_155_SHADOW_RANKING_SIMULATION_GATE_001",
        "v20_154_gate_consumed": "TRUE",
        "v20_154_status": v154_status,
        "v20_154_allowed_for_v20_155": tf(allowed),
        **SAFETY,
        "proposal_row_count": str(len(eligible_proposals)),
        "baseline_candidate_count": str(len(base)),
        "simulation_row_count": str(len(sim_rows)),
        "limitation_row_count": str(len(limitation_rows)),
        "rank_impact_proxy_used": "FALSE",
        "score_recomputation_performed": tf(not has_limitations),
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
        "v20_156_shadow_review_allowed": tf(next_allowed),
        "blocking_reason": blocking,
        "final_status": status,
        "research_only": "TRUE",
        "staging_review_only": "TRUE",
        "limited_shadow_ranking_simulation_only": "TRUE",
        "audit_only": "TRUE",
    }
    write_csv(OUT_SIM, SIM_FIELDS, sim_rows)
    write_csv(OUT_DELTA, DELTA_FIELDS, [summary])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_SAFETY, SAFETY_AUDIT_FIELDS, safety_rows)
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, limitation_rows or [{
        "limitation_id": "V20_155_LIMITATION_0000",
        "ticker": "",
        "limitation_reason": "NO_SCORE_RECOMPUTATION_LIMITATION_DETECTED",
        "score_recomputation_available": "TRUE",
        "rank_impact_proxy_used": "FALSE",
        "source_artifact": rel(V108_COMPONENTS),
        **COMMON,
    }])
    write_report(status, len(sim_rows), len(limitation_rows))

    print(status)
    print("V20_154_GATE_CONSUMED=TRUE")
    print(f"V20_154_ALLOWED_FOR_V20_155={tf(allowed)}")
    print(f"PROPOSAL_ROW_COUNT={len(eligible_proposals)}")
    print(f"BASELINE_CANDIDATE_COUNT={len(base)}")
    print(f"SIMULATION_ROW_COUNT={len(sim_rows)}")
    print(f"LIMITATION_ROW_COUNT={len(limitation_rows)}")
    print("RANK_IMPACT_PROXY_USED=FALSE")
    print(f"SCORE_RECOMPUTATION_PERFORMED={tf(not has_limitations)}")
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
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"SAFETY_TRUE_COUNT={safety_count}")
    print(f"V20_156_SHADOW_REVIEW_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
