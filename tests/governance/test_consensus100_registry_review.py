"""Synthetic-only exact registry admission; no live registry or data access."""
import copy
import json
from pathlib import Path

import pytest

from scripts.maintenance import consensus100_registry_review as cr
from scripts.maintenance import research_registry as rr


def write(path, value):
    path.write_bytes(rr.canonical_json(value))
    return {"path": str(path), "sha256": rr.sha256_file(path)}


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    spec = {"task_id": cr.ID, "source_policy": cr.MODE, "strict_PIT_promotion_eligible": False,
        "universe": {"dynamic": True, "top_n": 100, "selection_rule": "MANAGER_COUNT_WEIGHT_SUM",
            "filing_scope": "INITIAL_PUBLIC_AS_FILED_NO_AMENDMENT_BACKFILL", "held_outside_pool": "KEEP_NO_NEW_BUY"},
        "training_boundary": {"exclusive": "2026-01-01"}, "fusion_input": "CHRONOLOGICAL_OOF_ONLY",
        "source_gate": {"latest_human_scope": "synthetic explicit historical-source permission"}}
    proposal = {"parent_entity_id": cr.PARENT, "candidate": {
        "entity_id": cr.ID, "canonical_name": cr.ID, "aliases": [],
        "decision_layer": "joint-portfolio-policy", "information_source_fingerprint": cr.INFO_SHA,
        "information_family": cr.INFO_FAMILY, "specification_fingerprint": rr.sha256_value(spec),
        "mechanism": {"multi_model_pto": True, "dynamic_consensus_pool": True, "settled_fractional_cash": True}}}
    human = {"source": "CURRENT_HUMAN_CHAT_MESSAGES", "task_id": cr.ID,
        "human_latest_quote_scope": spec["source_gate"]["latest_human_scope"]}
    code = tmp_path / "synthetic_account.py"
    code.write_text("# synthetic source custody only", encoding="utf-8")
    preflight = tmp_path / "synthetic_account_preflight.json"
    write(preflight, {"synthetic_only": True})
    account = {"task_id": cr.ID, "initial_cash_usd": 3000, "cash_only": True, "fractional": True,
        "settlement_rule": "ORDINARY_TRADE_T_PLUS_2_BEFORE_2024_05_28_T_PLUS_1_SINCE_WITH_COMPLETE_EXCHANGE_SESSION_CALENDAR",
        "sale_proceeds": "NAV_ASSET_UNTIL_SETTLED_NOT_BUYING_POWER", "base_one_way_all_in_bps": 10,
        "other_one_way_all_in_bps": [5, 25], "fixed_ticket_stress_usd": .5,
        "normal_min_trade_usd": 5, "fee_owner": "SINGLE_FEE_FOR_NOTIONAL_FOR_QUOTE_AND_FILL",
        "broker_fees_known": False, "broker_fill_at_open_certified": False, "existing_source_unknowns_retained": True,
        "account_source_ref": str(code), "account_source_sha256": rr.sha256_file(code),
        "account_preflight_ref": str(preflight), "account_preflight_sha256": rr.sha256_file(preflight)}
    parent = rr._normalize_entity({"entity_id": cr.PARENT, "canonical_name": cr.PARENT,
        "entity_type": "RESEARCH_BRANCH", "status": "OPEN", "aliases": [],
        "decision_layer": "joint-portfolio-policy", "specification_fingerprint": rr.sha256_value({"parent": "spec"}),
        "information_source_fingerprint": cr.INFO_SHA, "mechanism_fingerprint": rr.sha256_value({"parent": "mechanism"}),
        "information_family": cr.INFO_FAMILY, "evidence_source_temporal_status": "SYNTHETIC_ONLY",
        "excluded_source_refs": [], "temporal_evidence_limitations": ["SYNTHETIC_ONLY"]})
    scope = copy.deepcopy(cr.REVIEW_SCOPE)
    scope["parent_row_hash"] = parent["row_hash"]
    for key, value in (("spec_ref", spec), ("proposal_ref", proposal), ("human_ref", human), ("account_ref", account)):
        scope[key] = write(tmp_path / Path(scope[key]["path"]).name, value)
    monkeypatch.setattr(cr, "REVIEW_SCOPE", scope)
    monkeypatch.setattr(rr, "_CONSENSUS100_REVIEW_SCOPE", scope)
    entity = cr.candidate_entity()
    operation = {"op": "add_entity", "entity": entity, "parent_entity_id": cr.PARENT, "change_type": cr.CHANGE}
    proposal = {"candidate": entity, "parent_entity_id": cr.PARENT, "change_type": cr.CHANGE}
    decision = rr.evaluate_proposal(proposal, [parent], [], head_sha256=rr.GENESIS)
    checked = cr.validate_scope(operation, rr._normalize_entity(entity), {cr.PARENT: parent})
    binding = {"schema_version": 1, "research_id": cr.ID, "scientific_identity": checked["scientific_identity"],
        "registry_head_sha256": rr.GENESIS, "proposal_sha256": decision["proposal_sha256"],
        "candidate_pre_admission_row_hash": checked["candidate_row_hash"],
        "review_operations_subject_sha256": rr.sha256_value([operation]), "parent_entity_id": cr.PARENT,
        "parent_row_hash": parent["row_hash"], "frozen_contract_sha256": checked["contract_sha256"],
        "strict_PIT_promotion_eligible": False, "production_qualified": False, "fit_authority": False,
        "formal_freeze_authority": False, "source_gate_required": True, "prior_artifact_reopened": False,
        "legacy_exposure_retained": True, **checked["additional_binding"]}
    author, reviewer = "synthetic-author", "synthetic-reviewer"
    human_record = {**binding, "kind": "HUMAN_AUTHORIZATION_RECORD", "human_user_authorized": True,
        "authorization_source": "CURRENT_HUMAN_REQUEST", "recorded_by": author,
        "human_request_ref": checked["request_path"], "human_request_sha256": checked["request_sha256"],
        checked["human_premise_field"]: True}
    human_ref = write(tmp_path / checked["human_record_filename"], human_record)
    review_record = {**binding, "kind": checked["independent_review_kind"], "status": "PASS",
        "independent": True, "author": author, "reviewer": reviewer, "scope": "OPEN_METADATA_ONLY",
        "nonredundancy_basis": checked["nonredundancy_basis"], "human_authorization_sha256": human_ref["sha256"]}
    review_ref = write(tmp_path / checked["review_record_filename"], review_record)
    operation["review_resolution"] = {"kind": checked["resolution_kind"], "automatic_decision": decision,
        "human_authorization_ref": human_ref["path"], "human_authorization_sha256": human_ref["sha256"],
        "independent_review_ref": review_ref["path"], "independent_review_sha256": review_ref["sha256"]}
    patch = {"author": author, "validation": {"status": "PASS"},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": reviewer}, "operations": [operation]}
    return {"parent": parent, "patch": patch, "scope": scope, "code": code,
        "human_record": human_record, "review_record": review_record}


def apply(f, **changes):
    return rr._apply_operations(changes.get("parents", [f["parent"]]), changes.get("aliases", []),
        f["patch"], head_sha256=rr.GENESIS)


def test_exact_open_metadata_admission_preserves_parent_and_gates(reviewed):
    entities, aliases = apply(reviewed)
    rows = {row["entity_id"]: row for row in entities}
    assert rows[cr.PARENT] == reviewed["parent"]
    admitted = rows[cr.ID]
    assert admitted["status"] == "OPEN"
    assert admitted["information_source_fingerprint"] == reviewed["parent"]["information_source_fingerprint"]
    assert admitted["metadata"]["explicit_review_decision"] == "ACCEPT_OPEN_METADATA_ONLY"
    for field in ("fit_authority", "formal_freeze_authority", "strict_PIT_promotion_eligible", "broker_action_allowed", "account_qualification_granted"):
        assert admitted["metadata"][field] is False
    assert aliases == [rr._alias_row(cr.ID, cr.ID)]


@pytest.mark.parametrize("field,value", [("fit_authority", True), ("source_policy", "STRICT_PIT")])
def test_entity_metadata_drift_rejected(reviewed, field, value):
    reviewed["patch"]["operations"][0]["entity"]["metadata"][field] = value
    with pytest.raises(rr.RegistryError):
        apply(reviewed)


def test_changed_source_custody_rejected(reviewed):
    reviewed["code"].write_text("# changed source", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="ADDITIONAL_FROZEN_CUSTODY"):
        apply(reviewed)


def test_changed_human_scope_bytes_rejected(reviewed):
    Path(reviewed["scope"]["human_ref"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="CONTROL_CUSTODY"):
        apply(reviewed)


def test_nonindependent_reviewer_rejected(reviewed):
    reviewed["patch"]["independent_review"]["reviewer"] = reviewed["patch"]["author"]
    with pytest.raises(rr.RegistryError, match="REVIEWER_MUST_DIFFER"):
        apply(reviewed)


def test_false_human_authorization_rejected(reviewed):
    record = reviewed["human_record"]
    record["human_user_authorized"] = False
    resolution = reviewed["patch"]["operations"][0]["review_resolution"]
    ref = write(Path(resolution["human_authorization_ref"]), record)
    resolution["human_authorization_sha256"] = ref["sha256"]
    with pytest.raises(rr.RegistryError, match="HUMAN_AUTHORIZATION_REQUIRED"):
        apply(reviewed)


def test_proposal_decision_forgery_rejected(reviewed):
    reviewed["patch"]["operations"][0]["review_resolution"]["automatic_decision"]["matched_entity_ids"] = [cr.PARENT]
    with pytest.raises(rr.RegistryError, match="DECISION_BINDING"):
        apply(reviewed)


def test_unrelated_identity_has_no_review_override(reviewed):
    op = reviewed["patch"]["operations"][0]
    op["entity"]["entity_id"] = op["entity"]["canonical_name"] = "SYNTHETIC_UNAUTHORIZED_CHILD"
    with pytest.raises(rr.RegistryError):
        apply(reviewed)


def test_closed_exact_identity_remains_blocked(reviewed):
    old = copy.deepcopy(reviewed["patch"]["operations"][0]["entity"])
    old.update(entity_id="SYNTHETIC_CLOSED_BRANCH", canonical_name="SYNTHETIC_CLOSED_BRANCH", status="CLOSED")
    old = rr._normalize_entity(old)
    with pytest.raises(rr.RegistryError, match="EXACT_AUTOMATIC_DECISION"):
        apply(reviewed, parents=[reviewed["parent"], old])


def test_alias_conflict_remains_blocked(reviewed):
    existing = rr._alias_row(cr.ID, cr.PARENT)
    with pytest.raises(rr.RegistryError, match="EXACT_AUTOMATIC_DECISION"):
        apply(reviewed, aliases=[existing])


def test_unreviewed_same_information_candidate_stays_rejected(reviewed):
    op = reviewed["patch"]["operations"][0]
    del op["review_resolution"]
    with pytest.raises(rr.RegistryError, match="PROPOSAL_NOT_APPLYABLE:REVIEW_REQUIRED"):
        apply(reviewed)


def test_outcome_or_test_counter_cannot_enter_review(reviewed):
    reviewed["patch"]["independent_review"]["post_2025_observation_count"] = 1
    with pytest.raises(rr.RegistryError, match="POST_2025_COUNTER_NONZERO"):
        apply(reviewed)


@pytest.fixture
def continuation(reviewed, tmp_path, monkeypatch):
    # Only generated metadata/code custody: this never loads a live research run.
    old_entities, old_aliases = apply(reviewed)
    parent = next(r for r in old_entities if r["entity_id"] == cr.ID)
    scope = copy.deepcopy(cr.CONTINUATION_REVIEW_SCOPE)
    scope["parent_row_hash"] = parent["row_hash"]
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.setattr(cr, "CONTINUATION_RUN", child)
    refs = {}
    for key in ("account_freeze_ref", "authorized_spec_ref", "fusion_freeze_ref",
                "historical_fusion_adapter_archive_ref", "historical_owner_archive_ref",
                "membership_ref", "parent_fit_log_ref", "physical_binding_ref",
                "predictor_freeze_ref", "terminal_audit_ref"):
        artifact = tmp_path / (key + ".txt")
        artifact.write_text("synthetic custody " + key, encoding="utf-8")
        refs[key] = {"path": str(artifact), "sha256": rr.sha256_file(artifact)}
    continuation = {"schema": "CONSENSUS_PRE2026_SOURCE_COMPLETION_CONTINUATION_SCOPE_R1",
        "status": "AUTHORIZED_REPAIR_BRANCH_PENDING_SOURCE_PROOF_AND_REVIEWED_FIT_FREEZE",
        "task_id": cr.ID, "research_id": cr.CONTINUATION_ID, "parent_research_id": cr.ID, "run": str(child),
        "original_artifacts_overwritten": False, "broker_action_allowed": False,
        "source_qualification": "PENDING_NEW_PRE2026_ECONOMIC_FACTS_NO_REPLAY_AUTHORITY_YET",
        "human_instruction": "synthetic explicit pre2026 continuation permission",
        "boundaries": {"fit_preprocess_calibration_selection_before": "2026-01-01",
            "FAST3_Confirmation_access": False, "existing_A2_exposure_retained": True,
            "fresh_blind_holdout": False, "strict_PIT_certified": False,
            "no_new_2026_sample_or_outcome_read_authorized": True, "source_vintage": "UNKNOWN_RETAINED"},
        "budget": {"global_original_fit_unit_limit": 10000, "new_fusion_slots": 4,
            "no_fit_budget_reset": True, "no_new_seed_horizon_or_asset_pool_search": True, "prior_fit_units": 1098},
        "scientific_change": {"new_named_fusion_candidate": "nnls_zero_abstain",
            "original_m035_zero_failure_preserved": True,
            "zero_rule": "Only exact solver zero with strictly certified negative training XTy outside floating uncertainty -> explicit zero forecast; otherwise reject. Positive normalized rule unchanged."},
        "parent_custody": {**refs, "parent_fit_units": 1098, "parent_fit_log_events": 1699,
            "run": "D:/us-tech-quant-backtests/" + cr.ID + "/20261011T170254+0000_bf592a79"}}
    scope["continuation_ref"] = write(child / "CONTINUATION_SCOPE.json", continuation)
    account = {"schema": "CONSENSUS_SOURCE_COMPLETION_ACCOUNT_CONVENTION_R1",
        "status": "FROZEN_BEFORE_NEW_ACCOUNT_REPLAY_OR_SELECTION", "task_id": cr.ID,
        "research_id": cr.CONTINUATION_ID, "continuation_scope_ref": scope["continuation_ref"],
        "selection_outcomes_seen_before_this_freeze": False, "source_policy": cr.MODE,
        "strict_pit_certification": False,
        "time_boundary": {"all_fit_selection_and_replay_observations_before": "2026-01-01",
            "actual_2026_payment_or_fx_realization_read_or_used": False},
        "account": {"cash_account": True, "currency": "USD", "fractional_shares": True, "initial_usd": 3000},
        "stock_distribution_research_convention": {"mode": "BENEFICIAL_FRACTIONAL_ECONOMIC_INTEREST_RESEARCH_ASSUMPTION",
            "raw_price_adjustment_factor_as_share_ratio_allowed": False},
        "out_of_pool_child_exit": {"future_pool_membership_read": False, "synthetic_zero_alpha_allowed": False}}
    scope["account_convention_ref"] = write(child / "ACCOUNT_CONVENTION_SCOPE.json", account)
    monkeypatch.setattr(cr, "CONTINUATION_REVIEW_SCOPE", scope)
    monkeypatch.setattr(rr, "_CONSENSUS100_CONTINUATION_REVIEW_SCOPE", scope)
    monkeypatch.setattr(rr, "_load_snapshot_for_read", lambda *_: ({"snapshot_sha256": rr.GENESIS}, old_entities, old_aliases))
    needs = cr.continuation_review_requirements(tmp_path / "synthetic_registry")
    op = needs["operation_without_review_resolution"]
    checked = cr.validate_continuation_scope(op, rr._normalize_entity(op["entity"]), {cr.ID: parent})
    binding = needs["required_binding"]
    author, reviewer = "synthetic-continuation-author", "synthetic-continuation-reviewer"
    human = {**binding, "kind": "HUMAN_AUTHORIZATION_RECORD", "human_user_authorized": True,
        "authorization_source": "CURRENT_HUMAN_REQUEST", "recorded_by": author,
        "human_request_ref": checked["request_path"], "human_request_sha256": checked["request_sha256"],
        checked["human_premise_field"]: True}
    human_ref = write(child / checked["human_record_filename"], human)
    review = {**binding, "kind": checked["independent_review_kind"], "status": "PASS", "independent": True,
        "author": author, "reviewer": reviewer, "scope": "OPEN_METADATA_ONLY",
        "nonredundancy_basis": checked["nonredundancy_basis"], "human_authorization_sha256": human_ref["sha256"]}
    review_ref = write(child / checked["review_record_filename"], review)
    op["review_resolution"] = {"kind": checked["resolution_kind"], "automatic_decision": needs["automatic_preflight"],
        "human_authorization_ref": human_ref["path"], "human_authorization_sha256": human_ref["sha256"],
        "independent_review_ref": review_ref["path"], "independent_review_sha256": review_ref["sha256"]}
    patch = {"author": author, "validation": {"status": "PASS"},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": reviewer}, "operations": [op]}
    return {"parent": parent, "parents": old_entities, "aliases": old_aliases, "scope": scope, "patch": patch,
        "needs": needs, "continuation": continuation, "account": account, "review": review, "human": human}


def apply_continuation(f):
    return rr._apply_operations(f["parents"], f["aliases"], f["patch"], head_sha256=rr.GENESIS)


def test_continuation_metadata_only_review_preserves_parent_and_failures(continuation):
    f = continuation
    result, aliases = apply_continuation(f)
    rows = {r["entity_id"]: r for r in result}
    assert rows[cr.ID] == f["parent"]
    child = rows[cr.CONTINUATION_ID]
    assert child["status"] == "OPEN"
    assert child["information_source_fingerprint"] == f["parent"]["information_source_fingerprint"]
    assert child["specification_fingerprint"] != f["parent"]["specification_fingerprint"]
    assert child["mechanism_fingerprint"] != f["parent"]["mechanism_fingerprint"]
    assert child["metadata"]["original_failure_preserved"] is True
    assert child["metadata"]["prior_fit_units"] == 1098
    for key in ("fit_authority", "formal_freeze_authority", "strict_PIT_promotion_eligible",
                "broker_action_allowed", "account_qualification_granted", "distinct_information_source_claim"):
        assert child["metadata"][key] is False
    assert child["metadata"]["explicit_review_decision"] == "ACCEPT_OPEN_METADATA_ONLY"
    assert rr._alias_row(cr.CONTINUATION_ID, cr.CONTINUATION_ID) in aliases


def test_continuation_proposal_remains_review_required_without_self_signature(continuation):
    needs = continuation["needs"]
    assert needs["automatic_preflight"]["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
    assert needs["admitted"] is False and needs["independent_review_created"] is False
    assert needs["new_fit_units"] == 0
    del continuation["patch"]["operations"][0]["review_resolution"]
    with pytest.raises(rr.RegistryError, match="PROPOSAL_NOT_APPLYABLE:REVIEW_REQUIRED"):
        apply_continuation(continuation)


@pytest.mark.parametrize("field,value", [("fit_authority", True), ("distinct_information_source_claim", True),
                                        ("original_failure_preserved", False), ("prior_fit_units", 0)])
def test_continuation_candidate_authority_or_history_drift_rejected(continuation, field, value):
    continuation["patch"]["operations"][0]["entity"]["metadata"][field] = value
    with pytest.raises(rr.RegistryError):
        apply_continuation(continuation)


@pytest.mark.parametrize("section,field,value", [
    ("boundaries", "fresh_blind_holdout", True), ("boundaries", "no_new_2026_sample_or_outcome_read_authorized", False),
    ("budget", "prior_fit_units", 0), ("budget", "new_fusion_slots", 84),
    ("scientific_change", "original_m035_zero_failure_preserved", False)])
def test_continuation_pinned_control_semantics_checked(continuation, section, field, value):
    f = continuation; f["continuation"][section][field] = value
    f["scope"]["continuation_ref"] = write(Path(f["scope"]["continuation_ref"]["path"]), f["continuation"])
    with pytest.raises(rr.RegistryError, match="BOUNDARY_OR_SCIENCE"):
        cr.validate_continuation_scope({"entity": cr.continuation_candidate_entity(),
            "change_type": cr.CONTINUATION_CHANGE, "parent_entity_id": cr.ID},
            rr._normalize_entity(cr.continuation_candidate_entity()), {cr.ID: f["parent"]})


@pytest.mark.parametrize("role", ["historical_fusion_adapter_archive_ref", "historical_owner_archive_ref",
                                  "parent_fit_log_ref", "membership_ref"])
def test_continuation_parent_custody_tamper_rejected(continuation, role):
    Path(continuation["continuation"]["parent_custody"][role]["path"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="ADDITIONAL_FROZEN_CUSTODY"):
        apply_continuation(continuation)


def test_continuation_parent_must_remain_open_and_exact(continuation):
    f = continuation
    changed = copy.deepcopy(f["parent"]); changed["status"] = "CLOSED"
    f["parents"] = [rr._normalize_entity(rr._entity_without_hash(changed)) if r["entity_id"] == cr.ID else r for r in f["parents"]]
    with pytest.raises(rr.RegistryError):
        apply_continuation(f)


def test_continuation_independent_reviewer_required(continuation):
    continuation["patch"]["independent_review"]["reviewer"] = continuation["patch"]["author"]
    with pytest.raises(rr.RegistryError, match="REVIEWER_MUST_DIFFER"):
        apply_continuation(continuation)


def test_continuation_account_and_human_bindings_cannot_be_reused(continuation):
    f = continuation; op = f["patch"]["operations"][0]
    f["review"]["account_convention_scope_sha256"] = "0" * 64
    ref = write(Path(op["review_resolution"]["independent_review_ref"]), f["review"])
    op["review_resolution"]["independent_review_sha256"] = ref["sha256"]
    with pytest.raises(rr.RegistryError, match="EVIDENCE_BINDING_MISMATCH"):
        apply_continuation(f)


def test_continuation_account_future_pool_and_synthetic_alpha_rejected(continuation):
    f = continuation; f["account"]["out_of_pool_child_exit"]["synthetic_zero_alpha_allowed"] = True
    f["scope"]["account_convention_ref"] = write(Path(f["scope"]["account_convention_ref"]["path"]), f["account"])
    candidate = cr.continuation_candidate_entity()
    with pytest.raises(rr.RegistryError, match="ACCOUNT_CONVENTION_REQUIRED"):
        cr.validate_continuation_scope({"entity": candidate, "change_type": cr.CONTINUATION_CHANGE, "parent_entity_id": cr.ID},
            rr._normalize_entity(candidate), {cr.ID: f["parent"]})



def test_exact_continuation_structural_token_retains_metric_guards():
    rr._reject_outcome_fields({"entity_id": cr.CONTINUATION_ID,
        "source_ref": "D:/task/" + cr.CONTINUATION_ID + "/CONTINUATION_SCOPE.json"})
    for value in (cr.CONTINUATION_ID + "_SHARPE_1P2", cr.CONTINUATION_ID + "_R2_0P9", "R2_0P9"):
        with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES"):
            rr._reject_outcome_fields({"entity_id": value})
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_FIELDS"):
        rr._reject_outcome_fields({"r2": cr.CONTINUATION_ID})



def test_exact_pinned_continuation_control_paths_are_not_outcomes():
    run = Path("D:/us-tech-quant-backtests") / cr.CONTINUATION_ID / "20261012T025603+0000_4a58260e"
    for name in ("CONTINUATION_SCOPE.json", "ACCOUNT_CONVENTION_SCOPE.json"):
        ref = str(run / name)
        rr._reject_outcome_fields({"source_ref": ref})
        with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES"):
            rr._reject_outcome_fields({"source_ref": ref + "?SHARPE=1.2"})
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES"):
        rr._reject_outcome_fields({"source_ref": str(run / "RETURN_10_percent.json")})


@pytest.fixture
def comparison(reviewed, tmp_path, monkeypatch):
    """Synthetic design and records only; never open the real R12 or registry."""
    parents, aliases = apply(reviewed)
    parent = next(row for row in parents if row["entity_id"] == cr.ID)
    run = tmp_path / "comparison"; run.mkdir()
    monkeypatch.setattr(cr, "COMPARISON_RUN", run)
    scope = copy.deepcopy(cr.COMPARISON_REVIEW_SCOPE)
    scope["parent_row_hash"] = parent["row_hash"]
    coordinates = run / "COMPARISON_COORDINATES.jsonl"
    coordinates.write_text('{"synthetic_only":true}\n', encoding="utf-8")
    scope["coordinates_ref"] = {"path": str(coordinates), "sha256": rr.sha256_file(coordinates)}
    budget = {"prior_fit_units": 2063, "max_fit_units": 10000, "remaining_before_new_work": 7937,
        "forecast_recovery_max_new_units": 75, "no_reset": True, "failed_attempts_count": True,
        "risk_and_rl_preflight_required": True, "budget_exhaustion_is_incomplete_not_completion": True}
    master = {"schema": "CONSENSUS_COMPARISON_RESEARCH_SCOPE_R12", "task_id": cr.ID,
        "research_id": cr.COMPARISON_ID, "status": "AUTHORIZED_DESIGN_PENDING_EXECUTION_ADMISSION",
        "output_run": str(run), "source_policy": cr.MODE, "train_and_development_before": "2026-01-01",
        "outer_development": ["2023-01-01", "2026-01-01"], "rl_training_years": [2021, 2022],
        "test2026_read_authorized": False, "confirmation_read_authorized": False, "real_trades_authorized": False,
        "independent_holdout_claim": False, "prior_exposure_retained": True, "old_artifacts_overwrite": False,
        "old_account_state_reused": False, "source_qualification_is_not_granted_by_this_design": True,
        "budget": budget, "account": {"initial_cash": 3000, "type": "CASH", "fractional": True},
        "comparison": {"matrix_coordinates_ref": scope["coordinates_ref"], "total_planned_coordinates": 383,
            "main_cartesian_coordinates": 324},
        "selection": {"no_fusion_preselection": True, "development_only": True},
        "efficiency": {"one_heavy_job_at_a_time": True},
        "rl": {"require_qualified_2021_2022_account_sources": True, "no_outer_2023_2025_reward_training": True}}
    scope["master_ref"] = write(run / "COMPARISON_RESEARCH_SCOPE.json", master)
    human = {"schema": "CONSENSUS_COMPARISON_HUMAN_REQUIREMENT_R12", "task_id": cr.ID,
        "research_id": cr.COMPARISON_ID, "source": "CURRENT_HUMAN_CHAT_MESSAGES", "research_scope_ref": scope["master_ref"],
        "comparison_reset_and_matrix_required": True, "no_future_data": True, "cash_only": True, "fractional": True,
        "initial_cash_usd": 3000, "source_policy": cr.MODE, "test2026_read_authorized": False,
        "confirmation_read_authorized": False, "broker_actions_authorized": False,
        "exact_user_architecture": "synthetic matrix instruction", "exact_user_reset": "synthetic reset instruction",
        "prior_user_execution": "synthetic execution instruction"}
    scope["human_ref"] = write(run / "COMPARISON_HUMAN_REQUIREMENT_R12.json", human)
    candidate = {"entity_id": cr.COMPARISON_ID, "canonical_name": cr.COMPARISON_ID, "aliases": [],
        "parent_entity_id": cr.ID, "decision_layer": "joint-portfolio-policy",
        "information_source_fingerprint": cr.INFO_SHA, "information_family": cr.INFO_FAMILY,
        "specification": {"research_scope_ref": scope["master_ref"], "coordinates_ref": scope["coordinates_ref"],
            "account": master["account"], "budget": budget},
        "mechanism": {"comparison_unit": "INDEPENDENT_EMPTY_USD3000_CONTINUOUS_CASH_ACCOUNT"},
        "evidence_source_temporal_status": "FROZEN_PRE2026_HISTORY_UNKNOWN_VINTAGE_MECHANISM_ONLY",
        "excluded_source_refs": ["FAST3_CONFIRMATION", "TEST2026_BEFORE_COMPLETE_FREEZE", "YEAR2027_AND_LATER"],
        "temporal_evidence_limitations": ["2023_2025_PREVIOUS_EXPOSURE_RETAINED_NOT_FRESH_HOLDOUT"]}
    scope["proposal_ref"] = write(run / "COMPARISON_REGISTRY_PROPOSAL.json",
        {"candidate": candidate, "parent_entity_id": cr.ID, "change_type": cr.COMPARISON_CHANGE, "claimed_novelty": False})
    monkeypatch.setattr(cr, "COMPARISON_REVIEW_SCOPE", scope)
    monkeypatch.setattr(rr, "_CONSENSUS100_COMPARISON_REVIEW_SCOPE", scope)
    monkeypatch.setattr(rr, "_load_snapshot_for_read", lambda *_: ({"snapshot_sha256": rr.GENESIS}, parents, aliases))
    needs = cr.comparison_review_requirements(tmp_path / "synthetic_registry")
    op = needs["operation_without_review_resolution"]
    checked = cr.validate_comparison_scope(op, rr._normalize_entity(op["entity"]), {cr.ID: parent})
    binding = needs["required_binding"]
    author, reviewer = "synthetic-matrix-author", "synthetic-matrix-reviewer"
    human_record = {**binding, "kind": "HUMAN_AUTHORIZATION_RECORD", "human_user_authorized": True,
        "authorization_source": "CURRENT_HUMAN_REQUEST", "recorded_by": author,
        "human_request_ref": checked["request_path"], "human_request_sha256": checked["request_sha256"],
        checked["human_premise_field"]: True}
    human_ref = write(run / checked["human_record_filename"], human_record)
    review = {**binding, "kind": checked["independent_review_kind"], "status": "PASS", "independent": True,
        "author": author, "reviewer": reviewer, "scope": "OPEN_METADATA_ONLY",
        "nonredundancy_basis": checked["nonredundancy_basis"], "human_authorization_sha256": human_ref["sha256"]}
    review_ref = write(run / checked["review_record_filename"], review)
    op["review_resolution"] = {"kind": checked["resolution_kind"], "automatic_decision": needs["automatic_preflight"],
        "human_authorization_ref": human_ref["path"], "human_authorization_sha256": human_ref["sha256"],
        "independent_review_ref": review_ref["path"], "independent_review_sha256": review_ref["sha256"]}
    patch = {"author": author, "validation": {"status": "PASS"},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": reviewer}, "operations": [op]}
    return {"parents": parents, "aliases": aliases, "parent": parent, "scope": scope, "patch": patch,
        "needs": needs, "master": master, "human": human, "review": review}


def apply_comparison(f):
    return rr._apply_operations(f["parents"], f["aliases"], f["patch"], head_sha256=rr.GENESIS)


def test_comparison_metadata_only_retains_all_runtime_gates_and_parent(comparison):
    rows, aliases = apply_comparison(comparison)
    rows = {row["entity_id"]: row for row in rows}
    assert rows[cr.ID] == comparison["parent"]
    child = rows[cr.COMPARISON_ID]
    assert child["status"] == "OPEN" and child["metadata"]["prior_fit_units"] == 2063
    assert child["metadata"]["original_failure_preserved"] is True
    for key in ("fit_authority", "formal_freeze_authority", "strict_PIT_promotion_eligible",
                "quote_qualified", "account_qualification_granted", "broker_action_allowed", "prior_artifact_reopened"):
        assert child["metadata"][key] is False
    assert rr._alias_row(cr.COMPARISON_ID, cr.COMPARISON_ID) in aliases


def test_comparison_cannot_self_admit_without_review(comparison):
    assert comparison["needs"]["automatic_preflight"]["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
    assert comparison["needs"]["admitted"] is False
    del comparison["patch"]["operations"][0]["review_resolution"]
    with pytest.raises(rr.RegistryError, match="PROPOSAL_NOT_APPLYABLE"):
        apply_comparison(comparison)


@pytest.mark.parametrize("field,value", [("test2026_read_authorized", True), ("prior_exposure_retained", False),
    ("old_artifacts_overwrite", True), ("source_qualification_is_not_granted_by_this_design", False)])
def test_comparison_rejects_rebound_boundary_or_authority(comparison, field, value):
    f = comparison; f["master"][field] = value
    f["scope"]["master_ref"] = write(Path(f["scope"]["master_ref"]["path"]), f["master"])
    op = {**f["patch"]["operations"][0], "entity": cr.comparison_candidate_entity()}
    with pytest.raises(rr.RegistryError, match="BOUNDARY_OR_BUDGET"):
        cr.validate_comparison_scope(op, rr._normalize_entity(op["entity"]), {cr.ID: f["parent"]})


def test_comparison_rejects_lifetime_budget_reset(comparison):
    f = comparison; f["master"]["budget"]["prior_fit_units"] = 0
    f["scope"]["master_ref"] = write(Path(f["scope"]["master_ref"]["path"]), f["master"])
    op = {**f["patch"]["operations"][0], "entity": cr.comparison_candidate_entity()}
    with pytest.raises(rr.RegistryError, match="BOUNDARY_OR_BUDGET"):
        cr.validate_comparison_scope(op, rr._normalize_entity(op["entity"]), {cr.ID: f["parent"]})


def test_comparison_changed_coordinate_bytes_rejected(comparison):
    Path(comparison["scope"]["coordinates_ref"]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="ADDITIONAL_FROZEN_CUSTODY"):
        apply_comparison(comparison)


def test_comparison_cannot_reopen_closed_parent_or_matching_closed_mechanism(comparison):
    f = comparison; parent = copy.deepcopy(f["parent"])
    parent["status"] = "CLOSED"
    parent = rr._normalize_entity(rr._entity_without_hash(parent))
    f["parents"] = [parent if row["entity_id"] == cr.ID else row for row in f["parents"]]
    with pytest.raises(rr.RegistryError):
        apply_comparison(f)
    f["parents"] = [f["parent"] if row["entity_id"] == cr.ID else row for row in f["parents"]]
    closed = copy.deepcopy(f["patch"]["operations"][0]["entity"])
    closed.update(entity_id="SYNTHETIC_CLOSED_MATRIX", canonical_name="SYNTHETIC_CLOSED_MATRIX", status="CLOSED")
    f["parents"].append(rr._normalize_entity(closed))
    with pytest.raises(rr.RegistryError, match="EXACT_AUTOMATIC_DECISION"):
        apply_comparison(f)


def test_comparison_rejects_nonindependent_reviewer_and_reused_bindings(comparison):
    f = comparison
    f["patch"]["independent_review"]["reviewer"] = f["patch"]["author"]
    with pytest.raises(rr.RegistryError, match="REVIEWER_MUST_DIFFER"):
        apply_comparison(f)
    f["patch"]["independent_review"]["reviewer"] = f["review"]["reviewer"]
    f["review"]["coordinates_sha256"] = "0" * 64
    op = f["patch"]["operations"][0]
    updated = write(Path(op["review_resolution"]["independent_review_ref"]), f["review"])
    op["review_resolution"]["independent_review_sha256"] = updated["sha256"]
    with pytest.raises(rr.RegistryError, match="EVIDENCE_BINDING_MISMATCH"):
        apply_comparison(f)
