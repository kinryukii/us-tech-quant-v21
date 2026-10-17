"""Synthetic metadata/fake-owner contract cases only; no project business/data."""
import ast
from contextlib import contextmanager
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

SOURCE=Path(__file__).with_name("full_selector_post_primary_fusion_continuation_R1.py")
spec=importlib.util.spec_from_file_location("fusion_source_only_candidate",SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture_state():
 rows={};nodes={};events=[]
 def event(n,a,p):
  events.append((len(events)+1,n,a,json.dumps(p),"2026-10-11T00:00:00Z"))
 def learned(n,k,status="COMPLETE",entered=1,role=None):
  identity={"node":n};token=m.digest(identity);artifact={"path":str(m.RUN/"models"/(m.digest(n)+".joblib")),"sha256":"a"*64}
  nodes[n]={"node_id":n,"kind":k,**({"role":role} if role else {})}
  rows[n]=(n,k,status,entered,token,json.dumps(artifact) if status=="COMPLETE" else None,None if status=="COMPLETE" else "original scientific failure")
  event(n,"BEGIN",identity);event(n,"BACKEND_ENTER",{})
  event(n,status,artifact if status=="COMPLETE" else {"entered":1,"error":"synthetic failure"})
 for k,count in (("ESTIMATOR",327),("CALIBRATOR",10),("SCALER",5)):
  for i in range(count):learned(f"MODEL|OLD_{k}_{i}|cut|MID|seed|None",k)
 for i in range(9):learned(f"MODEL|ELASTIC_NET|cut{i}|MID|seed|None","ESTIMATOR","FAILED")
 source=next(iter(rows));artifact=json.loads(rows[source][5])
 for i in range(3):
  n=f"MODEL|ALIAS_{i}|cut|MID|seed|None";nodes[n]={"node_id":n,"kind":"ESTIMATOR"};rows[n]=(n,"ESTIMATOR","COMPLETE",0,rows[source][4],rows[source][5],None);event(n,"EXACT_ALIAS",{"source_node":source,"artifact":artifact,"actual_backend_entries":0})
 n="MODEL|ELASTIC_NET|blocked|MID|seed|None";nodes[n]={"node_id":n,"kind":"ESTIMATOR"};rows[n]=(n,"ESTIMATOR","BLOCKED_DEPENDENCY",0,None,None,"dependency");event(n,"BLOCKED_DEPENDENCY",{"reason":"dependency"})
 n=m.TARGET;nodes[n]={"node_id":n,"kind":"ESTIMATOR","role":"FT_TRANSFORMER"};artifact={"path":str(m.RUN/"models"/"target.joblib"),"sha256":"b"*64};rows[n]=(n,"ESTIMATOR","COMPLETE",1,m.TOKEN,json.dumps(artifact),None)
 event(n,"BEGIN",{"legacy_target":True});event(n,"BACKEND_ENTER",{})
 assert len(events)==1059
 event(n,"REBOOT_REPLAY_RESERVED",{});event(n,"REBOOT_REPLAY_ENTER",{"paid_additional_attempt":1});event(n,"COMPLETE",artifact)
 for i in range(164):learned(f"MODEL|NEW_{i}|cut|MID|seed|None","ESTIMATOR")
 assert len(events)==1554
 for k,count in (("META_MODEL",32),("META_SCALER",28),("META_TARGET_SCALE",14)):
  for i in range(count):
   method=m.METHODS[1:][i%10];n=f"{k}|{method}|{i}";nodes[n]={"node_id":n,"kind":k,"method":method};rows[n]=(n,k,"NAMED",0,None,None,None)
 for i in range(144):
  n=f"HYBRID|{i}";k="HYBRID_ESTIMATOR" if i<120 else "HYBRID_SCALER";nodes[n]={"node_id":n,"kind":k};rows[n]=(n,k,"NAMED",0,None,None,None)
 for n,k in (("RISK|one","RISK_LEARNED_UNIT"),("ACCOUNT|one","CONTINUOUS_ACCOUNT")):
  nodes[n]={"node_id":n,"kind":k};rows[n]=(n,k,"NAMED",0,None,None,None)
 rows=sorted(rows.values());design={"dag":{"nodes":list(nodes.values())}}
 boundary={"actual_sql_observation":{"node_count":len(rows),"events_sha256":m.digest(events),"nodes_sha256":m.digest(rows)}}
 return rows,events,design,boundary

def terminal_state(status="COMPLETE"):
 rows,events,design,boundary=fixture_state();byid={v[0]:v for v in rows}
 for n in sorted(m.scope_nodes(design)):
  old=byid[n];identity={"fusion":n};token=m.digest(identity);artifact={"path":str(m.RUN/"models"/(m.digest(n)+".joblib")),"sha256":"d"*64}
  def event(a,p):events.append((len(events)+1,n,a,json.dumps(p),"2026-10-11T01:00:00Z"))
  if status=="BLOCKED_DEPENDENCY":byid[n]=(n,old[1],status,0,None,None,"dependency");event(status,{"reason":"dependency"})
  else:
   byid[n]=(n,old[1],status,1,token,json.dumps(artifact) if status=="COMPLETE" else None,None if status=="COMPLETE" else "new fusion scientific failure")
   event("BEGIN",identity);event("BACKEND_ENTER",{});event(status,artifact if status=="COMPLETE" else {"entered":1,"error":"synthetic failure"})
 return sorted(byid.values()),events,design,boundary

def config():
 refs={k:dict(path=str(v[0].resolve()),sha256=v[1]) for k,v in m.HISTORY.items()}
 entry={"path":str(m.ENTRY.resolve()),"sha256":"1"*64};test={"path":str(m.TEST.resolve()),"sha256":"2"*64}
 cfg=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_CONFIGURATION_R1",research_id=m.ID,phase=m.NAME,entry_ref=entry,test_ref=test,boundary_ref=refs["boundary_ref"],prior_failure_ref=refs["prior_failure_ref"],source_configuration_ref={"path":str(m.R4.resolve()),"sha256":"3"*64},controller_ref={"path":str(m.CONTROLLER.resolve()),"sha256":"4"*64},source_review_ref={"path":str(m.REVIEW.resolve()),"sha256":"5"*64},authority_ref=refs["authority_ref"],fixed_methods=list(m.METHODS),first_fusion_entry_only=True,new_backend_replays_authorized=0,paid_cap=738)
 return cfg,entry,test,refs

def acceptance():
 cfg,entry,test,refs=config();ref=lambda p:{"path":str(p.resolve()),"sha256":"8"*64};cfg_ref=ref(m.CONFIG);cold_ref=ref(m.COLD);admission_ref=ref(m.ADMISSION)
 state={"ledger":"unchanged"}
 cold=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_COLD_R1",status="PASS",research_id=m.ID,actual_cold=True,synthetic=False,config_ref=cfg_ref,entry_ref=entry,boundary_ref=refs["boundary_ref"],source_review_ref=cfg["source_review_ref"],business_entry_calls=0,model_deserialization_calls=0,forecast_or_label_value_reads=0,phase_marker_writes=0,economic_reads=0,source_and_sql_unchanged=True,source_guard_passed=True,registry_metadata_scope_passed=True,numerical_body_sentinel_active=True,metadata_contexts_restored=True,before=state,after=state)
 accept=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_ACCEPTANCE_R1",research_id=m.ID,status="PASS",independent_from_entry_writer=True,config_ref=cfg_ref,entry_ref=entry,boundary_ref=refs["boundary_ref"],source_review_ref=cfg["source_review_ref"],actual_cold_ref=cold_ref,admission_review_ref=admission_ref,old_workers_gone=True,first_fusion_entry_only=True)
 args=(cfg_ref,entry,refs["boundary_ref"],cfg["source_review_ref"],admission_ref,cold_ref)
 return accept,cold,args

def test_actual_shape_prestate_positive():
 result=m.validate_metadata(*fixture_state());assert result["event_count"]==1554 and result["cumulative_paid_alpha_attempts"]==517 and result["remaining_alpha_upper"]==735

@pytest.mark.parametrize("status",["COMPLETE","FAILED","BLOCKED_DEPENDENCY"])
def test_terminal_owner_typed_paths_positive(status):
 result=m.validate_metadata(*terminal_state(status),terminal=True)
 assert result["cumulative_paid_alpha_attempts"]==(517 if status=="BLOCKED_DEPENDENCY" else 591)

@pytest.mark.parametrize("index,value",[(2,"STARTED"),(3,1),(4,"a"*64),(5,'{"path":"orphan"}'),(6,"earlier failure")])
def test_any_prior_fusion_entry_or_metadata_rejected(index,value):
 rows,events,design,boundary=fixture_state();n=next(iter(m.scope_nodes(design)));i=next(i for i,v in enumerate(rows) if v[0]==n);row=list(rows[i]);row[index]=value;rows[i]=tuple(row)
 with pytest.raises(ValueError):m.validate_metadata(rows,events,design,boundary)

@pytest.mark.parametrize("case",["primary_identity","target_identity","target_failed","old_failed_error","old_prefix","extra_primary_event","fusion_history","unknown_node","row_width","missing_fusion","wrong_fusion_kind","risk_entered"])
def test_metadata_contract_negative(case):
 rows,events,design,boundary=fixture_state();scope=m.scope_nodes(design);target=next(i for i,v in enumerate(rows) if v[0]==m.TARGET)
 if case=="target_identity":r=list(rows[target]);r[4]="e"*64;rows[target]=tuple(r)
 elif case=="target_failed":r=list(rows[target]);r[2]="FAILED";r[5]=None;r[6]="wrong retry";rows[target]=tuple(r)
 elif case=="primary_identity":r=list(rows[0]);r[4]="e"*64;rows[0]=tuple(r)
 elif case=="old_failed_error":i=next(i for i,v in enumerate(rows) if v[2]=="FAILED");r=list(rows[i]);r[6]="rewritten";rows[i]=tuple(r)
 elif case=="old_prefix":r=list(events[0]);r[3]='{"mutated":true}';events[0]=tuple(r)
 elif case=="extra_primary_event":events.append((1555,m.TARGET,"BACKEND_ENTER","{}","now"))
 elif case=="fusion_history":events.append((1555,next(iter(scope)),"BEGIN","{}","now"))
 elif case=="unknown_node":events.append((1555,"unknown","BEGIN","{}","now"))
 elif case=="row_width":rows[0]=rows[0][:-1]
 elif case=="missing_fusion":design["dag"]["nodes"]=[n for n in design["dag"]["nodes"] if n["node_id"]!=next(iter(scope))]
 elif case=="wrong_fusion_kind":next(n for n in design["dag"]["nodes"] if n["node_id"] in scope)["kind"]="HYBRID_ESTIMATOR"
 elif case=="risk_entered":i=next(i for i,v in enumerate(rows) if v[1]=="RISK_LEARNED_UNIT");r=list(rows[i]);r[3]=1;rows[i]=tuple(r)
 with pytest.raises(ValueError):m.validate_metadata(rows,events,design,boundary)

@pytest.mark.parametrize("case",["new_reboot","new_primary","missing_terminal","wrong_identity","wrong_artifact","failed_charge","duplicate_enter"])
def test_terminal_delta_negative(case):
 rows,events,design,boundary=terminal_state();scope=m.scope_nodes(design);n=next(iter(scope));i=next(i for i,v in enumerate(rows) if v[0]==n)
 if case=="new_reboot":events.append((len(events)+1,m.TARGET,"REBOOT_REPLAY_ENTER","{}","now"))
 elif case=="new_primary":events.append((len(events)+1,m.TARGET,"COMPLETE",rows[0][5] or "{}","now"))
 elif case=="missing_terminal":r=list(rows[i]);r[2:]=["NAMED",0,None,None,None];rows[i]=tuple(r)
 elif case=="wrong_identity":r=list(rows[i]);r[4]="f"*64;rows[i]=tuple(r)
 elif case=="wrong_artifact":r=list(rows[i]);r[5]=json.dumps({"path":"wrong","sha256":"f"*64});rows[i]=tuple(r)
 elif case=="failed_charge":rows,events,design,boundary=terminal_state("FAILED");i=next(i for i,v in enumerate(rows) if v[0]==n);r=list(rows[i]);r[3]=0;rows[i]=tuple(r)
 elif case=="duplicate_enter":events.append((len(events)+1,n,"BACKEND_ENTER","{}","now"))
 with pytest.raises(ValueError):m.validate_metadata(rows,events,design,boundary,terminal=True)

def test_configuration_closed_positive():
 cfg,entry,test,refs=config();m.validate_configuration(cfg,entry,test,refs)
@pytest.mark.parametrize("key,value",[
 ("phase","other"),("research_id","other"),("first_fusion_entry_only",False),("new_backend_replays_authorized",1),("new_backend_replays_authorized",False),("paid_cap",739),
 ("fixed_methods",list(reversed(m.METHODS))),("fixed_methods",list(m.METHODS)+["equal"]),("controller_ref",{"path":"D:/other.py","sha256":"a"*64}),("source_configuration_ref",{"path":"D:/other.json","sha256":"a"*64}),("source_review_ref",{"path":"D:/other_review.json","sha256":"a"*64}),("prior_failure_ref",{"path":"D:/wrong.json","sha256":"a"*64}),("extra",True)])
def test_configuration_negative(key,value):
 cfg,entry,test,refs=config();cfg[key]=value
 with pytest.raises(ValueError):m.validate_configuration(cfg,entry,test,refs)

def test_acceptance_positive():
 accept,cold,args=acceptance();m.validate_acceptance(accept,cold,*args)
@pytest.mark.parametrize("where,key,value",[
 ("accept","old_workers_gone",False),("accept","independent_from_entry_writer",False),("accept","first_fusion_entry_only",False),("accept","entry_ref",{"path":"wrong","sha256":"a"*64}),("accept","extra",True),
 ("cold","actual_cold",False),("cold","synthetic",True),("cold","model_deserialization_calls",1),("cold","forecast_or_label_value_reads",1),("cold","business_entry_calls",1),("cold","phase_marker_writes",1),("cold","source_and_sql_unchanged",False),("cold","after",{"changed":True})])
def test_acceptance_negative(where,key,value):
 accept,cold,args=acceptance();(accept if where=="accept" else cold)[key]=value
 with pytest.raises(ValueError):m.validate_acceptance(accept,cold,*args)

def prediction_fixture():
 old={str((m.RUN/"predictions"/f"existing_{i}").resolve()):"a"*64 for i in range(596)}
 return old,{"primary":{"current_prediction_opaque_pins":old,"current_prediction_pins_sha256":m.digest(old)}}
def test_prediction_exactreuse_positive():
 old,b=prediction_fixture();m.validate_prediction_pins(dict(old),b)
@pytest.mark.parametrize("name",["policy_FUSION_median.parquet","annual_native/FUSION_ridge_stack_2024.parquet.json","fusion_receipt_nnls_2025.json","failure_FUSION_hgb_stack.json"])
def test_only_actual_fixed_fusion_write_paths_allowed(name):
 old,b=prediction_fixture();new=dict(old);new[str((m.RUN/"predictions"/name).resolve())]="b"*64;m.validate_prediction_pins(new,b,terminal=True)
@pytest.mark.parametrize("name",["selection_FUSION_median.json","policy_FUSION_equal.parquet","policy_UNKNOWN.parquet","native_oof/FT_TRANSFORMER/new.parquet","annual_native/FUSION_median_2026.parquet"])
def test_other_new_prediction_paths_rejected(name):
 old,b=prediction_fixture();new=dict(old);new[str((m.RUN/"predictions"/name).resolve())]="b"*64
 with pytest.raises(ValueError):m.validate_prediction_pins(new,b,terminal=True)
@pytest.mark.parametrize("case",["mutate","delete","partial"])
def test_preserved_596_prediction_negative(case):
 old,b=prediction_fixture();new=dict(old);first=next(iter(old))
 if case=="mutate":new[first]="f"*64
 elif case=="delete":del new[first]
 else:new[str((m.RUN/"predictions"/"policy_FUSION_median.parquet").resolve())]="b"*64
 with pytest.raises(ValueError):m.validate_prediction_pins(new,b)

def fake_owner():
 def harmless(*args,**kwargs):return None
 class Journal:
  def __init__(self,*args,**kwargs):pass
 return SimpleNamespace(**{n:harmless for n in ("train_primary","train_fusion","FullSelectorReader","worker_runtime","_load_frame","_raw_reference","_fusion_inputs","_fusion_forecast","assemble_selection")},_TaskLedger=Journal,pd=SimpleNamespace(read_parquet=harmless))
@pytest.mark.parametrize("name",["train_primary","train_fusion","FullSelectorReader","worker_runtime","_load_frame","_raw_reference","_fusion_inputs","_fusion_forecast","assemble_selection","journal_init","pandas_read"])
def test_metadata_sentinel_blocks_and_restores(name):
 c=fake_owner();old={k:v for k,v in vars(c).items()};original=c._TaskLedger.__init__
 with m.metadata_only_scope(c) as calls:
  with pytest.raises(ValueError,match="METADATA_ONLY_BODY_ENTRY_FORBIDDEN"):
   if name=="journal_init":c._TaskLedger()
   elif name=="pandas_read":c.pd.read_parquet("must_not_read")
   else:getattr(c,name)()
 assert all(getattr(c,k) is v for k,v in old.items()) and c._TaskLedger.__init__ is original and sum(calls.values())==1

def test_fusion_route_once_exact_owner():
 calls=[];c=SimpleNamespace(train_fusion=lambda run,methods:calls.append((run,methods)))
 m.fusion_only(c);assert calls==[(m.RUN,m.METHODS)]

def test_source_only_not_installed_blocks_authority():
 with pytest.raises(ValueError,match="SOURCE_ONLY_PROPOSAL_NOT_INSTALLED"):m.load_authority()

def test_source_ast_business_and_scope_boundaries():
 tree=ast.parse(SOURCE.read_text(encoding="utf-8"));calls=[v for v in ast.walk(tree) if isinstance(v,ast.Call)]
 train=[v for v in calls if isinstance(v.func,ast.Attribute) and v.func.attr=="train_fusion"]
 assert len(train)==1
 forbidden={"train_primary","interrupted_once","train_hybrid","train_risk","run_accounts","statistics"}
 assert not any(isinstance(v.func,ast.Attribute) and v.func.attr in forbidden for v in calls)
 run=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=="run")
 text=ast.unparse(run)
 assert "with scope(RUN)" in text and "with c.engineering_source_configuration" in text
 assert text.index("with scope(RUN)")<text.index("with c.engineering_source_configuration")<text.index("c._verify_task_sources")<text.index("observe(")
 assert "fusion_only(c)" in text and "os_exit_code_not_inferred=True" in text
 assert "fixed_authority" not in text and "interrupted_once" not in text

@pytest.mark.parametrize("name",["joblib_load","pickle_load","pickle_loads"])
def test_deserializer_sentinel_blocks_and_restores(name):
 import joblib,pickle
 c=fake_owner();old=(joblib.load,pickle.load,pickle.loads)
 with m.metadata_only_scope(c) as calls:
  with pytest.raises(ValueError,match="METADATA_ONLY_BODY_ENTRY_FORBIDDEN"):
   if name=="joblib_load":joblib.load("must_not_read")
   elif name=="pickle_load":pickle.load(None)
   else:pickle.loads(b"must_not_decode")
 assert (joblib.load,pickle.load,pickle.loads)==old and sum(calls.values())==1

def setup_orchestration(monkeypatch,case):
 # Full route uses fake owners and references. No actual source/SQL/body access.
 import joblib
 cfg,entry,test,refs=config();accept,cold,args=acceptance()
 trace=[];active=set();markers={};owner_calls=[];old_marker={"old_START":"802","old_FAIL":"a75"}
 before={"ledger":{"event_count":1554},"predictions":{"preserved":True},"selection_assembly_ref":{"path":"opaque","sha256":"a"*64}}
 cold.update(before=before,after=before,test_ref=cfg["test_ref"],source_configuration_ref=cfg["source_configuration_ref"],controller_ref=cfg["controller_ref"])
 if case=="cold_wrong_controller":cold["controller_ref"]={"path":"wrong","sha256":"f"*64}
 admission=dict(schema="FULL_SELECTOR_POST_PRIMARY_FUSION_ADMISSION_REVIEW_R1",status="PASS",research_id=m.ID,independent_from_entry_writer=True,config_ref=args[0],entry_ref=entry,boundary_ref=refs["boundary_ref"],actual_cold_ref=args[-1])
 c=fake_owner();c.__file__=str(Path(__file__).resolve())
 @contextmanager
 def scope(run):
  assert run==m.RUN and "lock" in active
  active.add("registry");trace.append("registry_enter")
  try:yield
  finally:active.remove("registry");trace.append("registry_exit")
 @contextmanager
 def source(ref):
  assert "registry" in active and ref==cfg["source_configuration_ref"]
  active.add("source");trace.append("source_enter")
  try:yield
  finally:active.remove("source");trace.append("source_exit")
 def verify(run,design):
  assert {"lock","registry","source"}<=active;trace.append("verify")
  if case=="source_guard_failure":raise ValueError("synthetic source guard refused")
 def train(run,methods):
  assert {"lock","registry","source"}<=active;owner_calls.append((run,methods));trace.append("fusion_owner")
  if case=="owner_failure":raise RuntimeError("synthetic engineering failure")
 c.nonexecuting_registry_metadata_scope=scope;c.engineering_source_configuration=source;c._verify_task_sources=verify;c.train_fusion=train;c._registry_metadata_observation=lambda:{"fixed_two_metadata":True}
 @contextmanager
 def lock(run):
  assert run==m.RUN;trace.append("lock_enter")
  if case=="lock_held":raise ValueError("SINGLE_WORKER_PROCESS_LOCK_HELD")
  active.add("lock")
  try:yield
  finally:active.remove("lock");trace.append("lock_exit")
 @contextmanager
 def transported():
  trace.append("transport_enter")
  try:yield c,SimpleNamespace(_worker_lock=lock),{"actual_snapshot":True}
  finally:trace.append("transport_exit")
 r=SimpleNamespace(e=SimpleNamespace(read=lambda p:{"dag":{"nodes":[]}}),transported_owners=transported)
 def fake_import(name):assert name=="scripts.research.a2.training.full_selector_alpha_reboot_recovery";return r
 def fake_observe(e,controller,design,boundary,terminal=False):
  assert {"lock","registry","source"}<=active;trace.append("terminal_observe" if terminal else "readonly_observe")
  if case=="cold_body_denied":controller.FullSelectorReader(m.RUN)
  if case=="cold_body_exception_swallowed":
   try:controller.FullSelectorReader(m.RUN)
   except ValueError:pass
  return {"ledger":{"event_count":1776},"predictions":{"preserved":True},"selection_assembly_ref":{"path":"new","sha256":"b"*64}} if terminal else copy.deepcopy(before)
 def fake_write(e,path,value,kind):
  assert path not in markers;markers[path]=copy.deepcopy(value);trace.append("write_"+path.name)
  return {"path":str(path.resolve()),"sha256":"8"*64}
 def no_marker():
  if any(p in markers for p in (m.START,m.COMPLETE,m.FAILURE)):raise ValueError("PHASE_ALREADY_ENTERED_NO_RELAUNCH")
 if case=="already_started":markers[m.START]={"status":"earlierSTART"}
 metadata={m.ACCEPT:accept,m.COLD:cold,m.ADMISSION:admission}
 monkeypatch.setattr(m,"load_authority",lambda:(cfg,refs,{}))
 monkeypatch.setattr(m,"read",lambda p,limit=0:copy.deepcopy(metadata[Path(p)]))
 monkeypatch.setattr(m,"pin",lambda value,path=None:Path(value["path"]))
 monkeypatch.setattr(m,"reference",lambda p:{"path":str(Path(p).resolve()),"sha256":"8"*64})
 monkeypatch.setattr(m,"observe",fake_observe)
 monkeypatch.setattr(m,"write",fake_write)
 monkeypatch.setattr(m,"no_phase_marker",no_marker)
 monkeypatch.setattr(m,"CONTROLLER",Path(__file__).resolve())
 monkeypatch.setattr(m.importlib,"import_module",fake_import)
 return trace,active,markers,owner_calls,old_marker,c

def test_orchestration_execute_once_and_contexts_restore(monkeypatch):
 trace,active,markers,calls,old,c=setup_orchestration(monkeypatch,"success")
 result=m.run("execute")
 assert result["status"]=="NATURAL_APPLICATION_RETURN" and result["os_exit_code_not_inferred"] is True
 assert calls==[(m.RUN,m.METHODS)] and set(markers)=={m.START,m.COMPLETE} and not active and old=={"old_START":"802","old_FAIL":"a75"}
 assert trace.index("lock_enter")<trace.index("registry_enter")<trace.index("source_enter")<trace.index("readonly_observe")<trace.index("fusion_owner")
 assert trace[-4:]==["source_exit","registry_exit","lock_exit","transport_exit"]
 with pytest.raises(ValueError,match="NO_RELAUNCH"):m.run("execute")
 assert len(calls)==1

@pytest.mark.parametrize("case",["source_guard_failure","lock_held","already_started","cold_wrong_controller"])
def test_orchestration_preentry_refusal_has_no_new_marker(monkeypatch,case):
 trace,active,markers,calls,old,c=setup_orchestration(monkeypatch,case)
 with pytest.raises(ValueError):m.run("execute")
 assert not calls and not active and old=={"old_START":"802","old_FAIL":"a75"}
 assert set(markers)==({m.START} if case=="already_started" else set())

def test_orchestration_owner_failure_preserves_original_and_new_failure(monkeypatch):
 trace,active,markers,calls,old,c=setup_orchestration(monkeypatch,"owner_failure")
 with pytest.raises(RuntimeError,match="synthetic engineering failure"):m.run("execute")
 assert calls==[(m.RUN,m.METHODS)] and set(markers)=={m.START,m.FAILURE} and markers[m.FAILURE]["retry_authorized"] is False and not active and old=={"old_START":"802","old_FAIL":"a75"}
 assert trace[-4:]==["source_exit","registry_exit","lock_exit","transport_exit"]
 with pytest.raises(ValueError,match="NO_RELAUNCH"):m.run("execute")
 assert len(calls)==1

@pytest.mark.parametrize("operation",["inspect","cold"])
def test_orchestration_metadata_only_zero_owner_calls(monkeypatch,operation):
 trace,active,markers,calls,old,c=setup_orchestration(monkeypatch,"success")
 original=(c.FullSelectorReader,c.train_fusion,c._TaskLedger.__init__,c.pd.read_parquet)
 result=m.run(operation)
 assert not calls and not active and (c.FullSelectorReader,c.train_fusion,c._TaskLedger.__init__,c.pd.read_parquet)==original
 assert not any(p in markers for p in (m.START,m.COMPLETE,m.FAILURE))
 assert set(markers)==({m.COLD} if operation=="cold" else set())
 if operation=="cold":assert result["metadata_contexts_restored"] is True and result["business_entry_calls"]==0 and result["numerical_body_sentinel_active"] is True

@pytest.mark.parametrize("case",["cold_body_denied","cold_body_exception_swallowed"])
def test_orchestration_cold_body_attempt_even_swallowed_is_rejected(monkeypatch,case):
 trace,active,markers,calls,old,c=setup_orchestration(monkeypatch,case);original=c.FullSelectorReader
 with pytest.raises(ValueError):m.run("cold")
 assert not calls and not active and not markers and c.FullSelectorReader is original

def test_worker_lock_ast_covers_all_scopes():
 tree=ast.parse(SOURCE.read_text(encoding="utf-8"));run=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=="run")
 text=ast.unparse(run)
 assert text.index("w._worker_lock(RUN)")<text.index("metadata_only_scope(c)")<text.index("with scope(RUN)")<text.index("c.engineering_source_configuration")
 assert "as sentinel_calls" in text and text.count("require(not sentinel_calls")>=2
