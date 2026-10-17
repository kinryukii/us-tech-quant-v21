"""Pure synthetic continuation tests: stdlib fake owners/SQLite/files only.

Do not import canonical research owners, read the real run, or execute estimators.
"""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
import pytest

SOURCE=Path("D:/us-tech-quant/scripts/research/a2/training/full_selector_engineering_continuation.py")
ROLES=("RIDGE","ELASTIC_NET","HUBER","LOGIT","LINEAR_SVM","EBM","RF","EXTRA_TREES","HGB","XGB","LGB","CAT","MLP","RESNET","FT_TRANSFORMER","PAIRWISE_RANKER","LISTWISE_MLP","LAMBDAMART","QUANTILE_HGB","GAUSSIAN_MLP","MT_RIDGE","MT_EXTRA_TREES","MT_MLP")
MEMBERS=("RIDGE","HGB","XGB","CAT","MLP","QUANTILE_HGB")
METHODS=("equal","median","simplex","nnls","ridge_stack","elastic_stack","hgb_stack","mlp_stack","linear_gate","mlp_gate","ridge_then_hgb","hgb_then_ridge")

@pytest.fixture
def e():
    before={x for x in sys.modules if x.startswith("scripts.research")}
    spec=importlib.util.spec_from_file_location("_synthetic_continuation",SOURCE)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert {x for x in sys.modules if x.startswith("scripts.research")}==before
    return mod


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding="utf-8")
    return path

@pytest.fixture
def bank(e,tmp_path,monkeypatch):
    run=tmp_path/"run";repo=tmp_path/"repo";run.mkdir();(run/"models").mkdir();(run/"continuation").mkdir()
    monkeypatch.setattr(e,"RUN",run);monkeypatch.setattr(e,"REPO",repo)
    wf=repo/"scripts/research/a2/training/full_selector_workflow.py";wf.parent.mkdir(parents=True);wf.write_text("# synthetic workflow")
    a94=repo/"a94.py";a94.write_text("# synthetic original a94")
    core=tuple(dict.fromkeys(("RIDGE","HGB","LAMBDAMART",*MEMBERS)))
    nodes=[dict(node_id="MODEL|"+r+"|cut|MID|seed|None",kind="ESTIMATOR",role=r) for r in ROLES]
    nodes += [dict(node_id="META|"+m,kind="META_MODEL",method=m) for m in METHODS if m not in ("equal","median")]
    nodes += [dict(node_id="ACCOUNT|"+str(i),kind="CONTINUOUS_ACCOUNT") for i in range(66)]
    # Real core names in fixture account axis enable the original API spy.
    nodes[23+10:]=[dict(node_id="ACCOUNT|"+r,kind="CONTINUOUS_ACCOUNT") for r in ("RAW","RIDGE","HGB","LAMBDAMART","FUSION_equal",*("other"+str(i) for i in range(61)))]
    design=dict(research_id=e.ID,sources={str(wf):e.sha(wf),str(a94):e.sha(a94)},dag=dict(nodes=nodes))
    write(run/"DESIGN_FREEZE.json",design)
    for name in ("FREEZE_ACCEPTANCE.json","input_manifest.json","run_config.json","risk_inputs.json"):write(run/name,{"synthetic":True})
    monkeypatch.setattr(e,"ORIGINAL_PINS",{n:e.sha(run/n) for n in e.ORIGINAL_PINS})
    write(run/"PRIMARY_CORE_EXECUTION_STARTED.json",dict(research_id=e.ID,design_ref=e.ref(run/"DESIGN_FREEZE.json"),source_ref=e.ref(wf)))
    write(run/"EXECUTION_FAILURE.json",dict(research_id=e.ID,scientific_retries=0,error="EXECUTABLE_SOURCE_CHANGED:synthetic source gate"))
    db=sqlite3.connect(run/"TASK_LEDGER.sqlite")
    db.execute("CREATE TABLE nodes(node_id TEXT,kind TEXT,status TEXT,entered INTEGER,identity TEXT,artifact TEXT,error TEXT)")
    db.execute("CREATE TABLE events(sequence INTEGER,node_id TEXT,action TEXT,payload TEXT,utc TEXT)")
    db.execute("CREATE TABLE authority(design_sha256 TEXT)")
    db.execute("INSERT INTO authority VALUES (?)",(e.sha(run/"DESIGN_FREEZE.json"),))
    model=run/"models/synthetic_model.joblib";model.write_bytes(b"synthetic-only-not-loaded")
    for node in nodes:
        done=node.get("role") in core
        db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?)",(node["node_id"],node["kind"],"COMPLETE" if done else "NAMED",1 if done else 0,"f"*64 if done else None,json.dumps(e.ref(model)) if done else None,None))
    db.commit();db.close()
    class Journal:
        def __init__(self,*args):self.db=sqlite3.connect(run/"TASK_LEDGER.sqlite");self.design=design
        def status(self,node):
            row=self.db.execute("SELECT status,entered,identity,artifact,error FROM nodes WHERE node_id=?",(node,)).fetchone()
            return dict(zip(("status","entered","identity","artifact","error"),row))
    journal=Journal();snap=e.public_snapshot(e.ledger_snapshot(journal,run));journal.db.close()
    manifest=dict(schema="FULL_SELECTOR_ENGINEERING_CONTINUATION_R1",research_id=e.ID,run=str(run),entry_ref=e.ref(e.__file__),
        original_refs={n:e.ref(run/n) for n in e.ORIGINAL_PINS},original_start_ref=e.ref(run/"PRIMARY_CORE_EXECUTION_STARTED.json"),original_failure_ref=e.ref(run/"EXECUTION_FAILURE.json"))
    mp=write(run/"continuation/ENGINEERING_CONTINUATION_MANIFEST_R1.json",manifest)
    cold=write(run/"synthetic_cold.json",{"numeric_entries":0})
    review=dict(schema="FULL_SELECTOR_ENGINEERING_PHASE_ACCEPTANCE_R1",research_id=e.ID,status="PASS",phase="remaining-alpha",
        independent_from_entry_writer=True,original_worker_terminal=True,scientific_retry_authorized=False,
        manifest_ref=e.ref(mp),entry_ref=e.ref(e.__file__),original_failure_ref=manifest["original_failure_ref"],core_exit_stage="EQUAL_SOURCE_GATE",
        core_complete_reuse_verified=True,core_roles=list(core),ledger_prestate=snap,account_metadata_cold_pass=True,account_metadata_cold_ref=e.ref(cold),
        fixed_remaining_roles=[r for r in ROLES if r not in core],fixed_remaining_fusions=[m for m in METHODS if m!="equal"],equal_unattempted=True,core_policy_terminal_ref=None)
    calls=[]
    @contextmanager
    def lock(*args):calls.append("lock");yield;calls.append("unlock")
    def mark_roles(run,roles):
        calls.append(("primary",roles))
        db=sqlite3.connect(run/"TASK_LEDGER.sqlite")
        for role in roles:db.execute("UPDATE nodes SET status='COMPLETE',entered=1,identity=?,artifact=? WHERE node_id LIKE ?",("e"*64,json.dumps(e.ref(model)),"MODEL|"+role+"|%"))
        db.commit();db.close()
    def fusion(run,methods):
        calls.append(("fusion",methods))
        db=sqlite3.connect(run/"TASK_LEDGER.sqlite")
        for method in methods:db.execute("UPDATE nodes SET status='COMPLETE',entered=1,identity=?,artifact=? WHERE node_id=?",("d"*64,json.dumps(e.ref(model)),"META|"+method))
        db.commit();db.close()
    policy=run/"predictions/policy_FUSION_equal.parquet";policy.parent.mkdir()
    raw=run/"predictions/policy_RAW.parquet";raw.write_bytes(b"synthetic-policy")
    def publication(path):
        value=dict(path=str(path),sha256=e.sha(path),identity_sha256="1"*64,frame_sha256="2"*64,rows=100,dates=3,keys_sha256="3"*64,identity={"synthetic":True})
        write(Path(str(path)+".json"),value);return value
    raw_ref=publication(raw)
    def assembly(*args):
        calls.append("assembly");paths={"RAW":raw_ref}
        if policy.exists() and Path(str(policy)+".json").exists():paths["FUSION_equal"]=e.read(Path(str(policy)+".json"))
        return dict(score_paths=paths)
    def accounts(run,policy_terminal):
        calls.append("accounts");db=sqlite3.connect(run/"TASK_LEDGER.sqlite")
        for role in policy_terminal["policy_refs"]:db.execute("UPDATE nodes SET status='COMPLETE',entered=1,identity=?,artifact=? WHERE node_id=?",("c"*64,json.dumps(e.ref(model)),"ACCOUNT|"+role))
        db.commit();db.close();write(run/"CORE_BASE_ACCOUNT_TERMINAL.json",{"complete":list(policy_terminal["policy_refs"])})
    controller=SimpleNamespace(_TaskLedger=Journal,worker_runtime=lambda *args:calls.append("runtime"),FUSION_MEMBERS=MEMBERS,FUSIONS=METHODS,
        CORE=("RAW","RIDGE","HGB","LAMBDAMART","FUSION_equal","RISK_DIAG"),learners=SimpleNamespace(PARADIGMS=ROLES),train_primary=mark_roles,train_fusion=fusion,assemble_selection=assembly)
    workflow=SimpleNamespace(_worker_lock=lock,run_accounts=accounts,_immutable_account_json=e.append_json)
    account=SimpleNamespace(metadata_preflight=lambda *args:calls.append("metadata"))
    monkeypatch.setattr(e,"owners",lambda:(controller,workflow,account))
    def publish_review(phase="remaining-alpha"):
        review["phase"]=phase;review["manifest_ref"]=e.ref(mp)
        write(run/"continuation"/(e.PHASE_NAMES[phase]+"_ACCEPTANCE.json"),review)
    publish_review()
    return SimpleNamespace(run=run,repo=repo,wf=wf,a94=a94,model=model,policy=policy,design=design,manifest=manifest,mp=mp,review=review,Journal=Journal,
        calls=calls,c=controller,w=workflow,a=account,publish=publish_review,publication=publication)


def test_import_is_stdlib_only_and_never_loads_canonical_owners(e):
    assert e.PHASES==("core-account","remaining-alpha")


def test_fixed_remaining_stage_uses_only_original_16_11(e,bank):
    result=e.execute(bank.run,"remaining-alpha")
    assert ("primary",tuple(bank.review["fixed_remaining_roles"])) in bank.calls
    assert ("fusion",tuple(bank.review["fixed_remaining_fusions"])) in bank.calls
    assert "metadata" not in bank.calls and "accounts" not in bank.calls
    assert result["risk_pending"] and not result["all_task_complete"]
    assert bank.calls.count("runtime")==1
    assert e.read(bank.run/"EXECUTION_FAILURE.json")["error"].startswith("EXECUTABLE_SOURCE_CHANGED")
    with pytest.raises(ValueError,match="PHASE_ALREADY_STARTED"):
        e.execute(bank.run,"remaining-alpha")

@pytest.mark.parametrize("name",list(("DESIGN_FREEZE.json","FREEZE_ACCEPTANCE.json","input_manifest.json","run_config.json","risk_inputs.json")))
def test_changed_freeze_input_rejected_before_runtime(e,bank,name):
    (bank.run/name).write_text("drift")
    with pytest.raises(ValueError,match="ORIGINAL_FREEZE_INPUT_OR_GATE_CHANGED"):e.execute(bank.run,"remaining-alpha")
    assert "runtime" not in bank.calls


def test_a94_drift_without_owner_correction_is_rejected(e,bank):
    bank.a94.write_text("other task changed source")
    with pytest.raises(ValueError,match="EXECUTABLE_SOURCE_CHANGED"):e.execute(bank.run,"remaining-alpha")
    assert "runtime" not in bank.calls

@pytest.mark.parametrize("field,value",[("original_worker_terminal",False),("independent_from_entry_writer",False),("scientific_retry_authorized",True),("status","REVIEW")])
def test_unreviewed_or_live_terminal_rejected(e,bank,field,value):
    bank.review[field]=value;bank.publish()
    with pytest.raises(ValueError,match="TERMINAL_BOUND_INDEPENDENT_PHASE_REVIEW_REQUIRED"):e.execute(bank.run,"remaining-alpha")
    assert "runtime" not in bank.calls


def test_active_native_worker_lock_does_not_call_authority_or_runtime(e,bank):
    @contextmanager
    def locked(*a):raise ValueError("SINGLE_WORKER_PROCESS_LOCK_HELD");yield
    bank.w._worker_lock=locked
    with pytest.raises(ValueError,match="SINGLE_WORKER_PROCESS_LOCK_HELD"):e.execute(bank.run,"remaining-alpha")
    assert bank.calls==[]

@pytest.mark.parametrize("status,entered",[("STARTED",0),("STARTED",1),("NAMED",1)])
def test_started_or_disguised_entry_tail_rejected(e,bank,status,entered):
    journal=bank.Journal();journal.db.execute("UPDATE nodes SET status=?,entered=? WHERE node_id LIKE 'MODEL|MLP|%'",(status,entered));journal.db.commit()
    with pytest.raises(ValueError,match="STARTED_SCIENTIFIC_TAIL|NAMED_NODE_HAS_PRIOR_ENTRY"):e.ledger_snapshot(journal,bank.run)
    journal.db.close()


def test_complete_artifact_drift_blocks_before_runtime(e,bank):
    bank.model.write_bytes(b"modified")
    with pytest.raises(ValueError,match="PHYSICAL_REFERENCE_CHANGED"):e.execute(bank.run,"remaining-alpha")
    assert "runtime" not in bank.calls


def test_complete_identity_changed_from_review_rejected(e,bank):
    j=bank.Journal();j.db.execute("UPDATE nodes SET identity=? WHERE node_id LIKE 'MODEL|MLP|%'",("a"*64,));j.db.commit();j.db.close()
    with pytest.raises(ValueError,match="TERMINAL_BOUND_LEDGER_CHANGED"):e.execute(bank.run,"remaining-alpha")

@pytest.mark.parametrize("status,entered",[("FAILED",0),("FAILED",1),("COMPLETE",1),("SOURCE_NOT_TESTABLE",0)])
def test_account_nonzero_or_failed_slot_never_retried(e,bank,status,entered):
    bank.publish("core-account");j=bank.Journal()
    artifact=json.dumps(e.ref(bank.model)) if status=="COMPLETE" else None
    j.db.execute("UPDATE nodes SET status=?,entered=?,identity=?,artifact=? WHERE node_id='ACCOUNT|RAW'",(status,entered,"a"*64 if status=="COMPLETE" else None,artifact));j.db.commit()
    bank.review["ledger_prestate"]=e.public_snapshot(e.ledger_snapshot(j,bank.run));bank.publish("core-account")
    with pytest.raises(ValueError,match="ORIGINAL_ACCOUNT_ZERO_ENTRY_BOUNDARY_CHANGED"):e.validate_phase_nodes(j,bank.run,"core-account",bank.review)
    j.db.close();assert "accounts" not in bank.calls


def test_correction_context_is_exact_owner_api_not_sha_waiver(e,bank):
    correction=write(bank.run/"ENGINEERING_SOURCE_CORRECTION_R1.json",{"synthetic_reviewed":True})
    bank.manifest["engineering_source_configuration_ref"]=e.ref(correction);write(bank.mp,bank.manifest)
    bank.review["engineering_source_configuration_ref"]=e.ref(correction);bank.publish()
    with pytest.raises(ValueError,match="EXACT_OWNER_SOURCE_CORRECTION_CONTEXT_REQUIRED"):e.execute(bank.run,"remaining-alpha")
    called=[]
    @contextmanager
    def context(value):called.append(value);yield
    bank.c.engineering_source_configuration=context
    e.execute(bank.run,"remaining-alpha")
    assert called==[e.ref(correction)]


def test_equal_first_transform_only_uses_zero_fit_original_owner(e,bank):
    terminal=e.core_policy_terminal(bank.c,bank.w,bank.run,bank.review,bank.design)
    assert ("fusion",("equal",)) in bank.calls
    assert not any(isinstance(x,tuple) and x[0]=="primary" for x in bank.calls)
    assert set(terminal["policy_refs"])=={"RAW"}
    bank.review["core_policy_terminal_ref"]=e.ref(bank.run/"CORE_BASE_POLICY_TERMINAL.json")
    before=list(bank.calls)
    e.core_policy_terminal(bank.c,bank.w,bank.run,bank.review,bank.design)
    assert bank.calls==before+["assembly"]

@pytest.mark.parametrize("relative",["predictions/policy_FUSION_equal.parquet","predictions/failure_FUSION_equal.json","predictions/annual_native/FUSION_equal_2024.parquet","predictions/fusion_receipt_equal_2025.json"])
def test_equal_any_existing_prefix_cannot_retransform(e,bank,relative):
    p=bank.run/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"prior prefix")
    with pytest.raises(ValueError,match="EQUAL_ALREADY_ATTEMPTED_OR_HAS_ARTIFACT"):e.core_policy_terminal(bank.c,bank.w,bank.run,bank.review,bank.design)
    assert not any(isinstance(x,tuple) for x in bank.calls)


def test_core_marker_after_metadata_accounts_and_restores_overlay(e,bank,monkeypatch):
    bank.publish("core-account");installed=[]
    @contextmanager
    def overlay(*a):installed.append(True);yield {"candidate_ref":{"synthetic":True}};installed.append(False)
    monkeypatch.setattr(e,"account_overlay",overlay)
    result=e.execute(bank.run,"core-account")
    assert bank.calls.index("metadata")<bank.calls.index(("fusion",("equal",)))<bank.calls.index("accounts")
    assert installed==[True,False] and not result["risk_estimates_started"]
    assert (bank.run/"PRIMARY_CORE_EXECUTION_COMPLETE.json").is_file()
    assert e.read(bank.run/"EXECUTION_FAILURE.json")["scientific_retries"]==0


def test_source_cold_failure_creates_no_phase_marker_or_account_entry(e,bank,monkeypatch):
    bank.publish("core-account")
    @contextmanager
    def overlay(*a):yield {}
    monkeypatch.setattr(e,"account_overlay",overlay)
    def fail(*a):raise ValueError("cold source failed")
    bank.a.metadata_preflight=fail
    with pytest.raises(ValueError,match="cold source failed"):e.execute(bank.run,"core-account")
    assert "accounts" not in bank.calls and not (bank.run/"continuation/CORE_ACCOUNT_CONTINUATION_R1_STARTED.json").exists()


def test_native_account_failure_keeps_new_marker_and_original_error(e,bank,monkeypatch):
    bank.publish("core-account")
    @contextmanager
    def overlay(*a):yield {}
    monkeypatch.setattr(e,"account_overlay",overlay)
    def fail(*a,**kw):raise ValueError("original owner prefix failed")
    bank.w.run_accounts=fail
    old=(bank.run/"EXECUTION_FAILURE.json").read_bytes()
    with pytest.raises(ValueError,match="original owner prefix failed"):e.execute(bank.run,"core-account")
    assert (bank.run/"EXECUTION_FAILURE.json").read_bytes()==old
    assert (bank.run/"continuation/CORE_ACCOUNT_CONTINUATION_R1_FAILURE.json").exists()
    assert not (bank.run/"PRIMARY_CORE_EXECUTION_COMPLETE.json").exists()

@pytest.fixture
def overlay_bank(e,tmp_path,monkeypatch):
    repo=tmp_path/"repo";base=repo/"scripts/research/a2/data/full_selector_account_inputs.py";base.parent.mkdir(parents=True)
    candidate=tmp_path/"account_inputs_r5.py"
    adapter=tmp_path/"current_adapter.py";cash=tmp_path/"current_cash.py";old_a=tmp_path/"old_adapter.py";old_c=tmp_path/"old_cash.py"
    for p in (adapter,cash,old_a,old_c):p.write_text("# synthetic "+p.name)
    ordinary=write(tmp_path/"v17.json",{})
    own={"cash_adapter":e.ref(adapter),"cash_owner":e.ref(cash)}
    tx=[dict(role=r,original_ref=dict(path=own[r]["path"],sha256=e.sha(p)),custody_ref=e.ref(p)) for r,p in (("cash_adapter",old_a),("cash_owner",old_c))]
    source=SimpleNamespace(__file__=str(adapter),cash=SimpleNamespace(__file__=str(cash)))
    fake=ModuleType("synthetic_account_owner");fake.source=source;monkeypatch.setitem(sys.modules,"synthetic_account_owner",fake)
    common="from pathlib import Path\nfrom synthetic_account_owner import source\nREPO=Path(__file__).resolve().parents[4]\nDEFAULT_REFS="+repr({"ordinary_sources":e.ref(ordinary)})+"\ndef load_account_inputs(run):return custody_reader([])\n"
    base.write_text(common+"OWNERS={}\ndef custody_reader(tx):return 'original'\n",encoding="utf-8")
    common += "def identity_links(*args,**kwargs):return 'original links'\n"+"def metadata_preflight(*args):return 'original metadata'\n"
    candidate.write_text(common+"OWNERS="+repr(own)+"\nB_PRODUCER_TRANSPORT="+repr(tuple(tx))+"\ndef custody_reader(tx):return 'transport'\n",encoding="utf-8")
    canonical=ModuleType("synthetic_original_account");canonical.__file__=str(base);exec(compile(base.read_text(),str(base),"exec"),canonical.__dict__)
    base.write_text(base.read_text()+"def identity_links(*args,**kwargs):return 'original links'\ndef metadata_preflight(*args):return 'original metadata'\n")
    canonical=ModuleType("synthetic_original_account");canonical.__file__=str(base);exec(compile(base.read_text(),str(base),"exec"),canonical.__dict__)
    monkeypatch.setattr(e,"REPO",repo);monkeypatch.setattr(e,"ACCOUNT_BASE",base);monkeypatch.setattr(e,"ACCOUNT_BASE_SHA",e.sha(base))
    monkeypatch.setattr(e,"ACCOUNT_CANDIDATE",candidate);monkeypatch.setattr(e,"ACCOUNT_CANDIDATE_SHA",e.sha(candidate))
    cfg=dict(base_ref=e.ref(base),candidate_ref=e.ref(candidate),current_owner_refs=own,old_custody_refs=tx,ordinary_sources_ref=e.ref(ordinary))
    return SimpleNamespace(account=canonical,manifest={"account_overlay":cfg},base=base,candidate=candidate,ordinary=ordinary,adapter=adapter,old_a=old_a)

@pytest.mark.parametrize("fail",[False,True])
def test_three_global_overlay_actual_filename_and_finally_restore(e,overlay_bank,fail):
    b=overlay_bank;loader=b.account.load_account_inputs;original=b.account.custody_reader;owners=b.account.OWNERS
    with pytest.raises(RuntimeError) if fail else __import__("contextlib").nullcontext():
        with e.account_overlay(b.account,b.manifest) as receipt:
            assert b.account.load_account_inputs is loader and loader(None)=="transport"
            assert b.account.custody_reader.__code__.co_filename==str(b.candidate.resolve())
            assert receipt["old_sources_executed"] is False and receipt["report_scope_enabled"] is False
            if fail:raise RuntimeError("test finally")
    assert b.account.custody_reader is original and b.account.OWNERS is owners
    assert not hasattr(b.account,"B_PRODUCER_TRANSPORT")

@pytest.mark.parametrize("asset",["candidate","base","adapter","old_a"])
def test_overlay_all_physical_refs_guarded(e,overlay_bank,asset):
    getattr(overlay_bank,asset).write_text("drift")
    with pytest.raises(ValueError,match="PHYSICAL_REFERENCE_CHANGED"): 
        with e.account_overlay(overlay_bank.account,overlay_bank.manifest):pass


def test_overlay_cannot_change_business_function_even_rehashed(e,overlay_bank,monkeypatch):
    b=overlay_bank;b.candidate.write_text(b.candidate.read_text().replace("def load_account_inputs(run):return custody_reader([])","def load_account_inputs(run):return 'new engine'"))
    monkeypatch.setattr(e,"ACCOUNT_CANDIDATE_SHA",e.sha(b.candidate));b.manifest["account_overlay"]["candidate_ref"]=e.ref(b.candidate)
    with pytest.raises(ValueError,match="ACCOUNT_OVERLAY_BUSINESS_AST_CHANGED"):
        with e.account_overlay(b.account,b.manifest):pass


def test_v17_report_activation_is_explicitly_rejected(e,overlay_bank):
    b=overlay_bank;write(b.ordinary,{"report_same_file_cash_table_scope":True})
    b.manifest["account_overlay"]["ordinary_sources_ref"]=e.ref(b.ordinary)
    b.account.DEFAULT_REFS["ordinary_sources"]=e.ref(b.ordinary)
    with pytest.raises(ValueError,match="V17_REPORT_SCOPE_MUST_REMAIN_ABSENT"):
        with e.account_overlay(b.account,b.manifest):pass


def test_equal_complete_publication_reused_without_fusion_call(e,bank):
    bank.policy.write_bytes(b"synthetic completed equal")
    bank.review["equal_complete_policy_ref"]=bank.publication(bank.policy)
    bank.review["equal_complete_receipt_ref"]=e.ref(Path(str(bank.policy)+".json"))
    bank.review["equal_unattempted"]=False
    e.core_policy_terminal(bank.c,bank.w,bank.run,bank.review,bank.design)
    assert not any(isinstance(x,tuple) and x[0]=="fusion" for x in bank.calls)


def test_remaining_native_owner_must_leave_all_applicable_nodes_terminal(e,bank):
    bank.c.train_primary=lambda *a:bank.calls.append("incomplete-owner")
    with pytest.raises(ValueError,match="REMAINING_ALPHA_NODE_NOT_TERMINAL"):e.execute(bank.run,"remaining-alpha")
    assert not (bank.run/"continuation/REMAINING_ALPHA_CONTINUATION_R1_COMPLETE.json").exists()
    assert (bank.run/"continuation/REMAINING_ALPHA_CONTINUATION_R1_FAILURE.json").exists()


def test_partial_remaining_complete_without_policy_cannot_reenter(e,bank):
    j=bank.Journal();j.db.execute("UPDATE nodes SET status='COMPLETE',entered=1,identity=?,artifact=? WHERE node_id LIKE 'MODEL|HUBER|%'",("b"*64,json.dumps(e.ref(bank.model))))
    j.db.commit();bank.review["ledger_prestate"]=e.public_snapshot(e.ledger_snapshot(j,bank.run));j.db.close();bank.publish()
    with pytest.raises(ValueError,match="PARTIAL_ALPHA_WITHOUT_TERMINAL_PUBLICATION"):e.execute(bank.run,"remaining-alpha")
    assert not (bank.run/"continuation/REMAINING_ALPHA_CONTINUATION_R1_STARTED.json").exists()


def test_completed_remaining_policy_is_exact_reused_without_learner_callback(e,bank):
    p=bank.run/"predictions/policy_HUBER.parquet";p.write_bytes(b"fixed finished policy");full=bank.publication(p);receipt=Path(str(p)+".json")
    bank.review["preserved_alpha_refs"]={"HUBER":dict(disposition="COMPLETE",ref=full,receipt_ref=e.ref(receipt))}
    j=bank.Journal();j.db.execute("UPDATE nodes SET status='COMPLETE',entered=1,identity=?,artifact=? WHERE node_id LIKE 'MODEL|HUBER|%'",("b"*64,json.dumps(e.ref(bank.model))))
    j.db.commit();bank.review["ledger_prestate"]=e.public_snapshot(e.ledger_snapshot(j,bank.run));j.db.close();bank.publish()
    result=e.execute(bank.run,"remaining-alpha")
    primary=next(x[1] for x in bank.calls if isinstance(x,tuple) and x[0]=="primary")
    assert "HUBER" not in primary and len(primary)==15
    assert "HUBER" in result["fixed_roles"] and len(result["fixed_roles"])==16


def test_five_globals_restored_including_existing_optional_constant(e,overlay_bank):
    b=overlay_bank;saved={name:getattr(b.account,name,None) for name in e.OVERLAY_GLOBALS}
    b.account.B_PRODUCER_TRANSPORT=("preexisting-exact",);saved["B_PRODUCER_TRANSPORT"]=b.account.B_PRODUCER_TRANSPORT
    with e.account_overlay(b.account,b.manifest):
        for name in ("custody_reader","identity_links","metadata_preflight"):
            assert getattr(b.account,name).__code__.co_filename==str(b.candidate.resolve())
            assert getattr(b.account,name) is not saved[name]
    assert all(getattr(b.account,name) is saved[name] for name in e.OVERLAY_GLOBALS)


@pytest.mark.parametrize("change",["authority","missing_node","extra_node"])
def test_empty_or_changed_existing_ledger_never_gets_initialized(e,bank,change):
    j=bank.Journal()
    if change=="authority":j.db.execute("DELETE FROM authority")
    elif change=="missing_node":j.db.execute("DELETE FROM nodes WHERE node_id='ACCOUNT|RAW'")
    else:j.db.execute("INSERT INTO nodes VALUES('EXTRA','ESTIMATOR','NAMED',0,NULL,NULL,NULL)")
    j.db.commit();j.db.close()
    with pytest.raises(ValueError,match="EXISTING_LEDGER_AUTHORITY_REQUIRED|EXISTING_FINITE_NODE_SET_CHANGED"):
        e.execute(bank.run,"remaining-alpha")
    assert "runtime" not in bank.calls



def test_original_eight_field_frame_publication_is_accepted(e,bank):
    bank.policy.write_bytes(b"original-eight-field-schema")
    value=bank.publication(bank.policy)
    assert e.frame_receipt(value,e.ref(Path(str(bank.policy)+".json")))==bank.policy.resolve()
    assert set(value)==e.FRAME_RECEIPT_FIELDS


@pytest.mark.parametrize("change",["missing_sidecar","different_sidecar","two_fields_only","extra_field"])
def test_original_frame_sidecar_and_schema_are_required(e,bank,change):
    bank.policy.write_bytes(b"original-eight-field-schema");value=bank.publication(bank.policy);sidecar=Path(str(bank.policy)+".json")
    if change=="missing_sidecar":sidecar.unlink()
    elif change=="different_sidecar":write(sidecar,dict(value,rows=200))
    elif change=="two_fields_only":value={k:value[k] for k in ("path","sha256")}
    else:value["extra"]="not original schema"
    with pytest.raises(ValueError,match="EXACT_FRAME_RECEIPT_SIDECAR_REQUIRED|EXACT_ORIGINAL_FRAME_RECEIPT_REQUIRED"):
        e.frame_receipt(value)


@pytest.mark.parametrize("change",["receipt_unbound","missing_from_assembly","failure_conflict"])
def test_equal_complete_cannot_silently_turn_into_raw_only_terminal(e,bank,change):
    bank.policy.write_bytes(b"complete-equal");bank.review["equal_complete_policy_ref"]=bank.publication(bank.policy)
    bank.review["equal_complete_receipt_ref"]=e.ref(Path(str(bank.policy)+".json"));bank.review["equal_unattempted"]=False
    if change=="receipt_unbound":bank.review.pop("equal_complete_receipt_ref")
    elif change=="missing_from_assembly":bank.c.assemble_selection=lambda *args:{"score_paths":{}}
    else:write(bank.run/"predictions/failure_FUSION_equal.json",{"status":"FAILED"})
    with pytest.raises(ValueError,match="EQUAL_COMPLETE_SIDECAR_REVIEW_REQUIRED|EQUAL_COMPLETE_PUBLICATION_MISSING|EQUAL_EXACT_REUSE_OR_FAILURE_CONFLICT"):
        e.core_policy_terminal(bank.c,bank.w,bank.run,bank.review,bank.design)
    assert not (bank.run/"CORE_BASE_POLICY_TERMINAL.json").exists()
