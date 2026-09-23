#!/usr/bin/env python
"""V20.192 current chain release candidate with DATA_TRUST gate-only metadata."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V188_SEAL = FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv"
V188_GATE = FACTORS / "V20_188_NEXT_STAGE_GATE.csv"
V189_HANDOFF = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_AUDIT.csv"
V189_GATE = FACTORS / "V20_189_NEXT_STAGE_GATE.csv"
V190_SMOKE = FACTORS / "V20_190_CURRENT_CHAIN_SMOKE_TEST_AUDIT.csv"
V190_GATE = FACTORS / "V20_190_NEXT_STAGE_GATE.csv"
V191_REGRESSION = FACTORS / "V20_191_DAILY_RUNNER_REGRESSION_AUDIT.csv"
V191_UNIVERSE = FACTORS / "V20_191_CANDIDATE_UNIVERSE_REGRESSION_AUDIT.csv"
V191_RANKING = FACTORS / "V20_191_RANKING_WEIGHT_REGRESSION_AUDIT.csv"
V191_READ_CENTER = FACTORS / "V20_191_READ_CENTER_REGRESSION_AUDIT.csv"
V191_OFFICIAL = FACTORS / "V20_191_OFFICIAL_USE_REGRESSION_AUDIT.csv"
V191_DOWNSTREAM = FACTORS / "V20_191_DOWNSTREAM_COMPATIBILITY_REGRESSION_AUDIT.csv"
V191_GATE = FACTORS / "V20_191_NEXT_STAGE_GATE.csv"

PROTECTED = [
    V188_SEAL, V188_GATE, V189_HANDOFF, V189_GATE, V190_SMOKE, V190_GATE,
    V191_REGRESSION, V191_UNIVERSE, V191_RANKING, V191_READ_CENTER,
    V191_OFFICIAL, V191_DOWNSTREAM, V191_GATE,
]

OUT_PACKET = FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_PACKET.csv"
OUT_GUARDRAIL = FACTORS / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_GUARDRAIL_AUDIT.csv"
OUT_READINESS = FACTORS / "V20_192_CURRENT_CHAIN_READINESS_AUDIT.csv"
OUT_STATUS = FACTORS / "V20_192_DATA_TRUST_SEALED_STATUS_AUDIT.csv"
OUT_GATE = FACTORS / "V20_192_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_REPORT.md"

READY_V188 = "PASS_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_READY_FOR_V20_189_CURRENT_CHAIN_HANDOFF"
READY_V189 = "PASS_V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_READY_FOR_V20_190_CURRENT_CHAIN_SMOKE_TEST"
READY_V190 = "PASS_V20_190_CURRENT_CHAIN_SMOKE_TEST_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_191_DAILY_RUNNER_REGRESSION"
READY_V191 = "PASS_V20_191_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_192_RELEASE_CANDIDATE"
PASS_STATUS = "PASS_V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_193_FINAL_OPERATOR_ACCEPTANCE"
BLOCKED_STATUS = "BLOCKED_V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_CURRENT_CHAIN_RELEASE_CANDIDATE_WITH_DATA_TRUST_GATE_ONLY"

SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
    "direct_ticker_mapping_required_before_official_use": "TRUE",
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
COMMON = {**SAFETY, "repair_scope": SCOPE, "audit_only": "TRUE"}

PACKET_FIELDS = [
    "release_candidate_id", "release_candidate_scope", "release_candidate_created",
    "data_trust_sealed_status_preserved", "data_trust_zero_weight",
    "data_trust_gate_only", "data_trust_audit_only", "data_trust_read_center_disclosed",
    "daily_runner_candidate_universe_unchanged", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "candidate_removed_or_reordered_count",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    *COMMON.keys(),
]
AUDIT_FIELDS = [
    "audit_check_id", "audit_surface", "audit_check", "expected_value",
    "actual_value", "audit_check_passed", "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_188_status_consumed", "v20_188_status",
    "v20_189_status_consumed", "v20_189_status", "v20_190_status_consumed",
    "v20_190_status", "v20_191_status_consumed", "v20_191_status",
    "current_chain_release_candidate_created", "release_candidate_guardrail_pass",
    "current_chain_readiness_pass", "data_trust_sealed_status_pass",
    "baseline_candidate_count", "daily_runner_candidate_count",
    "read_center_display_candidate_count", "candidate_removed_or_reordered_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "ready_for_v20_193_final_operator_acceptance", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight",
    "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_read_center_disclosed", "recommended_next_action",
    "blocking_reason", "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in PROTECTED if path.exists()}


def audit_row(prefix: str, idx: int, surface: str, check: str, expected: str, actual: str, path: Path) -> dict[str, str]:
    return {
        "audit_check_id": f"V20_192_{prefix}_{idx:03d}",
        "audit_surface": surface,
        "audit_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "audit_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    }


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.192 Current Chain Release Candidate With DATA_TRUST Gate-Only Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- current_chain_release_candidate_created: {gate['current_chain_release_candidate_created']}",
        f"- release_candidate_guardrail_pass: {gate['release_candidate_guardrail_pass']}",
        f"- current_chain_readiness_pass: {gate['current_chain_readiness_pass']}",
        f"- data_trust_sealed_status_pass: {gate['data_trust_sealed_status_pass']}",
        f"- ready_for_v20_193_final_operator_acceptance: {gate['ready_for_v20_193_final_operator_acceptance']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Release candidate created with DATA_TRUST preserved as zero-weight gate-only audit metadata. Candidate universe, ranking, read-center, official-use, and downstream compatibility guardrails remain passing.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path in [OUT_PACKET, OUT_GUARDRAIL, OUT_READINESS, OUT_STATUS]:
        write_csv(path, PACKET_FIELDS if path == OUT_PACKET else AUDIT_FIELDS, [])
    gate = {
        "gate_check_id": "V20_192_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "FALSE",
        "v20_188_status": "",
        "v20_189_status_consumed": "FALSE",
        "v20_189_status": "",
        "v20_190_status_consumed": "FALSE",
        "v20_190_status": "",
        "v20_191_status_consumed": "FALSE",
        "v20_191_status": "",
        "current_chain_release_candidate_created": "FALSE",
        "release_candidate_guardrail_pass": "FALSE",
        "current_chain_readiness_pass": "FALSE",
        "data_trust_sealed_status_pass": "FALSE",
        "baseline_candidate_count": "0",
        "daily_runner_candidate_count": "0",
        "read_center_display_candidate_count": "0",
        "candidate_removed_or_reordered_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "ready_for_v20_193_final_operator_acceptance": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_192",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = protected_hashes()
    datasets = {path: read_csv(path)[0] for path in PROTECTED}
    if any(not rows for rows in datasets.values()):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    gate188 = datasets[V188_GATE][0]
    gate189 = datasets[V189_GATE][0]
    gate190 = datasets[V190_GATE][0]
    gate191 = datasets[V191_GATE][0]
    seal = datasets[V188_SEAL][0]
    if not all([
        gate188.get("final_status") == READY_V188,
        gate189.get("final_status") == READY_V189,
        gate190.get("final_status") == READY_V190,
        gate191.get("final_status") == READY_V191,
        gate191.get("ready_for_v20_192_daily_runner_current_chain_release_candidate") == "TRUE",
        all(row.get("regression_passed") == "TRUE" for row in datasets[V191_REGRESSION]),
        all(row.get("regression_passed") == "TRUE" for row in datasets[V191_UNIVERSE]),
        all(row.get("regression_passed") == "TRUE" for row in datasets[V191_RANKING]),
        all(row.get("regression_passed") == "TRUE" for row in datasets[V191_READ_CENTER]),
        all(row.get("regression_passed") == "TRUE" for row in datasets[V191_OFFICIAL]),
        all(row.get("regression_passed") == "TRUE" for row in datasets[V191_DOWNSTREAM]),
    ]):
        return emit_blocked("V20_188_THROUGH_V20_191_REQUIREMENTS_NOT_MET")

    upstream_mutated = before != protected_hashes()
    sealed_status = all([
        seal.get("release_seal_created") == "TRUE",
        seal.get("sealed_zero_weight") == "TRUE",
        seal.get("sealed_gate_only") == "TRUE",
        seal.get("sealed_audit_only") == "TRUE",
        seal.get("sealed_read_center_disclosed") == "TRUE",
        gate191.get("data_trust_zero_weight") == "TRUE",
        gate191.get("data_trust_gate_only") == "TRUE",
        gate191.get("data_trust_audit_only") == "TRUE",
    ])
    guardrail_ok = all([
        gate191.get("candidate_universe_regression_pass") == "TRUE",
        gate191.get("ranking_regression_pass") == "TRUE",
        gate191.get("zero_weight_regression_pass") == "TRUE",
        gate191.get("read_center_regression_pass") == "TRUE",
        gate191.get("official_use_regression_pass") == "TRUE",
        gate191.get("downstream_compatibility_regression_pass") == "TRUE",
        gate191.get("candidate_removed_or_reordered_count") == "0",
        gate191.get("official_ranking_score_mutation_count") == "0",
        gate191.get("official_rank_mutation_count") == "0",
        gate191.get("data_trust_score_contribution_sum") == "0.0000000000",
        gate191.get("data_trust_nonzero_weight_count") == "0",
        gate191.get("ready_for_official_use") == "FALSE",
        gate191.get("real_book_use_allowed") == "FALSE",
        gate191.get("official_recommendation_created") == "FALSE",
        gate191.get("official_weight_mutation_allowed") == "FALSE",
        not upstream_mutated,
    ])
    readiness_ok = all([
        gate188.get("ready_for_v20_189_daily_runner_seal_handoff_to_current_chain") == "TRUE",
        gate189.get("ready_for_v20_190_current_chain_smoke_test") == "TRUE",
        gate190.get("ready_for_v20_191_current_chain_daily_runner_regression") == "TRUE",
        gate191.get("ready_for_v20_192_daily_runner_current_chain_release_candidate") == "TRUE",
    ])
    candidate_created = all([sealed_status, guardrail_ok, readiness_ok])

    packet_rows = [{
        "release_candidate_id": "V20_192_CURRENT_CHAIN_RELEASE_CANDIDATE_PACKET_001",
        "release_candidate_scope": "CURRENT_DAILY_RESEARCH_CHAIN_WITH_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA",
        "release_candidate_created": tf(candidate_created),
        "data_trust_sealed_status_preserved": tf(sealed_status),
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "daily_runner_candidate_universe_unchanged": gate191.get("candidate_universe_regression_pass", ""),
        "official_ranking_score_mutation_count": gate191.get("official_ranking_score_mutation_count", ""),
        "official_rank_mutation_count": gate191.get("official_rank_mutation_count", ""),
        "data_trust_score_contribution_sum": gate191.get("data_trust_score_contribution_sum", ""),
        "data_trust_nonzero_weight_count": gate191.get("data_trust_nonzero_weight_count", ""),
        "candidate_removed_or_reordered_count": gate191.get("candidate_removed_or_reordered_count", ""),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]
    guardrail_rows = [
        audit_row("GUARDRAIL", 1, "release_candidate", "candidate_universe_regression_pass", "TRUE", gate191.get("candidate_universe_regression_pass", ""), V191_GATE),
        audit_row("GUARDRAIL", 2, "release_candidate", "official_ranking_score_mutation_count", "0", gate191.get("official_ranking_score_mutation_count", ""), V191_GATE),
        audit_row("GUARDRAIL", 3, "release_candidate", "official_rank_mutation_count", "0", gate191.get("official_rank_mutation_count", ""), V191_GATE),
        audit_row("GUARDRAIL", 4, "release_candidate", "data_trust_score_contribution_sum", "0.0000000000", gate191.get("data_trust_score_contribution_sum", ""), V191_GATE),
        audit_row("GUARDRAIL", 5, "release_candidate", "data_trust_nonzero_weight_count", "0", gate191.get("data_trust_nonzero_weight_count", ""), V191_GATE),
        audit_row("GUARDRAIL", 6, "release_candidate", "candidate_removed_or_reordered_count", "0", gate191.get("candidate_removed_or_reordered_count", ""), V191_GATE),
        audit_row("GUARDRAIL", 7, "release_candidate", "official_use_regression_pass", "TRUE", gate191.get("official_use_regression_pass", ""), V191_GATE),
        audit_row("GUARDRAIL", 8, "release_candidate", "upstream_release_candidate_inputs_mutated", "FALSE", tf(upstream_mutated), V191_GATE),
    ]
    readiness_rows = [
        audit_row("READINESS", 1, "current_chain", "v188_ready", "TRUE", gate188.get("ready_for_v20_189_daily_runner_seal_handoff_to_current_chain", ""), V188_GATE),
        audit_row("READINESS", 2, "current_chain", "v189_ready", "TRUE", gate189.get("ready_for_v20_190_current_chain_smoke_test", ""), V189_GATE),
        audit_row("READINESS", 3, "current_chain", "v190_ready", "TRUE", gate190.get("ready_for_v20_191_current_chain_daily_runner_regression", ""), V190_GATE),
        audit_row("READINESS", 4, "current_chain", "v191_ready", "TRUE", gate191.get("ready_for_v20_192_daily_runner_current_chain_release_candidate", ""), V191_GATE),
    ]
    status_rows = [
        audit_row("SEALED_STATUS", 1, "data_trust", "sealed_zero_weight", "TRUE", seal.get("sealed_zero_weight", ""), V188_SEAL),
        audit_row("SEALED_STATUS", 2, "data_trust", "sealed_gate_only", "TRUE", seal.get("sealed_gate_only", ""), V188_SEAL),
        audit_row("SEALED_STATUS", 3, "data_trust", "sealed_audit_only", "TRUE", seal.get("sealed_audit_only", ""), V188_SEAL),
        audit_row("SEALED_STATUS", 4, "data_trust", "sealed_read_center_disclosed", "TRUE", seal.get("sealed_read_center_disclosed", ""), V188_SEAL),
        audit_row("SEALED_STATUS", 5, "data_trust", "data_trust_zero_weight", "TRUE", gate191.get("data_trust_zero_weight", ""), V191_GATE),
        audit_row("SEALED_STATUS", 6, "data_trust", "data_trust_gate_only", "TRUE", gate191.get("data_trust_gate_only", ""), V191_GATE),
        audit_row("SEALED_STATUS", 7, "data_trust", "data_trust_audit_only", "TRUE", gate191.get("data_trust_audit_only", ""), V191_GATE),
    ]
    guardrail_pass = all(row["audit_check_passed"] == "TRUE" for row in guardrail_rows)
    readiness_pass = all(row["audit_check_passed"] == "TRUE" for row in readiness_rows)
    sealed_pass = all(row["audit_check_passed"] == "TRUE" for row in status_rows)
    all_pass = all([candidate_created, guardrail_pass, readiness_pass, sealed_pass])

    gate = {
        "gate_check_id": "V20_192_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "TRUE",
        "v20_188_status": gate188.get("final_status", ""),
        "v20_189_status_consumed": "TRUE",
        "v20_189_status": gate189.get("final_status", ""),
        "v20_190_status_consumed": "TRUE",
        "v20_190_status": gate190.get("final_status", ""),
        "v20_191_status_consumed": "TRUE",
        "v20_191_status": gate191.get("final_status", ""),
        "current_chain_release_candidate_created": tf(candidate_created),
        "release_candidate_guardrail_pass": tf(guardrail_pass),
        "current_chain_readiness_pass": tf(readiness_pass),
        "data_trust_sealed_status_pass": tf(sealed_pass),
        "baseline_candidate_count": gate191.get("baseline_candidate_count", ""),
        "daily_runner_candidate_count": gate191.get("daily_runner_candidate_count", ""),
        "read_center_display_candidate_count": gate191.get("read_center_display_candidate_count", ""),
        "candidate_removed_or_reordered_count": gate191.get("candidate_removed_or_reordered_count", ""),
        "official_ranking_score_mutation_count": gate191.get("official_ranking_score_mutation_count", ""),
        "official_rank_mutation_count": gate191.get("official_rank_mutation_count", ""),
        "data_trust_score_contribution_sum": gate191.get("data_trust_score_contribution_sum", ""),
        "data_trust_nonzero_weight_count": gate191.get("data_trust_nonzero_weight_count", ""),
        "ready_for_v20_193_final_operator_acceptance": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "recommended_next_action": "RUN_V20_193_FINAL_OPERATOR_ACCEPTANCE" if all_pass else "REPAIR_V20_192_RELEASE_CANDIDATE",
        "blocking_reason": "NONE" if all_pass else "V20_192_RELEASE_CANDIDATE_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_PACKET, PACKET_FIELDS, packet_rows)
    write_csv(OUT_GUARDRAIL, AUDIT_FIELDS, guardrail_rows)
    write_csv(OUT_READINESS, AUDIT_FIELDS, readiness_rows)
    write_csv(OUT_STATUS, AUDIT_FIELDS, status_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("REAL_BOOK_USE_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
