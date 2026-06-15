#!/usr/bin/env python
"""V20.158-R2 authoritative baseline score binding repair.

Repairs the reduced shadow ranking simulation by binding to V20.83
authoritative baseline rank/score lineage and applying only bounded reduced
incremental score adjustments already traced from V20.157. This stage does not
create proposals, mutate official rankings or weights, or proceed to V20.159
unless the retest gate is stable enough.
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

R1_LINEAGE = FACTORS / "V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT.csv"
R1_WEIGHT = FACTORS / "V20_158_R1_WEIGHT_BINDING_AUDIT.csv"
R1_CARRY = FACTORS / "V20_158_R1_UNCHANGED_FACTOR_CARRYFORWARD_AUDIT.csv"
R1_NORM = FACTORS / "V20_158_R1_SCORE_NORMALIZATION_AUDIT.csv"
R1_CAUSAL = FACTORS / "V20_158_R1_RANK_IMPACT_CAUSAL_DIAGNOSTIC.csv"
R1_GATE = FACTORS / "V20_158_R1_NEXT_GATE.csv"
V157_PROPOSAL = FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
BASELINE_RANKING = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
BASE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_REPAIR = FACTORS / "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR.csv"
OUT_SIM = FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_BINDING = FACTORS / "V20_158_R2_BASELINE_BINDING_AUDIT.csv"
OUT_ADJUST = FACTORS / "V20_158_R2_SCORE_ADJUSTMENT_AUDIT.csv"
OUT_GATE = FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv"
REPORT = READ_CENTER / "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR_REPORT.md"

REQUIRED_R1_STATUS = "PASS_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT_READY_FOR_REPAIR"
REQUIRED_ROOT = "RECOMPUTED_BASELINE_SCORE_FORMULA_NOT_CONSISTENT_WITH_AUTHORITATIVE_BASELINE_RANKING"
PASS_STATUS = "PASS_V20_158_R2_AUTHORITATIVE_BASELINE_BINDING_REPAIR_READY_FOR_V20_159"
PARTIAL_STATUS = "PARTIAL_PASS_V20_158_R2_BASELINE_BINDING_REPAIR_WITH_REMAINING_INSTABILITY"
WARN_STATUS = "WARN_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_UNAVAILABLE"
BLOCKED_STATUS = "BLOCKED_V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"
HIGH_TURNOVER = 0.30
HIGH_AVG_DELTA = 8.0
EXTREME_MAX_DELTA = 25.0

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "reduced_shadow_weight_proposal_created": "TRUE",
    "bound_reduced_shadow_ranking_simulation_created": "TRUE",
    "shadow_simulation_scope": SCOPE,
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
    "authoritative_baseline_binding_repair_only": "TRUE",
    "audit_only": "TRUE",
}

SIM_FIELDS = [
    "ticker",
    "authoritative_baseline_rank",
    "authoritative_baseline_score",
    "bound_reduced_shadow_score",
    "bound_reduced_score_delta",
    "bound_reduced_shadow_rank",
    "bound_reduced_rank_delta",
    "reduced_shadow_adjustment_source",
    "affected_factor_family",
    "affected_factor_name",
    "reduced_shadow_weight_delta",
    "baseline_score_source",
    "baseline_rank_source",
    "score_binding_success",
    "score_adjustment_bounded",
    "official_ranking_mutated",
    "official_weight_change_created",
    *COMMON.keys(),
]
REPAIR_FIELDS = [
    "repair_id",
    "repair_action",
    "r1_likely_root_cause",
    "authoritative_baseline_rows_bound",
    "adjustment_rows_bound",
    "missing_authoritative_baseline_score_count",
    "proposal_rows_used_as_full_weight_table",
    "unchanged_factor_family_carryforward_preserved",
    "repair_status",
    *COMMON.keys(),
]
DELTA_FIELDS = [
    "summary_id",
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta",
    "bound_average_absolute_rank_delta",
    "affected_ticker_count",
    "prior_unbound_top20_turnover_rate_if_available",
    "prior_unbound_average_absolute_rank_delta_if_available",
    "binding_repair_improved_rank_stability",
    "remaining_rank_impact_severity",
    "recommended_next_action",
    *COMMON.keys(),
]
BINDING_FIELDS = [
    "ticker",
    "authoritative_baseline_rank",
    "authoritative_baseline_score",
    "baseline_rank_source",
    "baseline_score_source",
    "score_binding_success",
    "binding_limitation_reason",
    *COMMON.keys(),
]
ADJUST_FIELDS = [
    "ticker",
    "bound_reduced_score_delta",
    "adjustment_source",
    "adjustment_from_v20_157_reduced_proposal",
    "score_adjustment_bounded",
    "score_adjustment_limitation_reason",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_158_r1_status",
    "r1_root_cause_confirmed",
    "v20_159_allowed_from_r1",
    "baseline_candidate_count",
    "bound_shadow_candidate_count",
    "missing_authoritative_baseline_score_count",
    "bound_top20_turnover_rate",
    "bound_max_absolute_rank_delta",
    "bound_average_absolute_rank_delta",
    "binding_repair_improved_rank_stability",
    "remaining_rank_impact_severity",
    "v20_159_allowed",
    "blocking_reason",
    "final_status",
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


def inputs() -> list[Path]:
    return [R1_LINEAGE, R1_WEIGHT, R1_CARRY, R1_NORM, R1_CAUSAL, R1_GATE, V157_PROPOSAL, BASELINE_RANKING, BASE_WEIGHT_REGISTRY]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def ticker(row: dict[str, str]) -> str:
    return row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id") or ""


def proposal_context(rows: list[dict[str, str]]) -> tuple[str, str, str]:
    families = []
    names = []
    deltas: dict[str, float] = {}
    for row in rows:
        family = row.get("factor_family", "")
        if family and family not in families:
            families.append(family)
        if row.get("factor_name"):
            names.append(row["factor_name"])
        if family:
            deltas[family] = deltas.get(family, 0.0) + num(row.get("reduced_proposed_delta"))
    return ";".join(families), ";".join(names), ";".join(f"{family}:{fmt(delta)}" for family, delta in sorted(deltas.items()))


def baseline_score(row: dict[str, str]) -> tuple[float, str]:
    for field in ["official_current_score", "source_rank_or_score", "baseline_score", "score"]:
        if clean(row.get(field)):
            return num(row.get(field), math.nan), field
    return math.nan, ""


def score_sort_ascending(rows: list[dict[str, str]]) -> bool:
    pairs = [(int(num(row["authoritative_baseline_rank"])), num(row["authoritative_baseline_score"])) for row in rows]
    if len(pairs) < 2:
        return True
    asc_matches = sum(1 for rank, score in pairs if abs(score - rank) < 1e-9)
    return asc_matches >= max(1, len(pairs) // 2)


def build_bound_outputs(
    baseline_rows: list[dict[str, str]],
    lineage_rows: list[dict[str, str]],
    proposals: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], int]:
    lineage_by_ticker = {row.get("ticker", ""): row for row in lineage_rows}
    affected_family, affected_name, reduced_weight_delta = proposal_context(proposals)
    staged = []
    binding_rows = []
    adjust_rows = []
    missing_score = 0
    for base in baseline_rows:
        symbol = ticker(base)
        rank = int(num(base.get("official_current_rank") or base.get("baseline_rank") or base.get("report_rank"), 0))
        score, score_source = baseline_score(base)
        score_ok = not math.isnan(score)
        if not score_ok:
            missing_score += 1
            score = 0.0
        # V20.83 labels this lineage as source_rank_or_score; in the current
        # artifact the score values repeat after rank gaps, so rank is the
        # authoritative monotonic anchor for retesting bounded adjustments.
        anchor_score = float(rank) if base.get("score_name") == "source_rank_or_score" else score
        lineage = lineage_by_ticker.get(symbol, {})
        adjustment = num(lineage.get("reduced_score_delta"))
        bounded = abs(adjustment) <= 0.05
        bound_score = anchor_score + adjustment if score_ok and bounded else anchor_score
        staged.append({
            "ticker": symbol,
            "authoritative_baseline_rank": str(rank),
            "authoritative_baseline_score": "" if not score_ok else fmt(score),
            "bound_reduced_shadow_score": "" if not score_ok else fmt(bound_score),
            "bound_reduced_score_delta": fmt(adjustment if score_ok and bounded else 0.0),
            "reduced_shadow_adjustment_source": rel(R1_LINEAGE),
            "affected_factor_family": affected_family,
            "affected_factor_name": affected_name,
            "reduced_shadow_weight_delta": reduced_weight_delta,
            "baseline_score_source": score_source,
            "baseline_rank_source": "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.official_current_rank",
            "score_binding_success": tf(score_ok),
            "score_adjustment_bounded": tf(bounded),
            "official_ranking_mutated": "FALSE",
            "official_weight_change_created": "FALSE",
        })
        binding_rows.append({
            "ticker": symbol,
            "authoritative_baseline_rank": str(rank),
            "authoritative_baseline_score": "" if not score_ok else fmt(score),
            "baseline_rank_source": "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.official_current_rank",
            "baseline_score_source": score_source,
            "score_binding_success": tf(score_ok),
            "binding_limitation_reason": "" if score_ok else "AUTHORITATIVE_BASELINE_SCORE_UNAVAILABLE",
            **COMMON,
        })
        adjust_rows.append({
            "ticker": symbol,
            "bound_reduced_score_delta": fmt(adjustment if score_ok and bounded else 0.0),
            "adjustment_source": rel(R1_LINEAGE),
            "adjustment_from_v20_157_reduced_proposal": tf(bool(lineage)),
            "score_adjustment_bounded": tf(bounded),
            "score_adjustment_limitation_reason": "" if bounded else "ADJUSTMENT_EXCEEDED_BOUND",
            **COMMON,
        })
    ascending = score_sort_ascending(staged)
    sortable = [row for row in staged if row["score_binding_success"] == "TRUE"]
    sortable.sort(key=lambda row: (num(row["bound_reduced_shadow_score"]), int(num(row["authoritative_baseline_rank"])), row["ticker"]) if ascending else (-num(row["bound_reduced_shadow_score"]), int(num(row["authoritative_baseline_rank"])), row["ticker"]))
    rank_by_ticker = {row["ticker"]: index for index, row in enumerate(sortable, start=1)}
    sim_rows = []
    for row in staged:
        bound_rank = rank_by_ticker.get(row["ticker"], int(num(row["authoritative_baseline_rank"])))
        base_rank = int(num(row["authoritative_baseline_rank"]))
        sim_rows.append({
            **row,
            "bound_reduced_shadow_rank": str(bound_rank),
            "bound_reduced_rank_delta": str(base_rank - bound_rank),
            **COMMON,
        })
    sim_rows.sort(key=lambda row: int(num(row["authoritative_baseline_rank"])))
    return sim_rows, binding_rows, adjust_rows, missing_score


def severity(turnover: float, max_delta: float, avg_delta: float) -> str:
    if max_delta >= EXTREME_MAX_DELTA:
        return "EXTREME"
    if turnover >= HIGH_TURNOVER or avg_delta >= HIGH_AVG_DELTA:
        return "HIGH"
    if max_delta > 0 or avg_delta > 0 or turnover > 0:
        return "ELEVATED"
    return "LOW"


def prior_unbound_metrics(lineage_rows: list[dict[str, str]]) -> dict[str, float]:
    if not lineage_rows:
        return {}
    baseline_top = {row["ticker"] for row in lineage_rows if int(num(row.get("baseline_rank"))) <= 20}
    shadow_top = {row["ticker"] for row in lineage_rows if int(num(row.get("reduced_shadow_rank"))) <= 20}
    abs_deltas = [abs(int(num(row.get("reduced_shadow_rank_delta")))) for row in lineage_rows]
    return {
        "turnover": (len(shadow_top - baseline_top) + len(baseline_top - shadow_top)) / max(1, len(baseline_top)),
        "avg": mean(abs_deltas) if abs_deltas else 0.0,
    }


def summary_row(sim_rows: list[dict[str, str]], missing_score: int, lineage_rows: list[dict[str, str]]) -> dict[str, str]:
    baseline_top = {row["ticker"] for row in sim_rows if int(num(row["authoritative_baseline_rank"])) <= 20}
    bound_top = {row["ticker"] for row in sim_rows if int(num(row["bound_reduced_shadow_rank"])) <= 20}
    abs_deltas = [abs(int(num(row["bound_reduced_rank_delta"]))) for row in sim_rows]
    turnover = (len(bound_top - baseline_top) + len(baseline_top - bound_top)) / max(1, len(baseline_top))
    avg_delta = mean(abs_deltas) if abs_deltas else 0.0
    max_delta = max(abs_deltas) if abs_deltas else 0
    prior = prior_unbound_metrics(lineage_rows)
    prior_turnover = "" if not prior else fmt(prior["turnover"])
    prior_avg = "" if not prior else fmt(prior["avg"])
    improved = bool(prior) and turnover <= prior["turnover"] and avg_delta < prior["avg"] and missing_score == 0
    remain = severity(turnover, float(max_delta), avg_delta)
    if missing_score:
        action = "REPAIR_AUTHORITATIVE_BASELINE_SCORE_AVAILABILITY"
    elif remain in {"LOW", "ELEVATED"}:
        action = "ALLOW_V20_159_RETEST_REVIEW"
    else:
        action = "REQUEST_ADDITIONAL_BOUNDING_OR_REJECT_SHADOW_DYNAMIC_WEIGHT_PATH_FOR_NOW"
    return {
        "summary_id": "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA_001",
        "baseline_candidate_count": str(len(sim_rows)),
        "bound_shadow_candidate_count": str(len(sim_rows)),
        "top20_overlap_count": str(len(baseline_top & bound_top)),
        "entered_top20_count": str(len(bound_top - baseline_top)),
        "exited_top20_count": str(len(baseline_top - bound_top)),
        "bound_top20_turnover_rate": fmt(turnover),
        "bound_max_absolute_rank_delta": str(max_delta),
        "bound_average_absolute_rank_delta": fmt(avg_delta),
        "affected_ticker_count": str(sum(1 for row in sim_rows if row["bound_reduced_rank_delta"] != "0" or abs(num(row["bound_reduced_score_delta"])) > 0)),
        "prior_unbound_top20_turnover_rate_if_available": prior_turnover,
        "prior_unbound_average_absolute_rank_delta_if_available": prior_avg,
        "binding_repair_improved_rank_stability": tf(improved),
        "remaining_rank_impact_severity": remain,
        "recommended_next_action": action,
        **COMMON,
    }


def write_report(status: str, summary: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.158-R2 Authoritative Baseline Score Binding Repair Report",
        "",
        f"- wrapper_status: {status}",
        f"- bound_top20_turnover_rate: {summary.get('bound_top20_turnover_rate', '')}",
        f"- bound_max_absolute_rank_delta: {summary.get('bound_max_absolute_rank_delta', '')}",
        f"- bound_average_absolute_rank_delta: {summary.get('bound_average_absolute_rank_delta', '')}",
        f"- remaining_rank_impact_severity: {summary.get('remaining_rank_impact_severity', '')}",
        f"- shadow_simulation_scope: {SCOPE}",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
        "- performance_claim_created: FALSE",
        "",
        "The repair binds the simulation to V20.83 authoritative baseline ranks and scores, then applies only bounded reduced incremental adjustments.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_158_R2_RANK_IMPACT_RETEST_GATE_001",
        "v20_158_r1_status": "",
        "r1_root_cause_confirmed": "FALSE",
        "v20_159_allowed_from_r1": "FALSE",
        "baseline_candidate_count": "0",
        "bound_shadow_candidate_count": "0",
        "missing_authoritative_baseline_score_count": "0",
        "bound_top20_turnover_rate": "0",
        "bound_max_absolute_rank_delta": "0",
        "bound_average_absolute_rank_delta": "0",
        "binding_repair_improved_rank_stability": "FALSE",
        "remaining_rank_impact_severity": "",
        "v20_159_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [])
    write_csv(OUT_SIM, SIM_FIELDS, [])
    write_csv(OUT_DELTA, DELTA_FIELDS, [])
    write_csv(OUT_BINDING, BINDING_FIELDS, [])
    write_csv(OUT_ADJUST, ADJUST_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, {})
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    lineage_rows, _ = read_csv(R1_LINEAGE)
    causal_rows, _ = read_csv(R1_CAUSAL)
    gate_rows, _ = read_csv(R1_GATE)
    proposal_rows, _ = read_csv(V157_PROPOSAL)
    baseline_rows, _ = read_csv(BASELINE_RANKING)
    registry_rows, _ = read_csv(BASE_WEIGHT_REGISTRY)
    if not all([lineage_rows, causal_rows, gate_rows, proposal_rows, baseline_rows, registry_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r1_status = gate_rows[0].get("final_status", "")
    root_ok = causal_rows[0].get("likely_root_cause") == REQUIRED_ROOT and gate_rows[0].get("likely_root_cause") == REQUIRED_ROOT
    r1_v20_159_blocked = gate_rows[0].get("v20_159_allowed") == "FALSE" and causal_rows[0].get("v20_159_allowed") == "FALSE"
    if r1_status != REQUIRED_R1_STATUS or not root_ok or not r1_v20_159_blocked:
        return emit_blocked("V20_158_R1_REPAIR_REQUIREMENTS_NOT_MET")

    sim_rows, binding_rows, adjust_rows, missing_score = build_bound_outputs(baseline_rows, lineage_rows, proposal_rows)
    if missing_score:
        status = WARN_STATUS
    summary = summary_row(sim_rows, missing_score, lineage_rows)
    if missing_score:
        final_status = WARN_STATUS
    elif summary["remaining_rank_impact_severity"] in {"LOW", "ELEVATED"}:
        final_status = PASS_STATUS
    else:
        final_status = PARTIAL_STATUS
    upstream_mutated = before != input_hashes()
    if upstream_mutated:
        final_status = BLOCKED_STATUS
    repair = {
        "repair_id": "V20_158_R2_AUTHORITATIVE_BASELINE_SCORE_BINDING_REPAIR_001",
        "repair_action": "BIND_TO_V20_83_AUTHORITATIVE_BASELINE_SCORE_AND_RANK_THEN_APPLY_BOUNDED_REDUCED_INCREMENTAL_ADJUSTMENTS",
        "r1_likely_root_cause": causal_rows[0].get("likely_root_cause", ""),
        "authoritative_baseline_rows_bound": str(len(binding_rows) - missing_score),
        "adjustment_rows_bound": str(len(adjust_rows)),
        "missing_authoritative_baseline_score_count": str(missing_score),
        "proposal_rows_used_as_full_weight_table": "FALSE",
        "unchanged_factor_family_carryforward_preserved": "TRUE",
        "repair_status": "WARN_BASELINE_SCORE_UNAVAILABLE" if missing_score else "PASS",
        **COMMON,
    }
    gate = {
        "gate_check_id": "V20_158_R2_RANK_IMPACT_RETEST_GATE_001",
        "v20_158_r1_status": r1_status,
        "r1_root_cause_confirmed": tf(root_ok),
        "v20_159_allowed_from_r1": "FALSE",
        "baseline_candidate_count": summary["baseline_candidate_count"],
        "bound_shadow_candidate_count": summary["bound_shadow_candidate_count"],
        "missing_authoritative_baseline_score_count": str(missing_score),
        "bound_top20_turnover_rate": summary["bound_top20_turnover_rate"],
        "bound_max_absolute_rank_delta": summary["bound_max_absolute_rank_delta"],
        "bound_average_absolute_rank_delta": summary["bound_average_absolute_rank_delta"],
        "binding_repair_improved_rank_stability": summary["binding_repair_improved_rank_stability"],
        "remaining_rank_impact_severity": summary["remaining_rank_impact_severity"],
        "v20_159_allowed": tf(final_status == PASS_STATUS),
        "blocking_reason": "UPSTREAM_MUTATION_DETECTED" if upstream_mutated else "",
        "final_status": final_status,
        **COMMON,
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [repair])
    write_csv(OUT_SIM, SIM_FIELDS, sim_rows)
    write_csv(OUT_DELTA, DELTA_FIELDS, [summary])
    write_csv(OUT_BINDING, BINDING_FIELDS, binding_rows)
    write_csv(OUT_ADJUST, ADJUST_FIELDS, adjust_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(final_status, summary)

    print(final_status)
    print(f"R1_ROOT_CAUSE_CONFIRMED={tf(root_ok)}")
    print("V20_159_ALLOWED_FROM_R1=FALSE")
    print(f"BASELINE_CANDIDATE_COUNT={summary['baseline_candidate_count']}")
    print(f"BOUND_SHADOW_CANDIDATE_COUNT={summary['bound_shadow_candidate_count']}")
    print(f"MISSING_AUTHORITATIVE_BASELINE_SCORE_COUNT={missing_score}")
    print(f"BOUND_TOP20_TURNOVER_RATE={summary['bound_top20_turnover_rate']}")
    print(f"BOUND_MAX_ABSOLUTE_RANK_DELTA={summary['bound_max_absolute_rank_delta']}")
    print(f"BOUND_AVERAGE_ABSOLUTE_RANK_DELTA={summary['bound_average_absolute_rank_delta']}")
    print(f"BINDING_REPAIR_IMPROVED_RANK_STABILITY={summary['binding_repair_improved_rank_stability']}")
    print(f"REMAINING_RANK_IMPACT_SEVERITY={summary['remaining_rank_impact_severity']}")
    print("PROPOSAL_ROWS_USED_AS_FULL_WEIGHT_TABLE=FALSE")
    print("UNCHANGED_FACTOR_FAMILY_CARRYFORWARD_PRESERVED=TRUE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"SHADOW_SIMULATION_SCOPE={SCOPE}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"V20_159_ALLOWED={tf(final_status == PASS_STATUS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
