"""Synthetic admission tests; no real data, training, account or provider."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from scripts.maintenance import research_registry as rr


@pytest.fixture
def tmp_path():
    base = Path(os.environ.get("US_TECH_QUANT_TEST_TMP_ROOT", "D:/us-tech-quant-cache")).resolve()
    token = "".join("abcd"[int(ch, 16) >> 2] + "abcd"[int(ch, 16) & 3] for ch in uuid.uuid4().hex)
    root = base / token
    assert root.parent == base and not root.exists()
    root.mkdir()
    try:
        yield root
    finally:
        assert root.resolve().parent == base
        shutil.rmtree(root)


def fp(value):
    return rr.sha256_value({"identity": value})


def entity(name, status="ACTIVE", *, information=None):
    return {
        "entity_id": name, "canonical_name": name, "entity_type": "RESEARCH_BRANCH",
        "status": status, "specification_fingerprint": fp("spec:" + name),
        "information_source_fingerprint": information or fp("input:" + name),
        "mechanism_fingerprint": fp("mechanism:" + name), "decision_layer": "REFERENCE",
        "evidence_source_temporal_status": "PRE2026_ONLY",
        "excluded_source_refs": [], "temporal_evidence_limitations": ["SYNTHETIC_ONLY"],
        "post_2025_observation_count": 0, "trial_ledger_failure_row_count": 0,
        "parent_entity_id": None,
    }


def patch(base, operations):
    return {
        "schema_version": 1, "expected_base_head_sha256": base, "author": "synthetic-author",
        "event_time_utc": "2025-12-31T00:00:00Z", "validation": {"status": "PASS"},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": "synthetic-reviewer"},
        "operation_count": len(operations), "operations_sha256": rr.sha256_value(operations),
        "operations": operations,
    }


def write(path, value):
    path.write_bytes(rr.canonical_json(value) + b"\n")
    return str(path), rr.sha256_file(path)


def prepared(tmp_path, stage="R6", *, old_source_name=None):
    root = tmp_path / "registry"
    parent = entity("RAW_A2_BROAD_OOF_PREDICTIONS", information=rr.A_BREADTH_REVIEW_INFORMATION_SHA256)
    parent["information_family"] = "frozen-r1-continuation-source32-and-current-account-state"
    old = [entity("ACTION_ML_BUY_SELL_SIZING", "CLOSED"),
           entity("GENERIC_MARKET_RISK_GROSS_OVERLAYS", "CLOSED")]
    bootstrap = patch(rr.GENESIS, [{"op": "add_entity", "entity": item} for item in [parent, *old]])
    bootstrap.update({"patch_purpose": "AUDITED_INVENTORY_BOOTSTRAP",
                      "pinned_bootstrap_source_sha256": fp("synthetic-bootstrap"),
                      "pinned_outcome_blind_inventory_sha256": fp("synthetic-inventory")})
    rr.apply_patch(root, bootstrap)
    identity = next(key for key in rr.A_DECISION_REVIEW_SCOPES if key.endswith("_" + stage))
    limits = rr.A_DECISION_REVIEW_SCOPES[identity]
    pins = {}
    script = tmp_path / "training.py"
    script.write_text("# synthetic source\n", encoding="utf-8")
    pins[str(script)] = rr.sha256_file(script)
    if old_source_name is not None:
        source_dir = tmp_path / "a2_pto_full_compat_20260928_r2"
        source_dir.mkdir()
        script = source_dir / old_source_name
        script.write_text("# synthetic old producer source\n", encoding="utf-8")
        pins = {str(script): rr.sha256_file(script)}
    docs = {}
    for name, value in [
        ("frozen_spec", {"status": "FROZEN_SYNTHETIC", "label_contract": "FROZEN_PRE2026"}),
        ("input_manifest", {"status": "FROZEN_SYNTHETIC", "cutoff_exclusive": "2026-01-01"}),
        ("future_candidates", {"candidates": [{"candidate_id": f"candidate_{i:02d}"}
                                               for i in range(limits["future_candidate_count"])]}),
    ]:
        docs[name + "_ref"], docs[name + "_sha256"] = write(tmp_path / (name + ".json"), value)
    user = tmp_path / "user_attachment.txt"
    user.write_text("Synthetic human authorization for supervised pre2026 research only.\n", encoding="utf-8")
    docs.update({"user_attachment_ref": str(user), "user_attachment_sha256": rr.sha256_file(user)})
    if old_source_name is not None:
        full_spec = {"schema_id": "A_R6_R7_FROZEN_SUPERVISED_SPECIFICATION_R1",
                     "source_pins": pins, "label_contract": "FROZEN_PRE2026"}
        docs["frozen_spec_ref"], docs["frozen_spec_sha256"] = write(Path(docs["frozen_spec_ref"]), full_spec)
        pins = {"frozen_spec_ref": docs["frozen_spec_ref"], "frozen_spec_sha256": docs["frozen_spec_sha256"],
                "pinset_sha256": rr.sha256_value(full_spec["source_pins"])}
    old_row = rr.query_registry(root, entity_id=limits["prior_comparison"])["entities"][0]
    specification = {**rr.A_DECISION_REVIEW_CONSTRAINTS,
                     **{key: limits[key] for key in ("model_year_attempt_cap", "physical_fit_attempt_cap", "future_candidate_count")},
                     "frozen_spec_sha256": docs["frozen_spec_sha256"]}
    mechanism = {"objective_structure": limits["objective_structure"],
                 "label_contract_sha256": fp("synthetic-label-contract"), "policy_parameters_frozen": True}
    candidate = entity(identity, "OPEN", information=rr.A_BREADTH_REVIEW_INFORMATION_SHA256)
    candidate.update({
        "decision_layer": limits["decision_layer"], "parent_entity_id": parent["entity_id"],
        "specification_fingerprint": rr.sha256_value(specification),
        "mechanism_fingerprint": rr.sha256_value(mechanism),
        "metadata": {**docs, **rr.A_DECISION_REVIEW_PERMISSIONS,
                     "specification": specification, "mechanism": mechanism,
                     "information_family": parent["information_family"], "training_source_pins": pins,
                     "prior_comparison_rows": [{
                         "entity_id": old_row["entity_id"], "status": "CLOSED", "row_hash": old_row["row_hash"],
                         "relationship": "PRIOR_NEGATIVE_COMPARISON_NOT_TRAINING_PARENT",
                         "prior_artifact_reopened": False, "prior_conclusion_retained": True,
                     }]},
    })
    operation = {"op": "add_entity", "entity": candidate,
                 "change_type": "EXPLICIT_HUMAN_A_NEW_SUPERVISED_DECISION_STRUCTURE",
                 "parent_entity_id": parent["entity_id"]}
    proposal = {"candidate": candidate, "change_type": operation["change_type"], "parent_entity_id": parent["entity_id"]}
    ready = rr.a_decision_review_binding(root, proposal=proposal, operation=operation)
    binding = ready["review_binding"]
    human = {**binding, "kind": "HUMAN_AUTHORIZATION_RECORD", "human_user_authorized": True,
             "authorization_source": "CURRENT_HUMAN_REQUEST", "recorded_by": "synthetic-author",
             "human_request_sha256": docs["user_attachment_sha256"]}
    human_ref, human_sha = write(tmp_path / f"A_{stage}_REGISTRY_HUMAN_AUTHORIZATION.json", human)
    review = {**binding, "kind": "INDEPENDENT_A_DECISION_REGISTRY_REVIEW", "status": "PASS",
              "independent": True, "author": "synthetic-author", "reviewer": "synthetic-reviewer",
              "nonredundancy_basis": "NEW_FROZEN_DIRECT_DECISION_TARGET_STRUCTURE",
              "prior_artifact_reopened": False, "legacy_exposure_retained": True,
              "source_fingerprint_is_bank_custody_only": True, "human_authorization_sha256": human_sha}
    review_ref, review_sha = write(tmp_path / f"A_{stage}_REGISTRY_INDEPENDENT_REVIEW.json", review)
    operation["review_resolution"] = {
        "kind": "A_DIRECT_DECISION_SUPERVISED_PRE2026", "automatic_decision": ready["automatic_decision"],
        "human_authorization_ref": human_ref, "human_authorization_sha256": human_sha,
        "independent_review_ref": review_ref, "independent_review_sha256": review_sha,
    }
    return root, candidate, operation, proposal, ready, patch(binding["registry_head_sha256"], [operation])


def refresh(patch_value):
    patch_value["operations_sha256"] = rr.sha256_value(patch_value["operations"])


@pytest.mark.parametrize("stage", ["R6", "R7"])
def test_exact_supervised_admission_preserves_closed_and_account_block(tmp_path, stage):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path, stage)
    before = {key: rr.query_registry(root, entity_id=key)["entities"][0]["row_hash"]
              for key in ["ACTION_ML_BUY_SELL_SIZING", "GENERIC_MARKET_RISK_GROSS_OVERLAYS"]}
    assert ready["automatic_decision"]["decision"] == "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"
    rr.apply_patch(root, value)
    metadata = candidate["metadata"]
    actual = rr.verify_a_decision_admission(
        root, research_id=candidate["entity_id"], frozen_spec_sha256=metadata["frozen_spec_sha256"],
        input_manifest_sha256=metadata["input_manifest_sha256"], training_source_pins=metadata["training_source_pins"])
    assert actual["status"] == "PASS"
    assert actual["admission"] == "SUPERVISED_PRE2026_NO_ACCOUNT"
    assert actual["supervised_fit_authority"] is True
    assert actual["real_account_authority"] is False and actual["source_activation_authority"] is False
    assert actual["branch_N_adopted"] is False and actual["test2026_locked"] is True
    for key, digest in before.items():
        row = rr.query_registry(root, entity_id=key)["entities"][0]
        assert row["status"] == "CLOSED" and row["row_hash"] == digest
    assert rr.validate_registry(root)["status"] == "PASS"


@pytest.mark.parametrize("field,bad", [
    ("model_year_attempt_cap", 46), ("physical_fit_attempt_cap", 82), ("future_candidate_count", 16),
    ("grid_count", 1), ("optuna_count", 1), ("seed_count", 2), ("scientific_retry_count", 1),
    ("raw_a2_membership_frozen", False), ("raw_a2_rank_frozen", False), ("stock_q_frozen", False),
    ("RL_allowed", True), ("real_account_count", 1), ("test2026_locked", False),
    ("cutoff_exclusive", "2027-01-01"), ("annual_years", [2024, 2025, 2026]),
])
def test_constraint_mutations_fail_closed(tmp_path, field, bad):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    candidate["metadata"]["specification"][field] = bad
    candidate["specification_fingerprint"] = rr.sha256_value(candidate["metadata"]["specification"])
    refresh(value)
    with pytest.raises(rr.RegistryError):
        rr.apply_patch(root, value)


@pytest.mark.parametrize("field,bad", [
    ("real_account_authority", True), ("source_activation_authority", True), ("branch_N_adopted", True),
    ("strict_PIT_promotion_eligible", True), ("formal_freeze_authority", True),
    ("supervised_fit_authority", None), ("test2026_locked", None),
])
def test_permission_mutations_fail_closed(tmp_path, field, bad):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    candidate["metadata"][field] = bad
    refresh(value)
    with pytest.raises(rr.RegistryError, match="AUTHORITY_FORBIDDEN"):
        rr.apply_patch(root, value)


@pytest.mark.parametrize("prefix", ["frozen_spec", "input_manifest", "future_candidates", "user_attachment"])
def test_custody_tamper_rejected(tmp_path, prefix):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    Path(candidate["metadata"][prefix + "_ref"]).write_text("{}", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="CUSTODY_SHA256_MISMATCH"):
        rr.apply_patch(root, value)


def test_source_tamper_rejected(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    Path(next(iter(candidate["metadata"]["training_source_pins"]))).write_text("# changed\n", encoding="utf-8")
    with pytest.raises(rr.RegistryError, match="CUSTODY_SHA256_MISMATCH"):
        rr.apply_patch(root, value)


def test_future_candidate_count_and_identity_are_real(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    manifest = Path(candidate["metadata"]["future_candidates_ref"])
    candidate["metadata"]["future_candidates_ref"], candidate["metadata"]["future_candidates_sha256"] = write(manifest, {"candidates": []})
    refresh(value)
    with pytest.raises(rr.RegistryError, match="FUTURE_CANDIDATE_COUNT_MISMATCH"):
        rr.apply_patch(root, value)


@pytest.mark.parametrize("bad_parent", ["ACTION_ML_BUY_SELL_SIZING", "NONEXISTENT_PARENT"])
def test_actual_terminal_or_unknown_parent_is_not_hidden(tmp_path, bad_parent):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    candidate["parent_entity_id"] = bad_parent
    operation["parent_entity_id"] = bad_parent
    proposal["parent_entity_id"] = bad_parent
    decision = rr.preflight_proposal(root, proposal)
    assert decision["decision"] in {"BLOCKED_CLOSED_BRANCH", "REVIEW_REQUIRED_INSUFFICIENT_EVIDENCE"}
    refresh(value)
    with pytest.raises(rr.RegistryError):
        rr.apply_patch(root, value)


def test_old_closed_entities_cannot_be_updated(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    old = rr.query_registry(root, entity_id="ACTION_ML_BUY_SELL_SIZING")["entities"][0]
    bad = patch(ready["review_binding"]["registry_head_sha256"], [{
        "op": "update_entity", "entity": {"entity_id": old["entity_id"], "status": "ACTIVE"}}])
    with pytest.raises(rr.RegistryError, match="TERMINAL_ENTITY_IMMUTABLE"):
        rr.apply_patch(root, bad)


@pytest.mark.parametrize("field,bad", [("human_user_authorized", False), ("human_request_sha256", "a"*64)])
def test_human_authority_is_physically_bound(tmp_path, field, bad):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    resolution = operation["review_resolution"]
    path = Path(resolution["human_authorization_ref"])
    human = json.loads(path.read_text(encoding="utf-8")); human[field] = bad
    resolution["human_authorization_ref"], resolution["human_authorization_sha256"] = write(path, human)
    refresh(value)
    with pytest.raises(rr.RegistryError, match="HUMAN_AUTHORIZATION_REQUIRED"):
        rr.apply_patch(root, value)


def test_automatic_blocked_is_not_overridden(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    candidate["derived_from_entity_id"] = "ACTION_ML_BUY_SELL_SIZING"
    refresh(value)
    assert rr.preflight_proposal(root, proposal)["decision"] == "BLOCKED_CLOSED_BRANCH"
    with pytest.raises(rr.RegistryError, match="PROPOSAL_NOT_APPLYABLE:BLOCKED_CLOSED_BRANCH"):
        rr.apply_patch(root, value)


def test_runtime_identity_or_source_callers_cannot_self_certify(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    metadata = candidate["metadata"]
    with pytest.raises(rr.RegistryError, match="CANONICAL_ADMISSION_MISSING"):
        rr.verify_a_decision_admission(root, research_id=candidate["entity_id"],
            frozen_spec_sha256=metadata["frozen_spec_sha256"], input_manifest_sha256=metadata["input_manifest_sha256"],
            training_source_pins=metadata["training_source_pins"])
    rr.apply_patch(root, value)
    with pytest.raises(rr.RegistryError, match="CANONICAL_ADMISSION_MISMATCH"):
        rr.verify_a_decision_admission(root, research_id=candidate["entity_id"],
            frozen_spec_sha256="b"*64, input_manifest_sha256=metadata["input_manifest_sha256"],
            training_source_pins=metadata["training_source_pins"])


def test_no_generic_review_override(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    candidate["entity_id"] = candidate["canonical_name"] = "UNAUTHORIZED_SUPERVISED_BRANCH"
    refresh(value)
    with pytest.raises(rr.RegistryError):
        rr.apply_patch(root, value)


def test_runtime_reports_current_head_after_unrelated_admission(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path)
    first = rr.apply_patch(root, value)
    other = entity("UNRELATED_NEW_SOURCE")
    other.update({"information_family": "different-synthetic-input",
                  "authoritative_artifact_refs": ["synthetic://different-input-contract"]})
    newest = rr.apply_patch(root, patch(first["head_sha256"], [{"op": "add_entity", "entity": other}]))
    metadata = candidate["metadata"]
    actual = rr.verify_a_decision_admission(root, research_id=candidate["entity_id"],
        frozen_spec_sha256=metadata["frozen_spec_sha256"], input_manifest_sha256=metadata["input_manifest_sha256"],
        training_source_pins=metadata["training_source_pins"])
    assert actual["registry_head_sha256"] == newest["head_sha256"]
    assert actual["admission_base_head_sha256"] == ready["review_binding"]["registry_head_sha256"]


@pytest.mark.parametrize("old_source_name", ["shared.py", "build_inputs.py"])
def test_source_pin_frozen_spec_reference_keeps_old_r2_paths_under_generic_firewall(tmp_path, old_source_name):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path, old_source_name=old_source_name)
    declared = candidate["metadata"]["training_source_pins"]
    assert ready["review_binding"]["training_source_pins"] == declared
    normalized = json.loads(Path(declared["frozen_spec_ref"]).read_text(encoding="utf-8"))["source_pins"]
    rr.apply_patch(root, value)
    metadata = candidate["metadata"]
    actual = rr.verify_a_decision_admission(root, research_id=candidate["entity_id"],
        frozen_spec_sha256=metadata["frozen_spec_sha256"], input_manifest_sha256=metadata["input_manifest_sha256"],
        training_source_pins=normalized)
    assert actual["training_source_pins"] == normalized
    assert actual["custody_sha256"] == ready["review_binding"]["custody_sha256"]
    wrong = {key: "b"*64 for key in normalized}
    with pytest.raises(rr.RegistryError, match="CANONICAL_ADMISSION_MISMATCH"):
        rr.verify_a_decision_admission(root, research_id=candidate["entity_id"],
            frozen_spec_sha256=metadata["frozen_spec_sha256"], input_manifest_sha256=metadata["input_manifest_sha256"],
            training_source_pins=wrong)


def test_frozen_source_pinset_digest_cannot_be_guessed(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path, old_source_name="shared.py")
    candidate["metadata"]["training_source_pins"]["pinset_sha256"] = "c"*64
    refresh(value)
    with pytest.raises(rr.RegistryError, match="SOURCE_PINSET_SHA256_MISMATCH"):
        rr.apply_patch(root, value)


def test_frozen_source_descriptor_cannot_point_to_other_spec(tmp_path):
    root, candidate, operation, proposal, ready, value = prepared(tmp_path, old_source_name="shared.py")
    candidate["metadata"]["training_source_pins"]["frozen_spec_ref"] = candidate["metadata"]["input_manifest_ref"]
    refresh(value)
    with pytest.raises(rr.RegistryError, match="SOURCE_SPEC_REFERENCE_MISMATCH"):
        rr.apply_patch(root, value)
