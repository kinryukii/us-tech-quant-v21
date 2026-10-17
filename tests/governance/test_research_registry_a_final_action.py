"""Synthetic-only final-action registry admission; no real research data or runs.

Imports only the existing metadata registry. All registry snapshots, audits,
contracts and authority fixtures below are task-owned synthetic scratch files.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from scripts.maintenance import research_registry as rr


def write(path: Path, value) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(rr.canonical_json(value))
    return {"path": str(path), "sha256": rr.sha256_file(path)}


def pin(path: Path) -> dict:
    return {"path": str(path), "sha256": rr.sha256_file(path)}


def members_for(f, identity):
    census = f["census"]
    representative = next(r for r in census["representatives"] if r["representative_id"] == identity)
    by_slot = {o["slot_id"]: (i, o) for i, o in enumerate(census["objects"])}
    result = []
    for slot in representative["member_slot_ids"]:
        ordinal, member = by_slot[slot]
        result.append({"census_object_ordinal": ordinal, "census_ref": f["manifest"]["census_ref"],
            "original_scientific_identity": member["scientific_identity"],
            "fit_receipt_sha256": member["receipt_ref"]["sha256"], "model_sha256": member["model_sha256"],
            "publication_sha256": member["publication"]["sha256"],
            "original_fit_tuple_sha256": member.get("scientific_tuple_sha256"),
            "producer_pin_group": member["producer_ref"]})
    return result


def entity(identity: str, *, parent=None, family="synthetic-raw-family") -> dict:
    return {"entity_id": identity, "canonical_name": identity, "aliases": [],
        "entity_type": "RESEARCH_BRANCH", "status": "OPEN",
        "specification_fingerprint": rr.sha256_value({"spec": identity}),
        "information_source_fingerprint": rr.sha256_value({"source": identity}),
        "mechanism_fingerprint": rr.sha256_value({"mechanism": identity}),
        "decision_layer": "STATEFUL_ACTION_CONTINUOUS_RESEARCH_ACCOUNT",
        "evidence_source_temporal_status": "FROZEN_PRE2026_RESEARCH_ONLY",
        "excluded_source_refs": ["synthetic://excluded"], "temporal_evidence_limitations": ["synthetic"],
        "post_2025_observation_count": 0, "parent_entity_id": parent,
        "information_family": family, "feature_input_family": family,
        "authoritative_artifact_refs": ["synthetic://authority/" + identity.casefold()]}


def patch(head, operations):
    return {"schema_version": 1, "expected_base_head_sha256": head, "author": "synthetic-author",
        "validation": {"status": "PASS"}, "independent_review": {
            "status": "PASS", "independent": True, "reviewer": "synthetic-reviewer"},
        "event_time_utc": "2025-12-31T00:00:00Z", "operations": operations,
        "operation_count": len(operations), "operations_sha256": rr.sha256_value(operations)}


@pytest.fixture
def fixture(monkeypatch):
    base = Path(os.environ.get("US_TECH_QUANT_TEST_TMP_ROOT",
        "D:/us-tech-quant-cache/V24/V24_A_FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION_R1/registry_synthetic")).resolve()
    token = "".join("jkvz"[int(c, 16) >> 2] + "jkvz"[int(c, 16) & 3] for c in uuid.uuid4().hex)
    scratch = base / token
    assert scratch.parent == base and not scratch.exists()
    scratch.mkdir(parents=True)
    results, run = scratch / "results", scratch / "qualified_reference"
    results.mkdir(); run.mkdir()
    human_path = scratch / "human_request.txt"
    human_path.write_text("synthetic bounded human authorization", encoding="utf-8")
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_RESULTS", results)
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_MANIFEST", results / "A_FINAL_ACTION_COVERAGE_MANIFEST.json")
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_REFERENCE_RUN", run)
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_HUMAN_REQUEST", human_path)
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_HUMAN_SHA", rr.sha256_file(human_path))
    root = scratch / "registry"
    parent = entity(rr._A_FINAL_ACTION_REVIEW_SCOPE["parent_entity_id"])
    result = rr.apply_patch(root, patch(rr.GENESIS, [{"op": "add_entity", "entity": parent}]))
    parent_row = rr.query_registry(root, entity_id=parent["entity_id"])["entities"][0]
    frozen57 = [{"candidate_id": "RAW_s10", "execution_friction": {"one_way_bps": 10}}] + [
        {"candidate_id": "rule_" + str(i), "execution_friction": {"one_way_bps": 10}} for i in range(52)]
    scope = {**rr._A_FINAL_ACTION_REVIEW_SCOPE, "parent_row_hash": parent_row["row_hash"],
        "frozen57_path": str(scratch / "original57.json"),
        "frozen57_sha256": write(scratch / "original57.json", frozen57)["sha256"]}
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_REVIEW_SCOPE", scope)
    original_ids = ["existing_" + str(i) for i in range(37)] + ["R10_HAZARD_LOGISTIC_LOW"]
    census = {"schema": "A_EXISTING_ACTION_ASSET_CENSUS_R1", "task_id": rr._A_FINAL_ACTION_ID,
        "representatives": [{"representative_id": identity, "classification": "A_DIRECT_ACTION_COMPATIBLE",
            "member_slot_ids": [identity + "_slot"]} for identity in original_ids],
        "objects": [{"slot_id": identity + "_slot", "status": "TRAINED", "scientific_identity": "FROZEN_SYNTHETIC",
            "receipt_ref": {"sha256": rr.sha256_value({"receipt": i})}, "model_sha256": rr.sha256_value({"model": i}),
            "publication": {"sha256": rr.sha256_value({"publication": i})},
            "scientific_tuple_sha256": rr.sha256_value({"original_tuple": i}), "producer_ref": "FROZEN_SYNTHETIC"}
            for i, identity in enumerate(original_ids)]}
    census_ref = write(results / "A_EXISTING_ACTION_ASSET_CENSUS.json", census)
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_CENSUS_SHA", census_ref["sha256"])
    source_pins = [pin(Path(rr.__file__).resolve()), pin(Path(rr.__file__).resolve().with_name("research_inventory.py"))]
    prior_source_ref = write(results / "SOURCE_AND_CODE_FREEZE.json", {
        "task_id": rr._A_FINAL_ACTION_ID, "status": "FROZEN_PRE_OUTCOME", "source_pins": source_pins})
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_DECLARATION_SOURCE_REF", prior_source_ref)
    audit = {"candidate_ids": ["RAW_s10"], "namespace": "FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING",
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "certified_market_quote_authority": False, "research_integrity": {"RAW_s10": {
            "groups": {g: True for g in rr._A_FINAL_ACTION_GATES}, "all_passed": True,
            "gate_role": "RESEARCH_INTEGRITY_ONLY"}},
        "unselected_synthetic_economics": {"pnl": "NEVER_DECODE_THIS_VALUE", "returns": [1.2, -3.4]}}
    audit_ref = write(run / "ledgers/stateful/attempt_0001/audit.json", audit)
    config_ref = write(run / "run_config.json", {"task_id": "synthetic-parent", "frozen": True})
    recovery_ref = write(results / "A_R9_ORIGINAL_RECOVERY_AND_ADMISSION.json", {
        "status": "NOT_TESTABLE_CAUSAL_INPUT",
        "specific_reason": "R9_GROSS_FEATURE_PROJECTION_UNBOUND_IN_ORIGINAL_CONTRACT"})
    manifest = {"schema": "A_FINAL_ACTION_COVERAGE_MANIFEST_R1", "task_id": rr._A_FINAL_ACTION_ID,
        "status": "FROZEN_PRE_OUTCOME", "phase0_frozen": True, "2026_locked": True,
        "parent_entity_id": scope["parent_entity_id"], "new_fit_budget": 0, "real_fit_budget": 0,
        "existing_candidate_count": 2, "reference_candidate_id": "RAW_s10",
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "certified_market_quote_authority": False, "test2026": "LOCKED", "MKFG_settlement_authority": "UNKNOWN",
        "candidates": [{"candidate_id": "existing_" + str(i),
            "scientific_tuple_sha256": rr.sha256_value({"tuple": i})} for i in range(2)],
        "reference": {"candidate_id": "RAW_s10", "audit_ref": audit_ref, "config_ref": config_ref,
            "raw_candidate": {"candidate_id": "RAW_s10"}},
        "reference_audit_ref": audit_ref, "reference_run_config_ref": config_ref,
        "census_ref": census_ref,
        "R9_recovery_ref": recovery_ref,
        "source_and_code_freeze_ref": write(results / "sourcefreeze.json", {"frozen": True}),
        "human_authorization_ref": pin(human_path),
        "independent_review_ref": write(results / "phase0review.json", {"status": "PASS"}),
        "source_pins": source_pins,
        "registry_mechanism": copy.deepcopy(rr._A_FINAL_ACTION_REGISTRY_MECHANISM)}
    f = {"root": root, "results": results, "manifest": manifest, "parent": parent_row,
        "audit": audit, "audit_path": Path(audit_ref["path"]), "head": result["head_sha256"], "census": census,
        "frozen57": frozen57, "prior_source_ref": prior_source_ref}
    for candidate in manifest["candidates"]:
        candidate["original_member_refs"] = members_for(f, candidate["candidate_id"])
    try:
        yield f
    finally:
        assert scratch.parent == base and scratch.resolve().is_relative_to(base)
        shutil.rmtree(scratch)


def prepare(f):
    manifest_ref = write(rr._A_FINAL_ACTION_MANIFEST, f["manifest"])
    row = entity(rr._A_FINAL_ACTION_ID, parent=f["parent"]["entity_id"])
    row.pop("authoritative_artifact_refs")
    row["information_source_fingerprint"] = f["parent"]["information_source_fingerprint"]
    row["specification"] = {"final_action_manifest_ref": manifest_ref}
    row["specification_fingerprint"] = rr.sha256_value(row["specification"])
    row["mechanism"] = copy.deepcopy(rr._A_FINAL_ACTION_REGISTRY_MECHANISM)
    row["mechanism_fingerprint"] = rr.sha256_value(row["mechanism"])
    row["metadata"] = {"final_action_manifest_ref": manifest_ref,
        "scientific_identity": rr._A_FINAL_ACTION_REVIEW_SCOPE["scientific_identity"],
        "fit_authority": False, "formal_freeze_authority": False, "source_gate_required": True,
        "strict_PIT_promotion_eligible": False, "production_qualified": False,
        "certified_market_quote_authority": False}
    op = {"op": "add_entity", "entity": row,
        "parent_entity_id": f["parent"]["entity_id"],
        "change_type": rr._A_FINAL_ACTION_REVIEW_SCOPE["change_type"]}
    return op, manifest_ref


def reviewed(f):
    op, manifest_ref = prepare(f)
    decision = rr.preflight_proposal(f["root"], {"candidate": op["entity"],
        "parent_entity_id": op["parent_entity_id"], "change_type": op["change_type"]})
    assert decision["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
    normalized = rr._normalize_entity(op["entity"])
    scope = rr._a_final_action_review_scope(op, normalized, {f["parent"]["entity_id"]: f["parent"]})
    binding = {"schema_version": 1, "research_id": scope["research_id"], "scientific_identity": scope["scientific_identity"],
        "registry_head_sha256": f["head"], "proposal_sha256": decision["proposal_sha256"],
        "candidate_pre_admission_row_hash": scope["candidate_row_hash"],
        "review_operations_subject_sha256": rr.sha256_value([op]),
        "parent_entity_id": scope["parent_entity_id"], "parent_row_hash": scope["parent_row_hash"],
        "frozen_contract_sha256": scope["contract_sha256"], "strict_PIT_promotion_eligible": False,
        "production_qualified": False, "fit_authority": False, "formal_freeze_authority": False,
        "source_gate_required": True, "prior_artifact_reopened": False, "legacy_exposure_retained": True,
        **scope["additional_binding"]}
    human = {**binding, "kind": "HUMAN_AUTHORIZATION_RECORD", "human_user_authorized": True,
        "authorization_source": "CURRENT_HUMAN_REQUEST", "recorded_by": "synthetic-author",
        "human_request_ref": scope["request_path"], "human_request_sha256": scope["request_sha256"],
        scope["human_premise_field"]: True}
    human_ref = write(f["results"] / scope["human_record_filename"], human)
    review = {**binding, "kind": scope["independent_review_kind"], "status": "PASS", "independent": True,
        "author": "synthetic-author", "reviewer": "synthetic-reviewer", "scope": "OPEN_METADATA_ONLY",
        "nonredundancy_basis": scope["nonredundancy_basis"], "human_authorization_sha256": human_ref["sha256"]}
    review_ref = write(f["results"] / scope["review_record_filename"], review)
    op["review_resolution"] = {"kind": scope["resolution_kind"], "automatic_decision": decision,
        "human_authorization_ref": human_ref["path"], "human_authorization_sha256": human_ref["sha256"],
        "independent_review_ref": review_ref["path"], "independent_review_sha256": review_ref["sha256"]}
    return patch(f["head"], [op]), manifest_ref


def scope_for(f):
    op, _ = prepare(f)
    return rr._a_final_action_review_scope(op, rr._normalize_entity(op["entity"]),
        {f["parent"]["entity_id"]: f["parent"]})


def test_reviewed_child_and_runtime_guard_use_existing_immutable_registry(fixture):
    p, ref = reviewed(fixture)
    before = rr.current_state(fixture["root"])["head_sha256"]
    admitted = rr.apply_patch(fixture["root"], p)
    assert admitted["head_sha256"] != before
    accepted = rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref=ref)
    assert accepted["status"] == "PASS" and accepted["new_fit_budget"] == 0
    assert accepted["admission_base_head_sha256"] == before
    assert accepted["strict_PIT_promotion_eligible"] is False


def test_preflight_is_readonly_and_does_not_authorize_overlap(fixture):
    op, _ = prepare(fixture)
    before = (fixture["root"] / "CURRENT.json").read_bytes()
    result = rr.preflight_proposal(fixture["root"], {"candidate": op["entity"],
        "parent_entity_id": op["parent_entity_id"], "change_type": op["change_type"]})
    assert result["status"] == "REVIEW_REQUIRED"
    assert before == (fixture["root"] / "CURRENT.json").read_bytes()


@pytest.mark.parametrize("field,value", [("phase0_frozen", False), ("2026_locked", False),
    ("status", "PLANNED"), ("task_id", "ANOTHER_TASK"), ("parent_entity_id", "ANOTHER_PARENT"),
    ("strict_PIT_promotion_eligible", True), ("production_qualified", True),
    ("certified_market_quote_authority", True), ("test2026", "OPEN"),
    ("MKFG_settlement_authority", "KNOWN"), ("new_fit_budget", 1),
    ("real_fit_budget", False), ("reference_candidate_id", "ANOTHER_BASELINE")])
def test_manifest_cannot_relax_frozen_scope(fixture, field, value):
    fixture["manifest"][field] = value
    with pytest.raises(rr.RegistryError, match="A_FINAL_ACTION_"):
        scope_for(fixture)


@pytest.mark.parametrize("gate", rr._A_FINAL_ACTION_GATES)
@pytest.mark.parametrize("bad", [False, None, "MISSING"])
def test_actual_reference_requires_all_ten_literal_true(fixture, gate, bad):
    groups = fixture["audit"]["research_integrity"]["RAW_s10"]["groups"]
    if bad == "MISSING":
        groups.pop(gate)
    else:
        groups[gate] = bad
    ref = write(fixture["audit_path"], fixture["audit"])
    fixture["manifest"]["reference_audit_ref"] = ref
    fixture["manifest"]["reference"]["audit_ref"] = ref
    with pytest.raises(rr.RegistryError, match="ACTUAL_REFERENCE_TEN_GATES_REQUIRED"):
        scope_for(fixture)


def test_extra_reference_gate_is_not_dropped_by_projection(fixture):
    fixture["audit"]["research_integrity"]["RAW_s10"]["groups"]["UNDECLARED_GATE"] = True
    ref = write(fixture["audit_path"], fixture["audit"])
    fixture["manifest"]["reference_audit_ref"] = ref
    fixture["manifest"]["reference"]["audit_ref"] = ref
    with pytest.raises(rr.RegistryError, match="ACTUAL_REFERENCE_TEN_GATES_REQUIRED"):
        scope_for(fixture)


@pytest.mark.parametrize("count", [0, 37])
def test_original_candidate_cap_accepts_only_bounded_complete_list(fixture, count):
    fixture["manifest"]["candidates"] = [{"candidate_id": "existing_" + str(i),
        "scientific_tuple_sha256": rr.sha256_value({"tuple": i})} for i in range(count)]
    fixture["manifest"]["existing_candidate_count"] = count
    for candidate in fixture["manifest"]["candidates"]:
        candidate["original_member_refs"] = members_for(fixture, candidate["candidate_id"])
    assert scope_for(fixture)["additional_binding"]["existing_candidate_count"] == count


@pytest.mark.parametrize("change", ["cap", "count", "duplicate_id", "duplicate_tuple", "reference", "missing_pin", "bad_pin", "duplicate_pin", "bad_raw", "bad_mechanism", "R9_status"])
def test_identity_custody_and_duplicate_constraints(fixture, change):
    m = fixture["manifest"]
    if change == "cap":
        m["candidates"] = [{"candidate_id": str(i), "scientific_tuple_sha256": rr.sha256_value({"x": i})} for i in range(38)]
        m["existing_candidate_count"] = 38
    elif change == "count": m["existing_candidate_count"] = 1
    elif change == "duplicate_id": m["candidates"][1]["candidate_id"] = m["candidates"][0]["candidate_id"]
    elif change == "duplicate_tuple": m["candidates"][1]["scientific_tuple_sha256"] = m["candidates"][0]["scientific_tuple_sha256"]
    elif change == "reference": m["candidates"][0]["candidate_id"] = "RAW_s10"
    elif change == "missing_pin": m["source_pins"] = m["source_pins"][:1]
    elif change == "bad_pin": m["source_pins"][0]["sha256"] = "0" * 64
    elif change == "duplicate_pin": m["source_pins"].append(copy.deepcopy(m["source_pins"][0]))
    elif change == "bad_raw": m["reference"]["raw_candidate"]["candidate_id"] = "OTHER"
    elif change == "bad_mechanism": m["registry_mechanism"]["new_fit"] = 1
    else: m["R9_recovery_ref"] = write(Path(m["R9_recovery_ref"]["path"]), {"status": "RECOVERED"})
    with pytest.raises(rr.RegistryError, match="A_FINAL_ACTION_"):
        scope_for(fixture)


@pytest.mark.parametrize("decision", ["BLOCKED_CLOSED_BRANCH", "BLOCKED_EXACT_DUPLICATE", "PASS_DISTINCT_INFORMATION_SOURCE", "EXTEND_EXISTING"])
def test_new_scope_cannot_override_other_automatic_decisions(decision):
    with pytest.raises(rr.RegistryError, match="AUTOMATIC_DECISION_REQUIRED"):
        rr._resolve_a_frozen_research_child_review({}, {}, {}, {"decision": decision}, {}, "0" * 64,
            scope=rr._A_FINAL_ACTION_REVIEW_SCOPE)


def test_copied_scope_is_not_owner_authority():
    with pytest.raises(rr.RegistryError, match="SCOPE_NOT_AUTHORIZED"):
        rr._resolve_a_frozen_research_child_review({}, {}, {}, {}, {}, "0" * 64,
            scope=copy.deepcopy(rr._A_FINAL_ACTION_REVIEW_SCOPE))


def test_audit_projection_skips_unselected_values(fixture, monkeypatch):
    original = json.loads
    def observed(value, *args, **kwargs):
        assert b"NEVER_DECODE_THIS_VALUE" not in value if isinstance(value, bytes) else "NEVER_DECODE_THIS_VALUE" not in value
        return original(value, *args, **kwargs)
    monkeypatch.setattr(json, "loads", observed)
    result = rr._a_final_action_audit_projection(fixture["audit_path"])
    assert "unselected_synthetic_economics" not in result


def test_runtime_requires_canonical_admission_and_exact_manifest(fixture):
    p, ref = reviewed(fixture)
    with pytest.raises(rr.RegistryError, match="CANONICAL_ADMISSION_MISSING"):
        rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref=ref)
    rr.apply_patch(fixture["root"], p)
    with pytest.raises(rr.RegistryError, match="CANONICAL_ADMISSION_MISMATCH"):
        rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref={**ref, "sha256": "0" * 64})


def test_unrelated_new_head_does_not_revoke_exact_admission(fixture):
    p, ref = reviewed(fixture)
    first = rr.apply_patch(fixture["root"], p)
    extra = entity("UNRELATED_OPEN", family="another-synthetic-family")
    second = rr.apply_patch(fixture["root"], patch(first["head_sha256"], [{"op": "add_entity", "entity": extra}]))
    result = rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref=ref)
    assert result["registry_head_sha256"] == second["head_sha256"]
    assert result["registry_head_sha256"] != first["head_sha256"]


def test_review_refs_are_revalidated_and_terminal_identity_cannot_reopen(fixture):
    p, ref = reviewed(fixture)
    accepted = rr.apply_patch(fixture["root"], p)
    row = rr.query_registry(fixture["root"], entity_id=rr._A_FINAL_ACTION_ID)["entities"][0]
    changed = {**row["metadata"], "scientific_disposition": "BOUNDED_FINAL_COVERAGE_CLOSED"}
    closed = rr.apply_patch(fixture["root"], patch(accepted["head_sha256"], [
        {"op": "update_entity", "entity": {"entity_id": rr._A_FINAL_ACTION_ID, "metadata": changed}},
        {"op": "close", "entity_id": rr._A_FINAL_ACTION_ID}]))
    with pytest.raises(rr.RegistryError, match="CANONICAL_ADMISSION_MISMATCH"):
        rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref=ref)
    with pytest.raises(rr.RegistryError, match="TERMINAL_ENTITY_IMMUTABLE"):
        rr.apply_patch(fixture["root"], patch(closed["head_sha256"], [
            {"op": "update_entity", "entity": {"entity_id": rr._A_FINAL_ACTION_ID, "status": "OPEN"}}]))


# Actual frozen declaration spellings that the unchanged generic guard rejects.
def original_real_names(f, monkeypatch):
    m = f["manifest"]
    m["candidates"][0]["candidate_id"] = "R10_HAZARD_LOGISTIC_LOW"
    m["candidates"][0]["original_member_refs"] = members_for(f, "R10_HAZARD_LOGISTIC_LOW")
    f["frozen57"][26]["candidate_id"] = "A_ridge_aware_return_shrink_s10"
    frozen_ref = write(Path(rr._A_FINAL_ACTION_REVIEW_SCOPE["frozen57_path"]), f["frozen57"])
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_REVIEW_SCOPE", {**rr._A_FINAL_ACTION_REVIEW_SCOPE,
        "frozen57_sha256": frozen_ref["sha256"]})
    repo = Path(rr.__file__).resolve().parents[2]
    for filename in ("build_inputs.py", "fast_account.py", "shared.py"):
        m["source_pins"].append(pin(repo / "scripts/research/a2/retained/a2_pto_full_compat_20260928_r2" / filename))
    prior = write(Path(f["prior_source_ref"]["path"]), {"task_id": rr._A_FINAL_ACTION_ID,
        "status": "FROZEN_PRE_OUTCOME", "source_pins": m["source_pins"]})
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_DECLARATION_SOURCE_REF", prior)
    rules = [row["candidate_id"] for row in f["frozen57"] if row["candidate_id"] != "RAW_s10"]
    m["statistical_design"] = {"rule_reference_ids": rules, "contrasts": [
        {"candidate": c["candidate_id"], "reference": reference,
         "kind": "PRIMARY" if reference == "RAW_s10" else "RULE_REFERENCE"}
        for c in m["candidates"] for reference in ["RAW_s10", *rules]]}
    return m


def test_real_frozen_names_pass_only_the_task_local_verified_projection(fixture, monkeypatch):
    m = original_real_names(fixture, monkeypatch)
    before = rr.canonical_json(m)
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr._reject_outcome_fields(m)
    result = rr.validate_a_final_action_manifest_metadata(m)
    assert result["status"] == "PASS"
    assert result["generic_firewall_modified"] is False and result["manifest_modified"] is False
    assert rr.canonical_json(m) == before
    assert scope_for(fixture)["additional_binding"]["existing_candidate_count"] == 2


@pytest.mark.parametrize("change", ["unknown_id", "unknown_reference", "reference_order", "contrast_order",
    "member_ordinal", "member_tuple", "member_model", "unknown_source_path", "source_sha", "census_sha"])
def test_task_projection_requires_exact_physical_original_declarations(fixture, monkeypatch, change):
    m = original_real_names(fixture, monkeypatch)
    if change == "unknown_id": m["candidates"][0]["candidate_id"] = "SHARPE_1.2"
    elif change == "unknown_reference": m["statistical_design"]["rule_reference_ids"][25] = "SHARPE_1.2"
    elif change == "reference_order": m["statistical_design"]["rule_reference_ids"].reverse()
    elif change == "contrast_order": m["statistical_design"]["contrasts"].reverse()
    elif change == "member_ordinal": m["candidates"][0]["original_member_refs"][0]["census_object_ordinal"] += 1
    elif change == "member_tuple": m["candidates"][0]["original_member_refs"][0]["original_fit_tuple_sha256"] = "0" * 64
    elif change == "member_model": m["candidates"][0]["original_member_refs"][0]["model_sha256"] = "0" * 64
    elif change == "unknown_source_path":
        extra = fixture["results"] / "SHARPE_1.2.py"
        extra.write_text("# synthetic unapproved source", encoding="utf-8")
        m["source_pins"].append(pin(extra))
    elif change == "source_sha": m["source_pins"][0]["sha256"] = "0" * 64
    else: m["census_ref"]["sha256"] = "0" * 64
    with pytest.raises(rr.RegistryError, match="A_FINAL_ACTION_"):
        rr.validate_a_final_action_manifest_metadata(m)


@pytest.mark.parametrize("location", ["candidate", "member", "source_ref", "contrast", "census_ref", "unrelated"])
@pytest.mark.parametrize("bad", [{"sharpe": 1.2}, {"note": "SHARPE_1.2"}])
def test_unknown_nested_results_are_never_projected_out(fixture, monkeypatch, location, bad):
    m = original_real_names(fixture, monkeypatch)
    target = {"candidate": m["candidates"][0], "member": m["candidates"][0]["original_member_refs"][0],
        "source_ref": m["source_pins"][0], "contrast": m["statistical_design"]["contrasts"][0],
        "census_ref": m["census_ref"], "unrelated": m}[location]
    target["unknown_nested"] = bad
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_(FIELDS|VALUES)_FORBIDDEN"):
        rr.validate_a_final_action_manifest_metadata(m)


def test_verified_candidate_name_in_an_unverified_field_still_rejects(fixture, monkeypatch):
    m = original_real_names(fixture, monkeypatch)
    m["unknown_nested"] = {"note": "R10_HAZARD_LOGISTIC_LOW"}
    with pytest.raises(rr.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN"):
        rr.validate_a_final_action_manifest_metadata(m)



def engineering_fixture(f, monkeypatch, *, admit=False, complete=False):
    code = f["results"].parent / "code/scripts"
    owner = code / "maintenance/research_registry.py"
    inventory = owner.with_name("research_inventory.py")
    main = code / "research/a2/training/stateful_final_action.py"
    replay = main.with_name("stateful_replay.py")
    execution = main.with_name("stateful_execution.py")
    paths = (owner, inventory, main, replay, execution) if complete else (owner, inventory, main, replay)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic original " + path.name, encoding="utf-8")
    monkeypatch.setattr(rr, "__file__", str(owner))
    f["manifest"]["source_pins"] = [pin(path) for path in paths]
    prior = write(Path(f["prior_source_ref"]["path"]), {"task_id": rr._A_FINAL_ACTION_ID,
        "status": "FROZEN_PRE_OUTCOME", "source_pins": f["manifest"]["source_pins"]})
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_DECLARATION_SOURCE_REF", prior)
    old_quote = {"source_pins": {str(replay): "0" * 64, str(inventory): rr.sha256_file(inventory)},
        "rule_definition": {"cash_legality_implies_quote_admission": False}, "population_ref": {"sha256": "1" * 64}}
    old_quote_ref = write(f["results"] / "original_quote.json", old_quote)
    parent_auth = {"quote_domain_ref": old_quote_ref}
    old_session = {"code_pins": {str(owner): "0" * 64, str(execution): "1" * 64,
        str(replay): "2" * 64, str(inventory): rr.sha256_file(inventory)},
        "contract_ref": {"sha256": "3" * 64}, "rule_definition": {"typed_authority_priority": True},
        "candidate_manifest_ref": {"sha256": "4" * 64}, "MKFG_lifecycle_changed": False}
    if complete:
        parent_auth["research_ca_accounting_convention"] = write(f["results"] / "original_session.json", old_session)
    config_ref = write(rr._A_FINAL_ACTION_REFERENCE_RUN / "run_config.json", {"research_account": parent_auth})
    f["manifest"]["reference_run_config_ref"] = config_ref
    f["manifest"]["reference"]["config_ref"] = config_ref
    if admit:
        reviewed_patch, manifest_ref = reviewed(f)
        rr.apply_patch(f["root"], reviewed_patch)
    else:
        _, manifest_ref = prepare(f)
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_ENGINEERING_MANIFEST_SHA", manifest_ref["sha256"])
    run = f["results"].parent / "unique_engineering_run"
    monkeypatch.setattr(rr, "_A_FINAL_ACTION_ENGINEERING_RUN", run)
    run_ref = write(run / "run_config.json", {"final_action_namespace": rr._A_FINAL_ACTION_ID,
        "coverage_manifest_ref": manifest_ref})
    updates = []
    for path in (owner, main):
        before = f["results"] / "runtime_source_before" / path.name
        before.parent.mkdir(parents=True, exist_ok=True); before.write_bytes(path.read_bytes())
        before_ref = pin(before)
        path.write_text("# synthetic engineering descendant " + path.name, encoding="utf-8")
        updates.append({"path": str(path), "before_ref": before_ref,
            "before_sha256": before_ref["sha256"], "after_sha256": rr.sha256_file(path)})
    new_quote = copy.deepcopy(old_quote);new_quote["source_pins"][str(replay)] = rr.sha256_file(replay)
    quote_ref = write(f["results"] / "FINAL_ACTION_QUOTE_DOMAIN_ENGINEERING_ENVELOPE.json", new_quote)
    receipt = {"schema": "A_FINAL_ACTION_ENGINEERING_TRANSPORT_REPAIR_R1", "task_id": rr._A_FINAL_ACTION_ID,
        "scientific_identity": rr._A_FINAL_ACTION_REVIEW_SCOPE["scientific_identity"],
        "scope": rr._A_FINAL_ACTION_ENGINEERING_SCOPE, "manifest_ref": manifest_ref, "run_config_ref": run_ref,
        "new_fit": 0, "new_account_attempts": 0, "strict_PIT_promotion_eligible": False,
        "production_qualified": False, "certified_market_quote_authority": False,
        "source_updates": updates, "quote_domain_ref": quote_ref,
        "source_diff_ref": write(f["results"] / "diff.json", {"synthetic": True}),
        "synthetic_acceptance_ref": write(f["results"] / "synthetic.json", {"status": "PASS"})}
    if complete:
        receipt["scope"] = rr._A_FINAL_ACTION_COMPLETE_ENGINEERING_SCOPE
        new_session = copy.deepcopy(old_session)
        for path in (owner, execution, replay): new_session["code_pins"][str(path)] = rr.sha256_file(path)
        receipt["session_convention_ref"] = write(f["results"] / "FINAL_ACTION_SESSION_CA_ENGINEERING_ENVELOPE.json", new_session)
    review = {"schema": "A_FINAL_ACTION_ENGINEERING_TRANSPORT_INDEPENDENT_REVIEW_R1",
        "task_id": rr._A_FINAL_ACTION_ID, "status": "PASS", "independent": True,
        "author": "synthetic-author", "reviewer": "synthetic-reviewer", "scope": receipt["scope"]}
    bundle = {"receipt": receipt, "review": review, "manifest_ref": manifest_ref,
        "quote": new_quote, "quote_path": Path(quote_ref["path"]), "owner": owner, "complete": complete}
    if complete: bundle["session"] = new_session
    refresh_engineering(f, bundle)
    return bundle


def refresh_engineering(f, bundle):
    prefix = "A_FINAL_ACTION_COMPLETE_RUNTIME" if bundle.get("complete") else "A_FINAL_ACTION_ENGINEERING"
    receipt_ref = write(f["results"] / (prefix + "_TRANSPORT_REPAIR.json"), bundle["receipt"])
    review = bundle["review"]
    review.update(receipt_ref=receipt_ref, manifest_ref=bundle["receipt"]["manifest_ref"],
        run_config_ref=bundle["receipt"]["run_config_ref"])
    review_ref = write(f["results"] / (prefix + "_TRANSPORT_INDEPENDENT_REVIEW.json"), review)
    bundle["envelope_ref"] = write(f["results"] / (prefix + "_SOURCE_CUSTODY.json"), {
        "schema": "A_FINAL_ACTION_ENGINEERING_SOURCE_CUSTODY_R1", "task_id": rr._A_FINAL_ACTION_ID,
        "status": "ACCEPTED_ENGINEERING_BEFORE_ACCOUNT_ATTEMPT", "receipt_ref": receipt_ref,
        "independent_review_ref": review_ref})


def test_engineering_custody_is_physical_exact_and_preserves_original_manifest(fixture, monkeypatch):
    b = engineering_fixture(fixture, monkeypatch)
    before = rr._A_FINAL_ACTION_MANIFEST.read_bytes()
    accepted = rr._a_final_action_engineering_custody(b["envelope_ref"], fixture["manifest"])
    assert accepted["engineering_run_dir"] == str(rr._A_FINAL_ACTION_ENGINEERING_RUN)
    assert accepted["quote_domain_ref"] == b["receipt"]["quote_domain_ref"]
    assert before == rr._A_FINAL_ACTION_MANIFEST.read_bytes()
    with pytest.raises(rr.RegistryError, match="PHYSICAL_CUSTODY_MISMATCH"):
        rr.validate_a_final_action_manifest_metadata(fixture["manifest"])
    assert rr.validate_a_final_action_manifest_metadata(fixture["manifest"],
        engineering_receipt_ref=b["envelope_ref"])["status"] == "PASS"


@pytest.mark.parametrize("change", ["manifest", "run_path", "run_sha", "third_source", "before_sha",
    "before_path", "after_sha", "quote_rule", "quote_other_pin", "quote_replay_pin", "review_status",
    "review_not_independent", "self_review", "new_fit", "attempt", "promotion"])
def test_engineering_custody_rejects_scope_and_source_drift(fixture, monkeypatch, change):
    b = engineering_fixture(fixture, monkeypatch); r = b["receipt"]
    if change == "manifest": r["manifest_ref"] = {**r["manifest_ref"], "sha256": "0" * 64}
    elif change == "run_path": r["run_config_ref"] = write(fixture["results"] / "another_run.json", {})
    elif change == "run_sha": r["run_config_ref"]["sha256"] = "0" * 64
    elif change == "third_source": r["source_updates"][1]["path"] = str(b["owner"].with_name("research_inventory.py"))
    elif change == "before_sha": r["source_updates"][0]["before_sha256"] = "0" * 64
    elif change == "before_path": r["source_updates"][0]["before_ref"] = pin(b["owner"])
    elif change == "after_sha": r["source_updates"][0]["after_sha256"] = "0" * 64
    elif change.startswith("quote_"):
        if change == "quote_rule": b["quote"]["rule_definition"]["cash_legality_implies_quote_admission"] = True
        elif change == "quote_other_pin": b["quote"]["source_pins"][str(b["owner"].with_name("research_inventory.py"))] = "0" * 64
        else: b["quote"]["source_pins"][str(b["owner"].parents[1] / "research/a2/training/stateful_replay.py")] = "0" * 64
        r["quote_domain_ref"] = write(b["quote_path"], b["quote"])
    elif change == "review_status": b["review"]["status"] = "PENDING"
    elif change == "review_not_independent": b["review"]["independent"] = False
    elif change == "self_review": b["review"]["reviewer"] = b["review"]["author"]
    elif change == "new_fit": r["new_fit"] = 1
    elif change == "attempt": r["new_account_attempts"] = 1
    else: r["production_qualified"] = True
    refresh_engineering(fixture, b)
    with pytest.raises(rr.RegistryError, match="A_FINAL_ACTION_"):
        rr._a_final_action_engineering_custody(b["envelope_ref"], fixture["manifest"])


def test_runtime_engineering_metadata_is_stripped_from_original_review_subject(fixture, monkeypatch):
    b = engineering_fixture(fixture, monkeypatch, admit=True)
    row = rr.query_registry(fixture["root"], entity_id=rr._A_FINAL_ACTION_ID)["entities"][0]
    metadata = {**row["metadata"], "engineering_receipt_ref": b["envelope_ref"]}
    head = rr.current_state(fixture["root"])["head_sha256"]
    rr.apply_patch(fixture["root"], patch(head, [{"op": "update_entity",
        "entity": {"entity_id": rr._A_FINAL_ACTION_ID, "metadata": metadata}}]))
    actual = rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref=b["manifest_ref"])
    assert actual["status"] == "PASS" and actual["quote_domain_ref"] == b["receipt"]["quote_domain_ref"]
    assert actual["engineering_run_dir"] == str(rr._A_FINAL_ACTION_ENGINEERING_RUN)
    assert actual["manifest_sha256"] == b["manifest_ref"]["sha256"]



def test_complete_runtime_custody_rebinds_only_three_session_code_pins(fixture, monkeypatch):
    b = engineering_fixture(fixture, monkeypatch, complete=True)
    original = rr._A_FINAL_ACTION_MANIFEST.read_bytes()
    actual = rr._a_final_action_engineering_custody(b["envelope_ref"], fixture["manifest"])
    assert actual["session_convention_ref"] == b["receipt"]["session_convention_ref"]
    assert original == rr._A_FINAL_ACTION_MANIFEST.read_bytes()
    assert rr.validate_a_final_action_manifest_metadata(fixture["manifest"], engineering_receipt_ref=b["envelope_ref"])["status"] == "PASS"


@pytest.mark.parametrize("change", ["fourth_pin", "registry_pin", "execution_pin", "replay_pin",
    "rule", "candidate_manifest", "terminal_flag", "extra_key", "missing_session", "session_path",
    "wrong_scope", "source_missing_key"])
def test_complete_runtime_custody_rejects_session_semantic_or_pin_drift(fixture, monkeypatch, change):
    b = engineering_fixture(fixture, monkeypatch, complete=True);r = b["receipt"]
    code = b["owner"].parents[1];session = b["session"]
    if change == "fourth_pin": session["code_pins"][str(b["owner"].with_name("research_inventory.py"))] = "0" * 64
    elif change == "registry_pin": session["code_pins"][str(b["owner"])] = "0" * 64
    elif change == "execution_pin": session["code_pins"][str(code / "research/a2/training/stateful_execution.py")] = "0" * 64
    elif change == "replay_pin": session["code_pins"][str(code / "research/a2/training/stateful_replay.py")] = "0" * 64
    elif change == "rule": session["rule_definition"]["typed_authority_priority"] = False
    elif change == "candidate_manifest": session["candidate_manifest_ref"]["sha256"] = "0" * 64
    elif change == "terminal_flag": session["MKFG_lifecycle_changed"] = True
    elif change == "extra_key": session["arbitrary"] = True
    elif change == "missing_session": r.pop("session_convention_ref")
    elif change == "session_path": r["session_convention_ref"] = write(fixture["results"] / "another_session.json", session)
    elif change == "wrong_scope": r["scope"] = rr._A_FINAL_ACTION_ENGINEERING_SCOPE
    else:
        session["code_pins"].pop(str(code / "research/a2/training/stateful_execution.py"))
    if "session_convention_ref" in r and change != "session_path":
        r["session_convention_ref"] = write(Path(r["session_convention_ref"]["path"]), session)
    refresh_engineering(fixture, b)
    with pytest.raises(rr.RegistryError, match="A_FINAL_ACTION_"):
        rr._a_final_action_engineering_custody(b["envelope_ref"], fixture["manifest"])


def test_runtime_complete_metadata_keeps_original_admission_and_budget(fixture, monkeypatch):
    b = engineering_fixture(fixture, monkeypatch, admit=True, complete=True)
    row = rr.query_registry(fixture["root"], entity_id=rr._A_FINAL_ACTION_ID)["entities"][0]
    head = rr.current_state(fixture["root"])["head_sha256"]
    rr.apply_patch(fixture["root"], patch(head, [{"op": "update_entity", "entity": {
        "entity_id": rr._A_FINAL_ACTION_ID, "metadata": {**row["metadata"], "engineering_receipt_ref": b["envelope_ref"]}}}]))
    result = rr.verify_a_final_action_admission(fixture["root"], final_action_manifest_ref=b["manifest_ref"])
    assert result["status"] == "PASS" and result["new_fit_budget"] == 0
    assert result["session_convention_ref"] == b["receipt"]["session_convention_ref"]
    assert result["manifest_sha256"] == b["manifest_ref"]["sha256"]
