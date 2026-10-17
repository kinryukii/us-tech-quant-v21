"""Exact metadata-only registry review for the authorized consensus cash study.

This module reads bounded, pinned control records and code custody only. It does
not read research observations, grant fitting authority, or mutate the registry.
"""
from __future__ import annotations

import json
from pathlib import Path

ID = "CONSENSUS100_PTO_3000_20261012_R1"
PARENT = "V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6"
BASE = Path("D:/us-tech-quant-results/_maintenance") / ID
INFO_SHA = "3a09663eb3ab3cf0c01b35a7c6b8b610853f59e18acc87692b306ff798bc6d9a"
INFO_FAMILY = "existing-pre2026-frozen-feature-labels-raw-open-close-cash-entitlement-inputs-source-publication-revision-unavailable-no-new-information-source-claim"
CHANGE = "EXTEND_EXISTING_CONSENSUS_UNIVERSE_AND_SMALL_CASH_COST_OBJECTIVE"
MODE = "FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY"
REVIEW_SCOPE = {
    "research_id": ID,
    "parent_entity_id": PARENT,
    "parent_status": "OPEN",
    "parent_row_hash": "c0025d618f14e3036d69ff053c1038074dfda9da6f1b28b28991d4229f86d533",
    "spec_ref": {"path": str(BASE / "AUTHORIZED_RESEARCH_SPEC.json"), "sha256": "9e7ac9f73d61a613eae5988e477d8825bb52ac112a422f7948bf885f1abc853b"},
    "proposal_ref": {"path": str(BASE / "AUTHORIZED_IDENTITY_PROPOSAL.json"), "sha256": "38d3700f534993460ba9e2ef2661365c46bea5ff5addc28a83dfc024f8396ca4"},
    "human_ref": {"path": str(BASE / "HUMAN_SOURCE_SCOPE.json"), "sha256": "f7edb7733bcca60741ac092b8d2b639253093a275a358685031683f9d819aa30"},
    "account_ref": {"path": str(BASE / "ACCOUNT_SOURCE_SCOPE.json"), "sha256": "c944665d322368bdb93338f46f370cd8654ac1663c3d8842f81dcc550c306f70"},
}


def _control(ref):
    from scripts.maintenance import research_registry as rr
    path = Path(ref["path"])
    if (not path.is_absolute() or path.drive.upper() in {"E:", "F:"}
            or path.resolve(strict=True) != path.absolute() or path.stat().st_size > 65536
            or rr.sha256_file(path) != ref["sha256"]):
        raise rr.RegistryError("CONSENSUS_REVIEW_CONTROL_CUSTODY_REQUIRED")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise rr.RegistryError("CONSENSUS_REVIEW_CONTROL_OBJECT_REQUIRED")
    return value


def candidate_entity():
    """Return this exact reviewed OPEN metadata candidate; no admission or fit."""
    from scripts.maintenance import research_registry as rr
    scope = REVIEW_SCOPE
    proposal = _control(scope["proposal_ref"])
    candidate = rr._candidate(proposal["candidate"])
    candidate.update(entity_type="RESEARCH_BRANCH", status="OPEN", parent_entity_id=PARENT,
        evidence_source_temporal_status="FROZEN_PRE2026_HISTORY_UNKNOWN_VINTAGE_MECHANISM_ONLY",
        excluded_source_refs=["FAST3_CONFIRMATION", "TEST2026_BEFORE_COMPLETE_FREEZE", "YEAR2027_AND_LATER"],
        temporal_evidence_limitations=["HISTORICAL_PUBLICATION_AND_REVISION_UNKNOWN",
            "EXISTING_A2_EXPOSURE_RETAINED", "INITIAL_PUBLIC_FILINGS_NO_AMENDMENT_BACKFILL"],
        post_2025_observation_count=0,
        metadata={"scientific_identity": "DYNAMIC_CONSENSUS_AND_SETTLED_CASH_FRICTION_PTO",
            "source_policy": MODE, "information_family": INFO_FAMILY,
            "spec_custody_ref": scope["spec_ref"], "human_scope_ref": scope["human_ref"],
            "account_scope_ref": scope["account_ref"], "fit_authority": False,
            "formal_freeze_authority": False, "strict_PIT_promotion_eligible": False,
            "quote_qualified": False, "account_qualification_granted": False,
            "broker_action_allowed": False, "source_gate_required": True,
            "prior_artifact_reopened": False, "legacy_exposure_retained": True})
    return candidate


def validate_scope(operation, normalized, entity_map):
    """Validate same-source scientific differences and exact review custody."""
    from scripts.maintenance import research_registry as rr
    scope = REVIEW_SCOPE
    proposal, spec, human, account = [_control(scope[k]) for k in
        ("proposal_ref", "spec_ref", "human_ref", "account_ref")]
    candidate = candidate_entity()
    parent = entity_map.get(PARENT, {})
    expected = rr._normalize_entity(candidate)
    if (normalized["row_hash"] != expected["row_hash"] or operation.get("change_type") != CHANGE
            or operation.get("parent_entity_id") != PARENT or operation["entity"].get("aliases")
            or parent.get("row_hash") != scope["parent_row_hash"] or parent.get("status") != "OPEN"
            or candidate["information_source_fingerprint"] != INFO_SHA
            or parent.get("information_source_fingerprint") != INFO_SHA
            or candidate.get("decision_layer") != "joint-portfolio-policy"
            or proposal.get("parent_entity_id") != PARENT):
        raise rr.RegistryError("CONSENSUS_REVIEW_EXACT_SAME_SOURCE_CHILD_REQUIRED")
    if (rr.sha256_value(spec) != candidate["specification_fingerprint"]
            or spec.get("task_id") != ID or spec.get("source_policy") != MODE
            or spec.get("strict_PIT_promotion_eligible") is not False
            or spec["universe"].get("dynamic") is not True or spec["universe"].get("top_n") != 100
            or spec["universe"].get("selection_rule") != "MANAGER_COUNT_WEIGHT_SUM"
            or spec["universe"].get("filing_scope") != "INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL"
            or spec["universe"].get("held_outside_pool") != "KEEP_NO_NEW_BUY"
            or spec["training_boundary"].get("exclusive") != "2026-01-01"
            or spec.get("fusion_input") != "CHRONOLOGICAL_OOF_ONLY"
            or spec["source_gate"].get("latest_human_scope") != human.get("human_latest_quote_scope")
            or human.get("source") != "CURRENT_HUMAN_CHAT_MESSAGES" or human.get("task_id") != ID):
        raise rr.RegistryError("CONSENSUS_REVIEW_SCIENTIFIC_SCOPE_MISMATCH")
    required = {"task_id": ID, "initial_cash_usd": 3000, "cash_only": True, "fractional": True,
        "settlement_rule": "ORDINARY_TRADE_T_PLUS_2_BEFORE_2024_05_28_T_PLUS_1_SINCE_WITH_COMPLETE_EXCHANGE_SESSION_CALENDAR",
        "sale_proceeds": "NAV_ASSET_UNTIL_SETTLED_NOT_BUYING_POWER", "base_one_way_all_in_bps": 10,
        "other_one_way_all_in_bps": [5, 25], "fixed_ticket_stress_usd": .5,
        "normal_min_trade_usd": 5, "fee_owner": "SINGLE_FEE_FOR_NOTIONAL_FOR_QUOTE_AND_FILL",
        "broker_fees_known": False, "broker_fill_at_open_certified": False,
        "existing_source_unknowns_retained": True}
    if any(account.get(k) != v or type(account.get(k)) is not type(v) for k, v in required.items()):
        raise rr.RegistryError("CONSENSUS_REVIEW_SETTLED_CASH_COST_SCOPE_MISMATCH")
    custody = [scope["proposal_ref"], scope["account_ref"],
        {"path": account["account_source_ref"], "sha256": account["account_source_sha256"]},
        {"path": account["account_preflight_ref"], "sha256": account["account_preflight_sha256"]}]
    return {**scope, "change_type": CHANGE, "candidate_row_hash": expected["row_hash"],
        "contract_path": scope["spec_ref"]["path"], "contract_sha256": scope["spec_ref"]["sha256"],
        "request_path": scope["human_ref"]["path"], "request_sha256": scope["human_ref"]["sha256"],
        "automatic_reasons": ["existing information source is reused without enough non-redundancy evidence"],
        "scientific_identity": "DYNAMIC_CONSENSUS_AND_SETTLED_CASH_FRICTION_PTO",
        "resolution_kind": "EXACT_CONSENSUS_FROZEN_HISTORY_METADATA_REVIEW",
        "human_premise_field": "frozen_history_scope_without_future_functions",
        "human_record_filename": "CONSENSUS100_REGISTRY_HUMAN_AUTHORIZATION.json",
        "review_record_filename": "CONSENSUS100_REGISTRY_INDEPENDENT_REVIEW.json",
        "independent_review_kind": "INDEPENDENT_CONSENSUS_REGISTRY_REVIEW",
        "nonredundancy_basis": "DYNAMIC_CONSENSUS_POOL_AND_SETTLED_CASH_COST_OBJECTIVE",
        "additional_custody": [{**ref, "maximum_bytes": 65536} for ref in custody],
        "additional_binding": {"account_scope_sha256": scope["account_ref"]["sha256"],
            "specification_fingerprint": candidate["specification_fingerprint"],
            "information_source_fingerprint": INFO_SHA,
            "mechanism_fingerprint": candidate["mechanism_fingerprint"],
            "quote_qualified": False, "account_qualification_granted": False, "broker_action_allowed": False}}


# Exact authorized continuation only; the original R1 review scope stays intact.
CONTINUATION_ID = "CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2"
CONTINUATION_RUN = Path("D:/us-tech-quant-backtests") / CONTINUATION_ID / "20261012T025603+0000_4a58260e"
CONTINUATION_CHANGE = "PRE2026_SOURCE_COMPLETION_AND_CERTIFIED_ZERO_ABSTENTION"
CONTINUATION_REVIEW_SCOPE = {
    "research_id": CONTINUATION_ID, "parent_entity_id": ID, "parent_status": "OPEN",
    "parent_row_hash": "46da9c2607c7a7a2058e3f80c859cd45e3011b9763505af69d510a52f51e12d3",
    "continuation_ref": {"path": str(CONTINUATION_RUN / "CONTINUATION_SCOPE.json"),
        "sha256": "0a0220d73bffef0db6b427a79a1e10abd34b3bf9725d68ebe5f6366369a5da41"},
    "account_convention_ref": {"path": str(CONTINUATION_RUN / "ACCOUNT_CONVENTION_SCOPE.json"),
        "sha256": "71ccae1d26b09cd972747a1876f7750b940e5b133abac5010c0a7bf28045eba8"},
}
CONTINUATION_SCIENCE = "PRE2026_SOURCE_COMPLETION_CERTIFIED_ZERO_ABSTENTION_AND_FRACTIONAL_STOCK_CLAIM_CONVENTION"


def _continuation_contract():
    scope = CONTINUATION_REVIEW_SCOPE
    return {"continuation": _control(scope["continuation_ref"]),
            "account_convention": _control(scope["account_convention_ref"])}


def continuation_candidate_entity():
    """Build the exact child proposal from two pinned metadata scopes; no admit."""
    from scripts.maintenance import research_registry as rr
    scope = CONTINUATION_REVIEW_SCOPE
    contract = _continuation_contract()
    return rr._candidate({
        "entity_id": CONTINUATION_ID, "canonical_name": CONTINUATION_ID, "aliases": [],
        "parent_entity_id": ID, "entity_type": "RESEARCH_BRANCH", "status": "OPEN",
        "decision_layer": "joint-portfolio-policy", "information_source_fingerprint": INFO_SHA,
        "information_family": INFO_FAMILY, "specification_fingerprint": rr.sha256_value(contract),
        "mechanism": {"parent_scientific_identity": "DYNAMIC_CONSENSUS_AND_SETTLED_CASH_FRICTION_PTO",
            "named_fusion": "nnls_zero_abstain", "original_m035_unchanged": True,
            "stock_claim_convention": "BENEFICIAL_FRACTIONAL_ECONOMIC_INTEREST_RESEARCH_ASSUMPTION",
            "out_of_pool_child": "CAUSAL_FULL_EXIT_WITH_SINGLE_FEES_AND_SETTLEMENT"},
        "evidence_source_temporal_status": "FROZEN_PRE2026_HISTORY_UNKNOWN_VINTAGE_MECHANISM_ONLY",
        "excluded_source_refs": ["FAST3_CONFIRMATION", "TEST2026_BEFORE_COMPLETE_FREEZE", "YEAR2027_AND_LATER"],
        "temporal_evidence_limitations": ["HISTORICAL_PUBLICATION_AND_REVISION_UNKNOWN",
            "EXISTING_A2_EXPOSURE_RETAINED", "INITIAL_PUBLIC_FILINGS_NO_AMENDMENT_BACKFILL",
            "NEW_ECONOMIC_SOURCE_FACTS_REQUIRE_SEPARATE_QUALIFICATION"],
        "post_2025_observation_count": 0,
        "metadata": {"scientific_identity": CONTINUATION_SCIENCE,
            "source_policy": MODE, "information_family": INFO_FAMILY,
            "continuation_scope_ref": scope["continuation_ref"],
            "account_convention_scope_ref": scope["account_convention_ref"],
            "fit_authority": False, "formal_freeze_authority": False,
            "strict_PIT_promotion_eligible": False, "quote_qualified": False,
            "account_qualification_granted": False, "broker_action_allowed": False,
            "source_gate_required": True, "prior_artifact_reopened": False,
            "legacy_exposure_retained": True, "original_failure_preserved": True,
            "distinct_information_source_claim": False, "prior_fit_units": 1098,
            "global_original_fit_unit_limit": 10000}})


def validate_continuation_scope(operation, normalized, entity_map):
    """Only the named R2 identity can request an independent metadata review."""
    from scripts.maintenance import research_registry as rr
    scope = CONTINUATION_REVIEW_SCOPE
    contract = _continuation_contract(); continuation = contract["continuation"]
    account = contract["account_convention"]
    candidate = continuation_candidate_entity(); expected = rr._normalize_entity(candidate)
    parent = entity_map.get(ID, {})
    if (normalized.get("row_hash") != expected["row_hash"]
            or operation.get("change_type") != CONTINUATION_CHANGE
            or operation.get("parent_entity_id") != ID or operation["entity"].get("aliases")
            or parent.get("row_hash") != scope["parent_row_hash"] or parent.get("status") != "OPEN"
            or parent.get("information_source_fingerprint") != INFO_SHA
            or parent.get("decision_layer") != "joint-portfolio-policy"):
        raise rr.RegistryError("CONSENSUS_CONTINUATION_EXACT_OPEN_PARENT_REQUIRED")
    if (continuation.get("schema") != "CONSENSUS_PRE2026_SOURCE_COMPLETION_CONTINUATION_SCOPE_R1"
            or continuation.get("status") != "AUTHORIZED_REPAIR_BRANCH_PENDING_SOURCE_PROOF_AND_REVIEWED_FIT_FREEZE"
            or continuation.get("task_id") != ID or continuation.get("research_id") != CONTINUATION_ID
            or continuation.get("parent_research_id") != ID or Path(continuation.get("run", "")) != CONTINUATION_RUN
            or continuation.get("original_artifacts_overwritten") is not False
            or continuation.get("broker_action_allowed") is not False
            or continuation.get("source_qualification") != "PENDING_NEW_PRE2026_ECONOMIC_FACTS_NO_REPLAY_AUTHORITY_YET"
            or not isinstance(continuation.get("human_instruction"), str) or not continuation["human_instruction"].strip()):
        raise rr.RegistryError("CONSENSUS_CONTINUATION_CONTRACT_REQUIRED")
    required = {"fit_preprocess_calibration_selection_before": "2026-01-01",
        "FAST3_Confirmation_access": False, "existing_A2_exposure_retained": True,
        "fresh_blind_holdout": False, "strict_PIT_certified": False,
        "no_new_2026_sample_or_outcome_read_authorized": True, "source_vintage": "UNKNOWN_RETAINED"}
    budget = {"global_original_fit_unit_limit": 10000, "new_fusion_slots": 4,
        "no_fit_budget_reset": True, "no_new_seed_horizon_or_asset_pool_search": True, "prior_fit_units": 1098}
    science = {"new_named_fusion_candidate": "nnls_zero_abstain", "original_m035_zero_failure_preserved": True,
        "zero_rule": "Only exact solver zero with strictly certified negative training XTy outside floating uncertainty -> explicit zero forecast; otherwise reject. Positive normalized rule unchanged."}
    for values, desired in ((continuation.get("boundaries", {}), required),
                            (continuation.get("budget", {}), budget),
                            (continuation.get("scientific_change", {}), science)):
        if any(values.get(k) != v or type(values.get(k)) is not type(v) for k, v in desired.items()):
            raise rr.RegistryError("CONSENSUS_CONTINUATION_BOUNDARY_OR_SCIENCE_DRIFT")
    if (account.get("schema") != "CONSENSUS_SOURCE_COMPLETION_ACCOUNT_CONVENTION_R1"
            or account.get("status") != "FROZEN_BEFORE_NEW_ACCOUNT_REPLAY_OR_SELECTION"
            or account.get("task_id") != ID or account.get("research_id") != CONTINUATION_ID
            or account.get("continuation_scope_ref") != scope["continuation_ref"]
            or account.get("selection_outcomes_seen_before_this_freeze") is not False
            or account.get("source_policy") != MODE or account.get("strict_pit_certification") is not False
            or account.get("time_boundary", {}).get("all_fit_selection_and_replay_observations_before") != "2026-01-01"
            or account.get("time_boundary", {}).get("actual_2026_payment_or_fx_realization_read_or_used") is not False
            or account.get("account") != {"cash_account": True, "currency": "USD", "fractional_shares": True, "initial_usd": 3000}
            or account.get("stock_distribution_research_convention", {}).get("mode") != "BENEFICIAL_FRACTIONAL_ECONOMIC_INTEREST_RESEARCH_ASSUMPTION"
            or account.get("stock_distribution_research_convention", {}).get("raw_price_adjustment_factor_as_share_ratio_allowed") is not False
            or account.get("out_of_pool_child_exit", {}).get("future_pool_membership_read") is not False
            or account.get("out_of_pool_child_exit", {}).get("synthetic_zero_alpha_allowed") is not False):
        raise rr.RegistryError("CONSENSUS_CONTINUATION_ACCOUNT_CONVENTION_REQUIRED")
    custody = continuation.get("parent_custody", {})
    if (custody.get("parent_fit_units") != 1098 or custody.get("parent_fit_log_events") != 1699
            or Path(custody.get("run", "")) != Path("D:/us-tech-quant-backtests") / ID / "20261011T170254+0000_bf592a79"):
        raise rr.RegistryError("CONSENSUS_CONTINUATION_PARENT_AND_BUDGET_REQUIRED")
    refs = []
    for key, ref in custody.items():
        if key.endswith("_ref"):
            if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                    or not Path(str(ref["path"])).is_absolute() or not rr.HEX_SHA256.fullmatch(str(ref["sha256"]))):
                raise rr.RegistryError("CONSENSUS_CONTINUATION_PARENT_REF_REQUIRED")
            refs.append({**ref, "maximum_bytes": 16 * 1024 * 1024})
    if {key for key in custody if key.endswith("_ref")} != {
            "account_freeze_ref", "authorized_spec_ref", "fusion_freeze_ref", "historical_fusion_adapter_archive_ref",
            "historical_owner_archive_ref", "membership_ref", "parent_fit_log_ref", "physical_binding_ref",
            "predictor_freeze_ref", "terminal_audit_ref"}:
        raise rr.RegistryError("CONSENSUS_CONTINUATION_COMPLETE_PARENT_CUSTODY_REQUIRED")
    return {**scope, "change_type": CONTINUATION_CHANGE, "candidate_row_hash": expected["row_hash"],
        "contract_path": scope["continuation_ref"]["path"], "contract_sha256": scope["continuation_ref"]["sha256"],
        "request_path": scope["continuation_ref"]["path"], "request_sha256": scope["continuation_ref"]["sha256"],
        "automatic_reasons": ["existing information source is reused without enough non-redundancy evidence"],
        "scientific_identity": CONTINUATION_SCIENCE,
        "resolution_kind": "EXACT_CONSENSUS_CONTINUATION_METADATA_REVIEW",
        "human_premise_field": "pre2026_source_completion_and_new_zero_abstention_identity",
        "human_record_filename": "CONSENSUS100_CONTINUATION_REGISTRY_HUMAN_AUTHORIZATION.json",
        "review_record_filename": "CONSENSUS100_CONTINUATION_REGISTRY_INDEPENDENT_REVIEW.json",
        "independent_review_kind": "INDEPENDENT_CONSENSUS_CONTINUATION_REGISTRY_REVIEW",
        "nonredundancy_basis": "CERTIFIED_ZERO_ABSTENTION_AND_FROZEN_STOCK_CLAIM_CONVENTION_WITH_SAME_INFORMATION_LIMITS",
        "additional_custody": [{**scope["account_convention_ref"], "maximum_bytes": 65536}, *refs],
        "additional_binding": {"continuation_scope_sha256": scope["continuation_ref"]["sha256"],
            "account_convention_scope_sha256": scope["account_convention_ref"]["sha256"],
            "specification_fingerprint": candidate["specification_fingerprint"],
            "information_source_fingerprint": INFO_SHA, "mechanism_fingerprint": candidate["mechanism_fingerprint"],
            "prior_fit_units": 1098, "global_original_fit_unit_limit": 10000,
            "original_failure_preserved": True, "distinct_information_source_claim": False,
            "quote_qualified": False, "account_qualification_granted": False, "broker_action_allowed": False}}


def continuation_proposal():
    """Unreviewed proposal only: admission and all runtime authority remain off."""
    return {"candidate": continuation_candidate_entity(), "parent_entity_id": ID,
            "change_type": CONTINUATION_CHANGE}


def continuation_review_requirements(registry_root):
    """Return metadata preflight and exact evidence binding; never self-review."""
    return _review_requirements(registry_root, continuation_proposal(), validate_continuation_scope,
                                CONTINUATION_ID, CONTINUATION_SCIENCE)


def _review_requirements(registry_root, proposal, validator, research_id, science):
    """Reuse the original single-operation evidence protocol; never sign/admit."""
    from scripts.maintenance import research_registry as rr
    manifest, entities, aliases = rr._load_snapshot_for_read(Path(registry_root), None)
    head = manifest["snapshot_sha256"]
    decision = rr.evaluate_proposal(proposal, entities, aliases, head_sha256=head)
    entity = proposal["candidate"]
    operation = {"op": "add_entity", "entity": entity, "parent_entity_id": proposal["parent_entity_id"],
                 "change_type": proposal["change_type"]}
    checked = validator(operation, rr._normalize_entity(entity), {r["entity_id"]: r for r in entities})
    binding = {"schema_version": 1, "research_id": research_id, "scientific_identity": science,
        "registry_head_sha256": head, "proposal_sha256": decision["proposal_sha256"],
        "candidate_pre_admission_row_hash": checked["candidate_row_hash"],
        "review_operations_subject_sha256": rr.sha256_value([operation]),
        "parent_entity_id": ID, "parent_row_hash": checked["parent_row_hash"],
        "frozen_contract_sha256": checked["contract_sha256"], "strict_PIT_promotion_eligible": False,
        "production_qualified": False, "fit_authority": False, "formal_freeze_authority": False,
        "source_gate_required": True, "prior_artifact_reopened": False, "legacy_exposure_retained": True,
        **checked["additional_binding"]}
    return {"status": "PROPOSED_PENDING_INDEPENDENT_METADATA_REVIEW", "proposal": proposal,
        "operation_without_review_resolution": operation, "automatic_preflight": decision,
        "required_binding": binding, "required_human_record_filename": checked["human_record_filename"],
        "required_independent_review_filename": checked["review_record_filename"],
        "required_human_premise_field": checked["human_premise_field"],
        "required_review_kind": checked["independent_review_kind"],
        "required_nonredundancy_basis": checked["nonredundancy_basis"],
        "required_resolution_kind": checked["resolution_kind"],
        "new_fit_units": 0, "admitted": False, "independent_review_created": False}


# One explicit R12 comparison design. Original R1/R2 identities and pins stay intact.
COMPARISON_ID = "CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12"
COMPARISON_RUN = Path("D:/us-tech-quant-backtests") / ID / "20261015T044002+0000_9a11ab31"
COMPARISON_CHANGE = "EXPLICIT_HUMAN_PREDICTION_RISK_DECISION_MATRIX"
COMPARISON_SCIENCE = "FROZEN_PREDICTION_RISK_DECISION_ACCOUNT_COMPARISON"
COMPARISON_REVIEW_SCOPE = {
    "research_id": COMPARISON_ID, "parent_entity_id": ID, "parent_status": "OPEN",
    "parent_row_hash": "46da9c2607c7a7a2058e3f80c859cd45e3011b9763505af69d510a52f51e12d3",
    "master_ref": {"path": str(COMPARISON_RUN / "COMPARISON_RESEARCH_SCOPE.json"),
        "sha256": "4e4e29a67ba09e0a541d5af93e7128556d4ae894bab5b2230fa38575be9d7332"},
    "proposal_ref": {"path": str(COMPARISON_RUN / "COMPARISON_REGISTRY_PROPOSAL.json"),
        "sha256": "1488da4ed442d83b69c2bb83cd3d4b2955ad24f6d26c35a5c6c36c64fbb53f61"},
    "coordinates_ref": {"path": str(COMPARISON_RUN / "COMPARISON_COORDINATES.jsonl"),
        "sha256": "ac86f8ba34871c4dc882bf386ee8db8335491d13ed734ecd1e8834cc331ffbe7"},
    "human_ref": {"path": str(COMPARISON_RUN / "COMPARISON_HUMAN_REQUIREMENT_R12.json"),
        "sha256": "3b5d2d419fb1d19b87635d9b373d4090cc13e836c498c1cd7b8e02442cd35823"},
}


def comparison_candidate_entity():
    """Pin the whole design by refs; owner names are not measured outcomes."""
    from scripts.maintenance import research_registry as rr
    scope = COMPARISON_REVIEW_SCOPE
    proposal = _control(scope["proposal_ref"])
    candidate = rr._candidate(proposal["candidate"])
    candidate.update(entity_type="RESEARCH_BRANCH", status="OPEN", post_2025_observation_count=0,
        metadata={"scientific_identity": COMPARISON_SCIENCE, "source_policy": MODE,
            "information_family": INFO_FAMILY, "comparison_scope_ref": scope["master_ref"],
            "coordinates_ref": scope["coordinates_ref"], "human_scope_ref": scope["human_ref"],
            "fit_authority": False, "formal_freeze_authority": False, "strict_PIT_promotion_eligible": False,
            "quote_qualified": False, "account_qualification_granted": False, "broker_action_allowed": False,
            "source_gate_required": True, "prior_artifact_reopened": False, "legacy_exposure_retained": True,
            "original_failure_preserved": True, "distinct_information_source_claim": False,
            "prior_fit_units": 2063, "global_original_fit_unit_limit": 10000})
    return candidate


def validate_comparison_scope(operation, normalized, entity_map):
    """Admit only the pinned same-source comparison child below the OPEN R1."""
    from scripts.maintenance import research_registry as rr
    scope = COMPARISON_REVIEW_SCOPE
    master, proposal, human = [_control(scope[k]) for k in ("master_ref", "proposal_ref", "human_ref")]
    candidate = comparison_candidate_entity(); expected = rr._normalize_entity(candidate)
    parent = entity_map.get(ID, {})
    if (normalized.get("row_hash") != expected["row_hash"] or operation.get("change_type") != COMPARISON_CHANGE
            or operation.get("parent_entity_id") != ID or operation["entity"].get("aliases")
            or candidate.get("entity_id") != COMPARISON_ID or candidate.get("canonical_name") != COMPARISON_ID
            or candidate.get("parent_entity_id") != ID or candidate.get("decision_layer") != "joint-portfolio-policy"
            or parent.get("row_hash") != scope["parent_row_hash"] or parent.get("status") != "OPEN"
            or parent.get("decision_layer") != "joint-portfolio-policy"
            or parent.get("information_source_fingerprint") != candidate.get("information_source_fingerprint")
            or candidate.get("information_source_fingerprint") != INFO_SHA
            or proposal.get("parent_entity_id") != ID or proposal.get("change_type") != COMPARISON_CHANGE
            or proposal.get("claimed_novelty") is not False):
        raise rr.RegistryError("CONSENSUS_COMPARISON_EXACT_OPEN_PARENT_REQUIRED")
    required = {"schema": "CONSENSUS_COMPARISON_RESEARCH_SCOPE_R12", "task_id": ID,
        "research_id": COMPARISON_ID, "status": "AUTHORIZED_DESIGN_PENDING_EXECUTION_ADMISSION",
        "output_run": str(COMPARISON_RUN), "source_policy": MODE, "train_and_development_before": "2026-01-01",
        "outer_development": ["2023-01-01", "2026-01-01"], "rl_training_years": [2021, 2022],
        "test2026_read_authorized": False, "confirmation_read_authorized": False, "real_trades_authorized": False,
        "independent_holdout_claim": False, "prior_exposure_retained": True, "old_artifacts_overwrite": False,
        "old_account_state_reused": False, "source_qualification_is_not_granted_by_this_design": True}
    budget = {"prior_fit_units": 2063, "max_fit_units": 10000, "remaining_before_new_work": 7937,
        "forecast_recovery_max_new_units": 75, "no_reset": True, "failed_attempts_count": True,
        "risk_and_rl_preflight_required": True, "budget_exhaustion_is_incomplete_not_completion": True}
    for actual, desired in ((master, required), (master.get("budget", {}), budget)):
        if any(type(actual.get(k)) is not type(v) or actual.get(k) != v for k, v in desired.items()):
            raise rr.RegistryError("CONSENSUS_COMPARISON_BOUNDARY_OR_BUDGET_DRIFT")
    spec = candidate.get("specification", {}); comparison = master.get("comparison", {})
    if (spec.get("research_scope_ref") != scope["master_ref"] or spec.get("coordinates_ref") != scope["coordinates_ref"]
            or comparison.get("matrix_coordinates_ref") != scope["coordinates_ref"]
            or comparison.get("total_planned_coordinates") != 383 or comparison.get("main_cartesian_coordinates") != 324
            or spec.get("account") != master.get("account") or spec.get("budget") != budget
            or master.get("selection", {}).get("no_fusion_preselection") is not True
            or master.get("selection", {}).get("development_only") is not True
            or master.get("efficiency", {}).get("one_heavy_job_at_a_time") is not True
            or master.get("rl", {}).get("require_qualified_2021_2022_account_sources") is not True
            or master.get("rl", {}).get("no_outer_2023_2025_reward_training") is not True):
        raise rr.RegistryError("CONSENSUS_COMPARISON_FULL_DESIGN_BINDING_REQUIRED")
    human_required = {"schema": "CONSENSUS_COMPARISON_HUMAN_REQUIREMENT_R12", "task_id": ID,
        "research_id": COMPARISON_ID, "source": "CURRENT_HUMAN_CHAT_MESSAGES", "research_scope_ref": scope["master_ref"],
        "comparison_reset_and_matrix_required": True, "no_future_data": True, "cash_only": True,
        "fractional": True, "initial_cash_usd": 3000, "source_policy": MODE, "test2026_read_authorized": False,
        "confirmation_read_authorized": False, "broker_actions_authorized": False}
    if (any(type(human.get(k)) is not type(v) or human.get(k) != v for k, v in human_required.items())
            or any(not isinstance(human.get(k), str) or not human[k].strip()
                   for k in ("exact_user_architecture", "exact_user_reset", "prior_user_execution"))):
        raise rr.RegistryError("CONSENSUS_COMPARISON_CURRENT_HUMAN_REQUEST_REQUIRED")
    return {**scope, "change_type": COMPARISON_CHANGE, "candidate_row_hash": expected["row_hash"],
        "contract_path": scope["master_ref"]["path"], "contract_sha256": scope["master_ref"]["sha256"],
        "request_path": scope["human_ref"]["path"], "request_sha256": scope["human_ref"]["sha256"],
        "automatic_reasons": ["existing information source is reused without enough non-redundancy evidence"],
        "scientific_identity": COMPARISON_SCIENCE, "resolution_kind": "EXACT_CONSENSUS_COMPARISON_METADATA_REVIEW",
        "human_premise_field": "prediction_risk_decision_matrix_and_reset_authorized",
        "human_record_filename": "CONSENSUS100_COMPARISON_REGISTRY_HUMAN_AUTHORIZATION.json",
        "review_record_filename": "CONSENSUS100_COMPARISON_REGISTRY_INDEPENDENT_REVIEW.json",
        "independent_review_kind": "INDEPENDENT_CONSENSUS_COMPARISON_REGISTRY_REVIEW",
        "nonredundancy_basis": "EXPLICIT_MATRIX_OF_FROZEN_PREDICTION_RISK_AND_ACCOUNT_DECISION_INTERACTIONS",
        "additional_custody": [{**scope["proposal_ref"], "maximum_bytes": 65536},
            {**scope["coordinates_ref"], "maximum_bytes": 131072}],
        "additional_binding": {"comparison_scope_sha256": scope["master_ref"]["sha256"],
            "coordinates_sha256": scope["coordinates_ref"]["sha256"], "human_scope_sha256": scope["human_ref"]["sha256"],
            "specification_fingerprint": candidate["specification_fingerprint"],
            "information_source_fingerprint": INFO_SHA, "mechanism_fingerprint": candidate["mechanism_fingerprint"],
            "prior_fit_units": 2063, "global_original_fit_unit_limit": 10000, "original_failure_preserved": True,
            "distinct_information_source_claim": False, "quote_qualified": False,
            "account_qualification_granted": False, "broker_action_allowed": False}}


def comparison_proposal():
    """Unreviewed R12 metadata proposal; no numerical authority."""
    return {"candidate": comparison_candidate_entity(), "parent_entity_id": ID, "change_type": COMPARISON_CHANGE}


def comparison_review_requirements(registry_root):
    return _review_requirements(registry_root, comparison_proposal(), validate_comparison_scope,
                                COMPARISON_ID, COMPARISON_SCIENCE)
