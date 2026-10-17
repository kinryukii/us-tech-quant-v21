"""Task-scoped engineering continuation; original owners perform all science.

Proposal only. This module is not imported by the frozen source closure. There
is no risk, hybrid, outer outcome, bootstrap or new estimator implementation.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import contextmanager, nullcontext
import hashlib
import importlib
import json
from pathlib import Path
import re
import sqlite3
import traceback
from types import ModuleType

ID = "V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1"
RUN = Path("D:/us-tech-quant-backtests/V24/20261010T151740+0000_642c1248")
CACHE = Path("D:/us-tech-quant-cache/V24/C_SELECTOR/FULL_SELECTOR_FIXED_POLICY_FAST_R1")
REPO = Path("D:/us-tech-quant")
PHASES = ("core-account", "remaining-alpha")
PHASE_NAMES = {"core-account":"CORE_ACCOUNT_CONTINUATION_R1", "remaining-alpha":"REMAINING_ALPHA_CONTINUATION_R1"}
ORIGINAL_PINS = {
    "DESIGN_FREEZE.json":"20a855c2bf4df41b1e84fbc8159a473a04a575ccfb5ba76ed819d1975bcb8359",
    "FREEZE_ACCEPTANCE.json":"7f9a4bf1fd0128a8ab7b0f1628432e23e6722a20ea7279cd7f595b3ce6162636",
    "input_manifest.json":"788eb12fd3448dd83779536dbda2cee4cbb70e201edaf12f7890266041a91d5d",
    "run_config.json":"721a3b14d337caa8e5046fee3c76a7774b33017403369555d3f809f59d490c4a",
    "risk_inputs.json":"0873f9248858fd0e0ab08cdc590968b939e1bc6535af488579eca2a7c0be041f",
}
ACCOUNT_BASE = REPO/"scripts/research/a2/data/full_selector_account_inputs.py"
ACCOUNT_BASE_SHA = "f6b084e5ffead9fca2897dd1ba1605de2d54eb5290112fddb1ad860a6d1b9d6d"
ACCOUNT_CANDIDATE = CACHE/"proposals/account_inputs_r6.py"
ACCOUNT_CANDIDATE_SHA = "b25c84b0b778b54e52b3361018409eed09c9f0b4f07f03e68aa211728e39ecb1"
OVERLAY_GLOBALS = ("custody_reader", "OWNERS", "B_PRODUCER_TRANSPORT", "identity_links", "metadata_preflight")
TERMINAL = {"COMPLETE", "FAILED", "SOURCE_NOT_TESTABLE", "BLOCKED_DEPENDENCY"}


def require(ok, code):
    if not ok: raise ValueError(code)


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def ref(path):
    return {"path":str(Path(path).resolve()),"sha256":sha(path)}


def pin(value, expected_path=None):
    require(isinstance(value,dict) and set(value)=={"path","sha256"},"CLOSED_PHYSICAL_REFERENCE_REQUIRED")
    path=Path(value["path"]).resolve()
    if expected_path is not None:
        require(path==Path(expected_path).resolve(),"EXACT_REFERENCE_PATH_REQUIRED")
    require(re.fullmatch("[0-9a-f]{64}",value["sha256"]) is not None and sha(path)==value["sha256"],"PHYSICAL_REFERENCE_CHANGED:"+str(path))
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def append_json(path,value):
    # Exclusive creation preserves earlier failures/markers, even on same bytes.
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as handle:
        json.dump(value,handle,indent=2,sort_keys=True,allow_nan=False)
        handle.write("\n")
    return ref(path)


def owners():
    # Only source imports; reader/runtime invocation follows physical guards.
    return (importlib.import_module("scripts.research.a2.training.selector_full_fixed_policy"),
            importlib.import_module("scripts.research.a2.training.full_selector_workflow"),
            importlib.import_module("scripts.research.a2.data.full_selector_account_inputs"))


def load_authority(run,phase):
    run=Path(run).resolve()
    require(run==RUN.resolve() and phase in PHASES,"EXACT_TASK_AND_PHASE_REQUIRED")
    for name,expected in ORIGINAL_PINS.items():
        require(sha(run/name)==expected,"ORIGINAL_FREEZE_INPUT_OR_GATE_CHANGED:"+name)
    path=run/"continuation/ENGINEERING_CONTINUATION_MANIFEST_R1.json"
    manifest=read(path)
    require(manifest.get("schema")=="FULL_SELECTOR_ENGINEERING_CONTINUATION_R1" and manifest.get("research_id")==ID
        and Path(manifest.get("run","" )).resolve()==run,"CONTINUATION_IDENTITY_CHANGED")
    require(manifest["entry_ref"]==ref(__file__),"ACTUAL_ADDITIVE_ENTRY_SOURCE_CHANGED")
    require(manifest["original_refs"]=={name:ref(run/name) for name in ORIGINAL_PINS},"CONTINUATION_ORIGINAL_BINDINGS_CHANGED")
    pin(manifest["original_start_ref"],run/"PRIMARY_CORE_EXECUTION_STARTED.json")
    pin(manifest["original_failure_ref"],run/"EXECUTION_FAILURE.json")
    start=read(manifest["original_start_ref"]["path"]);failure=read(manifest["original_failure_ref"]["path"])
    require(start.get("research_id")==failure.get("research_id")==ID and start.get("design_ref")==ref(run/"DESIGN_FREEZE.json")
        and failure.get("scientific_retries")==0,"ORIGINAL_FAILURE_OR_START_AUTHORITY_CHANGED")
    design=read(run/"DESIGN_FREEZE.json")
    require(start.get("source_ref")=={"path":str(REPO/"scripts/research/a2/training/full_selector_workflow.py"),
        "sha256":design["sources"][str(REPO/"scripts/research/a2/training/full_selector_workflow.py")]},"ORIGINAL_WORKFLOW_START_CHANGED")
    require(not (run/"EXECUTION_STARTED.json").exists(),"ORIGINAL_FULL_PHASE_ALREADY_ENTERED")
    require((run/"TASK_LEDGER.sqlite").is_file(),"EXISTING_SOLE_LEDGER_REQUIRED")
    review_path=run/"continuation"/(PHASE_NAMES[phase]+"_ACCEPTANCE.json")
    review=read(review_path)
    require(review.get("schema")=="FULL_SELECTOR_ENGINEERING_PHASE_ACCEPTANCE_R1" and review.get("research_id")==ID
        and review.get("phase")==phase and review.get("status")=="PASS"
        and review.get("independent_from_entry_writer") is True
        and review.get("original_worker_terminal") is True
        and review.get("scientific_retry_authorized") is False,"TERMINAL_BOUND_INDEPENDENT_PHASE_REVIEW_REQUIRED")
    require(review["manifest_ref"]==ref(path) and review["entry_ref"]==manifest["entry_ref"]
        and review["original_failure_ref"]==manifest["original_failure_ref"],"PHASE_REVIEW_BINDINGS_CHANGED")
    require(review.get("core_exit_stage") in ("ACCOUNT_SOURCE_PREFLIGHT","EQUAL_SOURCE_GATE")
        and review.get("core_complete_reuse_verified") is True,"SOURCE_ONLY_CORE_EXIT_BOUNDARY_REQUIRED")
    # Reviews assess the exact error, rather than changing the original failure.
    require(any(s in failure.get("error","") for s in ("EXECUTABLE_SOURCE_CHANGED", "ACCOUNT_SOURCE_CUSTODY_CHANGED", "CURRENT_ACCOUNT_SOURCE_OWNER_CHANGED")),
        "ORIGINAL_SOURCE_GATE_FAILURE_REQUIRED")
    correction=manifest.get("engineering_source_configuration_ref")
    if correction is not None:
        pin(correction,run/"ENGINEERING_SOURCE_CORRECTION_R1.json")
        require(review.get("engineering_source_configuration_ref")==correction,"PHASE_SOURCE_CORRECTION_NOT_BOUND")
    else:
        require(review.get("engineering_source_configuration_ref") is None,"UNDECLARED_SOURCE_CORRECTION")
        for source,expected in design["sources"].items():
            require(sha(source)==expected,"EXECUTABLE_SOURCE_CHANGED:"+source)
    marker=run/"continuation"/(PHASE_NAMES[phase]+"_STARTED.json")
    require(not marker.exists(),"PHASE_ALREADY_STARTED_NO_RETRY")
    return manifest,review,ref(review_path),design


def validate_existing_sqlite(run,design):
    path=Path(run)/"TASK_LEDGER.sqlite"
    require(path.is_file(),"EXISTING_SOLE_LEDGER_REQUIRED")
    # A read-only opening cannot create tables, refill an empty authority, or
    # recreate lost scientific history through the original constructor.
    db=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
    try:
        require(db.execute("SELECT design_sha256 FROM authority").fetchall()==[(sha(Path(run)/"DESIGN_FREEZE.json"),)],
            "EXISTING_LEDGER_AUTHORITY_REQUIRED_NO_INITIALIZATION")
        actual=db.execute("SELECT node_id,kind FROM nodes").fetchall()
        expected={n["node_id"]:n["kind"] for n in design["dag"]["nodes"]}
        require(len(actual)==len(expected) and dict(actual)==expected,"EXISTING_FINITE_NODE_SET_CHANGED")
        db.execute("SELECT sequence,node_id,action,payload,utc FROM events LIMIT 1").fetchall()
    finally:db.close()


def source_configuration(controller,run,manifest):
    correction=manifest.get("engineering_source_configuration_ref")
    if correction is None:return nullcontext()
    pin(correction,Path(run)/"ENGINEERING_SOURCE_CORRECTION_R1.json")
    factory=getattr(controller,"engineering_source_configuration",None)
    require(callable(factory),"EXACT_OWNER_SOURCE_CORRECTION_CONTEXT_REQUIRED")
    # This original owner's closed two-replacement context performs all99 source
    # checks. No sha replacement or independent source waiver exists here.
    return factory(correction)


def ledger_snapshot(journal,run,environment_manifest_ref=None,environment_postterminal_ref=None):
    rows=list(journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id"))
    require(rows,"EXISTING_LEDGER_NODES_REQUIRED")
    environment_started={};environment_events=None
    if environment_manifest_ref is not None:
        require(isinstance(environment_manifest_ref,dict) and set(environment_manifest_ref)=={"path","sha256"}
            and environment_manifest_ref==dict(path=str(RISK_ENVIRONMENT_MANIFEST.resolve()),sha256=RISK_ENVIRONMENT_MANIFEST_SHA),
            "ONLY_EXACT_ENVIRONMENT_OBSERVER_REFERENCE_REQUIRED")
        pin(environment_manifest_ref,RISK_ENVIRONMENT_MANIFEST)
        risk_environment_phase_namespace(run) # Actual four proofs/human/old START namespace; no scientific admission.
        environment_manifest=read(RISK_ENVIRONMENT_MANIFEST)
        for group_node,group in environment_manifest["groups"].items():
            actual=[list(r) for r in rows if r[0]==group_node or r[0].startswith(group_node+"|UNIT|")]
            require(actual==group["original_rows"],"ENVIRONMENT_SNAPSHOT_ORIGINAL_FOUR_GROUP_ROWS_CHANGED:"+group_node)
        fourth=environment_manifest["groups"]["RISK_REFRESH|2025-09-02"]["original_rows"]
        environment_started={r[0]:tuple(r) for r in fourth if r[2]=="STARTED"}
        require(len(environment_started)==34 and {r[0]:tuple(r) for r in rows if r[2]=="STARTED"}==environment_started,
            "ONLY_ORIGINAL_FOURTH34_STARTED_ROWS_MAY_BE_OBSERVED")
        environment_events=list(journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
        require(dict(nodes_sha256=digest(rows),events_sha256=digest(environment_events),event_count=len(environment_events))
            =={k:environment_manifest["ledger_prestate"][k] for k in ("nodes_sha256","events_sha256","event_count")},
            "EXACT_WHOLE_ENVIRONMENT_OBSERVER_PRESTATE_REQUIRED")
    postterminal_legacy={}
    if environment_postterminal_ref is not None:
        require(environment_manifest_ref is None,"NO_MIXED_PRESTART_AND_POSTTERMINAL_OBSERVER")
        boundary_path=Path(run)/"maintenance/FIXED214_ENVIRONMENT_RECOVERY_ACTUAL_POSTLOOP_NATURAL_FAILURE_BOUNDARY_R2.json"
        require(isinstance(environment_postterminal_ref,dict) and set(environment_postterminal_ref)=={"path","sha256"}
            and Path(environment_postterminal_ref["path"]).resolve()==boundary_path.resolve()
            and environment_postterminal_ref["sha256"]=="ee7301cc927c2b8b7aabb403e9b23617fe7bc4849c1c058354b6bb5645803078",
            "ONLY_EXACT_POSTLOOP_TERMINAL_METADATA_OBSERVER_REF")
        boundary=read(pin(environment_postterminal_ref,boundary_path))
        require(boundary["schema"]=="FIXED214_ENVIRONMENT_ACTUAL_POSTLOOP_NATURAL_FAILURE_BOUNDARY_R1"
            and boundary["status"]=="ACTUAL_POSTLOOP_METADATA_GUARD_FAILURE_NO_SCIENTIFIC_REPLAY"
            and boundary["current_scientific_COMPLETE_receipt_exists"] is False and boundary["scientific_failed_retries"]==0,
            "ACTUAL_POSTLOOP_FAILURE_NO_NEW_SCIENTIFIC_ADMISSION")
        failure=read(pin(boundary["pins"]["failure"],Path(run)/"continuation/RISK_ENVIRONMENT_REPLAY_CONTINUATION_R4_FAILURE.json"))
        osr=read(pin(boundary["pins"]["os"],Path(run)/"continuation/RISK_ENVIRONMENT_REPLAY_CONTINUATION_R4_OS_EXIT_RECEIPT_R1.json"))
        require(len(osr)==20 and osr["wait_for_exit_observed"] is True and osr["exit_code"]==1
            and osr["terminated_by_agent"] is False and len(osr["before_process_levels"])==2 and osr["after_process_levels"]==[]
            and "after=ledger_snapshot(journal,run)" in failure["error"],"EXACT_POSTLOOP_NATURAL_FAIL_REQUIRED")
        manifest=read(pin(boundary["pins"]["manifest"],RISK_ENVIRONMENT_MANIFEST))
        require(boundary["pins"]["manifest"]["sha256"]==RISK_ENVIRONMENT_MANIFEST_SHA,"ORIGINAL_FOUR_ENVIRONMENT_MANIFEST_REQUIRED")
        original={r[0]:tuple(r) for group in manifest["groups"].values() for r in group["original_rows"]}
        postterminal_legacy={r[0]:tuple(r) for r in boundary["legacy_upper_rows"]}
        require(len(postterminal_legacy)==boundary["legacy_upper_count"]==118
            and all(original.get(node)==row and row[1]=="RISK_LEARNED_UNIT" and row[2:6]==("NOT_REQUIRED",0,None,None)
                and row[6]=="ENVIRONMENT_OS_REBOOT_INTERRUPTION_NO_COMMITTED_OUTPUT_NOT_SCIENTIFIC_NEGATIVE"
                for node,row in postterminal_legacy.items()),"ONLY118_ACTUAL_ORIGINAL_UNENTERED_ENV_UPPER_ROWS")
        actual_by_node={r[0]:r for r in rows}
        require(all(actual_by_node.get(node)==row for node,row in postterminal_legacy.items()),"POSTTERMINAL_LEGACY_ROWS_UNCHANGED")
        environment_events=list(journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
        pre=boundary["ledger_poststate"]
        require(pre["event_count"]==16615 and digest(environment_events[:pre["event_count"]])==pre["events_sha256"]
            and digest(journal.db.execute("SELECT design_sha256 FROM authority").fetchall())==pre["authority_sha256"]
            and not any(event[1] in postterminal_legacy for event in environment_events),"POSTLOOP16615_PREFIX_AUTHORITY_AND_NO_LEGACY_EVENTS")
    for node,kind,status,entered,identity,artifact,error in rows:
        if status=="STARTED" and environment_manifest_ref is not None:
            require(environment_started.get(node)==(node,kind,status,entered,identity,artifact,error),
                "EXACT_OBSERVED_ENVIRONMENT_STARTED_ROW_REQUIRED:"+node)
            continue # Metadata observation only; no status/charge/identity change or entry authority.
        require(status!="STARTED","STARTED_SCIENTIFIC_TAIL_CANNOT_CONTINUE:"+node)
        require(status in TERMINAL|{"NAMED","NOT_REQUIRED"} and entered in (0,1),"INVALID_LEDGER_STATE:"+node)
        if status=="NOT_REQUIRED":
            parent=journal.status(node.split("|UNIT|")[0])
            require(kind=="RISK_LEARNED_UNIT" and "|UNIT|" in node and entered==0 and identity is None and artifact is None
                and parent["status"] in ("COMPLETE","FAILED","SOURCE_NOT_TESTABLE")
                and ((error=="UNENTERED_FROZEN_UPPER_SLOT" or postterminal_legacy.get(node)==(node,kind,status,entered,identity,artifact,error)) if parent["status"]=="COMPLETE" else isinstance(error,str) and bool(error)),
                "ONLY_UNENTERED_ORIGINAL_RISK_UPPER_NOT_REQUIRED_ALLOWED:"+node)
        if status=="NAMED":
            require(entered==0 and identity is None and artifact is None and error is None,"NAMED_NODE_HAS_PRIOR_ENTRY:"+node)
        if status=="COMPLETE":
            require(isinstance(identity,str) and re.fullmatch("[0-9a-f]{64}",identity) is not None,"COMPLETE_IDENTITY_MISSING:"+node)
            physical=json.loads(artifact)
            path=pin(physical)
            root="risk_states" if kind in ("RISK_REFRESH_DISPATCH","RISK_LEARNED_UNIT") else "models"
            require(path.is_relative_to((Path(run)/root).resolve()),"COMPLETE_ARTIFACT_NOT_SOLE_RUN_MODEL:"+node)
    events=environment_events if environment_events is not None else list(journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
    return {"nodes_sha256":digest(rows),"events_sha256":digest(events),"event_count":len(events),"rows":rows}


def public_snapshot(value):
    return {k:value[k] for k in ("nodes_sha256","events_sha256","event_count")}


def core_roles(controller):
    roles=tuple(dict.fromkeys(("RIDGE","HGB","LAMBDAMART",*controller.FUSION_MEMBERS)))
    require(len(roles)==7,"EXACT_SEVEN_CORE_LEARNERS_REQUIRED")
    return roles


def validate_phase_nodes(journal,run,phase,review):
    snapshot=ledger_snapshot(journal,run)
    require(public_snapshot(snapshot)==review["ledger_prestate"],"TERMINAL_BOUND_LEDGER_CHANGED")
    statuses={r[0]:r[2] for r in snapshot["rows"]}
    core=set(review["core_roles"])
    require(len(core)==7,"EXACT_CORE_ROLE_REVIEW_REQUIRED")
    for node in journal.design["dag"]["nodes"]:
        if node.get("role") in core:
            require(statuses[node["node_id"]] in TERMINAL,"CORE_LEARNER_NOT_TERMINAL:"+node["node_id"])
    if phase=="core-account":
        require(review.get("account_metadata_cold_pass") is True,"ACTUAL_ACCOUNT_METADATA_COLD_NOT_ACCEPTED")
        pin(review["account_metadata_cold_ref"])
        for row in snapshot["rows"]:
            if row[1]=="CONTINUOUS_ACCOUNT":
                require(row[2]=="NAMED" and row[3]==0,"ORIGINAL_ACCOUNT_ZERO_ENTRY_BOUNDARY_CHANGED:"+row[0])
        require(not any(r[1].startswith("ACCOUNT|") for r in journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events")),
            "ORIGINAL_ACCOUNT_EVENT_ALREADY_EXISTS")
    return snapshot


def _ast_without_overlay(text):
    module=ast.parse(text);kept=[]
    for node in module.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            if any(isinstance(t,ast.Name) and t.id in ("OWNERS","B_PRODUCER_TRANSPORT") for t in targets):continue
        if isinstance(node,ast.FunctionDef) and node.name in ("custody_reader","identity_links","metadata_preflight"):continue
        kept.append(node)
    module.body=kept
    return ast.dump(module,include_attributes=False)


@contextmanager
def account_overlay(account,manifest):
    cfg=manifest["account_overlay"]
    require(cfg["base_ref"]=={"path":str(ACCOUNT_BASE),"sha256":ACCOUNT_BASE_SHA}
        and cfg["candidate_ref"]=={"path":str(ACCOUNT_CANDIDATE),"sha256":ACCOUNT_CANDIDATE_SHA},"EXACT_REVIEWED_ACCOUNT_OVERLAY_REQUIRED")
    pin(cfg["base_ref"],ACCOUNT_BASE);candidate=pin(cfg["candidate_ref"],ACCOUNT_CANDIDATE)
    require(Path(account.__file__).resolve()==ACCOUNT_BASE.resolve(),"CANONICAL_ACCOUNT_OWNER_REQUIRED")
    base=ACCOUNT_BASE.read_text(encoding="utf-8-sig");code=candidate.read_text(encoding="utf-8-sig")
    require(_ast_without_overlay(base)==_ast_without_overlay(code),"ACCOUNT_OVERLAY_BUSINESS_AST_CHANGED")
    private=ModuleType("_full_selector_account_custody_overlay_r1")
    private.__file__=str(ACCOUNT_BASE) # existing REPO calculation only
    exec(compile(code,str(candidate),"exec"),private.__dict__)
    require(Path(private.REPO).resolve()==REPO.resolve() and all(getattr(private,name).__code__.co_filename==str(candidate) for name in ("custody_reader","identity_links","metadata_preflight")),"ACTUAL_OVERLAY_CODE_ORIGIN_REQUIRED")
    require(private.source is account.source,"UNCHANGED_ACTUAL_CASH_ADAPTER_REQUIRED")
    require(cfg["current_owner_refs"]=={r:private.OWNERS[r] for r in ("cash_adapter","cash_owner")}
        and cfg["old_custody_refs"]==list(private.B_PRODUCER_TRANSPORT),"EXACT_CURRENT_OWNER_AND_OLD_CUSTODY_BINDINGS_REQUIRED")
    for value in cfg["current_owner_refs"].values():pin(value)
    for value in cfg["old_custody_refs"]:pin(value["custody_ref"])
    require(Path(account.source.__file__).resolve()==Path(cfg["current_owner_refs"]["cash_adapter"]["path"]).resolve()
        and Path(account.source.cash.__file__).resolve()==Path(cfg["current_owner_refs"]["cash_owner"]["path"]).resolve(),"ACTUAL_OWNER_CODE_ORIGIN_CHANGED")
    ordinary=pin(cfg["ordinary_sources_ref"])
    require(cfg["ordinary_sources_ref"]==account.DEFAULT_REFS["ordinary_sources"]
        and "report_same_file_cash_table_scope" not in read(ordinary),"V17_REPORT_SCOPE_MUST_REMAIN_ABSENT")
    sentinel=object();saved={name:getattr(account,name,sentinel) for name in OVERLAY_GLOBALS}
    original_loader=account.load_account_inputs
    try:
        for name in OVERLAY_GLOBALS:setattr(account,name,getattr(private,name))
        require(account.load_account_inputs is original_loader,"ORIGINAL_ACCOUNT_LOADER_CHANGED")
        yield {"base_ref":cfg["base_ref"],"candidate_ref":cfg["candidate_ref"],
               "helper_code_filenames":{name:getattr(private,name).__code__.co_filename for name in ("custody_reader","identity_links","metadata_preflight")},"current_owner_refs":cfg["current_owner_refs"],
               "old_custody_refs":cfg["old_custody_refs"],"old_sources_executed":False,"report_scope_enabled":False}
    finally:
        for name,value in saved.items():
            if value is sentinel:delattr(account,name)
            else:setattr(account,name,value)
        require(account.load_account_inputs is original_loader,"ORIGINAL_ACCOUNT_LOADER_CHANGED_DURING_CONTINUATION")


FRAME_RECEIPT_FIELDS={"path","sha256","identity_sha256","frame_sha256","rows","dates","keys_sha256","identity"}


def frame_receipt(value,receipt_ref=None):
    # Original _store_frame receipt, not a permissive arbitrary-extra reference.
    require(isinstance(value,dict) and set(value)==FRAME_RECEIPT_FIELDS,"EXACT_ORIGINAL_FRAME_RECEIPT_REQUIRED")
    path=pin({k:value[k] for k in ("path","sha256")})
    sidecar=Path(str(path)+".json")
    if receipt_ref is not None:pin(receipt_ref,sidecar)
    require(sidecar.is_file() and read(sidecar)==value,"EXACT_FRAME_RECEIPT_SIDECAR_REQUIRED")
    return path


def core_policy_terminal(controller,workflow,run,review,design):
    run=Path(run);path=run/"CORE_BASE_POLICY_TERMINAL.json"
    if path.exists():
        pin(review["core_policy_terminal_ref"],path);terminal=read(path)
    else:
        require(review.get("core_exit_stage")=="EQUAL_SOURCE_GATE" and review.get("core_policy_terminal_ref") is None,
            "CORE_POLICY_TERMINAL_MISSING_NOT_SOURCE_EXIT")
        complete=review.get("equal_complete_policy_ref")
        if complete is not None:
            require(Path(complete["path"]).resolve()==(run/"predictions/policy_FUSION_equal.parquet").resolve(),"EXACT_EQUAL_PUBLICATION_PATH_REQUIRED")
            require(review.get("equal_complete_receipt_ref") is not None,"EQUAL_COMPLETE_SIDECAR_REVIEW_REQUIRED")
            frame_receipt(complete,review["equal_complete_receipt_ref"])
            require(review.get("equal_unattempted") is False and not (run/"predictions/failure_FUSION_equal.json").exists(),
                "EQUAL_EXACT_REUSE_OR_FAILURE_CONFLICT")
            # Assembly uses the original frame receipt and domain guards; no
            # trainer, calibration, fitting or fixed transform is called again.
        else:
            require(review.get("equal_unattempted") is True,"EQUAL_FIRST_TRANSFORM_NOT_REVIEWED")
            forbidden=[run/"predictions/policy_FUSION_equal.parquet",run/"predictions/failure_FUSION_equal.json"]
            forbidden += [run/"predictions"/folder/name for year in (2024,2025) for folder,name in
                (("annual_native",f"FUSION_equal_{year}.parquet"),("",f"fusion_receipt_equal_{year}.json"))]
            require(not any(p.exists() or Path(str(p)+".json").exists() for p in forbidden),"EQUAL_ALREADY_ATTEMPTED_OR_HAS_ARTIFACT")
            # Equal has ZERO learned nodes. First fixed transform only.
            controller.train_fusion(run,("equal",))
        assembly=controller.assemble_selection(run)
        if complete is not None:
            require(assembly["score_paths"].get("FUSION_equal")==complete,"EQUAL_COMPLETE_PUBLICATION_MISSING_FROM_OWNER_ASSEMBLY")
        terminal={"research_id":ID,"status":"CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT","design_sha256":sha(run/"DESIGN_FREEZE.json"),
            "policy_refs":{k:v for k,v in assembly["score_paths"].items() if k in controller.CORE},"outer_result_feedback":False}
        workflow._immutable_account_json(path,terminal)
    require(terminal.get("status")=="CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT" and terminal.get("design_sha256")==sha(run/"DESIGN_FREEZE.json")
        and terminal.get("outer_result_feedback") is False and set(terminal["policy_refs"])<=set(controller.CORE)-{r for r in controller.CORE if r.startswith("RISK_")},
        "EXACT_NON_RISK_CORE_POLICY_TERMINAL_REQUIRED")
    for value in terminal["policy_refs"].values():frame_receipt(value)
    # Owner validates footer/body/keys and original full-U policy domain. No
    # frame decoder, membership rule, or domain validator is duplicated here.
    checked=controller.assemble_selection(run)
    require(all(checked["score_paths"].get(role)==value for role,value in terminal["policy_refs"].items()),
        "CORE_FRAME_NOT_IN_ORIGINAL_QUALIFIED_ASSEMBLY")
    return terminal


def remaining_dispatch(controller,journal,run,review):
    roles=tuple(r for r in controller.learners.PARADIGMS if r not in core_roles(controller))
    methods=tuple(m for m in controller.FUSIONS if m!="equal")
    require(len(roles)==16 and len(methods)==11 and list(roles)==review["fixed_remaining_roles"]
        and list(methods)==review["fixed_remaining_fusions"],"EXACT_16_PRIMARY_11_FUSION_REQUIRED")
    # This is the first remaining-alpha phase. The physical complete policies
    # and typed failures are terminal dispositions, never grounds for a replay.
    active_roles=[];active_methods=[]
    for identifier,kind in [(r,"primary") for r in roles]+[(m,"fusion") for m in methods]:
        cid=identifier if kind=="primary" else "FUSION_"+identifier
        policy=Path(run)/"predictions"/("policy_"+cid+".parquet")
        failure=Path(run)/"predictions"/("failure_"+cid+".json")
        refs=review.get("preserved_alpha_refs",{})
        if policy.exists():
            require(cid in refs and refs[cid].get("disposition")=="COMPLETE", "COMPLETE_ALPHA_REUSE_NOT_REVIEWED:"+cid)
            require(Path(refs[cid]["ref"]["path"]).resolve()==policy.resolve(),"EXACT_COMPLETED_ALPHA_POLICY_PATH_REQUIRED")
            frame_receipt(refs[cid]["ref"],refs[cid]["receipt_ref"])
            continue
        if failure.exists():
            require(cid in refs and refs[cid].get("disposition")=="FAILED", "FAILED_ALPHA_DISPOSITION_NOT_REVIEWED:"+cid)
            pin(refs[cid]["ref"],failure)
            continue
        relevant=[n for n in journal.design["dag"]["nodes"] if n.get("role")==identifier
            or n.get("method")==identifier or (kind=="primary" and n["node_id"].startswith("PLATT|"+identifier+"|"))]
        require(all(journal.status(n["node_id"])["status"]=="NAMED" and journal.status(n["node_id"])["entered"]==0 for n in relevant),
            "PARTIAL_ALPHA_WITHOUT_TERMINAL_PUBLICATION_NO_REPLAY:"+cid)
        # Median has no learned nodes; its saved prefixes still prohibit replay.
        prefixes=[Path(run)/"predictions/annual_native"/(cid+"_"+str(y)+".parquet") for y in (2024,2025)]
        if kind=="fusion":prefixes += [Path(run)/"predictions"/("fusion_receipt_"+identifier+"_"+str(y)+".json") for y in (2024,2025)]
        require(not any(p.exists() or Path(str(p)+".json").exists() for p in prefixes),"ALPHA_PREFIX_WITHOUT_TERMINAL_NO_REPLAY:"+cid)
        (active_roles if kind=="primary" else active_methods).append(identifier)
    return roles,methods,tuple(active_roles),tuple(active_methods)


def require_remaining_terminal(journal,roles,methods):
    for node in journal.design["dag"]["nodes"]:
        if node.get("role") in roles or node.get("method") in methods or any(node["node_id"].startswith("PLATT|"+r+"|") for r in roles):
            require(journal.status(node["node_id"])["status"] in TERMINAL,"REMAINING_ALPHA_NODE_NOT_TERMINAL:"+node["node_id"])


def execute(run,phase):
    if phase==POLICY_CATALOG_PHASE:return execute_policy_catalog(run)
    if phase==POLICY_CHECKPOINT_PHASE:return execute_policy_checkpoint(run)
    if phase==POLICY_ZERO_PHASE:return execute_policy_zero_entry(run)
    if phase in TAIL_PHASES or phase==POLICY_REBOOT_PHASE:return execute_tail(run,phase)
    """No real entry without the later terminal-bound independent receipts."""
    if phase==RISK_PENDING_PHASE:return execute_risk(run,RISK_PENDING_NAME)
    if phase==RISK_PHASE:return execute_risk(run)
    if phase==SOURCE_RECOVERY_PHASE:return execute_source_recovery(run)
    run=Path(run).resolve();require(run==RUN.resolve() and phase in PHASES,"EXACT_TASK_AND_PHASE_REQUIRED")
    controller,workflow,account=owners()
    with workflow._worker_lock(run):
        manifest,review,review_ref,design=load_authority(run,phase)
        require(tuple(review["core_roles"])==core_roles(controller),"EXACT_FIXED_CORE_ROSTER_REQUIRED")
        with source_configuration(controller,run,manifest):
            validate_existing_sqlite(run,design)
            journal=controller._TaskLedger(run)
            try:
                before=validate_phase_nodes(journal,run,phase,review)
                controller.worker_runtime(run) # owner's per-process cache + actualruntime exact check
                overlay=account_overlay(account,manifest) if phase=="core-account" else nullcontext(None)
                with overlay as provenance:
                    if phase=="core-account":account.metadata_preflight(run) # physical/footer/UID guards before price/entry
                    else:remaining_dispatch(controller,journal,run,review)
                    name=PHASE_NAMES[phase];folder=run/"continuation"
                    marker=append_json(folder/(name+"_STARTED.json"),{"research_id":ID,"phase":phase,"review_ref":review_ref,
                        "manifest_ref":ref(folder/"ENGINEERING_CONTINUATION_MANIFEST_R1.json"),"entry_ref":ref(__file__),
                        "ledger_prestate":public_snapshot(before),"scientific_retries":0})
                    try:
                        if phase=="core-account":
                            terminal=core_policy_terminal(controller,workflow,run,review,design)
                            workflow.run_accounts(run,policy_terminal=terminal)
                            for role in terminal["policy_refs"]:
                                require(journal.status("ACCOUNT|"+role)["status"] in TERMINAL,"APPLICABLE_CORE_ACCOUNT_NOT_TERMINAL")
                            account_receipt=ref(run/"CORE_BASE_ACCOUNT_TERMINAL.json")
                            # Original-compatible completion; original start/failure unchanged.
                            completion={"research_id":ID,"status":"CORE_NON_RISK_STAGE_COMPLETE","design_ref":ref(run/"DESIGN_FREEZE.json"),
                                "all_task_complete":False,"risk_estimates_started":False,"engineering_continuation_ref":marker,
                                "account_terminal_ref":account_receipt,"account_source_overlay":provenance}
                            require(not (run/"PRIMARY_CORE_EXECUTION_COMPLETE.json").exists(),"PRESERVE_ORIGINAL_CORE_COMPLETION")
                            workflow._immutable_account_json(run/"PRIMARY_CORE_EXECUTION_COMPLETE.json",completion)
                        else:
                            roles,methods,active_roles,active_methods=remaining_dispatch(controller,journal,run,review)
                            if active_roles:controller.train_primary(run,active_roles)
                            if active_methods:controller.train_fusion(run,active_methods)
                            require_remaining_terminal(journal,roles,methods)
                            controller.assemble_selection(run)
                            completion={"research_id":ID,"status":"INDEPENDENT_ALPHA_STAGE_TERMINAL","fixed_roles":list(roles),
                                "fixed_fusions":list(methods),"risk_pending":True,"all_scientific_nodes_terminal":False,
                                "all_task_complete":False,"scientific_retries":0}
                        after=ledger_snapshot(journal,run)
                        append_json(folder/(name+"_COMPLETE.json"),{"research_id":ID,"phase":phase,"marker_ref":marker,
                            "completion":completion,"ledger_poststate":public_snapshot(after),"risk_dispatch_entered":False,"outer_feedback":False})
                        return completion
                    except BaseException:
                        append_json(folder/(name+"_FAILURE.json"),{"research_id":ID,"phase":phase,"marker_ref":marker,
                            "error":traceback.format_exc(),"scientific_retries":0,"original_failure_unchanged":True})
                        raise
            finally:journal.db.close()


SOURCE_RECOVERY_SHARED_SCALER_CUTS = ("2023-04-01","2023-07-01","2024-01-01","2024-07-01","2025-01-01")
SOURCE_RECOVERY_PHASE = "remaining-alpha-source-recovery"
SOURCE_RECOVERY_NAME = "REMAINING_ALPHA_SOURCE_RECOVERY_R1"
SOURCE_RECOVERY_CONFIG = "REMAINING_ALPHA_SOURCE_RECOVERY_CONFIGURATION_R1.json"
PRIOR_R3_SHA = "1a937d8935c192a23791d5b7fe02a92d703939d91fea4b6eaab9d3bd91ac49b4"
PRIOR_R3_CUSTODY = RUN/"source_corrections/ENGINEERING_SOURCE_CORRECTION_R2"/("full_selector_engineering_continuation.py."+PRIOR_R3_SHA+".before")
PRIOR_MANIFEST_SHA = "66217f50d66236d35b8009c0dc7837ce6d99d2ff5c7beda120ce7cfc3466ba40"
PRIOR_SOURCE_SHA = "29b37530c058f178855ec55494e92ed752aeb57b3b327fabd145fb8abaccb6b5"
PRIOR_REMAINING_ACCEPTANCE_SHA = "cc464d74a4b244888100067b524e2fe315cc7ce4a7974e182cbcad7f20c4a8eb"
PRIOR_PREFLIGHT_FAILURE_SHA = "37fe61c6d863673bb458d63f2b3eadb94e24e31563e4a0ee3d90414aa9002a88"
PRIOR_METADATA_REVIEW = CACHE/"proposals/REMAINING_ALPHA_POST_CORE_FAILURE_INDEPENDENT_METADATA_REVIEW_R1.json"
PRIOR_METADATA_REVIEW_SHA = "9420e29977b373fdcd72d980f26a01ac799737b9764eb1be483214734b736834"
SOURCE_RECOVERY_PRESTATE = {"nodes_sha256":"063b86fc5893b226a2270eb6a11f19e445b16adf8a4bb754fb8e34690282f654",
    "events_sha256":"1977b4a8dd6472a008714de5504d38ab99282a1aa73323af1a1a04e9ab2f5961","event_count":432}
PRESERVED_CORE_REFS = {
    "old_core_started_ref":("continuation/CORE_ACCOUNT_CONTINUATION_R1_STARTED.json","44757250835788a1b3b62a46d0265e7ead723f950a618fe62670d2d79210280c"),
    "old_core_failure_ref":("continuation/CORE_ACCOUNT_CONTINUATION_R1_FAILURE.json","4b82752e4736b7d43387ecde610aae67e87178ff10eeb189a2fd311d5a9f6d69"),
    "core_policy_terminal_ref":("CORE_BASE_POLICY_TERMINAL.json","fdd4350e8440850fe904785f4d73d74bf450c0e03b985f53cbca95f05947771d"),
    "equal_policy_ref":("predictions/policy_FUSION_equal.parquet","a0504bc593f5b43b1ba8e954d69bccc95a1cf901a66272489a8c25c1e575f282"),
    "equal_receipt_ref":("predictions/policy_FUSION_equal.parquet.json","d61f043c115f22f75553e89f2477e7deeeb7fd5de0dfb9f1933b4482c0468b88"),
}


def load_source_recovery_configuration(run):
    """Source/config-only gate, callable before final phase acceptance/cold.

    It does not instantiate TaskLedger, initialize runtime, read numerical
    inputs or consume phase acceptance. The later actual entry adds those gates.
    """
    run=Path(run).resolve();require(run==RUN.resolve(),"EXACT_SOURCE_RECOVERY_TASK_REQUIRED")
    for name,expected in ORIGINAL_PINS.items():
        require(sha(run/name)==expected,"ORIGINAL_FREEZE_INPUT_OR_GATE_CHANGED:"+name)
    folder=run/"continuation";path=folder/SOURCE_RECOVERY_CONFIG;cfg=read(path)
    required={"schema","research_id","run","phase","runtime_entry_ref","original_refs","base_manifest_ref",
        "previous_entry_custody_ref","prior_source_configuration_ref","engineering_source_configuration_ref",
        "prior_remaining_acceptance_ref","prior_metadata_review_ref","preflight_failure_ref","ledger_prestate",*PRESERVED_CORE_REFS}
    require(set(cfg)==required and cfg.get("schema")=="FULL_SELECTOR_REMAINING_ALPHA_SOURCE_RECOVERY_CONFIGURATION_R1"
        and cfg.get("research_id")==ID and cfg.get("phase")==SOURCE_RECOVERY_PHASE
        and Path(cfg.get("run","")).resolve()==run and cfg["runtime_entry_ref"]==ref(__file__),"EXACT_SOURCE_RECOVERY_CONFIGURATION_REQUIRED")
    require(cfg["original_refs"]=={n:ref(run/n) for n in ORIGINAL_PINS},"ORIGINAL_SOURCE_RECOVERY_BINDINGS_CHANGED")
    pin(cfg["base_manifest_ref"],folder/"ENGINEERING_CONTINUATION_MANIFEST_R1.json")
    require(cfg["base_manifest_ref"]["sha256"]==PRIOR_MANIFEST_SHA,"IMMUTABLE_SINGLE_BASE_MANIFEST_REQUIRED")
    pin(cfg["previous_entry_custody_ref"],PRIOR_R3_CUSTODY)
    require(cfg["previous_entry_custody_ref"]["sha256"]==PRIOR_R3_SHA,"IMMUTABLE_PRIOR_R3_ENTRY_CUSTODY_REQUIRED")
    old=read(cfg["base_manifest_ref"]["path"])
    pin(old["original_start_ref"],run/"PRIMARY_CORE_EXECUTION_STARTED.json")
    pin(old["original_failure_ref"],run/"EXECUTION_FAILURE.json")
    require(old["entry_ref"]["sha256"]==PRIOR_R3_SHA and old["original_refs"]==cfg["original_refs"],"PRIOR_R3_HISTORY_CHANGED")
    pin(cfg["prior_source_configuration_ref"],run/"ENGINEERING_SOURCE_CORRECTION_R1.json")
    require(cfg["prior_source_configuration_ref"]["sha256"]==PRIOR_SOURCE_SHA
        and old["engineering_source_configuration_ref"]==cfg["prior_source_configuration_ref"],"IMMUTABLE_PRIOR_SOURCE_R1_REQUIRED")
    pin(cfg["engineering_source_configuration_ref"],run/"ENGINEERING_SOURCE_CORRECTION_R2.json")
    correction=read(cfg["engineering_source_configuration_ref"]["path"])
    require(correction.get("schema")=="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2" and correction.get("status")=="PASS"
        and correction.get("research_id")==ID and correction["prior_source_configuration_ref"]==cfg["prior_source_configuration_ref"],"FIXED_FOUR_SOURCE_R2_CONFIGURATION_REQUIRED")
    pin(cfg["prior_remaining_acceptance_ref"],folder/"REMAINING_ALPHA_CONTINUATION_R1_ACCEPTANCE.json")
    require(cfg["prior_remaining_acceptance_ref"]["sha256"]==PRIOR_REMAINING_ACCEPTANCE_SHA,"IMMUTABLE_PRIOR_REMAINING_ACCEPTANCE_REQUIRED")
    prior_review=read(cfg["prior_remaining_acceptance_ref"]["path"])
    require(prior_review.get("schema")=="FULL_SELECTOR_ENGINEERING_PHASE_ACCEPTANCE_R1" and prior_review.get("status")=="PASS"
        and prior_review.get("phase")=="remaining-alpha" and prior_review.get("independent_from_entry_writer") is True
        and prior_review.get("scientific_retry_authorized") is False and prior_review["entry_ref"]==old["entry_ref"]
        and prior_review["manifest_ref"]==cfg["base_manifest_ref"] and prior_review["engineering_source_configuration_ref"]==cfg["prior_source_configuration_ref"],
        "PRIOR_ACCEPTED_REMAINING_METADATA_CHANGED")
    pin(cfg["prior_metadata_review_ref"],PRIOR_METADATA_REVIEW)
    require(cfg["prior_metadata_review_ref"]["sha256"]==PRIOR_METADATA_REVIEW_SHA,"FIXED_POST_CORE_FAILURE_METADATA_REVIEW_REQUIRED")
    pin(cfg["preflight_failure_ref"],folder/"REMAINING_ALPHA_CONTINUATION_R1_ROOT_PREFLIGHT_FAILURE.json")
    require(cfg["preflight_failure_ref"]["sha256"]==PRIOR_PREFLIGHT_FAILURE_SHA,"EXACT_ZERO_LAUNCH_SOURCE_PREFLIGHT_FAILURE_REQUIRED")
    failure=read(cfg["preflight_failure_ref"]["path"])
    require(failure.get("schema")=="FULL_SELECTOR_REMAINING_ALPHA_SOURCE_PREFLIGHT_FAILURE_R1" and failure.get("research_id")==ID
        and failure.get("actual_worker_launched_by_attempt") is False and failure.get("remaining_marker_absent") is True
        and not failure.get("new_training_entry") and not failure.get("new_account_entry") and not failure.get("new_bootstrap_entry"),
        "ORIGINAL_PREFLIGHT_MUST_HAVE_ZERO_SCIENTIFIC_ENTRY")
    require(cfg["ledger_prestate"]==SOURCE_RECOVERY_PRESTATE==prior_review["ledger_prestate"],"FIXED_SOURCE_RECOVERY_ZERO_ENTRY_PRESTATE_REQUIRED")
    for key,(relative,expected) in PRESERVED_CORE_REFS.items():
        pin(cfg[key],run/relative);require(cfg[key]["sha256"]==expected,"PRESERVED_CORE_OR_EQUAL_PUBLICATION_CHANGED:"+key)
    require(not (folder/"CORE_ACCOUNT_CONTINUATION_R1_COMPLETE.json").exists(),"FAILED_CORE_R1_CANNOT_BECOME_COMPLETE")
    require(not (folder/"REMAINING_ALPHA_CONTINUATION_R1_STARTED.json").exists()
        and not (run/"EXECUTION_STARTED.json").exists(),"ORIGINAL_REMAINING_OR_FULL_PHASE_ALREADY_STARTED")
    require(not any((folder/(SOURCE_RECOVERY_NAME+"_"+suffix+".json")).exists() for suffix in ("STARTED","COMPLETE","FAILURE")),
        "SOURCE_RECOVERY_ALREADY_ATTEMPTED_NO_RETRY")
    return cfg,read(run/"DESIGN_FREEZE.json"),prior_review


def load_source_recovery_acceptance(run,cfg):
    path=Path(run)/"continuation"/(SOURCE_RECOVERY_NAME+"_ACCEPTANCE.json");review=read(path)
    require(review.get("schema")=="FULL_SELECTOR_REMAINING_ALPHA_SOURCE_RECOVERY_PHASE_ACCEPTANCE_R1" and review.get("status")=="PASS"
        and review.get("research_id")==ID and review.get("phase")==SOURCE_RECOVERY_PHASE
        and review.get("independent_from_entry_writer") is True and review.get("all_prior_workers_terminal") is True
        and review.get("scientific_retry_authorized") is False and review.get("first_remaining_dispatch_only") is True,
        "INDEPENDENT_SOURCE_RECOVERY_PHASE_ACCEPTANCE_REQUIRED")
    require(review["phase_configuration_ref"]==ref(Path(run)/"continuation"/SOURCE_RECOVERY_CONFIG)
        and review["runtime_entry_ref"]==cfg["runtime_entry_ref"]
        and review["engineering_source_configuration_ref"]==cfg["engineering_source_configuration_ref"]
        and review["ledger_prestate"]==cfg["ledger_prestate"],"SOURCE_RECOVERY_ACCEPTANCE_BINDINGS_CHANGED")
    pin(review["actual_source_runtime_cold_ref"]);cold=read(review["actual_source_runtime_cold_ref"]["path"])
    require(cold.get("schema")=="FULL_SELECTOR_REMAINING_ALPHA_SOURCE_RECOVERY_COLD_R1" and cold.get("status")=="PASS"
        and cold.get("research_id")==ID and cold.get("actual_cold") is True and cold.get("synthetic") is False
        and cold["phase_configuration_ref"]==review["phase_configuration_ref"] and cold["runtime_entry_ref"]==cfg["runtime_entry_ref"]
        and cold["engineering_source_configuration_ref"]==cfg["engineering_source_configuration_ref"]
        and cold.get("source_and_sql_unchanged") is True and cold.get("scientific_entry_calls")==0,
        "ACTUAL_SOURCE_RUNTIME_COLD_REQUIRED_NOT_SYNTHETIC")
    return review,ref(path)


def source_recovery_prestate(journal,run,prior_review):
    before=validate_phase_nodes(journal,run,"remaining-alpha",prior_review)
    for row in before["rows"]:
        if row[1] in ("CONTINUOUS_ACCOUNT","RISK_REFRESH_DISPATCH","RISK_LEARNED_UNIT","MEMBER_SOLVE","WHOLE_SET_GATE","SHARED_BOOTSTRAP","HYBRID_ESTIMATOR","HYBRID_SCALER"):
            require(row[2]=="NAMED" and row[3]==0 and row[4] is None and row[5] is None,"INDEPENDENT_ALPHA_REQUIRES_OTHER_BRANCH_ZERO_ENTRY")
    require(not journal.db.execute("SELECT node_id FROM events WHERE node_id LIKE 'ACCOUNT|%' OR node_id LIKE 'RISK_REFRESH|%' OR node_id LIKE 'MEMBERS|%' OR node_id LIKE 'GATE|%' OR node_id LIKE 'HYBRID|%' OR node_id LIKE 'STATISTICS|%' LIMIT 1").fetchall(),
        "OTHER_BRANCH_HISTORY_EXISTS_NO_DISGUISED_ZERO_ENTRY")
    return before


def execute_source_recovery(run):
    run=Path(run).resolve();require(run==RUN.resolve(),"EXACT_SOURCE_RECOVERY_TASK_REQUIRED")
    controller,workflow,_=owners()
    with workflow._worker_lock(run):
        cfg,design,prior_review=load_source_recovery_configuration(run)
        review,review_ref=load_source_recovery_acceptance(run,cfg)
        require(tuple(prior_review["core_roles"])==core_roles(controller),"EXACT_FIXED_CORE_ROSTER_REQUIRED")
        # Explicit R2 owner context before any constructor or fitted-state decode.
        with controller.engineering_source_configuration(cfg["engineering_source_configuration_ref"]):
            validate_existing_sqlite(run,design);journal=controller._TaskLedger(run)
            try:
                before=source_recovery_prestate(journal,run,prior_review)
                shared_scalers={"SCALER|"+cut for cut in SOURCE_RECOVERY_SHARED_SCALER_CUTS}
                require([n for n in design["dag"]["nodes"] if n["kind"]=="SCALER" and not n.get("role")]==
                    [dict(node_id="SCALER|"+cut,kind="SCALER",cutoff=cut) for cut in SOURCE_RECOVERY_SHARED_SCALER_CUTS],
                    "EXACT_ORIGINAL_FIVE_SHARED_SCALERS_REQUIRED")
                shared_before={row[0]:row for row in before["rows"] if row[0] in shared_scalers}
                require(all(row[2] in ("COMPLETE","NAMED") for row in shared_before.values()),
                    "SHARED_SCALER_FAILED_OR_ENTERED_NO_RETRY")
                authority_before=journal.db.execute("SELECT design_sha256 FROM authority").fetchall()
                events_before=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                roles,methods,active_roles,active_methods=remaining_dispatch(controller,journal,run,prior_review)
                require(active_roles==roles and active_methods==methods,"ONLY_FIRST_FIXED16_AND11_DISPATCH_ALLOWED")
                controller.worker_runtime(run)
                folder=run/"continuation"
                marker=append_json(folder/(SOURCE_RECOVERY_NAME+"_STARTED.json"),dict(research_id=ID,phase=SOURCE_RECOVERY_PHASE,
                    phase_configuration_ref=ref(folder/SOURCE_RECOVERY_CONFIG),review_ref=review_ref,runtime_entry_ref=ref(__file__),
                    base_manifest_ref=cfg["base_manifest_ref"],previous_entry_custody_ref=cfg["previous_entry_custody_ref"],
                    engineering_source_configuration_ref=cfg["engineering_source_configuration_ref"],ledger_prestate=public_snapshot(before),scientific_retries=0))
                try:
                    controller.train_primary(run,active_roles)
                    controller.train_fusion(run,active_methods)
                    require_remaining_terminal(journal,roles,methods)
                    controller.assemble_selection(run)
                    after=ledger_snapshot(journal,run)
                    allowed=shared_scalers|{n["node_id"] for n in design["dag"]["nodes"] if n.get("role") in roles or n.get("method") in methods
                        or any(n["node_id"].startswith("PLATT|"+r+"|") for r in roles)}
                    shared_after={row[0]:row for row in after["rows"] if row[0] in shared_scalers}
                    require(all(shared_after[name]==row for name,row in shared_before.items() if row[2]=="COMPLETE"),
                        "COMPLETE_SHARED_SCALER_EXACT_REUSE_CHANGED")
                    require(all(row[2] in TERMINAL for row in shared_after.values()),"REQUIRED_SHARED_SCALER_NOT_TERMINAL")
                    require({r[0]:r for r in before["rows"] if r[0] not in allowed}=={r[0]:r for r in after["rows"] if r[0] not in allowed},
                        "NON_REMAINING_ALPHA_SCIENTIFIC_STATE_CHANGED")
                    events_after=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                    event_allowed=(allowed-shared_scalers)|{name for name,row in shared_before.items() if row[2]=="NAMED"}
                    require(events_after[:len(events_before)]==events_before and all(event[1] in event_allowed for event in events_after[len(events_before):]),
                        "NON_REMAINING_ALPHA_EVENT_OR_ORIGINAL_HISTORY_CHANGED")
                    require(journal.db.execute("SELECT design_sha256 FROM authority").fetchall()==authority_before,
                        "ORIGINAL_SOLE_LEDGER_AUTHORITY_CHANGED")
                    validate_existing_sqlite(run,design)
                    completion=dict(research_id=ID,phase=SOURCE_RECOVERY_PHASE,status="INDEPENDENT_ALPHA_STAGE_TERMINAL",
                        marker_ref=marker,phase_configuration_ref=ref(folder/SOURCE_RECOVERY_CONFIG),fixed_roles=list(roles),fixed_fusions=list(methods),
                        ledger_poststate=public_snapshot(after),old_core_failure_preserved_ref=cfg["old_core_failure_ref"],
                        existing_equal_exact_reuse=True,risk_dispatch_entered=False,account_entry=False,outer_feedback=False,scientific_retries=0)
                    # Verify fixed old provenance again; never rewrite its receipts.
                    for key,(relative,expected) in PRESERVED_CORE_REFS.items():pin(dict(path=str(run/relative),sha256=expected))
                    pin(cfg["base_manifest_ref"]);pin(cfg["prior_source_configuration_ref"]);pin(cfg["prior_remaining_acceptance_ref"])
                    append_json(folder/(SOURCE_RECOVERY_NAME+"_COMPLETE.json"),completion)
                    return completion
                except BaseException:
                    append_json(folder/(SOURCE_RECOVERY_NAME+"_FAILURE.json"),dict(research_id=ID,phase=SOURCE_RECOVERY_PHASE,
                        marker_ref=marker,error=traceback.format_exc(),scientific_retries=0,old_history_preserved=True))
                    raise
            finally:journal.db.close()


# One bounded later-context batch. Earlier source-pending dates retain NAMED0;
# no second risk kernel, numeric loader, reservation or retry logic is added.
RISK_PHASE = "risk-qualified-contexts"
RISK_PENDING_PHASE="risk-pending-first-entry"
RISK_PENDING_NAME="RISK_PENDING_METADATA_SUPPLEMENT_FIRST_ENTRY_R1"
RISK_NAME = "RISK_QUALIFIED_CONTEXT_CONTINUATION_R1"
R3_ENTRY_SHA = "1a937d8935c192a23791d5b7fe02a92d703939d91fea4b6eaab9d3bd91ac49b4"
RISK_C6_SHA = "c6a8f9ac13ba1570661c7496b661007d211d17b01a70dcebca37126df6a6dcc0"
RISK_C6_CUSTODY = RUN/"source_corrections/RISK_QUALIFIED_CONTEXT_CONTINUATION_R1"/("full_selector_engineering_continuation.py."+RISK_C6_SHA+".before")
RISK_SOURCE_R2_SHA = "8009d9bdc0f9e23760ea877bdee0f1e72f1af8affdb454e8c10e0f4824bb303f"
R3_MANIFEST_SHA = "66217f50d66236d35b8009c0dc7837ce6d99d2ff5c7beda120ce7cfc3466ba40"
RISK_CONTEXT_COUNT = 214
RISK_FAMILY_COUNT = 18
RISK_UPPER = 71
RISK_AUDIT = CACHE/"proposals/posterior_context_source_audit_R1/POSTERIOR_CONTEXT_NATIVE_SOURCE_METADATA_AUDIT_R1.json"
RISK_AUDIT_SHA = "ec23c21651941cc0fb0f5713a355c06a1aa59d4c6c8c085c8cb4d1d32e3f0668"
RISK_SHORTLIST = RISK_AUDIT.with_name("ORIGINAL_CONTEXT_METADATA_CANDIDATE_SHORTLIST_R1.json")
RISK_SHORTLIST_SHA = "09b90f0ecfc3060c24c2934b16e0ae061659f41e5b357c098c73685cd0e5ccdd"
RISK_INPUT_OWNER = REPO/"scripts/research/a2/data/full_selector_inputs.py"
RISK_INPUT_OWNER_SHA = "9e09b650df74474d8235aa8a39dc8fbffa6e82311f6018e94feedf39db175be9"
RISK_HELPER = CACHE/"proposals/metadata_helper_vectorized_R1/metadata_helper_candidate_R3.py"
RISK_HELPER_SHA = "c93ddc5f2e8a9e7ebd9655cc24dedaeeffd7688f9584441c08f031b790a1d342"



# Finite post-primary R5 provenance only. Original risk science stays in its owners.
RISK_SOURCE_BINDING_FIELDS={"source_configuration_ref","controller_ref","source_transport_ref","recovery_owner_ref"}
RISK_SOURCE_BINDING_PATHS={
 "source_configuration_ref":RUN/"ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json",
 "controller_ref":REPO/"scripts/research/a2/training/selector_full_fixed_policy.py",
 "source_transport_ref":RUN/"continuation/SAVED5_POST_PRIMARY_SOURCE_TRANSPORT_R5.json",
 "recovery_owner_ref":REPO/"scripts/research/a2/training/full_selector_alpha_reboot_recovery.py",
}
RISK_SAVED5_PATH=REPO/"scripts/research/a2/training/full_selector_core_account_source_recovery.py"
RISK_SAVED5_BOOTSTRAP_PATH=CACHE/"proposals/run_core_account_source_recovery_post_primary_fusion_R5_fixed_bootstrap_R4.py"
RISK_POST_PRIMARY_REVIEW=CACHE/"proposals/ENGINEERING_RISK_ENVIRONMENT_RECOVERY_INDEPENDENT_SOURCE_BINDINGS_R1.json"
RISK_SAVED5_HISTORICAL_SOURCE_REF={"path":str(RUN/"ENGINEERING_SOURCE_CORRECTION_R5.json"),"sha256":"c3bff6e808e73155f34f74928f28e041e1ee6107fb9b561984d02642e7766a8d"}
RISK_FIXED_SAVED5_REFS={'complete': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\continuation\\CORE_ACCOUNT_SOURCE_RECOVERY_R1_COMPLETE.json', 'sha256': '1202995462298c10ed87e86240d93487131a6b72c45e55e4b1e13501d3b3b5db'}, 'configuration': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\continuation\\CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1.json', 'sha256': 'd17ae880d3d0c8b33d868634474a64b952764dafaaa79bd96bb0eafd5cc935b6'}, 'acceptance': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\continuation\\CORE_ACCOUNT_SOURCE_RECOVERY_R1_ACCEPTANCE.json', 'sha256': '02099d7735c51d54e009fe167dcb138a937d5811f469a4f2338809b64d6f0122'}, 'entry': {'path': 'D:\\us-tech-quant\\scripts\\research\\a2\\training\\full_selector_core_account_source_recovery.py', 'sha256': 'd49dd09bf161fba98111b9256102ac4c4b2fb705372b0bb272b130cea87f31f0'}, 'os': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\continuation\\CORE_ACCOUNT_SOURCE_RECOVERY_R1_OS_EXIT_RECEIPT_R1.json', 'sha256': '2800b9ce7f20e1ebf886d64253565feb16cfd67ebc2360ed9865fc73c8196a3b'}, 'launch': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\continuation\\CORE_ACCOUNT_SOURCE_RECOVERY_R1_LAUNCH_RECEIPT_R1.json', 'sha256': 'bcdcf085fdc282fa645aaf88fd75b06516cd16b6457bf2c48932c9eb06e09fb1'}, 'process': {'path': 'D:\\us-tech-quant-backtests\\V24\\20261010T151740+0000_642c1248\\continuation\\CORE_ACCOUNT_SOURCE_RECOVERY_R1_PROCESS_OBSERVATION_R1.json', 'sha256': 'f68b6fea73ee9d51806539047b7ea60e9982e3e0686900094167d09c612ab80f'}, 'cold': {'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_METADATA_COLD_R4.json', 'sha256': 'f27172ad4f2beb08c7bdc832cd1ed91bfaf40b5871a20951ae0db9b5cf09dec8'}, 'bootstrap': {'path': 'D:\\us-tech-quant-cache\\V24\\C_SELECTOR\\FULL_SELECTOR_FIXED_POLICY_FAST_R1\\proposals\\run_core_account_source_recovery_post_primary_fusion_R5_fixed_bootstrap_R4.py', 'sha256': 'f048c2ba34e6e3676386488ac138b323139b76840605b0a0f9cc00cb8ff95762'}}
RISK_SAVED5_TERMINAL_REVIEW=CACHE/"proposals/SAVED5_FIXED_ABSENCE_NATURAL_TERMINAL_INDEPENDENT_ACCEPTANCE_R1.json"
RISK_UPSTREAM_FIELDS={"alpha_complete_ref","alpha_terminal_audit_ref","alpha_natural_exit_ref","saved5_complete_ref","saved5_phase_configuration_ref","saved5_independent_closed25_review_ref","saved5_natural_exit_ref"}
RISK_SAVED5_OS_FIELDS={"schema","research_id","status","observed_utc","exit_code","wait_for_exit_observed","terminated_by_agent","launch_ref","config_ref","acceptance_ref","entry_ref","actual_cold_ref","before_process_levels","after_process_levels","complete_ref","failure_ref","stdout_ref","stderr_ref","stdout_bytes","stderr_bytes"}
RISK_NONEXECUTED_LOGICAL_REFS={
 str((REPO/"scripts/maintenance/research_registry.py").resolve()):{"path":str((REPO/"scripts/maintenance/research_registry.py").resolve()),"sha256":"2ac483477b6024c6468e0b7be3131b3032a4b85ef369bcf335e6c36265872b92"},
 str((REPO/"scripts/research/a2/training/stateful_fusion.py").resolve()):{"path":str((REPO/"scripts/research/a2/training/stateful_fusion.py").resolve()),"sha256":"f83c8e09c0cf2856a61f98b51775cf6f382d70b6266878876ced1eba2754ae3b"},
}
_RISK_ACTIVE_CONTROLLER=None

def risk_current_source_binding(cfg=None):
    """Exact future independently reviewed R5 pins; no pending source may pass."""
    pin(ref(RISK_POST_PRIMARY_REVIEW),RISK_POST_PRIMARY_REVIEW);review=read(RISK_POST_PRIMARY_REVIEW)
    require(review.get("schema")=="FULL_SELECTOR_RISK_POST_PRIMARY_R5_SOURCE_REVIEW_R1" and review.get("research_id")==ID
        and review.get("status")=="PASS" and review.get("independent_from_entry_writer") is True
        and review.get("runtime_entry_ref")==ref(__file__),"ACTUAL_INDEPENDENT_R5_RISK_SOURCE_REVIEW_REQUIRED")
    values=review["runtime_source_binding"];require(set(values)==RISK_SOURCE_BINDING_FIELDS,"CLOSED_FOUR_CURRENT_R5_SOURCE_REFS_REQUIRED")
    for key,path in RISK_SOURCE_BINDING_PATHS.items():pin(values[key],path)
    if cfg is not None:require(cfg["engineering_source_configuration_ref"]==values["source_configuration_ref"]
        and cfg["runtime_entry_ref"]==review["runtime_entry_ref"] and cfg["current_entry_custody_ref"]==review["current_entry_custody_ref"],"CURRENT_R5_SOURCE_REVIEW_CONFIGURATION_CHANGED")
    return values,review

def risk_verified_source(value,name):
    path=pin(value)
    module=ModuleType(name);module.__file__=str(path)
    payload=path.read_bytes();require(hashlib.sha256(payload).hexdigest()==value["sha256"],"VERIFIED_SOURCE_BYTES_CHANGED")
    exec(compile(payload,str(path),"exec"),module.__dict__)
    return module

@contextmanager
def risk_runtime_owners(capture_stage="risk_execute_r4"):
    """One original verified-byte transport and actual owner fence, not a source waiver."""
    global _RISK_ACTIVE_CONTROLLER
    require(Path(__file__).resolve()==(REPO/"scripts/research/a2/training/full_selector_engineering_continuation.py").resolve(),"RISK_SOURCE_ONLY_CANDIDATE_NOT_INSTALLED")
    binding,_=risk_current_source_binding()
    recovery=risk_verified_source(binding["recovery_owner_ref"],"_risk_original_verified_recovery")
    previous=_RISK_ACTIVE_CONTROLLER
    with recovery.transported_owners(configuration_ref=binding["source_transport_ref"],source_ref=binding["source_configuration_ref"]) as (c,w,transport):
        pin(binding["controller_ref"],c.__file__)
        require(transport["configuration_ref"]==binding["source_transport_ref"] and transport["actual_controller_ref"]==binding["controller_ref"]
            and transport["active_source_configuration_ref"]==binding["source_configuration_ref"],"EXACT_FOUR_ORIGINAL_SNAPSHOT_TRANSPORT_REQUIRED")
        with c.nonexecuting_registry_metadata_scope(RUN,capture_stage=capture_stage,authority_ref=binding["source_configuration_ref"]):
            _RISK_ACTIVE_CONTROLLER=c
            try:
                account=importlib.import_module("scripts.research.a2.data.full_selector_account_inputs")
                yield c,w,account
            finally:_RISK_ACTIVE_CONTROLLER=previous

def risk_fixed_account_source_refs():
    require(_RISK_ACTIVE_CONTROLLER is not None,"CURRENT_FROZEN_ACCOUNT_SOURCE_SCOPE_REQUIRED")
    binding,_=risk_current_source_binding();data=read(binding["source_configuration_ref"]["path"])
    return _RISK_ACTIVE_CONTROLLER._frozen_account_loaded_sources(data)


def risk_current_nonexecuting_observation():
    require(_RISK_ACTIVE_CONTROLLER is not None,"RISK_TRANSPORT_AND_NONEXECUTING_SCOPE_REQUIRED")
    return _RISK_ACTIVE_CONTROLLER._registry_metadata_observation()

def risk_verify_nonexecuting_capture_ref(value):
    require(_RISK_ACTIVE_CONTROLLER is not None,"RISK_TRANSPORT_AND_NONEXECUTING_SCOPE_REQUIRED")
    return _RISK_ACTIVE_CONTROLLER._registry_metadata_verify_capture_ref(value)

def risk_capture_hash(path):
    observation=risk_current_nonexecuting_observation()
    value=next((v["custody_ref"] for v in observation["entries"].values() if Path(v["custody_ref"]["path"]).resolve()==Path(path).resolve()),None)
    require(value is not None,"ONLY_ACTUAL_TWO_CAPTURE_HASH_REFS")
    risk_verify_nonexecuting_capture_ref(value)
    return value["sha256"]

def risk_saved5_owner(value):
    pin(value,RISK_SAVED5_PATH)
    return risk_verified_source(value,"_risk_original_saved5_metadata_owner")

def risk_metadata_facade(historical_runtime_custody_refs=None):
    """Explicit saved5 metadata-only physical custody reader; global pin is untouched."""
    from types import SimpleNamespace
    expected={
        "controller":{"path":str((REPO/"scripts/research/a2/training/selector_full_fixed_policy.py").resolve()),"sha256":"c06c16288e939b58e1a78cfbe196996c196c6c7d1f2c65716833f95e0d48442e"},
        "transport_owner":{"path":str((REPO/"scripts/research/a2/training/full_selector_alpha_reboot_recovery.py").resolve()),"sha256":"343a867113d361ebf3956ebcc5b66f6b4c4fb4e5a88e083e99b44e059de2aca9"}}
    require(isinstance(historical_runtime_custody_refs,dict) and set(historical_runtime_custody_refs)==set(expected),
        "EXPLICIT_CLOSED_TWO_HISTORICAL_METADATA_RUNTIME_CUSTODIES_REQUIRED")
    for key,value in expected.items():
        custody=historical_runtime_custody_refs[key]
        target=RUN/"source_corrections/FIXED214_NONEXECUTED_METADATA_REFRESH_R1"/((key if key=="controller" else "transport_owner")+"."+value["sha256"]+".before.py")
        require(custody=={"path":str(target),"sha256":value["sha256"]},"EXACT_KNOWN_HISTORICAL_RUNTIME_CUSTODY_REQUIRED")
        pin(custody,target)
    def history_pin(value,expected_path=None):
        matched=next((key for key,v in expected.items() if risk_reference_equal(value,v)),None)
        if matched is None:return pin(value,expected_path)
        require(expected_path is None or Path(expected_path).resolve()==Path(expected[matched]["path"]).resolve(),
            "HISTORICAL_METADATA_LOGICAL_PATH_CHANGED")
        # The returned path is the actual immutable old bytes, never the changed live path.
        return pin(historical_runtime_custody_refs[matched])
    return SimpleNamespace(require=require,pin=history_pin,read=read,public_snapshot=public_snapshot)

def risk_reference_equal(left,right):
    """Closed physical metadata refs: normalize Windows spelling, never hashes."""
    require(all(isinstance(v,dict) and set(v)=={"path","sha256"} and isinstance(v["path"],str)
        and isinstance(v["sha256"],str) and re.fullmatch("[0-9a-f]{64}",v["sha256"]) is not None for v in (left,right)),
        "CLOSED_FIXED_PHYSICAL_METADATA_REFS_REQUIRED")
    return Path(left["path"]).resolve()==Path(right["path"]).resolve() and left["sha256"]==right["sha256"]

def risk_validate_saved5_os(os,launch,account,acceptance,complete_ref,process=None,terminal_review=None):
    """Only the actual 2800/bcdcf/f68 natural chain; scientific FAILED stays FAILED."""
    from datetime import datetime,timezone
    import shlex
    def utc(v):
        require(isinstance(v,str),"UTC_STRING_REQUIRED");value=datetime.fromisoformat(v.replace("Z","+00:00"))
        require(value.tzinfo is not None and value.utcoffset().total_seconds()==0,"EXACT_UTC_REQUIRED");return value
    def birth(v):
        utc(v);match=re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,7}))?(?:Z|\+00:00)",v)
        require(match is not None,"EXACT_WINDOWS_100NS_UTC_BIRTH_REQUIRED")
        return match[1]+("."+match[2].rstrip("0") if match[2] and match[2].rstrip("0") else "")+"Z"
    def level(v):
        fields={"pid","parent_pid","executable_path","command_line","creation_utc"}
        require(isinstance(v,dict) and set(v)==fields and type(v["pid"]) is int and v["pid"]>0
            and type(v["parent_pid"]) is int and isinstance(v["command_line"],str),"CLOSED_NATIVE_PROCESS_IDENTITY_REQUIRED")
        return dict(v,creation_utc=birth(v["creation_utc"]),executable_path=str(Path(v["executable_path"]).resolve()))
    require(set(os)==RISK_SAVED5_OS_FIELDS and os["schema"]=="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_OS_EXIT_RECEIPT_R1"
        and os["research_id"]==ID and os["status"]=="OS_EXIT_OBSERVED" and type(os["exit_code"]) is int and os["exit_code"]==0
        and os["wait_for_exit_observed"] is True and os["terminated_by_agent"] is False and os["failure_ref"] is None,
        "REAL_FIXED_SAVED5_WAITFOREXIT0_REQUIRED")
    expected=dict(config_ref=account["phase_configuration_ref"],acceptance_ref=account["review_ref"],entry_ref=account["runtime_entry_ref"],
        actual_cold_ref=acceptance["actual_source_metadata_cold_ref"],complete_ref=complete_ref,launch_ref=RISK_FIXED_SAVED5_REFS["launch"])
    for key,value in expected.items():require(risk_reference_equal(os[key],value),"SAVED5_OS_PRODUCER_BINDING_CHANGED:"+key)
    for key,label in (("config_ref","configuration"),("acceptance_ref","acceptance"),("entry_ref","entry"),
        ("actual_cold_ref","cold"),("complete_ref","complete")):
        require(risk_reference_equal(os[key],RISK_FIXED_SAVED5_REFS[label]),"ONLY_ACTUAL_FIXED_SAVED5_PRODUCER_CHAIN_REQUIRED")
    require(isinstance(launch,dict) and launch.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_LAUNCH_RECEIPT_R1"
        and launch.get("research_id")==ID and launch.get("status")=="SINGLE_SAVED5_ACCOUNT_EXECUTE_STARTED_NOT_COMPLETE"
        and launch.get("wait_for_exit_once") is True and launch.get("actual_two_level_observation_pending") is True,
        "ACTUAL_FIXED_SAVED5_SINGLE_LAUNCH_REQUIRED")
    for key in ("config_ref","acceptance_ref","entry_ref","actual_cold_ref"):
        require(risk_reference_equal(launch[key],os[key]),"SAVED5_LAUNCH_BINDING_CHANGED:"+key)
    require(isinstance(process,dict) and set(process)=={"schema","research_id","utc","launch_ref","actual_python_process_levels","single_account_worker_two_python_levels"}
        and process["schema"]=="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_PROCESS_OBSERVATION_R1" and process["research_id"]==ID
        and process["single_account_worker_two_python_levels"] is True and risk_reference_equal(process["launch_ref"],RISK_FIXED_SAVED5_REFS["launch"]),
        "ACTUAL_F68_TWO_LEVEL_PROCESS_OBSERVATION_REQUIRED")
    levels=os["before_process_levels"]
    require(isinstance(levels,list) and len(levels)==2 and isinstance(process["actual_python_process_levels"],list)
        and len(process["actual_python_process_levels"])==2,"EXACT_FIXED_TWO_NATIVE_LEVELS_REQUIRED")
    canonical=[level(v) for v in levels];observed=[level(v) for v in process["actual_python_process_levels"]]
    require({v["pid"]:v for v in canonical}=={v["pid"]:v for v in observed} and len({v["pid"] for v in canonical})==2,
        "ACTUAL_F68_AND_OS_BIRTH_IDENTITY_CHANGED")
    require(type(launch["launcher_pid"]) is int and launch["launcher_pid"]==7320,"ONLY_FIXED_SAVED5_LAUNCHER_REQUIRED")
    parents=[v for v in canonical if v["pid"]==launch["launcher_pid"]];require(len(parents)==1,"EXACT_SINGLE_SAVED5_PARENT_REQUIRED")
    parent=parents[0];child=next(v for v in canonical if v is not parent)
    require(child["pid"]==21792 and child["parent_pid"]==parent["pid"] and parent["parent_pid"]==14112
        and Path(parent["executable_path"]).resolve()==Path("D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe").resolve()
        and Path(child["executable_path"]).resolve()==Path("C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe").resolve(),
        "FIXED_SAVED5_PARENT_CHILD_IDENTITY_CHANGED")
    initial=launch["initial_launcher_observation"]
    require(isinstance(initial,list) and len(initial)==1 and level(initial[0])==parent,"INITIAL_LAUNCH_PARENT_BIRTH_CHANGED")
    require(birth(parent["creation_utc"])=="2026-10-12T01:19:57.985343Z" and birth(child["creation_utc"])=="2026-10-12T01:19:58.07418Z",
        "ONLY_ACTUAL_FIXED_SAVED5_BIRTHS_REQUIRED")
    args=launch["arguments"]
    require(isinstance(args,list) and len(args)==8 and args[0]=="-B" and Path(args[1]).resolve()==RISK_SAVED5_BOOTSTRAP_PATH.resolve()
        and risk_reference_equal(launch["bootstrap_ref"],RISK_FIXED_SAVED5_REFS["bootstrap"]),"ACTUAL_REVIEWED_SAVED5_BOOTSTRAP_REQUIRED")
    flags=dict(zip(args[2::2],args[3::2]))
    require(flags=={"--mode":"execute","--acceptance-sha":RISK_FIXED_SAVED5_REFS["acceptance"]["sha256"],
        "--caller-sha":RISK_FIXED_SAVED5_REFS["bootstrap"]["sha256"]},"EXACT_SAVED5_ONCE_EXECUTE_FLAGS_REQUIRED")
    for v in canonical:
        tokens=[x.strip('"') for x in shlex.split(v["command_line"],posix=False)]
        require(len(tokens)==9 and Path(tokens[0]).resolve()==Path(v["executable_path"]).resolve() and tokens[1:]==args,
            "ACTUAL_SAVED5_PROCESS_COMMAND_CHANGED")
    require(isinstance(terminal_review,dict) and terminal_review.get("schema")=="FULL_SELECTOR_SAVED5_FIXED_ABSENCE_NATURAL_TERMINAL_INDEPENDENT_ACCEPTANCE_R1"
        and terminal_review.get("status")=="PASS" and terminal_review.get("research_id")==ID
        and terminal_review.get("scope")=="SAVED5_STAGE_TERMINAL_WITH_FIVE_FROZEN_SOURCE_QUALIFICATION_FAILURES"
        and terminal_review.get("actual_process_identities_gone") is True and terminal_review.get("wait_for_exit_observed_zero") is True
        and terminal_review.get("ledger_poststate")==account["ledger_poststate"],"ACTUAL_INDEPENDENT_FIXED_TERMINAL_AUDIT_REQUIRED")
    for key,label in (("complete_ref","complete"),("configuration_ref","configuration"),("acceptance_ref","acceptance"),
        ("runtime_entry_ref","entry"),("os_exit_ref","os"),("launch_ref","launch"),("process_observation_ref","process")):
        require(risk_reference_equal(terminal_review[key],RISK_FIXED_SAVED5_REFS[label]),"INDEPENDENT_FIXED_TERMINAL_CHAIN_CHANGED:"+key)
    require(os["after_process_levels"]==[],"ONLY_FIXED_2800_EMPTY_AFTER_WITH_ACTUAL_INDEPENDENT_GONE_AUDIT")
    require(utc(launch["started_utc"])<=utc(parent["creation_utc"])<=utc(child["creation_utc"])<=utc(process["utc"])<=utc(os["observed_utc"]),
        "SAVED5_ACTUAL_PROCESS_TIMELINE_CHANGED")
    for stream in ("stdout","stderr"):
        value=os[stream+"_ref"];size=os[stream+"_bytes"]
        require(isinstance(value,dict) and set(value)=={"path","sha256"} and Path(value["path"]).resolve()==Path(launch[stream]).resolve()
            and isinstance(value["sha256"],str) and re.fullmatch("[0-9a-f]{64}",value["sha256"]) is not None
            and type(size) is int and size>=0,"SAVED5_OPAQUE_LOG_ENVELOPE_CHANGED")
    return True

def risk_post_primary_proof(cfg,*,tail_metadata_configuration=None):
    """Finite source review transport; separate from risk native qualification."""
    if tail_metadata_configuration is None:binding,review=risk_current_source_binding(cfg)
    else:binding,review=tail_historical_risk_source_binding(cfg,tail_metadata_configuration)
    proof=review["upstream_terminal_provenance"];require(set(proof)==RISK_UPSTREAM_FIELDS,"CLOSED_SEVEN_UPSTREAM_REFS_REQUIRED")
    folder=RUN/"continuation"
    paths={"alpha_complete_ref":folder/"POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_COMPLETE.json",
        "alpha_terminal_audit_ref":CACHE/"proposals/POST_PRIMARY_FUSION_ALPHA_TERMINAL_METADATA_ACCEPTANCE_R1.json",
        "alpha_natural_exit_ref":folder/"POST_PRIMARY_FUSION_SOURCE_CONTINUATION_R1_OS_EXIT_RECEIPT_R1.json",
        "saved5_complete_ref":folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_COMPLETE.json",
        "saved5_phase_configuration_ref":folder/"CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1.json",
        "saved5_independent_closed25_review_ref":folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_ACCEPTANCE.json",
        "saved5_natural_exit_ref":folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_OS_EXIT_RECEIPT_R1.json"}
    for key,path in paths.items():pin(proof[key],path)
    require(proof["alpha_complete_ref"]==cfg["prior_remaining_complete_ref"] and proof["saved5_complete_ref"]==cfg["engineering_account_completion_ref"],"UPSTREAM_PHASE_CHAIN_CHANGED")
    account=read(proof["saved5_complete_ref"]["path"]);acceptance=read(proof["saved5_independent_closed25_review_ref"]["path"])
    saved=risk_saved5_owner(account["runtime_entry_ref"])
    require(account["phase_configuration_ref"]==proof["saved5_phase_configuration_ref"] and account["review_ref"]==proof["saved5_independent_closed25_review_ref"]
        and acceptance["remaining_terminal_ref"]==proof["alpha_complete_ref"] and acceptance["remaining_terminal_audit_ref"]==proof["alpha_terminal_audit_ref"],"SAVED5_CLOSED25_ALPHA_CHAIN_CHANGED")
    saved_cfg=read(proof["saved5_phase_configuration_ref"]["path"])
    require(saved_cfg.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_CONFIGURATION_R1","FIXED_SAVED5_CURRENT_R5_SCHEMA_REQUIRED")
    current=read(binding["source_configuration_ref"]["path"])
    require(current.get("schema") in ('FULL_SELECTOR_RISK_FIXED_TWO_NONEXECUTED_CAPTURE_ORIGINAL_ACCOUNT_TRANSPORT_R3','FULL_SELECTOR_FIXED_TWO_CAPTURE_ENVIRONMENT_RECOVERY_SOURCE_R4')
        and current["prior_r5_configuration_ref"]==RISK_SAVED5_HISTORICAL_SOURCE_REF,"CURRENT_OBSERVER_VS_HISTORICAL_SAVED5_SOURCE_REQUIRED")
    custody=current["prior_r5_current_runtime_custody_refs"];history=risk_metadata_facade(custody)
    source_binding=saved.configuration_binding(history,saved_cfg)
    saved.validate_source_history(history,saved_cfg,source_binding)
    complete,audit=saved.validate_post_primary_terminal(history,RUN,saved_cfg,proof["alpha_complete_ref"],proof["alpha_terminal_audit_ref"],account["ledger_prestate"])
    require(proof["alpha_natural_exit_ref"]==saved.POST_PRIMARY_REFS["os_exit_ref"] and audit["natural_exit_receipt_ref"]==proof["alpha_natural_exit_ref"],"REAL_ALPHA_OS_CHAIN_CHANGED")
    os=read(proof["saved5_natural_exit_ref"]["path"]);launch_path=folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_LAUNCH_RECEIPT_R1.json"
    pin(os["launch_ref"],launch_path);launch=read(launch_path)
    require(risk_reference_equal(proof["saved5_natural_exit_ref"],RISK_FIXED_SAVED5_REFS["os"])
        and risk_reference_equal(os["launch_ref"],RISK_FIXED_SAVED5_REFS["launch"]),"ONLY_FIXED_REAL_SAVED5_NATURAL_EXIT_CHAIN")
    pin(RISK_FIXED_SAVED5_REFS["process"],folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_PROCESS_OBSERVATION_R1.json")
    process=read(RISK_FIXED_SAVED5_REFS["process"]["path"])
    terminal_review_ref=review["saved5_terminal_independent_review_ref"];pin(terminal_review_ref,RISK_SAVED5_TERMINAL_REVIEW)
    terminal_review=read(terminal_review_ref["path"])
    risk_validate_saved5_os(os,launch,account,acceptance,proof["saved5_complete_ref"],process,terminal_review)
    require(not (folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_FAILURE.json").exists(),"SAVED5_FAILURE_CANNOT_BE_NATURAL_COMPLETION")
    for stream in ("stdout","stderr"):
        pin(os[stream+"_ref"]);require(Path(os[stream+"_ref"]["path"]).stat().st_size==os[stream+"_bytes"],"SAVED5_TERMINAL_LOG_BYTES_CHANGED")
    pin(launch["bootstrap_ref"],RISK_SAVED5_BOOTSTRAP_PATH)
    return complete,account,proof

def risk_input_owner():
    return importlib.import_module("scripts.research.a2.data.full_selector_inputs")


def reference_projection(value):
    # The original input bindings also include descriptive reference metadata.
    require(isinstance(value,dict) and {"path","sha256"}<=set(value),"ORIGINAL_RISK_REFERENCE_REQUIRED")
    return {k:value[k] for k in ("path","sha256")}


def risk_prior_completions(run,cfg,*,tail_metadata_configuration=None):
    folder=Path(run)/"continuation"
    # Exact producer-shaped new alpha receipt. The original failed core stays failed.
    require(not (folder/"CORE_ACCOUNT_CONTINUATION_R1_COMPLETE.json").exists(),"FAILED_OLD_CORE_CANNOT_BE_COMPLETE")
    for key,(relative,expected) in PRESERVED_CORE_REFS.items():
        require(cfg["preserved_refs"][key]==dict(path=str(Path(run)/relative),sha256=expected),"PRESERVED_CORE_REFERENCE_CHANGED")
        pin(cfg["preserved_refs"][key],Path(run)/relative)
    require(set(cfg["preserved_refs"])==set(PRESERVED_CORE_REFS),"EXACT_PRESERVED_CORE_REFERENCE_SET_REQUIRED")
    if tail_metadata_configuration is None:ab,_,_=risk_post_primary_proof(cfg)
    else:ab,_,_=risk_post_primary_proof(cfg,tail_metadata_configuration=tail_metadata_configuration)
    old=read(cfg["base_manifest_ref"]["path"])
    account_preserved=dict(cfg["preserved_refs"])
    account_preserved["old_core_start_ref"]=account_preserved.pop("old_core_started_ref")
    for k in ("original_start_ref","original_failure_ref"):account_preserved[k]=old[k];pin(old[k])
    account=pin(cfg["engineering_account_completion_ref"],folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_COMPLETE.json");cb=read(account)
    fields={"schema","research_id","phase","status","phase_configuration_ref","review_ref","marker_ref","runtime_entry_ref","engineering_source_configuration_ref","base_manifest_ref","preserved_refs","ledger_prestate","ledger_poststate","account_terminal_ref","applicable_core_account_ids","core_account_states","preserved_failed_core_ref","existing_equal_exact_reuse","only_saved_core_account_dispatch","all66_accounts_complete","scientific_retries","all_task_complete","risk_dispatch_entered","outer_feedback"}
    require(set(cb)==fields and cb.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_COMPLETE_R1" and cb.get("research_id")==ID
        and cb.get("phase")=="core-account-source-recovery" and cb.get("status")=="CORE_NON_RISK_ACCOUNT_STAGE_TERMINAL"
        and cb.get("existing_equal_exact_reuse") is True and cb.get("only_saved_core_account_dispatch") is True
        and cb.get("all66_accounts_complete") is False and cb.get("all_task_complete") is False and cb.get("scientific_retries")==0
        and cb.get("risk_dispatch_entered") is False and cb.get("outer_feedback") is False
        and cb["preserved_refs"]==account_preserved and cb["preserved_failed_core_ref"]==cfg["preserved_refs"]["old_core_failure_ref"]
        and cb["engineering_source_configuration_ref"]==RISK_SAVED5_HISTORICAL_SOURCE_REF and cb["base_manifest_ref"]==cfg["base_manifest_ref"],"FIXED_NEW_ACCOUNT_NATURAL_COMPLETION_REQUIRED")
    pin(cb["marker_ref"],folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_STARTED.json");pin(cb["phase_configuration_ref"],folder/"CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1.json")
    config=read(cb["phase_configuration_ref"]["path"]);marker=read(cb["marker_ref"]["path"])
    config_fields={"schema","research_id","phase","run","runtime_entry_ref","module_refs","finite_source_refs","base_manifest_ref","engineering_source_configuration_ref","prior_source_configuration_ref","original_refs","preserved_refs"}
    require(set(config)==config_fields and config.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_CONFIGURATION_R1" and config.get("research_id")==ID
        and config.get("phase")=="core-account-source-recovery" and config["runtime_entry_ref"]==cb["runtime_entry_ref"]
        and config["engineering_source_configuration_ref"]==RISK_SAVED5_HISTORICAL_SOURCE_REF and config["base_manifest_ref"]==cfg["base_manifest_ref"]
        and config["prior_source_configuration_ref"]==cfg["prior_source_configuration_ref"] and config["original_refs"]==cfg["original_refs"]
        and config["preserved_refs"]==account_preserved and marker["phase_configuration_ref"]==cb["phase_configuration_ref"]
        and marker["runtime_entry_ref"]==cb["runtime_entry_ref"] and marker["engineering_source_configuration_ref"]==RISK_SAVED5_HISTORICAL_SOURCE_REF
        and marker["ledger_prestate"]==cb["ledger_prestate"] and not (folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_FAILURE.json").exists(),"EXACT_NEW_ACCOUNT_SOURCE_HISTORY_REQUIRED")
    pin(cb["runtime_entry_ref"],RISK_SAVED5_PATH);pin(cb["review_ref"],folder/"CORE_ACCOUNT_SOURCE_RECOVERY_R1_ACCEPTANCE.json")
    ar=read(cb["review_ref"]["path"])
    require(set(ar)=={"schema","research_id","run","phase","status","phase_configuration_ref","runtime_entry_ref","module_refs","finite_source_refs","base_manifest_ref","prior_source_configuration_ref","engineering_source_configuration_ref","original_refs","preserved_refs","remaining_terminal_ref","remaining_terminal_audit_ref","actual_source_metadata_cold_ref","actual_quote_input_qualification_ref","ledger_prestate","all_prior_workers_terminal","independent_from_entry_writer","scientific_retry_authorized","first_account_dispatch_only","fixed_core_account_ids","account_backend_entered_before_review"},"ORIGINAL_CLOSED25_SAVED5_REVIEW_REQUIRED")
    require(ar.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_POST_PRIMARY_FUSION_R5_SOURCE_RECOVERY_ACCEPTANCE_R1" and ar.get("status")=="PASS"
        and ar.get("research_id")==ID and ar.get("phase")=="core-account-source-recovery"
        and ar.get("independent_from_entry_writer") is True and ar.get("all_prior_workers_terminal") is True
        and ar.get("scientific_retry_authorized") is False and ar.get("first_account_dispatch_only") is True
        and ar.get("account_backend_entered_before_review")==0
        and ar["phase_configuration_ref"]==cb["phase_configuration_ref"] and ar["runtime_entry_ref"]==cb["runtime_entry_ref"]
        and ar["engineering_source_configuration_ref"]==RISK_SAVED5_HISTORICAL_SOURCE_REF
        and ar["preserved_refs"]==account_preserved and marker["review_ref"]==cb["review_ref"],"FIXED_INDEPENDENT_ACCOUNT_COMPLETION_PROOF_REQUIRED")
    pin(cb["account_terminal_ref"],Path(run)/"CORE_BASE_ACCOUNT_TERMINAL.json")
    require(cb["applicable_core_account_ids"]==["RAW","RIDGE","HGB","LAMBDAMART","FUSION_equal"]
        and set(cb["core_account_states"])==set(cb["applicable_core_account_ids"])
        and all(isinstance(s,str) and s in TERMINAL for s in cb["core_account_states"].values()),"EXACT_SAVED_FIVE_CORE_ACCOUNT_TERMINALS_REQUIRED")
    return ab,cb



RISK_ENVIRONMENT_NAME="RISK_ENVIRONMENT_REPLAY_CONTINUATION_R4"
RISK_ENVIRONMENT_BOUNDARY=RUN/"maintenance/FIXED214_RISK_FOURTH_OS_REBOOT_READONLY_BOUNDARY_R2.json"
RISK_ENVIRONMENT_BOUNDARY_SHA="8485af0a727cd155b1ca539d8bf8899afac023341f7d95eb139aafa7d50ad8dc"
RISK_ENVIRONMENT_MANIFEST=CACHE/"proposals/FIXED214_ENVIRONMENT_REPLAY_MANIFEST_CANDIDATE_R1.json"
RISK_ENVIRONMENT_MANIFEST_SHA="9ddb8ae9164ad4d97fb62db1a47f5aad7a0212fe1079bc3d1a840b42c400df6e"
RISK_ENVIRONMENT_GROUPS={"RISK_REFRESH|2021-04-09","RISK_REFRESH|2021-11-03","RISK_REFRESH|2022-05-04","RISK_REFRESH|2025-09-02"}

def risk_environment_phase_namespace(run):
    risk_third_phase_namespace(run)
    pin(dict(path=str(RISK_ENVIRONMENT_BOUNDARY),sha256=RISK_ENVIRONMENT_BOUNDARY_SHA))
    pin(dict(path=str(RISK_ENVIRONMENT_MANIFEST),sha256=RISK_ENVIRONMENT_MANIFEST_SHA))
    boundary=read(RISK_ENVIRONMENT_BOUNDARY);manifest=read(RISK_ENVIRONMENT_MANIFEST)
    require(boundary.get("schema")=="FIXED214_RISK_FOURTH_OS_REBOOT_READONLY_BOUNDARY_R2"
        and boundary.get("research_id")==ID and boundary.get("original8318_event_prefix_exact") is True
        and boundary.get("prior8318_nodes_reconstruction_exact") is True and boundary.get("ledger_readonly_before_after_exact") is True
        and boundary.get("complete_contexts")==173 and boundary.get("remaining_qualified_unentered_contexts")==13
        and boundary.get("original_pending_contexts")==24 and boundary.get("actual_paid_risk_learned_units")==6485,
        "ACTUAL_FOURTH_REBOOT_BOUNDARY_REQUIRED")
    require(manifest.get("schema")=="FULL_SELECTOR_FIXED214_ENVIRONMENT_REPLAY_MANIFEST_R1" and manifest.get("research_id")==ID
        and set(manifest.get("groups",{}))==RISK_ENVIRONMENT_GROUPS and manifest.get("actual_fourth_boundary_ref")==ref(RISK_ENVIRONMENT_BOUNDARY)
        and manifest.get("ledger_prestate")==boundary["metadata_snapshot"] and manifest.get("original_environment_paid_units_preserved")==105
        and manifest.get("scientific_failed_trial_retries")==0 and manifest.get("new_scientific_nodes_authorized") is False
        and manifest.get("risk_total_entry_cap")==15194 and manifest.get("worst_case_paid_after_this_bounded_phase")==7692,
        "FIXED_FOUR_ENVIRONMENT_MANIFEST_AND_ORIGINAL_BUDGET_REQUIRED")
    pin(manifest["human_authorization_ref"]);human=read(manifest["human_authorization_ref"]["path"])
    require(manifest["human_authorization_ref"]["sha256"]=="c06815fccd5b8e6a9294f24cd7a629df745363243a300b85ad524bb6682863c5"
        and human.get("user_quote")=="中断的你就继续重做"
        and human.get("scientific_failed_trial_retries")==0 and human.get("new_scientific_nodes_authorized") is False,
        "CURRENT_DIRECT_HUMAN_ENVIRONMENT_REDO_REQUIRED")
    expected={"RISK_REFRESH|2021-04-09":(RISK_REBOOT_DISPOSITION,15),"RISK_REFRESH|2021-11-03":(RISK_SECOND_DISPOSITION,32),"RISK_REFRESH|2022-05-04":(RISK_THIRD_DISPOSITION,25),"RISK_REFRESH|2025-09-02":(RISK_ENVIRONMENT_BOUNDARY,33)}
    for node,(proof_path,paid) in expected.items():
        group=manifest["groups"][node]
        require(group["actual_interruption_proof_ref"]==ref(proof_path) and group["original_paid_units"]==paid
            and len(group["original_rows"])==72 and group.get("old_scientific_negative_inferred") is False,
            "EXACT_REAL_ENVIRONMENT_PROOF_PER_GROUP_REQUIRED")
        pin(group["actual_interruption_proof_ref"])
    require(boundary["actual_marker_ref"]==ref(Path(run)/"continuation"/(RISK_THIRD_NAME+"_STARTED.json"))
        and not any((Path(run)/"continuation"/(RISK_THIRD_NAME+"_"+suffix+".json")).exists() for suffix in ("COMPLETE","FAILURE","OS_EXIT_RECEIPT_R1")),
        "PRESERVE_R3_OS_INTERRUPTION_NO_FAKE_NATURAL_TERMINAL")
    return RISK_ENVIRONMENT_NAME

def risk_environment_recovery_refs(review_ref,phase_review):
    pin(review_ref,CACHE/"proposals/FIXED214_ENVIRONMENT_RISK_REPLAY_INDEPENDENT_ACTUAL_ACCEPTANCE_R1.json")
    value=read(review_ref["path"])
    require(value.get("schema")=="FULL_SELECTOR_ENVIRONMENT_RISK_REPLAY_INDEPENDENT_ADMISSION_R1" and value.get("status")=="PASS"
        and value.get("independent_from_entry_writer") is True and value.get("independent_from_dispatch_writer") is True
        and value.get("manifest_ref")==ref(RISK_ENVIRONMENT_MANIFEST) and value.get("actual_boundary_ref")==ref(RISK_ENVIRONMENT_BOUNDARY)
        and value.get("approved_complete19_payload")==phase_review and value.get("approved_field_count")==19
        and value.get("workflow_candidate_sha256")=="3e9764be31de959f5ad04029420c6a771f5d6c96ac7c8301f1656496270aec8f"
        and value.get("scientific_failed_trial_retries")==0 and value.get("new_scientific_nodes_authorized") is False,
        "ACTUAL_INDEPENDENT_CLOSED19_ENVIRONMENT_PHASE_APPROVAL_REQUIRED")
    return dict(manifest_ref=ref(RISK_ENVIRONMENT_MANIFEST),independent_admission_ref=review_ref)

RISK_THIRD_NAME="RISK_REBOOT_NAMED_ONLY_CONTINUATION_R3"
RISK_THIRD_BOUNDARY=RUN/"maintenance/FIXED214_RISK_THIRD_OS_REBOOT_READONLY_BOUNDARY_R1.json"
RISK_THIRD_BOUNDARY_SHA="47a638282972788e522972e4d7aaf001ad03163401a79892370822eab6d5a766"
RISK_THIRD_DISPOSITION=RUN/"maintenance/FIXED214_RISK_THIRD_REBOOT_DISPOSITION_ACTUAL_R1.json"
RISK_THIRD_DISPOSITION_SHA="a930c70353644050a2a1516ff4d387f81b8f2262c2a71502186ed8803951f0a0" # exact actual third administrative closure, not science admission

RISK_SECOND_NAME="RISK_REBOOT_NAMED_ONLY_CONTINUATION_R2"
RISK_SECOND_BOUNDARY=RUN/"maintenance/FIXED214_RISK_SECOND_OS_REBOOT_READONLY_BOUNDARY_R1.json"
RISK_SECOND_BOUNDARY_SHA="86c39908323193fadcba0972feea02a9fc327cedf9758eb7fde88db4fdaa53b0"
RISK_SECOND_DISPOSITION=RUN/"maintenance/FIXED214_RISK_SECOND_REBOOT_DISPOSITION_ACTUAL_R1.json"
RISK_SECOND_DISPOSITION_SHA="a12d7b10af05be85c00c27627916e1b57f4c7e7ece14d979cae56adddebebe14" # exact actual administrative closure, not science admission
RISK_REBOOT_NAME="RISK_REBOOT_NAMED_ONLY_CONTINUATION_R1"
RISK_REBOOT_BOUNDARY=RUN/"maintenance/FIXED214_RISK_OS_REBOOT_INTERRUPTION_READONLY_BOUNDARY_R1.json"
RISK_REBOOT_BOUNDARY_SHA="2919c160341689df5a81a00d23a05e8d874fa81383a8f031fa4e99055a29f037"
RISK_REBOOT_DISPOSITION_SHA="6fc18096809b29cf54987b624bec36454c83acd2365dc744503f9b12ba7ea40b"
RISK_REBOOT_DISPOSITION=RUN/"maintenance/FIXED214_RISK_REBOOT_INTERRUPTION_DISPOSITION_ACTUAL_R1.json"

def risk_phase_namespace(run,phase_name=None):
    """Only fixed reviewed engineering phases; scientific nodes never renamed."""
    require(Path(run).resolve()==RUN.resolve(),"EXACT_REBOOT_TASK_REQUIRED")
    name=RISK_NAME if phase_name is None else phase_name
    require(name in (RISK_NAME,RISK_REBOOT_NAME,RISK_SECOND_NAME,RISK_THIRD_NAME,RISK_ENVIRONMENT_NAME,RISK_PENDING_NAME),"EXACT_ORIGINAL_OR_FIXED_REBOOT_PHASE_REQUIRED")
    if name==RISK_PENDING_NAME:return name
    if name==RISK_ENVIRONMENT_NAME:return risk_environment_phase_namespace(run)
    if name==RISK_THIRD_NAME:return risk_third_phase_namespace(run)
    if name==RISK_SECOND_NAME:return risk_second_phase_namespace(run)
    if name==RISK_NAME:return name
    pin({"path":str(RISK_REBOOT_BOUNDARY),"sha256":RISK_REBOOT_BOUNDARY_SHA})
    pin({"path":str(RISK_REBOOT_DISPOSITION),"sha256":RISK_REBOOT_DISPOSITION_SHA})
    boundary=read(RISK_REBOOT_BOUNDARY);disposition=read(RISK_REBOOT_DISPOSITION)
    require(boundary["research_id"]==ID and boundary["original_partial_STARTED_replay_refused"] is True
        and boundary["remaining_qualified_unentered_contexts"]==163
        and disposition.get("schema")=="FIXED214_RISK_REBOOT_INTERRUPTION_DISPOSITION_ACTUAL_R1"
        and disposition.get("status")=="ACTUAL_FIXED_ENVIRONMENT_INTERRUPTION_FINALIZED_NO_SCIENTIFIC_REPLAY"
        and disposition.get("boundary_ref")==ref(RISK_REBOOT_BOUNDARY)
        and disposition.get("interrupted_group")=="RISK_REFRESH|2021-04-09"
        and disposition.get("entered_units_preserved_failed")==15
        and disposition.get("unentered_upper_units_not_required")==56
        and disposition.get("paid_units_before_after")==560
        and disposition.get("old_event_prefix_exact") is True
        and disposition.get("non_group_nodes_and_authority_exact") is True
        and disposition.get("scientific_retry_authorized") is False,"ACTUAL_FIXED_INTERRUPTION_DISPOSITION_REQUIRED")
    pin(disposition["independent_review_ref"]);review=read(disposition["independent_review_ref"]["path"])
    require(review.get("status")=="PASS" and review.get("independent_from_disposition_writer") is True
        and review.get("actual_boundary_ref")==ref(RISK_REBOOT_BOUNDARY)
        and review.get("disposition_caller_ref")==disposition["caller_ref"]
        and review.get("scientific_retry_authorized") is False,"INDEPENDENT_ACTUAL_INTERRUPTION_CLOSURE_REQUIRED")
    pin(disposition["caller_ref"])
    require(boundary["actual_marker_ref"]==ref(Path(run)/"continuation"/(RISK_NAME+"_STARTED.json"))
        and not any((Path(run)/"continuation"/(RISK_NAME+"_"+s+".json")).exists() for s in ("COMPLETE","FAILURE")),
        "PRESERVED_REAL_INTERRUPTED_PHASE_NO_FAKE_TERMINAL")
    return name


def risk_second_phase_namespace(run):
    """Fixed second observed reboot, no generic resume namespace or scientific replay."""
    risk_phase_namespace(run,RISK_REBOOT_NAME)
    pin({"path":str(RISK_SECOND_BOUNDARY),"sha256":RISK_SECOND_BOUNDARY_SHA})
    pin({"path":str(RISK_SECOND_DISPOSITION),"sha256":RISK_SECOND_DISPOSITION_SHA})
    b=read(RISK_SECOND_BOUNDARY);d=read(RISK_SECOND_DISPOSITION)
    require(b["research_id"]==ID and b["original2977_event_prefix_exact"] is True
        and b["prior2977_nodes_reconstruction_exact"] is True and b["ledger_readonly_before_after_exact"] is True
        and b["remaining_qualified_unentered_contexts"]==129 and b["complete_contexts"]==59
        and b["original_partial_STARTED_replay_refused"] is True
        and d.get("schema")=="FIXED214_RISK_SECOND_REBOOT_DISPOSITION_ACTUAL_R1"
        and d.get("status")=="ACTUAL_FIXED_ENVIRONMENT_INTERRUPTION_FINALIZED_NO_SCIENTIFIC_REPLAY"
        and d.get("boundary_ref")==ref(RISK_SECOND_BOUNDARY) and d.get("interrupted_group")=="RISK_REFRESH|2021-11-03"
        and d.get("entered_units_preserved_failed")==32 and d.get("unentered_upper_units_not_required")==39
        and d.get("paid_units_before_after")==1821 and d.get("old_event_prefix_exact") is True
        and d.get("non_group_nodes_and_authority_exact") is True and d.get("scientific_retry_authorized") is False,
        "ACTUAL_FIXED_SECOND_INTERRUPTION_CLOSURE_REQUIRED")
    pin(d["independent_review_ref"]);pin(d["caller_ref"]);r=read(d["independent_review_ref"]["path"])
    require(r.get("status")=="PASS" and r.get("independent_from_disposition_writer") is True
        and r.get("actual_boundary_ref")==ref(RISK_SECOND_BOUNDARY) and r.get("disposition_caller_ref")==d["caller_ref"]
        and r.get("scientific_retry_authorized") is False,"INDEPENDENT_SECOND_ENVIRONMENT_DISPOSITION_REQUIRED")
    require(b["actual_marker_ref"]==ref(Path(run)/"continuation"/(RISK_REBOOT_NAME+"_STARTED.json"))
        and not any((Path(run)/"continuation"/(RISK_REBOOT_NAME+"_"+v+".json")).exists() for v in ("COMPLETE","FAILURE","OS_EXIT_RECEIPT_R1")),
        "PRESERVE_REAL_SECOND_INTERRUPTED_PHASE_NO_FAKE_NATURAL_TERMINAL")
    return RISK_SECOND_NAME


def risk_third_phase_namespace(run):
    """Fixed third observed reboot, no generic resume namespace or scientific replay."""
    risk_second_phase_namespace(run)
    pin({"path":str(RISK_THIRD_BOUNDARY),"sha256":RISK_THIRD_BOUNDARY_SHA})
    pin({"path":str(RISK_THIRD_DISPOSITION),"sha256":RISK_THIRD_DISPOSITION_SHA})
    b=read(RISK_THIRD_BOUNDARY);d=read(RISK_THIRD_DISPOSITION)
    require(b["research_id"]==ID and b["original5569_event_prefix_exact"] is True
        and b["prior5569_nodes_reconstruction_exact"] is True and b["ledger_readonly_before_after_exact"] is True
        and b["remaining_qualified_unentered_contexts"]==95 and b["complete_contexts"]==92
        and b["original_partial_STARTED_replay_refused"] is True
        and d.get("schema")=="FIXED214_RISK_THIRD_REBOOT_DISPOSITION_ACTUAL_R1"
        and d.get("status")=="ACTUAL_FIXED_ENVIRONMENT_INTERRUPTION_FINALIZED_NO_SCIENTIFIC_REPLAY"
        and d.get("boundary_ref")==ref(RISK_THIRD_BOUNDARY) and d.get("interrupted_group")=="RISK_REFRESH|2022-05-04"
        and d.get("entered_units_preserved_failed")==25 and d.get("unentered_upper_units_not_required")==46
        and d.get("paid_units_before_after")==3157 and d.get("old_event_prefix_exact") is True
        and d.get("non_group_nodes_and_authority_exact") is True and d.get("scientific_retry_authorized") is False,
        "ACTUAL_FIXED_THIRD_INTERRUPTION_CLOSURE_REQUIRED")
    pin(d["independent_review_ref"]);pin(d["caller_ref"]);r=read(d["independent_review_ref"]["path"])
    require(r.get("status")=="PASS" and r.get("independent_from_disposition_writer") is True
        and r.get("actual_boundary_ref")==ref(RISK_THIRD_BOUNDARY) and r.get("disposition_caller_ref")==d["caller_ref"]
        and r.get("scientific_retry_authorized") is False,"INDEPENDENT_THIRD_ENVIRONMENT_DISPOSITION_REQUIRED")
    require(b["actual_marker_ref"]==ref(Path(run)/"continuation"/(RISK_SECOND_NAME+"_STARTED.json"))
        and not any((Path(run)/"continuation"/(RISK_SECOND_NAME+"_"+v+".json")).exists() for v in ("COMPLETE","FAILURE","OS_EXIT_RECEIPT_R1")),
        "PRESERVE_REAL_THIRD_INTERRUPTED_PHASE_NO_FAKE_NATURAL_TERMINAL")
    return RISK_THIRD_NAME


def load_risk_configuration(run,phase_name=None):
    """Source/terminal configuration gate before cold or final risk admission."""
    run=Path(run).resolve();phase_name=risk_phase_namespace(run,phase_name);require(run==RUN.resolve(),"EXACT_RISK_CONTINUATION_TASK_REQUIRED")
    if phase_name==RISK_PENDING_NAME:return load_pending_risk_configuration(run)
    require(Path(__file__).resolve()==(REPO/"scripts/research/a2/training/full_selector_engineering_continuation.py").resolve(),"RISK_SOURCE_ONLY_CANDIDATE_NOT_INSTALLED")
    risk_current_nonexecuting_observation()
    for name,expected in ORIGINAL_PINS.items():require(sha(run/name)==expected,"ORIGINAL_FREEZE_INPUT_OR_GATE_CHANGED:"+name)
    folder=run/"continuation";path=risk_configuration_path(run,phase_name);cfg=read(path);design=read(run/"DESIGN_FREEZE.json")
    fields={"schema","research_id","run","runtime_entry_ref","original_refs","previous_entry_custody_ref","current_entry_custody_ref","base_manifest_ref","prior_source_configuration_ref","engineering_source_configuration_ref","prior_remaining_complete_ref","engineering_account_completion_ref","preserved_refs","audit_ref","shortlist_ref","qualification_ref","metadata_helper_overlay"}
    require(set(cfg)==fields and cfg.get("schema")=="FULL_SELECTOR_FIXED214_RISK_PHASE_CONFIGURATION_R1" and cfg.get("research_id")==ID
        and Path(cfg.get("run","")).resolve()==run and cfg["runtime_entry_ref"]==ref(__file__),"EXACT_RISK_ENTRY_CONFIGURATION_REQUIRED")
    require(cfg["original_refs"]=={n:ref(run/n) for n in ORIGINAL_PINS},"ORIGINAL_RISK_AUTHORITY_CHANGED")
    pin(cfg["previous_entry_custody_ref"],PRIOR_R3_CUSTODY);require(cfg["previous_entry_custody_ref"]["sha256"]==R3_ENTRY_SHA,"EXACT_PRIOR_R3_SOURCE_CUSTODY_REQUIRED")
    pin(cfg["current_entry_custody_ref"],RISK_C6_CUSTODY);require(cfg["current_entry_custody_ref"]["sha256"]==RISK_C6_SHA,"EXACT_PRE_RISK_C6_CUSTODY_REQUIRED")
    pin(cfg["base_manifest_ref"],folder/"ENGINEERING_CONTINUATION_MANIFEST_R1.json");require(cfg["base_manifest_ref"]["sha256"]==R3_MANIFEST_SHA,"IMMUTABLE_ORIGINAL_SINGLE_MANIFEST_REQUIRED")
    old=read(cfg["base_manifest_ref"]["path"]);require(old["entry_ref"]["sha256"]==R3_ENTRY_SHA and old["original_refs"]==cfg["original_refs"],"ORIGINAL_R3_HISTORY_CHANGED")
    pin(old["original_start_ref"],run/"PRIMARY_CORE_EXECUTION_STARTED.json");pin(old["original_failure_ref"],run/"EXECUTION_FAILURE.json")
    pin(cfg["prior_source_configuration_ref"],run/"ENGINEERING_SOURCE_CORRECTION_R1.json")
    require(cfg["prior_source_configuration_ref"]["sha256"]==PRIOR_SOURCE_SHA and cfg["prior_source_configuration_ref"]==old["engineering_source_configuration_ref"],"IMMUTABLE_PRIOR_SOURCE_R1_REQUIRED")
    binding,_=risk_current_source_binding(cfg)
    pin(binding["source_configuration_ref"],run/"ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json")
    require(isinstance(cfg["metadata_helper_overlay"],dict) and set(cfg["metadata_helper_overlay"])=={"base_ref","candidate_ref","independent_review_ref"}
        and cfg["metadata_helper_overlay"]["base_ref"]=={"path":str(RISK_INPUT_OWNER),"sha256":RISK_INPUT_OWNER_SHA}
        and cfg["metadata_helper_overlay"]["candidate_ref"]=={"path":str(RISK_HELPER),"sha256":RISK_HELPER_SHA}
        and cfg["metadata_helper_overlay"]["independent_review_ref"]["sha256"]=="c367f09771d8ec5ac8fb39584c6d7f9fbdc782c646c238c597a56cc6f26ad3df","MANDATORY_ORIGINAL_CLOSED3_HELPER_OVERLAY_REQUIRED")
    risk_prior_completions(run,cfg)
    for key,target,expected in (("audit_ref",RISK_AUDIT,RISK_AUDIT_SHA),("shortlist_ref",RISK_SHORTLIST,RISK_SHORTLIST_SHA)):
        pin(cfg[key],target);require(cfg[key]["sha256"]==expected,"FIXED_ORIGINAL_METADATA_AUDIT_REQUIRED")
    require(not any((folder/(phase_name+"_"+s+".json")).exists() for s in ("STARTED","COMPLETE","FAILURE")),"RISK_PHASE_ALREADY_STARTED_NO_RETRY")
    return cfg,design


def load_risk_authority(run,phase_name=None):
    phase_name=risk_phase_namespace(run,phase_name)
    if phase_name==RISK_PENDING_NAME:return load_pending_risk_authority(run)
    manifest,design=load_risk_configuration(run,phase_name);run=Path(run);folder=run/"continuation"
    pin(manifest["qualification_ref"]);qualification=read(manifest["qualification_ref"]["path"])
    require(qualification.get("schema")=="FULL_SELECTOR_FIXED214_RISK_METADATA_QUALIFICATION_R1"
        and qualification.get("status")=="PASS_ORIGINAL_FIXED_RISK_SOURCE_METADATA_AND_MINIMUM_SUPPORT"
        and qualification.get("research_id")==ID and qualification.get("independent_from_dispatch_writer") is True
        and qualification["audit_ref"]==manifest["audit_ref"] and qualification["shortlist_ref"]==manifest["shortlist_ref"]
        and qualification["design_ref"]==ref(run/"DESIGN_FREEZE.json") and qualification["risk_inputs_ref"]==ref(run/"risk_inputs.json")
        and qualification.get("full_U_axis_preserved") is True and qualification.get("original_UID_epochs_preserved") is True
        and qualification.get("original_minimum_support_gate_passed") is True and qualification.get("numeric_result_used_for_selection") is False,"CANDIDATE_AUDIT_IS_NOT_RISK_ADMISSION")
    review_path=folder/(phase_name+"_ACCEPTANCE.json");review=read(review_path)
    require(review.get("schema")=="FULL_SELECTOR_ENGINEERING_RISK_PHASE_ACCEPTANCE_R1" and review.get("status")=="PASS"
        and review.get("research_id")==ID and review.get("phase")==RISK_PHASE and review.get("independent_from_entry_writer") is True
        and review.get("original_worker_terminal") is True and review.get("scientific_retry_authorized") is False
        and review.get("past_alpha_phases_complete") is True,"INDEPENDENT_TERMINAL_BOUND_RISK_REVIEW_REQUIRED")
    require(review["phase_configuration_ref"]==ref(risk_configuration_path(run,phase_name)) and review["runtime_entry_ref"]==manifest["runtime_entry_ref"]
        and review["qualification_ref"]==manifest["qualification_ref"] and review["engineering_source_configuration_ref"]==manifest["engineering_source_configuration_ref"],"RISK_REVIEW_BINDINGS_CHANGED")
    pin(review["independent_entry_source_review_ref"],RISK_POST_PRIMARY_REVIEW)
    require(review["independent_entry_source_review_ref"]==ref(RISK_POST_PRIMARY_REVIEW),"CURRENT_UPSTREAM_SOURCE_REVIEW_CHANGED")
    pin(review["actual_source_runtime_cold_ref"]);cold=read(review["actual_source_runtime_cold_ref"]["path"])
    require(cold.get("schema")=="FULL_SELECTOR_ENGINEERING_RISK_SOURCE_METADATA_RUNTIME_COLD_R2" and cold.get("status")=="PASS"
        and cold.get("research_id")==ID and cold.get("actual_cold") is True and cold.get("synthetic") is False
        and cold["phase_configuration_ref"]==review["phase_configuration_ref"] and cold["current_R4_entry_ref"]==manifest["runtime_entry_ref"]
        and cold["engineering_source_configuration_ref"]==manifest["engineering_source_configuration_ref"]
        and cold.get("source_and_sql_unchanged") is True and cold.get("scientific_entry_calls")==0
        and cold.get("actual_qualification_gate_pass") is False and cold.get("actual_dispatch_allowed") is False,"ACTUAL_METADATA_RUNTIME_COLD_IS_NOT_QUALIFICATION")
    require(cold.get("independent_entry_source_review_ref")==review["independent_entry_source_review_ref"],"ACTUAL_COLD_UPSTREAM_SOURCE_REVIEW_CHANGED")
    if phase_name==RISK_REBOOT_NAME:
        require(review.get("interruption_boundary_ref")==ref(RISK_REBOOT_BOUNDARY)
            and review.get("interruption_disposition_ref")==ref(RISK_REBOOT_DISPOSITION),"ACTUAL_REBOOT_PHASE_ANCESTRY_REQUIRED")
    if phase_name==RISK_SECOND_NAME:
        require(review.get("interruption_boundary_ref")==ref(RISK_SECOND_BOUNDARY)
            and review.get("interruption_disposition_ref")==ref(RISK_SECOND_DISPOSITION),"SECOND_PHASE_ACTUAL_INTERRUPTION_ANCESTRY_REQUIRED")
    if phase_name==RISK_THIRD_NAME:
        require(review.get("interruption_boundary_ref")==ref(RISK_THIRD_BOUNDARY)
            and review.get("interruption_disposition_ref")==ref(RISK_THIRD_DISPOSITION),"THIRD_PHASE_ACTUAL_INTERRUPTION_ANCESTRY_REQUIRED")
    if phase_name==RISK_ENVIRONMENT_NAME:
        require(set(review)==set(read(RISK_THIRD_DISPOSITION.parent.parent/"continuation"/(RISK_THIRD_NAME+"_ACCEPTANCE.json"))) and len(review)==19
            and review.get("interruption_boundary_ref")==ref(RISK_ENVIRONMENT_BOUNDARY)
            and review.get("interruption_disposition_ref")==ref(RISK_ENVIRONMENT_MANIFEST),"EXACT_CLOSED19_FOURTH_ENVIRONMENT_ANCESTRY_REQUIRED")
    return manifest,review,ref(review_path),design,qualification


@contextmanager
def risk_metadata_overlay(full,manifest):
    cfg=manifest.get("metadata_helper_overlay")
    base=pin({"path":str(RISK_INPUT_OWNER),"sha256":RISK_INPUT_OWNER_SHA})
    require(Path(full.__file__).resolve()==base,"ORIGINAL_RISK_INPUT_OWNER_ORIGIN_REQUIRED")
    original=full._fixed_policy_native_metadata;loader=full.load_fixed_policy_risk_inputs
    require(Path(loader.__code__.co_filename).resolve()==base,"ORIGINAL_RISK_LOADER_CODE_ORIGIN_REQUIRED")
    require(Path(original.__code__.co_filename).resolve()==base,"ORIGINAL_METADATA_HELPER_ORIGIN_REQUIRED_NO_NESTED_OVERLAY")
    if cfg is None:
        yield None;return
    require(set(cfg)=={"base_ref","candidate_ref","independent_review_ref"}
        and cfg["base_ref"]=={"path":str(RISK_INPUT_OWNER),"sha256":RISK_INPUT_OWNER_SHA},"EXACT_METADATA_OVERLAY_SCOPE_REQUIRED")
    candidate=pin(cfg["candidate_ref"],RISK_HELPER)
    require(cfg["candidate_ref"]["sha256"]==RISK_HELPER_SHA,"EXACT_METADATA_HELPER_SOURCE_REQUIRED")
    pin(cfg["independent_review_ref"]);review=read(cfg["independent_review_ref"]["path"])
    require(review.get("status")=="PASS" and review.get("independent_from_helper_writer") is True
        and review.get("original_ref")==cfg["base_ref"] and review.get("candidate_ref")==cfg["candidate_ref"]
        and review.get("scientific_metadata_predicates_unchanged") is True,"INDEPENDENT_METADATA_HELPER_REVIEW_REQUIRED")
    text=candidate.read_text(encoding="utf-8");tree=ast.parse(text)
    require(len(tree.body)==1 and isinstance(tree.body[0],ast.FunctionDef)
        and tree.body[0].name=="_fixed_policy_native_metadata","ONLY_ONE_METADATA_HELPER_ALLOWED")
    namespace=dict(vars(full));namespace["__file__"]=str(base)
    exec(compile(text,str(candidate),"exec"),namespace)
    helper=namespace["_fixed_policy_native_metadata"]
    require(Path(helper.__code__.co_filename).resolve()==candidate,"ACTUAL_METADATA_HELPER_CODE_ORIGIN_REQUIRED")
    full._fixed_policy_native_metadata=helper
    try:
        yield dict(original_ref=cfg["base_ref"],candidate_ref=cfg["candidate_ref"],co_filename=helper.__code__.co_filename)
        require(full.load_fixed_policy_risk_inputs is loader,"ORIGINAL_NUMERIC_LOADER_CHANGED")
    finally:
        full._fixed_policy_native_metadata=original


def risk_dispatch_plan(workflow,controller,run,manifest,review,qualification):
    value=workflow.load_contexts(run)
    compact=value["compact_document"];original=compact["contexts"]
    require(len(original)==RISK_CONTEXT_COUNT and len(value["plan"]["nodes"])==RISK_CONTEXT_COUNT*RISK_FAMILY_COUNT
        and value["plan"]["learned_units_upper_bound"]==RISK_CONTEXT_COUNT*RISK_UPPER,
        "EXACT_FIXED214_3852_15194_REQUIRED")
    families=tuple(controller.FAMILIES)
    require(len(families)==RISK_FAMILY_COUNT and len(set(families))==RISK_FAMILY_COUNT
        and review["requested_families"]==list(families),"ALL_ORIGINAL18_FAMILIES_REQUIRED")
    require(qualification["contexts_ref"]==reference_projection(value["contexts_ref"])
        and qualification["recipe_sha256"]==value["plan"]["recipe_sha256"],"ORIGINAL_CONTEXT_RECIPE_CHANGED")
    contexts={};node_hashes={}
    for index,context in enumerate(original):
        body={k:v for k,v in context.items() if k!="context_id"}
        require(context["context_id"]==digest(body) and context["context_id"] not in contexts,"ORIGINAL_CONTEXT_PAYLOAD_CHANGED")
        contexts[context["context_id"]]=(index,context)
        nodes=[n for n in value["plan"]["nodes"] if n["decision_at"]==context["decision_at"]]
        require(len(nodes)==RISK_FAMILY_COUNT and {n["family"] for n in nodes}==set(families),"EXACT_ORIGINAL_FAMILY_NODES_REQUIRED")
        node_hashes[context["context_id"]]={n["family"]:digest(n) for n in nodes}
    shortlist=read(manifest["shortlist_ref"]["path"]);audit=read(manifest["audit_ref"]["path"])
    require(shortlist.get("status")=="SOURCE_CANDIDATES_ONLY_NOT_SCIENTIFIC_ADMISSION"
        and shortlist.get("original_context_count")==RISK_CONTEXT_COUNT
        and shortlist.get("original_family_node_count")==RISK_CONTEXT_COUNT*RISK_FAMILY_COUNT
        and shortlist.get("original_maximum_weighted_units")==RISK_CONTEXT_COUNT*RISK_UPPER
        and audit.get("status")=="METADATA_AUDIT_COMPLETE_NO_ESTIMATION",
        "EXACT_METADATA_ONLY_AUDIT_REQUIRED")
    rows=shortlist["contexts"]
    require(len(rows)==RISK_CONTEXT_COUNT and {r["context_id"] for r in rows}==set(contexts),"EXACT214_AUDIT_PARTITION_REQUIRED")
    for r in rows:
        index,context=contexts[r["context_id"]]
        require(r["original_context_index"]==index and r["frozen_context_payload_sha256"]==context["context_id"]
            and r["original_family_node_payload_sha256"]==node_hashes[r["context_id"]]
            and r["decision_at"]==context["decision_at"] and r["maximum_weighted_units"]==RISK_UPPER
            and r.get("dispatch_allowed_by_this_audit") is False,"CANDIDATE_PAYLOAD_OR_FAMILY_AXIS_CHANGED")
    selected=qualification["qualified_context_ids"]
    require(selected and len(set(selected))==len(selected) and set(selected)<=set(contexts)
        and selected==review["qualified_context_ids"],"CLOSED_QUALIFIED_CONTEXT_LIST_REQUIRED")
    candidates={r["context_id"] for r in rows if r["metadata_candidate_families"]}
    require(set(selected)<=candidates,"SOURCE_PENDING_CONTEXT_MUST_REMAIN_UNENTERED")
    ordered=sorted(selected,key=lambda cid:contexts[cid][1]["decision_at"])
    require(selected==ordered,"CHRONOLOGICAL_FIXED_CONTEXT_ORDER_REQUIRED")
    pending=set(contexts)-set(selected)
    require(set(qualification["pending_context_ids"])==pending
        and len(qualification["pending_context_ids"])==len(pending),"EXACT_READY_PENDING_PARTITION_REQUIRED")
    daily={r["decision_at"]:r for r in value["decision_to_context"]}
    require(all(contexts[cid][1]["decision_at"] in daily for cid in selected),"FROZEN_DECISION_CONTEXT_REQUIRED")
    return [(cid,daily[contexts[cid][1]["decision_at"]]) for cid in ordered],pending


def risk_dispatch_states(journal,plan,recovery_manifest=None):
    dispositions={}
    for cid,context in plan:
        node="RISK_REFRESH|"+context["decision_at"][:10];state=journal.status(node)
        if recovery_manifest is not None and node in RISK_ENVIRONMENT_GROUPS:
            rows=journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes WHERE node_id=? OR node_id LIKE ? ORDER BY node_id",(node,node+"|UNIT|%")).fetchall()
            require([list(row) for row in rows]==recovery_manifest["groups"][node]["original_rows"],"EXACT_FOUR_ENVIRONMENT_GROUP_CURRENT_ROWS_REQUIRED")
            dispositions[cid]=state["status"];continue
        require(state["status"]!="STARTED","RISK_STARTED_SCIENTIFIC_REPLAY_FORBIDDEN")
        units=[journal.status(node+"|UNIT|"+str(i).zfill(2)) for i in range(RISK_UPPER)]
        if state["status"]=="NAMED":
            require(state["entered"]==0 and state["identity"] is None and state["artifact"] is None
                and all(u["status"]=="NAMED" and u["entered"]==0 and u["identity"] is None and u["artifact"] is None for u in units),
                "PARTIAL_RISK_PREFIX_WITHOUT_TERMINAL_NO_RETRY")
            require(not journal.db.execute("SELECT 1 FROM events WHERE node_id=? OR node_id LIKE ? LIMIT 1",(node,node+"|UNIT|%")).fetchone(),
                "NAMED_RISK_GROUP_HAS_PRIOR_SCIENTIFIC_EVENTS")
        else:
            require(state["status"] in TERMINAL and not any(u["status"]=="STARTED" for u in units),"UNKNOWN_RISK_TERMINAL_DISPOSITION")
            if state["status"] in ("COMPLETE","FAILED","SOURCE_NOT_TESTABLE"):
                require(all(u["status"] in ("COMPLETE","FAILED","NOT_REQUIRED") for u in units),
                    "TERMINAL_RISK_GROUP_HAS_UNCLOSED_UPPER_SLOTS")
        dispositions[cid]=state["status"]
    return dispositions


def execute_risk(run,phase_name=None,recovery_admission_ref=None):
    run=Path(run).resolve();phase_name=risk_phase_namespace(run,phase_name)
    capture_stage="risk_pending_firstentry_execute_r1" if phase_name==RISK_PENDING_NAME else "risk_environment_execute_r4" if phase_name==RISK_ENVIRONMENT_NAME else "risk_execute_r4" if phase_name==RISK_NAME else "risk_reboot_named_execute_r1" if phase_name==RISK_REBOOT_NAME else "risk_reboot_named_execute_r2" if phase_name==RISK_SECOND_NAME else "risk_reboot_named_execute_r3"
    with risk_runtime_owners(capture_stage=capture_stage) as (controller,workflow,_):
        with workflow._worker_lock(run):
            manifest,review,review_ref,design,qualification=load_risk_authority(run,phase_name)
            with controller.engineering_source_configuration(manifest["engineering_source_configuration_ref"]):
                validate_existing_sqlite(run,design);journal=controller._TaskLedger(run)
                try:
                    before=ledger_snapshot(journal,run,environment_manifest_ref=ref(RISK_ENVIRONMENT_MANIFEST) if phase_name==RISK_ENVIRONMENT_NAME else None,environment_postterminal_ref=manifest["environment_postterminal_ref"] if phase_name==RISK_PENDING_NAME else None)
                    before_events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                    before_authority=journal.db.execute("SELECT design_sha256 FROM authority").fetchall()
                    require(public_snapshot(before)==review["ledger_prestate"],"TERMINAL_BOUND_RISK_LEDGER_CHANGED")
                    account_proof=read(manifest["engineering_account_completion_ref"]["path"])
                    require(account_proof["core_account_states"]=={cid:journal.status("ACCOUNT|"+cid)["status"] for cid in account_proof["applicable_core_account_ids"]}
                        and all(isinstance(v,str) and v in TERMINAL for v in account_proof["core_account_states"].values()),"NATURAL_ACCOUNT_PROOF_AND_CURRENT_SOLE_LEDGER_CHANGED")
                    for node in design["dag"]["nodes"]:
                        if node["kind"] in ("SCALER","ESTIMATOR","CALIBRATOR","META_MODEL","META_SCALER","META_TARGET_SCALE"):
                            require(journal.status(node["node_id"])["status"] in TERMINAL,"PRIOR_ALPHA_LEARNED_NODES_NOT_TERMINAL")
                    plan,pending=risk_dispatch_plan(workflow,controller,run,manifest,review,qualification)
                    recovery_refs=risk_environment_recovery_refs(recovery_admission_ref,review) if phase_name==RISK_ENVIRONMENT_NAME else None
                    require(recovery_admission_ref is None or phase_name==RISK_ENVIRONMENT_NAME,"NO_GENERIC_RECOVERY_ARGUMENT")
                    recovery_manifest=read(RISK_ENVIRONMENT_MANIFEST) if recovery_refs is not None else None
                    dispositions=risk_dispatch_states(journal,plan,recovery_manifest)
                    if phase_name==RISK_PENDING_NAME:
                        require(len(plan)==212 and len(pending)==2
                            and {cid for cid,status in dispositions.items() if status=="COMPLETE"}==set(qualification["original_qualified_reuse_context_ids"])
                            and {cid for cid,status in dispositions.items() if status=="NAMED"}==set(qualification["supplemental_pristine_first_entry_context_ids"])
                            and set(dispositions.values())=={"COMPLETE","NAMED"}
                            and workflow._risk_environment_paid_attempts(journal)==7174,
                            "EXACT190_COMPLETE_REUSE22_PRISTINE_FIRST2_PENDING7174_PAID")
                    if recovery_manifest is not None:
                        require(public_snapshot(before)=={key:recovery_manifest["ledger_prestate"][key] for key in ("nodes_sha256","events_sha256","event_count")}
                            and before_authority==[(sha(run/"DESIGN_FREEZE.json"),)]
                            and list(dispositions.values()).count("COMPLETE")==173 and list(dispositions.values()).count("NAMED")==13
                            and list(dispositions.values()).count("FAILED")==3 and list(dispositions.values()).count("STARTED")==1
                            and workflow._risk_environment_paid_attempts(journal)==6485,"EXACT173_REUSE_FOUR_ENVIRONMENT_13FIRST_6485PAID_REQUIRED")
                    if phase_name==RISK_REBOOT_NAME:
                        require(public_snapshot(before)==read(RISK_REBOOT_DISPOSITION)["ledger_poststate"]
                            and list(dispositions.values()).count("NAMED")==163
                            and list(dispositions.values()).count("COMPLETE")==26
                            and list(dispositions.values()).count("FAILED")==1,"EXACT_163_FIRST_26_REUSE_ONE_ENVIRONMENT_FAILURE_REQUIRED")
                    if phase_name==RISK_SECOND_NAME:
                        require(public_snapshot(before)==read(RISK_SECOND_DISPOSITION)["ledger_poststate"]
                            and list(dispositions.values()).count("NAMED")==129
                            and list(dispositions.values()).count("COMPLETE")==59
                            and list(dispositions.values()).count("FAILED")==2,"EXACT_129_FIRST_59_REUSE_TWO_ENVIRONMENT_FAILURES_REQUIRED")
                    if phase_name==RISK_THIRD_NAME:
                        require(public_snapshot(before)==read(RISK_THIRD_DISPOSITION)["ledger_poststate"]
                            and list(dispositions.values()).count("NAMED")==95
                            and list(dispositions.values()).count("COMPLETE")==92
                            and list(dispositions.values()).count("FAILED")==3,"EXACT_95_FIRST_92_REUSE_THREE_ENVIRONMENT_FAILURES_REQUIRED")
                    # Unselected source-pending dates remain pristine, not typed failures.
                    selected_days={context["decision_at"][:10] for _,context in plan}
                    for node in design["dag"]["nodes"]:
                        if node["kind"] in ("RISK_REFRESH_DISPATCH","RISK_LEARNED_UNIT") and node["day"] not in selected_days:
                            state=journal.status(node["node_id"])
                            require(state["status"]=="NAMED" and state["entered"]==0 and state["identity"] is None and state["artifact"] is None,
                                "SOURCE_PENDING_CONTEXT_HISTORY_MUST_REMAIN_UNENTERED")
                            require(not journal.db.execute("SELECT 1 FROM events WHERE node_id=? OR node_id LIKE ? LIMIT 1",("RISK_REFRESH|"+node["day"],"RISK_REFRESH|"+node["day"]+"|UNIT|%")).fetchone(),"PENDING_CONTEXT_HAS_PRIOR_HISTORY")
                    full=risk_input_owner();controller.worker_runtime(run)
                    with risk_metadata_overlay(full,manifest) as provenance:
                        folder=run/"continuation"
                        marker=append_json(folder/(phase_name+"_STARTED.json"),dict(research_id=ID,phase=RISK_PENDING_PHASE if phase_name==RISK_PENDING_NAME else RISK_PHASE,
                            review_ref=review_ref,phase_configuration_ref=ref(risk_configuration_path(run,phase_name)),runtime_entry_ref=ref(__file__),
                            ledger_prestate=public_snapshot(before),qualified_context_ids=[cid for cid,_ in plan],scientific_retries=0))
                        try:
                            for cid,context in plan:
                                previous=dispositions[cid]
                                recovery_node="RISK_REFRESH|"+context["decision_at"][:10]
                                is_environment=recovery_refs is not None and recovery_node in RISK_ENVIRONMENT_GROUPS
                                if previous in ("FAILED","SOURCE_NOT_TESTABLE","BLOCKED_DEPENDENCY") and not is_environment:continue
                                # Original metadata/source/axis guard before dispatcher BEGIN.
                                # The owner still independently validates and supplies ACK71
                                # before its original numeric loader projection.
                                pin(manifest["qualification_ref"]);pin(manifest["audit_ref"]);pin(manifest["shortlist_ref"])
                                full._fixed_policy_risk_binding(run,context)
                                if is_environment:
                                    workflow.risk_refresh_once(run,journal,context,full.load_fixed_policy_risk_inputs,recovery=recovery_refs)
                                else:workflow.risk_refresh_once(run,journal,context,full.load_fixed_policy_risk_inputs)
                                require(journal.status("RISK_REFRESH|"+context["decision_at"][:10])["status"] in TERMINAL,
                                    "ORIGINAL_RISK_DISPATCH_NOT_TERMINAL")
                            after=ledger_snapshot(journal,run,environment_postterminal_ref=manifest["environment_postterminal_ref"] if phase_name==RISK_PENDING_NAME else None)
                            first_days={context["decision_at"][:10] for cid,context in plan if dispositions[cid]=="NAMED" or (recovery_refs is not None and "RISK_REFRESH|"+context["decision_at"][:10] in RISK_ENVIRONMENT_GROUPS)}
                            allowed={n["node_id"] for n in design["dag"]["nodes"] if n["kind"] in ("RISK_REFRESH_DISPATCH","RISK_LEARNED_UNIT") and n["day"] in first_days}
                            require({r[0]:r for r in before["rows"] if r[0] not in allowed}=={r[0]:r for r in after["rows"] if r[0] not in allowed},"NON_FIRST_RISK_STATE_CHANGED")
                            after_events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                            require(after_events[:len(before_events)]==before_events and all(event[1] in allowed for event in after_events[len(before_events):]),"NON_FIRST_RISK_OR_OLD_HISTORY_EVENT_CHANGED")
                            require(journal.db.execute("SELECT design_sha256 FROM authority").fetchall()==before_authority,"ORIGINAL_SOLE_LEDGER_AUTHORITY_CHANGED")
                            validate_existing_sqlite(run,design)
                            if phase_name==RISK_PENDING_NAME:require(workflow._risk_environment_paid_attempts(journal)<=8736<=15194,"PENDING22_CUMULATIVE7174_PLUS22X71_CAP")
                            if recovery_refs is not None:require(workflow._risk_environment_paid_attempts(journal)<=15194,"CUMULATIVE_ACTUAL_RISK_BUDGET_CHANGED")
                            completion=dict(research_id=ID,status="BOUNDED_QUALIFIED_RISK_CONTEXTS_TERMINAL",all_task_complete=False,
                                fixed_contexts=RISK_CONTEXT_COUNT,requested_families=RISK_FAMILY_COUNT,weighted_unit_ceiling=RISK_CONTEXT_COUNT*RISK_UPPER,
                                qualified_context_count=len(plan),source_pending_context_count=len(pending),numeric_family_qualification_claimed=False,
                                scientific_retries=0,metadata_helper_overlay=provenance)
                            append_json(folder/(phase_name+"_COMPLETE.json"),dict(research_id=ID,phase=RISK_PENDING_PHASE if phase_name==RISK_PENDING_NAME else RISK_PHASE,marker_ref=marker,
                                completion=completion,ledger_poststate=public_snapshot(after),outer_feedback=False))
                            return completion
                        except BaseException:
                            append_json(folder/(phase_name+"_FAILURE.json"),dict(research_id=ID,phase=RISK_PENDING_PHASE if phase_name==RISK_PENDING_NAME else RISK_PHASE,marker_ref=marker,
                                error=traceback.format_exc(),scientific_retries=0))
                            raise
                finally:journal.db.close()



TAIL_PHASES=("post-risk-policy","remaining-accounts","shared-evidence-and-report")

TAIL_BASE_R4_SHA="b02bf73fcbeb6f517c2caca27f239e6432f46e9cdf5dcf4408f9e2625895e77e"

TAIL_STATS_OWNER_SHA="6374ea14234dc153ffd26e3ae91e104c2f3527755dce58976b9df43fc2adad31"

TAIL_ORIGINAL_WORKFLOW_SHA="4e989ebb783ce4b7c0f231417afee1e1357a6b38c94f78ddd60801c7ad72160d"

TAIL_CORE_IDS=("RAW","RIDGE","HGB","LAMBDAMART","FUSION_equal")

TAIL_R7_REF=dict(path=str(CACHE/"proposals/account_final_owner_projection_R1.py"),sha256="f9a020cfff567b2e9ff17d6a0a80c933e36f291ce3491abeba6ee50e2bb838fb")

TAIL_SOURCE_R2_REF=dict(path=str(RUN/"ENGINEERING_SOURCE_CORRECTION_R2.json"),sha256=RISK_SOURCE_R2_SHA)

def tail_name(phase):
    require(phase in TAIL_PHASES,"EXACT_FIXED_TAIL_PHASE_REQUIRED")
    return "POST_RISK_"+phase.replace("-","_").upper()+"_R1"


def tail_pending22_predecessor(cfg):
    """Actual pending22 terminal first; immutable ENV history remains a separate envelope."""
    require(cfg.get("schema")=="FULL_SELECTOR_FIXED_POST_PENDING22_POLICY_TAIL_CONFIGURATION_R1"
        and cfg.get("phase")==TAIL_PHASES[0],"ONLY_POST_PENDING22_FIRST_POLICY_PREDECESSOR")
    folder=RUN/"continuation"
    actual={"complete":(folder/(RISK_PENDING_NAME+"_COMPLETE.json"),
            "7ab7a0c466114f4dd623b3b579c2ff9d7d4204cfa3e72a8bedecfec4986cb403"),
        "os":(folder/(RISK_PENDING_NAME+"_OS_EXIT_RECEIPT_R1.json"),
            "54483eef6099d400bf0b36f4df0d6b3c0b00a4b97fed51b1ead30f93b7cada23"),
        "root_terminal":(RUN/"maintenance/FIXED214_PENDING22_ACTUAL_SCIENTIFIC_NATURAL_TERMINAL_ROOT_RECEIPT_R1.json",
            "d05d97ceea916ef3ca0ec5946c398ba0b97f03a85a1fd9b84a8a7ab0b8a3543f"),
        "audit":(CACHE/"proposals/FIXED214_PENDING22_ACTUAL_FIRSTENTRY_TERMINAL_METADATA_AUDIT_R1.json",
            "7ce24708ad87b0d31df21090107da5faf98cd8ebcbe8d3525889828f0ac2e52b"),
        "configuration":(folder/(RISK_PENDING_NAME+"_CONFIGURATION.json"),
            "c5e9f293e7af40e7b6756e1c75e9058673e5845284b3aca5505762a47d9a4e1c")}
    values={k:dict(path=str(p.resolve()),sha256=h) for k,(p,h) in actual.items()}
    for k,(p,h) in actual.items():pin(values[k],p)
    for key,k in (("prior_terminal_ref","complete"),("prior_audit_ref","audit"),
            ("pending_risk_configuration_ref","configuration")):
        require(risk_reference_equal(cfg[key],values[k]),"EXACT_ACTUAL_PENDING22_REF_REQUIRED:"+key)
    complete=read(actual["complete"][0]);osr=read(actual["os"][0]);audit=read(actual["audit"][0])
    historical=read(actual["configuration"][0])
    require(set(complete)=={"research_id","phase","marker_ref","completion","ledger_poststate","outer_feedback"}
        and complete["research_id"]==ID and complete["phase"]==RISK_PENDING_PHASE
        and complete["outer_feedback"] is False,"ACTUAL_PENDING22_COMPLETE_ENVELOPE_REQUIRED")
    completion=complete["completion"]
    require(completion["status"]=="BOUNDED_QUALIFIED_RISK_CONTEXTS_TERMINAL"
        and completion["fixed_contexts"]==214 and completion["qualified_context_count"]==212
        and completion["source_pending_context_count"]==2 and completion["requested_families"]==18
        and completion["weighted_unit_ceiling"]==15194 and completion["scientific_retries"]==0
        and completion["all_task_complete"] is False and completion["numeric_family_qualification_claimed"] is False,
        "ACTUAL_PENDING22_METADATA_TERMINAL_IS_NOT_ALL_FAMILY_NUMERIC_PASS")
    marker=read(pin(complete["marker_ref"],folder/(RISK_PENDING_NAME+"_STARTED.json")))
    require(marker["phase"]==RISK_PENDING_PHASE and marker["scientific_retries"]==0
        and risk_reference_equal(marker["phase_configuration_ref"],values["configuration"])
        and marker["runtime_entry_ref"]==historical["runtime_entry_ref"],"REAL_PENDING22_MARKER_CONFIGURATION_REQUIRED")
    require(len(osr)==20 and osr["schema"]=="FIXED214_PENDING22_SCIENCE_OS_EXIT_R1"
        and osr["wait_for_exit_observed"] is True and type(osr["exit_code"]) is int and osr["exit_code"]==0
        and osr["terminated_by_agent"] is False and len(osr["before_process_levels"])==2
        and osr["after_process_levels"]==[] and risk_reference_equal(osr["actual_output_ref"],values["complete"])
        and risk_reference_equal(osr["phase_configuration_ref"],values["configuration"])
        and osr["runtime_entry_ref"]["sha256"]==historical["runtime_entry_ref"]["sha256"],
        "ACTUAL_PENDING22_STRICT20_NATURAL_ZERO_EXIT_REQUIRED")
    require(not (folder/(RISK_PENDING_NAME+"_FAILURE.json")).exists(),"PENDING22_FAILED_SCIENCE_CANNOT_BE_COMPLETE")
    scope=audit["limits"]
    require(audit["status"]=="PASS" and audit["actual_read_only_audit"] is True
        and audit["workers_naturally_exited"] is True and risk_reference_equal(audit["complete_ref"],values["complete"])
        and complete["ledger_poststate"]==audit["ledger_poststate"]==cfg["ledger_prestate"]
        and cfg["ledger_prestate"]["event_count"]==18441 and scope["native_exit_code"]==0
        and scope["original190_parent_exactreuse_metadata"] is True and scope["new22_parent_metadata_COMPLETE"] is True
        and scope["pending_pristine_contexts"]==2 and scope["pending_pristine_node_count"]==144
        and scope["actual_pending_noevents_noidentity_noartifact_noerror_no_partial_model"] is True
        and scope["cumulative_paid_attempts"]==8054 and scope["unique_paid_risk_units"]==7949
        and scope["cumulative_environment_reentry_charges"]==105 and scope["scientific_failed_retries"]==0
        and scope["artifact_bytes_verified"] is False and scope["numeric_PSD_or_all_family_success_claim"] is False
        and scope["all_task_complete_claim"] is False,"ACTUAL_PENDING22_AUDIT_AND_PRESTATE_REQUIRED")
    require(cfg["prior_independent_acceptance_ref"]["sha256"]=="7915585998ac2ac8ceadb1099f0b5e335939fa13b25bcdc692e24b8cd5699981"
        and cfg["source_dependency_disposition_ref"]["sha256"]=="912e0bbfd49656c5c1773d24fad9af9a4e49fcd52ae064001e26103614730ba8"
        and cfg["prior_root_last_ref"]["sha256"]=="f51431a3064ee461637206bcc5146162647841cac464f3a0f405a1f0dd3e8cdc",
        "ONLY_ACTUALLY_WRITTEN_INDEPENDENT_PENDING22_TRANSPORT_REFS")
    peer=read(pin(cfg["prior_independent_acceptance_ref"],CACHE/"proposals/FIXED214_PENDING22_INDEPENDENT_ACTUAL_TERMINAL_AND_FINAL_SOURCE_ACCEPTANCE_R1.json"))
    require(peer["schema"]=="FULL_SELECTOR_PENDING22_INDEPENDENT_ACTUAL_TERMINAL_AND_FINAL_SOURCE_ACCEPTANCE_R1"
        and peer["research_id"]==ID and peer["status"]=="PASS"
        and all(peer.get(k) is True for k in ("independent_from_root_writer","independent_from_entry_writer","independent_from_dispatch_writer"))
        and risk_reference_equal(peer["approved_actual_terminal_ref"],values["root_terminal"])
        and risk_reference_equal(peer["approved_actual_audit_ref"],values["audit"])
        and risk_reference_equal(peer["approved_actual_scientific_COMPLETE_ref"],values["complete"])
        and risk_reference_equal(peer["approved_actual_OS_ref"],values["os"])
        and risk_reference_equal(peer["approved_current_configuration_ref"],values["configuration"])
        and peer["approved_final_source_proof_ref"]==cfg["source_dependency_disposition_ref"],
        "REAL_INDEPENDENT_PENDING22_TERMINAL_AND_FINAL_SOURCE_PROOF_REQUIRED")
    pin(peer["approved_final_source_candidate_ref"],CACHE/"source_facts_2019/PENDING2_ORIGINAL_FINAL_SOURCE_DISPOSITION_CANDIDATE_R1.json")
    proof=read(pin(cfg["source_dependency_disposition_ref"],CACHE/"proposals/FIXED214_PENDING2_ORIGINAL_FINAL_SOURCE_DISPOSITION_R1.json"))
    require(proof["schema"]=="FULL_SELECTOR_ORIGINAL_RISK_SOURCE_DEPENDENCY_FINAL_DISPOSITION_R1"
        and proof["status"]=="PASS_INDEPENDENT_FINAL_SOURCE_NOT_TESTABLE" and proof["research_id"]==ID
        and proof["independent_from_dispatch_writer"] is True and proof["bounded_authorized_source_work_complete"] is True
        and proof["scientific_retry_authorized"] is False,"DISTINCT_FINAL_SOURCE_DISPOSITION_NOT_SCIENTIFIC_RETRY")
    root=read(pin(cfg["prior_root_last_ref"],RUN/"maintenance/FIXED214_PENDING22_ROOT_LAST_ACTUAL_TERMINAL_AND_FINAL_SOURCE_TRANSPORT_R1.json"))
    require(root["schema"]=="FULL_SELECTOR_PENDING22_ROOT_LAST_ACTUAL_TERMINAL_AND_FINAL_SOURCE_TRANSPORT_R1"
        and root["research_id"]==ID and root["actual_complete_ref"]==cfg["prior_terminal_ref"]
        and root["actual_audit_ref"]==cfg["prior_audit_ref"]
        and root["independent_actual_terminal_and_final_source_acceptance_ref"]==cfg["prior_independent_acceptance_ref"]
        and root["source_dependency_disposition_ref"]==cfg["source_dependency_disposition_ref"]
        and root["pending_risk_configuration_ref"]==cfg["pending_risk_configuration_ref"]
        and root["scientific_retry_authorized"] is False and root["scientific_or_numeric_or_all_task_complete_claimed"] is False,
        "ROOT_LAST_ACTUAL_PENDING22_TRANSPORT_REQUIRED")
    for key,h,name in (("prior_entry_custody_ref",historical["runtime_entry_ref"]["sha256"],"full_selector_engineering_continuation.py"),
            ("prior_source_custody_ref",historical["source_configuration_ref"]["sha256"],"ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json")):
        require(cfg[key]["sha256"]==h,"ACTUAL_PENDING22_SOURCE_CUSTODY_IDENTITY_REQUIRED:"+key)
        pin(cfg[key],RUN/"source_corrections/POST_PENDING22_FIRST_POLICY_OWNER_R1"/(name+"."+h+".before"))
    require(historical["schema"]=="FULL_SELECTOR_FIXED214_PENDING_SUPPLEMENT_RISK_PHASE_CONFIGURATION_R1"
        and historical["phase"]==RISK_PENDING_PHASE and historical["runtime_entry_ref"]["sha256"]=="ff756a043da3731382c668a0b79bfdace6e6040d2bfceb976113f2419c696692"
        and historical["source_configuration_ref"]["sha256"]=="99c46864abcc16f9f8c1399a0eb66f2121c8b74a184093e7d62ecf93b36110ee"
        and historical["environment_postterminal_ref"]==cfg["environment_postterminal_ref"]
        and historical["risk_configuration_ref"]==cfg["risk_configuration_ref"],
        "UNCHANGED_PENDING22_HISTORY_ENVELOPE_REQUIRED")
    return tail_postloop_predecessor(historical)


def tail_postloop_predecessor(cfg):
    """Consume the exact independently accepted metadata closure without SCI promotion."""
    if cfg.get("schema")=="FULL_SELECTOR_FIXED_POST_PENDING22_POLICY_TAIL_CONFIGURATION_R1":
        return tail_pending22_predecessor(cfg)
    folder=RUN/"continuation"
    fixed={"prior_terminal_ref":(folder/"RISK_ENVIRONMENT_REPLAY_CONTINUATION_R4_POSTLOOP_METADATA_CLOSURE_R1.json",
        "1b320e35779e697737419d6fc5509835a01705cabd19b4b128c6d8149b457c13"),
        "prior_independent_acceptance_ref":(CACHE/"proposals/FIXED214_ENVIRONMENT_POSTLOOP_INDEPENDENT_ACTUAL_METADATA_ACCEPTANCE_R1.json",
        "849b3cd354bd77b3cb333fbc5759a2aff574a8eecc8522b6eae59171eec0c08c"),
        "prior_root_last_ref":(RUN/"maintenance/FIXED214_ENVIRONMENT_POSTLOOP_METADATA_CLOSURE_ROOT_LAST_ACTUAL_WRITE_R1.json",
        "6e36e1bb9de9f2bbeaace9bb352068cceac694995a0850ebfede682e0a2c7acc"),
        "environment_postterminal_ref":(RUN/"maintenance/FIXED214_ENVIRONMENT_RECOVERY_ACTUAL_POSTLOOP_NATURAL_FAILURE_BOUNDARY_R2.json",
        "ee7301cc927c2b8b7aabb403e9b23617fe7bc4849c1c058354b6bb5645803078")}
    for key,(path,h) in fixed.items():
        require(isinstance(cfg[key],dict) and set(cfg[key])=={"path","sha256"}
            and Path(cfg[key]["path"]).resolve()==path.resolve() and cfg[key]["sha256"]==h,
            "EXACT_TYPED_POSTLOOP_REF_REQUIRED:"+key)
        pin(cfg[key],path)
    closure=read(fixed["prior_terminal_ref"][0]);peer=read(fixed["prior_independent_acceptance_ref"][0])
    root=read(fixed["prior_root_last_ref"][0])
    require(len(closure)==19 and closure["schema"]=="FULL_SELECTOR_FIXED_ENVIRONMENT_POSTLOOP_METADATA_CLOSURE_R1"
        and closure["research_id"]==ID and closure["phase"]==RISK_PHASE
        and closure["status"]=="ACTUAL_NATURAL_FAILURE_POSTLOOP_METADATA_TERMINAL_CLOSURE"
        and closure["scientific_retries"]==0 and closure["all_task_complete"] is False
        and closure["outer_feedback"] is False,"DISTINCT_POSTLOOP_METADATA19_REQUIRED")
    require(peer["schema"]=="FULL_SELECTOR_FIXED214_ENVIRONMENT_POSTLOOP_INDEPENDENT_ACTUAL_METADATA_ACCEPTANCE_R1"
        and peer["research_id"]==ID and peer["status"]=="PASS"
        and all(peer.get(k) is True for k in ("independent_from_root_writer","independent_from_entry_writer","independent_from_dispatch_writer"))
        and peer["approved_postloop_metadata_closure_payload"]==closure
        and peer["approved_postloop_metadata_closure_raw_bytes_sha256"]==cfg["prior_terminal_ref"]["sha256"]
        and peer["actual_boundary_ref"]==cfg["environment_postterminal_ref"]
        and peer["actual_metadata_audit_ref"]==closure["actual_metadata_audit_ref"],
        "ACTUAL_INDEPENDENT_POSTLOOP_PAYLOAD_REQUIRED")
    pin(peer["approved_postloop_metadata_closure_candidate_ref"])
    require(root["formal_postloop_metadata_closure_ref"]==cfg["prior_terminal_ref"]
        and root["independent_actual_metadata_acceptance_ref"]==cfg["prior_independent_acceptance_ref"]
        and root["original_SCI_COMPLETE_created"] is False
        and root["scientific_execution_or_reexecution_authorized"] is False
        and root["source_or_numeric_or_whole_cache_admission_granted"] is False,
        "ACTUAL_ROOT_LAST_DISTINCT_METADATA_TRANSPORT_REQUIRED")
    scope=closure["terminal_scope"]
    require(scope["native_worker_exit_code"]==1 and scope["scientific_COMPLETE_receipt_created"] is False
        and scope["component_FAILED_retained"]==68 and scope["pending_contexts_pristine"]==24
        and scope["cumulative_paid_attempts"]==7174 and scope["legacy_unentered_upper_preserved"]==118
        and scope["artifact_bytes_verified"] is False and scope["risk_scientific_reexecution_authorized"] is False
        and scope["fresh_source_or_numeric_PSD_family_admission_granted"] is False,
        "POSTLOOP_SCOPE_IS_NOT_SCIENTIFIC_ADMISSION")
    require(not (folder/"RISK_ENVIRONMENT_REPLAY_CONTINUATION_R4_COMPLETE.json").exists(),
        "NATURAL_FAILURE_MUST_NOT_BECOME_SCI_COMPLETE")
    for key in ("marker_ref","actual_failure_ref","actual_os_ref","phase_configuration_ref","phase_acceptance_ref",
            "environment_admission_ref","actual_boundary_ref","actual_metadata_audit_ref"):
        pin(closure[key])
    require(closure["phase_configuration_ref"]==cfg["risk_configuration_ref"]
        and closure["actual_metadata_audit_ref"]==cfg["prior_audit_ref"]
        and closure["actual_boundary_ref"]==cfg["environment_postterminal_ref"]
        and closure["ledger_poststate"]==cfg["ledger_prestate"],"TYPED_PREDECESSOR_CONFIGURATION_REQUIRED")
    # Only these two known runtime envelopes are transported through preserved bytes.
    for key,value_key,h,name in (("prior_entry_custody_ref","runtime_entry_ref",
            "9723e3aba79922b5fa612e26dcb5dec1eb70f6539d7c8bca813ca6e85d1e41f3","full_selector_engineering_continuation.py"),
        ("prior_source_custody_ref","source_configuration_ref",
            "7a06fcb01131fc4bb63cf88ca5b132db30278167006bee84d9cf49429ebda376","ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json")):
        path=RUN/"source_corrections/POST_RISK_CURRENT_ENV_OWNER_R1"/(name+"."+h+".before")
        require(closure[value_key]["sha256"]==h and cfg[key]["sha256"]==h,"ONLY_EXACT_CURRENT_ENV_BYTE_CUSTODY_ALLOWED")
        pin(cfg[key],path)
    return closure


def tail_historical_risk_source_binding(risk_cfg,tail_cfg):
    """Only the accepted ENV predecessor's immutable metadata crosses this bridge."""
    if tail_cfg.get("schema")==POLICY_REBOOT_SCHEMA:return policy_reboot_historical_binding(risk_cfg,tail_cfg)
    require(isinstance(tail_cfg,dict)
        and ((tail_cfg.get("schema")=="FULL_SELECTOR_FIXED_POST_PENDING22_POLICY_TAIL_CONFIGURATION_R1" and tail_cfg.get("phase")==TAIL_PHASES[0])
             or (tail_cfg.get("schema")=="FULL_SELECTOR_FIXED214_PENDING_SUPPLEMENT_RISK_PHASE_CONFIGURATION_R1" and tail_cfg.get("phase")==RISK_PENDING_PHASE))
        and tail_cfg.get("research_id")==ID
        and tail_cfg.get("runtime_entry_ref")==ref(__file__),"ONLY_EXPLICIT_FIRST_TAIL_METADATA_BRIDGE_ALLOWED")
    value=tail_cfg["risk_configuration_ref"]
    require(set(value)=={"path","sha256"}
        and value["sha256"]=="ab1574c64958c3d9b40586ca884ab639f49f7decb40fc6e58dda9a05bd7e7a66",
        "ONLY_IMMUTABLE_ACTUAL_ENV_CONFIGURATION_ALLOWED")
    historical_path=pin(value,RUN/"continuation/RISK_CONTEXT_PHASE_CONFIGURATION_R1.json")
    require(risk_cfg==read(historical_path),"HISTORICAL_CONFIGURATION_FIELDS_MUST_NOT_BE_REBOUND")
    closure=tail_postloop_predecessor(tail_cfg)
    require(risk_reference_equal(value,closure["phase_configuration_ref"])
        and risk_reference_equal(risk_cfg["runtime_entry_ref"],closure["runtime_entry_ref"])
        and risk_reference_equal(risk_cfg["engineering_source_configuration_ref"],closure["source_configuration_ref"]),
        "ACTUAL_OLD_ENV_CONFIGURATION_AND_TYPED_CLOSURE_REQUIRED")
    pin(risk_cfg["current_entry_custody_ref"],RISK_C6_CUSTODY)
    require(risk_cfg["current_entry_custody_ref"]["sha256"]==RISK_C6_SHA,
        "ORIGINAL_PRE_RISK_C6_CUSTODY_REQUIRED")
    binding,review=risk_current_source_binding()
    require(binding["source_configuration_ref"]==tail_cfg["source_configuration_ref"]
        and review["runtime_entry_ref"]==tail_cfg["runtime_entry_ref"]
        and review["current_entry_custody_ref"]==tail_cfg["prior_entry_custody_ref"]
        and review.get("tail_historical_environment_configuration_ref")==value,
        "CURRENT_INDEPENDENT_SOURCE_MUST_EXPLICITLY_BIND_OLD_ENV_METADATA")
    if tail_cfg["phase"]==RISK_PENDING_PHASE:
        require(review.get("pending_firstentry_historical_environment_configuration_ref")==value
            and review.get("pending_firstentry_metadata_supplement_ref")==tail_cfg["metadata_supplement_ref"]
            and review.get("pending_firstentry_independent_metadata_supplement_review_ref")==tail_cfg["independent_metadata_supplement_review_ref"],
            "CURRENT_SOURCE_EXPLICIT_PENDING_FIRSTENTRY_METADATA_HISTORY_SCOPE")
    if tail_cfg["phase"]==TAIL_PHASES[0]:
        require(review.get("tail_completed_pending22_configuration_ref")==tail_cfg["pending_risk_configuration_ref"]
            and review.get("tail_completed_pending22_terminal_ref")==tail_cfg["prior_terminal_ref"]
            and review.get("tail_completed_pending22_independent_acceptance_ref")==tail_cfg["prior_independent_acceptance_ref"],
            "CURRENT_SOURCE_EXPLICIT_COMPLETED_PENDING22_HISTORY_SCOPE")
    require(binding["source_configuration_ref"]!=risk_cfg["engineering_source_configuration_ref"]
        and review["runtime_entry_ref"]!=risk_cfg["runtime_entry_ref"],
        "HISTORICAL_AND_CURRENT_SOURCE_REFS_MUST_REMAIN_DISTINCT")
    return binding,review


def tail_load_configuration(run,phase,*,pending_risk_firstentry=False):
    """First-policy R5/source transport; later account and STAT entry remain closed."""
    run=Path(run).resolve();require(run==RUN.resolve(),"EXACT_FIXED_TAIL_RUN_REQUIRED")
    pending=pending_risk_firstentry is True and phase==RISK_PENDING_PHASE
    require(pending or (pending_risk_firstentry is False and phase==TAIL_PHASES[0]),"ACCOUNT_AND_STAT_SOURCE_ADAPTATION_NOT_YET_ADMITTED")
    folder=run/"continuation";name=RISK_PENDING_NAME if pending else tail_name(phase);cfg=read(folder/(name+"_CONFIGURATION.json"))
    fields={"schema","research_id","run","phase","runtime_entry_ref","prior_entry_custody_ref","prior_source_custody_ref",
        "base_manifest_ref","original_refs","source_configuration_ref","phase_source_refs","prior_terminal_ref",
        "prior_audit_ref","prior_independent_acceptance_ref","prior_root_last_ref","environment_postterminal_ref",
        "ledger_prestate","preserved_refs","source_dependency_disposition_ref","account_support_ref","account_projection_ref",
        "risk_configuration_ref","core_account_complete_ref"}
    if pending:fields|={"audit_ref","shortlist_ref","qualification_ref","metadata_helper_overlay","metadata_supplement_ref","independent_metadata_supplement_review_ref"}
    if not pending:fields|={"pending_risk_configuration_ref"}
    schema="FULL_SELECTOR_FIXED214_PENDING_SUPPLEMENT_RISK_PHASE_CONFIGURATION_R1" if pending else "FULL_SELECTOR_FIXED_POST_PENDING22_POLICY_TAIL_CONFIGURATION_R1"
    require(set(cfg)==fields and cfg.get("schema")==schema
        and cfg.get("research_id")==ID and cfg.get("phase")==phase and Path(cfg.get("run","")).resolve()==run
        and cfg["runtime_entry_ref"]==ref(__file__),"EXACT_CURRENT_ENV_FIRST_POLICY_CONFIGURATION_REQUIRED")
    for filename,expected in ORIGINAL_PINS.items():
        require(sha(run/filename)==expected,"ORIGINAL_FREEZE_INPUT_OR_GATE_CHANGED:"+filename)
    require(cfg["original_refs"]=={n:ref(run/n) for n in ORIGINAL_PINS},"TAIL_ORIGINAL_AUTHORITY_CHANGED")
    pin(cfg["base_manifest_ref"],folder/"ENGINEERING_CONTINUATION_MANIFEST_R1.json")
    require(cfg["base_manifest_ref"]["sha256"]==R3_MANIFEST_SHA,"IMMUTABLE_SINGLE_BASE_MANIFEST_REQUIRED")
    tail_postloop_predecessor(cfg)
    binding,source_review=risk_current_source_binding()
    require(binding["source_configuration_ref"]==cfg["source_configuration_ref"]
        and source_review["current_entry_custody_ref"]==cfg["prior_entry_custody_ref"],
        "REAL_CURRENT_SOURCE_GUARD_AND_CUSTODY_REQUIRED")
    require(set(cfg["phase_source_refs"])=={"controller","workflow"}
        and cfg["phase_source_refs"]["controller"]==binding["controller_ref"],"EXACT_CURRENT_TAIL_SOURCE_ORIGINS_REQUIRED")
    for value in cfg["phase_source_refs"].values():pin(value)
    require(cfg["phase_source_refs"]["workflow"]["sha256"]=="3e9764be31de959f5ad04029420c6a771f5d6c96ac7c8301f1656496270aec8f",
        "UNCHANGED_CURRENT_ENV_WORKFLOW_MATH_REQUIRED")
    risk_cfg=read(pin(cfg["risk_configuration_ref"],folder/"RISK_CONTEXT_PHASE_CONFIGURATION_R1.json"))
    require(risk_cfg["base_manifest_ref"]==cfg["base_manifest_ref"] and risk_cfg["original_refs"]==cfg["original_refs"]
        and risk_cfg["engineering_account_completion_ref"]==cfg["core_account_complete_ref"],"CURRENT_R5_HISTORY_REQUIRED")
    _,core=risk_prior_completions(run,risk_cfg,tail_metadata_configuration=cfg)
    require(core["review_ref"]==cfg["account_support_ref"] and core["applicable_core_account_ids"]==list(TAIL_CORE_IDS)
        and set(core["core_account_states"].values())=={"FAILED"},"ORIGINAL_SAVED5_FIVE_FAILURES_MUST_STAY_FAILED")
    support=read(pin(cfg["account_support_ref"]));pin(cfg["account_projection_ref"])
    require(support["module_refs"]["r7"]==cfg["account_projection_ref"],"EXACT_ACTUAL_R5_ACCOUNT_PROJECTION_HISTORY_REQUIRED")
    audit=read(pin(cfg["prior_audit_ref"]))
    require(audit.get("status")=="PASS" and audit.get("actual_read_only_audit") is True
        and audit.get("workers_naturally_exited") is True
        and (audit.get("complete_ref") is None if pending else risk_reference_equal(audit.get("complete_ref"),cfg["prior_terminal_ref"]))
        and audit.get("ledger_poststate")==cfg["ledger_prestate"],"ACTUAL_CURRENT_PREDECESSOR_METADATA_AUDIT_REQUIRED")
    require(not any((folder/(name+"_"+s+".json")).exists() for s in ("STARTED","COMPLETE","FAILURE")),
        "TAIL_STAGE_ALREADY_ATTEMPTED_NO_RETRY")
    for value in cfg["preserved_refs"].values():pin(value)
    return cfg,read(run/"DESIGN_FREEZE.json")


def tail_load_authority(run,phase):
    """The fixed config is acyclic; cold runs before this independent review exists."""
    cfg,design=tail_load_configuration(run,phase);folder=Path(run)/"continuation";name=tail_name(phase);cfgpath=folder/(name+"_CONFIGURATION.json")
    review_path=folder/(name+"_ACCEPTANCE.json");review=read(review_path);review_ref=ref(review_path)
    require(review.get("schema")=="FULL_SELECTOR_FIXED_POST_PENDING22_POLICY_TAIL_ACCEPTANCE_R1" and review.get("status")=="PASS"
        and review.get("research_id")==ID and review.get("phase")==phase and review.get("independent_from_entry_writer") is True
        and review.get("all_prior_workers_terminal") is True and review.get("scientific_retry_authorized") is False
        and review.get("configuration_ref")==ref(cfgpath) and review.get("runtime_entry_ref")==cfg["runtime_entry_ref"]
        and review.get("source_configuration_ref")==cfg["source_configuration_ref"]
        and review.get("prior_terminal_ref")==cfg["prior_terminal_ref"]
        and review.get("pending_risk_configuration_ref")==cfg["pending_risk_configuration_ref"]
        and review.get("source_dependency_disposition_ref")==cfg["source_dependency_disposition_ref"]
        and review.get("prior_independent_acceptance_ref")==cfg["prior_independent_acceptance_ref"]
        and review.get("environment_postterminal_ref")==cfg["environment_postterminal_ref"]
        and review.get("ledger_prestate")==cfg["ledger_prestate"],"INDEPENDENT_FIXED_TAIL_FIRST_ENTRY_REVIEW_REQUIRED")
    cold=read(pin(review["actual_cold_ref"]))
    require(cold.get("status")=="PASS" and cold.get("actual_cold") is True and cold.get("synthetic") is False
        and cold.get("configuration_ref")==ref(cfgpath) and cold.get("runtime_entry_ref")==cfg["runtime_entry_ref"]
        and cold.get("source_configuration_ref")==cfg["source_configuration_ref"] and cold.get("scientific_entry_calls")==0
        and cold.get("source_and_sql_unchanged") is True,"ACTUAL_TAIL_ZERO_BUSINESS_COLD_REQUIRED")
    return cfg,review,review_ref,design


def tail_first_boundary(journal,design,phase,events,run):
    """Fixed first-call sets. Existing original five accounts are never retried."""
    nodes=design["dag"]["nodes"];kindset={"HYBRID_ESTIMATOR","HYBRID_SCALER","MEMBER_SOLVE","WHOLE_SET_GATE"}
    if phase==TAIL_PHASES[0]:
        targets=[n["node_id"] for n in nodes if n["kind"] in kindset]
        counts={k:sum(n["kind"]==k for n in nodes) for k in kindset}
        require(counts=={"HYBRID_ESTIMATOR":120,"HYBRID_SCALER":24,"MEMBER_SOLVE":9036,"WHOLE_SET_GATE":2008},
            "EXACT_ORIGINAL144_AND22_RISK_POLICIES_REQUIRED")
    elif phase==TAIL_PHASES[1]:
        originals={"ACCOUNT|"+r for r in TAIL_CORE_IDS}
        accounts={n["node_id"] for n in nodes if n["kind"]=="CONTINUOUS_ACCOUNT"}
        require(len(accounts)==66 and originals<=accounts,"ORIGINAL_ALL66_ACCOUNT_AXIS_REQUIRED")
        require(all(journal.status(n)["status"] in TERMINAL for n in originals),"ORIGINAL_SAVED_FIVE_ACCOUNT_STATES_NOT_TERMINAL")
        targets=sorted(accounts-originals)
        for name in targets:
            require(not (Path(run)/"accounts"/name.split("|",1)[1]).exists(),"TAIL_FIRST_ACCOUNT_OWNER_PREFIX_EXISTS:"+name)
    else:
        targets=[n["node_id"] for n in nodes if n["kind"]=="SHARED_BOOTSTRAP"]
        require(targets==["STATISTICS|SHARED_321"],"EXACT_ORIGINAL_SINGLE_STATISTICS_NODE_REQUIRED")
    for name in targets:
        state=journal.status(name)
        require(state["status"]=="NAMED" and state["entered"]==0 and state["identity"] is None
            and state["artifact"] is None and state["error"] is None,"TAIL_FIRST_TARGET_HAS_SCIENTIFIC_HISTORY:"+name)
        require(not (Path(run)/"models"/(digest(name)+".joblib")).exists(),"TAIL_NAMED_TARGET_HAS_PARTIAL_ARTIFACT:"+name)
    require(not any(event[1] in set(targets) for event in events),"TAIL_FIRST_TARGET_HAS_OLD_EVENT")
    return set(targets)


def tail_policy_prefix_absent(run,controller):
    """The phase is first-only; no publication framework or failed-role reopening."""
    run=Path(run)
    hybrids=["HYBRID_"+p+"_"+f for p,f in controller.HYBRIDS]
    risks=[*("RISK_"+f for f in controller.FAMILIES),*("GATE_"+g for g in controller.GATES)]
    require(len(hybrids)==6 and len(risks)==22,"FIXED_SIX_HYBRID_AND22_ROSTER")
    for role in hybrids+risks:
        names=["policy_"+role+".parquet","policy_"+role+".parquet.json","failure_"+role+".json",
            "risk_decisions_"+role+".json","hybrid_source_refs_"+role+".json","selection_"+role+".json"]
        require(not any((run/"predictions"/name).exists() for name in names),"TAIL_FIRST_POLICY_PREFIX_ALREADY_EXISTS:"+role)
        require(not (run/"predictions/native_oof"/role).exists(),"TAIL_FIRST_HYBRID_OOF_PREFIX_ALREADY_EXISTS:"+role)
        for year in (2024,2025):
            base=run/"predictions/annual_native"/(role+"_"+str(year)+".parquet")
            require(not base.exists() and not Path(str(base)+".json").exists(),"TAIL_FIRST_ANNUAL_PREFIX_ALREADY_EXISTS:"+role)


def tail_source_disposition(journal,workflow,run,cfg,*,apply=False):
    """Additive original block only after irreplaceable source facts are finalized."""
    rows=[n for n in journal.design["dag"]["nodes"] if n["kind"]=="RISK_REFRESH_DISPATCH" and journal.status(n["node_id"])["status"]=="NAMED"]
    if not rows:
        require(cfg["source_dependency_disposition_ref"] is None,"UNNECESSARY_SOURCE_DISPOSITION_CANNOT_ADD_SCOPE")
        return set()
    require(cfg["source_dependency_disposition_ref"] is not None,"PENDING_RISK_FACTS_MUST_BE_FINALLY_REVIEWED_OR_COMPLETED")
    proof=read(pin(cfg["source_dependency_disposition_ref"]))
    require(proof.get("schema")=="FULL_SELECTOR_ORIGINAL_RISK_SOURCE_DEPENDENCY_FINAL_DISPOSITION_R1"
        and proof.get("status")=="PASS_INDEPENDENT_FINAL_SOURCE_NOT_TESTABLE"
        and proof.get("research_id")==ID and proof.get("independent_from_dispatch_writer") is True
        and proof.get("bounded_authorized_source_work_complete") is True and proof.get("scientific_retry_authorized") is False,
        "NO_SOURCE_BLOCK_WITHOUT_FINAL_IRREPLACEABLE_OBJECT_REVIEW")
    contexts=workflow.load_contexts(run)["compact_document"]["contexts"]
    byday={v["decision_at"][:10]:v["context_id"] for v in contexts}
    groups=proof["groups"];expected={n["node_id"] for n in rows}
    require(len(groups)==len(expected) and {g["node_id"] for g in groups}==expected,"EXACT_ORIGINAL_PENDING_CONTEXT_DISPOSITION_REQUIRED")
    allowed=set();planned=[]
    for group in groups:
        name=group["node_id"];day=name.split("|")[1];ids=[name,*[name+"|UNIT|"+str(i).zfill(2) for i in range(71)]]
        require(group["context_id"]==byday[day] and group["original_node_ids"]==ids
            and isinstance(group.get("missing_objects"),list) and bool(group["missing_objects"])
            and isinstance(group.get("reason"),str) and bool(group["reason"]),"EXACT_CONTEXT_UID_SOURCE_MISSING_OBJECTS_REQUIRED")
        require(group.get("source_fact_refs"),"PHYSICAL_FAILED_FACT_WORK_REQUIRED")
        for value in group["source_fact_refs"].values():pin(value)
        for node in ids:
            s=journal.status(node)
            require(s["status"]=="NAMED" and s["entered"]==0 and s["identity"] is None and s["artifact"] is None and s["error"] is None,
                "SOURCE_DISPOSITION_REQUIRES_ZERO_ENTRY:"+node)
            require(not journal.db.execute("SELECT 1 FROM events WHERE node_id=? LIMIT 1",(node,)).fetchone(),
                "SOURCE_DISPOSITION_HAS_OLD_EVENT:"+node)
        require(not any((Path(run)/"risk_states"/(day+suffix)).exists() for suffix in (".joblib",".json",".failure.json")),
            "SOURCE_DISPOSITION_HAS_PARTIAL_RISK_OUTPUT:"+name)
        require(not any((Path(run)/"models"/(digest(node)+".joblib")).exists() for node in ids),
            "SOURCE_DISPOSITION_HAS_ORPHAN_NODE_ARTIFACT:"+name)
        planned.append((ids,group["reason"]));allowed.update(ids)
    # Every group is qualified before the first original additive block.
    if apply:
        for ids,reason in planned:
            for node in ids:journal.block(node,"SOURCE_NOT_TESTABLE:"+reason)
    return allowed


@contextmanager
def tail_account_context(controller,account,run,cfg):
    """Reuse the reviewed original overlay at this current canonical code origin."""
    from types import FunctionType
    path=pin(cfg["account_projection_ref"],Path(TAIL_R7_REF["path"]))
    require(cfg["account_projection_ref"]==TAIL_R7_REF,"EXACT_EXISTING_R7_CONTEXT_REQUIRED")
    spec=importlib.util.spec_from_file_location("fixed_tail_r7_existing_projection",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    require(ref(module.__file__)==TAIL_R7_REF,"ACTUAL_R7_CONTEXT_PHYSICAL_SOURCE_REQUIRED")
    namespace=dict(vars(module));namespace["RUNTIME_ENTRY_REF"]=dict(cfg["runtime_entry_ref"])
    for name in ("require_original_overlay_ast","runtime_view"):
        original=getattr(module,name)
        require(Path(original.__code__.co_filename).resolve()==path,"ORIGINAL_R7_CONTEXT_CODE_ORIGIN_REQUIRED")
        namespace[name]=FunctionType(original.__code__,namespace,original.__name__,original.__defaults__,original.__closure__)
    original=module.fixed_r7_account_overlay.__wrapped__
    require(Path(original.__code__.co_filename).resolve()==path,"ORIGINAL_R7_CONTEXT_GENERATOR_ORIGIN_REQUIRED")
    generator=FunctionType(original.__code__,namespace,original.__name__,original.__defaults__,original.__closure__)
    manifest=read(pin(cfg["base_manifest_ref"]))
    with contextmanager(generator)(sys.modules[__name__],account,manifest) as overlay:
        support=read(pin(cfg["account_support_ref"]))
        require(support.get("status")=="PASS" and support.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_ACCEPTANCE_R1"
            and support.get("engineering_source_configuration_ref")==TAIL_SOURCE_R2_REF,"ORIGINAL_ACCOUNT_SOURCE_ACCEPTANCE_REQUIRED")
        q=read(pin(support["actual_quote_input_qualification_ref"]))
        require(q.get("schema")=="FULL_SELECTOR_CORE_ACCOUNT_QUOTE_INPUT_QUALIFICATION_R1" and q.get("status")=="PASS"
            and q.get("research_id")==ID and q.get("actual_input_binding") is True and q.get("synthetic") is False
            and q.get("phase_configuration_ref")==support["phase_configuration_ref"]
            and q.get("engineering_source_configuration_ref")==TAIL_SOURCE_R2_REF
            and q.get("base_manifest_ref")==cfg["base_manifest_ref"] and q.get("module_refs")==support["module_refs"]
            and q.get("finite_source_refs")==support["finite_source_refs"] and q.get("held_or_selected_filter") is False
            and q.get("source_axis")=="ALL_CURRENT_FULL_U_SOURCE_AXES_PRE2026" and q.get("original_raw_equality_verified") is True
            and q.get("current_true_owner_coverage_exact") is True and q.get("current_quality_unchanged") is True
            and q.get("current_false_still_false") is True and q.get("historical_all_decisions_original_owner_verified") is True
            and q.get("historical_projected_keys_all_named") is True and q.get("new_class_A_records")==0
            and q.get("classifier_rule_changed") is False and q.get("account_backend_entered")==0
            and q.get("ledger_prestate")==support["ledger_prestate"] and q.get("ledger_poststate")==support["ledger_prestate"],
            "ALL_FULL_U_QUOTE_SOURCE_PROOF_REQUIRED_NOT_SAVED_POLICY_FILTER")
        for value in support["finite_source_refs"].values():pin(value)
        for value in q["quote_binding"]["current_market_refs"].values():pin(value)
        pin(q["quote_binding"]["classification_ref"]);pin(q["quote_binding"]["quote_owner_ref"]);pin(q["quote_binding"]["transport_ref"])
        account.metadata_preflight(run)
        seam_ref=support["module_refs"]["seam"];transport_ref=support["module_refs"]["transport"];quote_ref=support["module_refs"]["quote"]
        modules=[]
        for name,value in (("seam",seam_ref),("transport",transport_ref),("quote",quote_ref)):
            p=pin(value);sp=importlib.util.spec_from_file_location("fixed_tail_existing_"+name,p)
            obj=importlib.util.module_from_spec(sp);sp.loader.exec_module(obj);require(ref(obj.__file__)==value,"ACTUAL_EXISTING_QUOTE_SOURCE_ORIGIN_REQUIRED")
            modules.append(obj)
        seam,transport,quote=modules
        with seam.account_quote_transport(account,quote,transport,q["quote_binding"]) as quote_provenance:
            yield dict(original_projection_ref=TAIL_R7_REF,current_overlay_owner_ref=cfg["runtime_entry_ref"],
                original_overlay_function_AST_custody=module.CUSTODY_REF,fixed_private_transport=["RUNTIME_ENTRY_REF"],
                original_five_global_overlay=overlay,original_quote_source_transport=quote_provenance,old_custody_code_executed=False)


def tail_saved_account_refs(run,cfg):
    """Only opaque physical pins from the already published original five."""
    core=read(pin(cfg["core_account_complete_ref"]))
    body=read(pin(core["account_terminal_ref"],Path(run)/"CORE_BASE_ACCOUNT_TERMINAL.json"))
    require(body.get("research_id")==ID,"ORIGINAL_CORE_ACCOUNT_PUBLICATION_IDENTITY_CHANGED")
    values={}
    for role in TAIL_CORE_IDS:
        state=core["core_account_states"][role]
        if state!="COMPLETE":continue
        require(role in body["complete"],"ORIGINAL_COMPLETE_ACCOUNT_PUBLICATION_MISSING:"+role)
        for key,value in body["complete"][role].items():
            if value is not None:pin(value);values[role+"|"+key]=value
        published=read(pin(body["complete"][role]["publication"],Path(run)/"accounts"/role/"PUBLICATION_COMPLETE.json"))
        require(published.get("status")=="COMPLETE" and published.get("policy_id")==role
            and published.get("research_id")==ID,"ORIGINAL_COMPLETE_ACCOUNT_PUBLICATION_IDENTITY_CHANGED")
        for key,value in published["files"].items():pin(value);values[role+"|file|"+key]=value
    return values


def execute_tail(run,phase):
    """One finite first phase, using original owners and sole original ledger."""
    run=Path(run).resolve()
    require(run==RUN.resolve(),"EXACT_FIXED_TAIL_RUN_REQUIRED")
    recovery=phase==POLICY_REBOOT_PHASE
    policy=phase==TAIL_PHASES[0] or recovery
    require(policy,"ACCOUNT_AND_STAT_SOURCE_ADAPTATION_NOT_YET_ADMITTED")
    with risk_runtime_owners(capture_stage="policy_reboot_named_execute_r1" if recovery else "post_risk_policy_execute_env_r1") as (controller,workflow,account):
        with workflow._worker_lock(run):
            cfg,review,review_ref,design=policy_reboot_load_authority(run) if recovery else tail_load_authority(run,phase)
            require(ref(controller.__file__)==cfg["phase_source_refs"]["controller"]
                and ref(workflow.__file__)==cfg["phase_source_refs"]["workflow"],"ACTUAL_TAIL_OWNER_SOURCE_ORIGIN_CHANGED")
            with controller.engineering_source_configuration(cfg["source_configuration_ref"]):
                validate_existing_sqlite(run,design);journal=controller._TaskLedger(run)
                try:
                    before=ledger_snapshot(journal,run,environment_postterminal_ref=cfg["environment_postterminal_ref"])
                    events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                    authority=journal.db.execute("SELECT design_sha256 FROM authority").fetchall()
                    require(public_snapshot(before)==cfg["ledger_prestate"],"TAIL_TERMINAL_PRESTATE_CHANGED")
                    old_core=read(pin(cfg["core_account_complete_ref"]))
                    require(all(journal.status("ACCOUNT|"+role)["status"]==value
                        for role,value in old_core["core_account_states"].items()),"ORIGINAL_FIVE_ACCOUNT_PROOF_AND_CURRENT_STATES_CHANGED")
                    allowed=policy_reboot_first_boundary(journal,design,cfg,events,before,run) if recovery else tail_first_boundary(journal,design,phase,events,run)
                    if policy and not recovery:
                        tail_policy_prefix_absent(run,controller)
                        allowed.update(tail_source_disposition(journal,workflow,run,cfg,apply=False))
                    saved_accounts=tail_saved_account_refs(run,cfg) if phase==TAIL_PHASES[1] else {}
                    controller.worker_runtime(run)
                    folder=run/"continuation";name=POLICY_REBOOT_NAME if recovery else tail_name(phase)
                    marker=append_json(folder/(name+"_STARTED.json"),dict(research_id=ID,phase=phase,
                        configuration_ref=ref(folder/(name+"_CONFIGURATION.json")),runtime_entry_ref=cfg["runtime_entry_ref"],
                        review_ref=review_ref,ledger_prestate=public_snapshot(before),scientific_retries=0))
                    outputs={};provenance=None
                    try:
                        if policy:
                            if not recovery:tail_source_disposition(journal,workflow,run,cfg,apply=True)
                            provider=workflow.RiskProvider(run)
                            if not recovery:controller.train_hybrids(run,provider)
                            workflow.risk_policies(run,provider,roles=cfg["recovery_roles"]) if recovery else workflow.risk_policies(run,provider)
                            require(all(journal.status(n)["status"] in TERMINAL for n in allowed),"ORIGINAL_POLICY_TAIL_NOT_TERMINAL")
                            workflow.freeze_policy_terminal(run)
                            outputs["policy_terminal"]=ref(run/"POLICY_TERMINAL.json")
                        elif phase==TAIL_PHASES[1]:
                            with tail_account_context(controller,account,run,cfg) as provenance:
                                workflow.run_accounts(run)
                            outputs["account_terminal"]=ref(run/"ACCOUNT_TERMINAL.json")
                        else:
                            from scripts.research.a2.data.full_selector_inputs import load_fixed_policy_outer_h5
                            workflow.evaluate(run,load_fixed_policy_outer_h5)
                            require(journal.status("STATISTICS|SHARED_321")["status"]=="COMPLETE","ORIGINAL_NEW_STATISTICS_NOT_COMPLETE_NO_RETRY")
                            outputs["statistics_publication"]=ref(run/"evaluation/STATISTICS_PUBLICATION_COMPLETE_R1.json")
                            outputs["report"]=ref(workflow.render_report(run))
                        after=ledger_snapshot(journal,run,environment_postterminal_ref=cfg["environment_postterminal_ref"])
                        require(all(journal.status(n)["status"] in TERMINAL for n in allowed),"ORIGINAL_TAIL_FIRST_NODES_NOT_NATURALLY_TERMINAL")
                        require({r[0]:r for r in before["rows"] if r[0] not in allowed}=={r[0]:r for r in after["rows"] if r[0] not in allowed},"NON_TARGET_TAIL_STATE_CHANGED")
                        after_events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                        require(after_events[:len(events)]==events and all(row[1] in allowed for row in after_events[len(events):]),"OLD_OR_NON_FIRST_TAIL_EVENT_CHANGED")
                        require(journal.db.execute("SELECT design_sha256 FROM authority").fetchall()==authority,"SOLE_TAIL_AUTHORITY_CHANGED")
                        validate_existing_sqlite(run,design)
                        for value in (*cfg["preserved_refs"].values(),*saved_accounts.values()):pin(value)
                        if recovery:
                            for value in read(pin(cfg["checkpoint_ref"]))["preserved_policy_publication_refs"].values():pin(value)
                        result=dict(research_id=ID,phase=phase,status="ORIGINAL_OWNER_TAIL_STAGE_TERMINAL",
                            marker_ref=marker,configuration_ref=ref(folder/(name+"_CONFIGURATION.json")),
                            runtime_entry_ref=cfg["runtime_entry_ref"],source_configuration_ref=cfg["source_configuration_ref"],
                            ledger_poststate=public_snapshot(after),output_refs=outputs,account_context=provenance,
                            scientific_retries=0,all_task_complete=False,outer_feedback=False)
                        append_json(folder/(name+"_COMPLETE.json"),result);return result
                    except BaseException:
                        append_json(folder/(name+"_FAILURE.json"),dict(research_id=ID,phase=phase,marker_ref=marker,
                            error=traceback.format_exc(),scientific_retries=0,all_task_complete=False));raise
                finally:journal.db.close()


"""Text integrated into the sole existing entry owner; no standalone engine."""

def risk_configuration_path(run,phase_name):
    return Path(run)/"continuation"/((RISK_PENDING_NAME+"_CONFIGURATION.json") if phase_name==RISK_PENDING_NAME else "RISK_CONTEXT_PHASE_CONFIGURATION_R1.json")


def pending_risk_qualification(cfg):
    """Require a new independent qualification while preserving the old gate."""
    original_path=RUN/"continuation/RISK_CONTEXT_METADATA_QUALIFICATION_R1.json"
    original_ref={"path":str(original_path.resolve()),"sha256":"3d82db91331789db2cec0ec1c57398c41ebae2a5e7d6c13d9116253f837d3c13"}
    original=read(pin(original_ref,original_path))
    supplement_path=RUN/"continuation/FIXED214_PENDING24_CURRENT_AXIS_NATIVE_SUPPORT_METADATA_SUPPLEMENT_R1.json"
    supplement_ref={"path":str(supplement_path.resolve()),"sha256":"7f092409095b1e664a5f93d8fbb8c89ca6f0cba1b261f02e5efe805cdca2927e"}
    peer_path=CACHE/"proposals/FIXED214_PENDING24_CURRENT_AXIS_NATIVE_SUPPORT_SUPPLEMENT_INDEPENDENT_METADATA_REVIEW_R1.json"
    peer_ref={"path":str(peer_path.resolve()),"sha256":"15b587a85e8e60b96a56bf9862985404134b45b6205f7b1b0ee1f4f38b631045"}
    require(cfg["metadata_supplement_ref"]==supplement_ref
        and cfg["independent_metadata_supplement_review_ref"]==peer_ref,
        "ONLY_ACTUAL_ACCEPTED_PENDING24_METADATA_SUPPLEMENT")
    supplement=read(pin(supplement_ref,supplement_path));peer=read(pin(peer_ref,peer_path))
    require(peer["schema"]=="FULL_SELECTOR_PENDING24_CURRENT_AXIS_NATIVE_SUPPORT_SUPPLEMENT_INDEPENDENT_METADATA_REVIEW_R1"
        and peer["status"]=="PASS" and peer["source_or_firstentry_or_scientific_admission"] is False
        and peer["actual_current_axis_projection_accepted"] is True
        and peer["original_Q3d82_190_24_byteexact_preserved"] is True,
        "METADATA_REVIEW_IS_NOT_FIRST_ENTRY_ADMISSION")
    qualification=read(pin(cfg["qualification_ref"]))
    require(qualification.get("schema")=="FULL_SELECTOR_FIXED214_SUPPLEMENTAL_FIRSTENTRY_METADATA_QUALIFICATION_R1"
        and qualification.get("status")=="PASS_ORIGINAL_FIXED_CURRENT_AXIS_AND_COMMON_NATIVE_SUPPORT_SUPPLEMENT"
        and qualification.get("research_id")==ID and qualification.get("independent_from_dispatch_writer") is True
        and qualification["original_qualification_ref"]==original_ref
        and qualification["formal_metadata_supplement_ref"]==supplement_ref
        and qualification["independent_metadata_supplement_review_ref"]==peer_ref,
        "NEW_INDEPENDENT_SUPPLEMENTAL_QUALIFICATION_REQUIRED")
    fixed=set(original)-{"schema","status","independent_from_dispatch_writer","qualified_context_ids","pending_context_ids"}
    require({key:qualification[key] for key in fixed}=={key:original[key] for key in fixed}
        and qualification["audit_ref"]==cfg["audit_ref"] and qualification["shortlist_ref"]==cfg["shortlist_ref"],
        "ORIGINAL_QUALIFICATION_SOURCE_AXIS_AND_RECIPE_FIELDS_UNCHANGED")
    reuse=original["qualified_context_ids"];first=supplement["prospective_common_support_present_context_ids"]
    pending=supplement["native2019_support_still_pending_context_ids"]
    require(len(reuse)==190 and len(first)==22 and len(pending)==2
        and set(first+pending)==set(original["pending_context_ids"])
        and len(set(reuse+first+pending))==214
        and first==peer["prospective_common_minimum_native_cohort_present_context_ids"]
        and pending==peer["native2019_support_still_pending_context_ids"]
        and qualification["original_qualified_reuse_context_ids"]==reuse
        and qualification["supplemental_pristine_first_entry_context_ids"]==first
        and set(qualification["qualified_context_ids"])==set(reuse+first)
        and len(qualification["qualified_context_ids"])==212
        and qualification["pending_context_ids"]==pending,
        "EXACT190_REUSE22_FIRST2_PENDING_REQUIRED")
    require(qualification["original_family_metadata_support_and_numeric_guards_unchanged"] is True
        and qualification["all18_family_or_numeric_or_PSD_qualification_granted"] is False
        and qualification["first_entry_or_scientific_execution_authorized"] is False
        and qualification["independent_qualification_and_SOURCE_actual_cold_and_firstentry_required"] is True,
        "COMMON_N30_QUALIFICATION_MUST_NOT_PROMOTE_FAMILY_OR_SCIENCE")
    rows={row["context_id"]:row for row in supplement["contexts"]}
    require(set(rows)==set(original["pending_context_ids"]),"EXACT_ORIGINAL24_SUPPLEMENT_OBJECTS")
    for cid in first+pending:
        row=rows[cid]
        require(row["current_axis_binding"]["original_current_observation_source_verified"] is True
            and row["current_axis_binding"]["native_history_continuity_inferred"] is False
            and row["new_source_or_firstentry_admission"] is False
            and row["numerical_finite_PSD_convergence_or_scientific_admission"] is False
            and row["native_metadata_minimum_common_support_present"]==(cid in first)
            and (row["min30_native_cohort_size"]>0)==(cid in first),
            "SOURCE_KNOWN_AXIS_AND_COMMON_NATIVE_COHORT_ONLY")
    transport=read(pin(qualification["metadata_raw_transport_ref"],RUN/"maintenance/FIXED214_PENDING24_INDEPENDENT_METADATA_SUPPLEMENT_ACTUAL_TRANSPORT_R1.json"))
    require(qualification["metadata_raw_transport_ref"]["sha256"]=="e7ff02b57d6a2dc8ff96d0799f8b3d1291d433e82bdca67ef1810905b85daa74"
        and transport["formal_metadata_supplement_ref"]==supplement_ref
        and transport["independent_metadata_acceptance_ref"]==peer_ref
        and transport["original_qualification_ref"]==original_ref
        and transport["new_scientific_execution_or_admission"] is False,
        "ACTUAL_ACCEPTED_METADATA_RAW_TRANSPORT_REQUIRED")
    return qualification


def load_pending_risk_configuration(run):
    cfg,design=tail_load_configuration(run,RISK_PENDING_PHASE,pending_risk_firstentry=True)
    require(cfg["source_dependency_disposition_ref"] is None,"PENDING22_FIRSTENTRY_CANNOT_FINAL_BLOCK_THE_ORIGINAL_PENDING_CONTEXTS")
    historical=read(pin(cfg["risk_configuration_ref"],Path(run)/"continuation/RISK_CONTEXT_PHASE_CONFIGURATION_R1.json"))
    for key in ("audit_ref","shortlist_ref","metadata_helper_overlay"):
        require(cfg[key]==historical[key],"UNCHANGED_ORIGINAL_PENDING_RISK_OWNER_FIELD:"+key)
    pending_risk_qualification(cfg)
    # These two named aliases are the existing risk loop's source/account transport.
    manifest=dict(cfg,engineering_source_configuration_ref=cfg["source_configuration_ref"],
        engineering_account_completion_ref=cfg["core_account_complete_ref"])
    return manifest,design


def load_pending_risk_authority(run):
    manifest,design=load_pending_risk_configuration(run)
    qualification=pending_risk_qualification(manifest)
    folder=Path(run)/"continuation";path=folder/(RISK_PENDING_NAME+"_ACCEPTANCE.json")
    review=read(path);configuration_ref=ref(risk_configuration_path(run,RISK_PENDING_NAME))
    require(review.get("schema")=="FULL_SELECTOR_FIXED214_PENDING22_RISK_FIRSTENTRY_ACCEPTANCE_R1"
        and review.get("status")=="PASS" and review.get("research_id")==ID
        and review.get("phase")==RISK_PENDING_PHASE
        and all(review.get(key) is True for key in ("independent_from_entry_writer","independent_from_dispatch_writer","all_prior_workers_terminal"))
        and review.get("scientific_retry_authorized") is False
        and review.get("configuration_ref")==configuration_ref
        and review.get("runtime_entry_ref")==manifest["runtime_entry_ref"]
        and review.get("source_configuration_ref")==manifest["source_configuration_ref"]
        and review.get("qualification_ref")==manifest["qualification_ref"]
        and review.get("independent_entry_source_review_ref")==ref(RISK_POST_PRIMARY_REVIEW)
        and review.get("metadata_supplement_ref")==manifest["metadata_supplement_ref"]
        and review.get("environment_postterminal_ref")==manifest["environment_postterminal_ref"]
        and review.get("ledger_prestate")==manifest["ledger_prestate"]
        and review.get("original_qualified_reuse_context_ids")==qualification["original_qualified_reuse_context_ids"]
        and review.get("first_entry_context_ids")==qualification["supplemental_pristine_first_entry_context_ids"]
        and review.get("qualified_context_ids")==qualification["qualified_context_ids"]
        and review.get("pending_context_ids")==qualification["pending_context_ids"]
        and len(review.get("requested_families",[]))==18 and len(set(review.get("requested_families",[])))==18,
        "INDEPENDENT_CURRENT_SOURCE_BOUND_PENDING22_FIRSTENTRY_REQUIRED")
    cold=read(pin(review["actual_cold_ref"]))
    require(cold.get("schema")=="FULL_SELECTOR_FIXED214_PENDING22_SOURCE_METADATA_RUNTIME_COLD_R1"
        and cold.get("status")=="PASS" and cold.get("actual_cold") is True and cold.get("synthetic") is False
        and cold.get("configuration_ref")==configuration_ref
        and cold.get("runtime_entry_ref")==manifest["runtime_entry_ref"]
        and cold.get("source_configuration_ref")==manifest["source_configuration_ref"]
        and cold.get("independent_entry_source_review_ref")==review["independent_entry_source_review_ref"]
        and cold.get("qualification_ref")==manifest["qualification_ref"]
        and cold.get("environment_postterminal_ref")==manifest["environment_postterminal_ref"]
        and cold.get("source_and_sql_unchanged") is True and cold.get("scientific_entry_calls")==0
        and cold.get("actual_qualification_gate_pass") is False and cold.get("actual_dispatch_allowed") is False,
        "ACTUAL_PENDING22_ZERO_BUSINESS_COLD_IS_NOT_FIRSTENTRY")
    return manifest,review,ref(path),design,qualification


POLICY_REBOOT_PHASE="post-risk-policy-reboot-named-first"
POLICY_REBOOT_NAME="POST_RISK_POLICY_REBOOT_NAMED_FIRST_R1"
POLICY_REBOOT_SCHEMA="FULL_SELECTOR_ORIGINAL_POLICY_REBOOT_NAMED_FIRST_CONFIGURATION_R1"

def policy_reboot_original_configuration(cfg,*,include_environment_closure=False):
    """Keep the actual interrupted first-policy configuration immutable."""
    value=cfg["original_policy_configuration_ref"]
    require(value["sha256"]=="9f4fd663d3a2585532c78c28fc25d6cd5836f86ef0500dd9ccf58116cd769e33","ACTUAL_INTERRUPTED_POLICY_CONFIGURATION_REQUIRED")
    original=read(pin(value,RUN/"continuation/POST_RISK_POST_RISK_POLICY_R1_CONFIGURATION.json"))
    for key,name in (("prior_entry_custody_ref","full_selector_engineering_continuation.py"),("prior_source_custody_ref","ENGINEERING_RISK_NONEXECUTED_SOURCE_REFRESH_R1.json")):
        old=original["runtime_entry_ref" if key=="prior_entry_custody_ref" else "source_configuration_ref"]
        require(cfg[key]["sha256"]==old["sha256"],"ACTUAL_INTERRUPTED_POLICY_SOURCE_IDENTITY_REQUIRED")
        pin(cfg[key],RUN/"source_corrections/POLICY_REBOOT_NAMED_FIRST_R1"/(name+"."+old["sha256"]+".before"))
    require(original["runtime_entry_ref"]["sha256"]=="aa1efc943d16d279fe9a82eff3a0f1e1e88517294fee2a87c811d47e2e2584dd"
        and original["source_configuration_ref"]["sha256"]=="fbe6d52fcae54600e80f3f3a836fd91d3a7edef8ad1d47355fdeab06a038b9d9","ONLY_ACTUAL_OLD_POLICY_SOURCE_ENVELOPE")
    closure=tail_pending22_predecessor(original)
    return (original,closure) if include_environment_closure else original

def policy_reboot_historical_binding(risk_cfg,cfg):
    original,closure=policy_reboot_original_configuration(cfg,include_environment_closure=True)
    require(cfg.get("schema")==POLICY_REBOOT_SCHEMA and cfg.get("phase")==POLICY_REBOOT_PHASE
        and cfg.get("runtime_entry_ref")==ref(__file__),"EXPLICIT_CURRENT_POLICY_REBOOT_METADATA_BRIDGE")
    require(risk_cfg==read(pin(original["risk_configuration_ref"],RUN/"continuation/RISK_CONTEXT_PHASE_CONFIGURATION_R1.json")),"UNCHANGED_OLD_ENVIRONMENT_CONFIGURATION_ONLY")
    require(risk_reference_equal(original["risk_configuration_ref"],closure["phase_configuration_ref"])
        and risk_reference_equal(risk_cfg["runtime_entry_ref"],closure["runtime_entry_ref"])
        and risk_reference_equal(risk_cfg["engineering_source_configuration_ref"],closure["source_configuration_ref"]),"ACTUAL_OLD_ENV_CONFIGURATION_AND_TYPED_CLOSURE_REQUIRED")
    pin(risk_cfg["current_entry_custody_ref"],RISK_C6_CUSTODY)
    require(risk_cfg["current_entry_custody_ref"]["sha256"]==RISK_C6_SHA,"ORIGINAL_PRE_RISK_C6_CUSTODY_REQUIRED")
    binding,review=risk_current_source_binding()
    require(binding["source_configuration_ref"]==cfg["source_configuration_ref"]
        and review["current_entry_custody_ref"]==cfg["prior_entry_custody_ref"]
        and review.get("policy_reboot_original_configuration_ref")==cfg["original_policy_configuration_ref"]
        and review.get("policy_reboot_checkpoint_ref")==cfg["checkpoint_ref"]
        and review.get("policy_reboot_administrative_closure_ref")==cfg["independent_administrative_closure_ref"]
        and review.get("tail_historical_environment_configuration_ref")==original["risk_configuration_ref"],"CURRENT_SOURCE_EXPLICIT_POLICY_REBOOT_AND_OLD_ENV_HISTORY_REQUIRED")
    return binding,review

def policy_reboot_original_started_custody(cfg,original,audit):
    value=audit["original_policy_start_ref"]
    started=read(pin(value,RUN/"continuation/POST_RISK_POST_RISK_POLICY_R1_STARTED.json"))
    require(started.get("research_id")==ID and started.get("phase")==TAIL_PHASES[0]
        and started.get("configuration_ref")==cfg["original_policy_configuration_ref"]
        and started.get("runtime_entry_ref")==original["runtime_entry_ref"]
        and started.get("ledger_prestate")==original["ledger_prestate"]==audit["original_prestate"]
        and started.get("scientific_retries")==0,"ACTUAL_ORIGINAL_POLICY_STARTED_CUSTODY_AND_18441_PRESTATE_REQUIRED")
    return value

def policy_reboot_load_configuration(run):
    run=Path(run).resolve();require(run==RUN.resolve(),"EXACT_ORIGINAL_POLICY_REBOOT_RUN")
    folder=run/"continuation";cfg=read(folder/(POLICY_REBOOT_NAME+"_CONFIGURATION.json"))
    fields={"schema","research_id","run","phase","runtime_entry_ref","source_configuration_ref","phase_source_refs",
        "original_policy_configuration_ref","actual_reboot_boundary_ref","actual_paid_prefix_audit_ref","checkpoint_ref",
        "independent_administrative_closure_ref","prior_entry_custody_ref","prior_source_custody_ref","ledger_prestate",
        "environment_postterminal_ref","preserved_refs","core_account_complete_ref","original_refs","recovery_roles",
        "firstentry_count","firstentry_ids_sha256"}
    require(set(cfg)==fields and cfg["schema"]==POLICY_REBOOT_SCHEMA and cfg["research_id"]==ID
        and cfg["phase"]==POLICY_REBOOT_PHASE and Path(cfg["run"]).resolve()==run
        and cfg["runtime_entry_ref"]==ref(__file__),"EXACT_CLOSED_POLICY_REBOOT_CONFIGURATION")
    original=policy_reboot_original_configuration(cfg)
    for name,expected in ORIGINAL_PINS.items():require(sha(run/name)==expected,"ORIGINAL_POLICY_REBOOT_FREEZE_CHANGED:"+name)
    for key in ("original_refs","environment_postterminal_ref","preserved_refs","core_account_complete_ref"):
        require(cfg[key]==original[key],"ORIGINAL_POLICY_REBOOT_UPSTREAM_FIELD_CHANGED:"+key)
    expected={"actual_reboot_boundary_ref":"a87cc147185af47731651e39c138def131ebbc7b47d0c4a3f9495a610615008b",
        "actual_paid_prefix_audit_ref":"5096ce4d26f8ba22f5bbdde8633807ca183f2ade984fcdc3265e79afa5b6531f",
        "checkpoint_ref":"669420b10e76f7a95f430239d2393182ca667bb53b28cac323445bd9ec997d92"}
    facts={}
    for key,h in expected.items():
        require(cfg[key]["sha256"]==h,"ACTUAL_ORIGINAL_POLICY_REBOOT_FACT_PIN:"+key);facts[key]=read(pin(cfg[key]))
    boundary=facts["actual_reboot_boundary_ref"];audit=facts["actual_paid_prefix_audit_ref"];checkpoint=facts["checkpoint_ref"]
    require(boundary["native_exit_code"] is None and boundary["session49312_collected"] is False
        and boundary["oncecollect_conditions_satisfied"] is False,"LOST_OLD_NATIVE_EXIT_MUST_REMAIN_UNKNOWN")
    require(audit["status"]=="PASS_READONLY_REBOOT_METADATA_NOT_PHASE_ADMISSION" and audit["no_STARTED_targets"] is True
        and audit["cumulative_paid_attempts"]==8054 and audit["cumulative_environment_reentry_charges"]==105
        and audit["original8_FAILED_paid_and_artifact_refs_preserved"] is True,"ORIGINAL_PAID_AND_FAILED_BOUNDARY_REQUIRED")
    policy_reboot_original_started_custody(cfg,original,audit)
    require(checkpoint["actual_paid_prefix_audit_ref"]==cfg["actual_paid_prefix_audit_ref"]
        and checkpoint["ledger_prestate"]==cfg["ledger_prestate"] and checkpoint["firstentry_count"]==cfg["firstentry_count"]==3976
        and checkpoint["firstentry_ids_sha256"]==cfg["firstentry_ids_sha256"]=="0ac270d63c86d3d94cadeb3d40cada5862cc4137b154cfa13760d29471862983"
        and cfg["recovery_roles"]==checkpoint["recovery_policy_roles"] and len(cfg["recovery_roles"])==8
        and len(checkpoint["terminal_policy_roles"])==14 and checkpoint["no_STARTED"] is True,"EXACT_ORIGINAL3976_FIRSTENTRY_CHECKPOINT")
    require(cfg["independent_administrative_closure_ref"]["sha256"]=="bd301011a785fbd5a13cbd9e9059a41b6be30494922985084866fd50aff114ff","ACTUAL_INDEPENDENT_REBOOT_ADMINISTRATIVE_CLOSURE_PIN")
    peer=read(pin(cfg["independent_administrative_closure_ref"]))
    require(peer.get("schema")=="FULL_SELECTOR_ORIGINAL_POLICY_REBOOT_ADMINISTRATIVE_CLOSURE_INDEPENDENT_ACCEPTANCE_R1"
        and peer.get("status")=="PASS" and peer.get("research_id")==ID and peer.get("administrative_closure_only") is True
        and all(peer.get(k) is True for k in ("independent_from_root_writer","independent_from_entry_writer","independent_from_dispatch_writer"))
        and peer.get("actual_boundary_ref")==cfg["actual_reboot_boundary_ref"]
        and peer.get("actual_paid_prefix_identity_audit_ref")==cfg["actual_paid_prefix_audit_ref"]
        and peer["actual_process_boundary"]["native_exit_code"] is None and peer["actual_process_boundary"]["old_session49312_collected"] is False
        and peer["actual_process_boundary"]["collect49312_authorized"] is False
        and peer["authority_limits"]["scientific_retry_authorized"] is False
        and peer["source_or_cold_or_phase_or_scientific_admission_granted"] is False,"INDEPENDENT_ACTUAL_REBOOT_ADMINISTRATIVE_CLOSURE_REQUIRED")
    for suffix in ("COMPLETE","FAILURE","OS_EXIT_RECEIPT_R1"):
        require(not (folder/("POST_RISK_POST_RISK_POLICY_R1_"+suffix+".json")).exists(),"OLD_NATIVE_TERMINAL_MUST_NOT_BE_FABRICATED")
    require(not any((folder/(POLICY_REBOOT_NAME+"_"+s+".json")).exists() for s in ("STARTED","COMPLETE","FAILURE")),"POLICY_REBOOT_SLOT_ALREADY_ATTEMPTED_NO_RETRY")
    binding,review=policy_reboot_historical_binding(read(pin(original["risk_configuration_ref"])),cfg)
    require(set(cfg["phase_source_refs"])=={"controller","workflow"} and cfg["phase_source_refs"]["controller"]==binding["controller_ref"],"ACTUAL_POLICY_REBOOT_OWNER_SOURCE_BINDING")
    for value in cfg["phase_source_refs"].values():pin(value)
    require(cfg["phase_source_refs"]["workflow"]==original["phase_source_refs"]["workflow"],"UNCHANGED_ORIGINAL_POLICY_MATH_WORKFLOW")
    _,core=risk_prior_completions(run,read(pin(original["risk_configuration_ref"])),tail_metadata_configuration=cfg)
    require(set(core["core_account_states"].values())=={"FAILED"},"SAVED5_FAILURES_STAY_FAILED_NO_RETRY")
    for value in (*cfg["preserved_refs"].values(),*checkpoint["preserved_policy_publication_refs"].values()):pin(value)
    return cfg,read(run/"DESIGN_FREEZE.json")

def policy_reboot_load_authority(run):
    cfg,design=policy_reboot_load_configuration(run);folder=Path(run)/"continuation"
    review_path=folder/(POLICY_REBOOT_NAME+"_ACCEPTANCE.json");review=read(review_path)
    require(review.get("schema")=="FULL_SELECTOR_ORIGINAL_POLICY_REBOOT_NAMED_FIRST_ACCEPTANCE_R1"
        and review.get("status")=="PASS" and review.get("research_id")==ID
        and review.get("phase")==POLICY_REBOOT_PHASE and review.get("independent_from_entry_writer") is True
        and review.get("all_prior_workers_terminal_or_administratively_closed") is True
        and review.get("scientific_retry_authorized") is False
        and review.get("configuration_ref")==ref(folder/(POLICY_REBOOT_NAME+"_CONFIGURATION.json"))
        and review.get("runtime_entry_ref")==cfg["runtime_entry_ref"] and review.get("source_configuration_ref")==cfg["source_configuration_ref"]
        and review.get("checkpoint_ref")==cfg["checkpoint_ref"] and review.get("ledger_prestate")==cfg["ledger_prestate"],"INDEPENDENT_POLICY_REBOOT_ORIGINAL_FIRSTENTRY_ADMISSION_REQUIRED")
    cold=read(pin(review["actual_cold_ref"]))
    require(cold.get("status")=="PASS" and cold.get("actual_cold") is True and cold.get("synthetic") is False
        and cold.get("configuration_ref")==review["configuration_ref"] and cold.get("runtime_entry_ref")==cfg["runtime_entry_ref"]
        and cold.get("source_configuration_ref")==cfg["source_configuration_ref"] and cold.get("checkpoint_ref")==cfg["checkpoint_ref"]
        and cold.get("scientific_entry_calls")==0 and cold.get("source_and_sql_unchanged") is True,"NEW_ACTUAL_POLICY_REBOOT_COLD_REQUIRED_NO_OLD_COLD_SUBSTITUTION")
    return cfg,review,ref(review_path),design

def policy_reboot_first_boundary(journal,design,cfg,events,before,run):
    checkpoint=read(pin(cfg["checkpoint_ref"]))
    require(public_snapshot(before)==checkpoint["ledger_prestate"],"ACTUAL_REBOOT_CHECKPOINT_LEDGER_CHANGED")
    kinds={"HYBRID_ESTIMATOR","HYBRID_SCALER","MEMBER_SOLVE","WHOLE_SET_GATE"}
    targets={n["node_id"] for n in design["dag"]["nodes"] if n["kind"] in kinds}
    require(len(targets)==11188 and digest(sorted(targets))==checkpoint["original11188_target_ids_sha256"],"ORIGINAL_FULL_POLICY_SCOPE_MUST_REMAIN_FIXED")
    allowed={n for n in targets if journal.status(n)["status"]=="NAMED"}
    require(len(allowed)==cfg["firstentry_count"] and digest(sorted(allowed))==cfg["firstentry_ids_sha256"],"ONLY_ORIGINAL3976_PRISTINE_NAMED_FIRSTENTRY")
    for n in allowed:
        state=journal.status(n)
        require(state==dict(status="NAMED",entered=0,identity=None,artifact=None,error=None),"NO_OLD_ENTRY_OR_FAILED_RETRY:"+n)
        require(not (Path(run)/"models"/(digest(n)+".joblib")).exists(),"NO_NAMED_ORPHAN_ARTIFACT_OVERWRITE:"+n)
    require(not any(row[1] in allowed for row in events),"NO_PRIOR_EVENTS_FOR_REBOOT_FIRSTENTRY")
    require(all(journal.status(n)["status"] in TERMINAL for n in targets-allowed),"ALL_OTHER_POLICY_NODES_TERMINAL_PRESERVED")
    for value in checkpoint["preserved_policy_publication_refs"].values():pin(value)
    for role in cfg["recovery_roles"]:
        for name in ("policy_"+role+".parquet","policy_"+role+".parquet.json","risk_decisions_"+role+".json","failure_"+role+".json"):
            require(not (Path(run)/"predictions"/name).exists(),"PRESERVE_INCOMPLETE_POLICY_PUBLICATION_PREFIX:"+role)
    return allowed


"""Prospective additive controls for the canonical continuation entry only."""
POLICY_ZERO_PHASE='post-risk-policy-source-guard-zero-entry-r4'
POLICY_ZERO_NAME='POST_RISK_POLICY_SOURCE_GUARD_ZERO_ENTRY_R4'


def policy_zero_load_configuration(run):
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    run=Path(run).resolve();require(run==RUN.resolve(),'EXACT_ORIGINAL_ZERO_ENTRY_RUN')
    path=run/'continuation'/(POLICY_ZERO_NAME+'_CONFIGURATION.json');cfg=read(path)
    fields={'schema','research_id','run','phase','runtime_entry_ref','source_configuration_ref','phase_source_refs',
            'prior_configuration_ref','prior_started_ref','prior_failure_ref','prior_os_ref','prior_root_terminal_ref',
            'actual_audit_ref','original_ids_ref','independent_boundary_ref','independent_export_reuse_ref',
            'ledger_prestate','firstentry_count','firstentry_ids_sha256','recovery_roles','preserved_refs',
            'publication_custody_refs','environment_postterminal_ref','reuse_basis'}
    require(set(cfg)==fields and cfg.get('schema')=='FULL_SELECTOR_POLICY_SOURCE_GUARD_ZERO_ENTRY_CONFIGURATION_R1'
            and cfg.get('research_id')==ID and Path(cfg.get('run','')).resolve()==run and cfg.get('phase')==POLICY_ZERO_PHASE,
            'CLOSED_ORIGINAL_ZERO_ENTRY_CONFIGURATION')
    require(cfg['runtime_entry_ref']==ref(__file__) and set(cfg['phase_source_refs'])==set(sg.RUNTIME_PATHS),
            'ACTUAL_CURRENT_ORIGINAL_ENTRY_AND_CLOSED_RUNTIME')
    for name,p in sg.RUNTIME_PATHS.items():pin(cfg['phase_source_refs'][name],p)
    source=sg.read_control(cfg['source_configuration_ref'],run/sg.SOURCE_NAME)
    require(source['runtime_source_refs']==cfg['phase_source_refs'] and
            cfg['phase_source_refs']['entry']==cfg['runtime_entry_ref'],'SOURCE_AND_PHASE_SAME_EXECUTED_OWNERS')
    require(cfg['prior_configuration_ref']['sha256']=='858d932b6277b69056f53333d4d3f2679f76e2bc3a8d953f1343c38859f30086',
            'ACTUAL_FAILED_POLICY_CONFIGURATION_REQUIRED')
    prior=read(pin(cfg['prior_configuration_ref'],run/'continuation/POST_RISK_POLICY_REBOOT_NAMED_FIRST_R1_CONFIGURATION.json'))
    require(cfg['recovery_roles']==prior['recovery_roles'] and len(cfg['recovery_roles'])==8 and
            cfg['environment_postterminal_ref']==prior['environment_postterminal_ref'], 'ONLY_ORIGINAL_EIGHT_POLICY_ROLES')
    for key, oldkey in [('prior_started_ref','8ddd32685595de30ae43d0d1ec5f4a979aa9066d5e67ef4a70ec21f81ae15377'),
                        ('prior_failure_ref','b572f5e8eb2735fc2e63b57c46b8b7db7c06a7242d2fa99a96293aeabd803ae6'),
                        ('prior_os_ref','e93d9ab7efee416035d1f568c3610c3d51f825c100dc55ab4eda1aa61941ff3e'),
                        ('prior_root_terminal_ref','6a217593f9146bea5118ce1896ecee04a274d5b614b151dac78a296333e09ebd'),
                        ('actual_audit_ref','3c8dc63212be0e04275150fc1cada9ec19f13fba0f31d8bddbd044cb89e11111'),
                        ('original_ids_ref','27238085acb2b968e25bea792eaa552147a44d12e9199b8c830c2fb204c16bcb'),
                        ('independent_boundary_ref',sg.BOUNDARY_SHA),('independent_export_reuse_ref',sg.EXPORT_REUSE_SHA)]:
        require(cfg[key]['sha256']==oldkey,'EXACT_ACTUAL_TERMINAL_OR_BOUNDARY:'+key);pin(cfg[key])
    require(cfg['firstentry_count']==3394 and cfg['firstentry_ids_sha256']==sg.ACTUAL_PRESTATE['ids_sha256'] and
            cfg['ledger_prestate']=={k:sg.ACTUAL_PRESTATE[k] for k in ('nodes_sha256','events_sha256','event_count')}
            and cfg['reuse_basis']=='BOUNDED_REACHABLE_EXPORT_EQUIVALENCE', 'ONLY_EXACT_ZERO_ENTRY_RECOVERY_SCOPE')
    ids=sg.read_control(cfg['original_ids_ref'])['original_node_ids']
    require(len(ids)==3394 and ids==sorted(set(ids)) and sg.digest(ids)==cfg['firstentry_ids_sha256'],
            'EXACT_ORIGINAL3394_ID_NAMESPACE')
    require(source['independent_boundary_ref']==cfg['independent_boundary_ref'] and
            source['independent_export_reuse_ref']==cfg['independent_export_reuse_ref'] and
            source['actual_failure_ref']==cfg['prior_failure_ref'] and source['actual_audit_ref']==cfg['actual_audit_ref'] and
            source['original_ids_ref']==cfg['original_ids_ref'], 'ACTUAL_SOURCE_PHASE_BOUNDARIES_SAME')
    from scripts.common.json_projection import metadata_fields
    checkpoint_path=pin(prior['checkpoint_ref'])
    require(prior['checkpoint_ref']['sha256']=='669420b10e76f7a95f430239d2393182ca667bb53b28cac323445bd9ec997d92',
            'ORIGINAL14_PUBLICATION_CHECKPOINT_AUTHORITY')
    with checkpoint_path.open('rb') as handle:
        publications=metadata_fields(handle,{'preserved_policy_publication_refs'})['preserved_policy_publication_refs']
    required_preserved=dict(prior['preserved_refs'])
    required_preserved.update({'original14_policy_publication|'+key:value for key,value in publications.items()})
    require(len(prior['preserved_refs'])==5 and len(publications)==38 and len(required_preserved)==43 and
            cfg['preserved_refs']==required_preserved,'EXACT_ALL43_PRESERVED_REFERENCES_NO_OMISSION_OR_EXTRA')
    require(source['preinstall_custody_ref']['sha256']=='0952a382fed3b6c228b4af168ff02308fff119426f060b8c32a2828d6b62637b',
            'ACTUAL_PREINSTALL_PUBLICATION_AND_SOURCE_CUSTODY')
    preinstall=sg.read_control(source['preinstall_custody_ref'])
    require(cfg['publication_custody_refs']==preinstall['publication_custody_refs'] and
            set(cfg['publication_custody_refs'])=={'SCORE_ASSEMBLY',*('failure_'+role for role in cfg['recovery_roles'])},
            'EXACT_NINE_MUTABLE_PUBLICATION_BEFORE_CUSTODIES')
    for value in cfg['preserved_refs'].values():pin(value)
    for item in cfg['publication_custody_refs'].values():
        require(set(item)=={'original_observation_ref','immutable_custody_ref'} and
                item['original_observation_ref']['sha256']==item['immutable_custody_ref']['sha256'],
                'COMPLETE_OLD_PUBLICATION_WHOLE_BYTE_CUSTODY')
        custody=pin(item['immutable_custody_ref'])
        require(custody.is_relative_to((run/'source_corrections/POLICY_ZERO_ENTRY_SOURCE_GUARD_R1').resolve()),
                'TASK_PRIVATE_PUBLICATION_CUSTODY')
    return cfg,source,ids


def policy_zero_load_authority(run,cfg):
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    folder=Path(run)/'continuation';path=folder/(POLICY_ZERO_NAME+'_ACCEPTANCE.json')
    review=read(path)
    fields={'schema','status','research_id','phase','configuration_ref','runtime_entry_ref','source_configuration_ref',
            'independent_source_review_ref','actual_cold_ref','actual_cold_os_ref','independent_boundary_ref',
            'independent_export_reuse_ref','original_ids_ref','scope','checks','reuse_basis',
            'historical_whole_joint_module_identity','independent_from_entry_writer','independent_from_source_writer'}
    require(set(review)==fields and review.get('schema')=='FULL_SELECTOR_POLICY_SOURCE_GUARD_ZERO_ENTRY_ACCEPTANCE_R1'
            and review.get('status')=='PASS' and review.get('research_id')==ID and review.get('phase')==POLICY_ZERO_PHASE
            and review.get('configuration_ref')==ref(folder/(POLICY_ZERO_NAME+'_CONFIGURATION.json'))
            and review.get('runtime_entry_ref')==cfg['runtime_entry_ref'] and review.get('source_configuration_ref')==cfg['source_configuration_ref']
            and review.get('independent_from_entry_writer') is True and review.get('independent_from_source_writer') is True,
            'ACTUAL_INDEPENDENT_ZERO_ENTRY_PHASE_ACCEPTANCE_REQUIRED')
    for key in ('independent_boundary_ref','independent_export_reuse_ref','original_ids_ref','reuse_basis'):
        require(review[key]==cfg[key],'PHASE_SCOPE_AND_BOUNDARY_SAME:'+key)
    require(review['historical_whole_joint_module_identity']=='UNKNOWN' and review['scope']=='ONLY_ORIGINAL3394_ZERO_ENTRY_AND_ORIGINAL_ONCE_EXACT_REUSE',
            'BOUNDED_EXPORT_REUSE_NOT_WHOLE_MODULE_HISTORY_ASSERTION')
    checks={'original39961_prefix_and8054_preserved','all3394_single_block_zero_entry','new_joint_exact_loaded_export_fences',
            'original_once_and_math_unchanged','536_and_old40_exact_reuse_only','46_other_blocks_and_all_FAILED_preserved',
            'all22_and66_assembly_preserved','new_explicit_restore_history_seam','actual_source_whole_history_and_custody',
            'actual_cold_zero_science_and_no_sql_mutation','resource_and_original_worker_lock_required'}
    require(set(review['checks'])==checks and all(v is True for v in review['checks'].values()),'COMPLETE_PHASE_SCOPE_CHECKS')
    source=read(pin(cfg['source_configuration_ref']))
    require(review['independent_source_review_ref']==source['independent_review_ref'],'ACTUAL_SOURCE_ACCEPTANCE_SAME')
    pin(review['independent_source_review_ref'])
    cold=sg.read_control(review['actual_cold_ref'])
    osr=sg.read_control(review['actual_cold_os_ref'])
    require(cold.get('status')=='PASS' and cold.get('actual') is True and cold.get('synthetic') is False and
            cold.get('configuration_ref')==review['configuration_ref'] and cold.get('runtime_entry_ref')==cfg['runtime_entry_ref'] and
            cold.get('source_configuration_ref')==cfg['source_configuration_ref'] and cold.get('scientific_entry_calls')==0 and
            cold.get('TaskLedger_constructor_calls')==0 and cold.get('source_and_sql_unchanged') is True,
            'NEW_ACTUAL_COLD_REQUIRED_NOT_SYNTHETIC_SUBSTITUTION')
    root=sg.read_control(ref(RUN/'maintenance/POLICY_ZERO_ENTRY_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R4.json'))
    require(root.get('schema')=='FULL_SELECTOR_POLICY_ZERO_ENTRY_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R1' and
            root.get('status')=='PASS' and root.get('phase_acceptance_ref')==ref(path) and
            root.get('configuration_ref')==review['configuration_ref'] and root.get('source_configuration_ref')==cfg['source_configuration_ref'] and
            root.get('actual_cold_ref')==review['actual_cold_ref'] and root.get('actual_cold_os_ref')==review['actual_cold_os_ref'] and
            root.get('independent_boundary_ref')==cfg['independent_boundary_ref'] and
            root.get('independent_export_reuse_ref')==cfg['independent_export_reuse_ref'] and root.get('allow_original3394_first_entries') is True
            and isinstance(root.get('actual_cold_root_terminal_ref'),dict),
            'ROOT_LAST_ACTUAL_ZERO_ENTRY_ADMISSION_REQUIRED')
    sg.validate_actual_cold_native(osr,cold,review,cfg,root['actual_cold_root_terminal_ref'])
    return review,ref(path),ref(RUN/'maintenance/POLICY_ZERO_ENTRY_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R4.json')


def execute_policy_zero_entry(run):
    """Original owners, original eight roles, one explicit zero-entry restore."""
    global _RISK_ACTIVE_CONTROLLER
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    cfg,source,ids=policy_zero_load_configuration(run)
    prior=read(pin(source['prior_source_configuration_ref']))
    recovery=risk_verified_source(cfg['phase_source_refs']['recovery_owner'],'_risk_zero_entry_original_transport')
    previous=_RISK_ACTIVE_CONTROLLER
    with sg.frozen_joint_scope():
        with recovery.transported_owners(configuration_ref=prior['source_transport_ref'],source_ref=source['prior_source_configuration_ref']) as (c,w,transport):
            with c.nonexecuting_registry_metadata_scope(RUN,capture_stage='policy_zero_entry_r4',authority_ref=source['prior_source_configuration_ref']):
                with w._worker_lock(RUN):
                    _RISK_ACTIVE_CONTROLLER=c
                    try:
                        review,review_ref,root_ref=policy_zero_load_authority(RUN,cfg)
                        with c.engineering_source_configuration(cfg['source_configuration_ref']):
                            journal=c._TaskLedger(RUN)
                            try:
                                before_rows=journal.db.execute('SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id').fetchall()
                                before_events=journal.db.execute('SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence').fetchall()
                                authority=journal.db.execute('SELECT design_sha256 FROM authority').fetchall()
                                require(authority==[(sha(RUN/'DESIGN_FREEZE.json'),)],'SOLE_ORIGINAL_AUTHORITY_REQUIRED')
                                sg.zero_entry_plan(before_rows,before_events,ids,sg.ACTUAL_PRESTATE)
                                for node in ids:
                                    require(not (RUN/'models'/(digest(node)+'.joblib')).exists(),'NO_ZERO_ENTRY_ORPHAN_ARTIFACT_OVERWRITE')
                                for item in cfg['publication_custody_refs'].values():pin(item['original_observation_ref'])
                                c.worker_runtime(RUN)
                                folder=RUN/'continuation'
                                marker=append_json(folder/(POLICY_ZERO_NAME+'_STARTED.json'),dict(research_id=ID,phase=POLICY_ZERO_PHASE,
                                    configuration_ref=ref(folder/(POLICY_ZERO_NAME+'_CONFIGURATION.json')),runtime_entry_ref=cfg['runtime_entry_ref'],
                                    review_ref=review_ref,root_last_ref=root_ref,source_configuration_ref=cfg['source_configuration_ref'],
                                    ledger_prestate=cfg['ledger_prestate'],original_firstentry_scope=3394,original_paid_entries=8054,
                                    reuse_basis=cfg['reuse_basis'],historical_whole_joint_module_identity='UNKNOWN',
                                    joint_loaded_source=sg.active_joint_observation(),scientific_retries=0))
                                try:
                                    restore=sg.restore_zero_entry_transaction(journal.db,ids,sg.ACTUAL_PRESTATE,review_ref,c.now())
                                    restore_ref=append_json(folder/(POLICY_ZERO_NAME+'_ZERO_ENTRY_RESTORED.json'),restore)
                                    with sg.original_once_scope(c,ids):
                                        provider=w.RiskProvider(RUN)
                                        w.risk_policies(RUN,provider,roles=cfg['recovery_roles'])
                                        require(all(journal.status(n)['status'] in TERMINAL for n in ids),'ORIGINAL3394_NOT_NATURALLY_TERMINAL')
                                        w.freeze_policy_terminal(RUN)
                                    after_rows=journal.db.execute('SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id').fetchall()
                                    after_events=journal.db.execute('SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence').fetchall()
                                    history=sg.zero_entry_history(before_rows,before_events,after_rows,after_events,ids,sg.ACTUAL_PRESTATE,review_ref,restore['restored_at_utc'])
                                    require(journal.db.execute('SELECT design_sha256 FROM authority').fetchall()==authority,'SOLE_ORIGINAL_AUTHORITY_CHANGED')
                                    for value in cfg['preserved_refs'].values():pin(value)
                                    for item in cfg['publication_custody_refs'].values():pin(item['immutable_custody_ref'])
                                    result=dict(research_id=ID,phase=POLICY_ZERO_PHASE,status='ORIGINAL_OWNER_ZERO_ENTRY_STAGE_TERMINAL',
                                        marker_ref=marker,restore_ref=restore_ref,configuration_ref=ref(folder/(POLICY_ZERO_NAME+'_CONFIGURATION.json')),
                                        runtime_entry_ref=cfg['runtime_entry_ref'],source_configuration_ref=cfg['source_configuration_ref'],
                                        output_refs=dict(policy_terminal=ref(RUN/'POLICY_TERMINAL.json'),score_assembly=ref(RUN/'SCORE_ASSEMBLY.json')),
                                        ledger_poststate=dict(nodes_sha256=digest(after_rows),events_sha256=digest(after_events),event_count=len(after_events)),
                                        history=history,joint_loaded_source=sg.active_joint_observation(),reuse_basis=cfg['reuse_basis'],
                                        historical_whole_joint_module_identity='UNKNOWN',scientific_retries=0,all_task_complete=False,outer_feedback=False)
                                    append_json(folder/(POLICY_ZERO_NAME+'_COMPLETE.json'),result);return result
                                except BaseException:
                                    append_json(folder/(POLICY_ZERO_NAME+'_FAILURE.json'),dict(research_id=ID,phase=POLICY_ZERO_PHASE,marker_ref=marker,
                                        error=traceback.format_exc(),scientific_retries=0,all_task_complete=False));raise
                            finally:journal.db.close()
                    finally:_RISK_ACTIVE_CONTROLLER=previous


"""Additive original-owner checkpoint entry controls; not an executable engine."""
POLICY_CHECKPOINT_PHASE='post-risk-policy-source-guard-checkpoint-named-first-r5'
POLICY_CHECKPOINT_NAME='POST_RISK_POLICY_SOURCE_GUARD_CHECKPOINT_NAMED_FIRST_R5'


def policy_checkpoint_load_configuration(run):
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    run=Path(run).resolve();require(run==RUN.resolve(),'EXACT_ORIGINAL_CHECKPOINT_RUN')
    cfg=read(run/'continuation'/(POLICY_CHECKPOINT_NAME+'_CONFIGURATION.json'))
    fields={'schema','research_id','run','phase','runtime_entry_ref','source_configuration_ref','phase_source_refs',
            'prior_configuration_ref','prior_acceptance_ref','prior_started_ref','prior_restore_ref',
            'actual_disappearance_boundary_ref','actual_finite_audit_ref','actual_partial_checkpoint_ref',
            'independent_checkpoint_acceptance_ref','original_ids_ref','remaining_original_ids_ref',
            'ledger_prestate','firstentry_count','firstentry_ids_sha256','recovery_roles','preserved_refs',
            'publication_custody_refs','environment_postterminal_ref','reuse_basis'}
    require(set(cfg)==fields and cfg.get('schema')=='FULL_SELECTOR_POLICY_CHECKPOINT_CONFIGURATION_R5' and
            cfg.get('research_id')==ID and Path(cfg.get('run','')).resolve()==run and
            cfg.get('phase')==POLICY_CHECKPOINT_PHASE,'CLOSED_ORIGINAL_CHECKPOINT_CONFIGURATION')
    require(cfg['runtime_entry_ref']==ref(__file__) and set(cfg['phase_source_refs'])==set(sg.RUNTIME_PATHS),
            'CHECKPOINT_CURRENT_ENTRY_AND_CLOSED_RUNTIME')
    for name,p in sg.RUNTIME_PATHS.items():pin(cfg['phase_source_refs'][name],p)
    source=sg.read_control(cfg['source_configuration_ref'],run/sg.SOURCE_NAME)
    require(source['runtime_source_refs']==cfg['phase_source_refs'] and
            cfg['phase_source_refs']['entry']==cfg['runtime_entry_ref'],'CHECKPOINT_SOURCE_SAME_EXECUTED_OWNERS')
    epoch,checkpoint,custody=sg.validate_checkpoint_epoch_history(source)
    prior=sg.read_control(cfg['prior_configuration_ref'],run/'continuation/POST_RISK_POLICY_SOURCE_GUARD_ZERO_ENTRY_R4_CONFIGURATION.json')
    require(cfg['prior_configuration_ref']['sha256']=='ad17aae64bc35c9c9c72f8fca4b32dbcf605bfadb89f7139453cca8b968b16cc' and
            cfg['prior_configuration_ref']==checkpoint['original_configuration_ref'] and
            cfg['prior_acceptance_ref']==checkpoint['original_acceptance_ref'] and
            cfg['prior_restore_ref']==checkpoint['actual_restore_ref'],'CONSUMED_R4_CONFIGURATION_ADMISSION_RESTORE')
    require(cfg['prior_started_ref']==ref(run/'continuation/POST_RISK_POLICY_SOURCE_GUARD_ZERO_ENTRY_R4_STARTED.json'),
            'ACTUAL_R4_STARTED_REFERENCE_REQUIRED')
    pin(cfg['prior_started_ref'],run/'continuation/POST_RISK_POLICY_SOURCE_GUARD_ZERO_ENTRY_R4_STARTED.json')
    for key in ('actual_disappearance_boundary_ref','actual_finite_audit_ref','actual_partial_checkpoint_ref',
                'independent_checkpoint_acceptance_ref'):
        require(cfg[key]==epoch[key],'SAME_CHECKPOINT_EPOCH_AND_PHASE:'+key);pin(cfg[key])
    require(cfg['remaining_original_ids_ref']==epoch['pristine_original_ids_ref'] and
            cfg['original_ids_ref']==checkpoint['full_original_ids_ref']==prior['original_ids_ref'] and
            source['original_ids_ref']==cfg['original_ids_ref'],'ONLY_DERIVED_SUBSET_OF_ORIGINAL_IDS')
    original=sg.read_control(cfg['original_ids_ref'])
    remaining=sg.read_control(cfg['remaining_original_ids_ref'])
    ids=original['original_node_ids'];pending=remaining['original_node_ids']
    require(ids==sorted(set(ids)) and len(ids)==3394 and sg.digest(ids)==sg.ACTUAL_PRESTATE['ids_sha256'] and
            remaining['schema']=='FULL_SELECTOR_POLICY_ZERO_ENTRY_R4_DERIVED_PRISTINE_ORIGINAL_IDS_R1' and
            remaining['scope']=='DERIVED_SUBSET_ONLY_NOT_NEW_SCIENTIFIC_ID_AUTHORITY' and
            remaining['original_ids_ref']==cfg['original_ids_ref'] and
            pending==sorted(set(pending)) and set(pending)<=set(ids) and len(pending)==remaining['original_node_count']==1664 and
            sg.digest(pending)==remaining['original_node_ids_sha256']==cfg['firstentry_ids_sha256'] and
            cfg['firstentry_ids_sha256']=='ec4c4d7dfa598f0a2da87a49a75f620e492a66296fa272b736b391384abf4ac8' and
            cfg['firstentry_count']==1664,'EXACT_PRISTINE1664_ORIGINAL_NAMESPACE')
    require(cfg['ledger_prestate']==checkpoint['actual_ledger_poststate'] and
            cfg['ledger_prestate']==dict(nodes_sha256='1420a59256b2a82c7cf13fa0017e0e0b3ef25a4d1247ab3fe1c6c00ff0c63545',
                events_sha256='692e7e3e83a4ec68a8383199b60ef316f01da27d8028cd4177a04b912514964d',event_count=48545),
            'EXACT_ACCEPTED48545_CHECKPOINT')
    require(cfg['recovery_roles']==prior['recovery_roles'] and len(cfg['recovery_roles'])==8 and
            cfg['environment_postterminal_ref']==prior['environment_postterminal_ref'] and
            cfg['reuse_basis']==prior['reuse_basis']=='BOUNDED_REACHABLE_EXPORT_EQUIVALENCE' and
            cfg['preserved_refs']==prior['preserved_refs'] and len(cfg['preserved_refs'])==43,
            'ORIGINAL_ROLES_ENVIRONMENT_AND_ALL43_IMMUTABLE_PUBLICATIONS')
    for value in cfg['preserved_refs'].values():pin(value)
    require(cfg['publication_custody_refs']==custody['publication_custody_refs'] and
            set(cfg['publication_custody_refs'])==set(prior['publication_custody_refs']),
            'ALL_NINE_CURRENT_CHECKPOINT_PUBLICATIONS_WHOLE_CUSTODY')
    for key,value in cfg['publication_custody_refs'].items():
        require(value['original_observation_ref']['path']==prior['publication_custody_refs'][key]['original_observation_ref']['path'],
                'SAME_ORIGINAL_MUTABLE_PUBLICATION_PATHS')
        pin(value['immutable_custody_ref'])
    restore=sg.read_control(cfg['prior_restore_ref'])
    require(restore['phase_admission_ref']==cfg['prior_acceptance_ref'] and
            restore['restored_original_ids']==3394 and restore['administrative_event_count']==3394 and
            restore['actual_backend_entries']==0 and restore['budget_charge_delta']==0,
            'ONLY_EXISTING_SINGLE_ZERO_CHARGE_ADMIN_RESTORE')
    return cfg,source,ids,pending,checkpoint,restore


def policy_checkpoint_load_authority(run,cfg):
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    folder=Path(run)/'continuation';path=folder/(POLICY_CHECKPOINT_NAME+'_ACCEPTANCE.json')
    review=read(path)
    fields={'schema','status','research_id','phase','configuration_ref','runtime_entry_ref','source_configuration_ref',
            'independent_source_review_ref','actual_cold_ref','actual_cold_os_ref','independent_boundary_ref',
            'independent_export_reuse_ref','original_ids_ref','scope','checks','reuse_basis',
            'historical_whole_joint_module_identity','independent_from_entry_writer','independent_from_source_writer'}
    require(set(review)==fields and review.get('schema')=='FULL_SELECTOR_POLICY_SOURCE_GUARD_ZERO_ENTRY_ACCEPTANCE_R1' and
            review.get('status')=='PASS' and review.get('research_id')==ID and review.get('phase')==POLICY_CHECKPOINT_PHASE and
            review.get('configuration_ref')==ref(folder/(POLICY_CHECKPOINT_NAME+'_CONFIGURATION.json')) and
            review.get('runtime_entry_ref')==cfg['runtime_entry_ref'] and
            review.get('source_configuration_ref')==cfg['source_configuration_ref'] and
            review.get('independent_from_entry_writer') is True and review.get('independent_from_source_writer') is True,
            'ACTUAL_INDEPENDENT_CHECKPOINT_PHASE_ACCEPTANCE')
    source=read(pin(cfg['source_configuration_ref']))
    require(review['independent_boundary_ref']==cfg['independent_checkpoint_acceptance_ref'] and
            review['independent_export_reuse_ref']==source['independent_export_reuse_ref'] and
            review['original_ids_ref']==cfg['original_ids_ref'] and
            review['reuse_basis']==cfg['reuse_basis'] and review['historical_whole_joint_module_identity']=='UNKNOWN' and
            review['scope']=='ONLY_ORIGINAL1664_PRISTINE_FIRST_ENTRY_NO_SECOND_ADMIN_AND_ORIGINAL_ONCE_EXACT_REUSE',
            'CHECKPOINT_FIRST_ENTRY_ONLY_NOT_HISTORY_UPGRADE')
    checks={'original48545_39961_and34913_prefixes_preserved','all1664_pristine_NAMED_original_first_entry',
            '1730_536_and_old40_original_once_exact_reuse_only','no_second_ADMIN_or_ENV_REENTER',
            '46_other_blocks_and_all_FAILED_preserved','all22_and66_assembly_preserved',
            'original_math_RNG_order_precision_unchanged','actual_current_whole_history_source_capture_custody',
            'R4_native_exit_Wait_cause_unknown_session_uncollected','actual_cold_zero_science_no_sql_mutation',
            'fresh_resource_and_original_worker_lock_required'}
    require(set(review['checks'])==checks and all(v is True for v in review['checks'].values()),
            'COMPLETE_CHECKPOINT_PHASE_CHECKS')
    require(review['independent_source_review_ref']==source['independent_review_ref'],'SAME_ACTUAL_SOURCE_ACCEPTANCE')
    pin(review['independent_source_review_ref'])
    cold=sg.read_control(review['actual_cold_ref']);osr=sg.read_control(review['actual_cold_os_ref'])
    require(cold.get('status')=='PASS' and cold.get('actual') is True and cold.get('synthetic') is False and
            cold.get('configuration_ref')==review['configuration_ref'] and
            cold.get('runtime_entry_ref')==cfg['runtime_entry_ref'] and
            cold.get('source_configuration_ref')==cfg['source_configuration_ref'] and
            cold.get('scientific_entry_calls')==0 and cold.get('TaskLedger_constructor_calls')==0 and
            cold.get('source_and_sql_unchanged') is True and cold.get('checkpoint_firstentry_count')==1664 and
            cold.get('second_ADMIN_events')==0,'NEW_ACTUAL_CHECKPOINT_COLD_REQUIRED')
    rootpath=RUN/'maintenance/POLICY_CHECKPOINT_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R5.json'
    root=sg.read_control(ref(rootpath))
    require(root.get('schema')=='FULL_SELECTOR_POLICY_CHECKPOINT_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R5' and
            root.get('status')=='PASS' and root.get('phase_acceptance_ref')==ref(path) and
            root.get('configuration_ref')==review['configuration_ref'] and
            root.get('source_configuration_ref')==cfg['source_configuration_ref'] and
            root.get('actual_cold_ref')==review['actual_cold_ref'] and
            root.get('actual_cold_os_ref')==review['actual_cold_os_ref'] and
            root.get('independent_checkpoint_acceptance_ref')==cfg['independent_checkpoint_acceptance_ref'] and
            root.get('actual_partial_checkpoint_ref')==cfg['actual_partial_checkpoint_ref'] and
            root.get('allow_original1664_first_entries') is True and root.get('second_ADMIN_forbidden') is True and
            isinstance(root.get('actual_cold_root_terminal_ref'),dict),'ROOT_LAST_ACTUAL_CHECKPOINT_PHASE_ADMISSION')
    sg.validate_actual_cold_native(osr,cold,review,cfg,root['actual_cold_root_terminal_ref'])
    return review,ref(path),ref(rootpath)


def execute_policy_checkpoint(run):
    """Run only original pristine first entries; never restore or retry science."""
    global _RISK_ACTIVE_CONTROLLER
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    cfg,source,ids,pending,checkpoint,restore=policy_checkpoint_load_configuration(run)
    prior=read(pin(source['prior_source_configuration_ref']))
    recovery=risk_verified_source(cfg['phase_source_refs']['recovery_owner'],'_risk_checkpoint_original_transport')
    previous=_RISK_ACTIVE_CONTROLLER
    history_args=dict(original_expected=sg.ACTUAL_PRESTATE,original_history=sg.zero_entry_history,
                      admission_ref=cfg['prior_acceptance_ref'],restored_at_utc=restore['restored_at_utc'])
    with sg.frozen_joint_scope():
        with recovery.transported_owners(configuration_ref=prior['source_transport_ref'],source_ref=source['prior_source_configuration_ref']) as (c,w,transport):
            with c.nonexecuting_registry_metadata_scope(RUN,capture_stage='policy_checkpoint_r5',authority_ref=source['prior_source_configuration_ref']):
                with w._worker_lock(RUN):
                    _RISK_ACTIVE_CONTROLLER=c
                    try:
                        review,review_ref,root_ref=policy_checkpoint_load_authority(RUN,cfg)
                        with c.engineering_source_configuration(cfg['source_configuration_ref']):
                            journal=c._TaskLedger(RUN)
                            try:
                                before_rows=journal.db.execute('SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id').fetchall()
                                before_events=journal.db.execute('SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence').fetchall()
                                authority=journal.db.execute('SELECT design_sha256 FROM authority').fetchall()
                                require(authority==[(sha(RUN/'DESIGN_FREEZE.json'),)],'SOLE_ORIGINAL_CHECKPOINT_AUTHORITY')
                                sg.checkpoint_plan(before_rows,before_events,ids,pending,checkpoint,**history_args)
                                for node in pending:
                                    require(not (RUN/'models'/(digest(node)+'.joblib')).exists(),'NO_PRISTINE_CHECKPOINT_ORPHAN_OVERWRITE')
                                for item in cfg['publication_custody_refs'].values():pin(item['original_observation_ref'])
                                c.worker_runtime(RUN)
                                folder=RUN/'continuation'
                                marker=append_json(folder/(POLICY_CHECKPOINT_NAME+'_STARTED.json'),dict(
                                    research_id=ID,phase=POLICY_CHECKPOINT_PHASE,
                                    configuration_ref=ref(folder/(POLICY_CHECKPOINT_NAME+'_CONFIGURATION.json')),
                                    runtime_entry_ref=cfg['runtime_entry_ref'],review_ref=review_ref,root_last_ref=root_ref,
                                    source_configuration_ref=cfg['source_configuration_ref'],actual_partial_checkpoint_ref=cfg['actual_partial_checkpoint_ref'],
                                    ledger_prestate=cfg['ledger_prestate'],original_pristine_firstentry_scope=1664,
                                    exact_original_once_reuse1730=True,second_ADMIN_events=0,scientific_retries=0,
                                    reuse_basis=cfg['reuse_basis'],historical_whole_joint_module_identity='UNKNOWN',
                                    joint_loaded_source=sg.active_joint_observation()))
                                try:
                                    with sg.original_once_scope(c,pending):
                                        provider=w.RiskProvider(RUN)
                                        w.risk_policies(RUN,provider,roles=cfg['recovery_roles'])
                                        require(all(journal.status(n)['status'] in TERMINAL for n in ids),'ORIGINAL3394_NOT_NATURALLY_TERMINAL')
                                        w.freeze_policy_terminal(RUN)
                                    after_rows=journal.db.execute('SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id').fetchall()
                                    after_events=journal.db.execute('SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence').fetchall()
                                    history=sg.checkpoint_history(before_rows,before_events,after_rows,after_events,ids,pending,checkpoint,**history_args)
                                    require(journal.db.execute('SELECT design_sha256 FROM authority').fetchall()==authority,'SOLE_ORIGINAL_CHECKPOINT_AUTHORITY_CHANGED')
                                    for value in cfg['preserved_refs'].values():pin(value)
                                    for item in cfg['publication_custody_refs'].values():pin(item['immutable_custody_ref'])
                                    result=dict(research_id=ID,phase=POLICY_CHECKPOINT_PHASE,status='ORIGINAL_OWNER_CHECKPOINT_STAGE_TERMINAL',
                                        marker_ref=marker,configuration_ref=ref(folder/(POLICY_CHECKPOINT_NAME+'_CONFIGURATION.json')),
                                        runtime_entry_ref=cfg['runtime_entry_ref'],source_configuration_ref=cfg['source_configuration_ref'],
                                        actual_partial_checkpoint_ref=cfg['actual_partial_checkpoint_ref'],
                                        output_refs=dict(policy_terminal=ref(RUN/'POLICY_TERMINAL.json'),score_assembly=ref(RUN/'SCORE_ASSEMBLY.json')),
                                        ledger_poststate=dict(nodes_sha256=digest(after_rows),events_sha256=digest(after_events),event_count=len(after_events)),
                                        history=history,second_ADMIN_events=0,joint_loaded_source=sg.active_joint_observation(),
                                        reuse_basis=cfg['reuse_basis'],historical_whole_joint_module_identity='UNKNOWN',
                                        scientific_retries=0,all_task_complete=False,outer_feedback=False)
                                    append_json(folder/(POLICY_CHECKPOINT_NAME+'_COMPLETE.json'),result);return result
                                except BaseException:
                                    append_json(folder/(POLICY_CHECKPOINT_NAME+'_FAILURE.json'),dict(research_id=ID,
                                        phase=POLICY_CHECKPOINT_PHASE,marker_ref=marker,error=traceback.format_exc(),
                                        second_ADMIN_events=0,scientific_retries=0,all_task_complete=False));raise
                            finally:journal.db.close()
                    finally:_RISK_ACTIVE_CONTROLLER=previous



POLICY_CATALOG_PHASE = "post-risk-policy-catalog-limited1655-first-r6"
POLICY_CATALOG_NAME = "POST_RISK_POLICY_CATALOG_LIMITED1655_FIRST_R6"
_CATALOG_ORIGINAL_LOCK_HELD = False

def policy_catalog_load_configuration(run):
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    run=Path(run).resolve();require(run==RUN.resolve(),"CATALOG_EXACT_ORIGINAL_RUN")
    path=run/"continuation"/(POLICY_CATALOG_NAME+"_CONFIGURATION.json")
    cfg=sg.catalog_source_read_control(ref(path),"phase_cfg")
    fields={"schema","research_id","run","phase","runtime_entry_ref","phase_source_refs","source_configuration_ref",
        "prior_R5_configuration_ref","original_ids_ref","prior_remaining1664_ids_ref","approved1655_ids_ref",
        "human_authorization_ref","human_transcript_ref","source_intent_ref","catalog_annex_ref",
        "ledger_prestate","recovery_roles","preserved_refs","publication_custody_refs",
        "restoration_custody_ref","independent_R5_terminal_ref","reuse_basis"}
    require(set(cfg)==fields and cfg["schema"]=="FULL_SELECTOR_POLICY_CATALOG_LIMITED1655_CONFIGURATION_R6"
        and cfg["research_id"]==ID and Path(cfg["run"]).resolve()==run and cfg["phase"]==POLICY_CATALOG_PHASE,
        "CATALOG_CLOSED_NEW_CONFIGURATION")
    require(cfg["runtime_entry_ref"]==ref(__file__) and cfg["phase_source_refs"]["entry"]==cfg["runtime_entry_ref"]
        and set(cfg["phase_source_refs"])==set(sg.RUNTIME_PATHS),"CATALOG_EXECUTED_ENTRY_AND_RUNTIME5")
    for name,path in sg.RUNTIME_PATHS.items():pin(cfg["phase_source_refs"][name],path)
    source=sg.catalog_source_read_control(cfg["source_configuration_ref"],"source")
    require(set(source)==sg.CATALOG_SOURCE_FIELDS and source["schema"]==sg.CATALOG_SOURCE_SCHEMA
        and source["status"]=="PASS" and source["runtime_source_refs"]==cfg["phase_source_refs"]
        and source["catalog_nonexecuted_annex_ref"]==cfg["catalog_annex_ref"],"CATALOG_SAME_CURRENT_MAIN_SOURCE")
    intent=sg.catalog_source_read_control(cfg["source_intent_ref"],"intent")
    require(intent==sg.catalog_source_intent_payload(source),"CATALOG_SAME_SEVEN_FIELD_INTENT")
    require(cfg["prior_R5_configuration_ref"]["sha256"]=="875224f187c8727acce9fbe22ac4c868385565541b091af28929b61ec9814af9",
        "CATALOG_ORIGINAL_CONSUMED_R5_CONFIGURATION")
    old=sg.catalog_source_read_control(cfg["prior_R5_configuration_ref"],"old_phase_cfg")
    human=sg.catalog_limited1655_human_scope()
    require(cfg["human_authorization_ref"]==human["human_authorization_ref"]
        and cfg["human_transcript_ref"]==human["transcript_clarification_ref"]
        and cfg["approved1655_ids_ref"]==human["derived_ids_ref"]
        and cfg["original_ids_ref"]==old["original_ids_ref"]
        and cfg["prior_remaining1664_ids_ref"]==old["remaining_original_ids_ref"],
        "CATALOG_LIMITED_HUMAN_SCOPE_NO_NEW_ID_AUTHORITY")
    ids=sg.catalog_source_read_control(cfg["original_ids_ref"],"original_ids")["original_node_ids"]
    pending=sg.catalog_source_read_control(cfg["prior_remaining1664_ids_ref"],"prior_remaining_ids")["original_node_ids"]
    require(ids==sorted(set(ids)) and len(ids)==3394 and sg.digest(ids)==sg.ACTUAL_PRESTATE["ids_sha256"]
        and pending==sorted(set(pending)) and len(pending)==1664 and set(pending)<=set(ids)
        and sg.digest(pending)==sg._CATALOG_LIMITED_PENDING_DIGEST_R6
        and set(human["original_node_ids"])<=set(pending),"CATALOG_EXACT_ORIGINAL3394_1664_APPROVED1655")
    require(cfg["ledger_prestate"]==sg._CATALOG_LIMITED_PRESTATE_R6
        and cfg["recovery_roles"]==old["recovery_roles"] and len(cfg["recovery_roles"])==8
        and cfg["preserved_refs"]==old["preserved_refs"] and len(cfg["preserved_refs"])==43
        and cfg["reuse_basis"]==old["reuse_basis"]=="BOUNDED_REACHABLE_EXPORT_EQUIVALENCE",
        "CATALOG_ACCEPTED50215_ORIGINAL_ROLES_AND43_IMMUTABLE")
    for value in cfg["preserved_refs"].values():pin(value)
    whole=sg.catalog_source_read_control(cfg["restoration_custody_ref"],"wholebefore")
    require(set(whole)=={"schema","status","research_id","ledger_prestate","runtime_source_refs","artifacts","publication_custody_refs"}
        and whole["schema"]=="POLICY_CATALOG_LIMITED1655_PRE_RESTORE_WHOLEBEFORE_R6"
        and whole["status"]=="ACTUAL_OWNER_WHOLEBEFORE_SEALED"
        and whole["research_id"]==ID and whole["ledger_prestate"]==cfg["ledger_prestate"]
        and whole["runtime_source_refs"]==cfg["phase_source_refs"]
        and whole["publication_custody_refs"]==cfg["publication_custody_refs"],
        "CATALOG_NEW_PRE_RESTORE_WHOLEBEFORE")
    fixed={"sqlite":RUN/"TASK_LEDGER.sqlite","wal":RUN/"TASK_LEDGER.sqlite-wal","shm":RUN/"TASK_LEDGER.sqlite-shm",
        "state":RUN/"continuation/CONTINUATION_STATE_R5.json","plan":RUN/"EXEC_PLAN.json"}
    require(type(whole["artifacts"]) is dict and set(whole["artifacts"])==set(fixed),
        "CATALOG_ALL_ORIGINAL_WHOLEBEFORE_ARTIFACTS")
    custody_root=(RUN/"maintenance/POLICY_CATALOG_LIMITED1655_PRE_RESTORE_WHOLEBEFORE_R6").resolve()
    for key,live in fixed.items():
        item=whole["artifacts"][key]
        require(type(item) is dict and set(item)=={"present","observation_ref","custody_ref"}
            and type(item["present"]) is bool and (key not in {"sqlite","state","plan"} or item["present"]),
            "CATALOG_TYPED_WHOLEBEFORE_EXISTENCE")
        if item["present"]:
            require(Path(item["observation_ref"]["path"]).resolve()==live.resolve()
                and item["custody_ref"]["sha256"]==item["observation_ref"]["sha256"]
                and pin(item["custody_ref"]).is_relative_to(custody_root),"CATALOG_WHOLEBEFORE_SEPARATE_CUSTODY")
        else:require(item["observation_ref"] is None and item["custody_ref"] is None,"CATALOG_ABSENT_IS_NULL")
    require(set(cfg["publication_custody_refs"])==set(old["publication_custody_refs"]) and len(cfg["publication_custody_refs"])==9,
        "CATALOG_ALL_NINE_CURRENT_PUBLICATIONS")
    for name,item in cfg["publication_custody_refs"].items():
        require(set(item)=={"original_observation_ref","immutable_custody_ref"}
            and item["original_observation_ref"]["path"]==old["publication_custody_refs"][name]["original_observation_ref"]["path"]
            and item["original_observation_ref"]["sha256"]==item["immutable_custody_ref"]["sha256"]
            and pin(item["immutable_custody_ref"]).is_relative_to(custody_root),
            "CATALOG_SAME_NINE_PATHS_NEW_WHOLE_CUSTODY")
    require(cfg["independent_R5_terminal_ref"]["sha256"]==sg._CATALOG_OLD_TERMINAL_PINS["peer"],
        "CATALOG_ACCEPTED_R5_TERMINAL_BOUNDARY")
    sg.catalog_source_read_control(cfg["independent_R5_terminal_ref"],"peer")
    return cfg,source,ids,pending,human

def policy_catalog_load_authority(run,cfg,before_capture=False):
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    require(_CATALOG_ORIGINAL_LOCK_HELD is True and _RISK_ACTIVE_CONTROLLER is not None,"CATALOG_ACTUAL_ORIGINAL_LOCK_HELD")
    current,source,ids,pending,human=policy_catalog_load_configuration(run)
    require(current==cfg,"CATALOG_EXACT_PHYSICAL_CURRENT_CONFIGURATION")
    require(type(before_capture) is bool,"CATALOG_TYPED_PRECAPTURE_PHASE_GATE")
    if before_capture:
        sg.catalog_source_review_preflight(_RISK_ACTIVE_CONTROLLER,cfg["source_configuration_ref"],
            cfg["catalog_annex_ref"],sg.digest(sg.catalog_source_intent_payload(source)))
    else:
        source=_RISK_ACTIVE_CONTROLLER._source_correction(cfg["source_configuration_ref"])
    path=RUN/"continuation"/(POLICY_CATALOG_NAME+"_ACCEPTANCE.json");acceptance_ref=ref(path)
    review=sg.catalog_source_read_control(acceptance_ref,"phase_acceptance")
    fields={"schema","status","research_id","phase","configuration_ref","runtime_entry_ref","source_configuration_ref",
        "independent_source_review_ref","actual_cold_ref","actual_cold_os_ref","independent_boundary_ref",
        "independent_export_reuse_ref","original_ids_ref","scope","checks","reuse_basis",
        "historical_whole_joint_module_identity","independent_from_entry_writer","independent_from_source_writer"}
    old=sg.catalog_source_read_control(source["prior_checkpoint_source_ref"],"prior")
    require(set(review)==fields and review["schema"]=="FULL_SELECTOR_POLICY_SOURCE_GUARD_ZERO_ENTRY_ACCEPTANCE_R1"
        and review["status"]=="PASS" and review["research_id"]==ID and review["phase"]==POLICY_CATALOG_PHASE
        and review["configuration_ref"]==ref(RUN/"continuation"/(POLICY_CATALOG_NAME+"_CONFIGURATION.json"))
        and review["runtime_entry_ref"]==cfg["runtime_entry_ref"]
        and review["source_configuration_ref"]==cfg["source_configuration_ref"]
        and review["independent_source_review_ref"]==source["independent_review_ref"]
        and review["independent_boundary_ref"]==cfg["independent_R5_terminal_ref"]
        and review["independent_export_reuse_ref"]==old["independent_export_reuse_ref"]
        and review["original_ids_ref"]==cfg["original_ids_ref"]
        and review["scope"]=="ONLY_ORIGINAL1655_LIMITED_SECOND_ADMIN_THEN_ORIGINAL_FIRST_ENTRY_NO_OTHER_BLOCKED_OR_FAILED"
        and review["reuse_basis"]==cfg["reuse_basis"] and review["historical_whole_joint_module_identity"]=="UNKNOWN"
        and review["independent_from_entry_writer"] is True and review["independent_from_source_writer"] is True,
        "CATALOG_ACTUAL_NEW_INDEPENDENT_FORMAL19")
    checks={"both_human_receipts_and_exact1655_subset_verified","all1655_zero_entry_no_identity_artifact_or_charge",
        "paid3_other6_and_all_FAILED_saved5_preserved","original50215_48545_39961_34913_prefixes_preserved",
        "exact_one_limited_second_ADMIN_no_third_ADMIN_ENV_REENTER","original1733_536_40_once_exact_reuse",
        "math_precision_order_rng_and_original_once_unchanged","original8_roles_and22_66_assembly_preserved",
        "actual_current_history_SOURCE_and_three_capture_custody","old_R5_failure_native1_collected1_preserved",
        "R4_native_Wait_exit_cause_remain_UNKNOWN","new_actual_cold_zero_science_no_ledger_mutation",
        "fresh_original_resource_gate_and_original_worker_lock","new_ROOTLAST_and_wholebefore_required"}
    require(type(review["checks"]) is dict and set(review["checks"])==checks
        and all(v is True for v in review["checks"].values()),"CATALOG_ALL_NEW_PHASE_CHECKS")
    cold=sg.catalog_source_read_control(review["actual_cold_ref"],"actual_cold")
    osr=sg.catalog_source_read_control(review["actual_cold_os_ref"],"actual_cold_os")
    require(cold.get("status")=="PASS" and cold.get("actual") is True and cold.get("synthetic") is False
        and cold.get("configuration_ref")==review["configuration_ref"]
        and cold.get("runtime_entry_ref")==cfg["runtime_entry_ref"]
        and cold.get("source_configuration_ref")==cfg["source_configuration_ref"]
        and cold.get("scientific_entry_calls")==0 and cold.get("TaskLedger_constructor_calls")==0
        and cold.get("source_and_sql_unchanged") is True and cold.get("sql_changes")==0
        and cold.get("limited1655_restore_calls")==0 and cold.get("planned_second_ADMIN_count")==1655
        and cold.get("second_ADMIN_events")==0,"CATALOG_NEW_ACTUAL_COLD_NO_RESTORE_OR_SCIENCE")
    rootpath=RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R6.json";root_ref=ref(rootpath)
    root=sg.catalog_source_read_control(root_ref,"phase_root")
    rootfields={"schema","status","phase","phase_acceptance_ref","configuration_ref","source_configuration_ref",
        "independent_source_review_ref","actual_cold_ref","actual_cold_os_ref","actual_cold_root_terminal_ref",
        "independent_R5_terminal_ref","human_authorization_ref","human_transcript_ref","approved1655_ids_ref",
        "restoration_custody_ref","allow_limited_second_ADMIN1655","forbid_all_other_BLOCKED_FAILED_retry",
        "original_worker_lock_required","fresh_original_resource_gate_required"}
    require(set(root)==rootfields and root["schema"]=="POLICY_CATALOG_LIMITED1655_ROOT_LAST_ACTUAL_PHASE_ADMISSION_R6"
        and root["status"]=="PASS" and root["phase"]==POLICY_CATALOG_PHASE
        and root["phase_acceptance_ref"]==acceptance_ref and root["configuration_ref"]==review["configuration_ref"]
        and root["source_configuration_ref"]==cfg["source_configuration_ref"]
        and root["independent_source_review_ref"]==source["independent_review_ref"]
        and root["actual_cold_ref"]==review["actual_cold_ref"] and root["actual_cold_os_ref"]==review["actual_cold_os_ref"]
        and all(root[key]==cfg[key] for key in ("independent_R5_terminal_ref","human_authorization_ref","human_transcript_ref",
            "approved1655_ids_ref","restoration_custody_ref"))
        and all(root[key] is True for key in ("allow_limited_second_ADMIN1655","forbid_all_other_BLOCKED_FAILED_retry",
            "original_worker_lock_required","fresh_original_resource_gate_required")),"CATALOG_NEW_ACTUAL_ROOTLAST")
    sg.validate_catalog_actual_cold_native(osr,cold,review,cfg,root["actual_cold_root_terminal_ref"])
    permitpath=RUN/"maintenance/POLICY_CATALOG_LIMITED1655_SCIENCE_FRESH_RESOURCE_PERMIT_R6.json"
    permit=sg.catalog_source_read_control(ref(permitpath),"phase_resource")
    require(set(permit)=={"schema","status","phase","configuration_ref","source_configuration_ref","root_last_ref",
        "observed_utc","physical_available_bytes","prestart_minimum_available_GiB","threads","UTF8","worker_limit",
        "task_budget_GiB","pre_import_thread_environment","single_start_only","launcher_ref"}
        and permit["schema"]=="POLICY_CATALOG_LIMITED1655_SCIENCE_FRESH_RESOURCE_PERMIT_R6"
        and permit["status"]=="ACTUAL_PARENT_PRESTART_RESOURCE_SAMPLE_FOR_SINGLE_START"
        and permit["phase"]==POLICY_CATALOG_PHASE and permit["configuration_ref"]==review["configuration_ref"]
        and permit["source_configuration_ref"]==cfg["source_configuration_ref"] and permit["root_last_ref"]==root_ref
        and type(permit["physical_available_bytes"]) is int and permit["physical_available_bytes"]>=1610612736
        and permit["prestart_minimum_available_GiB"]==1.5 and permit["threads"]==2 and permit["UTF8"] is True
        and permit["worker_limit"]==1 and permit["task_budget_GiB"]==8
        and permit["pre_import_thread_environment"]=={name:"2" for name in sg.THREAD_FIELDS}
        and permit["single_start_only"] is True,"CATALOG_ORIGINAL_SCIENCE_RESOURCE_GATE_NOT_SYNTHETIC_1GIB")
    from datetime import datetime,timezone
    observed=datetime.fromisoformat(permit["observed_utc"].replace("Z","+00:00"))
    require(observed.tzinfo is not None and datetime.now(timezone.utc)>=observed>=datetime.fromtimestamp(rootpath.stat().st_mtime,timezone.utc),
        "CATALOG_RESOURCE_OBSERVED_AFTER_THIS_ROOTLAST")
    pin(permit["launcher_ref"],CACHE/"proposals/launch_original_catalog_limited1655_R6.ps1")
    return review,acceptance_ref,root_ref

def policy_catalog_source_metadata_probe(run,intent_ref,annex_ref):
    """Actual capture evidence only; no SQL, TaskLedger, SOURCE activation or science."""
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    run=Path(run).resolve();require(run==RUN.resolve(),"CATALOG_METADATA_EXACT_RUN")
    intent=sg.catalog_source_read_control(intent_ref,"intent")
    old,prior,original=sg._catalog_source_predecessor(intent["prior_checkpoint_source_ref"])
    recovery=risk_verified_source(intent["runtime_source_refs"]["recovery_owner"],"_catalog_metadata_original_transport")
    output=RUN/"maintenance/POLICY_CATALOG_LIMITED1655_ACTUAL_SOURCE_METADATA_PROBE_R6.json"
    require(not output.exists(),"CATALOG_ACTUAL_METADATA_EVIDENCE_ONCE")
    with sg.frozen_joint_scope():
        with recovery.transported_owners(configuration_ref=prior["source_transport_ref"],source_ref=old["prior_source_configuration_ref"]) as (c,w,transport):
            with w._worker_lock(RUN):
                sg.catalog_source_metadata_preflight(c,annex_ref,original,intent_ref)
                with c.nonexecuting_registry_metadata_scope(RUN,capture_stage="policy_catalog_source_metadata_r6",authority_ref=old["prior_source_configuration_ref"]) as registry:
                    with c.catalog_nonexecuting_metadata_scope(RUN,"policy_catalog_source_metadata_r6",annex_ref,original) as catalog:
                        result=sg.catalog_source_metadata_probe(c,annex_ref,original,intent_ref)
                        evidence=dict(schema="FULL_SELECTOR_POLICY_CATALOG_ACTUAL_SOURCE_METADATA_PROBE_R6",
                            status=result["status"],research_id=ID,actual=True,synthetic=False,intent_ref=intent_ref,
                            source_intent_payload_sha256=result["source_intent_payload_sha256"],
                            annex_ref=annex_ref,current_runtime_source_refs=intent["runtime_source_refs"],
                            original99_sources_sha256=sg.digest(original),prior_R5_source_ref=intent["prior_checkpoint_source_ref"],
                            registry_capture_ref=registry["capture_receipt_ref"],catalog_capture_ref=catalog["receipt_ref"],
                            source_admission=False,phase_admission=False,science_executed=False)
                return append_json(output,evidence)

def execute_policy_catalog(run):
    """Only approved1655 second ADMIN and original first entries after all real gates."""
    global _RISK_ACTIVE_CONTROLLER,_CATALOG_ORIGINAL_LOCK_HELD
    from scripts.research.a2.training import full_selector_source_guard_recovery as sg
    cfg,source,ids,pending,human=policy_catalog_load_configuration(run)
    old,prior,original=sg._catalog_source_predecessor(source["prior_checkpoint_source_ref"])
    recovery=risk_verified_source(cfg["phase_source_refs"]["recovery_owner"],"_catalog_limited1655_original_transport")
    previous=_RISK_ACTIVE_CONTROLLER
    with sg.frozen_joint_scope():
        with recovery.transported_owners(configuration_ref=prior["source_transport_ref"],source_ref=old["prior_source_configuration_ref"]) as (c,w,transport):
            with w._worker_lock(RUN):
                _RISK_ACTIVE_CONTROLLER=c;_CATALOG_ORIGINAL_LOCK_HELD=True
                try:
                    # Must precede both new closed2 and catalog capture slots.
                    sg.catalog_source_review_preflight(c,cfg["source_configuration_ref"],cfg["catalog_annex_ref"],
                        sg.digest(sg.catalog_source_intent_payload(source)))
                    # All formal/cold/ROOTLAST/resource gates precede either first-entry slot.
                    policy_catalog_load_authority(RUN,cfg,before_capture=True)
                    with c.nonexecuting_registry_metadata_scope(RUN,capture_stage="policy_catalog_firstentry_r6",authority_ref=old["prior_source_configuration_ref"]):
                        with c.catalog_nonexecuting_metadata_scope(RUN,"policy_catalog_nonexecuted_firstentry_r1",
                                cfg["catalog_annex_ref"],original,main_source_ref=cfg["source_configuration_ref"]):
                            review,review_ref,root_ref=policy_catalog_load_authority(RUN,cfg)
                            with c.engineering_source_configuration(cfg["source_configuration_ref"]):
                                journal=c._TaskLedger(RUN)
                                try:
                                    before_rows=journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id").fetchall()
                                    before_events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                                    authority=journal.db.execute("SELECT design_sha256 FROM authority").fetchall()
                                    require(authority==[(sha(RUN/"DESIGN_FREEZE.json"),)],"CATALOG_SOLE_ORIGINAL_AUTHORITY")
                                    sg.catalog_limited1655_plan(before_rows,before_events,ids,pending,human)
                                    for node in human["original_node_ids"]:
                                        require(not (RUN/"models"/(digest(node)+".joblib")).exists(),"CATALOG_NO_ORPHAN_OVERWRITE")
                                    for item in cfg["publication_custody_refs"].values():pin(item["original_observation_ref"])
                                    c.worker_runtime(RUN)
                                    folder=RUN/"continuation";restore=None
                                    marker=append_json(folder/(POLICY_CATALOG_NAME+"_STARTED.json"),dict(
                                        research_id=ID,phase=POLICY_CATALOG_PHASE,configuration_ref=review["configuration_ref"],
                                        source_configuration_ref=cfg["source_configuration_ref"],review_ref=review_ref,root_last_ref=root_ref,
                                        human_authorization_ref=cfg["human_authorization_ref"],human_transcript_ref=cfg["human_transcript_ref"],
                                        approved1655_ids_ref=cfg["approved1655_ids_ref"],ledger_prestate=cfg["ledger_prestate"],
                                        limited_second_ADMIN_planned=1655,scientific_retries=0))
                                    try:
                                        from datetime import datetime,timezone
                                        utc=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
                                        restore=sg.catalog_limited1655_restore_transaction(c,journal.db,cfg,ids,pending,human,utc)
                                        restore_ref=append_json(folder/(POLICY_CATALOG_NAME+"_RESTORE_RECEIPT.json"),restore)
                                        with sg.original_once_scope(c,human["original_node_ids"]):
                                            provider=w.RiskProvider(RUN)
                                            w.risk_policies(RUN,provider,roles=cfg["recovery_roles"])
                                            require(all(journal.status(n)["status"] in TERMINAL for n in ids),"CATALOG_ORIGINAL3394_NATURAL_TERMINAL")
                                            w.freeze_policy_terminal(RUN)
                                        after_rows=journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id").fetchall()
                                        after_events=journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence").fetchall()
                                        history=sg.catalog_limited1655_history(before_rows,before_events,after_rows,after_events,
                                            ids,pending,human,review_ref,root_ref,utc)
                                        require(journal.db.execute("SELECT design_sha256 FROM authority").fetchall()==authority,"CATALOG_AUTHORITY_PRESERVED")
                                        for value in cfg["preserved_refs"].values():pin(value)
                                        for item in cfg["publication_custody_refs"].values():pin(item["immutable_custody_ref"])
                                        result=dict(research_id=ID,phase=POLICY_CATALOG_PHASE,status="ORIGINAL_OWNER_LIMITED1655_STAGE_TERMINAL",
                                            marker_ref=marker,restore_receipt_ref=restore_ref,history=history,
                                            output_refs=dict(policy_terminal=ref(RUN/"POLICY_TERMINAL.json"),score_assembly=ref(RUN/"SCORE_ASSEMBLY.json")),
                                            ledger_poststate=dict(nodes_sha256=digest(after_rows),events_sha256=digest(after_events),event_count=len(after_events)),
                                            second_ADMIN_events=1655,third_ADMIN_events=0,scientific_retries=0,
                                            all_task_complete=False,outer_feedback=False,historical_whole_joint_module_identity="UNKNOWN")
                                        append_json(folder/(POLICY_CATALOG_NAME+"_COMPLETE.json"),result);return result
                                    except BaseException:
                                        append_json(folder/(POLICY_CATALOG_NAME+"_FAILURE.json"),dict(research_id=ID,phase=POLICY_CATALOG_PHASE,
                                            marker_ref=marker,error=traceback.format_exc(),restoration_result=restore,
                                            restoration_commit_state="COMMITTED" if restore is not None else "UNKNOWN_UNTIL_FINITE_OWNER_AUDIT",
                                            scientific_retries=0,all_task_complete=False))
                                        raise
                                finally:journal.db.close()
                finally:_RISK_ACTIVE_CONTROLLER=previous;_CATALOG_ORIGINAL_LOCK_HELD=False


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("phase",choices=(*PHASES,SOURCE_RECOVERY_PHASE,RISK_PHASE,RISK_PENDING_PHASE,*TAIL_PHASES,POLICY_REBOOT_PHASE,POLICY_ZERO_PHASE,POLICY_CHECKPOINT_PHASE,POLICY_CATALOG_PHASE))
    args=parser.parse_args();execute(args.run,args.phase)


if __name__=="__main__":main()
