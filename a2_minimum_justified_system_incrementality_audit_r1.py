"""Governance-only builder for A2 minimum justified system audit R1.

The runner is deliberately phase-gated. ``outcome-blind`` may read only the
explicitly whitelisted frozen branch-registry seed. Later phases must consume
the frozen inventory manifest before opening certified pre-2026 evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from io import StringIO
from pathlib import Path
from typing import Any, Iterable


TASK = "A2_MINIMUM_JUSTIFIED_SYSTEM_AND_COMPONENT_INCREMENTALITY_AUDIT_R1"
EXECUTION = "EXECUTION_4_FRESH_ZERO_READ"
RESULT_ROOT = Path(r"D:\us-tech-quant-results") / TASK
SEED = (
    Path(r"D:\us-tech-quant-results")
    / "A2_RESEARCH_TREE_FUNCTIONAL_EQUIVALENCE_AND_DEDUP_CLOSURE_AUDIT_R1"
    / "research_branch_registry.csv"
)
SEED_SHA256 = "f2b8a73072d60345098a81e22afe09b77b59a9547caa6509358a8f22098cbc33"
DENYLISTED_RISK_REGISTRY = Path(
    r"D:\us-tech-quant\config\research_governance\risk_registry.json"
)
PARENT_TASK = "A2_SELECTION_MECHANISM_STRESS_AND_PORTFOLIO_BRIDGE_R1"
PARENT_ROOT = Path(r"D:\us-tech-quant-results") / PARENT_TASK
PARENT_FINGERPRINT = "5c09c526735746cf0763f0c4029de7858e227d6d24c7c5af190f62bcb459f7f2"
CANONICAL_REGISTRY_ROOT = Path(r"D:\us-tech-quant-results\US_TECH_QUANT_RESEARCH_REGISTRY")
SAFE_PARENT_INPUTS = {
    "summary": PARENT_ROOT / "a2_selection_mechanism_summary.json",
    "report": PARENT_ROOT / "a2_selection_mechanism_report.md",
    "descriptor": PARENT_ROOT / "descriptor_coverage_audit.csv",
    "reuse": PARENT_ROOT / "reuse_matrix.csv",
    "manifest": PARENT_ROOT / "final_manifest.json",
}
EXECUTION_DATE = "2026-08-30"

ZERO_READ_COUNTERS = {
    "POST_2025_REALIZED_LABEL_METRIC_READ_COUNT": 0,
    "POST_2025_MODEL_EVALUATION_METRIC_READ_COUNT": 0,
    "POST_2025_OUTCOME_DERIVED_METADATA_READ_COUNT": 0,
    "POST_2025_RETURN_READ_COUNT": 0,
    "POST_2025_NAV_READ_COUNT": 0,
    "POST_2025_PNL_READ_COUNT": 0,
    "POST_2025_IC_READ_COUNT": 0,
    "POST_2025_AUROC_READ_COUNT": 0,
    "HOLDOUT_PEEK_COUNT": 0,
    "MIXED_SOURCE_CONTENT_OPEN_COUNT": 0,
    "2026_ECONOMIC_OUTCOME_READ_COUNT": 0,
}

ANTI_BLOAT_COUNTERS = {
    "NEW_FEATURE_COUNT": 0,
    "MODIFIED_FEATURE_COUNT": 0,
    "NEW_PREDICTIVE_TARGET_COUNT": 0,
    "NEW_PREDICTIVE_MODEL_SPEC_COUNT": 0,
    "NEW_PREDICTIVE_MODEL_FIT_COUNT": 0,
    "NEW_HYPERPARAMETER_TRIAL_COUNT": 0,
    "NEW_THRESHOLD_SEARCH_COUNT": 0,
    "NEW_RX_MARGIN_SEARCH_COUNT": 0,
    "NEW_PORTFOLIO_WEIGHT_SEARCH_COUNT": 0,
    "NEW_COMPONENT_SUBSET_SEARCH_COUNT": 0,
    "NEW_OPTIMIZER_SEARCH_COUNT": 0,
    "CLOSED_BRANCH_REOPEN_COUNT": 0,
    "NEW_TRADABLE_COMPONENT_COUNT": 0,
    "NEW_DEPENDENCY_COUNT": 0,
    "HARNESS_MODIFICATION_COUNT": 0,
}

OUTCOME_BLIND_FIELDS = [
    "entity_id", "canonical_name", "aliases_json", "entity_type_candidate",
    "canonical_identity", "parent_entity_ids_json", "information_source",
    "information_family", "economic_thesis", "target_definition",
    "outcome_horizon", "decision_layer", "feature_input_family",
    "model_family", "portfolio_action", "data_contract", "cost_contract",
    "temporal_contract", "authoritative_artifact_refs_json",
    "primary_source_path", "primary_result_path", "code_fingerprint",
    "specification_fingerprint", "prior_lifecycle_status",
    "prior_negative_evidence", "prior_reuse_decision",
    "functional_equivalence_group", "equivalence_class", "duplicate_with",
    "blocker", "evidence_source_temporal_status", "excluded_source_refs_json",
    "temporal_evidence_limitations", "economic_evaluation_status",
    "source_registry_path", "source_row_sha256", "source_payload_json",
]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    if path.resolve() == DENYLISTED_RISK_REGISTRY.resolve():
        raise RuntimeError("denylisted mixed source must never be opened or hashed")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


def pipe_list(value: str) -> list[str]:
    return sorted({item.strip() for item in str(value or "").split("|") if item.strip()})


def entity_type_candidate(row: dict[str, str]) -> str:
    entity_id = row["canonical_branch_id"]
    cluster = row["branch_cluster"]
    if entity_id == "RAW_A2_HGB_BASELINE":
        return "CORE_BASELINE"
    if entity_id in {
        "RAW_A2_TOP40_CHECKPOINT", "RAW_A2_BROAD_OOF_PREDICTIONS",
        "A2_TEMPORAL_PIT_FEATURE_CONTRACT", "A2_COST_NAV_REPLAY_ENGINE",
        "UNIFIED_FORWARD_CONTROL_PLANE",
    }:
        return "DATA_INFRASTRUCTURE"
    if row["branch_status"] == "CLOSED_DUPLICATE":
        return "CLOSED_BRANCH"
    if entity_id in {"R6_BAD_ASYMMETRY_SIGNAL", "R6_TOP_DECILE_HALF_CASH_POLICY"}:
        return "RISK_CONTROL"
    if entity_id == "E5_EXECUTION_HYSTERESIS":
        return "PORTFOLIO_CONTROL"
    if entity_id == "THIRTEEN_F_DUAL_SLEEVE":
        return "DIVERSIFIER_COMPONENT"
    if cluster.startswith(("C_", "D_", "G_")):
        return "RESEARCH_HYPOTHESIS"
    return "ALPHA_COMPONENT"


def structural_specification(row: dict[str, str]) -> dict[str, str]:
    keys = (
        "canonical_branch_id", "information_source", "target_or_outcome",
        "outcome_horizon", "candidate_universe", "model_or_scoring_family",
        "action_locus", "economic_translation", "temporal_contract",
    )
    return {key: row.get(key, "") for key in keys}


def transform_seed_row(row: dict[str, str]) -> dict[str, str]:
    source_row_sha = sha256_bytes(canonical_json(row).encode("utf-8"))
    spec = structural_specification(row)
    spec_sha = sha256_bytes(canonical_json(spec).encode("utf-8"))
    aliases = pipe_list(row.get("known_aliases", ""))
    canonical_identity = sha256_bytes(canonical_json({
        "canonical_name": row["canonical_branch_id"],
        "specification_fingerprint": spec_sha,
    }).encode("utf-8"))
    artifacts = [value for value in (
        row.get("primary_source_path", ""), row.get("primary_result_path", "")
    ) if value]
    excluded = []
    if row.get("branch_cluster") == "C_LOSER_DOWNSIDE_RISK":
        excluded.append(str(DENYLISTED_RISK_REGISTRY))
    negative = row.get("reason", "") if "NEGATIVE" in row.get("branch_status", "") else ""
    translation = row.get("economic_translation", "")
    cost_contract = translation if any(
        token in translation.lower() for token in ("cost", "bps", "turnover")
    ) else "NOT_DECLARED_IN_SAFE_STRUCTURAL_SEED"
    return {
        "entity_id": row["canonical_branch_id"],
        "canonical_name": row["canonical_branch_id"],
        "aliases_json": canonical_json(aliases),
        "entity_type_candidate": entity_type_candidate(row),
        "canonical_identity": canonical_identity,
        "parent_entity_ids_json": canonical_json(pipe_list(row.get("parent_or_predecessor", ""))),
        "information_source": row.get("information_source", ""),
        "information_family": row.get("branch_cluster", ""),
        "economic_thesis": row.get("primary_hypothesis", ""),
        "target_definition": row.get("target_or_outcome", ""),
        "outcome_horizon": row.get("outcome_horizon", ""),
        "decision_layer": row.get("action_locus", ""),
        "feature_input_family": row.get("information_source", ""),
        "model_family": row.get("model_or_scoring_family", ""),
        "portfolio_action": translation,
        "data_contract": row.get("candidate_universe", ""),
        "cost_contract": cost_contract,
        "temporal_contract": row.get("temporal_contract", ""),
        "authoritative_artifact_refs_json": canonical_json(artifacts),
        "primary_source_path": row.get("primary_source_path", ""),
        "primary_result_path": row.get("primary_result_path", ""),
        "code_fingerprint": "NOT_COMPUTED_FILE_LEVEL_FIREWALL",
        "specification_fingerprint": spec_sha,
        "prior_lifecycle_status": row.get("branch_status", ""),
        "prior_negative_evidence": negative,
        "prior_reuse_decision": row.get("allowed_next_action", ""),
        "functional_equivalence_group": row.get("functional_equivalence_group", ""),
        "equivalence_class": row.get("equivalence_class", ""),
        "duplicate_with": row.get("duplicate_with", ""),
        "blocker": row.get("blocker", ""),
        "evidence_source_temporal_status": "SAFE_STRUCTURAL_METADATA_ONLY",
        "excluded_source_refs_json": canonical_json(excluded),
        "temporal_evidence_limitations": "ECONOMIC_EVIDENCE_NOT_OPENED_BEFORE_INVENTORY_FREEZE",
        "economic_evaluation_status": "NOT_ECONOMICALLY_TESTED_OUTCOME_BLIND",
        "source_registry_path": str(SEED),
        "source_row_sha256": source_row_sha,
        "source_payload_json": canonical_json(row),
    }


def supplemental_rows() -> list[dict[str, str]]:
    definitions = [
        (
            "RX_MARGIN_RANGE_EXHAUSTION_LINEAGE",
            ["RX_MARGIN_R1", "RANGE_EXHAUSTION"],
            "Range-exhaustion / RX margin lineage named by the human audit contract",
            "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION",
        ),
        (
            "OPEN_ML_FREE_FACTOR_DISCOVERY_LINEAGE",
            ["OPEN_ML_DISCOVERY", "FREE_FACTOR_DISCOVERY"],
            "Open ML and free-factor discovery lineage named by the human audit contract",
            "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE",
        ),
        (
            "THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE",
            ["13F_LEVEL", "13F_LIFECYCLE"],
            "13F level and ownership-lifecycle lineage named by the human audit contract",
            "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE",
        ),
    ]
    rows: list[dict[str, str]] = []
    for entity_id, aliases, thesis, blocker in definitions:
        spec = {
            "canonical_branch_id": entity_id,
            "information_source": "HUMAN_CONTRACT_NAMED_FAMILY_ONLY",
            "target_or_outcome": "UNKNOWN",
            "outcome_horizon": "UNKNOWN",
            "candidate_universe": "UNKNOWN",
            "model_or_scoring_family": "UNKNOWN",
            "action_locus": "UNKNOWN",
            "economic_translation": "NONE",
            "temporal_contract": "PRE2026_REQUIRED_BUT_UNPROVEN",
        }
        spec_sha = sha256_bytes(canonical_json(spec).encode("utf-8"))
        source_payload = {
            "source": "ORIGINAL_HUMAN_TASK_COMPONENT_UNIVERSE",
            "entity_id": entity_id,
            "aliases": aliases,
            "blocker": blocker,
        }
        row = {field: "" for field in OUTCOME_BLIND_FIELDS}
        row.update({
            "entity_id": entity_id,
            "canonical_name": entity_id,
            "aliases_json": canonical_json(aliases),
            "entity_type_candidate": "RESEARCH_HYPOTHESIS",
            "canonical_identity": sha256_bytes(canonical_json({
                "canonical_name": entity_id,
                "specification_fingerprint": spec_sha,
            }).encode("utf-8")),
            "parent_entity_ids_json": "[]",
            "information_source": "HUMAN_CONTRACT_NAMED_FAMILY_ONLY",
            "information_family": entity_id,
            "economic_thesis": thesis,
            "target_definition": "UNKNOWN",
            "outcome_horizon": "UNKNOWN",
            "decision_layer": "UNKNOWN",
            "feature_input_family": "UNKNOWN",
            "model_family": "UNKNOWN",
            "portfolio_action": "NONE",
            "data_contract": "UNKNOWN",
            "cost_contract": "UNKNOWN",
            "temporal_contract": "PRE2026_REQUIRED_BUT_UNPROVEN",
            "authoritative_artifact_refs_json": "[]",
            "code_fingerprint": "UNAVAILABLE",
            "specification_fingerprint": spec_sha,
            "prior_lifecycle_status": "UNKNOWN",
            "prior_reuse_decision": "UNRESOLVED_MISSING_EVIDENCE",
            "blocker": blocker,
            "evidence_source_temporal_status": "UNKNOWN_TEMPORAL_CONTENT",
            "excluded_source_refs_json": "[]",
            "temporal_evidence_limitations": blocker,
            "economic_evaluation_status": "UNTESTABLE_OUTCOME_BLIND",
            "source_registry_path": "ORIGINAL_HUMAN_TASK_CONTRACT",
            "source_row_sha256": sha256_bytes(canonical_json(source_payload).encode("utf-8")),
            "source_payload_json": canonical_json(source_payload),
        })
        rows.append(row)
    return rows


def serialize_csv(rows: Iterable[dict[str, str]], fields: list[str]) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    normalized = [
        {field: "" if row.get(field) is None else str(row.get(field, "")) for field in fields}
        for row in rows
    ]
    atomic_write_bytes(path, serialize_csv(normalized, fields))


def truthy(value: str) -> bool:
    return str(value).strip().lower() == "true"


def role_for(entity_id: str) -> str:
    if entity_id == "RAW_A2_HGB_BASELINE":
        return "CORE"
    if entity_id in {
        "RAW_A2_TOP40_CHECKPOINT",
        "RAW_A2_BROAD_OOF_PREDICTIONS",
        "A2_TEMPORAL_PIT_FEATURE_CONTRACT",
        "A2_COST_NAV_REPLAY_ENGINE",
        "UNIFIED_FORWARD_CONTROL_PLANE",
    }:
        return "INFRASTRUCTURE"
    if entity_id == "E5_EXECUTION_HYSTERESIS":
        return "TURNOVER_CONTROL"
    if entity_id == "THIRTEEN_F_DUAL_SLEEVE":
        return "DIVERSIFIER"
    if entity_id == "THIRTEEN_F_CHANGE_STANDALONE":
        return "INCREMENTAL_ALPHA"
    if entity_id == "THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE":
        return "UNRESOLVED"
    if entity_id in {
        "R6_BAD_ASYMMETRY_SIGNAL",
        "R6_TOP_DECILE_HALF_CASH_POLICY",
        "R6_ATTENUATION_POLICY_VARIANTS",
        "STOCK_RISK_MODEL_VARIANTS",
        "PORTFOLIO_SYSTEMIC_RISK_OS",
        "GENERIC_MARKET_RISK_GROSS_OVERLAYS",
        "FIXED_PIT_QQQ_BETA_TARGET_1",
        "S1_SECTOR_REWEIGHT",
        "SECTOR_CASH_AND_GROSS_VARIANTS",
        "RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION",
        "FULL_POOL_SECTOR_MEMBERSHIP_DECONCENTRATION",
    }:
        return "RISK_CONTROL"
    if entity_id in {
        "BETA_MATCHED_EXPOSURE_DIAGNOSTICS",
        "SIGNAL_HORIZON_AND_PERSISTENCE",
        "WINNER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC",
        "LOSER_ORTHOGONAL_LOGISTIC_DIAGNOSTIC",
        "A2_SUCCESSOR_CONTROL_S1",
        "ALPHA_MODEL_VARIANT_FORWARD_ARMS",
    }:
        return "MONITOR_ONLY"
    if entity_id in {
        "WINNER_Q90_NEXTGEN_SIGNAL",
        "NG8_TOP60_TO_TOP20_RERANK",
        "TOP20_BOUNDARY_RECOVERY_RERANK",
        "SECTOR_AWARE_ML_RERANK",
        "GT40_CANDIDATE_GENERATOR_RECALL",
        "INSIDER_H22",
        "SEC_FUNDAMENTAL_CHANGE",
        "SEC_FUNDAMENTAL_CHANGE_R2_WRAPPER",
    }:
        return "INCREMENTAL_ALPHA"
    return "UNRESOLVED"


def decision_for(row: dict[str, str]) -> str:
    entity_id = row["entity_id"]
    status = row["prior_lifecycle_status"]
    equivalence = row["equivalence_class"]
    blocker = row["blocker"]
    if entity_id == "RAW_A2_HGB_BASELINE":
        return "KEEP_CORE"
    if role_for(entity_id) == "INFRASTRUCTURE":
        return "KEEP_CORE"
    if equivalence == "EXACT_DUPLICATE":
        return "TOMBSTONE_EXACT_DUPLICATE"
    if equivalence == "FUNCTIONAL_DUPLICATE":
        return "TOMBSTONE_FUNCTIONAL_REDUNDANCY"
    if entity_id == "THIRTEEN_F_DUAL_SLEEVE":
        return "UNTESTABLE_TEMPORAL_SOURCE"
    if blocker == "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION" or entity_id == "FIXED_PIT_QQQ_BETA_TARGET_1":
        return "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION"
    if blocker == "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE":
        return "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"
    if entity_id == "GT40_CANDIDATE_GENERATOR_RECALL":
        return "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"
    if status == "CLOSED_NEGATIVE":
        return "CLOSED_PRIOR_UNCHANGED"
    if status in {"FORWARD_ACTIVE_WAIT", "FROZEN_RESEARCH_CANDIDATE"}:
        return "WAIT_FORWARD"
    if status == "CLOSED_MECHANISM_UNRESOLVED":
        return "PARK_MECHANISM_UNRESOLVED"
    return "PARK_MECHANISM_UNRESOLVED"


def evidence_status_for(row: dict[str, str], decision: str) -> str:
    if decision == "KEEP_CORE" and row["entity_id"] == "RAW_A2_HGB_BASELINE":
        return "SAFE_PRE2026_FIXED_PARENT_EVIDENCE"
    if decision == "KEEP_CORE":
        return "SAFE_STRUCTURAL_REQUIRED_INFRASTRUCTURE_IDENTITY"
    if decision.startswith("TOMBSTONE_"):
        return "SAFE_STRUCTURAL_AUTHORITATIVE_EQUIVALENCE_EVIDENCE"
    if decision == "CLOSED_PRIOR_UNCHANGED":
        return "SAFE_STRUCTURAL_AUTHORITATIVE_PRIOR_LIFECYCLE_ONLY"
    if decision == "WAIT_FORWARD":
        return "SAFE_STRUCTURAL_FORWARD_STATUS_ONLY"
    if decision == "UNTESTABLE_TEMPORAL_SOURCE":
        return "UNTESTABLE_TEMPORAL_SOURCE"
    if decision == "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION":
        return "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION"
    if decision == "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE":
        return "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"
    return "SAFE_STRUCTURAL_MECHANISM_IDENTITY_ONLY"


def incrementality_status_for(row: dict[str, str], decision: str) -> str:
    if row["entity_id"] == "RAW_A2_HGB_BASELINE":
        return "CORE_RETAINED_FIXED_PARENT_SELECTION_EVIDENCE_IDENTITY_INCONCLUSIVE"
    if decision == "KEEP_CORE":
        return "NOT_APPLICABLE_INFRASTRUCTURE"
    if decision == "TOMBSTONE_EXACT_DUPLICATE":
        return "NO_DISTINCT_INCREMENTALITY_EXACT_IDENTITY"
    if decision == "TOMBSTONE_FUNCTIONAL_REDUNDANCY":
        return "NO_DISTINCT_INCREMENTALITY_FUNCTIONALLY_EQUIVALENT_ACTION"
    if decision == "CLOSED_PRIOR_UNCHANGED":
        return "NOT_REOPENED_AUTHORITATIVE_CLOSED_PRIOR"
    if decision == "WAIT_FORWARD":
        return "NOT_CURRENTLY_JUSTIFIED_AWAIT_FIXED_FORWARD_EVIDENCE"
    if decision == "UNTESTABLE_TEMPORAL_SOURCE":
        return "UNTESTABLE_TEMPORAL_SOURCE"
    if decision.startswith("UNTESTABLE_"):
        return decision
    return "UNRESOLVED_NO_FIXED_CONDITIONAL_TEST"


def registry_status_for(row: dict[str, str], lifecycle_decision: str) -> str:
    if lifecycle_decision == "KEEP_CORE":
        return "ACTIVE"
    if lifecycle_decision.startswith("TOMBSTONE_"):
        return "TOMBSTONED"
    if lifecycle_decision == "SUPERSEDED_BY_AUTHORITATIVE_ENTITY":
        return "SUPERSEDED"
    if lifecycle_decision == "CLOSED_PRIOR_UNCHANGED":
        return "CLOSED"
    if row["prior_lifecycle_status"].startswith("CLOSED"):
        return "CLOSED"
    return "OPEN"


def registry_information_family(row: dict[str, str]) -> str:
    for field in ("feature_input_family", "information_source"):
        value = row.get(field, "").strip()
        if value and value.upper() not in {"UNKNOWN", "UNAVAILABLE"}:
            return value
    return row.get("information_family", "").strip() or row["entity_id"]


def decision_reason(row: dict[str, str], decision: str) -> str:
    entity_id = row["entity_id"]
    if entity_id == "RAW_A2_HGB_BASELINE":
        return (
            "Frozen Raw A2 remains the authoritative core. Existing pre-2026 selection survives "
            "aggregate cost, but alpha identity remains inconclusive and no upgrade is claimed."
        )
    if decision == "KEEP_CORE":
        return "Required identity, PIT, replay, or forward-control infrastructure; not a separate alpha claim."
    if decision == "TOMBSTONE_EXACT_DUPLICATE":
        return f"Safe authoritative seed classifies the wrapper as an exact duplicate of {row['duplicate_with']}."
    if decision == "TOMBSTONE_FUNCTIONAL_REDUNDANCY":
        return f"Safe authoritative seed classifies the branch as functionally redundant with {row['duplicate_with']}."
    if decision == "CLOSED_PRIOR_UNCHANGED":
        return "Authoritative closed lifecycle is preserved without reopening, refitting, or re-evaluating the branch."
    if decision == "WAIT_FORWARD":
        return "Distinct/frozen candidate status is preserved, but no safe fixed evidence currently justifies system inclusion."
    if decision == "UNTESTABLE_TEMPORAL_SOURCE":
        return "Required evidence depends on an excluded mixed or uncertified physical source; no negative inference is made."
    if decision == "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION":
        return "No frozen executable authoritative specification exists; the component fails closed without a test."
    if decision == "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE":
        return "Safe authoritative evidence is insufficient; the component remains unresolved without a negative inference."
    return "Mechanism identity is preserved, but fixed conditional incrementality evidence is unresolved."


def command_outcome_blind(_: argparse.Namespace) -> int:
    if sha256_file(SEED) != SEED_SHA256:
        raise RuntimeError("safe registry seed SHA-256 changed")
    with SEED.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if len(source_rows) != 37:
        raise RuntimeError(f"expected 37 seed rows, got {len(source_rows)}")
    rows = [transform_seed_row(row) for row in source_rows]
    rows.extend(supplemental_rows())
    rows.sort(key=lambda row: row["entity_id"])
    inventory_path = RESULT_ROOT / "component_inventory_outcome_blind.csv"
    payload = serialize_csv(rows, OUTCOME_BLIND_FIELDS)
    atomic_write_bytes(inventory_path, payload)
    inventory_sha = sha256_bytes(payload)
    manifest = {
        "schema": "A2_OUTCOME_BLIND_COMPONENT_INVENTORY_MANIFEST_R1",
        "task": TASK,
        "execution": EXECUTION,
        "status": "FROZEN_BEFORE_ECONOMIC_EVIDENCE_OPEN",
        "inventory_path": str(inventory_path),
        "inventory_bytes": len(payload),
        "inventory_sha256": inventory_sha,
        "entity_count": len(rows),
        "safe_seed_row_count": len(source_rows),
        "supplemental_unresolved_family_count": len(rows) - len(source_rows),
        "seed_path": str(SEED),
        "seed_sha256": SEED_SHA256,
        "denylisted_source_open_count": 0,
        "mixed_source_content_open_count": 0,
        "post_2025_realized_label_metric_read_count": 0,
        "post_2025_model_evaluation_metric_read_count": 0,
        "post_2025_outcome_derived_metadata_read_count": 0,
        "ordering_assertion": "OUTCOME_BLIND_INVENTORY_HASHED_BEFORE_PERMITTED_PRE2026_ECONOMIC_EVIDENCE",
    }
    atomic_write_json(RESULT_ROOT / "component_inventory_manifest.json", manifest)
    atomic_write_bytes(
        RESULT_ROOT / "component_inventory_sha256.txt",
        (inventory_sha + "\n").encode("ascii"),
    )
    print(f"OUTCOME_BLIND_ENTITY_COUNT={len(rows)}")
    print(f"COMPONENT_INVENTORY_SHA256={inventory_sha}")
    print("MIXED_SOURCE_CONTENT_OPEN_COUNT=0")
    print("POST_2025_MODEL_EVALUATION_METRIC_READ_COUNT=0")
    return 0


def verify_audit_inputs() -> dict[str, Any]:
    temporal_inventory_path = RESULT_ROOT / "physical_source_temporal_inventory.csv"
    temporal_rows = load_csv(temporal_inventory_path)
    by_path = {row["path"]: row for row in temporal_rows}

    deny = by_path.get(str(DENYLISTED_RISK_REGISTRY))
    if not deny or deny["temporal_status"] != "MIXED_POST2025" or truthy(deny["content_open_allowed"]):
        raise RuntimeError("denylisted risk registry is not fail-closed in source inventory")

    required_safe_paths = [SEED, *SAFE_PARENT_INPUTS.values()]
    for path in required_safe_paths:
        row = by_path.get(str(path))
        if not row:
            raise RuntimeError(f"safe-source inventory is missing {path}")
        if row["temporal_status"] not in {"SAFE_PRE2026", "SAFE_STRUCTURAL_METADATA_ONLY"}:
            raise RuntimeError(f"source is not affirmatively safe before open: {path}")
        if not truthy(row["content_open_allowed"]):
            raise RuntimeError(f"safe source is not open-authorized: {path}")

    inventory_manifest = load_json(RESULT_ROOT / "component_inventory_manifest.json")
    inventory_path = Path(inventory_manifest["inventory_path"])
    actual_inventory_sha = sha256_file(inventory_path)
    if actual_inventory_sha != inventory_manifest["inventory_sha256"]:
        raise RuntimeError("frozen outcome-blind inventory SHA-256 changed")
    if inventory_manifest["status"] != "FROZEN_BEFORE_ECONOMIC_EVIDENCE_OPEN":
        raise RuntimeError("outcome-blind inventory is not frozen")
    inventory_rows = load_csv(inventory_path)
    if len(inventory_rows) != inventory_manifest["entity_count"]:
        raise RuntimeError("outcome-blind inventory row count changed")

    parent_manifest_path = SAFE_PARENT_INPUTS["manifest"]
    if sha256_file(parent_manifest_path) != PARENT_FINGERPRINT:
        raise RuntimeError("authoritative parent fingerprint changed")
    parent_manifest = load_json(parent_manifest_path)
    expected_gate = {
        "terminal_status": "COMPLETED_WITH_LIMITATIONS",
        "controller_validation_status": "PASS",
        "last_review_status": "PASS",
        "original_work_units_remaining": 0,
    }
    for field, expected in expected_gate.items():
        if parent_manifest.get(field) != expected:
            raise RuntimeError(f"parent gate mismatch: {field}")

    parent_hash_rows: list[dict[str, Any]] = []
    for artifact in parent_manifest["artifacts"]:
        path = PARENT_ROOT / artifact["path"]
        source_row = by_path.get(str(path))
        if not source_row or source_row["temporal_status"] not in {
            "SAFE_PRE2026", "SAFE_STRUCTURAL_METADATA_ONLY"
        } or not truthy(source_row["content_open_allowed"]):
            raise RuntimeError(f"parent artifact lacks file-level safe certification: {path}")
        actual_sha = sha256_file(path)
        actual_bytes = path.stat().st_size
        if actual_sha != artifact["sha256"] or actual_bytes != artifact["bytes"]:
            raise RuntimeError(f"parent artifact identity mismatch: {path}")
        parent_hash_rows.append({
            "path": str(path),
            "role": artifact["role"],
            "expected_bytes": artifact["bytes"],
            "actual_bytes": actual_bytes,
            "expected_sha256": artifact["sha256"],
            "actual_sha256": actual_sha,
            "status": "PASS",
        })

    summary = load_json(SAFE_PARENT_INPUTS["summary"])
    descriptor_rows = load_csv(SAFE_PARENT_INPUTS["descriptor"])
    reuse_rows = load_csv(SAFE_PARENT_INPUTS["reuse"])
    cutoffs = summary["cutoffs"]
    if any(value > "2025-12-31" for value in cutoffs.values()):
        raise RuntimeError("parent economic evidence exceeds pre-2026 cutoff")
    for module in summary["primary_tests"].values():
        if module["specifications_run"] != 0 or module["economic_tests_run"] != 0:
            raise RuntimeError("missing-specification module was unexpectedly executed")

    if sha256_file(SEED) != SEED_SHA256:
        raise RuntimeError("safe registry seed SHA-256 changed")

    return {
        "temporal_rows": temporal_rows,
        "inventory_manifest": inventory_manifest,
        "inventory_rows": inventory_rows,
        "parent_manifest": parent_manifest,
        "parent_hash_rows": parent_hash_rows,
        "summary": summary,
        "descriptor_rows": descriptor_rows,
        "reuse_rows": reuse_rows,
    }


def build_decisions(inventory_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for row in inventory_rows:
        decision = decision_for(row)
        role = role_for(row["entity_id"])
        excluded_refs = json.loads(row["excluded_source_refs_json"] or "[]")
        if row["entity_id"] == "THIRTEEN_F_DUAL_SLEEVE":
            excluded_refs = sorted(set(excluded_refs + [
                str(PARENT_ROOT.parent / "A2_13F_DUAL_SLEEVE_DIVERSIFICATION_R1")
            ]))
        decisions.append({
            "component_id": row["entity_id"],
            "canonical_name": row["canonical_name"],
            "economic_role": role,
            "lifecycle_decision": decision,
            "currently_in_minimum_system": decision == "KEEP_CORE",
            "required_infrastructure": role == "INFRASTRUCTURE",
            "incrementality_status": incrementality_status_for(row, decision),
            "evidence_status": evidence_status_for(row, decision),
            "decision_reason": decision_reason(row, decision),
            "prior_lifecycle_status": row["prior_lifecycle_status"],
            "prior_reuse_decision": row["prior_reuse_decision"],
            "equivalence_class": row["equivalence_class"],
            "functional_equivalence_group": row["functional_equivalence_group"],
            "duplicate_with": row["duplicate_with"],
            "specification_fingerprint": row["specification_fingerprint"],
            "source_row_sha256": row["source_row_sha256"],
            "evidence_source_temporal_status": row["evidence_source_temporal_status"],
            "excluded_source_refs": excluded_refs,
            "temporal_evidence_limitations": (
                decision if decision.startswith("UNTESTABLE_")
                else row["temporal_evidence_limitations"]
            ),
            "no_negative_inference_from_missing_evidence": decision.startswith("UNTESTABLE_"),
        })
    return decisions


def build_equivalence_rows(
    inventory_rows: list[dict[str, str]], decisions_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in inventory_rows:
        eq_class = row["equivalence_class"] or "UNRESOLVED"
        exact = eq_class == "EXACT_DUPLICATE"
        functional = eq_class == "FUNCTIONAL_DUPLICATE"
        distinct = eq_class == "GENUINELY_DISTINCT"
        confidence = "HIGH" if exact or functional else ("AUTHORITATIVE_STRUCTURAL" if eq_class else "UNRESOLVED")
        rows.append({
            "component_id": row["entity_id"],
            "canonical_or_duplicate_target": row["duplicate_with"] or row["entity_id"],
            "functional_equivalence_group": row["functional_equivalence_group"],
            "equivalence_class": eq_class,
            "exact_identity_match": str(exact).lower(),
            "functional_equivalent_action": str(functional).lower(),
            "genuinely_distinct_information_source": str(distinct).lower() if eq_class != "UNRESOLVED" else "unknown",
            "confidence": confidence,
            "evidence_source": "SAFE_CANONICAL_BRANCH_SEED_ROW_SHA256",
            "evidence_sha256": row["source_row_sha256"],
            "lifecycle_decision": decisions_by_id[row["entity_id"]]["lifecycle_decision"],
            "new_similarity_threshold_created": "false",
        })
    return rows


def build_matched_sample_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    descriptor = summary["descriptor_audit"]
    selection = summary["selection_concentration"]
    modules = summary["primary_tests"]
    return [
        {
            "audit_surface": "RAW_A2_FIXED_SELECTION_CHAIN",
            "component_id": "RAW_A2_HGB_BASELINE",
            "sample_contract": "AUTHORITATIVE_PARENT_EXISTING_ALIGNMENT_ONLY",
            "pre2026_cutoff": "2025-12-31",
            "available_rows_or_dates": selection["daily_observations"],
            "eligible_complete_case_rows": selection["daily_observations"],
            "aligned_rows": selection["daily_observations"],
            "matched_rows": 0,
            "specifications_run": 0,
            "economic_tests_run": 0,
            "status": "REUSED_FIXED_PARENT_EVIDENCE_NO_NEW_TEST",
            "limitation": "Selection is date-broad but identity remains inconclusive and security breadth is partial.",
        },
        {
            "audit_surface": "PRIMARY_TEST_A_RESIDUAL_A2_SCORE",
            "component_id": "RAW_A2_HGB_BASELINE",
            "sample_contract": "MISSING_FROZEN_RESIDUALIZATION_SPECIFICATION",
            "pre2026_cutoff": "2025-12-31",
            "available_rows_or_dates": descriptor["total_top40_rows"],
            "eligible_complete_case_rows": 0,
            "aligned_rows": 0,
            "matched_rows": 0,
            "specifications_run": modules["residual_a2_score"]["specifications_run"],
            "economic_tests_run": modules["residual_a2_score"]["economic_tests_run"],
            "status": "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION",
            "limitation": modules["residual_a2_score"]["reason"],
        },
        {
            "audit_surface": "PRIMARY_TEST_B_FIXED_MATCHED_PEER",
            "component_id": "RAW_A2_HGB_BASELINE",
            "sample_contract": "MISSING_FROZEN_MATCHING_SPECIFICATION",
            "pre2026_cutoff": "2025-12-31",
            "available_rows_or_dates": descriptor["total_top40_rows"],
            "eligible_complete_case_rows": 0,
            "aligned_rows": 0,
            "matched_rows": 0,
            "specifications_run": modules["matched_peer"]["specifications_run"],
            "economic_tests_run": modules["matched_peer"]["economic_tests_run"],
            "status": "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION",
            "limitation": modules["matched_peer"]["reason"],
        },
        {
            "audit_surface": "OPTIONAL_13F_ORTHOGONALITY",
            "component_id": "THIRTEEN_F_DUAL_SLEEVE",
            "sample_contract": "NO_CERTIFIED_PHYSICALLY_ISOLATED_PRE2026_STANDALONE_SLEEVE",
            "pre2026_cutoff": "UNPROVEN_SOURCE_NOT_OPENED",
            "available_rows_or_dates": 0,
            "eligible_complete_case_rows": 0,
            "aligned_rows": 0,
            "matched_rows": 0,
            "specifications_run": 0,
            "economic_tests_run": 0,
            "status": "UNTESTABLE_TEMPORAL_SOURCE",
            "limitation": summary["optional_13f_orthogonality"]["reason"],
        },
    ]


def build_incrementality_rows(
    decisions: list[dict[str, Any]], summary: dict[str, Any]
) -> list[dict[str, Any]]:
    bridge = summary["selection_cost_bridge"]
    rows: list[dict[str, Any]] = []
    for item in decisions:
        gross = cost = net = ""
        evidence_scope = "SAFE_STRUCTURAL_GOVERNANCE_ONLY"
        matched_status = "NO_NEW_MATCHED_TEST"
        lifecycle = item["lifecycle_decision"]
        if lifecycle == "UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION":
            fixed_specification_available = "false"
        elif lifecycle.startswith("UNTESTABLE_") or lifecycle == "PARK_MECHANISM_UNRESOLVED":
            fixed_specification_available = "unknown_or_not_opened"
        elif lifecycle == "KEEP_CORE" and item["component_id"] == "RAW_A2_HGB_BASELINE":
            fixed_specification_available = "true_existing_fixed_parent"
        elif lifecycle == "KEEP_CORE":
            fixed_specification_available = "not_applicable_infrastructure"
        elif lifecycle.startswith("TOMBSTONE_"):
            fixed_specification_available = "not_applicable_duplicate_identity"
        elif lifecycle == "CLOSED_PRIOR_UNCHANGED":
            fixed_specification_available = "not_reopened_prior_lifecycle_only"
        else:
            fixed_specification_available = "structural_status_preserved_no_new_test"
        if item["component_id"] == "RAW_A2_HGB_BASELINE":
            gross = bridge["gross_selection_linked_contribution"]
            cost = bridge["implementation_cost_linked_contribution"]
            net = bridge["net_selection_after_cost_linked_contribution"]
            evidence_scope = "FIXED_PARENT_PRE2026_TOTAL_SELECTION_DECOMPOSITION"
            matched_status = "EXISTING_PARENT_ALIGNMENT_REUSED"
        elif item["component_id"] == "RAW_A2_TOP40_CHECKPOINT":
            gross = bridge["raw_a2_top40_rank_selection_linked"]
            cost = bridge["raw_a2_top40_rank_selection_cost_linked"]
            net = bridge["raw_a2_top40_rank_selection_net_linked"]
            evidence_scope = "FIXED_PARENT_PRE2026_RANK_SELECTION_DECOMPOSITION"
            matched_status = "EXISTING_PARENT_ALIGNMENT_REUSED_INFRASTRUCTURE_ONLY"
        rows.append({
            "component_id": item["component_id"],
            "baseline_id": "RAW_A2_HGB_BASELINE",
            "fixed_specification_requirement_enforced": "true",
            "fixed_specification_available": fixed_specification_available,
            "sample_end": "2025-12-31" if evidence_scope.startswith("FIXED_PARENT") else "NOT_OPENED_OR_NOT_APPLICABLE",
            "matched_sample_status": matched_status,
            "gross_linked_incrementality": gross,
            "implementation_cost_linked": cost,
            "net_linked_incrementality": net,
            "evidence_scope": evidence_scope,
            "conditional_incrementality_status": item["incrementality_status"],
            "economic_role": item["economic_role"],
            "lifecycle_decision": item["lifecycle_decision"],
            "negative_inference_from_missing_evidence": "false",
            "new_test_run": "false",
        })
    return rows


def build_cost_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    bridge = summary["selection_cost_bridge"]
    return [
        {
            "evidence_unit": "TOTAL_SELECTION_CHAIN",
            "component_id": "RAW_A2_HGB_BASELINE",
            "gross_linked": bridge["gross_selection_linked_contribution"],
            "cost_linked": bridge["implementation_cost_linked_contribution"],
            "net_linked": bridge["net_selection_after_cost_linked_contribution"],
            "cost_consumption_ratio": bridge["linked_cost_consumption_ratio"],
            "selection_turnover_pearson": bridge["daily_selection_turnover_pearson"],
            "net_selection_turnover_pearson": bridge["daily_net_selection_turnover_pearson"],
            "signal_dates": bridge["top20_signal_dates"],
            "switch_dates": bridge["switch_dates_excluding_initial_formation"],
            "status": "SURVIVES_EXISTING_COST_FIXED_PARENT_EVIDENCE",
        },
        {
            "evidence_unit": "RAW_A2_TOP40_RANK_SELECTION",
            "component_id": "RAW_A2_TOP40_CHECKPOINT",
            "gross_linked": bridge["raw_a2_top40_rank_selection_linked"],
            "cost_linked": bridge["raw_a2_top40_rank_selection_cost_linked"],
            "net_linked": bridge["raw_a2_top40_rank_selection_net_linked"],
            "cost_consumption_ratio": "",
            "selection_turnover_pearson": "",
            "net_selection_turnover_pearson": "",
            "signal_dates": bridge["top20_signal_dates"],
            "switch_dates": bridge["switch_dates_excluding_initial_formation"],
            "status": "FULLY_CONSUMED_BY_EXISTING_COST_NOT_A_SEPARATE_COMPONENT_DECISION",
        },
        {
            "evidence_unit": "TOP40_TO_TOP20_CONCENTRATION",
            "component_id": "RAW_A2_HGB_BASELINE",
            "gross_linked": bridge["top40_to_top20_concentration_selection_linked"],
            "cost_linked": bridge["top40_to_top20_concentration_cost_linked"],
            "net_linked": bridge["top40_to_top20_concentration_net_linked"],
            "cost_consumption_ratio": "",
            "selection_turnover_pearson": "",
            "net_selection_turnover_pearson": "",
            "signal_dates": bridge["top20_signal_dates"],
            "switch_dates": bridge["switch_dates_excluding_initial_formation"],
            "status": "POSITIVE_FIXED_PARENT_CONCENTRATION_DECOMPOSITION_NOT_NEW_NONCORE_COMPONENT",
        },
    ]


def build_factor_rows() -> list[dict[str, Any]]:
    return [
        {
            "component_id": "RAW_A2_HGB_BASELINE",
            "exposure_measure": "SYSTEMATIC_LINKED_RETURN_SHARE",
            "value": 0.703,
            "source": "FIXED_CLEAN_R2_PARENT_EVIDENCE_REUSED_BY_AUTHORITATIVE_PARENT",
            "sample_end": "2025-12-31",
            "interpretation": "MATERIAL_SYSTEMATIC_EXPOSURE_IDENTITY_NOT_UPGRADED",
        },
        {
            "component_id": "RAW_A2_HGB_BASELINE",
            "exposure_measure": "SYSTEMATIC_VARIANCE_SHARE",
            "value": 0.695,
            "source": "FIXED_CLEAN_R2_PARENT_EVIDENCE_REUSED_BY_AUTHORITATIVE_PARENT",
            "sample_end": "2025-12-31",
            "interpretation": "MATERIAL_SYSTEMATIC_EXPOSURE_IDENTITY_NOT_UPGRADED",
        },
        {
            "component_id": "RAW_A2_HGB_BASELINE",
            "exposure_measure": "THREE_FACTOR_REGRESSION_R2",
            "value": 0.544,
            "source": "FIXED_CLEAN_R2_PARENT_EVIDENCE_REUSED_BY_AUTHORITATIVE_PARENT",
            "sample_end": "2025-12-31",
            "interpretation": "MATERIAL_SYSTEMATIC_EXPOSURE_IDENTITY_NOT_UPGRADED",
        },
    ]


def build_concentration_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    concentration = summary["selection_concentration"]
    return [
        {"grain": "DATE", "measure": "TOTAL_DATES", "value": concentration["daily_observations"], "status": "AVAILABLE"},
        {"grain": "DATE", "measure": "POSITIVE_DATES", "value": concentration["positive_selection_dates"], "status": "AVAILABLE"},
        {"grain": "DATE", "measure": "TOP5_POSITIVE_CONTRIBUTION_SHARE", "value": concentration["top5_date_positive_contribution_share"], "status": "AVAILABLE"},
        {"grain": "DATE", "measure": "TOP10_POSITIVE_CONTRIBUTION_SHARE", "value": concentration["top10_date_positive_contribution_share"], "status": "AVAILABLE"},
        {"grain": "DATE", "measure": "POSITIVE_DATE_HHI", "value": concentration["positive_date_hhi"], "status": "AVAILABLE"},
        {"grain": "DATE", "measure": "EFFECTIVE_POSITIVE_DATES", "value": concentration["effective_positive_dates"], "status": "AVAILABLE"},
        {"grain": "SECURITY", "measure": "TOP10_POSITIVE_CONTRIBUTION_SHARE", "value": concentration["top10_security_positive_contribution_share_reused"], "status": "AVAILABLE_REUSED"},
        {"grain": "SECURITY", "measure": "TOP5_POSITIVE_CONTRIBUTION_SHARE", "value": "", "status": "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"},
        {"grain": "SECURITY", "measure": "HHI", "value": "", "status": "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"},
        {"grain": "SECURITY_SECTOR", "measure": "TECH_SEMICONDUCTOR_OTHER_SLICE", "value": "", "status": "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"},
        {"grain": "SECURITY_RANK", "measure": "RANK_BUCKET_SLICE_1_5_6_10_11_20", "value": "", "status": "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE"},
    ]


def command_audit(_: argparse.Namespace) -> int:
    verified = verify_audit_inputs()
    inventory_rows = verified["inventory_rows"]
    summary = verified["summary"]
    inventory_sha = verified["inventory_manifest"]["inventory_sha256"]
    decisions = build_decisions(inventory_rows)
    inventory_by_id = {row["entity_id"]: row for row in inventory_rows}
    temporal_by_path = {
        row["path"].replace("/", "\\").casefold(): row
        for row in verified["temporal_rows"]
    }
    for decision in decisions:
        inventory_row = inventory_by_id[decision["component_id"]]
        artifact_refs = json.loads(inventory_row["authoritative_artifact_refs_json"] or "[]")
        expanded_refs = sorted({
            part.strip()
            for reference in artifact_refs
            for part in str(reference).split("|")
            if part.strip()
        })
        uncertified_refs = []
        for reference in expanded_refs:
            source = temporal_by_path.get(reference.replace("/", "\\").casefold())
            if not source or source["temporal_status"] not in {"SAFE_PRE2026", "SAFE_STRUCTURAL_METADATA_ONLY"}:
                uncertified_refs.append(reference)
        if uncertified_refs:
            decision["excluded_source_refs"] = sorted(set(decision["excluded_source_refs"] + uncertified_refs))
            suffix = f"EXCLUDED_UNCERTIFIED_PRIMARY_REFERENCE_COUNT={len(uncertified_refs)}"
            existing = decision["temporal_evidence_limitations"]
            decision["temporal_evidence_limitations"] = f"{existing};{suffix}" if existing else suffix
    decisions_by_id = {row["component_id"]: row for row in decisions}

    decision_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for row in decisions:
        decision_counts[row["lifecycle_decision"]] = decision_counts.get(row["lifecycle_decision"], 0) + 1
        role_counts[row["economic_role"]] = role_counts.get(row["economic_role"], 0) + 1

    preflight_manifest = {
        "schema": "A2_MINIMUM_JUSTIFIED_SYSTEM_PREFLIGHT_R1",
        "task": TASK,
        "execution": EXECUTION,
        "execution_mode": "FRESH_ZERO_READ_EXECUTION",
        "task_scope": "pre2026-research",
        "preflight_status": "PASS_WITH_SCOPED_HARD_BLOCKERS",
        "preflight_source": "HUMAN_SUPPLIED_SUCCESSFUL_SCOPED_PREFLIGHT",
        "preflight_rerun_in_fresh_execution": False,
        "preflight_rerun_reason": "FILE_LEVEL_FIREWALL_PROHIBITS_A_TOOL_PATH_THAT_OPENS_DENYLISTED_OR_MIXED_SOURCES",
        "applicable_hard_blocker_count": 0,
        "scoped_hard_blocker_count": 1,
        "scoped_hard_blocker": "A2_2026_HOLDOUT_ALREADY_EXPOSED",
        "scoped_blocker_blocks": "2026-optimization",
        "scoped_blocker_applicable_to_task": False,
        "parent_gate": "PASS",
        "parent_task": PARENT_TASK,
        "parent_terminal_status": "COMPLETED_WITH_LIMITATIONS",
        "parent_controller_validation_status": "PASS",
        "parent_last_review_status": "PASS",
        "parent_authoritative_fingerprint": PARENT_FINGERPRINT,
        "parent_manifest_artifact_hashes_verified": 8,
        "original_work_units_remaining": 0,
        "outcome_blind_inventory_sha256": inventory_sha,
        "risk_registry_status": "DENYLISTED_MIXED_2026",
        "risk_registry_content_opened": False,
        "fresh_zero_read_counters": ZERO_READ_COUNTERS,
        "anti_bloat_counters": ANTI_BLOAT_COUNTERS,
        "substantive_audit_gate": "PASS",
    }
    atomic_write_json(RESULT_ROOT / "preflight_manifest.json", preflight_manifest)

    preflight_report = f"""# Preflight report

Task: `{TASK}`  
Execution: `{EXECUTION}`  
Scope: `pre2026-research`

The user-supplied scoped preflight is `PASS_WITH_SCOPED_HARD_BLOCKERS`. Its only hard blocker, `A2_2026_HOLDOUT_ALREADY_EXPOSED`, blocks 2026 optimization and is not applicable to this post-2025-outcome-free pre-2026 audit. This execution makes no pristine-holdout claim.

The authoritative parent gate is `PASS`: terminal status `COMPLETED_WITH_LIMITATIONS`, controller validation `PASS`, independent review `PASS`, fingerprint `{PARENT_FINGERPRINT}`, all eight manifest artifact hashes verified, and original work units remaining `0`.

The fresh file-level firewall was completed before outcome-blind inventory construction. `risk_registry.json` is `DENYLISTED_MIXED_2026`; it was neither opened nor hashed. The frozen outcome-blind inventory SHA-256 is `{inventory_sha}`.

All fresh zero-read and Anti-Bloat counters are zero. The preflight executable was not rerun inside this fresh execution because that path is incompatible with the stricter physical-file firewall; the already-successful scoped preflight supplied by the user is the authoritative preflight result.
"""
    atomic_write_bytes(RESULT_ROOT / "preflight_report.md", preflight_report.encode("utf-8"))

    artifact_rows: list[dict[str, Any]] = []
    for index, row in enumerate(verified["parent_hash_rows"], start=1):
        artifact_rows.append({
            "source_id": f"PARENT_ARTIFACT_{index:02d}",
            "path": row["path"],
            "temporal_classification": "SAFE_PRE2026_OR_STRUCTURAL_PER_FILE_INVENTORY",
            "content_opened": "true",
            "bytes": row["actual_bytes"],
            "expected_sha256": row["expected_sha256"],
            "actual_sha256": row["actual_sha256"],
            "identity_status": row["status"],
            "role": row["role"],
            "limitation": "",
        })
    artifact_rows.extend([
        {
            "source_id": "SAFE_CANONICAL_BRANCH_SEED",
            "path": str(SEED),
            "temporal_classification": "SAFE_STRUCTURAL_METADATA_ONLY",
            "content_opened": "true",
            "bytes": SEED.stat().st_size,
            "expected_sha256": SEED_SHA256,
            "actual_sha256": sha256_file(SEED),
            "identity_status": "PASS",
            "role": "CANONICAL_BOOTSTRAP_SEED",
            "limitation": "GOVERNANCE_ONLY_NO_REALIZED_HOLDOUT_METRICS",
        },
        {
            "source_id": "FROZEN_OUTCOME_BLIND_INVENTORY",
            "path": verified["inventory_manifest"]["inventory_path"],
            "temporal_classification": "TASK_GENERATED_OUTCOME_BLIND",
            "content_opened": "true",
            "bytes": verified["inventory_manifest"]["inventory_bytes"],
            "expected_sha256": inventory_sha,
            "actual_sha256": sha256_file(Path(verified["inventory_manifest"]["inventory_path"])),
            "identity_status": "PASS",
            "role": "FROZEN_COMPONENT_UNIVERSE",
            "limitation": "FROZEN_BEFORE_ECONOMIC_EVIDENCE_OPEN",
        },
        {
            "source_id": "DENYLISTED_RISK_REGISTRY",
            "path": str(DENYLISTED_RISK_REGISTRY),
            "temporal_classification": "MIXED_POST2025",
            "content_opened": "false",
            "bytes": "FILESYSTEM_METADATA_ONLY",
            "expected_sha256": "NOT_COMPUTED",
            "actual_sha256": "NOT_COMPUTED",
            "identity_status": "EXCLUDED",
            "role": "EXCLUDED_MODEL_REGISTRY",
            "limitation": "DENYLISTED_MIXED_2026_DO_NOT_OPEN",
        },
    ])
    for source_id, name, expected_sha in (
        ("EXECUTION_1_2_BLOCKER_PROVENANCE", "BLOCKER_REPORT.md", "153779a23e28ca65dfce60d460eb52cd70fdd76c97ac91158197fe16d0f93a72"),
        ("EXECUTION_3_TEMPORAL_BLOCKER_PROVENANCE", "TEMPORAL_INTEGRITY_BLOCKER_REPORT.md", "85026b889a03745d85f449fafd39816c5671468f7d19e1d293acf3c5aabe3cc7"),
    ):
        path = RESULT_ROOT / name
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise RuntimeError(f"historical blocker provenance changed: {name}")
        artifact_rows.append({
            "source_id": source_id,
            "path": str(path),
            "temporal_classification": "SAFE_STRUCTURAL_METADATA_ONLY",
            "content_opened": "HASH_ONLY",
            "bytes": path.stat().st_size,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "identity_status": "PASS_PRESERVED_UNCHANGED",
            "role": "HISTORICAL_EXECUTION_PROVENANCE",
            "limitation": "CONTENTS_NOT_USED_AS_RESEARCH_INPUT",
        })
    artifact_fields = [
        "source_id", "path", "temporal_classification", "content_opened", "bytes",
        "expected_sha256", "actual_sha256", "identity_status", "role", "limitation",
    ]
    write_csv(RESULT_ROOT / "authoritative_artifact_inventory.csv", artifact_rows, artifact_fields)

    conflict_rows = [
        {
            "conflict_id": "PARENT_STATUS_VOCABULARY",
            "surface_a": "a2_selection_mechanism_summary.json.final_status",
            "value_a": summary["final_status"],
            "surface_b": "final_manifest.json.terminal_status",
            "value_b": verified["parent_manifest"]["terminal_status"],
            "resolution": "NO_RESEARCH_CONFLICT_MANIFEST_TERMINAL_VOCABULARY_IS_AUTHORITATIVE",
            "resolved_by": "AUTHORITATIVE_PARENT_FINAL_MANIFEST",
            "status": "RESOLVED",
        },
        {
            "conflict_id": "LEGACY_REGISTRY_TEMPORAL_SCOPE",
            "surface_a": "SAFE_CANONICAL_BRANCH_SEED",
            "value_a": "SAFE_STRUCTURAL_METADATA_ONLY",
            "surface_b": "LEGACY_CURRENT_AND_MODEL_REGISTRIES",
            "value_b": "UNKNOWN_OR_MIXED_TEMPORAL_CONTENT",
            "resolution": "BOOTSTRAP_FROM_SAFE_SEED_EXCLUDE_UNKNOWN_AND_MIXED_SOURCES",
            "resolved_by": "FILE_LEVEL_TEMPORAL_FIREWALL",
            "status": "RESOLVED_WITH_LIMITATION",
        },
    ]
    write_csv(
        RESULT_ROOT / "artifact_conflict_report.csv",
        conflict_rows,
        ["conflict_id", "surface_a", "value_a", "surface_b", "value_b", "resolution", "resolved_by", "status"],
    )

    temporal_audit = {
        "schema": "A2_FILE_LEVEL_TEMPORAL_SOURCE_AUDIT_R1",
        "task": TASK,
        "execution": EXECUTION,
        "status": "PASS",
        "policy": "OPEN_ONLY_SAFE_PRE2026_OR_SAFE_STRUCTURAL_METADATA_ONLY_PHYSICAL_FILES",
        "open_then_filter_prohibited": True,
        "denylisted_source": str(DENYLISTED_RISK_REGISTRY),
        "denylisted_source_status": "DENYLISTED_MIXED_2026",
        "denylisted_source_content_opened": False,
        "unknown_source_content_opened": False,
        "outcome_blind_inventory_frozen_before_economic_evidence": True,
        "outcome_blind_inventory_sha256": inventory_sha,
        "permitted_parent_economic_evidence_cutoff": "2025-12-31",
        "fresh_zero_read_counters": ZERO_READ_COUNTERS,
        "prior_execution_contamination_retained_only_as_fact": (
            "A prior execution encountered two forbidden post-2025 model evaluation metric values and was terminated."
        ),
        "prior_values_retrieved_or_used": False,
    }
    atomic_write_json(RESULT_ROOT / "temporal_source_audit.json", temporal_audit)

    unknown_rows = [row for row in verified["temporal_rows"] if row["temporal_status"] == "UNKNOWN_TEMPORAL_CONTENT"]
    registry_related_unknown_ids = {
        "SRC_REGISTRY_LEGACY_CURRENT",
        "SRC_REGISTRY_LEGACY_CURRENT_MANIFEST",
        "SRC_MODEL_ALPHA_REGISTRY",
        "SRC_MODEL_EXECUTION_REGISTRY",
    }
    separately_listed_registry_source_ids = {
        "SRC_REGISTRY_LEGACY_CURRENT",
        "SRC_MODEL_ALPHA_REGISTRY",
        "SRC_MODEL_EXECUTION_REGISTRY",
    }
    registry_related_unknown = [
        row for row in unknown_rows if row["source_id"] in registry_related_unknown_ids
    ]
    non_registry_candidate_unknown = [
        row for row in unknown_rows if row["source_id"] not in registry_related_unknown_ids
    ]
    temporal_inventory_reconciliation = {
        "schema": "A2_FILE_LEVEL_TEMPORAL_INVENTORY_COUNT_RECONCILIATION_R1",
        "task": TASK,
        "execution": EXECUTION,
        "status": "PASS_WITH_SCHEMA_CLARIFICATION",
        "frozen_manifest_modified": False,
        "physical_inventory_sha256": sha256_file(RESULT_ROOT / "physical_source_temporal_inventory.csv"),
        "physical_inventory_total_row_count": len(verified["temporal_rows"]),
        "physical_inventory_unknown_temporal_source_count_total": len(unknown_rows),
        "unknown_non_registry_candidate_source_count": len(non_registry_candidate_unknown),
        "unknown_registry_related_physical_row_count": len(registry_related_unknown),
        "unknown_registry_sources_separately_listed_count": len([
            row for row in unknown_rows if row["source_id"] in separately_listed_registry_source_ids
        ]),
        "unknown_paired_legacy_registry_manifest_count": len([
            row for row in unknown_rows if row["source_id"] == "SRC_REGISTRY_LEGACY_CURRENT_MANIFEST"
        ]),
        "frozen_manifest_unknown_temporal_source_count_field": len(non_registry_candidate_unknown),
        "clarification": (
            "The frozen manifest field counted 20 non-registry candidate sources. Four additional UNKNOWN "
            "registry-related physical rows comprise three registry sources separately listed in "
            "safe_registry_source_inventory.csv plus the paired legacy-current manifest. The physical "
            "inventory total is 24 UNKNOWN rows; its bytes and hash remain authoritative."
        ),
        "unknown_source_content_opened": False,
        "mixed_source_content_open_count": 0,
    }
    if len(unknown_rows) != 24 or len(non_registry_candidate_unknown) != 20 or len(registry_related_unknown) != 4:
        raise RuntimeError("temporal inventory count reconciliation changed")
    atomic_write_json(
        RESULT_ROOT / "temporal_source_inventory_reconciliation.json",
        temporal_inventory_reconciliation,
    )

    registry_sources = load_csv(RESULT_ROOT / "safe_registry_source_inventory.csv")
    for row in registry_sources:
        row["task_use"] = "IMPORT" if row["registry_source_status"] == "SAFE_REUSABLE" else "EXCLUDE_WITH_PROVENANCE"
        row["content_opened_in_fresh_execution"] = "true" if row["registry_source_status"] == "SAFE_REUSABLE" else "false"
    registry_source_fields = list(registry_sources[0].keys())
    write_csv(RESULT_ROOT / "registry_source_inventory.csv", registry_sources, registry_source_fields)
    registry_import_report = {
        "schema": "CANONICAL_RESEARCH_REGISTRY_IMPORT_REPORT_R1",
        "task": TASK,
        "status": "PASS_BOOTSTRAP_REQUIRED",
        "safe_seed_path": str(SEED),
        "safe_seed_sha256": SEED_SHA256,
        "safe_seed_rows_imported": 37,
        "task_contract_named_unresolved_families_added": 3,
        "research_entity_count_after_patch": len(decisions),
        "governance_manifest_entity_count_after_patch": 1,
        "canonical_entity_count_after_patch": len(decisions) + 1,
        "parallel_duplicate_registry_created": False,
        "excluded_registry_source_count": sum(row["task_use"] != "IMPORT" for row in registry_sources),
        "excluded_source_refs": [row["path"] for row in registry_sources if row["task_use"] != "IMPORT"],
        "realized_holdout_metric_values_imported": False,
        "information_family_mapping": (
            "Canonical registry information_family uses the granular feature/input source; "
            "the broader safe-seed branch cluster is preserved separately as research_branch_cluster."
        ),
        "responsibility_separation": {
            "research_registry": "IDENTITY_LIFECYCLE_EQUIVALENCE_AND_GOVERNANCE",
            "factor_registry": "SEPARATE_NOT_IMPORTED_UNCERTIFIED_SOURCE",
            "trial_ledger": "SEPARATE_NOT_IMPORTED_UNCERTIFIED_SOURCE",
        },
    }
    atomic_write_json(RESULT_ROOT / "registry_import_report.json", registry_import_report)

    equivalence_rows = build_equivalence_rows(inventory_rows, decisions_by_id)
    equivalence_fields = list(equivalence_rows[0].keys())
    write_csv(RESULT_ROOT / "reuse_and_equivalence_matrix.csv", equivalence_rows, equivalence_fields)
    grouped: dict[str, list[str]] = {}
    for row in inventory_rows:
        group = row["functional_equivalence_group"] or f"UNRESOLVED::{row['entity_id']}"
        grouped.setdefault(group, []).append(row["entity_id"])
    equivalence_groups = {
        "schema": "A2_FUNCTIONAL_EQUIVALENCE_GROUPS_R1",
        "inventory_sha256": inventory_sha,
        "groups": [
            {
                "group_id": group,
                "members": sorted(members),
                "exact_duplicate_members": sorted([
                    member for member in members
                    if decisions_by_id[member]["lifecycle_decision"] == "TOMBSTONE_EXACT_DUPLICATE"
                ]),
                "functional_redundancy_members": sorted([
                    member for member in members
                    if decisions_by_id[member]["lifecycle_decision"] == "TOMBSTONE_FUNCTIONAL_REDUNDANCY"
                ]),
            }
            for group, members in sorted(grouped.items())
        ],
        "new_similarity_threshold_created": False,
    }
    atomic_write_json(RESULT_ROOT / "equivalence_groups.json", equivalence_groups)

    redundancy_report = """# Redundancy evidence report

The frozen, temporally safe canonical branch seed supports two task-level tombstones. No similarity threshold, model, feature, or outcome-conditioned rule was created.

- `SEC_FUNDAMENTAL_CHANGE_R2_WRAPPER` is an exact duplicate of `SEC_FUNDAMENTAL_CHANGE`; the safe seed labels the wrapper `CLOSED_DUPLICATE` and `EXACT_DUPLICATE`. Decision: `TOMBSTONE_EXACT_DUPLICATE`.
- `TOP20_BOUNDARY_RECOVERY_RERANK` is functionally redundant with `NG8_TOP60_TO_TOP20_RERANK`; the safe seed labels the same information/action family `FUNCTIONAL_DUPLICATE`. Decision: `TOMBSTONE_FUNCTIONAL_REDUNDANCY`.

Model variants, policy-parameter variants, and partial overlaps are not automatically declared exact duplicates. Existing closed branches remain `CLOSED_PRIOR_UNCHANGED`; forward candidates remain `WAIT_FORWARD`; missing or temporally unsafe evidence remains `UNTESTABLE_*`.
"""
    atomic_write_bytes(RESULT_ROOT / "redundancy_evidence_report.md", redundancy_report.encode("utf-8"))

    matched_rows = build_matched_sample_rows(summary)
    write_csv(RESULT_ROOT / "matched_sample_coverage.csv", matched_rows, list(matched_rows[0].keys()))
    incrementality_rows = build_incrementality_rows(decisions, summary)
    write_csv(RESULT_ROOT / "conditional_incrementality_matrix.csv", incrementality_rows, list(incrementality_rows[0].keys()))
    cost_rows = build_cost_rows(summary)
    write_csv(RESULT_ROOT / "cost_and_turnover_matrix.csv", cost_rows, list(cost_rows[0].keys()))
    factor_rows = build_factor_rows()
    write_csv(RESULT_ROOT / "factor_exposure_matrix.csv", factor_rows, list(factor_rows[0].keys()))
    concentration_rows = build_concentration_rows(summary)
    write_csv(RESULT_ROOT / "contribution_concentration_matrix.csv", concentration_rows, ["grain", "measure", "value", "status"])

    component_decisions = {
        "schema": "A2_COMPONENT_DECISIONS_R1",
        "task": TASK,
        "execution": EXECUTION,
        "inventory_sha256": inventory_sha,
        "entity_count": len(decisions),
        "decision_counts": decision_counts,
        "economic_role_counts": role_counts,
        "minimum_system_conclusion": "PASS_NO_NONCORE_COMPONENT_CURRENTLY_JUSTIFIED",
        "decisions": decisions,
        "fresh_zero_read_counters": ZERO_READ_COUNTERS,
        "anti_bloat_counters": ANTI_BLOAT_COUNTERS,
    }
    atomic_write_json(RESULT_ROOT / "component_decisions.json", component_decisions)

    minimum_system = {
        "schema": "MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1",
        "task": TASK,
        "execution": EXECUTION,
        "final_status": "PASS_NO_NONCORE_COMPONENT_CURRENTLY_JUSTIFIED",
        "research_scope": "PRE2026_ONLY_NO_2026_SELECTION_OR_EVALUATION",
        "component_inventory_path": verified["inventory_manifest"]["inventory_path"],
        "component_inventory_sha256": inventory_sha,
        "component_decisions_path": str(RESULT_ROOT / "component_decisions.json"),
        "component_decisions_sha256": sha256_file(RESULT_ROOT / "component_decisions.json"),
        "parent_authoritative_fingerprint": PARENT_FINGERPRINT,
        "task_registry_context_path": str(RESULT_ROOT / "task_registry_context.json"),
        "task_registry_context_sha256": sha256_file(RESULT_ROOT / "task_registry_context.json"),
        "safe_registry_seed_path": str(SEED),
        "safe_registry_seed_sha256": SEED_SHA256,
        "core_components": ["RAW_A2_HGB_BASELINE"],
        "required_infrastructure": [
            "RAW_A2_TOP40_CHECKPOINT",
            "RAW_A2_BROAD_OOF_PREDICTIONS",
            "A2_TEMPORAL_PIT_FEATURE_CONTRACT",
            "A2_COST_NAV_REPLAY_ENGINE",
            "UNIFIED_FORWARD_CONTROL_PLANE",
        ],
        "currently_justified_noncore_components": [],
        "canonical_registry_entity_id": "MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1",
        "wait_forward_components": sorted([
            row["component_id"] for row in decisions if row["lifecycle_decision"] == "WAIT_FORWARD"
        ]),
        "parked_or_untestable_components": sorted([
            row["component_id"] for row in decisions
            if row["lifecycle_decision"].startswith("UNTESTABLE_")
            or row["lifecycle_decision"] == "PARK_MECHANISM_UNRESOLVED"
        ]),
        "tombstoned_components": sorted([
            row["component_id"] for row in decisions if row["lifecycle_decision"].startswith("TOMBSTONE_")
        ]),
        "closed_prior_unchanged_components": sorted([
            row["component_id"] for row in decisions if row["lifecycle_decision"] == "CLOSED_PRIOR_UNCHANGED"
        ]),
        "minimality_basis": [
            "Raw A2 remains the fixed authoritative core; this audit does not claim a new alpha identity.",
            "No noncore component has safe fixed matched-sample conditional incrementality evidence sufficient for current inclusion.",
            "Forward candidates are not promoted from historical evidence and remain WAIT_FORWARD.",
            "Missing specifications and temporally unsafe sources remain UNTESTABLE without negative inference.",
            "Required infrastructure is retained for identity, PIT, cost replay, and governance, not as separate alpha.",
        ],
        "parent_fixed_evidence": {
            "parent_decision": summary["final_decision"],
            "selection_assessment": summary["state_robustness"]["assessment"],
            "cost_assessment": summary["selection_cost_bridge"]["assessment"],
            "identity_changed_from_parent": summary["identity_assessment"]["changed_from_clean_r2"],
        },
        "limitations": [
            "Residual-score primary module is UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION.",
            "Matched-peer primary module is UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION.",
            "Some security-grain concentration diagnostics are UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE.",
            "Standalone 13F orthogonality is UNTESTABLE_TEMPORAL_SOURCE.",
            "The project-level 2026 holdout is historically exposed; no pristine-holdout claim is made.",
        ],
        "zero_read_counters": ZERO_READ_COUNTERS,
        "anti_bloat_counters": ANTI_BLOAT_COUNTERS,
    }
    atomic_write_json(RESULT_ROOT / "minimum_justified_system.json", minimum_system)

    diff_rows = []
    for row in decisions:
        changed = row["prior_lifecycle_status"] != row["lifecycle_decision"]
        diff_rows.append({
            "entity_id": row["component_id"],
            "base_lifecycle_status": row["prior_lifecycle_status"],
            "proposed_lifecycle_decision": row["lifecycle_decision"],
            "economic_role": row["economic_role"],
            "changed_from_safe_seed": str(changed).lower(),
            "change_kind": "TASK_DECISION_OVERLAY" if changed else "PRESERVE",
            "reason": row["decision_reason"],
        })
    write_csv(RESULT_ROOT / "registry_diff.csv", diff_rows, list(diff_rows[0].keys()))

    tombstone_ids = [row["component_id"] for row in decisions if row["lifecycle_decision"].startswith("TOMBSTONE_")]
    parked_ids = [
        row["component_id"] for row in decisions
        if row["lifecycle_decision"] == "PARK_MECHANISM_UNRESOLVED"
        or row["lifecycle_decision"].startswith("UNTESTABLE_")
    ]
    tombstone_plan = "# Tombstone and park plan\n\n"
    tombstone_plan += "Tombstones are governance lifecycle actions only; historical artifacts are preserved and no files are deleted.\n\n"
    tombstone_plan += "## Tombstone\n\n" + "\n".join(f"- `{value}`" for value in tombstone_ids) + "\n\n"
    tombstone_plan += "## Park or untestable\n\n" + "\n".join(f"- `{value}`" for value in parked_ids) + "\n\n"
    tombstone_plan += "Future proposals must be checked against canonical names, aliases, information family, mechanism, decision layer, and supersession/equivalence links. Renaming, R2/R3 suffixes, model swaps, small threshold changes, and information-family repackaging do not bypass a closed or tombstoned branch.\n"
    atomic_write_bytes(RESULT_ROOT / "tombstone_and_park_plan.md", tombstone_plan.encode("utf-8"))

    final_report = f"""# A2 minimum justified system and component incrementality audit R1

## Final status

`PASS_NO_NONCORE_COMPONENT_CURRENTLY_JUSTIFIED`

The minimum currently justified system is the frozen `RAW_A2_HGB_BASELINE` plus five required infrastructure identities. No noncore component has safe, fixed, matched-sample conditional-incrementality evidence sufficient for present inclusion. This is a successful uncertainty-reduction result, not a prompt to search for a more attractive survivor count.

## Execution provenance

- **EXECUTION_1** correctly failed closed as `HARD_BLOCKER_REQUIRED_PARENT_NOT_TERMINAL`.
- **EXECUTION_2** correctly stopped as `ANTI_BLOAT_ACCOUNTING_INCOMPLETE` because of a pytest staging directory later removed externally.
- **EXECUTION_3** correctly stopped as `HARD_BLOCKER_TEMPORAL_INTEGRITY_UNPROVEN` after a mixed registry source exposed two forbidden post-2025 model-evaluation metric values. Its preserved counters are realized-label reads `2`, model-evaluation reads `2`, outcome-derived metadata reads `2`, holdout peeks `1`, and 2026 economic-outcome reads `0`. No exposed value is reproduced or used here.
- **EXECUTION_4** is this fresh zero-read execution. Substantive research began only after the parent and Anti-Bloat gates passed and after the file-level temporal inventory, denylist, registry-source inventory, and outcome-blind component inventory were frozen.

The original blocker reports remain immutable provenance with the user-supplied SHA-256 values. Neither was used as research evidence.

## Temporal firewall

`risk_registry.json = DENYLISTED_MIXED_2026`. It was not opened, parsed, searched, sanitized, or hashed. Unknown and mixed physical sources were excluded before content access. The frozen inventory contains {len(decisions)} entities and has SHA-256 `{inventory_sha}`. Every fresh zero-read counter is `0`, including mixed-source content opens, holdout peeks, post-2025 realized-label/model-evaluation/outcome-derived metadata reads, and post-2025 return/NAV/P&L/IC/AUROC reads.

The project-level 2026 holdout is historically exposed. This audit makes no pristine-holdout claim and performs no 2026 optimization, selection, refit, economic evaluation, or holdout-based decision.

The frozen temporal manifest's `unknown_temporal_source_count=20` is a scoped count of non-registry candidate sources. The hash-bound physical inventory contains 24 unknown rows in total; the other four are registry-related physical rows: three registry sources separately listed in the registry-source inventory and the paired legacy-current manifest. `temporal_source_inventory_reconciliation.json` records this schema clarification without rewriting the frozen manifest.

## Research conclusion

Fixed parent evidence is positive in aggregate after existing cost, but only three of five fixed folds are positive, retained drawdown evidence is mixed, security-grain breadth is incomplete, and material systematic exposure remains. The parent alpha identity therefore remains inconclusive. The residual-score and matched-peer modules are `UNTESTABLE_MISSING_AUTHORITATIVE_SPECIFICATION`; the optional standalone 13F module is `UNTESTABLE_TEMPORAL_SOURCE`. None is negative evidence.

The two supported redundancy actions are `SEC_FUNDAMENTAL_CHANGE_R2_WRAPPER -> SEC_FUNDAMENTAL_CHANGE` (exact duplicate) and `TOP20_BOUNDARY_RECOVERY_RERANK -> NG8_TOP60_TO_TOP20_RERANK` (functional redundancy). Historical artifacts are not deleted.

Forward candidates remain `WAIT_FORWARD`; authoritative closed branches remain `CLOSED_PRIOR_UNCHANGED`; missing or unsafe evidence remains `UNTESTABLE_*`; unresolved mechanisms remain parked. No closed branch was reopened.

## Minimum justified system

- Core: `RAW_A2_HGB_BASELINE`.
- Required infrastructure: `RAW_A2_TOP40_CHECKPOINT`, `RAW_A2_BROAD_OOF_PREDICTIONS`, `A2_TEMPORAL_PIT_FEATURE_CONTRACT`, `A2_COST_NAV_REPLAY_ENGINE`, `UNIFIED_FORWARD_CONTROL_PLANE`.
- Currently justified noncore components: none.

Registry publication state and exact immutable snapshot identity are recorded in `registry_integration_report.json`; this report deliberately does not infer pointer state. The canonical registry stores governance identity and lifecycle only; never realized holdout metric values.

All Anti-Bloat counters are `0`; no feature, target, predictive model specification or fit, hyperparameter/threshold/RX/weight/subset/optimizer search, tradable component, dependency, or Harness modification was created.
"""
    atomic_write_bytes(RESULT_ROOT / "final_audit_report.md", final_report.encode("utf-8"))

    print(f"AUDIT_ENTITY_COUNT={len(decisions)}")
    print("FINAL_RESEARCH_STATUS=PASS_NO_NONCORE_COMPONENT_CURRENTLY_JUSTIFIED")
    print("MIXED_SOURCE_CONTENT_OPEN_COUNT=0")
    print("POST_2025_MODEL_EVALUATION_METRIC_READ_COUNT=0")
    return 0


def command_registry_patch(args: argparse.Namespace) -> int:
    verified = verify_audit_inputs()
    inventory_rows = verified["inventory_rows"]
    inventory_by_id = {row["entity_id"]: row for row in inventory_rows}
    component_decisions = load_json(RESULT_ROOT / "component_decisions.json")
    minimum_system_path = RESULT_ROOT / "minimum_justified_system.json"
    minimum_system = load_json(minimum_system_path)
    if component_decisions["inventory_sha256"] != verified["inventory_manifest"]["inventory_sha256"]:
        raise RuntimeError("component decisions are not bound to frozen inventory")
    if minimum_system["final_status"] != "PASS_NO_NONCORE_COMPONENT_CURRENTLY_JUSTIFIED":
        raise RuntimeError("minimum-system conclusion changed")

    operations: list[dict[str, Any]] = []
    for decision in sorted(component_decisions["decisions"], key=lambda row: row["component_id"]):
        row = inventory_by_id[decision["component_id"]]
        aliases = json.loads(row["aliases_json"] or "[]")
        parents = json.loads(row["parent_entity_ids_json"] or "[]")
        # The frozen inventory preserves the structural seed payload exactly,
        # including legacy fields that may carry multiple paths separated by
        # ``|``.  Registry references must be individually resolvable, so split
        # only at patch-construction time without rewriting the frozen input.
        artifacts = sorted({
            ref
            for packed_ref in json.loads(row["authoritative_artifact_refs_json"] or "[]")
            for ref in pipe_list(packed_ref)
        })
        canonical_information_family = registry_information_family(row)
        information_source_fingerprint = sha256_bytes(canonical_json({
            "information_source": row["information_source"],
            "information_family": canonical_information_family,
            "feature_input_family": row["feature_input_family"],
        }).encode("utf-8"))
        mechanism_fingerprint = sha256_bytes(canonical_json({
            "target_definition": row["target_definition"],
            "outcome_horizon": row["outcome_horizon"],
            "model_family": row["model_family"],
            "portfolio_action": row["portfolio_action"],
            "decision_layer": row["decision_layer"],
        }).encode("utf-8"))
        limitations = sorted({
            value for value in (
                row["temporal_evidence_limitations"],
                decision["temporal_evidence_limitations"],
            ) if value
        })
        entity = {
            "entity_id": decision["component_id"],
            "canonical_name": decision["canonical_name"],
            "aliases": aliases,
            "entity_type": row["entity_type_candidate"],
            "status": registry_status_for(row, decision["lifecycle_decision"]),
            "specification_fingerprint": row["specification_fingerprint"],
            "information_source_fingerprint": information_source_fingerprint,
            "mechanism_fingerprint": mechanism_fingerprint,
            "decision_layer": row["decision_layer"],
            "evidence_source_temporal_status": decision["evidence_status"],
            "excluded_source_refs": decision["excluded_source_refs"],
            "temporal_evidence_limitations": limitations,
            "factor_ledger_ref": None,
            "trial_ledger_ref": None,
            "trial_ledger_failure_row_count": None,
            "trial_ledger_status": "UNAVAILABLE_OR_NOT_IMPORTED_TEMPORAL_FIREWALL",
            "post_2025_observation_count": 0,
            "minimum_system_manifest_ref": str(minimum_system_path),
            "parent_entity_id": parents[0] if parents else None,
            "parent_entity_ids": parents,
            "information_source": row["information_source"],
            "information_family": canonical_information_family,
            "research_branch_cluster": row["information_family"],
            "economic_thesis": row["economic_thesis"],
            "target_definition": row["target_definition"],
            "outcome_horizon": row["outcome_horizon"],
            "feature_input_family": row["feature_input_family"],
            "model_family": row["model_family"],
            "portfolio_action": row["portfolio_action"],
            "mechanism_family": row["functional_equivalence_group"],
            "economic_role": decision["economic_role"],
            "lifecycle_decision": decision["lifecycle_decision"],
            "lifecycle_reason": decision["decision_reason"],
            "prior_lifecycle_status": row["prior_lifecycle_status"],
            "prior_reuse_decision": row["prior_reuse_decision"],
            "prior_negative_evidence": row["prior_negative_evidence"],
            "incrementality_status": decision["incrementality_status"],
            "equivalence_class": decision["equivalence_class"],
            "equivalent_to": decision["duplicate_with"] or None,
            "superseded_by": None,
            "reuse_decision": row["prior_reuse_decision"],
            "canonical_identity": row["canonical_identity"],
            "code_fingerprint": row["code_fingerprint"],
            "data_contract": row["data_contract"],
            "cost_contract": row["cost_contract"],
            "temporal_contract": row["temporal_contract"],
            "evaluation_start": None,
            "evaluation_end": "2025-12-31" if decision["component_id"] == "RAW_A2_HGB_BASELINE" else None,
            "authoritative_artifact_refs": artifacts,
            "source_task": TASK,
            "source_execution": EXECUTION,
            "source_registry": row["source_registry_path"],
            "source_row_sha256": row["source_row_sha256"],
            "project_holdout_exposed": True,
        }
        operation = {
            "record_type": "OPERATION",
            "op": "add_entity",
            "entity": entity,
        }
        operations.append(operation)

    minimum_manifest_sha = sha256_file(minimum_system_path)
    operations.append({
        "record_type": "OPERATION",
        "op": "add_entity",
        "entity": {
            "entity_id": "MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1",
            "canonical_name": "MINIMUM_JUSTIFIED_SYSTEM_MANIFEST_R1",
            "aliases": ["MINIMUM_JUSTIFIED_SYSTEM", "A2_MINIMUM_SYSTEM_R1"],
            "entity_type": "MINIMUM_SYSTEM_MANIFEST",
            "status": "ACTIVE",
            "specification_fingerprint": minimum_manifest_sha,
            "information_source_fingerprint": sha256_bytes(canonical_json({
                "task": TASK,
                "source": "FROZEN_COMPONENT_DECISIONS_AND_SAFE_PRE2026_PARENT_EVIDENCE",
            }).encode("utf-8")),
            "mechanism_fingerprint": sha256_bytes(canonical_json({
                "manifest_schema": minimum_system["schema"],
                "decision": minimum_system["final_status"],
            }).encode("utf-8")),
            "decision_layer": "RESEARCH_GOVERNANCE",
            "evidence_source_temporal_status": "TASK_GENERATED_SAFE_GOVERNANCE_ONLY",
            "excluded_source_refs": [str(DENYLISTED_RISK_REGISTRY)],
            "temporal_evidence_limitations": minimum_system["limitations"],
            "factor_ledger_ref": None,
            "trial_ledger_ref": None,
            "trial_ledger_failure_row_count": None,
            "trial_ledger_status": "NOT_APPLICABLE_GOVERNANCE_MANIFEST",
            "post_2025_observation_count": 0,
            "minimum_system_manifest_ref": str(minimum_system_path),
            "parent_entity_id": "RAW_A2_HGB_BASELINE",
            "parent_entity_ids": [
                "RAW_A2_HGB_BASELINE",
                "RAW_A2_TOP40_CHECKPOINT",
                "RAW_A2_BROAD_OOF_PREDICTIONS",
                "A2_TEMPORAL_PIT_FEATURE_CONTRACT",
                "A2_COST_NAV_REPLAY_ENGINE",
                "UNIFIED_FORWARD_CONTROL_PLANE",
            ],
            "economic_role": "INFRASTRUCTURE",
            "lifecycle_decision": "KEEP_CORE",
            "lifecycle_reason": "Query anchor for the validated minimum-system manifest; not a tradable component.",
            "prior_lifecycle_status": "NOT_APPLICABLE_NEW_GOVERNANCE_MANIFEST",
            "incrementality_status": "NOT_APPLICABLE_GOVERNANCE_MANIFEST",
            "equivalence_class": "AUTHORITATIVE_GOVERNANCE_MANIFEST",
            "equivalent_to": None,
            "superseded_by": None,
            "reuse_decision": "REUSE_CANONICAL_MANIFEST",
            "canonical_identity": minimum_manifest_sha,
            "code_fingerprint": sha256_file(Path(__file__)),
            "data_contract": "NO_ECONOMIC_DATA_GOVERNANCE_ONLY",
            "cost_contract": "NOT_APPLICABLE",
            "temporal_contract": "PRE2026_EVIDENCE_ONLY_NO_REALIZED_HOLDOUT_VALUES",
            "evaluation_start": None,
            "evaluation_end": "2025-12-31",
            "authoritative_artifact_refs": [
                str(minimum_system_path),
                str(RESULT_ROOT / "component_decisions.json"),
            ],
            "minimum_system_manifest_sha256": minimum_manifest_sha,
            "source_task": TASK,
            "source_execution": EXECUTION,
            "source_registry": "TASK_GENERATED_CANONICAL_GOVERNANCE_ENTITY",
            "source_row_sha256": minimum_manifest_sha,
            "project_holdout_exposed": True,
            "tradable_component": False,
        },
    })

    logical_operations = [
        {key: value for key, value in operation.items() if key != "record_type"}
        for operation in operations
    ]
    operations_sha = sha256_bytes(canonical_json(logical_operations).encode("utf-8"))
    validation_binding: dict[str, Any] = {
        "status": args.validation_status,
        "post_2025_observation_count": 0,
    }
    review_binding: dict[str, Any] = {
        "status": args.review_status,
        "independent": args.review_status == "PASS",
        "reviewer": args.reviewer,
    }
    if args.schema_dryrun:
        if (
            args.validation_status != "PASS"
            or args.review_status != "PASS"
            or args.reviewer != "SCHEMA_DRYRUN_INDEPENDENT"
            or "schema_dryrun" not in Path(args.output).stem
            or args.validation_artifact
            or args.review_artifact
        ):
            raise RuntimeError("invalid schema-dryrun registry-patch gate declaration")
    elif args.validation_status == "PASS" or args.review_status == "PASS":
        if args.validation_status != "PASS" or args.review_status != "PASS":
            raise RuntimeError("formal registry patch requires both validation and review PASS")
        expected_validation = (RESULT_ROOT / "final_validation.json").resolve()
        expected_review = (RESULT_ROOT / "final_independent_review.md").resolve()
        supplied_validation = Path(args.validation_artifact or "").resolve()
        supplied_review = Path(args.review_artifact or "").resolve()
        if supplied_validation != expected_validation or supplied_review != expected_review:
            raise RuntimeError("formal registry patch must bind exact final validation and review artifacts")
        if not expected_validation.is_file() or not expected_review.is_file():
            raise RuntimeError("formal registry patch gate artifact is missing")
        validation_binding.update({
            "artifact_path": str(expected_validation),
            "artifact_sha256": sha256_file(expected_validation),
        })
        review_binding.update({
            "artifact_path": str(expected_review),
            "artifact_sha256": sha256_file(expected_review),
        })

    header = {
        "record_type": "PATCH_HEADER",
        "schema_version": 1,
        "task": TASK,
        "execution": EXECUTION,
        "patch_purpose": "AUDITED_INVENTORY_BOOTSTRAP",
        "expected_base_head_sha256": "GENESIS",
        "pinned_bootstrap_source_sha256": SEED_SHA256,
        "pinned_outcome_blind_inventory_sha256": verified["inventory_manifest"]["inventory_sha256"],
        "operations_sha256": operations_sha,
        "operation_count": len(operations),
        "author": TASK,
        "event_time_utc": None,
        "validation": validation_binding,
        "independent_review": review_binding,
    }
    output = RESULT_ROOT / args.output
    lines = [canonical_json(header), *(canonical_json(operation) for operation in operations)]
    atomic_write_bytes(output, ("\n".join(lines) + "\n").encode("utf-8"))
    atomic_write_json(RESULT_ROOT / f"{output.stem}_manifest.json", {
        "schema": "CANONICAL_RESEARCH_REGISTRY_PATCH_MANIFEST_R1",
        "patch_path": str(output),
        "patch_sha256": sha256_file(output),
        "patch_purpose": "AUDITED_INVENTORY_BOOTSTRAP",
        "operations_sha256": operations_sha,
        "operation_count": len(operations),
        "validation_status": args.validation_status,
        "independent_review_status": args.review_status,
        "expected_base_head_sha256": "GENESIS",
        "contains_realized_holdout_metric_values": False,
        "post_2025_observation_count": 0,
        "validation_artifact_sha256": validation_binding.get("artifact_sha256"),
        "independent_review_artifact_sha256": review_binding.get("artifact_sha256"),
    })
    print(f"REGISTRY_PATCH={output}")
    print(f"REGISTRY_PATCH_OPERATION_COUNT={len(operations)}")
    print(f"REGISTRY_PATCH_OPERATIONS_SHA256={operations_sha}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    outcome_blind = subparsers.add_parser("outcome-blind")
    outcome_blind.set_defaults(func=command_outcome_blind)
    audit = subparsers.add_parser("audit")
    audit.set_defaults(func=command_audit)
    registry_patch = subparsers.add_parser("registry-patch")
    registry_patch.add_argument("--output", default="registry_patch_candidate.jsonl")
    registry_patch.add_argument("--validation-status", choices=("PENDING", "PASS"), default="PENDING")
    registry_patch.add_argument("--review-status", choices=("PENDING", "PASS"), default="PENDING")
    registry_patch.add_argument("--reviewer", default="UNASSIGNED")
    registry_patch.add_argument("--validation-artifact")
    registry_patch.add_argument("--review-artifact")
    registry_patch.add_argument("--schema-dryrun", action="store_true")
    registry_patch.set_defaults(func=command_registry_patch)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
