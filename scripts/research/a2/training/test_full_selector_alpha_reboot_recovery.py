"""Synthetic replay boundaries; no project data, training or owner worker."""
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
from scripts.research.a2.training import full_selector_alpha_reboot_recovery as r

class Journal:
 def __init__(self,tmp):
  self.run=tmp;self.db=sqlite3.connect(":memory:")
  self.db.execute("CREATE TABLE nodes(node_id TEXT PRIMARY KEY,status TEXT,entered INTEGER,identity TEXT,artifact TEXT,error TEXT)")
  self.db.execute("CREATE TABLE events(node_id TEXT,action TEXT,payload TEXT)")
  self.db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?)",(r.TARGET,"STARTED",1,r.TOKEN,None,None));self.db.commit()
 def status(self,node):
  row=self.db.execute("SELECT status,entered,identity,artifact,error FROM nodes WHERE node_id=?",(node,)).fetchone()
  return dict(zip(("status","entered","identity","artifact","error"),row))
 def event(self,node,action,payload):self.db.execute("INSERT INTO events VALUES (?,?,?)",(node,action,json.dumps(payload)))

def owner():
 class Ledger:
  def once(self,node,identity,work):return ("ORIGINAL_ONCE",node)
 return SimpleNamespace(_TaskLedger=Ledger,_predict=lambda *args:"ORIGINAL_PREDICT",digest=lambda v:r.TOKEN if v=={"good":True} else r.e.digest(v),sha=r.e.sha)

@pytest.fixture
def env(tmp_path):return Journal(tmp_path),owner()

def test_one_replay_preserves_entered_and_original_history(env):
 j,c=env
 j.event(r.TARGET,"BEGIN",{"good":True});j.event(r.TARGET,"BACKEND_ENTER",{});j.db.commit()
 old_once=c._TaskLedger.once;old_predict=c._predict
 def work(enter):enter({"actual_native":True});assert j.status(r.TARGET)["entered"]==1;return {"fit":"synthetic"}
 with r.interrupted_once(c,{"authority":"exact"},{"marker":"exact"},{}) as state:
  result=c._TaskLedger.once(j,r.TARGET,{"good":True},work)
  assert result=={"fit":"synthetic"} and state["calls"]==state["entries"]==1
 assert j.status(r.TARGET)["status"]=="COMPLETE" and j.status(r.TARGET)["entered"]==1
 assert [row[0] for row in j.db.execute("SELECT action FROM events")]==["BEGIN","BACKEND_ENTER","REBOOT_REPLAY_RESERVED","REBOOT_REPLAY_ENTER","COMPLETE"]
 assert c._TaskLedger.once is old_once and c._predict is old_predict
 artifact=json.loads(j.status(r.TARGET)["artifact"]);assert r.e.sha(artifact["path"])==artifact["sha256"]

@pytest.mark.parametrize("change",[{"status":"NAMED"},{"status":"FAILED"},{"entered":0},{"identity":"0"*64},{"artifact":"{}"},{"error":"old"}])
def test_reject_wrong_interrupted_state_before_reservation(env,change):
 j,c=env
 for key,value in change.items():j.db.execute("UPDATE nodes SET "+key+"=? WHERE node_id=?",(value,r.TARGET))
 j.db.commit()
 with r.interrupted_once(c,{}, {},{}):
  with pytest.raises(ValueError,match="EXACT_SINGLE"):
   c._TaskLedger.once(j,r.TARGET,{"good":True},lambda f:pytest.fail("work called"))
 assert j.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]==0

def test_reject_different_identity(env):
 j,c=env
 with r.interrupted_once(c,{}, {},{}):
  with pytest.raises(ValueError,match="EXACT_SINGLE"):
   c._TaskLedger.once(j,r.TARGET,{"bad":True},lambda f:pytest.fail("work called"))
 assert j.status(r.TARGET)["entered"]==1

def test_other_node_and_completed_target_delegate_original_once(env):
 j,c=env
 with r.interrupted_once(c,{}, {},{}):
  assert c._TaskLedger.once(j,"OTHER",{},None)==("ORIGINAL_ONCE","OTHER")
  j.db.execute("UPDATE nodes SET status='COMPLETE'");j.db.commit()
  assert c._TaskLedger.once(j,r.TARGET,{},None)==("ORIGINAL_ONCE",r.TARGET)

def test_orphan_artifact_blocks_without_deleting_it(env):
 j,c=env;p=j.run/"models"/(c.digest(r.TARGET)+".joblib");p.parent.mkdir();p.write_bytes(b"keep")
 with r.interrupted_once(c,{}, {},{}):
  with pytest.raises(ValueError,match="ORPHAN"):
   c._TaskLedger.once(j,r.TARGET,{"good":True},lambda f:pytest.fail("work called"))
 assert p.read_bytes()==b"keep" and j.status(r.TARGET)["status"]=="STARTED"

@pytest.mark.parametrize("case",["missing_callback","duplicate_callback","scientific_exception"])
def test_failure_is_terminal_and_never_retried(env,case):
 j,c=env;calls=[]
 def work(enter):
  calls.append(1)
  if case!="missing_callback":enter({})
  if case=="duplicate_callback":enter({})
  if case=="scientific_exception":raise ValueError("synthetic failure")
  return {}
 with r.interrupted_once(c,{}, {},{}) as state:
  assert c._TaskLedger.once(j,r.TARGET,{"good":True},work) is None
  assert j.status(r.TARGET)["status"]=="FAILED" and j.status(r.TARGET)["entered"]==1
  with pytest.raises(ValueError):c._TaskLedger.once(j,r.TARGET,{"good":True},work)
 assert len(calls)==1 and state["entries"]<=1
 assert sum(row[0]=="REBOOT_REPLAY_ENTER" for row in j.db.execute("SELECT action FROM events"))<=1

def test_context_restores_functions_on_base_exception(env):
 j,c=env;old=c._TaskLedger.once;predict=c._predict
 with pytest.raises(KeyboardInterrupt):
  with r.interrupted_once(c,{}, {},{}):raise KeyboardInterrupt()
 assert c._TaskLedger.once is old and c._predict is predict

def test_cached_forecast_exactreuse_avoids_prediction(env,monkeypatch,tmp_path):
 j,c=env;path=tmp_path/"cached.parquet";path.write_bytes(b"opaque synthetic")
 identity=dict(role="FT_TRANSFORMER",cutoff="2023-07-01",capacity="LOW",training_keys="k",max_train_label_end="2023-06-30")
 Path(str(path)+".json").write_text(json.dumps(dict(keys_sha256="keys",identity_sha256=c.digest(identity))))
 bundle=dict(identity);c._native_path=lambda *a:path;c.keys_digest=lambda frame:"keys";c._load_frame=lambda p:("EXACT_CACHED_FRAME",{})
 with r.interrupted_once(c,{}, {},{str(path.resolve()):r.e.sha(path)}) as state:
  assert c._predict(bundle,object())=="EXACT_CACHED_FRAME" and state["forecast_exact_reuses"]==1

def test_cached_forecast_tamper_rejected(env,tmp_path):
 j,c=env;path=tmp_path/"cached.parquet";path.write_bytes(b"changed");c._native_path=lambda *a:path
 with r.interrupted_once(c,{}, {},{str(path.resolve()):"0"*64}):
  with pytest.raises(ValueError,match="PRESERVED_NATIVE_FORECAST_CHANGED"):
   c._predict(dict(role="FT_TRANSFORMER",cutoff="2023-07-01",capacity="LOW"),object())

def test_same_cut_other_domain_uses_original_prediction(env,tmp_path):
 j,c=env;p=tmp_path/"c.parquet";p.write_bytes(b"opaque");Path(str(p)+".json").write_text(json.dumps(dict(keys_sha256="other")))
 c._native_path=lambda *a:p;c.keys_digest=lambda f:"current"
 with r.interrupted_once(c,{}, {},{str(p.resolve()):r.e.sha(p)}):
  assert c._predict(dict(role="FT_TRANSFORMER",cutoff="2023-07-01",capacity="LOW"),object())=="ORIGINAL_PREDICT"

def test_refuse_metadata_or_execution_second_attempt(monkeypatch,tmp_path):
 monkeypatch.setattr(r,"fixed_authority",lambda:({}, {}, {}))
 class Context:
  def __enter__(self):return self
  def __exit__(self,*a):return False
 c=SimpleNamespace(engineering_source_configuration=lambda x:Context(),_verify_task_sources=lambda *a:None)
 w=SimpleNamespace(_worker_lock=lambda *a:Context())
 monkeypatch.setattr(r.e,"owners",lambda:(c,w,None))
 from contextlib import contextmanager
 @contextmanager
 def transported():yield c,w,{}
 monkeypatch.setattr(r,"transported_owners",transported);monkeypatch.setattr(r,"fixed_authority",lambda:({"engineering_source_configuration_ref":{}},{},{"source_configuration_ref":{}}))
 p=tmp_path/"started";p.write_text("preserve");monkeypatch.setattr(r,"START",p)
 with pytest.raises(ValueError,match="REBOOT_ATTEMPT_EXISTS_NO_RETRY"):r.run("execute","x","y")
 assert p.read_text()=="preserve"
@pytest.fixture
def fake_transport(monkeypatch,tmp_path):
 import sys
 v22="scripts.v22.corporate_action_transition_r1";joint="scripts.research.a2.data.joint_cash_bindings";ca="scripts.research.a2.data.reused_pair_ca_sources";profile="scripts.research.a2.evaluation.frozen_a94_profile"
 files={v22:"class SourceBackedEntitlementEvent: pass\ndef canonical_bytes(x): return repr(x).encode()\ndef helper(): return 'v22'\n",joint:"from scripts.v22.corporate_action_transition_r1 import SourceBackedEntitlementEvent,canonical_bytes\ndef helper(): return 'joint'\n",ca:"from scripts.research.a2.data import joint_cash_bindings as cash\ndef helper(): return cash.helper()\n",profile:"def helper(): return 'profile'\n"}
 values={}
 for i,(name,body) in enumerate(files.items()):
  p=tmp_path/(str(i)+".py");p.write_text(body);values[name]=(str(tmp_path/("live"+str(i)+".py")),r.e.sha(p),p)
 for name in values:
  sys.modules.pop(name,None)
  parent,child=name.rsplit('.',1);module=r.importlib.import_module(parent)
  if hasattr(module,child):monkeypatch.delattr(module,child)
 monkeypatch.setattr(r,"TRANSPORT_MODULES",values);monkeypatch.setattr(r,"CONSUMERS",())
 monkeypatch.setattr(r,"transport_configuration",lambda:{})
 monkeypatch.setattr(r,"REPO",tmp_path)
 controller=tmp_path/"scripts/research/a2/training/selector_full_fixed_policy.py";controller.parent.mkdir(parents=True);controller.write_text("def resolve(ref): return ('DELEGATED',ref)\n")
 ns={};exec(compile(controller.read_bytes(),str(controller),"exec"),ns)
 c=SimpleNamespace(_correction_ref=ns["resolve"],__file__=str(controller));w=object();monkeypatch.setattr(r.e,"owners",lambda:(c,w,None))
 for attr in ("R4_SOURCE","GUARD_AUTH"):
  meta=tmp_path/(attr+".json");meta.write_text("{}");monkeypatch.setattr(r,attr,meta)
 return c,w,values

def test_transport_actual_origins_narrow_resolution_and_restore(fake_transport):
 import sys
 c,w,values=fake_transport;original=c._correction_ref
 with r.transported_owners() as (observed_c,observed_w,qualification):
  assert observed_c is c and observed_w is w and len(qualification['modules'])==4
  for name,(relative,sha,p) in values.items():
   assert c._correction_ref(dict(path=relative,sha256=sha))==("DELEGATED",dict(path=relative,sha256=sha))
   bad=dict(path=relative,sha256='0'*64);assert c._correction_ref(bad)==('DELEGATED',bad)
   assert Path(sys.modules[name].helper.__code__.co_filename)==p
 assert c._correction_ref is original and all(name not in sys.modules for name in values)

def test_transport_preloaded_live_module_rejects(fake_transport,monkeypatch):
 import sys
 c,w,values=fake_transport;name=next(iter(values));monkeypatch.setitem(sys.modules,name,SimpleNamespace(__file__="live.py"))
 with pytest.raises(ValueError,match="PRISTINE"):
  with r.transported_owners():pytest.fail('transport entered')

def test_transport_changed_snapshot_rejects(fake_transport):
 c,w,values=fake_transport;p=next(iter(values.values()))[2];p.write_text('def changed(): return 1\n')
 with pytest.raises(ValueError,match="PHYSICAL_REFERENCE_CHANGED"):
  with r.transported_owners():pytest.fail('transport entered')

def test_transport_restores_when_body_fails(fake_transport):
 import sys
 c,w,values=fake_transport;original=c._correction_ref
 with pytest.raises(RuntimeError,match='synthetic'):
  with r.transported_owners():raise RuntimeError('synthetic')
 assert c._correction_ref is original and all(name not in sys.modules for name in values)

@pytest.mark.parametrize('kind',['review_fail','review_stale','test_fail','test_stale','cold_synthetic','cold_missing_zero_gate','cold_wrong_prestate','review_source_stale','test_guard_stale'])
def test_admission_rejects_stale_failed_or_synthetic_evidence(monkeypatch,kind):
 cfg=dict(entry_ref={'source':'current'},test_ref={'test':'current'},prestate_ref={'pre':'current'},source_configuration_ref={'r4':'current'},source_guard_human_approval_ref={'guard':'current'})
 metadata=dict(ledger_prestate={'events':1059});transport={'real':'snapshots'}
 accept=dict(source_review_ref={'path':'review'},test_evidence_ref={'path':'tests'},actual_cold_ref={'path':'cold'})
 source=dict(schema='FULL_SELECTOR_ALPHA_REBOOT_SOURCE_REVIEW_R1',research_id=r.ID,status='PASS',independent_from_entry_writer=True,entry_ref=cfg['entry_ref'],test_ref=cfg['test_ref'],source_configuration_ref=cfg['source_configuration_ref'],source_guard_human_approval_ref=cfg['source_guard_human_approval_ref'])
 tests=dict(schema='FULL_SELECTOR_ALPHA_REBOOT_TEST_EVIDENCE_R1',research_id=r.ID,status='PASS',entry_ref=cfg['entry_ref'],test_ref=cfg['test_ref'],targeted_final_exit_code=0,default_exit_code=0,source_configuration_ref=cfg['source_configuration_ref'],source_guard_human_approval_ref=cfg['source_guard_human_approval_ref'])
 cold=dict(schema='FULL_SELECTOR_ALPHA_REBOOT_COLD_R1',research_id=r.ID,actual_cold=True,status='PASS',config_ref={'cfg':'current'},entry_ref=cfg['entry_ref'],prestate_ref=cfg['prestate_ref'],actual_source_transport=transport,ledger_prestate=metadata['ledger_prestate'],all99_source_guard=True,sole_readonly_ledger=True,opaque_artifacts_verified=True,no_native_or_prediction_or_label_or_account_or_risk_or_bootstrap_entry=True)
 if kind=='review_fail':source['status']='FAIL'
 if kind=='review_stale':source['entry_ref']={'source':'old'}
 if kind=='test_fail':tests['targeted_final_exit_code']=1
 if kind=='test_stale':tests['test_ref']={'test':'old'}
 if kind=='review_source_stale':source['source_configuration_ref']={'r4':'old'}
 if kind=='test_guard_stale':tests['source_guard_human_approval_ref']={'guard':'old'}
 if kind=='cold_synthetic':cold['actual_cold']=False
 if kind=='cold_missing_zero_gate':cold.pop('no_native_or_prediction_or_label_or_account_or_risk_or_bootstrap_entry')
 if kind=='cold_wrong_prestate':cold['prestate_ref']={'pre':'old'}
 monkeypatch.setattr(r.e,'pin',lambda *a:None);monkeypatch.setattr(r.e,'ref',lambda *a:{'cfg':'current'})
 monkeypatch.setattr(r.e,'read',lambda path: {'review':source,'tests':tests,str(r.COLD):cold}[str(path)])
 with pytest.raises(ValueError):r.validate_admission(accept,cfg,metadata,transport)

def test_transport_compiles_verified_bytes_and_ignores_matching_stale_pyc(fake_transport):
 import os,py_compile,sys
 c,w,values=fake_transport
 name='scripts.research.a2.data.joint_cash_bindings';p=values[name][2];original=p.read_text()
 p.write_text(original.replace("'joint'","'wrong'"))
 py_compile.compile(str(p),doraise=True)
 stale=p.stat()
 p.write_text(original);os.utime(p,ns=(stale.st_atime_ns,stale.st_mtime_ns))
 with r.transported_owners():
  assert sys.modules[name].helper()=='joint'


def test_transport_rejects_mixed_v22_dependency_objects(fake_transport):
 c,w,values=fake_transport
 name="scripts.research.a2.data.joint_cash_bindings";rel,sha,p=values[name]
 p.write_text("class SourceBackedEntitlementEvent: pass\ndef canonical_bytes(x): return b'fake'\ndef helper(): return 'joint'\n")
 values[name]=(rel,r.e.sha(p),p)
 with pytest.raises(ValueError,match='EXACT_V22_JOINT_SNAPSHOT_OBJECTS_REQUIRED'):
  with r.transported_owners():pytest.fail('mixed dependency entered')


@pytest.fixture
def pristine_named_sqlite_row():
 db=sqlite3.connect(":memory:")
 db.execute("CREATE TABLE nodes(node_id TEXT PRIMARY KEY,kind TEXT,status TEXT,entered INTEGER,identity TEXT,artifact TEXT,error TEXT)")
 db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",("MODEL|SYNTHETIC", "ESTIMATOR", "NAMED", 0, None, None, None))
 row=db.execute("SELECT node_id,kind,status,entered,identity,artifact,error FROM nodes").fetchone()
 db.close()
 return row

def test_named_metadata_matches_actual_seven_column_sqlite_schema(pristine_named_sqlite_row):
 from collections import Counter
 assert len(pristine_named_sqlite_row)==7
 r._require_unentered_named(pristine_named_sqlite_row,Counter())

@pytest.mark.parametrize("column,value",[(2,"STARTED"),(3,1),(4,"reserved"),(5,"artifact"),(6,"error")])
def test_named_metadata_rejects_each_non_pristine_field(pristine_named_sqlite_row,column,value):
 from collections import Counter
 row=list(pristine_named_sqlite_row);row[column]=value
 with pytest.raises(ValueError,match="NAMED_WITH_ENTRY_OR_HISTORY"):
  r._require_unentered_named(tuple(row),Counter())

@pytest.mark.parametrize("width",[6,8])
def test_named_metadata_rejects_wrong_column_width(pristine_named_sqlite_row,width):
 from collections import Counter
 row=pristine_named_sqlite_row[:width] if width==6 else pristine_named_sqlite_row+(None,)
 with pytest.raises(ValueError,match="NAMED_WITH_ENTRY_OR_HISTORY"):
  r._require_unentered_named(row,Counter())

def test_named_metadata_rejects_prior_history(pristine_named_sqlite_row):
 from collections import Counter
 with pytest.raises(ValueError,match="NAMED_WITH_ENTRY_OR_HISTORY"):
  r._require_unentered_named(pristine_named_sqlite_row,Counter({pristine_named_sqlite_row[0]:1}))
