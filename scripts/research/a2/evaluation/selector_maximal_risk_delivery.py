"""Additive C14 risk delivery; no old ML evaluator, bootstrap or oracle solve.

Execution is explicit, terminal and independently reviewed. All statistical
authority remains in the frozen evidence owners and the incremental adapter.
Old reports, diagnostics, ledgers and numeric summaries are only pinned/reused.
"""
from __future__ import annotations
from copy import deepcopy
import json
import importlib
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve,assert_safe_output_path
from scripts.research.a2.training import selector_maximal_breadth as ctl
from scripts.research.a2.training import selector_maximal_risk_journal as transport
from scripts.research.a2.data import selector_maximal_risk_outcomes as outcomes
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as ev
from scripts.research.a2.evaluation import selector_maximal_breadth_delivery as writer
from scripts.research.a2.evaluation import selector_maximal_risk_precomputed as precomputed
from scripts.research.a2.evaluation import selector_maximal_risk_incremental as incremental
from scripts.research.a2.risk.event_risk_contract_r5 import bind_pinned_kernel

RUN=outcomes.RUN
RESULTS=Path("D:/us-tech-quant-results/V24/C_SELECTOR/C14_MAXIMAL_BREADTH")
ID=ctl.ID
need=ev._require
NEW_ROLES=set(ev.HYBRIDS+ev.GATES+ev.CLASSICAL)-{"C14_D12"}
ROOT_NAME="joint_delivery_r1"
KEYS=list(ev.shared.KEY)
PANEL=KEYS+["ticker","U_t_fingerprint","rank","score","candidate_id"]
TERMINAL_NAME="RISK_DECISIONS_TERMINAL_R1.json"
OLD_ML_ASSEMBLY_SHA="a1e404a7c1c0de57bbd3f276c9e350dfefcdbdad61628431f3d2ef5c0538c00a"


def _ref(path):
    return dict(path=str(path),sha256=outcomes.binding.sha(path))


def _read(reference,*,root=RUN):
    return outcomes.read_ref(reference,root=root)


def _project(reference,columns,*,dates,allow_empty=False):
    wanted=pd.DatetimeIndex(dates)
    need(wanted.tz is None and not wanted.hasnans and wanted.is_unique
         and wanted.is_monotonic_increasing and len(wanted)>0
         and (wanted<pd.Timestamp("2026-01-01")).all(),"PRE2026_FIXED_PROJECTION_MASK_REQUIRED")
    path=ctl.pin(reference)
    empty=False
    if allow_empty:
        metadata=pq.ParquetFile(path)
        empty=metadata.metadata.num_rows==0
        need(set(columns)<=set(metadata.schema_arrow.names),"EMPTY_MATCHED_SCHEMA_REQUIRED")
    if not empty: ctl.footer(reference)
    table=pq.read_table(path,columns=list(columns),filters=[("signal_date","in",list(wanted))])
    need(table.column_names==list(columns),"EXACT_JOINT_COLUMN_PROJECTION_REQUIRED")
    out=table.to_pandas()
    out["signal_date"]=pd.to_datetime(out.signal_date)
    dates_read=pd.DatetimeIndex(out.signal_date)
    need(dates_read.tz is None and not dates_read.hasnans
         and (dates_read<pd.Timestamp("2026-01-01")).all(),"NO2026_JOINT_DATA_REQUIRED")
    need(dates_read.isin(wanted).all(),"NO_TAIL_OR_UNREQUESTED_DATE_READ")
    ctl.pin(reference)
    return out


def required_sources(*,include_post_reboot=False):
    modules=(sys.modules[__name__],ctl,transport,outcomes,writer,writer.old_delivery,
        ev,ev.shared,ev.prior,ev.risk_metrics,ev.risk_metrics.c11,ev.pairs_owner,precomputed,incremental,
        outcomes.owner,outcomes.owner.owner,outcomes.owner.identity_owner,outcomes.owner.namespace_owner,
        sys.modules[bind_pinned_kernel.__module__])
    pins={str(Path(m.__file__).resolve()):outcomes.binding.sha(m.__file__) for m in modules}
    pins.update(precomputed.required_source_pins())
    pins[str(ev.risk_metrics.CVAR_OWNER_PATH.resolve())]=ev.risk_metrics.CVAR_OWNER_SHA256
    if include_post_reboot:
        for relative in ("evaluation/selector_maximal_risk_resume.py","evaluation/selector_maximal_risk_execution.py"):
            path=(ctl.REPO/"scripts/research/a2"/relative).resolve()
            pins[str(path)]=outcomes.binding.sha(path)
    return pins


POST_REBOOT_ROOT_NAME="source_guard_recovery_r1"
POST_REBOOT_COMPLETE_NAME="POST_REBOOT_CLASSICAL_CHECKPOINT_COMPLETE_R1.json"
POST_REBOOT_MARKER_NAME="POST_REBOOT_CLASSICAL_CHECKPOINT_STARTED_R1.json"
POST_REBOOT_REVIEW_SCHEMA="C14_POST_REBOOT_JOINT_DELIVERY_REVIEW_V1"
PRIOR_DELIVERY_SOURCES={
    "scripts/research/a2/evaluation/selector_maximal_risk_delivery.py":
        ("evaluation/selector_maximal_risk_delivery.py","7a9aeea38288b38944d8b4bdd96047bf64039ee79c6bf28dc1395a7de1d305bd"),
    "tests/research/a2/evaluation/test_selector_maximal_risk_delivery.py":
        ("tests/evaluation/test_selector_maximal_risk_delivery.py","32c4bcb48f0819d8d6c71c8a98cebb214befd908912a4bb0697eb8f4e64404de"),
}
REUSED_CLASSICAL=("C14_D01","C14_D05","C14_D06","C14_D02","C14_G1","C14_G4")
REMAINING_CLASSICAL=("C14_D09","C14_D10","C14_D11")
OLD_ML_REPORT_SHA="5013e90f1e39e3d4d37f9e54df57d12a4ef8214f0761b8844a88bc9faea5bb37"
OLD_ML_AUDIT_SHA="f96fc83c06de18875dd4b6ce4a8afa5d9fc84d16bb5375c2419d7bae1f6b3686"


def _fixed_ref(reference,path,sha256=None):
    need(isinstance(reference,dict) and set(reference)=={"path","sha256"}
         and Path(reference["path"]).resolve()==Path(path).resolve()
         and (sha256 is None or reference["sha256"]==sha256),"FIXED_POST_REBOOT_REFERENCE_REQUIRED")
    return reference


def _same(left,right):
    return ctl.content_hash(left)==ctl.content_hash(right)


def post_reboot_execution_sources(checkpoint):
    """Reuse existing canonical snapshot origin checks; caller owns context."""
    owner=importlib.import_module("scripts.research.a2.evaluation.selector_maximal_risk_resume")
    snapshots=checkpoint["snapshot_transport"]
    need(set(snapshots)==set(owner.TRANSPORT),"EXACT_THREE_EXECUTED_SNAPSHOT_MODULES_REQUIRED")
    functions={owner.CA_NAME:("apply_transition_to_positions","apply_entitlement_lifecycle"),
        owner.ACCOUNT_NAME:("_engine_with_entitlement_hook",),owner.JOINT_NAME:("_hrp","allocate_q","exposure","_v24_call")}
    for name,refs in snapshots.items():
        module=sys.modules.get(name)
        need(module is not None,"COLD_EXECUTED_SNAPSHOT_MODULE_REQUIRED")
        owner.assert_module(module,name,refs["original_snapshot"]["path"])
        owner.function_origin(module,functions[name],refs["original_snapshot"]["path"])
    guard=ctl.checked_sources
    need(guard.__module__==owner.__name__ and guard.__qualname__=="executable_snapshot_guard.<locals>.checked"
         and Path(guard.__code__.co_filename).resolve()==Path(owner.__file__).resolve()
         and guard.__globals__ is owner.__dict__,"ORIGINAL_EXECUTABLE_SNAPSHOT_GUARD_CONTEXT_REQUIRED")


def post_reboot_inputs(review,terminal_ref,terminal,assembly,checkpoint_ref):
    """Bind existing producer receipts and opaque leaves; journal owns replay."""
    root=RUN/"risk_execution"/POST_REBOOT_ROOT_NAME
    need(review.get("schema")==POST_REBOOT_REVIEW_SCHEMA and review.get("independent_review") is True
         and review.get("classification")=="POST_REBOOT_JOINT_DELIVERY_ENGINEERING",
         "INDEPENDENT_POST_REBOOT_DELIVERY_REVIEW_REQUIRED")
    backups=review.get("source_backups",{})
    expected_paths={str((ctl.REPO/relative).resolve()) for relative in PRIOR_DELIVERY_SOURCES}
    need(set(backups)==expected_paths,"EXACT_TWO_DELIVERY_SOURCE_BACKUPS_REQUIRED")
    for relative,(backup,prior_sha) in PRIOR_DELIVERY_SOURCES.items():
        source=(ctl.REPO/relative).resolve();ref=backups[str(source)]
        _fixed_ref(ref,RUN/"source_corrections/C14_POST_REBOOT_JOINT_DELIVERY_R1"/backup,prior_sha)
        ctl.pin(ref)
        need(review["source_pins"].get(str(source))==outcomes.binding.sha(source),
             "CURRENT_DELIVERY_SOURCE_AND_TEST_PINS_REQUIRED")
    immutable=review.get("immutable_inputs",{})
    for key,name,digest in (("old_report","FINAL_REPORT.md",OLD_ML_REPORT_SHA),
            ("old_ml_audit","ML_DELIVERY_AUDIT.md",OLD_ML_AUDIT_SHA)):
        ref=_fixed_ref(immutable.get(key),RESULTS/name,digest);ctl.pin(ref)
    inputs=review["delivery_inputs"]
    need(set(inputs)=={"terminal","precomputed_review","legacy_summaries","post_reboot_checkpoint",
         "post_reboot_completion","post_reboot_marker"} and inputs["post_reboot_checkpoint"]==checkpoint_ref,
         "EXACT_REVIEWED_POST_REBOOT_DELIVERY_INPUTS_REQUIRED")
    _fixed_ref(checkpoint_ref,RUN/transport.POST_REBOOT_REVIEW_NAME)
    checkpoint=_read(checkpoint_ref)
    need(set(checkpoint)==transport.POST_REBOOT_FIELDS and checkpoint.get("status")=="PASS"
         and checkpoint.get("research_id")==ID and checkpoint.get("independent_review") is True
         and checkpoint.get("scientific_contract_changed") is False
         and checkpoint.get("remaining_classical_roles")==list(REMAINING_CLASSICAL),
         "FIXED_POST_REBOOT_CHECKPOINT_AUTHORITY_REQUIRED")
    post_reboot_execution_sources(checkpoint)
    prefix=dict(path=str(RUN/"RISK_EXECUTION_DELTA.jsonl"),**transport.POST_REBOOT_PREFIX)
    need(checkpoint["checkpoint_delta"]==prefix and terminal["review_ref"]==checkpoint["runtime_source_review"],
         "POST_REBOOT_PREFIX_AND_RUNTIME_TERMINAL_CHAIN_REQUIRED")
    qpath,qsha=transport.SOURCE_GUARD_REFS["qualification"]
    qualification=dict(path=str((RUN/qpath).resolve()),sha256=qsha)
    need(terminal["input_qualification"]==assembly.get("input_qualification")
         ==checkpoint["input_qualification"]==qualification,"ROOT1_QUALIFICATION_EXACT_REUSE_REQUIRED")
    audit_ref=_fixed_ref(inputs["post_reboot_completion"],root/POST_REBOOT_COMPLETE_NAME)
    marker_ref=_fixed_ref(inputs["post_reboot_marker"],root/POST_REBOOT_MARKER_NAME)
    audit=_read(audit_ref);marker=_read(marker_ref)
    need(audit.get("status")=="POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_TERMINAL"
         and marker.get("status")=="STARTED_POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT"
         and audit.get("research_id")==marker.get("research_id")==ID
         and audit.get("terminal")==terminal_ref and audit.get("review")==marker.get("review")==checkpoint_ref
         and audit.get("runtime_source_review")==marker.get("runtime_source_review")==terminal["review_ref"]
         and audit.get("checkpoint_delta")==marker.get("checkpoint_delta")==prefix
         and audit.get("old_marker")==marker.get("old_marker")==checkpoint["old_marker"]
         and audit.get("original_source_guard_review")==checkpoint["original_source_guard_review"]
         and audit.get("original_input_qualification")==qualification
         and _same(audit.get("preserved_old_recovery_event"),checkpoint["old_recovery_event"])
         and _same(audit.get("reused_completed_artifacts"),checkpoint["completed_role_artifacts"])
         and _same(audit.get("reused_completed_fit_artifacts"),checkpoint["completed_fit_artifacts"])
         and _same(audit.get("original_complete_cache_counts"),transport.POST_REBOOT_COUNTS)
         and marker.get("remaining_classical_roles")==list(REMAINING_CLASSICAL)
         and type(marker.get("completed_fit_slots_reused")) is int and marker["completed_fit_slots_reused"]==28,
         "NATURAL_POST_REBOOT_COMPLETION_MARKER_AND_AUTHORITY_CHAIN_REQUIRED")
    need(audit.get("RX_reopened") is False and type(audit.get("new_fit")) is int and audit["new_fit"]==0
         and audit.get("coverage_sufficient_claim_allowed") is False
         and all(obj.get("joint_delivery_completed") is False
                 and obj.get("interrupted_worker_execution_input_counts")=="UNKNOWN_DUE_REBOOT"
                 and all(type(obj.get(k)) is int and obj[k]==0 for k in ("scientific_retry","test2026_rows_read"))
                 for obj in (audit,marker)),"POST_REBOOT_COMPLETION_ENGINEERING_ONLY_REQUIRED")
    proof=audit.get("publication_source_transport",{})
    snapshots=checkpoint["snapshot_transport"]
    need(proof.get("B_freeze")==checkpoint["B_freeze"]
         and proof.get("original_publication_admission")==checkpoint["original_publication_admission"]
         and set(proof.get("transported_code_refs",{}))==set(snapshots)
         and proof.get("original_reader_code_reused") is True
         and proof.get("original_binding_sha_global_unchanged") is True
         and proof.get("original_metadata_qualification_chain_reused") is True
         and all(type(proof.get(k)) is int and proof[k]==0
                 for k in ("native_numeric_reads","label_reads","fit","solve","bootstrap")),
         "EXACT_POST_REBOOT_PUBLICATION_SOURCE_TRANSPORT_REQUIRED")
    for name,refs in snapshots.items():
        item=proof["transported_code_refs"][name]
        need(item==dict(logical_canonical_code_ref=dict(path=refs["live"]["path"],
             sha256=refs["original_snapshot"]["sha256"]),actual_live_source_ref=refs["live"],
             actual_executed_snapshot_ref=refs["original_snapshot"]),"PUBLICATION_EXECUTED_SOURCE_CHAIN_CHANGED")
        for ref in refs.values(): ctl.pin(ref)
    declared=checkpoint["completed_role_artifacts"];rx=set(transport.ACTIVE_RX)
    need(set(declared)==set(REUSED_CLASSICAL)|rx
         and set(REUSED_CLASSICAL)|rx<=set(terminal["complete_conditional_roles"])
         <=set(REUSED_CLASSICAL)|rx|set(REMAINING_CLASSICAL),"ONLY_ORIGINAL_POST_REBOOT_ROLE_ROSTER_REQUIRED")
    for role in REUSED_CLASSICAL:
        need(set(declared[role])=={"panels","predicted_risk","variance_diagnostics"}
             and all(_same(assembly.get(field,{}).get(role),ref) for field,ref in declared[role].items()),
             "ORIGINAL_SIX_COMPLETED_ARTIFACTS_EXACT_REUSE_REQUIRED")
        for ref in declared[role].values(): ctl.pin(ref)
    for role in rx:
        refs=declared[role];panel=assembly["panels"][role];native=assembly["native_pair_predictions"][role]
        names=dict(assembly="HYBRID_ASSEMBLY.json",panel="scores_pre2026.parquet",
             native_pairs="native_pairs_pre2026.parquet",matching="matching_pre2026.parquet")
        need(set(refs)==set(names) and {k:panel[k] for k in ("path","sha256")}==refs["panel"]
             and {k:native[k] for k in ("path","sha256")}==refs["native_pairs"]
             and dict(path=native["matching_path"],sha256=native["matching_sha256"])==refs["matching"],
             "COMPLETED_RX_PANEL_NATIVE_MATCHING_EXACT_REUSE_REQUIRED")
        for key,name in names.items():
            _fixed_ref(refs[key],root/role/name);ctl.pin(refs[key])
    for role in set(terminal["complete_conditional_roles"])&set(REMAINING_CLASSICAL):
        panel=assembly["panels"][role];risk=assembly.get("predicted_risk",{}).get(role)
        need(risk is not None and _same(risk,assembly.get("variance_diagnostics",{}).get(role)),
             "NEW_CLASSICAL_SAVED_VARIANCE_REFERENCE_REQUIRED")
        for ref,name in ((panel,"scores_pre2026.parquet"),(risk,"predicted_risk_pre2026.parquet")):
            _fixed_ref({k:ref[k] for k in ("path","sha256")},root/role/name);ctl.pin(ref)
    return audit_ref


def terminal_inputs(run,terminal_ref,review_ref,precomputed_review_ref,legacy_summary_ref,
        *,post_reboot_checkpoint_ref=None):
    need(Path(run).resolve()==RUN.resolve(),"ONLY_ORIGINAL_C14_DELIVERY_RUN")
    review=_read(review_ref)
    need(review.get("status")=="PASS" and review.get("research_id")==ID
         and review.get("scientific_contract_changed") is False and review.get("scientific_retry")==0
         and review.get("test2026_rows_read")==0,"INDEPENDENT_ADDITIVE_DELIVERY_REVIEW_REQUIRED")
    need(review.get("adapter_sha256")==outcomes.binding.sha(outcomes.binding.__file__),
         "EXACT_CURRENT_H5_ADAPTER_REVIEW_REQUIRED")
    pins=review.get("source_pins",{})
    need(all(pins.get(p)==h for p,h in required_sources(include_post_reboot=post_reboot_checkpoint_ref is not None).items()),"COMPLETE_JOINT_SOURCE_CLOSURE_REQUIRED")
    for p,h in pins.items():
        path=Path(p).resolve()
        need(path.is_relative_to(ctl.REPO.resolve()) and path.suffix==".py"
             and outcomes.binding.sha(path)==h,"JOINT_SOURCE_PHYSICAL_PIN_CHANGED")
    inputs=review.get("delivery_inputs",{})
    expected=dict(terminal=terminal_ref,precomputed_review=precomputed_review_ref,legacy_summaries=legacy_summary_ref)
    need(all(inputs.get(k)==v for k,v in expected.items()),"EXACT_REVIEWED_DELIVERY_INPUTS_REQUIRED")
    terminal_root=RUN/"risk_execution"
    if post_reboot_checkpoint_ref is not None: terminal_root/=POST_REBOOT_ROOT_NAME
    _fixed_ref(terminal_ref,terminal_root/TERMINAL_NAME)
    need(post_reboot_checkpoint_ref is not None or not any(
         k.startswith("post_reboot_") for k in inputs),"NO_POST_REBOOT_DOWNGRADE_TO_OLD_ROOT")
    terminal=_read(terminal_ref)
    need(terminal.get("status")=="RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING"
         and terminal.get("research_id")==ID and terminal.get("joint_delivery_completed") is False
         and terminal.get("new_risk_estimations")==terminal.get("scientific_retry")==terminal.get("test2026_rows_read")==0
         and terminal.get("strict_PIT_promotion_eligible") is False,
         "ALL_CONDITIONAL_DECISIONS_TERMINAL_BEFORE_OUTCOMES")
    design_ref=dict(path=str(RUN/"DESIGN_FREEZE.json"),sha256=outcomes.binding.DESIGN_SHA)
    design=_read(design_ref);ev.validate_design(design)
    if post_reboot_checkpoint_ref is not None:
        # The existing guard checks all frozen sources plus accepted overlays.
        ctl.checked_sources(RUN,design)
    if post_reboot_checkpoint_ref is not None:
        _fixed_ref(terminal["assembly"],terminal_root/"SCORE_ASSEMBLY_R1.json")
        _fixed_ref(terminal["final_pipeline"],terminal_root/"FINAL_PIPELINES_FREEZE_R1.json")
    assembly=_read(terminal["assembly"]);gate=_read(terminal["final_pipeline"])
    if post_reboot_checkpoint_ref is not None:
        post_reboot_inputs(review,terminal_ref,terminal,assembly,post_reboot_checkpoint_ref)
    ev.validate_final_pipeline_gate(design,gate,assembly,design_ref["sha256"])
    need(set(gate["role_statuses"].values())<=outcomes.TERMINAL
         and assembly.get("role_statuses")==gate["role_statuses"]
         and assembly.get("all_applicable_risk_roles_terminal") is True
         and gate["score_assembly_sha256"]==terminal["assembly"]["sha256"]
         and gate.get("conditional_delta_ref")==assembly.get("conditional_delta_ref")==terminal["delta"]
         and gate["fit_ledger_sha256"]==terminal["delta"]["sha256"],"EXACT_JOINT_TERMINAL_CHAIN_REQUIRED")
    need(Path(terminal["delta"]["path"]).resolve()==(RUN/"RISK_EXECUTION_DELTA.jsonl").resolve(),
         "ORIGINAL_CONDITIONAL_DELTA_PATH_REQUIRED")
    ctl.pin(terminal["delta"]);_read(terminal["input_qualification"])
    oldgate=gate.get("original_ml_gate_ref")
    need(oldgate==dict(path=str(RUN/"FINAL_PIPELINES_FREEZE.json"),sha256=outcomes.OLD_ML_GATE_SHA),
         "ORIGINAL_ML_GATE_IMMUTABLE_REQUIRED")
    original_gate=_read(oldgate)
    ev._gate(original_gate,design_ref["sha256"])
    count=terminal["reserved_fit_slots"]
    need(type(count)is int and 0<=count<=144 and 656+count<=800<=1800
         and type(terminal["backend_entered"])is int and 0<=terminal["backend_entered"]<=count
         and type(terminal["charged_solves"])is int and terminal["charged_solves"]>=0
         and type(terminal["combined_charged_solves"])is int
         and terminal["combined_charged_solves"]==18006+terminal["charged_solves"]<=29542<=30000,
         "COMBINED_FROZEN_DELIVERY_BUDGET_REQUIRED")
    new=terminal.get("complete_conditional_roles",[])
    original_complete={r for r,v in original_gate["role_statuses"].items() if v=="COMPLETE"}
    from_gate={r for r in NEW_ROLES if gate["role_statuses"][r]=="COMPLETE"}-original_complete
    from_assembly=(set(assembly["complete_candidates"]) & NEW_ROLES)-original_complete
    need(len(new)==len(set(new)) and set(new)==from_gate==from_assembly
         and all(gate["role_statuses"][r]=="COMPLETE" and r in assembly["complete_candidates"]
             and r in assembly["panels"] for r in new),"ALL_COMPLETE_NEW_PANEL_BINDINGS_REQUIRED")
    # Immutable original inputs, including labels, are independently reviewed.
    immutable=review.get("immutable_inputs",{})
    needed={"FIT_LEDGER.json","INPUT_QUALIFICATION.json","ML_ASSEMBLY.json","raw_score","hlabels","old_report","old_evidence"}
    need(needed<=set(immutable),"ORIGINAL_DELIVERY_INPUT_PINS_REQUIRED")
    original_assembly_ref=dict(path=str(RUN/"ML_ASSEMBLY.json"),sha256=OLD_ML_ASSEMBLY_SHA)
    execution_review=_read(terminal["review_ref"])
    need(execution_review.get("status")=="PASS" and execution_review.get("research_id")==ID
         and assembly.get("original_ml_assembly_ref")==immutable["ML_ASSEMBLY.json"]==original_assembly_ref
         and execution_review.get("immutable_inputs",{}).get("ML_ASSEMBLY.json")==original_assembly_ref,
         "ORIGINAL_ML_ASSEMBLY_EXACT_INDEPENDENT_PHYSICAL_CUSTODY_REQUIRED")
    for key in needed: ctl.pin(immutable[key])
    need(immutable["raw_score"]==design["raw_score"] and immutable["hlabels"]==design["inputs"]["hlabels"]
         and immutable["FIT_LEDGER.json"]["sha256"]==transport.BASELINE_HASHES["FIT_LEDGER.json"]
         and immutable["old_evidence"]==precomputed.C14_EVIDENCE,
         "ORIGINAL_LABEL_AND_ML_INPUT_CUSTODY_REQUIRED")
    q=_read(immutable["INPUT_QUALIFICATION.json"])
    need(q.get("research_id")==ID and q.get("pair_key_sha256")==gate["pair_key_sha256"],
         "ORIGINAL_PAIR_GEOMETRY_QUALIFICATION_REQUIRED")
    for item in assembly["panels"].values(): ctl.pin(item)
    return design_ref,design,review,terminal,assembly,gate,q


def new_memberships(design,assembly,gate,new_roles,reference,clock):
    calendar,_,mature=ev._clock(clock); progressive=mature[mature.year>=2024]
    edges={};panels={};rows=[]
    for role in new_roles:
        panel=_project(assembly["panels"][role],PANEL,dates=calendar)
        need(panel.candidate_id.eq(role).all(),"NEW_PANEL_EXACT_ROLE_REQUIRED")
        daily=ev.membership_diagnostics(role,reference,panel,clock,final_gate=gate,
            expected_design_sha256=outcomes.binding.DESIGN_SHA)
        wanted=mature if role in ev.CLASSICAL else progressive
        series=daily.set_index("signal_date").loc[wanted,"replacement_edge"]
        need(series.index.equals(wanted) and np.isfinite(series.to_numpy(float)).all(),
             "NO732_OR482_MISSING_EDGE_PADDING")
        edges[role]=series; panels[role]=panel;rows.append(daily)
    return edges,panels,pd.concat(rows,ignore_index=True) if rows else pd.DataFrame()


def matched_additions(edges,pre,clock,old_evidence):
    _,_,mature=ev._clock(clock); wanted=mature[mature.year>=2024]
    complete={r["candidate_id"] for r in pre["summaries"] if r["status"]=="COMPLETE"}
    contrasts={cid:ends for cid,ends in ev.CONTRASTS.items()
               if cid not in complete and any(side in edges for side in ends)
               and all(side in edges or side in complete for side in ends)}
    needed=sorted({side for ends in contrasts.values() for side in ends if side not in edges})
    endpoints={}
    if needed:
        reference=old_evidence["diagnostics"]["PRIMARY_DAILY_EDGE"]
        frame=_project(reference,["signal_date",*needed],dates=wanted).set_index("signal_date")
        need(frame.index.equals(wanted) and np.isfinite(frame[needed].to_numpy(float)).all(),
             "EXACT482_RETAINED_ENDPOINTS_ONLY")
        endpoints={cid:frame[cid].copy() for cid in needed}
    combined={**endpoints,**edges}
    for cid,(left,right) in contrasts.items():
        edges[cid]=combined[left]-combined[right]
    return edges,endpoints


def h5_keys(reference,panels,clock):
    _,_,mature=ev._clock(clock); pieces=[]
    for role,panel in panels.items():
        if role not in ev.RISK_CLASSICAL: continue
        selected=panel.loc[panel["rank"].le(20),KEYS]
        raw=reference.loc[reference.raw_rank.le(20),KEYS+["ticker"]]
        take=pd.concat([raw,selected.merge(reference[KEYS+["ticker"]],on=KEYS,validate="one_to_one")])
        pieces.append(take.loc[take.signal_date.isin(mature),KEYS+["ticker"]])
    return outcomes.owner.requested_keys(pd.concat(pieces).drop_duplicates(KEYS)) if pieces else None


def h5_decision_gate(design_ref,review_ref,terminal,keys):
    return dict(status="PASS",research_id=ID,design_sha256=design_ref["sha256"],review_ref=review_ref,
        decision_frozen=True,outcome_reads_before_gate=0,requested_keys_sha256=outcomes.content_hash(keys),
        test2026_rows_read=0,strict_PIT_promotion_eligible=False,
        score_assembly_ref=terminal["assembly"],final_pipeline_ref=terminal["final_pipeline"],
        all_applicable_risk_roles_terminal=True,full_calendar_count=752,mature_count=732,
        progressive_mature_count=482,risk_delta_ref=terminal["delta"],
        original_ml_gate_ref=dict(path=str(RUN/"FINAL_PIPELINES_FREEZE.json"),sha256=outcomes.OLD_ML_GATE_SHA),
        h5_sources=deepcopy(outcomes.H5_REFS))


def saved_variance_diagnostics(assembly,roles,clock,*,include_saved_coordinates=False):
    calendar,_,mature=ev._clock(clock);frames={};summaries=[]
    for role in roles:
        if role=="C14_D02":
            summaries.append(dict(candidate_id=role,status="EXACT_RAW_IDENTITY_NO_RISK_PAYLOAD",
                applicable_dates=752,native_risk_estimates=0,formal_risk_efficiency_eligible=False));continue
        pref=assembly.get("predicted_risk",{}).get(role)
        vref=assembly.get("variance_diagnostics",{}).get(role)
        need(pref is None or vref is None or pref==vref,"EXACT_SAVED_VARIANCE_REFERENCE_REQUIRED")
        ref=vref if vref is not None else pref
        if ref is None:
            summaries.append(dict(candidate_id=role,status="PREDICTED_DIAGNOSTIC_UNAVAILABLE",
                reason="NO_SAVED_NATIVE_VARIANCE_ARTIFACT",formal_risk_efficiency_eligible=role in ev.RISK_CLASSICAL));continue
        wanted=calendar if role in ev.RISK_CLASSICAL else calendar[calendar.year>=2024]
        columns=["signal_date","predicted_variance_before","predicted_variance_after"]
        if include_saved_coordinates: columns+=["before","after"]
        saved=_project(ref,columns,dates=wanted).set_index("signal_date")
        frame=saved[["predicted_variance_before","predicted_variance_after"]]
        need(frame.index.equals(wanted) and np.isfinite(frame.to_numpy(float)).all()
             and (frame.to_numpy(float)>=0).all(),"EXACT_SAVED752_OR502_NATIVE_VARIANCE_REQUIRED")
        frames[role]=frame
        for year in (2023,2024,2025,"POOLED"):
            group=frame if year=="POOLED" else frame.loc[frame.index.year==year]
            applicable=mature if role in ev.RISK_CLASSICAL else mature[mature.year>=2024]
            group_mature=group.loc[group.index.isin(applicable)]
            summaries.append(dict(candidate_id=role,year=str(year),
                status="COMPLETE_SAVED_NATIVE_VARIANCE" if len(group) else "EXACT_2023_RAW_FALLBACK_NO_PREDICTED_RISK",
                prediction_dates=len(group),mature_dates=len(group_mature),source_ref=ref,descriptive_only=True,
                predicted_variance_before_mean=float(group.predicted_variance_before.mean()) if len(group) else None,
                predicted_variance_after_mean=float(group.predicted_variance_after.mean()) if len(group) else None,
                formal_risk_efficiency_eligible=role in ev.RISK_CLASSICAL,
                predicted_variance_difference_mean=float((group.predicted_variance_after-group.predicted_variance_before).mean()) if len(group) else None,
                risk_contributions_available=False,saved_risk_coordinate_summaries_available=include_saved_coordinates,
                individual_rc_vectors_available=False,
                new_covariance_estimation=False))
            if include_saved_coordinates:
                selected=saved.loc[group.index]
                for side in ("before","after"):
                    values=selected[side].tolist()
                    need(all(isinstance(v,dict) for v in values),"SAVED_COORDINATE_STRUCT_REQUIRED")
                    keys=("predicted_variance","abs_rc_hhi","enb","max_correlation","max_abs_correlation",
                          "diversification_ratio","condition_number")
                    coordinate={}
                    for key in keys:
                        numbers=[v.get(key) for v in values if v.get(key) is not None]
                        need(all(np.isfinite(v) for v in numbers),"FINITE_SAVED_COORDINATE_OR_NULL_REQUIRED")
                        coordinate[key]=float(np.mean(numbers)) if numbers else None
                    coordinate.update(dates=len(values),singular_dates=sum(v.get("singular_covariance") is True for v in values),
                        statuses={status:sum(v.get("status")==status for v in values)
                            for status in sorted({str(v.get("status")) for v in values})})
                    summaries[-1]["saved_coordinates_"+side]=coordinate
    return frames,summaries


def risk_inputs(reference,panels,clock,h5,h5_receipt,assembly,review,*,saved_variance=None):
    """Reuse original pure H5 basket diagnostic code; never estimate covariance."""
    _,_,mature=ev._clock(clock); result={};blocked={};daily=[];summaries=[]
    path=Path(ev.risk_metrics.__file__).resolve()
    kernel=bind_pinned_kernel(ev.risk_metrics.risk_diagnostics,physical_path=path,
        expected_sha256=review["source_pins"][str(path)],dependencies=dict(ACTIVE_ROLES=ev.RISK_CLASSICAL))
    if saved_variance is None:
        saved_variance,_=saved_variance_diagnostics(assembly,list(panels),clock)
    for role,panel in panels.items():
        if role not in ev.RISK_CLASSICAL: continue
        frame,summary=kernel(role,reference,panel,clock,realized_h5=h5)
        pred=saved_variance.get(role)
        decreased=False;predicted_status="PREDICTED_DIAGNOSTIC_UNAVAILABLE"
        if pred is not None:
            formal=pred.loc[mature]
            need(formal.index.equals(mature) and np.isfinite(formal.to_numpy(float)).all()
                 and (formal.to_numpy(float)>=0).all(),"FULL732_SAVED_PREDICTED_VARIANCE_REQUIRED")
            decreased=bool(formal.predicted_variance_after.mean()<formal.predicted_variance_before.mean())
            predicted_status="COMPLETE_ORIGINAL_SAVED_VARIANCE"
            frame["prediction_status"]="COMPLETE_SAVED_NATIVE_VARIANCE"
            frame["predicted_variance"]=frame.signal_date.map(pred.predicted_variance_after)
            frame["raw_predicted_variance"]=frame.signal_date.map(pred.predicted_variance_before)
            for item in summary:
                values=pred if item["year"]=="POOLED" else pred.loc[pred.index.year==int(item["year"])]
                item.update(valid_predicted_risk_dates=len(values),prediction_status=predicted_status,
                    predicted_variance_mean=float(values.predicted_variance_after.mean()),
                    raw_predicted_variance_mean=float(values.predicted_variance_before.mean()),
                    predicted_variance_difference_mean=float((values.predicted_variance_after-values.predicted_variance_before).mean()),
                    prediction_coordinate="ORIGINAL_SAVED_NATIVE_VARIANCE_NO_COVARIANCE_REREAD")
        else:
            for item in summary: item["prediction_status"]=predicted_status
        daily.append(frame);summaries.extend(summary)
        valid=frame.set_index("signal_date").loc[mature]
        if not valid.realized_status.eq("COMPLETE").all():
            blocked[role]="BLOCKED_FULL732_NATIVE_H5_UNION_QUALIFICATION";continue
        raw=valid.raw_h5_return.astype(float);selected=valid.selected_h5_return.astype(float)
        need(raw.index.equals(mature) and selected.index.equals(mature)
             and np.isfinite(raw).all() and np.isfinite(selected).all(),"EXACT_FULL732_NATIVE_H5_REQUIRED")
        result[role]=dict(raw=raw,selected=selected,qualification=dict(status="PASS",
            source_receipt_sha256=outcomes.content_hash(h5_receipt),horizon_sessions=5,complete_dates=732,
            labels_mature_pre2026=True,native_shareholder_coordinate=True,
            predicted_risk_decreased=decreased,predicted_diagnostic_status=predicted_status))
    return result,blocked,pd.concat(daily,ignore_index=True) if daily else pd.DataFrame(),summaries


def new_pair_diagnostics(run,design,q,assembly,gate,new_roles,clock,old_evidence):
    roles=[r for r in new_roles if r in ev.HYBRIDS]
    if not roles: return pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),None
    _,_,mature=ev._clock(clock); wanted=mature[mature.year>=2024]
    # Original projected MEAN_ER reader; never call old finish or solve oracle.
    geometry,truth,_,_,receipt=ctl.label_pairs(run,design,q,"2026-01-01",start="2024-01-01")
    need(pd.DatetimeIndex(sorted(geometry.signal_date.unique())).equals(wanted) and len(geometry)==482*200,
         "EXACT_MATURE482_PAIR_LABELS_NO_TAIL")
    oref=old_evidence["diagnostics"]["SHARED_ORACLE"]
    oracle=_project(oref,["signal_date","oracle_utility"],dates=wanted).set_index("signal_date").oracle_utility
    need(oracle.index.equals(wanted) and np.isfinite(oracle).all(),"ONLY_ORIGINAL_COMPLETE482_SHARED_ORACLE_REUSE")
    daily=[];bins=[];ranks=[]
    for role in roles:
        ref=assembly["native_pair_predictions"][role]
        need(ref.get("kind")=="U0_POINT_GT0","EXACT_HYBRID_U0_NATIVE_PAIR_REQUIRED")
        frame=_project(ref,[*ctl.PAIR_KEYS,"point"],dates=wanted)
        need(frame[list(ctl.PAIR_KEYS)].equals(geometry[list(ctl.PAIR_KEYS)]),
             "EXACT_NEW_NATIVE_PAIR_ORDER_REQUIRED")
        matches=_project(dict(path=ref["matching_path"],sha256=ref["matching_sha256"]),
            [*ctl.PAIR_KEYS,"predicted_edge"],dates=wanted,allow_empty=True)
        a,b,c=ev.pair_diagnostics(role,geometry,frame.point.to_numpy(float),truth,matches,oracle,
            final_gate=gate,expected_design_sha256=outcomes.binding.DESIGN_SHA)
        daily.append(a);bins.append(b);ranks.append(c)
    return tuple(pd.concat(items,ignore_index=True) for items in (daily,bins,ranks))+(receipt,)


def coverage_and_counts(design,gate,terminal,review,*,post_reboot_checkpoint_ref=None):
    # An existing pinned delta is mandatory, so RiskJournal cannot create HEADER.
    ctl.pin(terminal["delta"])
    need(Path(terminal["delta"]["path"]).exists(),"EXISTING_DELTA_RESTORE_ONLY")
    if post_reboot_checkpoint_ref is None:
        journal=transport.RiskJournal(RUN)
    else:
        need(review.get("delivery_inputs",{}).get("post_reboot_checkpoint")==post_reboot_checkpoint_ref,
             "EXPLICIT_REVIEWED_POST_REBOOT_JOURNAL_ADMISSION_REQUIRED")
        journal=transport.RiskJournal(RUN,post_reboot_checkpoint_ref=post_reboot_checkpoint_ref)
    journal.verify()
    need(all(r.get("status") in ("COMPLETE","FAILED") for r in journal.requests.values()),
         "NO_UNRESOLVED_CHARGED_SOLVE_REQUESTS")
    need(not any(s["status"] in ("STARTED","RESERVED") for s in journal.slots.values()),
         "NO_UNRESOLVED_CONDITIONAL_COVERAGE_SLOTS")
    need(sum(r["status"]!="UNRESERVED" for r in journal.slots.values())==terminal["reserved_fit_slots"]
         and sum(r["entered"] for r in journal.slots.values())==terminal["backend_entered"]
         and len(journal.requests)==terminal["charged_solves"],"ACTUAL_DELTA_COUNTS_MUST_MATCH_TERMINAL")
    old=_read(review["immutable_inputs"]["FIT_LEDGER.json"])
    slots=[{**r,"backend_entered":bool(r["entered"])} for r in old["slots"].values()]
    slots += [{**r,"backend_entered":bool(r["entered"])} for r in journal.slots.values()]
    audit=ev.training_coverage_audit(design["coverage_plan"],slots,gate["role_statuses"])
    need(len(audit)==12,"ALL12_COVERAGE_DIMENSIONS_REQUIRED")
    counts=dict(journal.counts(),conditional_complete=sum(r["status"]=="COMPLETE" for r in journal.slots.values()),
        conditional_failed=sum(r["status"]=="FAILED" for r in journal.slots.values()),
        conditional_blocked=sum(r["status"]=="BLOCKED_DEPENDENCY" for r in journal.slots.values()),
        original_ml_summary_recomputed=False,scientific_retry=0,failed_reservation_refund=False,
        new_risk_estimations_by_C=0,fit_cap=1800,solve_cap=30000,named_solve_ceiling=29542)
    return audit,counts



def _records(frame):
    return frame.astype(object).where(pd.notna(frame),None).to_dict("records")


def diagnostic_summary(daily,pairs,bins,ranks,diagnostics,roles,variance_summary):
    def means(frame,keys,columns):
        if frame.empty: return []
        return _records(frame.groupby(keys)[columns].mean().reset_index())
    membership=means(daily,["candidate_id","year"],["replacement_edge","raw_overlap","replacement_count",
        "membership_turnover","challenger_raw_rank_mean","incumbent_raw_rank_mean"])
    for item in membership:
        group=daily.loc[daily.candidate_id.eq(item["candidate_id"]) & daily.year.eq(item["year"])]
        item.update(prediction_geometry_dates=len(group),mature_alpha_dates=int(group.replacement_edge.notna().sum()))
    pair=means(pairs,["candidate_id","year"],["pair_regret","matching_utility","oracle_matching_utility",
        "matching_regret","replacement_count","wrong_replacement_count","correct_replacement_count",
        "sign_accuracy","mean_absolute_edge_error"])
    rank=[] if ranks.empty else _records(ranks.groupby(["candidate_id","side","raw_rank"]).size().rename("replacements").reset_index())
    return dict(membership=membership,pair_and_matching=pair,replacement_rank_distribution=rank,
        calibration_rows=len(bins),calibration_ref=diagnostics["NEW_PAIR_CALIBRATION"],diagnostic_refs=diagnostics,
        saved_variance=variance_summary,pair_availability={role:("COMPLETE_NATIVE_U0_482" if role in ev.HYBRIDS
            else "NOT_APPLICABLE_NO_NATIVE_PAIR_PREDICTIONS") for role in roles},
        calibration_scope="Saved U0 point edge bins/sign/error only; Brier and quantile coverage are unavailable for these point heads",
        aggregation="Descriptive means of new saved daily diagnostics only; no calibration fit or extra hypothesis",
        oracle_scope="Original pinned mature482 oracle reused; no new oracle solve")


def _published_text(reference):
    path=ctl.pin(reference);raw=path.read_bytes()
    need(outcomes.binding.sha(path)==reference["sha256"],"PUBLISHED_REPORT_CUSTODY_CHANGED")
    return raw.decode("utf-8")


def _report_table(rows,columns):
    def cell(value):
        if value is None:return "不可得/不适用"
        if isinstance(value,(dict,list,tuple)):
            value=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,default=str)
        return str(value).replace("|","\\|").replace("\n","<br>")
    head="| "+" | ".join(label for _,label in columns)+" |"
    return "\n".join([head,"| "+" | ".join("---" for _ in columns)+" |",
        *("| "+" | ".join(cell(row.get(key)) for key,_ in columns)+" |" for row in rows)])


def joined_report_details(payload):
    """Format existing frozen metadata/published summaries; no scientific call."""
    design=payload.get("design_metadata",{});statuses=payload.get("role_statuses",{})
    faults=payload.get("role_failure_details",payload.get("faults",{}))
    published={r["candidate_id"]:r for r in payload.get("published_c14_summaries",[])}
    joint={r["candidate_id"]:r for r in payload.get("tests",[])}
    bindings={r.get("role",r.get("candidate_id")):r for r in
         [*design.get("role_bindings",[]),*design.get("fusion_bindings",[])]}
    rows=[]
    for role in design.get("roles",list(statuses)):
        old=published.get(role,{});new=joint.get(role,{})
        rows.append(dict(role=role,status=statuses.get(role,"UNKNOWN"),reason=faults.get(role),
             domain="FULL_732" if role in ev.CLASSICAL else "PROGRESSIVE_482",
             definition=bindings.get(role),published_lower=old.get("simultaneous_lower_95"),
             joint_lower=new.get("simultaneous_lower_95"),source=payload.get("terminal_ref")))
    pieces=["## 全部固定角色与终态",
        "原ML35角色、风险角色、固定contrast的阻塞/失败均保留；表中历史发布lower与本次joint lower分列，均值、SE、year及旧maxima不重算。",
        _report_table(rows,[("role","角色"),("status","终态"),("reason","失败/阻塞原因"),("domain","适用域"),
             ("definition","原冻结学习/输出定义"),("published_lower","原发布lower(原return单位)"),("joint_lower","联合lower(原return单位)"),
             ("source","终态来源")]),
        "## 原147历史摘要与联合门槛",
        "均值、SE、year沿用原发布摘要；原147摘要未保存旧lower时明确不可得，不倒推原发布值。"
        "下面联合lower仅展示原incremental返回值；旧maxima只通过原custody/cache ref保留。",
        _report_table([{**row,"joint_lower":{r["candidate_id"]:r for r in payload.get("legacy_summaries",[])}
             .get(row["candidate_id"],{}).get("simultaneous_lower_95")}
             for row in payload.get("published_legacy_summaries",[])],[
             ("candidate_id","历史ID"),("pooled_edge","原均值(原return单位)"),("bootstrap_se","原SE(原return单位)"),("year_edges","原year值(原return单位)"),
             ("simultaneous_lower_95","原发布lower(原return单位)"),("joint_lower","联合lower(原return单位)"),("provenance","原发布来源")]),
        _report_table([dict(kind=k,reference=v) for k,v in payload.get("precomputed_custody",{}).items()],
             [("kind","旧summary/maxima custody"),("reference","精确来源/哈希")]),
        "## 固定设计与原ML审计",
        "Raw1–10 core；Raw11–20 incumbent、21–40 entrant；每日200 pair、最多10替换、Top20等权。current216/风险hybrid228。"
        "752预测日；732成熟日(2023/24/25=250/252/230)；learned502预测/482成熟(252/230)；2023 exact Raw fallback；20尾日不评价。"
        "MEAN_ER四期限alpha与绝对shareholder H5分开。",
        "原ML seed/capacity/真正OOF及失败记录保留在末尾精确发布附录；其中风险等待描述是历史状态，当前状态以本报告终态表为准。"
        "LOW/MID/HIGH和固定三个seed没有再次选择；无in-sample融合，无Raw替代缺失OOF。",
        _report_table([{**row,"planned_values":design.get("coverage_plan",{}).get(row.get("dimension"),{}).get("planned"),
            "role_members":design.get("coverage_plan",{}).get(row.get("dimension"),{}).get("role_members")}
            for row in payload.get("training_coverage_audit",[])],[
             ("dimension","12维"),("planned","计划"),("actual","实际"),("attempted","尝试"),
             ("blocked","阻塞"),("uncovered","缺口"),("coverage","覆盖率"),("planned_values","计划值"),("role_members","角色范围"),("measurement","测量口径")]),
        "覆盖率是原owner定义的维度覆盖，不是组合穷尽；event-risk role_members若为空，不能因B bank存在宣称C训练过风险估计，C新增估计仍为0。",
        "## 已保存H5描述与正式风险效率",
        "H5相互重叠、非IID；q05 exceedance proxy与正式fractional-tail empirical CVaR分开。"
        "只对既有classical正式H5 union请求；不为报告扩展RX/G outcome读取。"
        "std/downside/q05/exceedance/CVaR保留原return单位，variance_difference及预测方差单位为return²。",
        _report_table(payload.get("h5_summary",[]),[("candidate_id","角色"),("year","年度"),
             ("applicable_dates","适用日"),("valid_h5_dates","有效H5"),("blocked_h5_dates","阻塞H5"),
             ("raw","Raw std/downside/q05/CVaR(原return单位)"),("selected","selected std/downside/q05/CVaR(原return单位)"),
             ("predicted_variance_difference_mean","预测方差差(return²)"),("tail_definition","尾部定义")]),
        _report_table([dict(role=r,**v.get("conditions",{}),supported=v.get("supported"))
             for r,v in payload.get("bootstrap",{}).get("risk_efficiency",{}).items()],[
             ("role","风险效率角色"),("complete_full732_alpha","完整732"),("alpha_noninferiority_lower_ge_zero","alpha lower>=0"),
             ("downside_simultaneous_lower_positive","DOWN lower>0"),("cvar_simultaneous_lower_positive","CVaR lower>0"),
             ("predicted_risk_decreased","预测风险下降"),("supported","支持")]),
        "## 原生保存预测坐标",
        _report_table(payload.get("variance_summary",[]),[("candidate_id","角色"),("year","年度"),("status","状态"),
             ("prediction_dates","预测分母"),("mature_dates","成熟分母"),("predicted_variance_before_mean","before方差(return²)"),
             ("predicted_variance_after_mean","after方差(return²)"),("predicted_variance_difference_mean","方差差(return²)"),
             ("saved_coordinates_before","保存before坐标"),("saved_coordinates_after","保存after坐标"),
             ("source_ref","原artifact")]),
        "D02为Raw identity无riskpayload；G仅502预测/482成熟，2023不伪称risk可得；RX未保存variance时明确不可得。"
        "abs_rc_hhi/ENB/相关性/分散率/condition/singular仅投影已保存before/after；individual RC向量未保存，不能重造。"
        "保存坐标中的predicted_variance单位为return²；其余保存坐标保留原坐标单位。"
        "variance不能替代tail/replica uncertainty gate的原判据。",
        "## 校准、regret、rank与替换",
        _report_table(payload.get("diagnostic_summary",{}).get("membership",[]),[
             ("candidate_id","角色"),("year","年度"),("prediction_geometry_dates","geometry/overlap分母"),
             ("mature_alpha_dates","alpha成熟分母"),("replacement_edge","alpha edge(原return单位)"),("raw_overlap","Raw重叠"),("replacement_count","替换数"),
             ("membership_turnover","换手"),("challenger_raw_rank_mean","entrant rank"),("incumbent_raw_rank_mean","incumbent rank")]),
        _report_table(payload.get("diagnostic_summary",{}).get("pair_and_matching",[]),[
             ("candidate_id","角色"),("year","年度"),("pair_regret","pair regret(原return单位)"),("matching_utility","matching utility(原return单位)"),
             ("oracle_matching_utility","原oracle(原return单位)"),("matching_regret","matching regret(原return单位)"),("wrong_replacement_count","错误替换"),
             ("correct_replacement_count","正确替换"),("sign_accuracy","符号准确"),("mean_absolute_edge_error","MAE(原return单位)")]),
        _report_table(payload.get("diagnostic_summary",{}).get("replacement_rank_distribution",[]),[
             ("candidate_id","角色"),("side","侧"),("raw_rank","Raw rank"),("replacements","替换频次")]),
        _report_table([dict(kind=k,reference=v) for k,v in payload.get("diagnostics",{}).items()],
             [("kind","诊断/point bins"),("reference","精确来源")]),
        "classical/G无native pair，不制造Brier或quantile coverage；RX U0仅point/sign/error，旧概率/分位诊断沿用原发布附录。",
        "## 预算、恢复与限制",
        _report_table([dict(item=k,value=v) for k,v in payload.get("budget",{}).items()],[("item","口径"),("value","计数/状态")]),
        "656原reservation+最多144 conditional=800 named上界，硬cap1800；Gate composite reservation不是独立backend数。"
        "共享risk attributable cap3000；18006原solve+delta累计不超过29542/30000；oracle新增solve0。"
        "历史qualification、ROOT1 execution、本次resumed input instrumentation分列，中断读取量UNKNOWN_DUE_REBOOT；inputowner solver=0不等于ledger实际solve=0。",
        _report_table([dict(scope=k,value=v) for k,v in payload.get("execution_input_counts",{}).items()],
             [("scope","读取计数范围/来源"),("value","计数")]),
        "旧147numeric/226exposure+75alpha+20risk=321；5000/block20同draw，固定732/482 mask。"
        "failed不补零，maxima/critical不下降；旧均值/SE/year原值保留，联合lower只按原incremental代数更新。",
        "自然终态、工程通过、覆盖充分、科学支持和生产授权是分别的主张。"
        "DELTA8/D12仍BLOCKED_BUDGET；C15未执行；strict_PIT_promotion_eligible=false；不得声称账户净赚或独立留出。"]
    for title,item in payload.get("retained_published_reports",{}).items():
        pieces.extend(["## "+title,"精确历史原文；其等待/剩余状态属于原发布时点。来源："+str(item["source_ref"]),item["text"]])
    return "\n\n".join(pieces)


def render_report(payload):
    prefix=("# C14 增量风险联合交付\n\n"
        "原 ML 无支持结论仅作为历史发布事实；此处没有重跑旧147/75项均值、SE、旧诊断或bootstrap。"
        "原5000共享maxT向量与旧摘要原值保留，只对新固定合格风险/contrast列续接同一321曝光门槛。\n\n"
        "2023 的 RX/G 是精确Raw fallback，学习成功域仍为2024/25原482成熟日；classical需原732成熟日。"
        "20个未知tail不评价、不补造，不重解共享oracle。"
        "Alpha使用MEAN_ER_3D_5D_10D_20D，风险检验使用绝对shareholder H5，两个目标不得互换。\n\n"
        "风险效率支持须 full732 alpha simultaneous lower>=0、DOWN/CVaR两项lower>0并预测风险下降；"
        "所有结果仍是已暴露历史机制证据，strict_PIT_promotion_eligible=false，不能声称账户净赚或独立留出。\n\n")
    return (prefix+joined_report_details(payload)+"\n\n"+ev.render_report(payload).replace("所有edge及lower bound单位为bp；",
        "以下alpha汇总表edge/lower单位为bp；")+"\n\n新增H5描述与准入缺口：\n\n"+str(payload.get("h5_summary",[]))+
        "\n\n原生保存预测方差：\n\n"+str(payload.get("variance_summary",[]))+
        "\n\nG仅502预测/482成熟日期描述；2023精确Raw不伪称预测风险可得。无native pair的classical/G不制造pair校准；其余不可得字段及证据ref见机制诊断。\n")



def statistics_once(root,*,terminal_ref,source_review_ref,precomputed_review_ref,legacy_summary_ref,
        pre,clock,custody,edges,endpoints,risk,failures,design,gate,assembly,
         post_reboot_checkpoint_ref=None,post_reboot_completion_ref=None):
    """Commit new statistics once; later report repair uses exact pinned values."""
    root=Path(root)
    need(root.resolve()==(RUN/"risk_execution"/ROOT_NAME).resolve(),"EXACT_JOINT_STATISTICS_CACHE_ROOT")
    expected=custody["expected_precomputed_sha256"]
    need(incremental.content_hash(pre)==expected,"EXACT_STATISTICS_PRECOMPUTED_CONTENT_PIN")
    inputs=dict(clock=clock,rule=design["evaluation"]["bootstrap"],
        legacy_ids=design["evaluation"]["legacy"]["numeric_ids"],specs=design["evaluation"]["new_specs"],
        new_edges=edges,retained_endpoints=endpoints,risk_inputs=risk,failures=failures,
        design=design,gate=gate,assembly=assembly)
    identity=dict(terminal_ref=terminal_ref,source_review_ref=source_review_ref,
        precomputed_review_ref=precomputed_review_ref,legacy_summary_ref=legacy_summary_ref,
        precomputed_sha256=expected,fixed_inputs_sha256=incremental.content_hash(inputs))
    need((post_reboot_checkpoint_ref is None)==(post_reboot_completion_ref is None),
         "PAIRED_POST_REBOOT_STATISTICS_CUSTODY_REQUIRED")
    if post_reboot_checkpoint_ref is not None:
        identity.update(post_reboot_checkpoint_ref=post_reboot_checkpoint_ref,
             post_reboot_completion_ref=post_reboot_completion_ref)
    started=root/"JOINT_STATISTICS_STARTED_R1.json"
    complete=root/"JOINT_STATISTICS_COMPLETE_R1.json"
    values_path=root/"JOINT_STATISTICS_VALUES_R1.json"
    maxima_path=root/"JOINT_STATISTICS_MAXIMA_R1.parquet"

    def restore():
        need(started.exists(),"COMPLETE_STATISTICS_REQUIRES_ORIGINAL_STARTED_RECEIPT")
        beginning=_read(_ref(started)); receipt=_read(_ref(complete))
        need(beginning==dict(status="STARTED",research_id=ID,identity=identity,scientific_retry=0)
             and receipt.get("status")=="COMPLETE" and receipt.get("research_id")==ID
             and receipt.get("identity")==identity and receipt.get("scientific_retry")==0,
             "EXACT_STATISTICS_CACHE_LINEAGE_REQUIRED")
        vref,mref=receipt["values_ref"],receipt["maxima_ref"]
        need(Path(vref["path"]).resolve()==values_path.resolve()
             and Path(mref["path"]).resolve()==maxima_path.resolve(),"EXACT_STATISTICS_CACHE_OUTPUT_PATHS")
        values=_read(vref)
        maxima=precomputed._project(mref,("max_t",)).max_t.to_numpy(float)
        need(maxima.shape==(5000,) and np.isfinite(maxima).all()
             and (maxima>=np.asarray(pre["maxima"],float)).all(),"EXACT_COMPLETE5000_STATISTICS_CACHE_MAXIMA")
        need(incremental.content_hash(dict(values=values,maxima=maxima))==receipt["output_content_sha256"],
             "STATISTICS_CACHE_CONTENT_CHANGED")
        rows,bootstrap,legacy=values["tests"],values["bootstrap"],values["legacy_summaries"]
        need([r["candidate_id"] for r in rows]==[r["candidate_id"] for r in inputs["specs"]]
             and [r["candidate_id"] for r in legacy]==inputs["legacy_ids"]
             and [r["candidate_id"] for r in bootstrap["risk_tests"]]==[r["candidate_id"] for r in ev.RISK_SPECS]
             and bootstrap.get("status")=="COMPLETE" and bootstrap.get("repeats")==5000
             and bootstrap.get("exposure_namespace")==321 and bootstrap.get("strict_PIT_promotion_eligible") is False
             and bootstrap.get("independent_holdout") is False
             and bootstrap.get("old147_bootstrap_calls")==bootstrap.get("old_ml_bootstrap_calls")==0
             and bootstrap.get("incremental_precomputed_sha256")==expected
             and bootstrap["critical_max_t"]==float(np.quantile(maxima,.95,method="higher")),
             "COMPLETE_FROZEN_STATISTICS_CACHE_RECEIPT_REQUIRED")
        return rows,bootstrap,maxima,legacy,_ref(complete)

    if complete.exists(): return restore()
    need(not started.exists(),"EXISTING_NEW_STATISTICS_ATTEMPT_NO_AUTOMATIC_REBOOTSTRAP")
    writer.put(started,dict(status="STARTED",research_id=ID,identity=identity,scientific_retry=0))
    rows,bootstrap,maxima,legacy=incremental.incremental_statistics(pre,edges,clock,inputs["rule"],
        inputs["legacy_ids"],inputs["specs"],failures,
        expected_precomputed_sha256=expected,retained_endpoints=endpoints,
        expected_endpoint_sha256=incremental.content_hash(endpoints) if endpoints else None,risk_inputs=risk,
        design=design,gate=gate,assembly=assembly,expected_design_sha256=gate["design_sha256"])
    # Persist before any diagnostic/report write. No STARTED-only retry is legal.
    def scalar(value):
        if isinstance(value,np.generic): return value.item()
        raise TypeError("UNKNOWN_STATISTICS_CACHE_JSON_TYPE:"+type(value).__name__)
    values=json.loads(json.dumps(dict(tests=rows,bootstrap=bootstrap,legacy_summaries=legacy),
        allow_nan=False,default=scalar))
    maxima=np.asarray(maxima,float)
    writer.put(values_path,values)
    writer.table(maxima_path,pd.DataFrame(dict(max_t=maxima)))
    writer.put(complete,dict(status="COMPLETE",research_id=ID,identity=identity,scientific_retry=0,
        values_ref=_ref(values_path),maxima_ref=_ref(maxima_path),
        output_content_sha256=incremental.content_hash(dict(values=values,maxima=maxima))))
    return restore()


def deliver(run,terminal_ref,source_review_ref,precomputed_review_ref,legacy_summary_ref,
        *,post_reboot_checkpoint_ref=None):
    args=terminal_inputs(run,terminal_ref,source_review_ref,precomputed_review_ref,legacy_summary_ref,
         post_reboot_checkpoint_ref=post_reboot_checkpoint_ref)
    design_ref,design,review,terminal,assembly,gate,q=args
    root=RUN/"risk_execution"/ROOT_NAME
    recovery_refs=({k:review["delivery_inputs"][k] for k in
         ("post_reboot_checkpoint","post_reboot_completion","post_reboot_marker")}
         if post_reboot_checkpoint_ref is not None else {})
    done=root/"RISK_DELIVERY_COMPLETE_R1.json"
    if done.exists():
        value=_read(_ref(done))
        need(value.get("terminal_ref")==terminal_ref and value.get("source_review_ref")==source_review_ref
             and value.get("precomputed_review_ref")==precomputed_review_ref
             and value.get("legacy_summary_ref",legacy_summary_ref)==legacy_summary_ref
             and value.get("post_reboot_inputs",{})==recovery_refs,"EXACT_ADDITIVE_DELIVERY_REUSE_REQUIRED")
        for ref in value["outputs"].values(): ctl.pin(ref)
        return value
    # Actual delta terminality/counts are checked before any numeric reader.
    audit,counts=coverage_and_counts(design,gate,terminal,review,
         post_reboot_checkpoint_ref=post_reboot_checkpoint_ref)
    # Original published statistical custody is independently reviewed again.
    pre,clock,custody=precomputed.load_precomputed(design_ref,precomputed_review_ref,legacy_summary_ref)
    old_evidence=_read(precomputed.C14_EVIDENCE)
    reference=writer.old_delivery.reference_labels(design)
    roles=terminal["complete_conditional_roles"]
    edges,panels,daily=new_memberships(design,assembly,gate,roles,reference,clock)
    edges,endpoints=matched_additions(edges,pre,clock,old_evidence)
    saved_variance,variance_summary=saved_variance_diagnostics(assembly,roles,clock,
         include_saved_coordinates=post_reboot_checkpoint_ref is not None)
    keys=h5_keys(reference,panels,clock);risk={};blocked={};h5daily=pd.DataFrame();h5summary=[];h5receipt=None
    if keys is not None:
        hgate=h5_decision_gate(design_ref,source_review_ref,terminal,keys)
        hpath=root/"H5_DECISION_GATE_R1.json";writer.put(hpath,hgate)
        h5,h5receipt=outcomes.read_h5(design_ref,source_review_ref,_ref(hpath),keys)
        risk,blocked,h5daily,h5summary=risk_inputs(reference,panels,clock,h5,h5receipt,assembly,review,saved_variance=saved_variance)
    pdaily,bins,ranks,pair_receipt=new_pair_diagnostics(RUN,design,q,assembly,gate,roles,clock,old_evidence)
    failures={r:gate.get("role_failure_details",{}).get(r,gate["role_statuses"][r])
        for r in incremental.ADDITIONS if r not in edges and next(x for x in pre["summaries"] if x["candidate_id"]==r)["status"]!="COMPLETE"}
    rows,bootstrap,maxima,legacy,statistics_cache_ref=statistics_once(root,
        terminal_ref=terminal_ref,source_review_ref=source_review_ref,precomputed_review_ref=precomputed_review_ref,
        legacy_summary_ref=legacy_summary_ref,pre=pre,clock=clock,custody=custody,
        edges=edges,endpoints=endpoints,risk=risk,failures=failures,design=design,gate=gate,assembly=assembly,
        post_reboot_checkpoint_ref=post_reboot_checkpoint_ref,
        post_reboot_completion_ref=recovery_refs.get("post_reboot_completion"))
    for row in bootstrap["risk_tests"]:
        if row["status"]!="COMPLETE":
            row["failure_reason"]=blocked.get(row["role"],gate.get("role_failure_details",{}).get(row["role"],"NATIVE_FULL732_H5_NOT_QUALIFIED"))
    diagnostics={}
    for name,frame in (("NEW_DAILY_MEMBERSHIP",daily),("NEW_PAIR_DIAGNOSTICS",pdaily),
        ("NEW_PAIR_CALIBRATION",bins),("NEW_REPLACEMENT_RANKS",ranks),("NEW_H5_RISK_DIAGNOSTICS",h5daily),
        ("NEW_SAVED_VARIANCE_DIAGNOSTICS",pd.concat([f.reset_index().assign(candidate_id=r) for r,f in saved_variance.items()],ignore_index=True) if saved_variance else pd.DataFrame()),
        ("JOINT_BOOTSTRAP_MAXT",pd.DataFrame(dict(max_t=maxima)))):
        diagnostics[name]=writer.table(root/(name+".parquet"),frame)
    evidence=dict(research_id=ID,status="C14_JOINT_RISK_DELIVERY_TERMINAL",tests=rows,risk_tests=bootstrap["risk_tests"],
        bootstrap=bootstrap,legacy_summaries=legacy,training_coverage_audit=audit,budget=counts,
        role_statuses=gate["role_statuses"],role_failure_details=gate.get("role_failure_details",{}),
        all_applicable_risk_roles_terminal=True,diagnostics=diagnostics,terminal_ref=terminal_ref,
        source_review_ref=source_review_ref,precomputed_review_ref=precomputed_review_ref,precomputed_custody=custody,
        post_reboot_inputs=recovery_refs,
        h5_summary=h5summary,variance_summary=variance_summary,retained_ml_diagnostic_refs=old_evidence["diagnostics"],
        h5_receipt=h5receipt,pair_label_receipt=pair_receipt,h5_input_blockers=blocked,statistics_cache_ref=statistics_cache_ref,
        old147_statistics_recomputed=False,old75_statistics_recomputed=False,old_diagnostics_recomputed=False,
        oracle_new_solves=0,strict_PIT_promotion_eligible=False,independent_holdout=False,test2026_rows_read=0,
        no_account_net_profit_claim=True,coverage_sufficient_claim_allowed=False,
        limitation="Complete terminal delivery is not independent report acceptance or sufficient unblocked scientific coverage")
    writer.put(root/"JOINT_RISK_EVIDENCE_R1.json",evidence)
    retained_reports={}
    if post_reboot_checkpoint_ref is not None:
        for title,key in (("原ML发布报告历史附录","old_report"),("原ML详细审计历史附录","old_ml_audit")):
            reference=review["immutable_inputs"][key]
            retained_reports[title]=dict(source_ref=reference,text=_published_text(reference))
    completion=_read(recovery_refs["post_reboot_completion"]) if recovery_refs else {}
    report_payload=dict(evidence,h5_summary=h5summary,faults=evidence["role_failure_details"],
        design_metadata=design,published_c14_summaries=deepcopy(pre["summaries"]),
        published_legacy_summaries=deepcopy(pre["legacy_summaries"]),
        retained_published_reports=retained_reports,
        execution_input_counts={k:completion.get(k) for k in ("historical_qualification_counts",
            "prior_checkpoint_execution_input_counts","interrupted_worker_execution_input_counts",
            "resumed_worker_execution_input_counts")} if completion else {},
        remaining=[blocked,design["blocked_roles"],"C15未执行；DELTA8/D12仍BLOCKED_BUDGET；当前B scope外family保持BLOCK"],
        storage=dict(run=str(RUN),results=str(RESULTS)),preservation=review["immutable_inputs"],
        diagnostic_summary=diagnostic_summary(daily,pdaily,bins,ranks,diagnostics,roles,variance_summary))
    report=RESULTS/"JOINED_FINAL_REPORT_R1.md"
    assert_safe_output_path(report,kind="results",paths=resolve(ctl.REPO))
    report.parent.mkdir(parents=True,exist_ok=True);content=render_report(report_payload).encode("utf-8")
    if report.exists(): need(report.read_bytes()==content,"PRESERVE_DIFFERENT_JOINED_REPORT")
    else: report.write_bytes(content)
    # Preserve every reviewed original artifact and the exact final/delta chain.
    terminal_inputs(run,terminal_ref,source_review_ref,precomputed_review_ref,legacy_summary_ref,
         post_reboot_checkpoint_ref=post_reboot_checkpoint_ref)
    cache_metadata=_read(statistics_cache_ref)
    result=dict(status="C14_JOINT_RISK_DELIVERY_COMPLETE",research_id=ID,terminal_ref=terminal_ref,
        source_review_ref=source_review_ref,precomputed_review_ref=precomputed_review_ref,
        legacy_summary_ref=legacy_summary_ref,post_reboot_inputs=recovery_refs,
        outputs=dict(evidence=_ref(root/"JOINT_RISK_EVIDENCE_R1.json"),report=_ref(report),
            joint_maxima=diagnostics["JOINT_BOOTSTRAP_MAXT"],statistics_cache=statistics_cache_ref,
            statistics_values=cache_metadata["values_ref"],statistics_maxima=cache_metadata["maxima_ref"],**diagnostics),
        all_applicable_risk_roles_terminal=True,coverage_sufficient_claim_allowed=False,
        original_ml_outputs_immutable=True,old147_bootstrap_calls=0,old_ml_bootstrap_calls=0,
        oracle_new_solves=0,test2026_rows_read=0,scientific_retry=0,
        strict_PIT_promotion_eligible=False,independent_holdout=False)
    writer.put(done,result)
    return result
