"""C14 postdecision H5 gate over the byte-identical frozen projection owner.

Only gates/research receipt identity are rebound. Numeric projection, exact
CUSIP continuity, event flags and H5 maturity remain the original owner code.
No C13 design, bank, run authority or contract is consumed.
"""
from __future__ import annotations
import json
from pathlib import Path
from scripts.research.a2.data import selector_constrained_outcomes as owner
from scripts.research.a2.data import selector_maximal_risk_binding as binding
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as evidence
from scripts.research.a2.risk.event_risk_contract_r5 import bind_pinned_kernel
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

ID = binding.contract.ID
OLD_ML_GATE_SHA = "7d68b43b9ee7d63b35f80fa8515f19dc007a167c5e7eba53e2dcde905be52fed"
TERMINAL = {"COMPLETE","FAILED_UNTESTABLE","BLOCKED_INPUT","BLOCKED_BY_CURRENT_B_SCOPE","BLOCKED_BUDGET"}
OWNER_SHA = "db41eea99bdc80eb158bf2d978fde43cac9905517492402e9fe977bc01dfb252"
RUN = binding.RUN
need = binding.need
AI = Path("D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/cache")
H5_REFS = {
    "labels": dict(path="D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/cache/five_day_shareholder_targets.parquet", sha256=owner.SOURCE_SHA["labels"]),
    "identity": dict(path=str(AI/"value_training_panel_shareholder_pitguarded_r1.parquet"), sha256=owner.SOURCE_SHA["identity"]),
    "membership": dict(path="D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/universe/daily_eligible_universe_membership.parquet", sha256=owner.SOURCE_SHA["membership"]),
    "calendar": dict(path=str(AI/"calendar_r1.parquet"), sha256=owner.SOURCE_SHA["calendar"]),
}


def read_ref(ref, *, root=None):
    need(isinstance(ref, dict) and set(ref) == {"path","sha256"}, "EXACT_C14_GATE_REFERENCE_REQUIRED")
    path = Path(ref["path"])
    need(path.is_absolute() and path.drive.upper() == "D:", "D_GATE_CUSTODY_REQUIRED")
    if root is not None:
        need(path.resolve().is_relative_to(Path(root).resolve()), "C14_RUN_OWNED_GATE_REQUIRED")
    need(binding.sha(path) == ref["sha256"], "C14_GATE_PHYSICAL_SHA_CHANGED")
    return json.loads(path.read_text(encoding="utf-8"))


def gates(design_ref, review_ref, decision_gate_ref, keys):
    """Require full terminal C14 decisions before the original numeric reader."""
    need(Path(design_ref["path"]).resolve() == (RUN/"DESIGN_FREEZE.json").resolve()
         and design_ref["sha256"] == binding.DESIGN_SHA, "EXACT_C14_DESIGN_AUTHORITY_REQUIRED")
    design = read_ref(design_ref, root=RUN)
    review = read_ref(review_ref, root=RUN)
    gate = read_ref(decision_gate_ref, root=RUN)
    evidence.validate_design(design)
    need(review.get("status") == "PASS" and review.get("research_id") == ID,
         "C14_INDEPENDENT_INPUT_EXECUTION_REVIEW_REQUIRED")
    pins = review.get("source_pins", {})
    required_owners = (owner,owner.owner,owner.identity_owner,owner.namespace_owner,evidence)
    for module in required_owners:
        path = str(Path(module.__file__).resolve())
        need(path in design["sources"] and pins.get(path) == design["sources"][path]
             == binding.sha(path), "COMPLETE_FROZEN_H5_READER_CLOSURE_REQUIRED")
    for module, expected in ((owner, OWNER_SHA), (binding, review.get("adapter_sha256"))):
        path = Path(module.__file__).resolve()
        need(pins.get(str(path)) == expected == binding.sha(path), "EXACT_C14_H5_OWNER_REVIEW_REQUIRED")
    own = Path(__file__).resolve()
    need(pins.get(str(own)) == binding.sha(own), "EXACT_C14_H5_GATE_REVIEW_REQUIRED")
    for path, digest in pins.items():
        source = Path(path)
        need(source.is_absolute() and source.resolve().is_relative_to(own.parents[4])
             and source.suffix == ".py" and binding.sha(source) == digest, "REVIEWED_SOURCE_CLOSURE_CHANGED")
    need(gate.get("status") == "PASS" and gate.get("research_id") == ID
         and gate.get("design_sha256") == binding.DESIGN_SHA
         and gate.get("review_ref") == review_ref
         and gate.get("decision_frozen") is True and gate.get("outcome_reads_before_gate") == 0
         and gate.get("requested_keys_sha256") == content_hash(keys)
         and gate.get("test2026_rows_read") == 0
         and gate.get("strict_PIT_promotion_eligible") is False,
         "C14_EXACT_TERMINAL_DECISION_AND_KEY_FREEZE_REQUIRED")
    assembly = read_ref(gate["score_assembly_ref"], root=RUN)
    final = read_ref(gate["final_pipeline_ref"], root=RUN)
    evidence.validate_final_pipeline_gate(design, final, assembly, binding.DESIGN_SHA)
    need(set(final["role_statuses"].values()) <= TERMINAL, "ALL_RISK_ROLES_EXACT_TERMINAL_STATUS_REQUIRED")
    need(final["score_assembly_sha256"] == gate["score_assembly_ref"]["sha256"]
         and gate.get("all_applicable_risk_roles_terminal") is True
         and gate.get("full_calendar_count") == 752 and gate.get("mature_count") == 732
         and gate.get("progressive_mature_count") == 482,
         "COMPLETE_ORIGINAL_RISK_CLOCK_AND_TERMINAL_GATE_REQUIRED")
    delta = gate["risk_delta_ref"]
    path = Path(delta["path"])
    need(path.resolve() == (RUN/"RISK_EXECUTION_DELTA.jsonl").resolve()
         and binding.sha(path) == delta["sha256"], "TERMINAL_CONDITIONAL_DELTA_PIN_REQUIRED")
    need(gate.get("original_ml_gate_ref",{}).get("path") == str(RUN/"FINAL_PIPELINES_FREEZE.json"),
         "ORIGINAL_ML_GATE_PRESERVATION_REQUIRED")
    need(gate["original_ml_gate_ref"]["sha256"] == OLD_ML_GATE_SHA, "ORIGINAL_ML_GATE_IMMUTABLE_PIN_REQUIRED")
    old_ml = read_ref(gate["original_ml_gate_ref"],root=RUN)
    evidence._gate(old_ml,binding.DESIGN_SHA)
    need(gate.get("h5_sources") == H5_REFS, "ORIGINAL_FOUR_H5_SOURCES_NO_SUBSTITUTION")
    need(set(H5_REFS) == set(owner.SOURCE_SHA)
         and all(ref["sha256"] == owner.SOURCE_SHA[name] for name,ref in H5_REFS.items()),
         "ORIGINAL_H5_SOURCE_PINS_REQUIRED")
    return design, H5_REFS


def read_h5(design_ref, review_ref, decision_gate_ref, requested_keys):
    """Run the original projection/qualification body after only a C14 gate."""
    need(binding.sha(owner.__file__) == OWNER_SHA, "ORIGINAL_H5_PROJECTION_SOURCE_CHANGED")
    kernel = bind_pinned_kernel(owner.read_h5, physical_path=owner.__file__,
        expected_sha256=OWNER_SHA, dependencies=dict(gates=gates, RESEARCH_ID=ID))
    result, receipt = kernel(design_ref,review_ref,decision_gate_ref,requested_keys)
    need(receipt.get("research_id") == ID and receipt.get("test2026_reads") == 0
         and receipt.get("outcome_reads_before_gate") == 0
         and receipt.get("new_fits") == 0 and receipt.get("new_state_estimations") == 0,
         "C14_POSTDECISION_H5_LOCKS_REQUIRED")
    receipt = dict(receipt, schema="C14_POSTDECISION_H5_SOURCE_RECEIPT_V1",
        kernel_receipt_schema=receipt["schema"],
        projection_owner_ref=dict(path=str(Path(owner.__file__).resolve()),sha256=OWNER_SHA),
        gate_owner_ref=dict(path=str(Path(__file__).resolve()),sha256=binding.sha(__file__)),
        original_kernel_code_reused=True, original_module_globals_unchanged=True,
        C13_contract_or_bank_authority_used=False)
    return result,receipt

