#!/usr/bin/env python
"""V20.151 forward observation accumulation repair.

Builds a research-only forward observation accumulation layer from existing
daily runner/ranking/observation artifacts. It records eligibility and pending
outcomes without fabricating tickers, forward outcomes, or benchmark outcomes.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
STAGING = OUTPUTS / "staging"
OBSERVATIONS = OUTPUTS / "observations"
READ_CENTER = OUTPUTS / "read_center"

IN_PACKET = STAGING / "V20_150_STAGING_REVIEW_PACKET.csv"
IN_GATE = STAGING / "V20_150_STAGING_REVIEW_GATE.csv"
IN_BOUNDARY = STAGING / "V20_150_PROMOTION_BOUNDARY_AUDIT.csv"
IN_SAFETY = STAGING / "V20_150_SAFETY_CONSTRAINT_AUDIT.csv"

OUT_ACCUMULATION = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ACCUMULATION.csv"
OUT_GATE = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_GATE.csv"
OUT_SOURCE_AUDIT = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT.csv"
OUT_ELIGIBILITY = OBSERVATIONS / "V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT.csv"
REPORT = READ_CENTER / "V20_151_FORWARD_OBSERVATION_ACCUMULATION_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V150_REQUIRED_STATUS = "PASS_V20_150_STAGING_REVIEW_PACKET_READY_FOR_V20_151"
PASS_STATUS = "PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_READY_FOR_V20_152"
PARTIAL_STATUS = "PARTIAL_PASS_V20_151_FORWARD_OBSERVATION_ACCUMULATION_WITH_PENDING_OUTCOMES_READY_FOR_V20_152"
WARN_STATUS = "WARN_V20_151_NO_ELIGIBLE_FORWARD_OBSERVATIONS_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_151_FORWARD_OBSERVATION_ACCUMULATION"

TARGET_STAGE_PREFIXES = ("V20_55_", "V20_70_", "V20_71_", "V20_76_", "V20_77_", "V20_83_", "V20_96_", "V20_97_")
REQUIRED_INPUTS = [IN_PACKET, IN_GATE, IN_BOUNDARY, IN_SAFETY]
UPSTREAM_HASH_INPUTS = sorted(
    [path for path in CONSOLIDATION.glob("V20_*") if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 150))]
    + [path for path in STAGING.glob("V20_150_*") if path.is_file()]
)
SAFETY_FIELDS = [
    "formal_activation_allowed",
    "promotion_ready",
    "official_recommendation_created",
    "official_ranking_mutated",
    "weight_mutated",
    "real_book_action_created",
    "trade_action_created",
    "broker_execution_supported",
    "performance_claim_created",
]
COMMON = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "forward_observation_accumulation_only": "TRUE",
    "audit_only": "TRUE",
    "simulation_only": "TRUE",
}

ACCUMULATION_FIELDS = ["forward_observation_accumulation_id", "selected_repair_scenario_id", "source_run_id", "source_stage", "source_artifact_path", "run_timestamp_utc", "observation_date", "observation_status", "outcome_status", "forward_outcome_fabricated", "benchmark_outcome_fabricated", "ticker_rows_fabricated", "dynamic_weight_research_eligible", "eligibility_status", "exclusion_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "selected_repair_scenario_id", "v20_150_gate_consumed", "v20_151_allowed_after_v20_150", "staging_review_allowed", "formal_activation_allowed", "promotion_ready", "safety_constraint_audit_passed", "source_audit_row_count", "discovered_run_count", "eligible_forward_observation_count", "ineligible_forward_observation_count", "outcome_pending_count", "no_ticker_rows_fabricated", "no_forward_outcomes_fabricated", "no_benchmark_outcomes_fabricated", "no_upstream_outputs_mutated", "v20_152_forward_observation_review_allowed", "next_recommended_action", "blocking_reason", "forward_observation_accumulation_status", *COMMON.keys()]
SOURCE_FIELDS = ["forward_observation_source_audit_id", "selected_repair_scenario_id", "source_stage", "source_artifact_path", "source_exists", "source_non_empty", "source_row_count", "source_sha256", "source_role", "discovered_run_count", "source_usable_for_forward_observation", "source_exclusion_reason", *COMMON.keys()]
ELIGIBILITY_FIELDS = ["forward_observation_eligibility_audit_id", "selected_repair_scenario_id", "source_run_id", "source_stage", "source_artifact_path", "run_timestamp_utc", "observation_date", "eligible_for_forward_observation", "dynamic_weight_research_eligible", "outcome_status", "exclusion_reason", "source_evidence_sufficient", "research_only", "staging_review_only", *SAFETY_FIELDS]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: str | None) -> bool:
    return (value or "").strip().upper() == "TRUE"


def clean(value: str | None) -> str:
    return (value or "").strip()


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[str, str]:
    return {display_path(path): digest(path) for path in UPSTREAM_HASH_INPUTS if path.exists()}


def stage_for(path: Path) -> str:
    name = path.name
    for prefix in TARGET_STAGE_PREFIXES:
        if name.startswith(prefix):
            return prefix.rstrip("_").replace("_", ".")
    return "UNKNOWN"


def role_for(path: Path) -> str:
    name = path.name.upper()
    if "OBSERVATION" in name:
        return "OBSERVATION_SOURCE"
    if "DAILY_ONE_CLICK" in name or "DAILY" in name:
        return "DAILY_RUNNER_SOURCE"
    if "RANKING" in name:
        return "RANKING_REFERENCE_SOURCE"
    if "BUY_ZONE" in name:
        return "BUY_ZONE_REFERENCE_SOURCE"
    return "REFERENCE_SOURCE"


def discover_sources() -> list[Path]:
    return sorted(path for path in OUTPUTS.rglob("*") if path.is_file() and any(path.name.startswith(prefix) for prefix in TARGET_STAGE_PREFIXES))


def row_count(path: Path) -> int:
    if path.suffix.lower() != ".csv":
        return 0
    try:
        return len(read_csv(path))
    except Exception:
        return 0


def run_id_from(row: dict[str, str]) -> str:
    for field in ["run_id", "source_run_id", "observation_run_id"]:
        if clean(row.get(field)):
            return clean(row.get(field))
    return ""


def timestamp_from(row: dict[str, str]) -> str:
    for field in ["run_timestamp_utc", "run_timestamp", "source_timestamp_utc", "observation_timestamp", "ranking_timestamp_utc", "modified_at_utc"]:
        if clean(row.get(field)):
            return clean(row.get(field))
    return ""


def observation_date_from(row: dict[str, str]) -> str:
    for field in ["observation_date", "latest_price_date", "run_timestamp_utc", "run_timestamp", "source_timestamp_utc"]:
        value = clean(row.get(field))
        if value:
            return value[:10]
    return ""


def row_safety_ok(row: dict[str, str]) -> bool:
    disallowed = [
        "official_recommendation_created",
        "official_weight_mutated",
        "weight_mutated",
        "trade_action_created",
        "promotion_allowed",
        "promotion_ready",
    ]
    return not any(truthy(row.get(field)) for field in disallowed)


def build_source_audit(selected_id: str, sources: list[Path]) -> list[dict[str, str]]:
    rows = []
    for i, path in enumerate(sources, start=1):
        is_csv = path.suffix.lower() == ".csv"
        count = row_count(path)
        role = role_for(path)
        usable = is_csv and count > 0 and role in {"OBSERVATION_SOURCE", "DAILY_RUNNER_SOURCE"}
        exclusion = "" if usable else ("NON_CSV_REFERENCE_ONLY" if not is_csv else "REFERENCE_SOURCE_NOT_DAILY_OBSERVATION")
        rows.append({
            "forward_observation_source_audit_id": f"V20_151_FORWARD_OBSERVATION_SOURCE_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_stage": stage_for(path),
            "source_artifact_path": display_path(path),
            "source_exists": "TRUE",
            "source_non_empty": tf(path.stat().st_size > 0),
            "source_row_count": str(count),
            "source_sha256": digest(path),
            "source_role": role,
            "discovered_run_count": "0",
            "source_usable_for_forward_observation": tf(usable),
            "source_exclusion_reason": exclusion,
            **COMMON,
        })
    return rows


def collect_candidates(selected_id: str, sources: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    seen: set[str] = set()
    eligibility: list[dict[str, str]] = []
    accumulation: list[dict[str, str]] = []
    for path in sources:
        if path.suffix.lower() != ".csv":
            continue
        role = role_for(path)
        if role not in {"OBSERVATION_SOURCE", "DAILY_RUNNER_SOURCE"}:
            continue
        rows = read_csv(path)
        for row in rows:
            run_id = run_id_from(row)
            if not run_id:
                continue
            duplicate = run_id in seen
            if not duplicate:
                seen.add(run_id)
            source_evidence_sufficient = bool(timestamp_from(row)) and row_safety_ok(row)
            research_valid = truthy(row.get("research_observation_valid")) or truthy(row.get("observation_valid")) or truthy(row.get("research_only_daily_conclusion_ready"))
            eligible = (not duplicate) and source_evidence_sufficient and (research_valid or "V20_55_" in path.name)
            outcome_status = "OUTCOME_PENDING" if eligible else "NOT_APPLICABLE"
            exclusion_parts = []
            if duplicate:
                exclusion_parts.append("DUPLICATE_RUN_ID")
            if not source_evidence_sufficient:
                exclusion_parts.append("SOURCE_EVIDENCE_INSUFFICIENT")
            if not (research_valid or "V20_55_" in path.name):
                exclusion_parts.append("NOT_RESEARCH_OBSERVATION_RUN")
            exclusion = "|".join(exclusion_parts) if exclusion_parts else ""
            dynamic_eligible = eligible and truthy(row.get("eligible_for_v20_96_research_only")) and truthy(row.get("research_only"))
            base = {
                "selected_repair_scenario_id": selected_id,
                "source_run_id": run_id,
                "source_stage": stage_for(path),
                "source_artifact_path": display_path(path),
                "run_timestamp_utc": timestamp_from(row),
                "observation_date": observation_date_from(row),
                "eligible_for_forward_observation": tf(eligible),
                "dynamic_weight_research_eligible": tf(dynamic_eligible),
                "outcome_status": outcome_status,
                "exclusion_reason": exclusion,
                "source_evidence_sufficient": tf(source_evidence_sufficient),
                "research_only": "TRUE",
                "staging_review_only": "TRUE",
                **{field: "FALSE" for field in SAFETY_FIELDS},
            }
            eligibility.append({"forward_observation_eligibility_audit_id": f"V20_151_FORWARD_OBSERVATION_ELIGIBILITY_AUDIT_{len(eligibility)+1:03d}", **base})
            if eligible:
                accumulation.append({
                    "forward_observation_accumulation_id": f"V20_151_FORWARD_OBSERVATION_ACCUMULATION_{len(accumulation)+1:03d}",
                    "selected_repair_scenario_id": selected_id,
                    "source_run_id": run_id,
                    "source_stage": stage_for(path),
                    "source_artifact_path": display_path(path),
                    "run_timestamp_utc": timestamp_from(row),
                    "observation_date": observation_date_from(row),
                    "observation_status": "ELIGIBLE_RESEARCH_ONLY_FORWARD_OBSERVATION",
                    "outcome_status": outcome_status,
                    "forward_outcome_fabricated": "FALSE",
                    "benchmark_outcome_fabricated": "FALSE",
                    "ticker_rows_fabricated": "0",
                    "dynamic_weight_research_eligible": tf(dynamic_eligible),
                    "eligibility_status": "ELIGIBLE_FOR_FORWARD_OBSERVATION",
                    "exclusion_reason": "",
                    **COMMON,
                })
    return eligibility, accumulation


def safety_counts(groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in SAFETY_FIELDS}
    for rows in groups:
        for row in rows:
            for field in SAFETY_FIELDS:
                if truthy(row.get(field)):
                    counts[field] += 1
    return counts


def write_report(status: str, selected_id: str, source_count: int, eligible_count: int, pending_count: int) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.151 Forward Observation Accumulation Report", "",
        f"- wrapper_status: {status}",
        f"- selected_repair_scenario_id: {selected_id}",
        f"- discovered_source_artifact_count: {source_count}",
        f"- eligible_forward_observation_count: {eligible_count}",
        f"- outcome_pending_count: {pending_count}",
        "- formal_activation_allowed: FALSE",
        "- promotion_ready: FALSE",
        "",
        "Forward observations are accumulated from existing research artifacts only. No ticker rows, forward outcomes, benchmark outcomes, official artifacts, trades, broker executions, weight mutations, or performance claims are fabricated.",
    ]) + "\n", encoding="utf-8")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    gate = {
        "gate_check_id": "V20_151_FORWARD_OBSERVATION_GATE_001",
        "selected_repair_scenario_id": "",
        "v20_150_gate_consumed": "FALSE",
        "v20_151_allowed_after_v20_150": "FALSE",
        "staging_review_allowed": "FALSE",
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
        "safety_constraint_audit_passed": "FALSE",
        "source_audit_row_count": "0",
        "discovered_run_count": "0",
        "eligible_forward_observation_count": "0",
        "ineligible_forward_observation_count": "0",
        "outcome_pending_count": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "no_forward_outcomes_fabricated": "TRUE",
        "no_benchmark_outcomes_fabricated": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_152_forward_observation_review_allowed": "FALSE",
        "next_recommended_action": "V20.151_FORWARD_OBSERVATION_ACCUMULATION_REPAIR",
        "blocking_reason": blocking,
        "forward_observation_accumulation_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_ACCUMULATION, ACCUMULATION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, [])
    write_csv(OUT_ELIGIBILITY, ELIGIBILITY_FIELDS, [])
    write_report(BLOCKED_STATUS, "", 0, 0, 0)
    print(BLOCKED_STATUS)
    print("V20_151_ALLOWED_AFTER_V20_150=FALSE")
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    packet_rows = read_csv(IN_PACKET)
    gate_rows = read_csv(IN_GATE)
    boundary_rows = read_csv(IN_BOUNDARY)
    safety_rows = read_csv(IN_SAFETY)
    if not all([packet_rows, gate_rows, boundary_rows, safety_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    packet = first(packet_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(packet.get("selected_repair_scenario_id"))
    v150_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_150_STAGING_REVIEW_GATE_001"
    allowed = clean(gate_in.get("staging_review_packet_status")) == V150_REQUIRED_STATUS
    staging_allowed = truthy(gate_in.get("staging_review_allowed")) and truthy(packet.get("staging_review_allowed"))
    formal_activation_allowed = truthy(gate_in.get("formal_activation_allowed")) or truthy(packet.get("formal_activation_allowed"))
    promotion_ready = truthy(gate_in.get("promotion_ready")) or truthy(packet.get("promotion_ready"))
    safety_passed = all(truthy(row.get("safety_constraint_passed")) for row in safety_rows)
    boundary_passed = all(truthy(row.get("boundary_passed")) for row in boundary_rows)

    sources = discover_sources()
    source_audit = build_source_audit(selected_id, sources)
    eligibility, accumulation = collect_candidates(selected_id, sources)
    run_counts_by_path: dict[str, int] = {}
    for row in eligibility:
        run_counts_by_path[row["source_artifact_path"]] = run_counts_by_path.get(row["source_artifact_path"], 0) + 1
    for row in source_audit:
        discovered_count = run_counts_by_path.get(row["source_artifact_path"], 0)
        row["discovered_run_count"] = str(discovered_count)
        if row["source_usable_for_forward_observation"] == "TRUE" and discovered_count == 0:
            row["source_usable_for_forward_observation"] = "FALSE"
            row["source_exclusion_reason"] = "NO_DISCOVERED_RUN_ROWS"

    counts = safety_counts([packet_rows, gate_rows, boundary_rows, safety_rows, source_audit, eligibility, accumulation])
    safety_true_count = sum(counts.values())
    ticker_fabricated_count = sum(int(clean(row.get("ticker_rows_fabricated")) or "0") for row in accumulation)
    forward_fabricated_count = sum(1 for row in accumulation if truthy(row.get("forward_outcome_fabricated")))
    benchmark_fabricated_count = sum(1 for row in accumulation if truthy(row.get("benchmark_outcome_fabricated")))
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    eligible_count = len(accumulation)
    pending_count = sum(1 for row in accumulation if row.get("outcome_status") == "OUTCOME_PENDING")
    ineligible_count = sum(1 for row in eligibility if row.get("eligible_for_forward_observation") == "FALSE")
    gate_ok = all([v150_gate_consumed, allowed, staging_allowed, not formal_activation_allowed, not promotion_ready, safety_passed, boundary_passed, selected_id == EXPECTED_SCENARIO_ID])
    safe_ok = all([safety_true_count == 0, ticker_fabricated_count == 0, forward_fabricated_count == 0, benchmark_fabricated_count == 0, not upstream_mutation])

    if not gate_ok or not safe_ok:
        status = BLOCKED_STATUS
    elif eligible_count == 0:
        status = WARN_STATUS
    elif pending_count > 0:
        status = PARTIAL_STATUS
    else:
        status = PASS_STATUS
    next_allowed = status in {PASS_STATUS, PARTIAL_STATUS}
    blocking = "" if status != BLOCKED_STATUS else "forward_observation_accumulation_requirements_not_met"
    gate = {
        "gate_check_id": "V20_151_FORWARD_OBSERVATION_GATE_001",
        "selected_repair_scenario_id": selected_id,
        "v20_150_gate_consumed": tf(v150_gate_consumed),
        "v20_151_allowed_after_v20_150": tf(allowed),
        "staging_review_allowed": tf(staging_allowed),
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
        "safety_constraint_audit_passed": tf(safety_passed),
        "source_audit_row_count": str(len(source_audit)),
        "discovered_run_count": str(len(eligibility)),
        "eligible_forward_observation_count": str(eligible_count),
        "ineligible_forward_observation_count": str(ineligible_count),
        "outcome_pending_count": str(pending_count),
        "no_ticker_rows_fabricated": tf(ticker_fabricated_count == 0),
        "no_forward_outcomes_fabricated": tf(forward_fabricated_count == 0),
        "no_benchmark_outcomes_fabricated": tf(benchmark_fabricated_count == 0),
        "no_upstream_outputs_mutated": tf(not upstream_mutation),
        "v20_152_forward_observation_review_allowed": tf(next_allowed),
        "next_recommended_action": "V20.152_FORWARD_OBSERVATION_REVIEW" if next_allowed else "V20.151_FORWARD_OBSERVATION_ACCUMULATION_REPAIR",
        "blocking_reason": blocking,
        "forward_observation_accumulation_status": status,
        **COMMON,
    }
    write_csv(OUT_ACCUMULATION, ACCUMULATION_FIELDS, accumulation)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SOURCE_AUDIT, SOURCE_FIELDS, source_audit)
    write_csv(OUT_ELIGIBILITY, ELIGIBILITY_FIELDS, eligibility)
    write_report(status, selected_id, len(source_audit), eligible_count, pending_count)
    print(status)
    print(f"V20_150_GATE_CONSUMED={tf(v150_gate_consumed)}")
    print(f"V20_151_ALLOWED_AFTER_V20_150={tf(allowed)}")
    print(f"STAGING_REVIEW_ALLOWED={tf(staging_allowed)}")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"SAFETY_CONSTRAINT_AUDIT_PASSED={tf(safety_passed)}")
    print(f"SOURCE_AUDIT_ROW_COUNT={len(source_audit)}")
    print(f"DISCOVERED_RUN_COUNT={len(eligibility)}")
    print(f"ELIGIBLE_FORWARD_OBSERVATION_COUNT={eligible_count}")
    print(f"INELIGIBLE_FORWARD_OBSERVATION_COUNT={ineligible_count}")
    print(f"OUTCOME_PENDING_COUNT={pending_count}")
    print(f"TICKER_ROWS_FABRICATED={ticker_fabricated_count}")
    print(f"FORWARD_OUTCOMES_FABRICATED={forward_fabricated_count}")
    print(f"BENCHMARK_OUTCOMES_FABRICATED={benchmark_fabricated_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_TRUE_COUNT={safety_true_count}")
    print(f"V20_152_FORWARD_OBSERVATION_REVIEW_ALLOWED={tf(next_allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
