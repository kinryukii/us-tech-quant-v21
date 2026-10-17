"""Pure fabricated authority/owners and tmp SQLite metadata tests.
No canonical owner/data module is imported. Price, labels, joblib, training,
fusion/equal and risk are sentinels; only fake saved-core accounting can run.
"""
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import ast,copy,hashlib,importlib.util,json,re,sqlite3
import pytest
P=Path(__file__).resolve().parents[4]/"scripts/research/a2/training/full_selector_core_account_source_recovery.py"
spec=importlib.util.spec_from_file_location("_fixed_core_recovery_fake",P)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def req(ok,code):
 if not ok:raise ValueError(code)
def reference(p):return dict(path=str(Path(p)),sha256=sha(p))
def bank(tmp_path,monkeypatch):
 run=tmp_path/"synthetic_run";run.mkdir()
 monkeypatch.setattr(r,"RUN",run);monkeypatch.setattr(r,"RUNTIME_PATH",P)
 # Source formal path is task-fixed in production; tmp is the synthetic task.
 monkeypatch.setattr(r,"SOURCE_FORMAL_R2",dict(path=str(run/"ENGINEERING_SOURCE_CORRECTION_R2.json"),
   sha256="8009d9bdc0f9e23760ea877bdee0f1e72f1af8affdb454e8c10e0f4824bb303f"))
 calls=[];control=dict(source=False,lock=False,fail=None,journal=None,closed=False)
 ids=list(r.CORE_IDS)+["SYNTHETIC_"+str(i) for i in range(61)]
 rows=[("ACCOUNT|"+role,"CONTINUOUS_ACCOUNT","NAMED",0,None,None,None) for role in ids]
 rows.append(("ESTIMATOR|ORIGINAL","ESTIMATOR","COMPLETE",1,"a"*64,'{"path":"synthetic://opaque-model","sha256":"'+"b"*64+'"}',None))
 db=sqlite3.connect(run/"TASK_LEDGER.sqlite")
 db.executescript("CREATE TABLE nodes(node_id TEXT PRIMARY KEY,kind TEXT,status TEXT,entered INTEGER,identity TEXT,artifact TEXT,error TEXT);CREATE TABLE events(sequence INTEGER PRIMARY KEY,node_id TEXT,action TEXT,payload TEXT,utc TEXT);CREATE TABLE authority(design_sha256 TEXT);")
 db.executemany("INSERT INTO nodes VALUES(?,?,?,?,?,?,?)",rows)
 db.execute("INSERT INTO authority VALUES(?)",(r.ORIGINAL_PINS["DESIGN_FREEZE.json"],))
 db.execute("INSERT INTO events VALUES(1,'ESTIMATOR|ORIGINAL','COMPLETE','{}','SYNTHETIC_UTC')");db.commit();db.close()
 design=dict(account_path_ids=ids,dag=dict(nodes=[dict(node_id=x[0],kind=x[1]) for x in rows]))
 physical={}
 def put(p,obj):
  p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
  with p.open("x",encoding="utf-8") as h:json.dump(obj,h,sort_keys=True)
  physical[str(p)]=sha(p);return reference(p)
 def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
 def pin(ref,expected=None):
  req(isinstance(ref,dict) and set(ref)=={"path","sha256"},"CLOSED_PHYSICAL_REFERENCE_REQUIRED")
  req(re.fullmatch("[0-9a-f]{64}",ref["sha256"]) is not None,"INVALID_PHYSICAL_SHA")
  path=Path(ref["path"])
  if expected is not None:req(path.resolve()==Path(expected).resolve(),"EXACT_REFERENCE_PATH_REQUIRED")
  if str(path) in physical:req(sha(path)==physical[str(path)],"FAKE_PHYSICAL_CHANGED")
  calls.append(("pin",str(path)));return path
 def ref(p):
  if str(p)==str(P):return reference(P)
  for value in r.MODULE_REFS.values():
   if str(p)==value["path"]:return value
  return reference(p)
 def snapshot(journal,run):
  values=list(journal.db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes ORDER BY node_id"))
  req(all(x[2]!="STARTED" for x in values),"STARTED_SCIENTIFIC_TAIL_CANNOT_CONTINUE")
  events=list(journal.db.execute("SELECT sequence,node_id,action,payload,utc FROM events ORDER BY sequence"))
  return dict(rows=values,nodes_sha256=digest(values),events_sha256=digest(events),event_count=len(events))
 def validate(run,design):
  calls.append("readonly_validate");req(control["source"],"SOURCE_BEFORE_SQL_REQUIRED")
  db=sqlite3.connect((Path(run)/"TASK_LEDGER.sqlite").as_uri()+"?mode=ro",uri=True)
  try:
   req(db.execute("SELECT design_sha256 FROM authority").fetchall()==[(r.ORIGINAL_PINS["DESIGN_FREEZE.json"],)],"AUTHORITY_CHANGED")
   req(dict(db.execute("SELECT node_id,kind FROM nodes"))=={x["node_id"]:x["kind"] for x in design["dag"]["nodes"]},"NODE_SET_CHANGED")
  finally:db.close()
 def append(p,value):
  calls.append(("append",Path(p).name));return put(p,value)
 def frame(value,receipt_ref=None):
  req(set(value)=={"path","sha256","identity_sha256","frame_sha256","rows","dates","keys_sha256","identity"},"EXACT8_REQUIRED")
  calls.append(("frame",value["identity"]["policy_id"]));return Path(value["path"])
 class Tracked:
  def __init__(self,db):self._db=db
  def __getattr__(self,key):return getattr(self._db,key)
  def close(self):control["closed"]=True;calls.append("db_close");self._db.close()
 e=SimpleNamespace(__file__=r.MODULE_REFS["continuation"]["path"],require=req,pin=pin,ref=ref,read=read,
  validate_existing_sqlite=validate,public_snapshot=lambda x:{k:x[k] for k in ("nodes_sha256","events_sha256","event_count")},
  append_json=append,frame_receipt=frame,TERMINAL={"COMPLETE","FAILED","SOURCE_NOT_TESTABLE","BLOCKED_DEPENDENCY"})
 ns=dict(snapshot=snapshot)
 exec(compile("def ledger_snapshot(journal,run):return snapshot(journal,run)",e.__file__,"exec"),ns)
 e.ledger_snapshot=ns["ledger_snapshot"]
 def compile_module(name,code,extra):
  path=r.MODULE_REFS[name]["path"];namespace=dict(contextmanager=contextmanager,Path=Path,sqlite3=sqlite3,
   calls=calls,control=control,req=req,r=r,put=put,Tracked=Tracked,**extra)
  exec(compile(code,path,"exec"),namespace)
  return SimpleNamespace(__file__=path,**{k:v for k,v in namespace.items() if k not in ("__builtins__","__file__")})
 c=compile_module("controller","""@contextmanager
def engineering_source_configuration(ref):
 calls.append('source_enter')
 req(ref==r.SOURCE_FORMAL_R2,'FIXED_R2_REQUIRED')
 if control['fail']=='source':raise ValueError('fake_source_failed')
 control['source']=True
 try:yield
 finally:control['source']=False;calls.append('source_exit')
class _TaskLedger:
 def __init__(self,run):
  calls.append('constructor');req(control['source'] and control['lock'],'SOURCE_LOCK_BEFORE_CONSTRUCTOR')
  self.db=Tracked(sqlite3.connect(Path(run)/'TASK_LEDGER.sqlite'));control['journal']=self
def worker_runtime(run):
 calls.append('runtime');req(control['source'],'SOURCE_BEFORE_RUNTIME')
 if control['fail']=='runtime':raise ValueError('fake_runtime_failed')
""",{})
 w=compile_module("workflow","""@contextmanager
def _worker_lock(run):
 calls.append('lock_enter')
 if control['fail']=='locked':raise ValueError('SINGLE_WORKER_PROCESS_LOCK_HELD')
 control['lock']=True
 try:yield
 finally:control['lock']=False;calls.append('lock_exit')
def run_accounts(run,policy_terminal=None):
 calls.append('run_accounts')
 req(set(policy_terminal['policy_refs'])==set(r.CORE_IDS),'ONLY_SAVED5_REQUIRED')
 if control['fail']=='account_raise':raise ValueError('fake_account_source_failure')
 db=control['journal'].db
 for role in r.CORE_IDS:
  state='FAILED' if control['fail']=='typed_failed' and role=='HGB' else 'COMPLETE'
  db.execute("UPDATE nodes SET status=?,entered=1,identity=?,artifact=?,error=? WHERE node_id=?",(state,'c'*64,'{}' if state=='COMPLETE' else None,None if state=='COMPLETE' else 'FAKE_SOURCE_GAP','ACCOUNT|'+role))
  for action in ('BEGIN','BACKEND_ENTER','COMPLETE' if state=='COMPLETE' else 'FAILED'):
   db.execute("INSERT INTO events(node_id,action,payload,utc) VALUES(?,?,?,?)",('ACCOUNT|'+role,action,'{}','SYNTHETIC_UTC'))
 if control['fail']=='noncore_node':db.execute("UPDATE nodes SET status='FAILED',error='fake_extra' WHERE node_id='ACCOUNT|SYNTHETIC_0'")
 if control['fail']=='noncore_event':db.execute("INSERT INTO events(node_id,action,payload,utc) VALUES('RISK_REFRESH|FAKE','BEGIN','{}','SYNTHETIC_UTC')")
 if control['fail']=='old_event':db.execute("UPDATE events SET payload='changed' WHERE sequence=1")
 if control['fail']=='authority':db.execute("UPDATE authority SET design_sha256='changed'")
 db.commit()
 if control['fail']=='history_file':Path(run/'continuation/CORE_ACCOUNT_CONTINUATION_R1_FAILURE.json').write_text('changed',encoding='utf-8')
 put(run/'CORE_BASE_ACCOUNT_TERMINAL.json',dict(complete=list(r.CORE_IDS),failed={}))
def _immutable_account_json(path,value):
 calls.append(('compat',Path(path).name))
 if control['fail']=='compat':raise OSError('fake_publication_failure')
 put(path,value)
""",{})
 a=compile_module("account","""def load_account_inputs(*a,**k):raise AssertionError('REAL_PRICE_INPUT_SENTINEL')
def metadata_preflight(run):
 calls.append('metadata');req(control['source'],'SOURCE_BEFORE_METADATA')
 if control['fail']=='metadata':raise ValueError('fake_metadata_failed')
""",{})
 for key in ("custody_reader","OWNERS","B_PRODUCER_TRANSPORT","identity_links"):setattr(a,key,object())
 a.original_metadata=a.metadata_preflight
 quote=compile_module("quote","def build_usable_a_mask(*a,**k):raise AssertionError('REAL_QUOTE_NUMERIC_SENTINEL')",{})
 a.quote=quote
 r7=compile_module("r7","""@contextmanager
def fixed_r7_account_overlay(e,account,manifest):
 calls.append('overlay_enter')
 names=('custody_reader','OWNERS','B_PRODUCER_TRANSPORT','identity_links','metadata_preflight')
 saved={n:getattr(account,n) for n in names}
 for n in names[:-1]:setattr(account,n,'FAKE_PRIVATE_'+n)
 try:yield {'candidate':'SYNTHETIC'}
 finally:
  for n,v in saved.items():setattr(account,n,v)
  calls.append('overlay_exit')
""",{})
 seam=compile_module("seam","""@contextmanager
def account_quote_transport(account,quote,transport,binding):
 calls.append('seam_enter');saved=account.quote;account.quote=object()
 try:yield {'seam':'SYNTHETIC'}
 finally:account.quote=saved;calls.append('seam_exit')
""",{})
 transport=compile_module("transport","def bind_existing_quote_domain(*a,**k):raise AssertionError('REAL_QUOTE_TRANSPORT_SENTINEL')",{})
 modules=dict(continuation=e,controller=c,workflow=w,account=a,r7=r7,seam=seam,transport=transport,quote=quote)
 def forbidden(*a,**k):raise AssertionError("SCIENTIFIC_OR_ECONOMIC_SENTINEL")
 for owner in (c,w,a):
  for name in ("train_fusion","train_primary","fit","risk_policies","evaluate","render_report","joblib_load","label_pairs"):
   setattr(owner,name,forbidden)
 for name in r.ORIGINAL_PINS:put(run/name,design if name=="DESIGN_FREEZE.json" else {"FAKE_METADATA":True})
 preserved=r.history_refs(run)
 for key,value in preserved.items():
  if key=="old_core_failure_ref":put(value["path"],dict(error="QUOTE_DECISION_KEY_NOT_IN_OLD_MASK:2023-01-26|PFE",scientific_retries=0))
  elif key=="core_policy_terminal_ref":pass
  else:put(value["path"],{"FAKE_CUSTODY_ONLY":True})
 policyrefs={}
 for role in r.CORE_IDS:
  physical_ref=preserved["equal_policy_ref"] if role=="FUSION_equal" else dict(path=str(run/"predictions"/("policy_"+role+".parquet")),sha256="a"*64)
  policyrefs[role]=dict(**physical_ref,identity_sha256="b"*64,frame_sha256="c"*64,rows=313668,dates=752,keys_sha256="d"*64,identity=dict(policy_id=role))
 terminal=dict(research_id=r.ID,status="CORE_BASE_POLICY_FROZEN_FOR_ACCOUNT",design_sha256=r.ORIGINAL_PINS["DESIGN_FREEZE.json"],
  outer_result_feedback=False,policy_refs=policyrefs)
 put(preserved["core_policy_terminal_ref"]["path"],terminal)
 base_ref=dict(path=str(run/"continuation/ENGINEERING_CONTINUATION_MANIFEST_R1.json"),sha256=r.BASE_MANIFEST_SHA)
 prior_ref=dict(path=str(run/"ENGINEERING_SOURCE_CORRECTION_R1.json"),sha256=r.OLD_SOURCE_SHA)
 put(base_ref["path"],dict(engineering_source_configuration_ref=prior_ref,FAKE_MANIFEST_ONLY=True))
 put(prior_ref["path"],{"FAKE_CUSTODY_ONLY":True})
 put(r.SOURCE_FORMAL_R2["path"],dict(schema="FULL_SELECTOR_ENGINEERING_SOURCE_CORRECTION_R2",status="PASS",research_id=r.ID,prior_source_configuration_ref=prior_ref))
 db=sqlite3.connect(run/"TASK_LEDGER.sqlite");pre=e.public_snapshot(snapshot(SimpleNamespace(db=db),run));db.close()
 remaining_ref=put(run/"continuation/REMAINING_ALPHA_SOURCE_RECOVERY_R1_COMPLETE.json",dict(
  research_id=r.ID,phase="remaining-alpha-source-recovery",status="INDEPENDENT_ALPHA_STAGE_TERMINAL",
  ledger_poststate=pre,account_entry=False,risk_dispatch_entered=False,scientific_retries=0))
 audit_ref=put(run/"fake_remaining_audit.json",dict(schema="FULL_SELECTOR_REMAINING_ALPHA_SOURCE_RECOVERY_TERMINAL_METADATA_ACCEPTANCE_R1",
  research_id=r.ID,status="PASS",actual_read_only_audit=True,remaining_terminal_ref=remaining_ref,workers_naturally_exited=True,
  ledger_poststate=pre,engineering_source_configuration_ref=r.SOURCE_FORMAL_R2,base_manifest_ref=base_ref,runtime_entry_ref=r.MODULE_REFS["continuation"]))
 review=dict(schema="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_ACCEPTANCE_R1",research_id=r.ID,phase=r.PHASE,
  run=str(run),status="PASS",runtime_entry_ref=reference(P),module_refs=r.MODULE_REFS,finite_source_refs=r.FINITE_REFS,
  base_manifest_ref=base_ref,prior_source_configuration_ref=prior_ref,engineering_source_configuration_ref=r.SOURCE_FORMAL_R2,
  original_refs={n:dict(path=str(run/n),sha256=h) for n,h in r.ORIGINAL_PINS.items()},preserved_refs=preserved,
  remaining_terminal_ref=remaining_ref,remaining_terminal_audit_ref=audit_ref,ledger_prestate=pre,
  all_prior_workers_terminal=True,independent_from_entry_writer=True,scientific_retry_authorized=False,first_account_dispatch_only=True,
  fixed_core_account_ids=list(r.CORE_IDS),account_backend_entered_before_review=0)
 cfg={k:copy.deepcopy(review[k]) for k in r.CONFIG_FIELDS-{"schema"}}
 cfg["schema"]="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1"
 review["phase_configuration_ref"]=put(run/"continuation/CORE_ACCOUNT_SOURCE_RECOVERY_CONFIGURATION_R1.json",cfg)
 cold=dict(schema="FULL_SELECTOR_CORE_ACCOUNT_SOURCE_RECOVERY_METADATA_COLD_R1",research_id=r.ID,status="PASS",
  actual_cold=True,synthetic=False,runtime_entry_ref=review["runtime_entry_ref"],engineering_source_configuration_ref=r.SOURCE_FORMAL_R2,
  base_manifest_ref=base_ref,module_refs=r.MODULE_REFS,finite_source_refs=r.FINITE_REFS,phase_configuration_ref=review["phase_configuration_ref"],
  ledger_prestate=pre,ledger_poststate=pre,scientific_entry_calls=0)
 review["actual_source_metadata_cold_ref"]=put(run/"fake_source_cold.json",cold)
 q=dict(schema="FULL_SELECTOR_CORE_ACCOUNT_QUOTE_INPUT_QUALIFICATION_R1",status="PASS",research_id=r.ID,
  actual_input_binding=True,synthetic=False,quote_binding=r.quote_binding(),module_refs=r.MODULE_REFS,finite_source_refs=r.FINITE_REFS,
  phase_configuration_ref=review["phase_configuration_ref"],base_manifest_ref=base_ref,engineering_source_configuration_ref=r.SOURCE_FORMAL_R2,
  source_axis="ALL_CURRENT_FULL_U_SOURCE_AXES_PRE2026",current_true_owner_coverage_exact=True,current_quality_unchanged=True,
  current_false_still_false=True,historical_all_decisions_original_owner_verified=True,historical_projected_keys_all_named=True,
  original_raw_equality_verified=True,held_or_selected_filter=False,new_class_A_records=0,classifier_rule_changed=False,
  account_backend_entered=0,ledger_prestate=pre,ledger_poststate=pre)
 review["actual_quote_input_qualification_ref"]=put(run/"fake_quote_qualification.json",q)
 review_ref=put(run/"continuation"/(r.NAME+"_ACCEPTANCE.json"),review)
 saved={n:getattr(a,n) for n in ("custody_reader","OWNERS","B_PRODUCER_TRANSPORT","identity_links","metadata_preflight","quote")}
 return SimpleNamespace(run=run,review=review,review_ref=review_ref,cfg=cfg,cold=cold,q=q,modules=modules,
  calls=calls,control=control,physical=physical,read=read,put=put,saved=saved,e=e)

def revise(b,path,obj):
 Path(path).write_text(json.dumps(obj,sort_keys=True),encoding="utf-8");b.physical[str(path)]=sha(path)
def run(b):return r.recover_once(b.run,b.review_ref,b.modules)
def unchanged_helpers(b):
 a=b.modules["account"]
 assert all(getattr(a,n) is v for n,v in b.saved.items())
 assert b.control["source"] is False and b.control["lock"] is False

def test_source_import_has_no_real_owner_or_actual_main():
 tree=ast.parse(P.read_text(encoding="utf-8"))
 imports=[ast.unparse(n) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
 assert all("scripts." not in x and "joblib" not in x for x in imports)
 assert not any(isinstance(n,ast.FunctionDef) and n.name=="main" for n in tree.body)
 calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
 assert calls.count("w.run_accounts")==1
 assert not any(x.endswith(("train_fusion","train_primary","fit","evaluate","render_report")) for x in calls)

def test_first_saved5_exact_owner_order_and_remaining61_preserved(tmp_path,monkeypatch):
 b=bank(tmp_path,monkeypatch);old={k:Path(v["path"]).read_bytes() for k,v in b.review["preserved_refs"].items()}
 result=run(b);assert set(result)==r.COMPLETE_FIELDS
 assert result["applicable_core_account_ids"]==list(r.CORE_IDS) and result["all66_accounts_complete"] is False
 assert result["existing_equal_exact_reuse"] is True and result["only_saved_core_account_dispatch"] is True
 assert all(v=="COMPLETE" for v in result["core_account_states"].values())
 actions=[x for x in b.calls if isinstance(x,str)]
 assert actions.index("source_enter")<actions.index("readonly_validate")<actions.index("constructor")<actions.index("runtime")<actions.index("metadata")<actions.index("run_accounts")
 assert b.calls.count("run_accounts")==1 and b.control["closed"]
 unchanged_helpers(b)
 assert all(Path(b.review["preserved_refs"][k]["path"]).read_bytes()==v for k,v in old.items())
 assert not (b.run/"continuation/CORE_ACCOUNT_CONTINUATION_R1_COMPLETE.json").exists()
 complete=b.run/"continuation"/(r.NAME+"_COMPLETE.json")
 assert complete.exists() and (b.run/"PRIMARY_CORE_EXECUTION_COMPLETE.json").exists()
 append_names=[v[1] for v in b.calls if isinstance(v,tuple) and v[0]=="append"]
 assert append_names==[r.NAME+"_STARTED.json",r.NAME+"_COMPLETE.json"]
 db=sqlite3.connect(b.run/"TASK_LEDGER.sqlite")
 assert db.execute("SELECT count(*) FROM nodes WHERE kind='CONTINUOUS_ACCOUNT' AND status='NAMED' AND entered=0").fetchone()==(61,)
 db.close()

@pytest.mark.parametrize("field,value",[
 ("current_true_owner_coverage_exact",False),("current_false_still_false",False),
 ("held_or_selected_filter",True),("new_class_A_records",1),("synthetic",True),
 ("source_axis","ONLY_SELECTED_TOP20"),("original_raw_equality_verified",False),
 ("historical_projected_keys_all_named",False)])
def test_false_or_filtered_quote_qualification_refuses_before_constructor(tmp_path,monkeypatch,field,value):
 b=bank(tmp_path,monkeypatch);b.q[field]=value;revise(b,b.review["actual_quote_input_qualification_ref"]["path"],b.q)
 with pytest.raises(ValueError,match="ACTUAL_ALL_SOURCE_QUOTE"):run(b)
 assert "constructor" not in b.calls and "run_accounts" not in b.calls
 assert not (b.run/"continuation"/(r.NAME+"_STARTED.json")).exists();unchanged_helpers(b)

@pytest.mark.parametrize("table,sql",[
 ("nodes","UPDATE nodes SET status='STARTED',entered=1 WHERE node_id='ESTIMATOR|ORIGINAL'"),
 ("nodes","UPDATE nodes SET status='FAILED',entered=1,error='fake' WHERE node_id='ACCOUNT|RAW'"),
 ("events","INSERT INTO events(node_id,action,payload,utc) VALUES('ACCOUNT|RAW','BEGIN','{}','SYNTHETIC_UTC')")])
def test_any_scientific_tail_or_account_prior_attempt_refused_readonly_before_constructor(tmp_path,monkeypatch,table,sql):
 b=bank(tmp_path,monkeypatch);db=sqlite3.connect(b.run/"TASK_LEDGER.sqlite");db.execute(sql);db.commit();db.close()
 with pytest.raises(ValueError):run(b)
 assert "constructor" not in b.calls and "run_accounts" not in b.calls;unchanged_helpers(b)

@pytest.mark.parametrize("stage",["locked","source","runtime","metadata"])
def test_lock_source_runtime_metadata_failure_zero_account_and_restoration(tmp_path,monkeypatch,stage):
 b=bank(tmp_path,monkeypatch);b.control["fail"]=stage
 with pytest.raises(ValueError):run(b)
 assert "run_accounts" not in b.calls
 assert not (b.run/"continuation"/(r.NAME+"_STARTED.json")).exists();unchanged_helpers(b)
 if stage in ("runtime","metadata"):assert b.control["closed"]

@pytest.mark.parametrize("stage",["noncore_node","noncore_event","old_event","authority","history_file"])
def test_noncore_state_event_authority_or_history_mutation_cannot_complete(tmp_path,monkeypatch,stage):
 b=bank(tmp_path,monkeypatch);b.control["fail"]=stage
 with pytest.raises(ValueError):run(b)
 assert (b.run/"continuation"/(r.NAME+"_FAILURE.json")).exists()
 assert not (b.run/"continuation"/(r.NAME+"_COMPLETE.json")).exists()
 assert not (b.run/"PRIMARY_CORE_EXECUTION_COMPLETE.json").exists()
 assert b.control["closed"];unchanged_helpers(b)

def test_typed_failed_core_account_terminal_preserved_not_claimed_66_or_economic_pass(tmp_path,monkeypatch):
 b=bank(tmp_path,monkeypatch);b.control["fail"]="typed_failed";result=run(b)
 assert result["core_account_states"]["HGB"]=="FAILED" and result["all66_accounts_complete"] is False
 assert not result["all_task_complete"]
 assert "economic_qualified" not in result and "account_qualified" not in result

def test_new_phase_started_failure_not_reentered_and_original_failure_not_rewritten(tmp_path,monkeypatch):
 b=bank(tmp_path,monkeypatch);b.control["fail"]="account_raise"
 old=Path(b.review["preserved_refs"]["old_core_failure_ref"]["path"]).read_bytes()
 with pytest.raises(ValueError,match="fake_account_source_failure"):run(b)
 b.control["fail"]=None
 with pytest.raises(ValueError,match="FIRST_NEW_ACCOUNT_PHASE_ONLY"):run(b)
 assert b.calls.count("run_accounts")==1
 assert Path(b.review["preserved_refs"]["old_core_failure_ref"]["path"]).read_bytes()==old

def test_compatible_publication_failure_keeps_new_natural_complete_and_forbids_replay(tmp_path,monkeypatch):
 b=bank(tmp_path,monkeypatch);b.control["fail"]="compat"
 with pytest.raises(OSError,match="fake_publication_failure"):run(b)
 assert (b.run/"continuation"/(r.NAME+"_COMPLETE.json")).exists()
 assert not (b.run/"continuation"/(r.NAME+"_FAILURE.json")).exists()
 b.control["fail"]=None
 with pytest.raises(ValueError,match="FIRST_NEW_ACCOUNT_PHASE_ONLY"):run(b)
 assert b.calls.count("run_accounts")==1;unchanged_helpers(b)

def test_foreign_same_named_function_origin_refused_before_lock_or_data(tmp_path,monkeypatch):
 b=bank(tmp_path,monkeypatch);ns={}
 exec(compile("def run_accounts(*a,**k):pass","synthetic_foreign.py","exec"),ns)
 b.modules["workflow"].run_accounts=ns["run_accounts"]
 with pytest.raises(ValueError,match="FUNCTION_ORIGIN_CHANGED"):run(b)
 assert "lock_enter" not in b.calls and "constructor" not in b.calls

@pytest.mark.parametrize("what",["config_extra","config_binding","review_extra","missing_actual_cold"])
def test_closed_configuration_review_or_synthetic_cold_mismatch_refused(tmp_path,monkeypatch,what):
 b=bank(tmp_path,monkeypatch)
 if what=="config_extra":
  b.cfg["arbitrary_transport"]=True;revise(b,b.review["phase_configuration_ref"]["path"],b.cfg)
 elif what=="config_binding":
  b.cfg["module_refs"]={};revise(b,b.review["phase_configuration_ref"]["path"],b.cfg)
 elif what=="review_extra":
  b.review["lower_source_gate"]=True;revise(b,b.review_ref["path"],b.review)
 else:
  b.cold["actual_cold"]=False;revise(b,b.review["actual_source_metadata_cold_ref"]["path"],b.cold)
 with pytest.raises(ValueError):run(b)
 assert "constructor" not in b.calls and "run_accounts" not in b.calls
