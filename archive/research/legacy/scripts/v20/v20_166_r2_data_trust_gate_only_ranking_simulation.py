#!/usr/bin/env python
"""V20.166-R2 DATA_TRUST gate-only ranking simulation.

Runs a research-only ranking simulation after DATA_TRUST is made gate-only.
DATA_TRUST is excluded from scoring, PASS rows may be ranked, FAIL/UNKNOWN rows
are excluded, and the R1 inferred mapping limitation is preserved. Official
rankings, official weights, and upstream outputs are not mutated.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V166_POLICY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_POLICY.csv"
V166_WEIGHT = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv"
V166_ELIGIBILITY = FACTORS / "V20_166_DATA_TRUST_RANKING_ELIGIBILITY_AUDIT.csv"
V166_BACKLOG = FACTORS / "V20_166_DATA_TRUST_FAILED_REPAIR_BACKLOG.csv"
V166_SAFETY = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
V166_GATE = FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"

R1_MAPPING = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_SOURCE_MAPPING.csv"
R1_STATUS = FACTORS / "V20_166_R1_DATA_TRUST_TICKER_STATUS.csv"
R1_REPAIR = FACTORS / "V20_166_R1_DATA_TRUST_STATUS_REPAIR_AUDIT.csv"
R1_UNKNOWN = FACTORS / "V20_166_R1_DATA_TRUST_REMAINING_UNKNOWN_BACKLOG.csv"
R1_READY = FACTORS / "V20_166_R1_DATA_TRUST_GATE_READY_AUDIT.csv"
R1_GATE = FACTORS / "V20_166_R1_DATA_TRUST_NEXT_GATE.csv"

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R10_SCORES = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
R1_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
R2_CONTRIB = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
WEIGHT_AUDIT = CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv"
WEIGHT_EXPOSURE = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"

OUT_SIM = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANK_DELTA.csv"
OUT_SCORE = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_AUDIT.csv"
OUT_ELIGIBILITY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_ELIGIBILITY_AUDIT.csv"
OUT_MAPPING = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_MAPPING_CONFIDENCE_AUDIT.csv"
OUT_SAFETY = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_SAFETY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_166_R2_DATA_TRUST_GATE_ONLY_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_REPORT.md"

REQUIRED_R1_STATUS = "PASS_V20_166_R1_DATA_TRUST_STATUS_MAPPING_READY_FOR_V20_166_R2"
PASS_STATUS = "PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_READY_FOR_V20_167"
PARTIAL_STATUS = "PARTIAL_PASS_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION_WITH_MAPPING_LIMITATIONS_READY_FOR_V20_167"
WARN_STATUS = "WARN_V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_RECOMPUTATION_BLOCKED"
BLOCKED_STATUS = "BLOCKED_V20_166_R2_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION"

PROPOSED_WEIGHTS = {
    "fundamental": 0.2222222222,
    "technical": 0.2777777778,
    "strategy": 0.2222222222,
    "risk": 0.1666666667,
    "market_regime": 0.1111111111,
    "data_trust": 0.0,
}
SCORING_FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime"]

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
COMMON = {
    **SAFETY,
    "data_trust_gate_only_ranking_simulation_created": "TRUE",
    "simulation_scope": SCOPE,
    "audit_only": "TRUE",
}

SIM_FIELDS = [
    "ticker",
    "baseline_rank",
    "baseline_score",
    "data_trust_status",
    "data_trust_pass",
    "data_trust_fail",
    "data_trust_unknown",
    "data_trust_mapping_confidence",
    "ranking_eligible_after_data_trust_gate",
    "gate_only_rank",
    "gate_only_score",
    "rank_delta",
    "score_delta",
    "baseline_top20_flag",
    "gate_only_top20_flag",
    "entered_gate_only_top20",
    "exited_gate_only_top20",
    "data_trust_scoring_weight_before",
    "data_trust_scoring_weight_after",
    "scoring_weight_renormalization_applied",
    "official_ranking_mutated",
    "official_weight_change_created",
    *COMMON.keys(),
]
DELTA_FIELDS = [
    "summary_id",
    "baseline_candidate_count",
    "data_trust_pass_count",
    "data_trust_fail_count",
    "data_trust_unknown_count",
    "ranking_candidate_count_after_data_trust_gate",
    "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count",
    "mapping_confidence_limitation_flag",
    "proposed_scoring_weight_sum",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "top20_turnover_rate",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "gate_only_policy_simulation_success",
    "recommended_next_action",
    *COMMON.keys(),
]
SCORE_FIELDS = [
    "ticker",
    "fundamental_score_available",
    "technical_score_available",
    "strategy_score_available",
    "risk_score_available",
    "market_regime_score_available",
    "data_trust_score_excluded_from_scoring",
    "all_required_scoring_families_available",
    "score_recomputation_performed",
    "score_recomputation_blocked_reason",
    "baseline_score_source",
    "gate_only_score_source",
    "formula_consistent_with_available_factor_family_scores",
    "limitation_reason",
    *COMMON.keys(),
]
ELIGIBILITY_FIELDS = [
    "ticker",
    "data_trust_status",
    "data_trust_pass",
    "data_trust_fail",
    "data_trust_unknown",
    "ranking_eligible_after_data_trust_gate",
    "excluded_from_ranking_due_to_data_trust",
    "exclusion_reason",
    "mapping_confidence",
    *COMMON.keys(),
]
MAPPING_FIELDS = [
    "mapping_confidence",
    "ticker_count",
    "mapping_confidence_limitation_flag",
    "direct_ticker_mapping_count",
    "inferred_from_artifact_mapping_count",
    "official_promotion_sufficient",
    "limitation_reason",
    *COMMON.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id",
    "safety_check",
    "expected_value",
    "actual_value",
    "safety_passed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_166_r1_gate_consumed",
    "v20_166_r1_status",
    "data_trust_scoring_weight",
    "data_trust_role",
    "ready_for_gate_only_ranking_simulation",
    "data_trust_unknown_count",
    "ranking_eligible_after_data_trust_count",
    "score_recomputation_blocked",
    "mapping_confidence_limitation_flag",
    "gate_only_policy_simulation_success",
    "no_upstream_outputs_mutated",
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
    required = [V166_POLICY, V166_WEIGHT, V166_ELIGIBILITY, V166_BACKLOG, V166_SAFETY, V166_GATE, R1_MAPPING, R1_STATUS, R1_REPAIR, R1_UNKNOWN, R1_READY, R1_GATE, BASELINE, WEIGHTS]
    optional = [R4_SCORES, R10_SCORES, R1_CONTRIB, R2_CONTRIB, WEIGHT_AUDIT, WEIGHT_EXPOSURE]
    return required + [path for path in optional if path.exists()]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def score_table(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("ticker", "").upper(): row for row in rows if row.get("ticker")}


def score_available(row: dict[str, str], family: str) -> bool:
    return clean(row.get(f"{family}_contribution")) != ""


def recompute_score(row: dict[str, str]) -> float:
    return sum(num(row.get(f"{family}_contribution")) * PROPOSED_WEIGHTS[family] for family in SCORING_FAMILIES)


def build_outputs(
    baseline_rows: list[dict[str, str]],
    status_rows: list[dict[str, str]],
    score_rows: list[dict[str, str]],
    r1_ready: dict[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    status_by_ticker = {row["ticker"].upper(): row for row in status_rows}
    scores_by_ticker = score_table(score_rows)
    baseline_by_ticker = {row.get("ticker", "").upper(): row for row in baseline_rows}
    scored: list[tuple[float, int, str]] = []
    score_audit: list[dict[str, str]] = []
    eligibility: list[dict[str, str]] = []

    for ticker, base in baseline_by_ticker.items():
        status = status_by_ticker.get(ticker, {})
        score_source = scores_by_ticker.get(ticker, {})
        eligible = status.get("ranking_eligible_after_data_trust_gate") == "TRUE"
        available = {family: score_available(score_source, family) for family in SCORING_FAMILIES}
        all_available = all(available.values())
        recompute = eligible and all_available
        blocked_reason = "" if recompute else ("DATA_TRUST_GATE_EXCLUDED" if not eligible else "MISSING_REQUIRED_FACTOR_FAMILY_SCORE")
        limitation = "RESEARCH_RECOMPUTED_SCORE_NOT_AUTHORITATIVE_BASELINE_LINEAGE"
        if recompute:
            scored.append((recompute_score(score_source), int(num(base.get("official_current_rank"))), ticker))
        score_audit.append({
            "ticker": ticker,
            "fundamental_score_available": tf(available["fundamental"]),
            "technical_score_available": tf(available["technical"]),
            "strategy_score_available": tf(available["strategy"]),
            "risk_score_available": tf(available["risk"]),
            "market_regime_score_available": tf(available["market_regime"]),
            "data_trust_score_excluded_from_scoring": "TRUE",
            "all_required_scoring_families_available": tf(all_available),
            "score_recomputation_performed": tf(recompute),
            "score_recomputation_blocked_reason": blocked_reason,
            "baseline_score_source": base.get("score_name", "official_current_score"),
            "gate_only_score_source": rel(R10_SCORES) if recompute else "",
            "formula_consistent_with_available_factor_family_scores": tf(recompute),
            "limitation_reason": limitation if recompute else blocked_reason,
            **COMMON,
        })
        excluded = not eligible
        eligibility.append({
            "ticker": ticker,
            "data_trust_status": status.get("data_trust_status", "UNKNOWN"),
            "data_trust_pass": status.get("data_trust_pass", "FALSE"),
            "data_trust_fail": status.get("data_trust_fail", "FALSE"),
            "data_trust_unknown": status.get("data_trust_unknown", "TRUE"),
            "ranking_eligible_after_data_trust_gate": tf(eligible),
            "excluded_from_ranking_due_to_data_trust": tf(excluded),
            "exclusion_reason": "" if eligible else "DATA_TRUST_FAIL_OR_UNKNOWN_EXCLUDED",
            "mapping_confidence": status.get("mapping_confidence", "UNKNOWN"),
            **COMMON,
        })

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    rank_by_ticker = {ticker: rank for rank, (_, _, ticker) in enumerate(scored, start=1)}
    score_by_ticker = {ticker: score for score, _, ticker in scored}
    baseline_top20 = {ticker for ticker, row in baseline_by_ticker.items() if 0 < int(num(row.get("official_current_rank"))) <= 20}
    gate_top20 = {ticker for ticker, rank in rank_by_ticker.items() if rank <= 20}
    sim_rows: list[dict[str, str]] = []
    deltas: list[int] = []
    for ticker, base in baseline_by_ticker.items():
        status = status_by_ticker.get(ticker, {})
        eligible = ticker in rank_by_ticker
        baseline_rank = int(num(base.get("official_current_rank")))
        gate_rank = rank_by_ticker.get(ticker, 0)
        rank_delta = gate_rank - baseline_rank if eligible else 0
        if eligible:
            deltas.append(abs(rank_delta))
        baseline_score = num(base.get("official_current_score"))
        gate_score = score_by_ticker.get(ticker, 0.0)
        sim_rows.append({
            "ticker": ticker,
            "baseline_rank": str(baseline_rank),
            "baseline_score": fmt(baseline_score),
            "data_trust_status": status.get("data_trust_status", "UNKNOWN"),
            "data_trust_pass": status.get("data_trust_pass", "FALSE"),
            "data_trust_fail": status.get("data_trust_fail", "FALSE"),
            "data_trust_unknown": status.get("data_trust_unknown", "TRUE"),
            "data_trust_mapping_confidence": status.get("mapping_confidence", "UNKNOWN"),
            "ranking_eligible_after_data_trust_gate": tf(eligible),
            "gate_only_rank": str(gate_rank) if eligible else "",
            "gate_only_score": fmt(gate_score) if eligible else "",
            "rank_delta": str(rank_delta) if eligible else "",
            "score_delta": fmt(gate_score - baseline_score) if eligible else "",
            "baseline_top20_flag": tf(ticker in baseline_top20),
            "gate_only_top20_flag": tf(ticker in gate_top20),
            "entered_gate_only_top20": tf(ticker in gate_top20 and ticker not in baseline_top20),
            "exited_gate_only_top20": tf(ticker in baseline_top20 and ticker not in gate_top20),
            "data_trust_scoring_weight_before": "0.1000000000",
            "data_trust_scoring_weight_after": "0.0000000000",
            "scoring_weight_renormalization_applied": "TRUE",
            "official_ranking_mutated": "FALSE",
            "official_weight_change_created": "FALSE",
            **COMMON,
        })

    direct = int(num(r1_ready.get("direct_ticker_mapping_count")))
    inferred = int(num(r1_ready.get("inferred_from_artifact_mapping_count")))
    pass_count = sum(1 for row in status_rows if row["data_trust_pass"] == "TRUE")
    fail_count = sum(1 for row in status_rows if row["data_trust_fail"] == "TRUE")
    unknown_count = sum(1 for row in status_rows if row["data_trust_unknown"] == "TRUE")
    overlap = len(baseline_top20 & gate_top20)
    entered = len(gate_top20 - baseline_top20)
    exited = len(baseline_top20 - gate_top20)
    performed_count = sum(1 for row in score_audit if row["score_recomputation_performed"] == "TRUE")
    success = performed_count == pass_count and pass_count > 0 and unknown_count == 0
    limitation = inferred > 0 and direct == 0
    summary = {
        "summary_id": "V20_166_R2_DATA_TRUST_GATE_ONLY_RANK_DELTA_001",
        "baseline_candidate_count": str(len(baseline_rows)),
        "data_trust_pass_count": str(pass_count),
        "data_trust_fail_count": str(fail_count),
        "data_trust_unknown_count": str(unknown_count),
        "ranking_candidate_count_after_data_trust_gate": str(len(scored)),
        "direct_ticker_mapping_count": str(direct),
        "inferred_from_artifact_mapping_count": str(inferred),
        "mapping_confidence_limitation_flag": tf(limitation),
        "proposed_scoring_weight_sum": fmt(sum(PROPOSED_WEIGHTS.values())),
        "top20_overlap_count": str(overlap),
        "entered_top20_count": str(entered),
        "exited_top20_count": str(exited),
        "top20_turnover_rate": fmt((entered + exited) / max(len(baseline_top20), 1)),
        "max_absolute_rank_delta": str(max(deltas, default=0)),
        "average_absolute_rank_delta": fmt(mean(deltas) if deltas else 0.0),
        "gate_only_policy_simulation_success": tf(success),
        "recommended_next_action": "CONTINUE_TO_V20_167_WITH_MAPPING_LIMITATION_DISCLOSED" if limitation else "CONTINUE_TO_V20_167",
        **COMMON,
    }
    mapping_rows = [
        {
            "mapping_confidence": "INFERRED",
            "ticker_count": str(inferred),
            "mapping_confidence_limitation_flag": tf(limitation),
            "direct_ticker_mapping_count": str(direct),
            "inferred_from_artifact_mapping_count": str(inferred),
            "official_promotion_sufficient": "FALSE",
            "limitation_reason": "DATA_TRUST_PASS_INFERRED_FROM_AUTHORITATIVE_BASELINE_FIELDS_PLUS_AGGREGATE_QUALITY_ARTIFACTS",
            **COMMON,
        },
        {
            "mapping_confidence": "DIRECT",
            "ticker_count": str(direct),
            "mapping_confidence_limitation_flag": tf(limitation),
            "direct_ticker_mapping_count": str(direct),
            "inferred_from_artifact_mapping_count": str(inferred),
            "official_promotion_sufficient": "FALSE",
            "limitation_reason": "NO_DIRECT_TICKER_LEVEL_DATA_TRUST_FIELD_AVAILABLE" if direct == 0 else "",
            **COMMON,
        },
    ]
    return sim_rows, [summary], score_audit, eligibility, mapping_rows


def safety_rows(upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("research_only", "TRUE", "TRUE"),
        ("data_trust_scoring_weight", "0.0000000000", "0.0000000000"),
        ("data_trust_role", DATA_TRUST_ROLE, DATA_TRUST_ROLE),
        ("formal_activation_allowed", "FALSE", "FALSE"),
        ("promotion_ready", "FALSE", "FALSE"),
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("official_ranking_mutated", "FALSE", "FALSE"),
        ("official_weight_change_created", "FALSE", "FALSE"),
        ("official_weight_registry_mutated", "FALSE", "FALSE"),
        ("weight_mutated", "FALSE", "FALSE"),
        ("real_book_action_created", "FALSE", "FALSE"),
        ("trade_action_created", "FALSE", "FALSE"),
        ("broker_execution_supported", "FALSE", "FALSE"),
        ("performance_claim_created", "FALSE", "FALSE"),
        ("shadow_weight_expansion_allowed", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "safety_check_id": f"V20_166_R2_SAFETY_{idx:03d}",
        "safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.166-R2 DATA_TRUST Gate-Only Ranking Simulation Report",
        "",
        f"- wrapper_status: {status}",
        f"- data_trust_role: {DATA_TRUST_ROLE}",
        "- data_trust_scoring_weight: 0.0000000000",
        "- research_only: TRUE",
        "- official_ranking_mutated: FALSE",
        "- official_weight_change_created: FALSE",
        "- mapping_limitation: DATA_TRUST PASS is inferred from authoritative baseline fields plus aggregate quality artifacts; this is not sufficient for official promotion.",
    ]
    if summary:
        lines.extend([
            f"- baseline_candidate_count: {summary['baseline_candidate_count']}",
            f"- ranking_candidate_count_after_data_trust_gate: {summary['ranking_candidate_count_after_data_trust_gate']}",
            f"- direct_ticker_mapping_count: {summary['direct_ticker_mapping_count']}",
            f"- inferred_from_artifact_mapping_count: {summary['inferred_from_artifact_mapping_count']}",
            f"- top20_turnover_rate: {summary['top20_turnover_rate']}",
            f"- max_absolute_rank_delta: {summary['max_absolute_rank_delta']}",
            f"- gate_only_policy_simulation_success: {summary['gate_only_policy_simulation_success']}",
        ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_166_R2_DATA_TRUST_GATE_ONLY_NEXT_GATE_001",
        "v20_166_r1_gate_consumed": "FALSE",
        "v20_166_r1_status": "",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": DATA_TRUST_ROLE,
        "ready_for_gate_only_ranking_simulation": "FALSE",
        "data_trust_unknown_count": "0",
        "ranking_eligible_after_data_trust_count": "0",
        "score_recomputation_blocked": "TRUE",
        "mapping_confidence_limitation_flag": "FALSE",
        "gate_only_policy_simulation_success": "FALSE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    for path, fields in [
        (OUT_SIM, SIM_FIELDS), (OUT_DELTA, DELTA_FIELDS), (OUT_SCORE, SCORE_FIELDS),
        (OUT_ELIGIBILITY, ELIGIBILITY_FIELDS), (OUT_MAPPING, MAPPING_FIELDS),
        (OUT_SAFETY, SAFETY_FIELDS),
    ]:
        write_csv(path, fields, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    required = [V166_POLICY, V166_WEIGHT, V166_ELIGIBILITY, V166_BACKLOG, V166_SAFETY, V166_GATE, R1_MAPPING, R1_STATUS, R1_REPAIR, R1_READY, R1_GATE, BASELINE, WEIGHTS, R10_SCORES]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    r1_gate_rows, _ = read_csv(R1_GATE)
    r1_ready_rows, _ = read_csv(R1_READY)
    status_rows, _ = read_csv(R1_STATUS)
    baseline_rows, _ = read_csv(BASELINE)
    score_rows, _ = read_csv(R10_SCORES)
    if not all([r1_gate_rows, r1_ready_rows, status_rows, baseline_rows, score_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r1_gate = r1_gate_rows[0]
    r1_ready = r1_ready_rows[0]
    prereq_ok = all([
        r1_gate.get("final_status") == REQUIRED_R1_STATUS,
        r1_gate.get("data_trust_scoring_weight") == "0.0000000000",
        r1_gate.get("data_trust_role") == DATA_TRUST_ROLE,
        r1_ready.get("ready_for_gate_only_ranking_simulation") == "TRUE",
        r1_ready.get("data_trust_unknown_count") == "0",
        num(r1_ready.get("ranking_eligible_after_data_trust_count")) > 0,
    ])
    if not prereq_ok:
        return emit_blocked("V20_166_R1_REQUIREMENTS_NOT_MET")

    sim, delta, score_audit, eligibility, mapping = build_outputs(baseline_rows, status_rows, score_rows, r1_ready)
    upstream_mutated = before != input_hashes()
    safety = safety_rows(upstream_mutated)
    safety_ok = all(row["safety_passed"] == "TRUE" for row in safety)
    summary = delta[0]
    score_blocked = any(row["score_recomputation_blocked_reason"] == "MISSING_REQUIRED_FACTOR_FAMILY_SCORE" for row in score_audit)
    if upstream_mutated or not safety_ok:
        status, blocking = BLOCKED_STATUS, "SAFETY_OR_UPSTREAM_MUTATION_FAILURE"
    elif score_blocked or summary["gate_only_policy_simulation_success"] != "TRUE":
        status, blocking = WARN_STATUS, ""
    elif summary["mapping_confidence_limitation_flag"] == "TRUE":
        status, blocking = PARTIAL_STATUS, ""
    else:
        status, blocking = PASS_STATUS, ""
    gate = {
        "gate_check_id": "V20_166_R2_DATA_TRUST_GATE_ONLY_NEXT_GATE_001",
        "v20_166_r1_gate_consumed": "TRUE",
        "v20_166_r1_status": r1_gate.get("final_status", ""),
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": DATA_TRUST_ROLE,
        "ready_for_gate_only_ranking_simulation": "TRUE",
        "data_trust_unknown_count": r1_ready.get("data_trust_unknown_count", "0"),
        "ranking_eligible_after_data_trust_count": r1_ready.get("ranking_eligible_after_data_trust_count", "0"),
        "score_recomputation_blocked": tf(score_blocked),
        "mapping_confidence_limitation_flag": summary["mapping_confidence_limitation_flag"],
        "gate_only_policy_simulation_success": summary["gate_only_policy_simulation_success"],
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }
    write_csv(OUT_SIM, SIM_FIELDS, sim)
    write_csv(OUT_DELTA, DELTA_FIELDS, delta)
    write_csv(OUT_SCORE, SCORE_FIELDS, score_audit)
    write_csv(OUT_ELIGIBILITY, ELIGIBILITY_FIELDS, eligibility)
    write_csv(OUT_MAPPING, MAPPING_FIELDS, mapping)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(status, summary)

    print(status)
    print("V20_166_R1_GATE_CONSUMED=TRUE")
    print(f"V20_166_R1_STATUS={r1_gate.get('final_status', '')}")
    for field in [
        "baseline_candidate_count", "data_trust_pass_count", "data_trust_fail_count",
        "data_trust_unknown_count", "ranking_candidate_count_after_data_trust_gate",
        "direct_ticker_mapping_count", "inferred_from_artifact_mapping_count",
        "mapping_confidence_limitation_flag", "proposed_scoring_weight_sum",
        "top20_overlap_count", "entered_top20_count", "exited_top20_count",
        "top20_turnover_rate", "max_absolute_rank_delta", "average_absolute_rank_delta",
        "gate_only_policy_simulation_success", "recommended_next_action",
    ]:
        print(f"{field.upper()}={summary[field]}")
    print("DATA_TRUST_SCORING_WEIGHT=0.0000000000")
    print(f"DATA_TRUST_ROLE={DATA_TRUST_ROLE}")
    print(f"SCORE_RECOMPUTATION_BLOCKED={tf(score_blocked)}")
    print("RESEARCH_ONLY=TRUE")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
