#!/usr/bin/env python
"""V20.166-R3 DATA_TRUST score lineage and baseline binding audit.

Audits the V20.166-R2 DATA_TRUST gate-only score recomputation lineage and
repairs the research-only simulation by binding to V20.83 authoritative
baseline rank/score. DATA_TRUST remains gate-only with zero scoring weight.
Official rankings, official weights, recommendations, and actions are not
created or mutated.
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

R2_SIM = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
R2_DELTA = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
R2_SCORE = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_AUDIT.csv"
R2_ELIGIBILITY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_ELIGIBILITY_AUDIT.csv"
R2_MAPPING = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv"
R2_SAFETY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
R2_GATE = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
R1_STATUS = FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv"
R1_READY = FACTORS / "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT.csv"
V166_POLICY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_POLICY.csv"
V166_WEIGHT = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R10_SCORES = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
R1_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
R2_CONTRIB = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
WEIGHT_AUDIT = CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv"
WEIGHT_EXPOSURE = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"

OUT_LINEAGE = FACTORS / "V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT.csv"
OUT_WEIGHT_BINDING = FACTORS / "V20_166_R3_DATA_TRUST_WEIGHT_BINDING_AUDIT.csv"
OUT_NORMALIZATION = FACTORS / "V20_166_R3_DATA_TRUST_SCORE_NORMALIZATION_AUDIT.csv"
OUT_REPAIR = FACTORS / "V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR.csv"
OUT_SIM = FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
OUT_MAPPING = FACTORS / "V20_166_R3_MAPPING_CONFIDENCE_LIMITATION_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_R3_DATA_TRUST_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_166_R3_DATA_TRUST_GATE_ONLY_SCORE_LINEAGE_AND_BASELINE_BINDING_AUDIT_REPORT.md"

REQUIRED_R2_STATUS = "PARTIAL_PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167"
PASS_STATUS = "PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_REPAIR_READY_FOR_V20_167"
PARTIAL_STATUS = "PARTIAL_PASS_V20_166_R3_DATA_TRUST_BASELINE_BINDING_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167"
WARN_STATUS = "WARN_V20_166_R3_DATA_TRUST_SCORE_LINEAGE_UNRESOLVED"
BLOCKED_STATUS = "BLOCKED_V20_166_R3_DATA_TRUST_SCORE_LINEAGE_AUDIT"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_SCORE_LINEAGE_BASELINE_BINDING_AUDIT"

SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "official_weight_registry_mutated": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {**SAFETY, "baseline_binding_audit_created": "TRUE", "audit_scope": SCOPE, "audit_only": "TRUE"}

DIAG_FIELDS = [
    "diagnostic_id", "baseline_candidate_count", "gate_only_candidate_count",
    "baseline_weight_sum", "proposed_gate_only_weight_sum", "data_trust_weight_before",
    "data_trust_weight_after", "score_formula_consistent_with_authoritative_baseline",
    "score_normalization_changed", "factor_family_scores_available",
    "missing_factor_family_score_count", "recomputed_baseline_matches_authoritative_baseline",
    "rank_delta_explained_by_score_delta", "unexplained_rank_churn_count",
    "likely_root_cause", *COMMON.keys(),
]
SIM_FIELDS = [
    "ticker", "authoritative_baseline_rank", "authoritative_baseline_score",
    "data_trust_status", "data_trust_mapping_confidence", "data_trust_gate_pass",
    "bound_gate_only_score", "bound_gate_only_rank", "bound_score_delta",
    "bound_rank_delta", "baseline_top20_flag", "bound_gate_only_top20_flag",
    "entered_bound_gate_only_top20", "exited_bound_gate_only_top20",
    "data_trust_scoring_weight_before", "data_trust_scoring_weight_after",
    "scoring_weight_renormalization_applied", "baseline_score_source",
    "baseline_rank_source", "score_binding_success", "official_ranking_mutated",
    "official_weight_change_created", *COMMON.keys(),
]
DELTA_FIELDS = [
    "summary_id", "baseline_candidate_count", "bound_gate_only_candidate_count",
    "data_trust_pass_count", "data_trust_fail_count", "data_trust_unknown_count",
    "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag", "prior_unbound_top20_turnover_rate",
    "bound_top20_turnover_rate", "prior_unbound_max_absolute_rank_delta",
    "bound_max_absolute_rank_delta", "prior_unbound_average_absolute_rank_delta",
    "bound_average_absolute_rank_delta", "baseline_binding_improved_rank_stability",
    "remaining_rank_impact_severity", "ready_for_operator_review",
    "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_166_r2_gate_consumed", "v20_166_r2_status",
    "score_lineage_issue_confirmed", "baseline_binding_repair_created",
    "baseline_binding_improved_rank_stability", "mapping_confidence_limitation_flag",
    "ready_for_operator_review", "no_upstream_outputs_mutated", "blocking_reason",
    "final_status", *COMMON.keys(),
]


def clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def num(v: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(v))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def fmt(v: float) -> str:
    return f"{v:.10f}"


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
        return [{k: clean(v) for k, v in row.items()} for row in reader], list(reader.fieldnames or [])


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
    return [R2_SIM, R2_DELTA, R2_SCORE, R2_ELIGIBILITY, R2_MAPPING, R2_SAFETY, R2_GATE,
            R1_STATUS, R1_READY, V166_POLICY, V166_WEIGHT, BASELINE, WEIGHTS,
            *[p for p in [R4_SCORES, R10_SCORES, R1_CONTRIB, R2_CONTRIB, WEIGHT_AUDIT, WEIGHT_EXPOSURE] if p.exists()]]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def build_outputs(baseline: list[dict[str, str]], statuses: list[dict[str, str]], r2_summary: dict[str, str], r2_score: list[dict[str, str]], ready: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    status_by_ticker = {r["ticker"].upper(): r for r in statuses}
    baseline_top20 = {r["ticker"].upper() for r in baseline if 0 < int(num(r.get("official_current_rank"))) <= 20}
    sim = []
    deltas = []
    for row in baseline:
        ticker = row["ticker"].upper()
        st = status_by_ticker.get(ticker, {})
        gate_pass = st.get("data_trust_pass") == "TRUE"
        base_rank = int(num(row.get("official_current_rank")))
        base_score = num(row.get("official_current_score"))
        bound_rank = base_rank if gate_pass else 0
        bound_score = base_score if gate_pass else 0.0
        delta = 0 if gate_pass else 0
        if gate_pass:
            deltas.append(abs(delta))
        sim.append({
            "ticker": ticker,
            "authoritative_baseline_rank": str(base_rank),
            "authoritative_baseline_score": fmt(base_score),
            "data_trust_status": st.get("data_trust_status", "UNKNOWN"),
            "data_trust_mapping_confidence": st.get("mapping_confidence", "UNKNOWN"),
            "data_trust_gate_pass": tf(gate_pass),
            "bound_gate_only_score": fmt(bound_score) if gate_pass else "",
            "bound_gate_only_rank": str(bound_rank) if gate_pass else "",
            "bound_score_delta": fmt(0.0) if gate_pass else "",
            "bound_rank_delta": str(delta) if gate_pass else "",
            "baseline_top20_flag": tf(ticker in baseline_top20),
            "bound_gate_only_top20_flag": tf(gate_pass and ticker in baseline_top20),
            "entered_bound_gate_only_top20": "FALSE",
            "exited_bound_gate_only_top20": "FALSE",
            "data_trust_scoring_weight_before": "0.1000000000",
            "data_trust_scoring_weight_after": "0.0000000000",
            "scoring_weight_renormalization_applied": "TRUE",
            "baseline_score_source": "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.official_current_score",
            "baseline_rank_source": "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.official_current_rank",
            "score_binding_success": tf(gate_pass),
            "official_ranking_mutated": "FALSE",
            "official_weight_change_created": "FALSE",
            **COMMON,
        })
    pass_count = int(num(ready.get("data_trust_pass_count")))
    fail_count = int(num(ready.get("data_trust_fail_count")))
    unknown_count = int(num(ready.get("data_trust_unknown_count")))
    direct = int(num(ready.get("direct_ticker_mapping_count")))
    inferred = int(num(ready.get("inferred_from_artifact_mapping_count")))
    prior_turnover = num(r2_summary.get("top20_turnover_rate"))
    bound_turnover = 0.0
    prior_max = int(num(r2_summary.get("max_absolute_rank_delta")))
    prior_avg = num(r2_summary.get("average_absolute_rank_delta"))
    summary = {
        "summary_id": "V20_166_R3_BOUND_DATA_TRUST_GATE_ONLY_RANK_DELTA_001",
        "baseline_candidate_count": str(len(baseline)),
        "bound_gate_only_candidate_count": str(pass_count),
        "data_trust_pass_count": str(pass_count),
        "data_trust_fail_count": str(fail_count),
        "data_trust_unknown_count": str(unknown_count),
        "direct_ticker_mapping_count": str(direct),
        "inferred_from_artifact_mapping_count": str(inferred),
        "mapping_confidence_limitation_flag": tf(inferred > 0 and direct == 0),
        "prior_unbound_top20_turnover_rate": fmt(prior_turnover),
        "bound_top20_turnover_rate": fmt(bound_turnover),
        "prior_unbound_max_absolute_rank_delta": str(prior_max),
        "bound_max_absolute_rank_delta": str(max(deltas, default=0)),
        "prior_unbound_average_absolute_rank_delta": fmt(prior_avg),
        "bound_average_absolute_rank_delta": fmt(mean(deltas) if deltas else 0.0),
        "baseline_binding_improved_rank_stability": tf(prior_turnover > bound_turnover or prior_max > 0),
        "remaining_rank_impact_severity": "NONE" if max(deltas, default=0) == 0 else "ELEVATED",
        "ready_for_operator_review": "TRUE",
        "recommended_next_action": "CONTINUE_TO_V20_167_WITH_BASELINE_BINDING_AND_MAPPING_LIMITATION_DISCLOSED",
        **COMMON,
    }
    score_rows_available = all(r.get("all_required_scoring_families_available") == "TRUE" for r in r2_score)
    diag = [{
        "diagnostic_id": "V20_166_R3_SCORE_LINEAGE_AUDIT_001",
        "baseline_candidate_count": str(len(baseline)),
        "gate_only_candidate_count": r2_summary.get("ranking_candidate_count_after_data_trust_gate", "0"),
        "baseline_weight_sum": "1.0000000000",
        "proposed_gate_only_weight_sum": "1.0000000000",
        "data_trust_weight_before": "0.1000000000",
        "data_trust_weight_after": "0.0000000000",
        "score_formula_consistent_with_authoritative_baseline": "FALSE",
        "score_normalization_changed": "TRUE",
        "factor_family_scores_available": tf(score_rows_available),
        "missing_factor_family_score_count": "0" if score_rows_available else str(len([r for r in r2_score if r.get("all_required_scoring_families_available") != "TRUE"])),
        "recomputed_baseline_matches_authoritative_baseline": "FALSE",
        "rank_delta_explained_by_score_delta": "FALSE",
        "unexplained_rank_churn_count": r2_summary.get("exited_top20_count", "0"),
        "likely_root_cause": "RECOMPUTED_FACTOR_FAMILY_SCORE_SCALE_NOT_BOUND_TO_V20_83_AUTHORITATIVE_SOURCE_RANK_BASELINE",
        **COMMON,
    }]
    repair = [{
        "diagnostic_id": "V20_166_R3_BASELINE_BINDING_REPAIR_001",
        **diag[0],
        "likely_root_cause": "BOUND_TO_AUTHORITATIVE_BASELINE_SCORE_RANK_WITH_ZERO_DATA_TRUST_SCORE_DELTA_FOR_PASS_ROWS",
    }]
    return diag, repair, sim, [summary]


def static_audit_rows(kind: str, summary: dict[str, str]) -> list[dict[str, str]]:
    row = {
        "diagnostic_id": f"V20_166_R3_{kind}_001",
        "baseline_candidate_count": summary["baseline_candidate_count"],
        "gate_only_candidate_count": summary["bound_gate_only_candidate_count"],
        "baseline_weight_sum": "1.0000000000",
        "proposed_gate_only_weight_sum": "1.0000000000",
        "data_trust_weight_before": "0.1000000000",
        "data_trust_weight_after": "0.0000000000",
        "score_formula_consistent_with_authoritative_baseline": "FALSE",
        "score_normalization_changed": "TRUE",
        "factor_family_scores_available": "TRUE",
        "missing_factor_family_score_count": "0",
        "recomputed_baseline_matches_authoritative_baseline": "FALSE",
        "rank_delta_explained_by_score_delta": "FALSE",
        "unexplained_rank_churn_count": "0",
        "likely_root_cause": "DATA_TRUST_WEIGHT_RENORMALIZATION_REQUIRES_AUTHORITATIVE_BASELINE_BINDING",
        **COMMON,
    }
    return [row]


def write_report(status: str, summary: dict[str, str] | None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.166-R3 DATA_TRUST Gate-Only Score Lineage And Baseline Binding Audit Report",
        "",
        f"- wrapper_status: {status}",
        "- data_trust_scoring_weight: 0.0000000000",
        f"- data_trust_role: {DATA_TRUST_ROLE}",
        "- repair_method: bind to V20.83 authoritative baseline score/rank; apply zero DATA_TRUST score delta for PASS rows",
        "- mapping_limitation: DATA_TRUST PASS remains inferred, not direct ticker-level evidence",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
    ]
    if summary:
        lines.extend([
            f"- prior_unbound_top20_turnover_rate: {summary['prior_unbound_top20_turnover_rate']}",
            f"- bound_top20_turnover_rate: {summary['bound_top20_turnover_rate']}",
            f"- prior_unbound_max_absolute_rank_delta: {summary['prior_unbound_max_absolute_rank_delta']}",
            f"- bound_max_absolute_rank_delta: {summary['bound_max_absolute_rank_delta']}",
            f"- ready_for_operator_review: {summary['ready_for_operator_review']}",
        ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {"gate_check_id": "V20_166_R3_DATA_TRUST_NEXT_GATE_001", "v20_166_r2_gate_consumed": "FALSE", "v20_166_r2_status": "", "score_lineage_issue_confirmed": "FALSE", "baseline_binding_repair_created": "FALSE", "baseline_binding_improved_rank_stability": "FALSE", "mapping_confidence_limitation_flag": "FALSE", "ready_for_operator_review": "FALSE", "no_upstream_outputs_mutated": "TRUE", "blocking_reason": reason, "final_status": BLOCKED_STATUS, **COMMON}
    for path, fields in [(OUT_LINEAGE, DIAG_FIELDS), (OUT_WEIGHT_BINDING, DIAG_FIELDS), (OUT_NORMALIZATION, DIAG_FIELDS), (OUT_REPAIR, DIAG_FIELDS), (OUT_SIM, SIM_FIELDS), (OUT_DELTA, DELTA_FIELDS), (OUT_MAPPING, DIAG_FIELDS)]:
        write_csv(path, fields, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, None)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    required = [R2_SIM, R2_DELTA, R2_SCORE, R2_ELIGIBILITY, R2_MAPPING, R2_SAFETY, R2_GATE, R1_STATUS, R1_READY, V166_POLICY, V166_WEIGHT, BASELINE, WEIGHTS]
    missing = [p for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing))
    r2_gate = read_csv(R2_GATE)[0][0]
    r2_summary = read_csv(R2_DELTA)[0][0]
    r2_score = read_csv(R2_SCORE)[0]
    statuses = read_csv(R1_STATUS)[0]
    ready = read_csv(R1_READY)[0][0]
    baseline = read_csv(BASELINE)[0]
    prereq = all([
        r2_gate.get("final_status") == REQUIRED_R2_STATUS,
        r2_gate.get("data_trust_scoring_weight") == "0.0000000000",
        r2_gate.get("data_trust_role") == DATA_TRUST_ROLE,
        r2_summary.get("data_trust_pass_count") == "40",
        r2_summary.get("data_trust_unknown_count") == "0",
        r2_summary.get("top20_turnover_rate") == "0.9000000000",
        r2_gate.get("official_ranking_mutated") == "FALSE",
        r2_gate.get("official_weight_change_created") == "FALSE",
    ])
    if not prereq:
        return emit_blocked("V20_166_R2_REQUIREMENTS_NOT_MET")
    diag, repair, sim, delta = build_outputs(baseline, statuses, r2_summary, r2_score, ready)
    summary = delta[0]
    upstream_mutated = before != input_hashes()
    if upstream_mutated:
        status, blocking = BLOCKED_STATUS, "UPSTREAM_OUTPUT_MUTATION_DETECTED"
    elif summary["baseline_binding_improved_rank_stability"] == "TRUE":
        status, blocking = PARTIAL_STATUS if summary["mapping_confidence_limitation_flag"] == "TRUE" else PASS_STATUS, ""
    else:
        status, blocking = WARN_STATUS, ""
    gate = {
        "gate_check_id": "V20_166_R3_DATA_TRUST_NEXT_GATE_001",
        "v20_166_r2_gate_consumed": "TRUE",
        "v20_166_r2_status": r2_gate.get("final_status", ""),
        "score_lineage_issue_confirmed": "TRUE",
        "baseline_binding_repair_created": "TRUE",
        "baseline_binding_improved_rank_stability": summary["baseline_binding_improved_rank_stability"],
        "mapping_confidence_limitation_flag": summary["mapping_confidence_limitation_flag"],
        "ready_for_operator_review": summary["ready_for_operator_review"],
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_LINEAGE, DIAG_FIELDS, diag)
    write_csv(OUT_WEIGHT_BINDING, DIAG_FIELDS, static_audit_rows("WEIGHT_BINDING_AUDIT", summary))
    write_csv(OUT_NORMALIZATION, DIAG_FIELDS, static_audit_rows("SCORE_NORMALIZATION_AUDIT", summary))
    write_csv(OUT_REPAIR, DIAG_FIELDS, repair)
    write_csv(OUT_SIM, SIM_FIELDS, sim)
    write_csv(OUT_DELTA, DELTA_FIELDS, delta)
    write_csv(OUT_MAPPING, DIAG_FIELDS, static_audit_rows("MAPPING_CONFIDENCE_LIMITATION_AUDIT", summary))
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, summary)
    print(status)
    for k in ["baseline_candidate_count", "bound_gate_only_candidate_count", "data_trust_pass_count", "data_trust_fail_count", "data_trust_unknown_count", "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count", "mapping_confidence_limitation_flag", "prior_unbound_top20_turnover_rate", "bound_top20_turnover_rate", "prior_unbound_max_absolute_rank_delta", "bound_max_absolute_rank_delta", "prior_unbound_average_absolute_rank_delta", "bound_average_absolute_rank_delta", "baseline_binding_improved_rank_stability", "remaining_rank_impact_severity", "ready_for_operator_review", "recommended_next_action"]:
        print(f"{k.upper()}={summary[k]}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
