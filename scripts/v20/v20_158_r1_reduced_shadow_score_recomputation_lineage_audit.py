#!/usr/bin/env python
"""V20.158-R1 reduced shadow score recomputation lineage audit.

Diagnoses why V20.158 reduced shadow deltas still produced unstable rank
impact. This is an audit-only stage: it reads V20.158/V20.157/base ranking
artifacts, writes new V20.158-R1 diagnostics, and does not mutate official
rankings, weights, proposals, or upstream outputs.
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

V158_SIM = FACTORS / "V20_158_REDUCED_SHADOW_WEIGHT_RANKING_SIMULATION.csv"
V158_DELTA = FACTORS / "V20_158_REDUCED_SHADOW_VS_BASELINE_RANK_DELTA.csv"
V158_GATE = FACTORS / "V20_158_REDUCED_SHADOW_RANKING_GATE.csv"
V158_SOURCE = FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SOURCE_AUDIT.csv"
V158_SAFETY = FACTORS / "V20_158_REDUCED_SHADOW_RANKING_SAFETY_AUDIT.csv"
V158_COMPARISON = FACTORS / "V20_158_REDUCED_VS_ORIGINAL_SHADOW_IMPACT_COMPARISON.csv"
V157_PROPOSAL = FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv"
V157_GATE = FACTORS / "V20_157_DELTA_REDUCTION_GATE.csv"
BASE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
BASELINE_RANKING = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_LINEAGE = FACTORS / "V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT.csv"
OUT_WEIGHT = FACTORS / "V20_158_R1_WEIGHT_BINDING_AUDIT.csv"
OUT_CARRY = FACTORS / "V20_158_R1_UNCHANGED_FACTOR_CARRYFORWARD_AUDIT.csv"
OUT_NORM = FACTORS / "V20_158_R1_SCORE_NORMALIZATION_AUDIT.csv"
OUT_CAUSAL = FACTORS / "V20_158_R1_RANK_IMPACT_CAUSAL_DIAGNOSTIC.csv"
OUT_GATE = FACTORS / "V20_158_R1_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_158_R1_REDUCED_SHADOW_SCORE_RECOMPUTATION_LINEAGE_AUDIT_REPORT.md"

REQUIRED_V158_STATUS = "WARN_V20_158_REDUCED_SHADOW_RANKING_STILL_TOO_UNSTABLE"
PASS_STATUS = "PASS_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT_READY_FOR_REPAIR"
PARTIAL_STATUS = "PARTIAL_PASS_V20_158_R1_LINEAGE_AUDIT_WITH_UNCONFIRMED_ROOT_CAUSE"
BLOCKED_STATUS = "BLOCKED_V20_158_R1_SCORE_RECOMPUTATION_LINEAGE_AUDIT"
SCOPE = "RESEARCH_ONLY_LINEAGE_AUDIT"
FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "new_shadow_proposal_created": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "v20_159_allowed": "FALSE",
}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "lineage_audit_only": "TRUE",
    "audit_only": "TRUE",
}

LINEAGE_FIELDS = [
    "ticker",
    "baseline_rank",
    "recomputed_baseline_rank",
    "recomputed_baseline_rank_delta",
    "reduced_shadow_rank",
    "reduced_shadow_rank_delta",
    "baseline_score",
    "reduced_shadow_score",
    "reduced_score_delta",
    "score_formula_consistent_with_baseline",
    "score_delta_proportional_to_weight_delta",
    "rank_delta_explained_by_score_delta",
    "unexplained_rank_churn",
    "likely_root_cause",
    *COMMON.keys(),
]
WEIGHT_FIELDS = [
    "factor_family",
    "base_weight",
    "current_research_weight_from_proposal",
    "reduced_weight_delta",
    "reduced_shadow_weight",
    "base_weight_missing",
    "current_research_weight_missing",
    "proposal_row_present",
    "unchanged_factor_family_carryforward",
    "weight_binding_status",
    "exclusion_reason",
    *COMMON.keys(),
]
CARRY_FIELDS = [
    "factor_family",
    "proposal_row_present",
    "base_weight_present",
    "carryforward_required",
    "carryforward_applied",
    "carryforward_status",
    "exclusion_reason",
    *COMMON.keys(),
]
NORM_FIELDS = [
    "normalization_audit_id",
    "baseline_weight_sum",
    "reduced_shadow_weight_sum",
    "score_normalization_changed",
    "proposal_rows_used_as_full_weight_table",
    "score_formula_consistent_with_baseline",
    "normalization_diagnostic",
    *COMMON.keys(),
]
CAUSAL_FIELDS = [
    "diagnostic_id",
    "baseline_weight_sum",
    "reduced_shadow_weight_sum",
    "missing_base_weight_count",
    "missing_current_research_weight_count",
    "unchanged_factor_family_carryforward_count",
    "unchanged_factor_family_missing_count",
    "score_formula_consistent_with_baseline",
    "score_normalization_changed",
    "proposal_rows_used_as_full_weight_table",
    "score_delta_proportional_to_weight_delta",
    "rank_delta_explained_by_score_delta",
    "unexplained_rank_churn_count",
    "likely_root_cause",
    "recommended_repair_action",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_158_status",
    "v20_158_warn_status_confirmed",
    "baseline_weight_sum",
    "reduced_shadow_weight_sum",
    "missing_base_weight_count",
    "missing_current_research_weight_count",
    "unchanged_factor_family_carryforward_count",
    "unchanged_factor_family_missing_count",
    "score_formula_consistent_with_baseline",
    "score_normalization_changed",
    "proposal_rows_used_as_full_weight_table",
    "score_delta_proportional_to_weight_delta",
    "rank_delta_explained_by_score_delta",
    "unexplained_rank_churn_count",
    "likely_root_cause",
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
    return [
        V158_SIM, V158_DELTA, V158_GATE, V158_SOURCE, V158_SAFETY, V158_COMPARISON,
        V157_PROPOSAL, V157_GATE, BASE_WEIGHT_REGISTRY, BASELINE_RANKING,
    ]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def base_weight_map(rows: list[dict[str, str]]) -> dict[str, float]:
    out = {}
    for row in rows:
        family = row.get("factor_family", "")
        if family:
            out[family] = num(row.get("active_research_base_weight"), math.nan)
    return out


def proposal_delta_map(rows: list[dict[str, str]]) -> tuple[dict[str, float], dict[str, str]]:
    deltas: dict[str, float] = {}
    current_weights: dict[str, str] = {}
    for row in rows:
        family = row.get("factor_family", "")
        if not family:
            continue
        deltas[family] = deltas.get(family, 0.0) + num(row.get("reduced_proposed_delta"))
        if row.get("original_shadow_proposed_weight") or row.get("original_proposed_delta"):
            original_weight = num(row.get("original_shadow_proposed_weight")) - num(row.get("original_proposed_delta"))
            current_weights.setdefault(family, fmt(original_weight))
        elif row.get("current_research_weight"):
            current_weights.setdefault(family, row.get("current_research_weight", ""))
    return deltas, current_weights


def baseline_rank_map(rows: list[dict[str, str]]) -> dict[str, int]:
    out = {}
    for row in rows:
        ticker = row.get("ticker") or row.get("normalized_ticker") or row.get("ticker_or_candidate_id")
        if ticker:
            out[ticker] = int(num(row.get("official_current_rank") or row.get("baseline_rank") or row.get("report_rank"), 0))
    return out


def recomputed_rank_map(sim_rows: list[dict[str, str]]) -> dict[str, int]:
    ranked = sorted(sim_rows, key=lambda row: (-num(row.get("baseline_score")), int(num(row.get("baseline_rank"))), row.get("ticker", "")))
    return {row.get("ticker", ""): index for index, row in enumerate(ranked, start=1)}


def build_weight_audits(base_weights: dict[str, float], deltas: dict[str, float], current_weights: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object]]:
    weight_rows = []
    carry_rows = []
    missing_base = 0
    missing_current = 0
    carry_count = 0
    carry_missing = 0
    for family in FAMILIES:
        base = base_weights.get(family, math.nan)
        delta = deltas.get(family, 0.0)
        proposal_present = family in deltas
        current = current_weights.get(family, "")
        base_missing = math.isnan(base)
        current_missing = proposal_present and current == ""
        if base_missing:
            missing_base += 1
        if current_missing:
            missing_current += 1
        carry_required = not proposal_present
        carry_applied = carry_required and not base_missing
        if carry_applied:
            carry_count += 1
        if carry_required and base_missing:
            carry_missing += 1
        reduced_weight = 0.0 if base_missing else base + delta
        status = "PASS" if not base_missing and not current_missing else "PARTIAL"
        weight_rows.append({
            "factor_family": family,
            "base_weight": "" if base_missing else fmt(base),
            "current_research_weight_from_proposal": current,
            "reduced_weight_delta": fmt(delta),
            "reduced_shadow_weight": "" if base_missing else fmt(reduced_weight),
            "base_weight_missing": tf(base_missing),
            "current_research_weight_missing": tf(current_missing),
            "proposal_row_present": tf(proposal_present),
            "unchanged_factor_family_carryforward": tf(carry_applied),
            "weight_binding_status": status,
            "exclusion_reason": "MISSING_BASE_WEIGHT" if base_missing else ("MISSING_CURRENT_RESEARCH_WEIGHT_ON_PROPOSAL_FAMILY" if current_missing else ""),
            **COMMON,
        })
        carry_rows.append({
            "factor_family": family,
            "proposal_row_present": tf(proposal_present),
            "base_weight_present": tf(not base_missing),
            "carryforward_required": tf(carry_required),
            "carryforward_applied": tf(carry_applied),
            "carryforward_status": "CARRIED_FORWARD" if carry_applied else ("NOT_REQUIRED" if proposal_present else "MISSING"),
            "exclusion_reason": "" if carry_applied or proposal_present else "MISSING_BASE_WEIGHT_FOR_UNCHANGED_FAMILY",
            **COMMON,
        })
    baseline_sum = sum(value for value in base_weights.values() if not math.isnan(value))
    reduced_sum = sum((0.0 if math.isnan(base_weights.get(family, math.nan)) else base_weights[family]) + deltas.get(family, 0.0) for family in FAMILIES)
    return weight_rows, carry_rows, {
        "baseline_weight_sum": baseline_sum,
        "reduced_shadow_weight_sum": reduced_sum,
        "missing_base_weight_count": missing_base,
        "missing_current_research_weight_count": missing_current,
        "unchanged_factor_family_carryforward_count": carry_count,
        "unchanged_factor_family_missing_count": carry_missing,
    }


def build_lineage(sim_rows: list[dict[str, str]], baseline_ranks: dict[str, int]) -> tuple[list[dict[str, str]], dict[str, object]]:
    recomputed = recomputed_rank_map(sim_rows)
    rows = []
    inconsistent = 0
    unexplained = 0
    proportional_fail = 0
    explained_fail = 0
    for row in sim_rows:
        ticker = row.get("ticker", "")
        baseline_rank = baseline_ranks.get(ticker, int(num(row.get("baseline_rank"))))
        recomputed_rank = recomputed.get(ticker, baseline_rank)
        reduced_rank_delta = int(num(row.get("reduced_shadow_rank_delta")))
        recomputed_delta = baseline_rank - recomputed_rank
        score_delta = num(row.get("reduced_score_delta"))
        formula_consistent = recomputed_rank == baseline_rank
        proportional = abs(score_delta) > 0 or reduced_rank_delta == 0
        explained = abs(reduced_rank_delta) <= 2 or abs(score_delta) >= 0.005
        row_unexplained = (not formula_consistent) and abs(reduced_rank_delta) >= 5
        if not formula_consistent:
            inconsistent += 1
        if not proportional:
            proportional_fail += 1
        if not explained:
            explained_fail += 1
        if row_unexplained:
            unexplained += 1
        cause = "RECOMPUTED_BASELINE_SCORE_ORDER_DIFFERS_FROM_AUTHORITATIVE_BASELINE_RANK" if row_unexplained else "NO_MATERIAL_UNEXPLAINED_CHURN"
        rows.append({
            "ticker": ticker,
            "baseline_rank": str(baseline_rank),
            "recomputed_baseline_rank": str(recomputed_rank),
            "recomputed_baseline_rank_delta": str(recomputed_delta),
            "reduced_shadow_rank": row.get("reduced_shadow_rank", ""),
            "reduced_shadow_rank_delta": row.get("reduced_shadow_rank_delta", ""),
            "baseline_score": row.get("baseline_score", ""),
            "reduced_shadow_score": row.get("reduced_shadow_score", ""),
            "reduced_score_delta": row.get("reduced_score_delta", ""),
            "score_formula_consistent_with_baseline": tf(formula_consistent),
            "score_delta_proportional_to_weight_delta": tf(proportional),
            "rank_delta_explained_by_score_delta": tf(explained),
            "unexplained_rank_churn": tf(row_unexplained),
            "likely_root_cause": cause,
            **COMMON,
        })
    return rows, {
        "score_formula_consistent_with_baseline": inconsistent == 0,
        "score_delta_proportional_to_weight_delta": proportional_fail == 0,
        "rank_delta_explained_by_score_delta": explained_fail == 0,
        "unexplained_rank_churn_count": unexplained,
        "average_recomputed_baseline_rank_delta": mean(abs(int(row["recomputed_baseline_rank_delta"])) for row in rows) if rows else 0.0,
    }


def likely_root_cause(metrics: dict[str, object], proposal_rows_used_as_full_weight_table: bool, normalization_changed: bool) -> str:
    if proposal_rows_used_as_full_weight_table:
        return "PROPOSAL_ROWS_USED_AS_FULL_WEIGHT_TABLE_INSTEAD_OF_DELTA_OVER_BASE_WEIGHTS"
    if not metrics["score_formula_consistent_with_baseline"]:
        return "RECOMPUTED_BASELINE_SCORE_FORMULA_NOT_CONSISTENT_WITH_AUTHORITATIVE_BASELINE_RANKING"
    if normalization_changed:
        return "WEIGHT_SUM_NORMALIZATION_CHANGED_SCORE_SCALE"
    if not metrics["rank_delta_explained_by_score_delta"]:
        return "RANK_DELTA_NOT_EXPLAINED_BY_REDUCED_SCORE_DELTA"
    return "ROOT_CAUSE_NOT_CONFIRMED"


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_158_R1_NEXT_GATE_001",
        "v20_158_status": "",
        "v20_158_warn_status_confirmed": "FALSE",
        "baseline_weight_sum": "0",
        "reduced_shadow_weight_sum": "0",
        "missing_base_weight_count": "0",
        "missing_current_research_weight_count": "0",
        "unchanged_factor_family_carryforward_count": "0",
        "unchanged_factor_family_missing_count": "0",
        "score_formula_consistent_with_baseline": "FALSE",
        "score_normalization_changed": "FALSE",
        "proposal_rows_used_as_full_weight_table": "FALSE",
        "score_delta_proportional_to_weight_delta": "FALSE",
        "rank_delta_explained_by_score_delta": "FALSE",
        "unexplained_rank_churn_count": "0",
        "likely_root_cause": "",
        "v20_159_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_LINEAGE, LINEAGE_FIELDS, [])
    write_csv(OUT_WEIGHT, WEIGHT_FIELDS, [])
    write_csv(OUT_CARRY, CARRY_FIELDS, [])
    write_csv(OUT_NORM, NORM_FIELDS, [])
    write_csv(OUT_CAUSAL, CAUSAL_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, {})
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def write_report(status: str, causal: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.158-R1 Reduced Shadow Score Recomputation Lineage Audit Report",
        "",
        f"- wrapper_status: {status}",
        f"- likely_root_cause: {causal.get('likely_root_cause', '')}",
        f"- unexplained_rank_churn_count: {causal.get('unexplained_rank_churn_count', '')}",
        f"- baseline_weight_sum: {causal.get('baseline_weight_sum', '')}",
        f"- reduced_shadow_weight_sum: {causal.get('reduced_shadow_weight_sum', '')}",
        "- v20_159_allowed: FALSE",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
        "- new_shadow_proposal_created: FALSE",
        "",
        "This stage is diagnostic only and does not create a new shadow proposal or proceed to V20.159.",
    ]) + "\n", encoding="utf-8")


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    sim_rows, _ = read_csv(V158_SIM)
    gate_rows, _ = read_csv(V158_GATE)
    proposal_rows, _ = read_csv(V157_PROPOSAL)
    registry_rows, _ = read_csv(BASE_WEIGHT_REGISTRY)
    baseline_rows, _ = read_csv(BASELINE_RANKING)
    if not all([sim_rows, gate_rows, proposal_rows, registry_rows, baseline_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v158_status = gate_rows[0].get("final_status", "")
    if v158_status != REQUIRED_V158_STATUS:
        return emit_blocked("V20_158_STATUS_NOT_WARN_STILL_TOO_UNSTABLE")

    weights = base_weight_map(registry_rows)
    deltas, current_weights = proposal_delta_map(proposal_rows)
    weight_rows, carry_rows, weight_metrics = build_weight_audits(weights, deltas, current_weights)
    lineage_rows, lineage_metrics = build_lineage(sim_rows, baseline_rank_map(baseline_rows))
    baseline_sum = float(weight_metrics["baseline_weight_sum"])
    reduced_sum = float(weight_metrics["reduced_shadow_weight_sum"])
    normalization_changed = abs(reduced_sum - baseline_sum) > 1e-9
    proposal_rows_used_as_full_weight_table = len(deltas) == len(FAMILIES) and abs(reduced_sum - sum(deltas.values())) < 1e-9
    root = likely_root_cause(lineage_metrics, proposal_rows_used_as_full_weight_table, normalization_changed)
    causal = {
        "diagnostic_id": "V20_158_R1_RANK_IMPACT_CAUSAL_DIAGNOSTIC_001",
        "baseline_weight_sum": fmt(baseline_sum),
        "reduced_shadow_weight_sum": fmt(reduced_sum),
        "missing_base_weight_count": str(weight_metrics["missing_base_weight_count"]),
        "missing_current_research_weight_count": str(weight_metrics["missing_current_research_weight_count"]),
        "unchanged_factor_family_carryforward_count": str(weight_metrics["unchanged_factor_family_carryforward_count"]),
        "unchanged_factor_family_missing_count": str(weight_metrics["unchanged_factor_family_missing_count"]),
        "score_formula_consistent_with_baseline": tf(bool(lineage_metrics["score_formula_consistent_with_baseline"])),
        "score_normalization_changed": tf(normalization_changed),
        "proposal_rows_used_as_full_weight_table": tf(proposal_rows_used_as_full_weight_table),
        "score_delta_proportional_to_weight_delta": tf(bool(lineage_metrics["score_delta_proportional_to_weight_delta"])),
        "rank_delta_explained_by_score_delta": tf(bool(lineage_metrics["rank_delta_explained_by_score_delta"])),
        "unexplained_rank_churn_count": str(lineage_metrics["unexplained_rank_churn_count"]),
        "likely_root_cause": root,
        "recommended_repair_action": "ALIGN_REDUCED_SHADOW_RECOMPUTE_WITH_AUTHORITATIVE_BASELINE_SCORE_LINEAGE_AND_CARRYFORWARD_FULL_BASE_WEIGHT_TABLE",
        **COMMON,
    }
    norm = {
        "normalization_audit_id": "V20_158_R1_SCORE_NORMALIZATION_AUDIT_001",
        "baseline_weight_sum": fmt(baseline_sum),
        "reduced_shadow_weight_sum": fmt(reduced_sum),
        "score_normalization_changed": tf(normalization_changed),
        "proposal_rows_used_as_full_weight_table": tf(proposal_rows_used_as_full_weight_table),
        "score_formula_consistent_with_baseline": causal["score_formula_consistent_with_baseline"],
        "normalization_diagnostic": "REDUCED_WEIGHT_SUM_DIFFERS_FROM_BASELINE_WEIGHT_SUM" if normalization_changed else "NO_WEIGHT_SUM_NORMALIZATION_CHANGE_DETECTED",
        **COMMON,
    }
    upstream_mutated = before != input_hashes()
    confirmed = root != "ROOT_CAUSE_NOT_CONFIRMED"
    status = BLOCKED_STATUS if upstream_mutated else (PASS_STATUS if confirmed else PARTIAL_STATUS)
    gate = {
        "gate_check_id": "V20_158_R1_NEXT_GATE_001",
        "v20_158_status": v158_status,
        "v20_158_warn_status_confirmed": "TRUE",
        "baseline_weight_sum": causal["baseline_weight_sum"],
        "reduced_shadow_weight_sum": causal["reduced_shadow_weight_sum"],
        "missing_base_weight_count": causal["missing_base_weight_count"],
        "missing_current_research_weight_count": causal["missing_current_research_weight_count"],
        "unchanged_factor_family_carryforward_count": causal["unchanged_factor_family_carryforward_count"],
        "unchanged_factor_family_missing_count": causal["unchanged_factor_family_missing_count"],
        "score_formula_consistent_with_baseline": causal["score_formula_consistent_with_baseline"],
        "score_normalization_changed": causal["score_normalization_changed"],
        "proposal_rows_used_as_full_weight_table": causal["proposal_rows_used_as_full_weight_table"],
        "score_delta_proportional_to_weight_delta": causal["score_delta_proportional_to_weight_delta"],
        "rank_delta_explained_by_score_delta": causal["rank_delta_explained_by_score_delta"],
        "unexplained_rank_churn_count": causal["unexplained_rank_churn_count"],
        "likely_root_cause": causal["likely_root_cause"],
        "v20_159_allowed": "FALSE",
        "blocking_reason": "UPSTREAM_MUTATION_DETECTED" if upstream_mutated else "",
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_LINEAGE, LINEAGE_FIELDS, lineage_rows)
    write_csv(OUT_WEIGHT, WEIGHT_FIELDS, weight_rows)
    write_csv(OUT_CARRY, CARRY_FIELDS, carry_rows)
    write_csv(OUT_NORM, NORM_FIELDS, [norm])
    write_csv(OUT_CAUSAL, CAUSAL_FIELDS, [causal])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, causal)

    print(status)
    print("V20_158_WARN_STATUS_CONFIRMED=TRUE")
    print(f"BASELINE_WEIGHT_SUM={causal['baseline_weight_sum']}")
    print(f"REDUCED_SHADOW_WEIGHT_SUM={causal['reduced_shadow_weight_sum']}")
    print(f"MISSING_BASE_WEIGHT_COUNT={causal['missing_base_weight_count']}")
    print(f"MISSING_CURRENT_RESEARCH_WEIGHT_COUNT={causal['missing_current_research_weight_count']}")
    print(f"UNCHANGED_FACTOR_FAMILY_CARRYFORWARD_COUNT={causal['unchanged_factor_family_carryforward_count']}")
    print(f"UNCHANGED_FACTOR_FAMILY_MISSING_COUNT={causal['unchanged_factor_family_missing_count']}")
    print(f"SCORE_FORMULA_CONSISTENT_WITH_BASELINE={causal['score_formula_consistent_with_baseline']}")
    print(f"SCORE_NORMALIZATION_CHANGED={causal['score_normalization_changed']}")
    print(f"PROPOSAL_ROWS_USED_AS_FULL_WEIGHT_TABLE={causal['proposal_rows_used_as_full_weight_table']}")
    print(f"SCORE_DELTA_PROPORTIONAL_TO_WEIGHT_DELTA={causal['score_delta_proportional_to_weight_delta']}")
    print(f"RANK_DELTA_EXPLAINED_BY_SCORE_DELTA={causal['rank_delta_explained_by_score_delta']}")
    print(f"UNEXPLAINED_RANK_CHURN_COUNT={causal['unexplained_rank_churn_count']}")
    print(f"LIKELY_ROOT_CAUSE={causal['likely_root_cause']}")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("NEW_SHADOW_PROPOSAL_CREATED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("V20_159_ALLOWED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
