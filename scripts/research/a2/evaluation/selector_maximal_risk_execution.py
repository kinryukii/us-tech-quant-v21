"""Finite C14 conditional decision continuation over already reviewed owners.

No old ML training/evaluation/report path is called. Native input qualification
precedes any reservation/label. This ends at a new terminal decision gate; joint
postdecision evidence is a separate additive delivery, never a C14-complete claim.
"""
from __future__ import annotations
import argparse
import json
import traceback
from pathlib import Path
from contextlib import contextmanager
from copy import deepcopy
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_maximal_breadth as ctl
from scripts.research.a2.training import selector_maximal_risk_journal as journal_owner
from scripts.research.a2.training import selector_maximal_risk_hybrids as hybrids
from scripts.research.a2.training import selector_maximal_risk_membership as membership
from scripts.research.a2.training import selector_maximal_breadth_estimators as kernel
from scripts.research.a2.data import selector_maximal_risk_binding as binding
from scripts.research.a2.data import selector_maximal_risk_current as current_owner
from scripts.research.a2.data import selector_maximal_risk_inputs as input_owner
from scripts.research.a2.data import selector_maximal_risk_outcomes as outcomes
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as evidence
from scripts.research.a2.evaluation.selector_maximal_breadth_delivery import put, ref

RUN = binding.RUN
MATRIX_SHA = "3b5fd9f188b62e36f99c00848f33a60d0dc801416fa847a6e1839d4cb80c3c61"
REQUIRED_NEW = (journal_owner,hybrids,membership,binding,current_owner,input_owner,outcomes)
SOURCE_FIELDS = ("source_review","current_bindings","current_audit","requirement_matrix")
TERMINAL = outcomes.TERMINAL
SOURCE_GUARD_RECOVERY_NAME = "source_guard_recovery_r1"
SOURCE_METADATA_QUALIFICATION_SHA = "a4976c8990b9af5e5107bcaeeed70ff7d15680f8659d4680fdeb6e4d646f99d3"


def read_exact(reference, *, root=RUN):
    return outcomes.read_ref(reference,root=root)


def reviewed_sources(review_ref):
    review = read_exact(review_ref)
    ctl.require(review.get("status") == "PASS" and review.get("research_id") == ctl.ID
        and review.get("adapter_sha256") == binding.sha(binding.__file__),
        "INDEPENDENT_CONDITIONAL_EXECUTION_SOURCE_REVIEW_REQUIRED")
    pins = review.get("source_pins",{})
    required = (ctl,*REQUIRED_NEW)
    for module in required:
        path = str(Path(module.__file__).resolve())
        ctl.require(pins.get(path) == binding.sha(path),"EXACT_REVIEWED_EXECUTION_OWNER_REQUIRED:"+path)
    own = str(Path(__file__).resolve())
    ctl.require(pins.get(own) == binding.sha(own),"EXACT_EXECUTION_DRIVER_REVIEW_REQUIRED")
    for path,digest in pins.items():
        p = Path(path).resolve()
        ctl.require(p.is_relative_to(ctl.REPO) and p.suffix == ".py" and binding.sha(p) == digest,
                    "REVIEWED_EXECUTION_SOURCE_CHANGED")
    ctl.require(review.get("scientific_contract_changed") is False and review.get("scientific_retry") == 0
                and review.get("test2026_rows_read") == 0,"UNCHANGED_FROZEN_SCIENCE_REQUIRED")
    return review


def validate_start(config,review):
    ctl.require(set(config) == set(SOURCE_FIELDS) | {"research_id","status"}
        and config["research_id"] == ctl.ID and config["status"] == "REVIEWED_C14_RISK_EXECUTION_INPUTS",
        "EXACT_EXECUTION_INPUT_CONFIGURATION_REQUIRED")
    ctl.require(config["requirement_matrix"] == dict(path=str(RUN/"RISK_ROLE_REQUIREMENT_MATRIX.json"),sha256=MATRIX_SHA),
                "IMMUTABLE_REQUIREMENT_MATRIX_REQUIRED")
    matrix = read_exact(config["requirement_matrix"])
    audit = read_exact(config["current_audit"])
    bindings = read_exact(config["current_bindings"])
    ctl.require(all(review.get("metadata_inputs",{}).get(k) == config[k]
        for k in ("current_audit","current_bindings","requirement_matrix")),
        "REVIEWED_EXACT_INPUT_CONFIGURATION_REQUIRED")
    ctl.require(audit.get("status") == "PASS_FULL752_CURRENT_U_UID_EPOCH_SEGMENT_SOURCE_METADATA"
        and audit.get("research_id") == ctl.ID and audit.get("days_checked") == audit.get("exact_days") == 752
        and all(audit.get(k) == 0 for k in ("risk_numeric_reads","label_numeric_reads","economic_reads","fit","solve","bootstrap","test2026_rows_read"))
        and audit.get("bindings_ref") == config["current_bindings"]
        and audit.get("helper_ref") == dict(path=str(Path(current_owner.__file__).resolve()),sha256=binding.sha(current_owner.__file__)),
        "INDEPENDENT_FULL752_CURRENT_METADATA_AUDIT_REQUIRED")
    ctl.require(bindings.get("research_id") == ctl.ID and bindings.get("numeric_read_authority") is False,
        "C14_LABEL_FREE_CURRENT_BINDINGS_REQUIRED")
    values = bindings.get("bindings",{})
    ctl.require(isinstance(values,dict) and len(values) == 752
        and binding.content_hash(values) == audit.get("bindings_content_sha256")
        and all(v.get("numeric_read_authority") is False for v in values.values()),
        "ALL752_LABEL_FREE_CURRENT_BINDINGS_REQUIRED")
    return matrix,values


def stage(path,name,**details):
    payload = dict(research_id=ctl.ID,status=name,current_time=ctl.now(),
        strict_PIT_promotion_eligible=False,test2026_rows_read=0,**details)
    ctl.write_json(path,payload)
    print(json.dumps({k:v for k,v in payload.items() if k not in ("roles","errors")}),flush=True)
    return payload


def normalized(reason):
    if reason == "COMPLETE": return reason
    if str(reason).startswith("BLOCKED_BUDGET"): return "BLOCKED_BUDGET"
    if "CURRENT_B_SCOPE" in str(reason): return "BLOCKED_BY_CURRENT_B_SCOPE"
    if str(reason).startswith(("BLOCKED","WAITING","PARTIAL")): return "BLOCKED_INPUT"
    return "FAILED_UNTESTABLE"


def terminal(run,design,q,old_ml,qualification,results,journal,review_ref,*,artifact_root=None,input_qualification_ref=None):
    ctl.require(all(s["status"] not in ("STARTED","RESERVED") for s in journal.slots.values()),
                "NO_UNRESOLVED_CONDITIONAL_TRAINING")
    complete = list(old_ml["complete_candidates"])
    failures = dict(old_ml["failed_or_untestable"])
    panels = dict(old_ml["panels"]); native = dict(old_ml["native_pair_predictions"])
    predicted_risk, variance_diagnostics = {}, {}
    reasons = {role: design["blocked_roles"].get(role,"BLOCKED_INPUT") for role in design["roles"]}
    reasons.update(failures)
    for role in complete: reasons[role] = "COMPLETE"
    for role,gate in qualification["roles"].items():
        if role in reasons and role not in complete:
            reasons[role] = gate["phase"] + ":" + ";".join(gate.get("reasons",[]))
    allowed = set(hybrids.ROLES) | set(membership.ROLES)
    ctl.require(allowed <= set(design["roles"]), "ONLY_FROZEN_CONDITIONAL_OWNER_ROLES_REQUIRED")
    protected = set(old_ml["complete_candidates"]) | set(old_ml["panels"]) | set(old_ml["native_pair_predictions"])
    for result in results:
        added = result["complete_candidates"]
        ctl.require(len(added) == len(set(added)) and set(added) <= allowed,
                    "ONLY_UNIQUE_FROZEN_CONDITIONAL_COMPLETE_ROLES_REQUIRED")
        for field in ("failed_or_untestable", "panels", "native_pair_predictions", "predicted_risk", "variance_diagnostics", "roles"):
            keys = set(result.get(field, {}))
            ctl.require(keys <= allowed and not keys & protected,
                        "CONDITIONAL_OUTPUT_CANNOT_ADD_FOREIGN_ROLE_OR_REPLACE_ORIGINAL_ML:" + field)
            if field in ("panels", "native_pair_predictions", "predicted_risk", "variance_diagnostics"):
                ctl.require(keys <= set(added), "NUMERIC_ARTIFACT_REQUIRES_COMPLETED_CONDITIONAL_ROLE:" + field)
        ctl.require(not set(added) & set(result.get("failed_or_untestable", {}))
                    and set(added) <= set(result.get("panels", {})),
                    "COMPLETED_CONDITIONAL_ROLE_REQUIRES_PANEL_AND_NO_FAILURE")
        for role in added:
            if role != "C14_D02":
                ctl.require(qualification["roles"].get(role, {}).get("phase") == "FULL752_NUMERIC_INPUT_QUALIFIED",
                            "COMPLETE_CONDITIONAL_ROLE_REQUIRES_FULL752_INPUT_QUALIFICATION")
        for role in added:
            ctl.require(role not in complete,"DUPLICATE_COMPLETED_ROLE")
            complete.append(role); failures.pop(role,None); reasons[role] = "COMPLETE"
        failures.update(result.get("failed_or_untestable",{}))
        for role,error in result.get("failed_or_untestable",{}).items(): reasons[role] = error
        panels.update(result.get("panels",{})); native.update(result.get("native_pair_predictions",{}))
        predicted_risk.update(result.get("predicted_risk",{})); variance_diagnostics.update(result.get("variance_diagnostics",{}))
    conditional_complete = [role for role in complete if role in allowed and role not in old_ml["complete_candidates"]]
    # Contrasts are predeclared endpoints, not a model or a selection opportunity.
    for contrast in design["contrasts"]:
        cid = contrast["candidate_id"]
        if contrast["left"] in complete and contrast["right"] in complete:
            reasons[cid] = "COMPLETE"; failures.pop(cid,None)
            if cid not in complete: complete.append(cid)
        else:
            reasons[cid] = "FAILED_UNTESTABLE:MISSING_FROZEN_MATCHED_ENDPOINT"
    statuses = {role:normalized(reasons[role]) for role in design["roles"]}
    ctl.require(set(statuses.values()) <= TERMINAL,"EXACT_TERMINAL_STATUS_ENUM_REQUIRED")
    failures = {role:reasons[role] for role in design["roles"] if statuses[role] != "COMPLETE"}
    root = Path(artifact_root) if artifact_root is not None else run/"risk_execution"
    ctl.require(root.resolve() in {(run/"risk_execution").resolve(),(run/"risk_execution"/RECOVERY_NAME).resolve(),
        (run/"risk_execution"/SOURCE_GUARD_RECOVERY_NAME).resolve()}, "EXACT_CONDITIONAL_ARTIFACT_ROOT_REQUIRED")
    if root.resolve() == (run/"risk_execution"/SOURCE_GUARD_RECOVERY_NAME).resolve():
        prior_path = (run/"risk_execution"/RECOVERY_NAME/"INPUT_QUALIFICATION_R1.json").resolve()
        expected = dict(path=str(prior_path),sha256=SOURCE_METADATA_QUALIFICATION_SHA)
        ctl.require(input_qualification_ref == expected, "EXACT_PRIOR_SOURCE_METADATA_QUALIFICATION_REF_REQUIRED")
        retained = read_exact(input_qualification_ref,root=run)
        ctl.require(ctl.content_hash(retained) == ctl.content_hash(qualification)
                    and binding.sha(prior_path) == SOURCE_METADATA_QUALIFICATION_SHA,
                    "PRIOR_SOURCE_METADATA_QUALIFICATION_BODY_OR_CUSTODY_CHANGED")
        qualification_ref = dict(expected)
    else:
        ctl.require(input_qualification_ref is None, "EXPLICIT_QUALIFICATION_REF_ONLY_FOR_SOURCE_GUARD_RECOVERY")
        qualification_ref = ref(root/"INPUT_QUALIFICATION_R1.json")
    put(root/"FIT_STATUS_SNAPSHOT_R1.json",dict(research_id=ctl.ID,status="DERIVED_TERMINAL_SNAPSHOT",
        authoritative_delta_ref=ref(journal.path),slots=journal.slots,not_an_independent_ledger=True))
    assembly = dict(old_ml,status="SCORE_ASSEMBLY_COMPLETE",complete_candidates=complete,
        failed_or_untestable=failures,panels=panels,native_pair_predictions=native,
        predicted_risk=predicted_risk,variance_diagnostics=variance_diagnostics,
        delta_slot_metadata_ref=ref(root/"FIT_STATUS_SNAPSHOT_R1.json"),
        all_training_terminal=True,capacity_selection_complete=True,
        original_ml_assembly_ref=ref(run/"ML_ASSEMBLY.json"),conditional_delta_ref=ref(journal.path),
        role_statuses=statuses,role_failure_details=reasons,
        all_applicable_risk_roles_terminal=True,strict_PIT_promotion_eligible=False,
        input_qualification=qualification_ref)
    put(root/"SCORE_ASSEMBLY_R1.json",assembly)
    gate = dict(status="FINAL_PIPELINES_FROZEN",research_id=ctl.ID,
        design_sha256=binding.DESIGN_SHA,all_training_terminal=True,capacity_selection_complete=True,
        roles=design["roles"],role_statuses=statuses,role_failure_details=reasons,
        score_assembly_sha256=binding.sha(root/"SCORE_ASSEMBLY_R1.json"),
        fit_ledger_sha256=binding.sha(journal.path),pair_key_sha256=q["pair_key_sha256"],
        original_ml_gate_ref=dict(path=str(run/"FINAL_PIPELINES_FREEZE.json"),sha256=outcomes.OLD_ML_GATE_SHA),
        conditional_delta_ref=ref(journal.path),forecast2026_rows=0,outer_labels_read=0,
        scope="original ML immutable plus all applicable conditional risk decisions; joint evidence pending")
    evidence.validate_final_pipeline_gate(design,gate,assembly,binding.DESIGN_SHA)
    put(root/"FINAL_PIPELINES_FREEZE_R1.json",gate)
    summary = dict(status="RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING",research_id=ctl.ID,
        review_ref=review_ref,input_qualification=qualification_ref,
        assembly=ref(root/"SCORE_ASSEMBLY_R1.json"),final_pipeline=ref(root/"FINAL_PIPELINES_FREEZE_R1.json"),
        delta=ref(journal.path),reserved_fit_slots=sum(s["status"] != "UNRESERVED" for s in journal.slots.values()),
        backend_entered=sum(s["entered"] for s in journal.slots.values()),
        complete_fit_slots=sum(s["status"] == "COMPLETE" for s in journal.slots.values()),
        failed_fit_slots=sum(s["status"] == "FAILED" for s in journal.slots.values()),
        blocked_fit_slots=sum(s["status"] == "BLOCKED_DEPENDENCY" for s in journal.slots.values()),
        charged_solves=len(journal.requests),combined_charged_solves=18006+len(journal.requests),
        complete_conditional_roles=conditional_complete,
        complete_fixed_contrasts=[x["candidate_id"] for x in design["contrasts"] if reasons[x["candidate_id"]] == "COMPLETE"],
        joint_delivery_completed=False,coverage_sufficient_claim_allowed=False,
        new_risk_estimations=0,scientific_retry=0,test2026_rows_read=0,strict_PIT_promotion_eligible=False)
    put(root/"RISK_DECISIONS_TERMINAL_R1.json",summary)
    return summary


@contextmanager
def frozen_test_configuration(review):
    """Pin the frozen, nonexecuted pytest config; preserve every code guard.

    Live test discovery can evolve in another task. C14 execution uses no pytest
    configuration. The only transport maps the exact original pytest.ini to its
    original immutable source snapshot, with both live and snapshot custody.
    """
    custody = review.get("nonexecuting_test_configuration", {})
    live = (ctl.REPO / "pytest.ini").resolve()
    snapshot = (RUN / "source_snapshot/pytest.ini").resolve()
    ctl.require(set(custody) == {"classification", "live", "original_snapshot", "executed"}
        and custody["classification"] == "EXACT_ORIGINAL_NONEXECUTING_PYTEST_CONFIGURATION"
        and custody["executed"] is False
        and custody["live"].get("path") == str(live)
        and custody["original_snapshot"].get("path") == str(snapshot),
        "ONLY_ORIGINAL_NONEXECUTING_PYTEST_CONFIGURATION_TRANSPORT")
    ctl.require(binding.sha(live) == custody["live"].get("sha256")
        and binding.sha(snapshot) == custody["original_snapshot"].get("sha256"),
        "EXACT_LIVE_AND_FROZEN_TEST_CONFIGURATION_CUSTODY_REQUIRED")
    original = ctl.checked_sources
    def checked_frozen(run, design):
        ctl.require(Path(run).resolve() == RUN.resolve(), "EXACT_ORIGINAL_C14_RUN_ONLY")
        sources = design.get("sources", {})
        ctl.require(str(live) in sources and str(snapshot) not in sources
            and sources[str(live)] == custody["original_snapshot"]["sha256"],
            "ORIGINAL_DESIGN_TEST_CONFIGURATION_PIN_REQUIRED")
        ctl.require(binding.sha(live) == custody["live"]["sha256"]
            and binding.sha(snapshot) == sources[str(live)],
            "TEST_CONFIGURATION_CHANGED_AFTER_ADMISSION")
        mapped = deepcopy(design)
        mapped["sources"][str(snapshot)] = mapped["sources"].pop(str(live))
        ctl.require(len(mapped["sources"]) == len(sources)
            and {p:h for p,h in mapped["sources"].items() if p != str(snapshot)}
                == {p:h for p,h in sources.items() if p != str(live)},
            "ALL_EXECUTABLE_SOURCE_PINS_PRESERVED")
        return original(run, mapped)
    ctl.checked_sources = checked_frozen
    try:
        yield
    finally:
        ctl.checked_sources = original


RECOVERY_NAME = "source_metadata_recovery_r1"
RECOVERY_SCHEMA = "C14_SOURCE_METADATA_ZERO_ENTRY_RECOVERY_V1"
RECOVERY_PINS = {
    "terminal": "249baa7efc5c618cb24f704c82510cbb820ae7f4b64710ce62b10a62e3f6ba56",
    "qualification": "1f011fa411cb6da3e9a9622ec7e7c35548acba87061121067c12d1c155764d47",
    "delta_header": "d942801d01f4d39e70f03998f4000bff528433d46df3a13f6146f90f433058bf",
    "source_review": "9acb13f36c91aa439514b5021f43930e37f9ac498cf2919ed48217633c9c4a0b",
    "config": "6bcca6ad6dac81f6c68f07610bf65b026132817c996010931c84dacefbf9b81f",
}
RECOVERY_DELTA_POLICY = "PRIOR_TERMINAL_DELTA_SHA_IS_PRESERVED_HEADER_SNAPSHOT; LIVE_DELTA_REMAINS_SINGLE_APPEND_ONLY_AUTHORITY"


def recovery_metadata(run,review,matrix):
    """Only this reviewed zero-entry case may select a versioned artifact root.

    Prior terminal delta pins are historical header pins, witnessed by the exact
    immutable snapshot. The one live delta remains the original journal authority.
    No native payload, prediction table, label or endpoint body is opened here.
    """
    reference = review.get("source_metadata_recovery_ref")
    if reference is None: return None
    run = Path(run).resolve(); old = run/"risk_execution"
    expected_receipt = run/"C14_SOURCE_METADATA_RECOVERY_RECEIPT_R1.json"
    ctl.require(set(reference) == {"path","sha256"}
        and Path(reference["path"]).resolve() == expected_receipt,
        "EXACT_SOURCE_METADATA_RECOVERY_RECEIPT_REQUIRED")
    value = read_exact(reference)
    fields = {"schema","research_id","status","classification","artifact_root","prior_refs",
        "d02_artifacts","scientific_contract_changed","scientific_retry","historical_delta_reference_policy"}
    root = old/RECOVERY_NAME
    ctl.require(set(value) == fields and value["schema"] == RECOVERY_SCHEMA
        and value["research_id"] == ctl.ID and value["status"] == "PASS"
        and value["classification"] == "SOURCE_METADATA_ENGINEERING_ONLY"
        and value["artifact_root"] == str(root)
        and value["scientific_contract_changed"] is False and type(value["scientific_retry"]) is int
        and value["scientific_retry"] == 0 and value["historical_delta_reference_policy"] == RECOVERY_DELTA_POLICY,
        "EXACT_ZERO_ENTRY_RECOVERY_CLASSIFICATION_AND_ROOT_REQUIRED")
    paths = dict(terminal=old/"RISK_DECISIONS_TERMINAL_R1.json",qualification=old/"INPUT_QUALIFICATION_R1.json",
        assembly=old/"SCORE_ASSEMBLY_R1.json",final_pipeline=old/"FINAL_PIPELINES_FREEZE_R1.json",
        fit_snapshot=old/"FIT_STATUS_SNAPSHOT_R1.json",membership=old/"MEMBERSHIP_ASSEMBLY.json",
        started=old/"EXECUTION_STARTED_R1.json",source_review=run/"RISK_INPUT_SOURCE_REVIEW_R2.json",
        config=old/"EXECUTION_INPUTS_R2.json",delta_header=run/"RISK_EXECUTION_DELTA.jsonl",
        header_snapshot=run/"source_corrections/C14_SOURCE_METADATA_RECOVERY_ROUTING_R1/RISK_EXECUTION_DELTA_HEADER.jsonl",
        d02_receipts=old/"C14_D02/MEMBERSHIP_RECEIPTS.json",d02_assembly=old/"C14_D02/MEMBERSHIP_ASSEMBLY.json")
    refs = value["prior_refs"]
    ctl.require(set(refs) == set(paths), "ALL_ORIGINAL_RECOVERY_METADATA_PINS_REQUIRED")
    for key,path in paths.items():
        r = refs[key]
        ctl.require(set(r) == {"path","sha256"} and Path(r["path"]).resolve() == path
            and (key not in RECOVERY_PINS or r["sha256"] == RECOVERY_PINS[key]),
            "EXACT_ORIGINAL_RECOVERY_PIN_REQUIRED:"+key)
        # After successful execution this live file grows; its old exact bytes
        # remain independently pinned in header_snapshot, never rewritten.
        if key != "delta_header": ctl.pin(r)
    ctl.require(refs["header_snapshot"]["sha256"] == refs["delta_header"]["sha256"],
        "ORIGINAL_HEADER_SNAPSHOT_MUST_MATCH_HISTORICAL_DELTA_PIN")
    terminal = read_exact(refs["terminal"]); qualification = read_exact(refs["qualification"])
    prior_config = read_exact(refs["config"]); started = read_exact(refs["started"])
    ctl.require(terminal.get("research_id") == ctl.ID
        and terminal.get("status") == "RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING"
        and terminal.get("review_ref") == refs["source_review"]
        and terminal.get("input_qualification") == refs["qualification"]
        and terminal.get("assembly") == refs["assembly"] and terminal.get("final_pipeline") == refs["final_pipeline"]
        and terminal.get("delta") == refs["delta_header"]
        and terminal.get("complete_conditional_roles") == ["C14_D02"]
        and terminal.get("complete_fixed_contrasts") == []
        and terminal.get("joint_delivery_completed") is False
        and terminal.get("coverage_sufficient_claim_allowed") is False
        and prior_config.get("source_review") == refs["source_review"]
        and started.get("config") == refs["config"] and started.get("review") == refs["source_review"],
        "EXACT_PREVIOUS_SOURCE_METADATA_TERMINAL_CHAIN_REQUIRED")
    zeros = ("reserved_fit_slots","backend_entered","complete_fit_slots","failed_fit_slots","blocked_fit_slots",
             "charged_solves","new_risk_estimations","scientific_retry","test2026_rows_read")
    ctl.require(all(type(terminal.get(k)) is int and terminal[k] == 0 for k in zeros)
        and terminal.get("combined_charged_solves") == journal_owner.BASELINE_SOLVES,
        "PREVIOUS_TERMINAL_MUST_HAVE_ZERO_SCIENTIFIC_ENTRY")
    counts = {"native_state_load_attempts","native_states_loaded","daily_role_bindings","selector_fit",
        "risk_estimator_fit","solver","bootstrap","risk_numeric_read","test2026_rows_read","EF_access","provider_fetch"}
    ctl.require(qualification.get("research_id") == ctl.ID and set(qualification.get("counts",{})) == counts
        and all(type(v) is int and v == 0 for v in qualification["counts"].values())
        and qualification.get("realized_endpoint_qualified") is False,
        "PREVIOUS_INPUT_QUALIFICATION_MUST_HAVE_ZERO_NATIVE_OR_SCIENTIFIC_ENTRY")
    rows = {r["role"]:r for r in matrix["roles"]}
    gates = qualification.get("roles",{})
    waiting = {r for r,v in rows.items() if v["current_status"] == "WAITING_R5_PUBLICATION"}
    ctl.require(set(gates) == set(rows) and len(waiting) == 10
        and all(g.get("states") == [] and g.get("full_required_dates_qualified") is False for g in gates.values())
        and all(gates[r].get("phase") == "BLOCKED_INPUT"
            and gates[r].get("reasons") == ["RiskBindingBlocked:ORIGINAL_MECHANISM_SOURCE_TIME_ONLY"] for r in waiting),
        "ONLY_EXACT_UNTOUCHED_SOURCE_METADATA_BLOCKERS_RECOVERABLE")
    snapshot = read_exact(refs["fit_snapshot"])
    ctl.require(snapshot.get("authoritative_delta_ref") == refs["delta_header"]
        and snapshot.get("not_an_independent_ledger") is True and len(snapshot.get("slots",{})) == 144
        and all(s.get("status") == "UNRESERVED" and type(s.get("entered")) is int and s["entered"] == 0
                for s in snapshot["slots"].values()), "PREVIOUS_ALL144_SLOTS_MUST_BE_UNRESERVED")
    membership_value = read_exact(refs["membership"])
    ctl.require(membership_value.get("research_id") == ctl.ID
        and membership_value.get("status") == "MEMBERSHIP_ASSEMBLY_COMPLETE"
        and membership_value.get("complete_candidates") == ["C14_D02"]
        and membership_value.get("native_pair_predictions") == {}, "ONLY_ORIGINAL_RAW_IDENTITY_COMPLETE_REUSE")
    artifacts = value["d02_artifacts"]
    ctl.require(set(artifacts) == {"panel","predicted_risk"}, "EXACT_ORIGINAL_D02_ARTIFACT_PINS_REQUIRED")
    for key,field,name in (("panel","panels","scores_pre2026.parquet"),
                           ("predicted_risk","predicted_risk","predicted_risk_pre2026.parquet")):
        original_ref = membership_value[field]["C14_D02"]
        expected = {k:original_ref[k] for k in ("path","sha256")}
        ctl.require(artifacts[key] == expected and Path(expected["path"]).resolve() == old/"C14_D02"/name,
                    "EXACT_ORIGINAL_D02_ARTIFACT_REQUIRED")
        ctl.pin(expected)
    ctl.require(read_exact(refs["d02_receipts"]) == []
        and read_exact(refs["d02_assembly"]) == membership_value["roles"]["C14_D02"],
        "ORIGINAL_D02_ZERO_SOLVE_RECEIPTS_REQUIRED")
    return dict(root=root,reference=reference,receipt=value,raw_identity_ref=refs["membership"])


def recovery_journal(run,recovery):
    """Replay the existing sole authority; never delete/reset a reservation."""
    ctl.pin(recovery["receipt"]["prior_refs"]["delta_header"])
    journal = journal_owner.RiskJournal(run)
    ctl.require(journal.path.resolve() == (Path(run)/"RISK_EXECUTION_DELTA.jsonl").resolve()
        and journal.sequence == 1 and not journal.roles and not journal.requests
        and len(journal.slots) == 144
        and all(s.get("status") == "UNRESERVED" and type(s.get("entered")) is int and s["entered"] == 0
                for s in journal.slots.values()), "LIVE_JOURNAL_MUST_BE_HEADER_ONLY_ZERO_ENTRY")
    journal.verify()
    return journal


def _execute_reviewed(run,config_ref,config,review):
    review_ref = config["source_review"]
    matrix,current = validate_start(config,review)
    cfg,design,q = ctl.checked(run); evidence.validate_design(design)
    recovery = recovery_metadata(run,review,matrix)
    root = recovery["root"] if recovery is not None else run/"risk_execution"
    assert_safe_output_path(root,kind="backtest",paths=resolve(ctl.REPO))
    done = root/"RISK_DECISIONS_TERMINAL_R1.json"
    if done.exists():
        value = read_exact(ref(done))
        ctl.require(value.get("research_id") == ctl.ID
            and value.get("status") == "RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING"
            and value.get("review_ref") == review_ref
            and value.get("joint_delivery_completed") is False
            and value.get("coverage_sufficient_claim_allowed") is False,
            "EXACT_TERMINAL_CONTINUATION_RECEIPT_REQUIRED")
        for field in ("assembly","final_pipeline","delta","input_qualification"): ctl.pin(value[field])
        return value
    ctl.require(not (root/"EXECUTION_STARTED_R1.json").exists(),
                "EXISTING_EXECUTION_REQUIRES_BOUNDED_CHECKPOINT_RECOVERY_NO_DUPLICATE_WORKER")
    journal = recovery_journal(run,recovery) if recovery is not None else None
    put(root/"EXECUTION_STARTED_R1.json",dict(research_id=ctl.ID,config=config_ref,review=review_ref,
        status="STARTED_ENGINEERING_INPUT_QUALIFICATION",current_time=ctl.now(),scientific_retry=0))
    stage(root/"PIPELINE_STATE.json","R5_METADATA_BINDING")
    publication = binding.read_publication_metadata()
    ctl.require(publication.get("publication") is not None,"QUALIFIED_ORIGINAL_R5_PUBLICATION_REQUIRED")
    raw_meta = ctl.project(q["artifacts"]["raw_current"],list(current_owner.RAW_META),
        start="2023-01-01",stop="2026-01-01",run=run)
    inputs = input_owner.RiskInputs(publication["publication"],matrix,current,raw_meta,
        source_review=review,source_review_ref=review_ref)
    stage(root/"PIPELINE_STATE.json","RISK_NUMERIC_INPUT_QUALIFICATION")
    qualification = inputs.qualify()
    put(root/"INPUT_QUALIFICATION_R1.json",qualification)
    # No scientific reservation exists until a complete exact752 gate has passed.
    if journal is None: journal = journal_owner.RiskJournal(run)
    for role,gate in qualification["roles"].items():
        if gate["phase"] != "FULL752_NUMERIC_INPUT_QUALIFIED": continue
        path = root/"input_gates"/(role+".json"); put(path,gate)
        if role in journal.families: journal.activate_role(role,ref(path))
    stage(root/"PIPELINE_STATE.json","QUALIFIED_CONDITIONAL_DECISIONS",
        role_input_status={r:g["phase"] for r,g in qualification["roles"].items()},
        qualified_roles=list(journal.roles))
    # Verify physical clock metadata before materializing any prepared numeric column.
    ctl.footer(q["artifacts"]["raw_current"])
    ctl.footer(q["artifacts"]["pair_geometry"])
    raw = pq.read_table(ctl.pin(q["artifacts"]["raw_current"])).to_pandas()
    geometry = pq.read_table(ctl.pin(q["artifacts"]["pair_geometry"])).to_pandas()
    raw.signal_date = pd.to_datetime(raw.signal_date); geometry.signal_date = pd.to_datetime(geometry.signal_date)
    ctl.require(raw.signal_date.lt("2026-01-01").all() and geometry.signal_date.lt("2026-01-01").all(),
                "PREPARED_INPUT_PRE2026_LOCK")
    results = []
    hybrid_roles = [r for r in hybrids.ROLES if r in journal.roles]
    if hybrid_roles:
        ctl.footer(q["artifacts"]["current_pair_features"])
        features = pq.read_table(ctl.pin(q["artifacts"]["current_pair_features"])).to_pandas()
        ctl.require(features[list(ctl.PAIR_KEYS)].equals(geometry[list(ctl.PAIR_KEYS)]),"EXACT_PAIR_FEATURE_ORDER_REQUIRED")
        base_x = features[ctl.feature_order()].to_numpy(float)
        runtime = ctl.runtime_parts(ctl.runtime_for(run,cfg))[0]
        for role in hybrid_roles:
            stage(root/"PIPELINE_STATE.json","QUALIFIED_HYBRID_RUNNING",role=role)
            try:
                result = hybrids.execute_hybrid(run,design,q,raw,geometry,base_x,role,
                    inputs.get_risk,journal,kernel,runtime,
                    **({"artifact_root":root} if recovery is not None else {}))
            except Exception as error:
                # Preserve independent branches. STARTED never becomes an invented
                # scientific failure/completion or an automatically retried fit.
                details = dict(error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
                put(root/role/"ENGINEERING_FAILURE_R1.json",details)
                if not any(s["candidate_id"] == role and s["status"] == "STARTED" for s in journal.slots.values()):
                    journal.block_remaining(role,"UNEXPECTED_ENGINEERING_FAILURE_BEFORE_UNUSED_FITS")
                result = dict(status="HYBRID_FAILED_UNTESTABLE",complete_candidates=[],
                    failed_or_untestable={role:details["error_type"]+":"+details["error"]},
                    panels={},native_pair_predictions={})
            results.append(result)
    stage(root/"PIPELINE_STATE.json","QUALIFIED_CLASSICAL_AND_FIXED_VETO_RUNNING")
    results.append(membership.execute_membership(run,design,q,raw,geometry,matrix,
        inputs.get_risk,journal,review_ref,role_gates=inputs.status()["roles"],
        qualification_ref=ref(root/"INPUT_QUALIFICATION_R1.json"),
        **({"artifact_root":root,"raw_identity_ref":recovery["raw_identity_ref"]} if recovery is not None else {})))
    old_ml_ref = review["immutable_inputs"]["ML_ASSEMBLY.json"]
    old_ml = read_exact(old_ml_ref)
    summary = terminal(run,design,q,old_ml,qualification,results,journal,review_ref,
        **({"artifact_root":root} if recovery is not None else {}))
    stage(root/"PIPELINE_STATE.json",summary["status"],terminal=ref(done),
        joint_delivery_completed=False,coverage_sufficient_claim_allowed=False)
    return summary



def execute(run,config_ref):
    run = Path(run).resolve()
    ctl.require(run == RUN.resolve(), "EXACT_ORIGINAL_C14_RUN_ONLY")
    config = read_exact(config_ref)
    review = reviewed_sources(config["source_review"])
    with frozen_test_configuration(review):
        return _execute_reviewed(run,config_ref,config,review)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run",required=True); parser.add_argument("--config",required=True)
    parser.add_argument("--config-sha256",required=True); args = parser.parse_args()
    try:
        result = execute(args.run,dict(path=args.config,sha256=args.config_sha256))
        print(json.dumps(result),flush=True)
    except Exception:
        print(traceback.format_exc(),flush=True)
        raise


if __name__ == "__main__": main()
