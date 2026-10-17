"""Offline full original first-batch paths; no OpenD, model or accepted runtime reads."""
import sys,importlib.util,json,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from contextlib import contextmanager
from unittest.mock import patch
import pytest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
import moomoo_component
from moomoo_component.cohort import Cohort,HGB_STRATEGIES
from moomoo_component.core import Engine,_first_execution_sha
from moomoo_component.best_broker import BestBroker,SID
from moomoo_component import core,cohort,best_broker,strategy

def fixture_module(name):
 spec=importlib.util.spec_from_file_location('_original_fixture_'+name,APP/'tests'/('test_'+name+'.py'))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
CF=fixture_module('cohort');BF=fixture_module('best_broker')
OPEN=datetime(2026,10,8,13,30,tzinfo=timezone.utc)
CLOSE=datetime(2026,10,7,20,tzinfo=timezone.utc)
NOW=OPEN+timedelta(hours=2)
REFS={k:{'path':'fixture/'+k,'sha256':'a'*64} for k in
 ('frozen_calendar','session_hours_rules','daily/report.json','selected/package.json','selected/current_report.json','current/features.parquet')}

class Source(CF.Source):
 def __init__(self,broker=False):
  super().__init__();self.opening=OPEN;self.broker=broker
  self.weights={s:{'US.AAPL':.1,'US.MSFT':.1} for s in ([SID] if broker else HGB_STRATEGIES)}
 def status(self,now=None):
  return dict(status='READY',reason='offline',signal_date=(self.opening-timedelta(hours=17,minutes=30)).date().isoformat(),source_date=(self.opening-timedelta(hours=17,minutes=30)).date().isoformat(),
   execution_date=self.opening.date().isoformat(),signal_close_utc=(self.opening-timedelta(hours=17,minutes=30)).isoformat(),
   next_open_utc=self.opening.isoformat(),next_close_utc=(self.opening+timedelta(hours=6,minutes=30)).isoformat(),
   source_refs=deepcopy(REFS),data_gaps=[])
 def close_states(self,books,signal_date):
  result=super().close_states(books,signal_date)
  for state in result.values():state['close_asof_utc']=self.status(NOW)['signal_close_utc']
  return result
 def load(self,states,now=None):
  result=super().load(states,now)
  if self.broker:result['plans']={SID:result['plans'][SID]}
  return result

@contextmanager
def real_clock(now):
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None):return now if tz is None else now.astimezone(tz)
 with patch.object(core,'datetime',Clock),patch.object(strategy,'datetime',Clock),patch.object(best_broker,'datetime',Clock):
  yield

@pytest.fixture
def paper(tmp_path):
 source,quotes=Source(),CF.Quotes()
 with patch.object(core,'now_iso',return_value=(CLOSE-timedelta(hours=1)).isoformat()):
  c=Cohort(tmp_path/'paper',source,quotes,execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
 c.meta['active_strategy_ids']=list(HGB_STRATEGIES)
 for e in c._active_engines().values():e._set('paper',{'cash':8700.,'positions':{'US.OLD':10},'fees':0.})
 c._prepare(source.status(NOW),NOW);c._persist()
 try:yield c,source,quotes
 finally:
  if not c.closed:c.close()

def paper_grant(c,deadline=None,**changes):
 args=dict(execution_date='2026-10-08',deadline_utc=(deadline or NOW+timedelta(seconds=600)).isoformat(),
  authorization_id='offline_first_20261008',expected_package_sha256='a'*64,
  expected_plan_sha256_by_book={s:_first_execution_sha(c.plans[s]) for s in HGB_STRATEGIES},now=NOW)
 args.update(changes);return c.authorize_first_execution(**args)

def paper_tick(c,q,clock=NOW):
 q.clock=clock;c.stop_event.clear()
 for e in c._active_engines().values():e.cancel_step.clear()
 return c.tick(now=clock)

def count(e,t):return e.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]

def test_paper_no_permission_cannot_create_first_batch(paper):
 c,s,q=paper;result=paper_tick(c,q)
 assert result['status']=='MISSED_OPEN'
 assert all(count(e,'paper_batches')==0 and count(e,'orders')==0 for e in c._active_engines().values())

def test_paper_grant_only_then_real_held_first_batch_sell_buy_and_idempotency(paper):
 c,s,q=paper;before={sid:deepcopy(e._get('paper',{})) for sid,e in c._active_engines().items()}
 g=paper_grant(c)
 assert c.stop_event.is_set()
 assert all(e._get('paper',{})==before[sid] and count(e,'paper_batches')==0 for sid,e in c._active_engines().items())
 result=paper_tick(c,q)
 assert result['status']=='EXECUTED',result.get('last_error')
 for sid,e in c._active_engines().items():
  batch=json.loads(e.db.execute('SELECT payload FROM paper_batches').fetchone()[0])
  fills=[json.loads(r[0]) for r in e.db.execute('SELECT payload FROM paper_fills')]
  assert batch['pretrade_equity']==9700
  assert batch['first_execution_permission_sha256']==_first_execution_sha(g['books'][sid])
  assert [f['side'] for f in sorted(fills,key=lambda f:f['sequence'])]==['SELL','BUY','BUY']
  assert 'US.OLD' not in e._get('paper',{})['positions']
  assert e._get('paper',{})['cash']>=0
  assert all(f['fee_bps']==5 and f['filled_at']==NOW.isoformat() for f in fills)
 old=[count(e,'paper_fills') for e in c._active_engines().values()]
 paper_tick(c,q,NOW+timedelta(seconds=2))
 assert old==[count(e,'paper_fills') for e in c._active_engines().values()]

def test_paper_restart_keeps_permission_and_original_batch_prefix(paper):
 c,s,q=paper;g=paper_grant(c);q.errors={'US.MSFT':'fixture missing'}
 paper_tick(c,q);before={sid:count(e,'paper_fills') for sid,e in c._active_engines().items()}
 path=c.path;c.close();new=Cohort(path,s,q)
 try:
  assert new.meta['paper_first_execution']==g
  q.errors={};result=paper_tick(new,q,NOW+timedelta(seconds=5))
  assert result['status']=='EXECUTED',result.get('last_error')
  for sid,e in new._active_engines().items():assert count(e,'paper_fills')==before[sid]+1
 finally:new.close()

def test_paper_expired_first_permission_never_creates_batch(paper):
 c,s,q=paper;paper_grant(c,deadline=NOW+timedelta(seconds=1))
 result=paper_tick(c,q,NOW+timedelta(seconds=2))
 assert result['status']=='MISSED_OPEN'
 assert all(count(e,'paper_batches')==0 for e in c._active_engines().values())

@pytest.mark.parametrize('failure',['ledger','plan','source','permission'])
def test_paper_first_cas_drift_rejects(paper,failure):
 c,s,q=paper;paper_grant(c)
 if failure=='ledger':c.engines[SID]._set('paper',{'cash':9001.,'positions':{'US.OLD':10},'fees':0.})
 elif failure=='plan':c.plans[SID]['rows'][0]['target_weight']=.09
 elif failure=='source':
  old=s.status;s.status=lambda now=None:{**old(now),'source_refs':{**REFS,'extra':{'sha256':'b'*64}}}
 else:c.engines[SID]._set('paper_first_execution',{})
 result=paper_tick(c,q)
 assert result['status']=='BLOCKED'
 assert all(count(e,'orders')==0 for e in c._active_engines().values())

def test_paper_second_signal_uses_original_open_not_first_permission(paper):
 c,s,q=paper;paper_grant(c);s.opening+=timedelta(days=1)
 result=paper_tick(c,q,NOW+timedelta(days=1))
 assert result['status']=='MISSED_OPEN'
 assert all(count(e,'orders')==0 for e in c._active_engines().values())

@pytest.mark.parametrize('change',[{'execution_date':'2026-10-09'},{'deadline_utc':(NOW+timedelta(seconds=601)).isoformat()},
 {'expected_package_sha256':'b'*64},{'expected_plan_sha256_by_book':{SID:'b'*64,'HGB_FACTOR_5':'b'*64}}])
def test_paper_bad_grant_rejects(paper,change):
 c,s,q=paper
 with pytest.raises(ValueError):paper_grant(c,**change)
 assert all(e._get('paper_first_execution',None) is None for e in c._active_engines().values())

def test_paper_same_grant_idempotent_different_id_no_renewal(paper):
 c,s,q=paper;g=paper_grant(c);assert paper_grant(c)==g
 with pytest.raises(ValueError,match='NO_RENEWAL'):paper_grant(c,authorization_id='changed_grant_id')

@pytest.fixture
def sim(tmp_path):
 f=BF.FakeBroker
 f.positions={};f.submissions=[];f.cash=1000000.;f.clock=staticmethod(lambda:NOW)
 f.prewarm_calls=[];f.snapshot_calls=[];f.quote_errors={};f.submit_options=[];f.before_send_error=None
 f.reconcile_result=None;f.reconcile_calls=[];f.market_prices={}
 source=Source(broker=True);e=Engine(tmp_path/'sim',broker_factory=f)
 runner=BestBroker(tmp_path/'sim',source,engine=e,execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True,now=lambda:NOW)
 runner._connect();runner.stop_event.clear();runner._prepare(NOW);runner.stop_event.set();e.stop()
 runner._accept_snapshot(e.broker.snapshot([],include_quotes=False))
 try:yield runner,source,f
 finally:
  if not getattr(runner,'_fixture_closed',False):runner.close()

def sim_grant(r,**changes):
 args=dict(execution_date='2026-10-08',deadline_utc=(NOW+timedelta(seconds=600)).isoformat(),
  authorization_id='offline_sim_first_20261008',expected_package_sha256='a'*64,
  expected_plan_sha256=_first_execution_sha(r.plan),account_id=r.engine.account_id,now=NOW)
 args.update(changes);return r.authorize_first_execution(**args)

def sim_tick(r,f,now=NOW):
 f.clock=staticmethod(lambda:now);r._now=lambda:now;r.stop_event.clear();r.engine.cancel_step.clear()
 with real_clock(now):r.tick(now=now)

def test_sim_no_permission_cannot_send_first_order(sim):
 r,s,f=sim;sim_tick(r,f)
 assert r.status=='MISSED_OPEN' and f.submissions==[]

def test_sim_permission_only_then_original_state_machine_initializes_and_reconciles(sim):
 r,s,f=sim;before=deepcopy(r.engine._get('best_execution',{}));g=sim_grant(r)
 assert r.stop_event.is_set() and f.submissions==[] and r.engine._get('best_execution',{})==before
 for i in range(5):sim_tick(r,f,NOW+timedelta(seconds=i))
 state=r.engine._get('best_execution',{})
 assert state['phase']=='DONE',state
 assert f.submissions and all(o['side']=='BUY' for o in f.submissions)
 assert state['first_execution_permission_sha256']==_first_execution_sha(g)
 assert all(x['execution_deadline_utc']==g['deadline_utc'] for x in f.submit_options)
 n=len(f.submissions);sim_tick(r,f,NOW+timedelta(seconds=8));assert len(f.submissions)==n

def test_sim_restart_no_duplicate_and_expired_pending_only_reconciles(sim):
 r,s,f=sim;g=sim_grant(r);sim_tick(r,f)
 assert r.engine._pending()
 prior=len(f.submissions);r.stop()
 # New original runner over the same Engine simulates persisted controller restart, no new grant.
 new=BestBroker(r.engine.path,s,engine=r.engine,now=lambda:NOW+timedelta(seconds=601))
 new.plan=deepcopy(r.engine._get('best_plan',{})['plan']);new.metadata=deepcopy(r.engine._get('best_plan',{})['metadata'])
 new.snapshot=deepcopy(r.snapshot);new.last_snapshot_at=time.monotonic();new.prepared_at=time.monotonic()
 sim_tick(new,f,NOW+timedelta(seconds=601))
 assert not new.engine._pending() and len(f.submissions)==prior
 assert new.status in {'MISSED_OPEN','PARTIALLY_EXECUTED','EXECUTED'}

@pytest.mark.parametrize('failure',['account','budget','plan','baseline','source','unknown'])
def test_sim_binding_drift_or_unknown_rejects(sim,failure):
 r,s,f=sim;sim_grant(r)
 if failure=='account':r.engine.account_id='different'
 elif failure=='budget':r.budget=10001
 elif failure=='plan':r.plan['rows'][0]['target_weight']=.09
 elif failure=='baseline':f.cash+=1
 elif failure=='source':
  old=s.status;s.status=lambda now=None:{**old(now),'source_refs':{**REFS,'extra':'changed'}}
 else:r.engine._halt('unknown original order')
 with pytest.raises(ValueError):sim_tick(r,f)
 assert f.submissions==[]

def test_sim_expiry_during_synchronous_quote_batch_prevents_original_step(sim):
 r,s,f=sim;sim_grant(r)
 original=r.engine.broker.snapshot_partial
 def slow(codes):
  result=original(codes);r._now=lambda:NOW+timedelta(seconds=601);return result
 with patch.object(r.engine.broker,'snapshot_partial',side_effect=slow):
  r.stop_event.clear();r.engine.cancel_step.clear()
  with real_clock(NOW):r.tick(now=NOW)
 assert f.submissions==[] and r.status=='PARTIALLY_EXECUTED'

def test_sim_second_signal_cannot_inherit_grant(sim):
 r,s,f=sim;sim_grant(r);s.opening+=timedelta(days=1);r.prepared_at=0
 sim_tick(r,f,NOW+timedelta(days=1))
 assert r.status=='MISSED_OPEN' and f.submissions==[]

def test_sim_original_held_sell_must_reconcile_before_buy(sim):
 r,s,f=sim
 # Add a fully reconciled original pre-signal holding via original tables, offline only.
 f.positions={'US.OLD':10};f.cash-=1000
 e=r.engine
 e.db.execute('INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
  ('prior',CLOSE.isoformat(),SID,'moomoo_simulate',e.account_id,'US.OLD','BUY',10,100,'FILLED_ALL','prior-order'))
 e.db.execute('INSERT INTO order_fills VALUES (?,?)',('prior',json.dumps({'fill_qty':10,'fill_price':100})));e.db.commit()
 r._accept_snapshot(e.broker.snapshot([],include_quotes=False));sim_grant(r)
 sim_tick(r,f);assert [o['side'] for o in f.submissions]==['SELL']
 assert e._pending()
 sim_tick(r,f,NOW+timedelta(seconds=1))
 assert f.reconcile_calls and all(o['status']=='FILLED_ALL' for o in e.state()['orders'] if o['side']=='SELL')
 for i in range(2,7):sim_tick(r,f,NOW+timedelta(seconds=i))
 assert f.submissions[0]['side']=='SELL' and any(o['side']=='BUY' for o in f.submissions[1:])
 assert 'US.OLD' not in {k:v for k,v in f.positions.items() if v}


def test_paper_existing_catchup_cannot_initialize_absent_batch(paper):
 c,s,q=paper
 with pytest.raises(ValueError):c.authorize_catchup(execution_date='2026-10-08',deadline_utc=(NOW+timedelta(seconds=600)).isoformat(),now=NOW)
 assert all(count(e,'paper_batches')==0 for e in c._active_engines().values())

@pytest.mark.parametrize('bad',[{'asof':(NOW-timedelta(seconds=31)).isoformat()}, {'ask':102.,'bid':98.}, {'tradable':False}])
def test_paper_bad_quotes_preserve_unspent_targets(paper,bad):
 c,s,q=paper;paper_grant(c);q.overrides={code:bad for code in ('US.OLD','US.AAPL','US.MSFT')}
 paper_tick(c,q)
 assert all(count(e,'paper_fills')==0 and e._get('paper',{})['positions']=={'US.OLD':10} for e in c._active_engines().values())

def test_paper_partial_group_permission_never_starts_books(paper):
 c,s,q=paper
 engine=c.engines['HGB_FACTOR_5'];original=engine._store_first_execution_permission
 def fail(key,value):
  if key=='paper_first_execution':raise OSError('fixture second DB failure')
  return original(key,value)
 with patch.object(engine,'_store_first_execution_permission',side_effect=fail):
  with pytest.raises(OSError):paper_grant(c)
 assert c.stop_event.is_set() and 'paper_first_execution' not in c.meta
 result=paper_tick(c,q)
 assert result['status']=='MISSED_OPEN'
 assert all(count(e,'paper_batches')==0 for e in c._active_engines().values())

def test_sim_new_engine_restart_uses_same_permit_not_a_new_authorization(sim):
 r,s,f=sim;g=sim_grant(r);f.quote_errors={'US.AAPL':'missing','US.MSFT':'missing'}
 sim_tick(r,f);assert not f.submissions
 path=r.engine.path;r.close();r._fixture_closed=True
 e=Engine(path,broker_factory=f);new=BestBroker(path,s,engine=e,now=lambda:NOW+timedelta(seconds=2))
 try:
  new._connect();new.stop_event.clear();new._prepare(NOW+timedelta(seconds=2));f.quote_errors={}
  sim_tick(new,f,NOW+timedelta(seconds=2))
  assert e._get('best_first_execution',None)==g and f.submissions
  assert all(x['execution_deadline_utc']==g['deadline_utc'] for x in f.submit_options)
 finally:new.close()

@pytest.mark.parametrize('change',[{'account_id':'not-original'},{'deadline_utc':(NOW+timedelta(seconds=601)).isoformat()},
 {'expected_plan_sha256':'b'*64},{'execution_date':'2026-10-09'}])
def test_sim_invalid_grant_no_write_or_order(sim,change):
 r,s,f=sim
 with pytest.raises(ValueError):sim_grant(r,**change)
 assert r.engine._get('best_first_execution',None) is None and f.submissions==[]

def test_sim_grant_idempotent_but_not_renewable(sim):
 r,s,f=sim;g=sim_grant(r);assert sim_grant(r)==g
 with pytest.raises(ValueError,match='NO_RENEWAL'):sim_grant(r,authorization_id='different_authorization')
 assert r.engine._get('best_first_execution',None)==g and not f.submissions


def test_first_execution_server_only_uses_server_utc_and_never_starts():
 from unittest.mock import Mock
 from moomoo_component import server
 sf=fixture_module('server_configuration');fixture=sf.CatchupRoutingTests();fixture.setUp()
 owner=Mock(spec=['authorize_first_execution','start','best_broker'])
 owner.authorize_first_execution.return_value={'authorized':True}
 fixture.fixture.cohort=owner
 body={'execution_date':'2026-10-08','deadline_utc':(NOW+timedelta(seconds=600)).isoformat(),
  'authorization_id':'offline_grant_id','expected_package_sha256':'a'*64,
  'expected_plan_sha256_by_book':{sid:'b'*64 for sid in HGB_STRATEGIES}}
 with patch.object(server,'datetime') as clock:
  clock.now.return_value=NOW;code,response=fixture.request(body,path='/api/applied/first-execution')
 assert code==200
 owner.authorize_first_execution.assert_called_once_with(**body,now=NOW);owner.start.assert_not_called()
 broker=Mock(spec=['authorize_first_execution','start','engine'])
 broker.engine._get.return_value='3604';broker.authorize_first_execution.return_value={'authorized':True}
 owner.best_broker=broker;body.pop('expected_plan_sha256_by_book');body['expected_plan_sha256']='b'*64
 with patch.object(server,'datetime') as clock:
  clock.now.return_value=NOW;code,response=fixture.request(body,path='/api/applied/broker-first-execution')
 assert code==200
 broker.authorize_first_execution.assert_called_once_with(**body,account_id='3604',now=NOW)
 broker.start.assert_not_called()

@pytest.mark.parametrize('extra', ['account_id','qty','weights','now','budget','execution_delay_minutes'])
def test_first_execution_server_rejects_extra_control_fields(extra):
 from unittest.mock import Mock
 sf=fixture_module('server_configuration');fixture=sf.CatchupRoutingTests();fixture.setUp()
 owner=Mock(spec=['authorize_first_execution','start','best_broker']);fixture.fixture.cohort=owner
 body={'execution_date':'2026-10-08','deadline_utc':(NOW+timedelta(seconds=600)).isoformat(),
  'authorization_id':'offline_grant_id','expected_package_sha256':'a'*64,
  'expected_plan_sha256_by_book':{sid:'b'*64 for sid in HGB_STRATEGIES},extra:1}
 code,response=fixture.request(body,path='/api/applied/first-execution')
 assert code==400;owner.authorize_first_execution.assert_not_called();owner.start.assert_not_called()


def test_paper_group_persist_failure_cannot_be_committed_by_later_start(paper):
 c,s,q=paper
 with patch.object(c,'_persist',side_effect=OSError('fixture group commit failure')):
  with pytest.raises(OSError):paper_grant(c)
 assert c.stop_event.is_set() and 'paper_first_execution' not in c.meta
 assert c.db.execute("SELECT 1 FROM settings WHERE key='paper_first_execution:2026-10-07'").fetchone() is None
 # All per-book permits exist, but the original controller cannot execute an uncommitted group.
 assert all(e._get('paper_first_execution',None) for e in c._active_engines().values())
 with patch.object(cohort.threading,'Thread',CF.NoWorker):c.start()
 result=paper_tick(c,q)
 assert result['status']=='MISSED_OPEN'
 assert all(count(e,'paper_batches')==0 and count(e,'orders')==0 for e in c._active_engines().values())

def test_paper_old_epoch_same_day_waiting_batch_rejects_first_grant(paper):
 c,s,q=paper;e=c.engines[SID]
 e.db.execute('INSERT INTO paper_batches VALUES (?,?)',('different-old-epoch',json.dumps({
  'signal_date':'2026-10-07','execution_date':'2026-10-08','status':'WAITING_QUOTES'})));e.db.commit()
 with pytest.raises(ValueError,match='ALREADY_ATTEMPTED'):paper_grant(c)
 assert e._get('paper_first_execution',None) is None and count(e,'orders')==0

def test_paper_elapsed_time_including_sql_write_lock_cannot_cross_first_deadline(paper):
 from types import SimpleNamespace
 c,s,q=paper;paper_grant(c);e=c.engines[SID];q.clock=NOW
 values=iter([100.,701.])
 with patch.object(core,'time',SimpleNamespace(monotonic=lambda:next(values))):
  with pytest.raises(ValueError,match='EXPIRED_BEFORE_COMMIT'):
   e.paper_rebalance(SID,c.plans[SID],q.quotes(['US.OLD','US.AAPL','US.MSFT']),now=NOW,
    next_open_utc=OPEN.isoformat(),signal_date='2026-10-07',execution_date='2026-10-08',
    signal_close_utc=CLOSE.isoformat(),source_refs=c.plan_metadata['source_refs'],allow_partial_quotes=True,execution_window_seconds=600)
 assert count(e,'paper_batches')==0 and count(e,'orders')==0 and e._get('paper',{})['cash']==8700.

def test_paper_synchronous_quotes_crossing_deadline_do_not_create_batch(paper):
 c,s,q=paper;paper_grant(c);clock={'value':NOW};q.clock=NOW;old=q.quotes_partial
 def slow(codes):
  result=old(codes);clock['value']=NOW+timedelta(seconds=601);return result
 c.stop_event.clear()
 for e in c._active_engines().values():e.cancel_step.clear()
 with patch.object(q,'quotes_partial',side_effect=slow),patch.object(cohort,'_now',side_effect=lambda value=None:value or clock['value']):
  c.tick()
 assert all(count(e,'paper_batches')==0 and count(e,'orders')==0 for e in c._active_engines().values())

def test_future_explicit_paper_grant_keeps_old_complete_permission_without_auto_inheritance(paper):
 c,s,q=paper;old=paper_grant(c);s.opening+=timedelta(days=1);later=NOW+timedelta(days=1)
 c._prepare(s.status(later),later);c._persist()
 new=paper_grant(c,execution_date='2026-10-09',now=later,deadline_utc=(later+timedelta(seconds=600)).isoformat(),authorization_id='offline_next_explicit_grant')
 assert new['signal_date']=='2026-10-08'
 assert json.loads(c.db.execute("SELECT value FROM settings WHERE key='paper_first_execution:2026-10-07'").fetchone()[0])==old
 for sid,e in c._active_engines().items():
  assert e._get('paper_first_execution:2026-10-07',None)==old['books'][sid]
  assert e._get('paper_first_execution',None)==new['books'][sid]
  assert count(e,'paper_batches')==0

def test_future_explicit_sim_grant_keeps_old_complete_permission(sim):
 r,s,f=sim;old=sim_grant(r);s.opening+=timedelta(days=1);later=NOW+timedelta(days=1)
 r.stop_event.clear();r._prepare(later);r.stop_event.set();r._accept_snapshot(r.engine.broker.snapshot([],include_quotes=False))
 new=sim_grant(r,execution_date='2026-10-09',now=later,deadline_utc=(later+timedelta(seconds=600)).isoformat(),authorization_id='offline_next_explicit_grant')
 assert new['signal_date']=='2026-10-08'
 assert r.engine._get('best_first_execution:2026-10-07',None)==old and r.engine._get('best_first_execution',None)==new
 assert f.submissions==[]


def test_paper_elapsed_clock_starts_before_engine_lock_wait(paper):
 from types import SimpleNamespace
 c,s,q=paper;paper_grant(c);e=c.engines[SID];q.clock=NOW;clock={'mono':100.};original=e.lock
 class SlowLock:
  def __enter__(self):original.acquire();clock['mono']=701.;return self
  def __exit__(self,*args):original.release()
 with patch.object(e,'lock',SlowLock()),patch.object(core,'time',SimpleNamespace(monotonic=lambda:clock['mono'])):
  with pytest.raises(ValueError,match='EXPIRED_BEFORE_COMMIT'):
   e.paper_rebalance(SID,c.plans[SID],q.quotes(['US.OLD','US.AAPL','US.MSFT']),now=NOW,
    next_open_utc=OPEN.isoformat(),signal_date='2026-10-07',execution_date='2026-10-08',
    signal_close_utc=CLOSE.isoformat(),source_refs=c.plan_metadata['source_refs'],allow_partial_quotes=True,execution_window_seconds=600)
 assert count(e,'paper_batches')==0 and count(e,'orders')==0


@pytest.mark.parametrize('key,value',[('execution_delay_minutes',1),('execution_window_seconds',601),('allow_partial_quotes',False)])
def test_paper_explicit_saved_policy_conflict_rejects_grant(paper,key,value):
 c,s,q=paper;c.plan_metadata[key]=value
 with pytest.raises(ValueError,match='BINDING_INVALID'):paper_grant(c)
 assert all(e._get('paper_first_execution',None) is None for e in c._active_engines().values())

@pytest.mark.parametrize('key,value',[('execution_delay_minutes',1),('execution_window_seconds',601),('allow_partial_quotes',False)])
def test_sim_explicit_saved_policy_conflict_rejects_grant(sim,key,value):
 r,s,f=sim;saved=r.engine._get('best_plan',{});saved['metadata'][key]=value;r.engine._set('best_plan',saved)
 with pytest.raises(ValueError,match='BINDING_INVALID'):sim_grant(r)
 assert r.engine._get('best_first_execution',None) is None and not f.submissions

def test_paper_direct_owner_rejects_mutated_active_permission_before_first_batch(paper):
 c,s,q=paper;paper_grant(c,deadline=NOW+timedelta(seconds=300));e=c.engines[SID];q.clock=NOW
 changed=e._get('paper_first_execution',None);changed['deadline_utc']=(NOW+timedelta(seconds=400)).isoformat()
 e._set('paper_first_execution',changed)
 with pytest.raises(ValueError,match='IMMUTABLE_PERMISSION_CHANGED'):
  e.paper_rebalance(SID,c.plans[SID],q.quotes(['US.OLD','US.AAPL','US.MSFT']),now=NOW,
   next_open_utc=OPEN.isoformat(),signal_date='2026-10-07',execution_date='2026-10-08',
   signal_close_utc=CLOSE.isoformat(),source_refs=c.plan_metadata['source_refs'],allow_partial_quotes=True,execution_window_seconds=600)
 assert count(e,'paper_batches')==0 and count(e,'orders')==0

def test_sim_mutated_active_deadline_cannot_override_immutable_grant(sim):
 r,s,f=sim;sim_grant(r,deadline_utc=(NOW+timedelta(seconds=300)).isoformat())
 changed=r.engine._get('best_first_execution',None);changed['deadline_utc']=(NOW+timedelta(seconds=400)).isoformat()
 r.engine._set('best_first_execution',changed)
 with pytest.raises(ValueError,match='IMMUTABLE_PERMISSION_CHANGED'):sim_tick(r,f)
 assert f.submissions==[]


def _closed_first_fixture():
 case=BF.ClosedBrokerTests();case.setUp();case.make()
 r,e=case.runner,case.engine;saved=e._get('best_plan',{})
 m=saved['metadata'];capital=e._get('best_capital',{})
 authorized=case.opening+timedelta(seconds=601)
 record=dict(reason='USER_REQUESTED_SAME_DAY_FIRST_EXECUTION',authorization_id='offline_closed_first',
  signal_date=m['signal_date'],execution_date=m['execution_date'],account_id=e.account_id,
  source_plan_sha256=_first_execution_sha(saved['plan']),source_refs=deepcopy(m['source_refs']),
  expected_package_sha256=m['source_refs']['selected/package.json']['sha256'],
  authorized_at_utc=authorized.isoformat(),deadline_utc=(authorized+timedelta(seconds=600)).isoformat(),
  next_open_utc=m['next_open_utc'],signal_close_utc=m['signal_close_utc'],next_close_utc=m['next_close_utc'],
  execution_delay_minutes=0,execution_window_seconds=600,budget=r.budget,unused_cash=capital['unused_cash'],
  frozen_metadata_sha256=_first_execution_sha(m),pre_first_book_sha256='unused_after_original_state_initialization')
 e._store_first_execution_permission('best_first_execution',record)
 state=e._get('best_execution',{});state['first_execution_permission_sha256']=_first_execution_sha(record)
 e._set('best_execution',state)
 case.now=authorized+timedelta(seconds=601);r._now=lambda:case.now
 return case,record


def test_expired_first_chart_package_uses_original_closed_history_without_sdk_or_replan():
 case,record=_closed_first_fixture()
 try:
  r=case.runner;before=case.frozen()
  with patch.object(case.source,'load',side_effect=AssertionError('no inference')),patch.object(case.source,'close_states',side_effect=AssertionError('no old close')),patch.object(BF.FakeBroker,'snapshot',side_effect=AssertionError('no SDK')),patch.object(case.engine,'step',side_effect=AssertionError('no step')):
   r.tick(now=case.now)
  assert case.frozen()==before and r.status=='PARTIALLY_EXECUTED'
  assert case.engine._get('best_first_execution',{})==record and BF.FakeBroker.submissions==[]
 finally:case.tearDown()


def test_unexpired_first_chart_package_still_rejects_fresh_source_change():
 case,record=_closed_first_fixture()
 try:
  case.now=datetime.fromisoformat(record['deadline_utc'])-timedelta(seconds=1)
  with pytest.raises(ValueError,match='BEST_FIRST_EXECUTION_SOURCE_CHANGED'):
   case.runner._prepare(case.now)
  assert BF.FakeBroker.submissions==[]
 finally:case.tearDown()


def test_expired_first_chart_package_still_rejects_original_economic_change():
 case,record=_closed_first_fixture()
 try:
  case.d['package']['shared_scores']['current']['rows'][0]['pred_hgb']+=.01
  case.republish()
  with pytest.raises(ValueError,match='PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):
   case.runner._prepare(case.now)
  assert BF.FakeBroker.submissions==[]
 finally:case.tearDown()


def test_expired_first_chart_package_still_rejects_mutated_immutable_permission():
 case,record=_closed_first_fixture()
 try:
  changed=deepcopy(record);changed['deadline_utc']=(datetime.fromisoformat(record['deadline_utc'])-timedelta(seconds=1)).isoformat()
  case.engine._set('best_first_execution',changed)
  with pytest.raises(ValueError,match='BEST_FIRST_EXECUTION_IMMUTABLE_PERMISSION_CHANGED'):
   case.runner._prepare(case.now)
  assert BF.FakeBroker.submissions==[]
 finally:case.tearDown()


def test_expired_first_execution_default_runtime_still_requires_strict_fresh_source():
 case,record=_closed_first_fixture()
 try:
  case.runner.plan=deepcopy(case.saved['plan']);case.runner.metadata=deepcopy(case.saved['metadata'])
  with pytest.raises(ValueError,match='BEST_FIRST_EXECUTION_SOURCE_CHANGED'):
   case.runner._first_execution_end(case.now)
  assert BF.FakeBroker.submissions==[]
 finally:case.tearDown()


# Normal LEGACY account targets intentionally differ from the published CASH_START.
def display_fixture(owner,source,tmp_path,broker=False,snapshot_policy="MISSING"):
 from moomoo_component.applied_source import LEGACY_POLICY,_state,_PROVENANCE
 signal='2026-10-07'
 if broker:
  saved=owner.engine._get('best_plan',{});plans={SID:deepcopy(owner.plan)};states={SID:deepcopy(saved['close_state'])}
 else:plans={sid:deepcopy(owner.plans[sid]) for sid in HGB_STRATEGIES};states=deepcopy(owner.close_states)
 for sid,plan in plans.items():
  for ticker,weight in states[sid]['weights'].items():
   if not any(row['code']=='US.'+ticker for row in plan['rows']):
    plan['rows'].append(dict(ticker=ticker,code='US.'+ticker,target_weight=0.,weight_before=weight))
  plan.update(strategy_id=sid,status='READY',signal_date=signal,source_date=signal,execution_date='2026-10-08',
   cash_weight_before=states[sid]['cash_weight'],valuation_basis='SIGNAL_CLOSE',execution_status='TARGET_ONLY',
   provenance=_PROVENANCE,model_fit_calls=0,broker_action_allowed=False)
 cash=deepcopy(plans)
 for plan in cash.values():
  for row in plan['rows']:row['target_weight']=.03 if row['target_weight'] else 0.
  plan['target_cash_weight']=1-sum(row['target_weight'] for row in plan['rows'])
 d=BF._closed_decision_fixture(tmp_path,signal,cash)
 # Original LEGACY histories omit policy_id, while current packages now name it.
 d['snapshot'].pop('policy_id')
 if snapshot_policy!='MISSING':d['snapshot']['policy_id']=snapshot_policy
 for app in d['snapshot']['applications'].values():app.pop('policy_id')
 h='history/'+signal+'.json'
 ref=BF._closed_write(d['folder']/'snapshot.json',d['snapshot'])
 d['package']['policy_id']=LEGACY_POLICY
 for value in d['package']['strategies'].values():value['application']['policy_id']=LEGACY_POLICY
 d['package']['source_refs'][h]=ref;d['package']['source_hashes'][h]=ref['sha256']
 d['refs']['selected/package.json']=BF._closed_write(d['folder']/'latest.json',d['package'])
 for plan in plans.values():
  plan['source_hashes']=deepcopy(d['package']['source_hashes']);plan['source_refs']=deepcopy(d['refs'])
 source.runtime_root=tmp_path/'original_owner';ap=source.runtime_root/signal/'plans.json';ap.parent.mkdir(parents=True)
 archive=dict(source_date=signal,execution_date='2026-10-08',next_open_utc=OPEN.isoformat(),
  next_close_utc=(OPEN+timedelta(hours=6,minutes=30)).isoformat(),model_fit_calls=0,provenance=_PROVENANCE,
  plans=deepcopy(plans),states={sid:_state(states[sid],signal) for sid in plans},
  scores=deepcopy(d['package']['shared_scores']),source_hashes=deepcopy(d['package']['source_hashes']),source_refs=deepcopy(d['refs']))
 d['archive']=archive;d['archive_ref']=BF._closed_write(ap,archive)
 base=source.status;d['live_refs']=deepcopy(d['refs'])
 source.status=lambda now=None:{**base(now),'source_refs':deepcopy(d['live_refs'])}
 if broker:
  owner.plan=deepcopy(plans[SID]);owner.metadata['source_refs']=deepcopy(d['refs'])
  saved.update(plan=deepcopy(owner.plan),metadata=deepcopy(owner.metadata));owner.engine._set('best_plan',saved)
 else:
  owner.plans.update(deepcopy(plans));owner.plan_metadata['source_refs']=deepcopy(d['refs']);owner._persist()
 d['plans']=plans;d['original_archive_bytes']=ap.read_bytes();d['original_plan_sha']={sid:_first_execution_sha(plan) for sid,plan in plans.items()}
 display_republish(d)
 assert any([(r['code'],r['target_weight']) for r in plans[sid]['rows']] !=
  [('US.'+r['ticker'],r['target_weight']) for r in d['snapshot']['applications'][sid]['rows']] for sid in plans)
 return d

def display_republish(d):
 d['package']['source_hashes']['performance_extension/manifest']=str(len(json.dumps(d['package'])))+'display'
 d['package']['display_revision']=d['package'].get('display_revision',0)+1
 d['live_refs']['selected/package.json']=BF._closed_write(d['folder']/'latest.json',d['package'])

def dg(c,d,**changes):return paper_grant(c,expected_package_sha256=d['live_refs']['selected/package.json']['sha256'],**changes)
def sg(r,d,**changes):return sim_grant(r,expected_package_sha256=d['live_refs']['selected/package.json']['sha256'],**changes)

def test_display_paper_actual_account_plans_first_batch_restart_and_old_economic_refs(paper,tmp_path):
 c,s,q=paper;d=display_fixture(c,s,tmp_path);g=dg(c,d)
 assert g['display_binding']==g['books'][SID]['display_binding']==g['books']['HGB_FACTOR_5']['display_binding']
 assert g['request']['expected_package_sha256']==d['live_refs']['selected/package.json']['sha256']
 assert g['books'][SID]['expected_package_sha256']==d['refs']['selected/package.json']['sha256']
 assert paper_tick(c,q)['status']=='EXECUTED'
 assert Path(d['archive_ref']['path']).read_bytes()==d['original_archive_bytes']
 assert {sid:_first_execution_sha(c.plans[sid]) for sid in HGB_STRATEGIES}==d['original_plan_sha']
 path=c.path;c.close();n=Cohort(path,s,q)
 try:
  assert n.meta['paper_first_execution']==g
  counts=[count(e,'paper_fills') for e in n._active_engines().values()]
  assert paper_tick(n,q,NOW+timedelta(seconds=2))['status']=='EXECUTED'
  assert counts==[count(e,'paper_fills') for e in n._active_engines().values()]
 finally:n.close()

def test_display_sim_original_path_grant_then_execute_no_archive_or_plan_rewrite(sim,tmp_path):
 r,s,f=sim;d=display_fixture(r,s,tmp_path,True);g=sg(r,d)
 assert sg(r,d)==g
 assert g['expected_package_sha256']==d['refs']['selected/package.json']['sha256']
 sim_tick(r,f)
 assert f.submissions and Path(d['archive_ref']['path']).read_bytes()==d['original_archive_bytes']
 assert _first_execution_sha(r.plan)==d['original_plan_sha'][SID]
 assert r.engine._get('best_first_execution',{})==g

@pytest.mark.parametrize('case',['mu','target','cash','leaf','state','archive','policy','history','oldrefs'])
def test_display_pregrant_economic_or_state_drift_rejected(paper,tmp_path,case):
 c,s,q=paper;d=display_fixture(c,s,tmp_path)
 if case=='mu':d['package']['shared_scores']['current']['rows'][0]['pred_hgb']+=.1
 elif case=='target':d['package']['strategies'][SID]['application']['rows'][0]['target_weight']+=.01
 elif case=='cash':d['package']['strategies'][SID]['application']['target_cash_weight']+=.01
 elif case=='leaf':Path(d['refs']['current/features.parquet']['path']).write_bytes(b'changed original feature')
 elif case=='state':c.close_states[SID]['cash_weight']-=.01
 elif case=='archive':
  d['archive']['plans'][SID]['rows'][0]['target_weight']+=.01;BF._closed_write(Path(d['archive_ref']['path']),d['archive'])
 elif case=='policy':d['package']['policy_id']='HGB_TOP20_RISK_R1'
 elif case=='history':d['package']['source_refs']['history/2026-10-07.json']['sha256']='0'*64
 else:d['live_refs']['current/features.parquet']['sha256']='0'*64
 display_republish(d)
 with pytest.raises(ValueError):dg(c,d)
 assert c.meta.get('paper_first_execution') is None
 assert all(e._get('paper_first_execution',None) is None and count(e,'paper_batches')==0 for e in c._active_engines().values())

@pytest.mark.parametrize('broker',[False,True])
def test_display_active_accepts_only_bound_package_and_expired_readonly_at_exact_deadline(paper,sim,tmp_path,broker):
 c,s,q=sim if broker else paper;d=display_fixture(c,s,tmp_path,broker);g=sg(c,d) if broker else dg(c,d)
 deadline=datetime.fromisoformat(g['deadline_utc']);display_republish(d)
 call=lambda clock:c._first_execution_end(clock) if broker else c._first_execution_end(s.status(clock),clock)
 with pytest.raises(ValueError,match='DISPLAY_BINDING_CHANGED'):call(deadline-timedelta(microseconds=1))
 with patch.object(c.engine if broker else c.engines[SID],'_pending',return_value=[{'id':'pending'}]):
  with pytest.raises(ValueError,match='DISPLAY_BINDING_CHANGED'):call(deadline)
 assert call(deadline)==deadline
 assert (c.engine._get('best_first_execution',{}) if broker else c.meta['paper_first_execution'])==g
 assert all(count(e,'orders')==0 for e in ([c.engine] if broker else c._active_engines().values()))

@pytest.mark.parametrize('case',['mu','target','cash','leaf'])
def test_display_expired_still_rejects_economic_changes(sim,tmp_path,case):
 r,s,f=sim;d=display_fixture(r,s,tmp_path,True);g=sg(r,d)
 if case=='mu':d['package']['shared_scores']['current']['rows'][0]['pred_hgb']+=.1
 elif case=='target':d['package']['strategies'][SID]['application']['rows'][0]['target_weight']+=.1
 elif case=='cash':d['package']['strategies'][SID]['application']['target_cash_weight']+=.1
 else:Path(d['refs']['current/features.parquet']['path']).write_bytes(b'changed')
 display_republish(d)
 with pytest.raises(ValueError):r._first_execution_end(datetime.fromisoformat(g['deadline_utc']))
 assert f.submissions==[] and r.engine._get('best_first_execution',{})==g

@pytest.mark.parametrize('broker',[False,True])
def test_display_proof_tamper_and_next_signal_noninheritance(paper,sim,tmp_path,broker):
 c,s,q=sim if broker else paper;d=display_fixture(c,s,tmp_path,broker);g=sg(c,d) if broker else dg(c,d)
 call=lambda clock:c._first_execution_end(clock) if broker else c._first_execution_end(s.status(clock),clock)
 if broker:
  changed=deepcopy(g);changed['display_binding']['accepted_package_ref']['sha256']='0'*64
  c.engine._set('best_first_execution',changed)
 else:
  changed=deepcopy(g);changed['display_binding']['accepted_package_ref']['sha256']='0'*64;c.meta['paper_first_execution']=changed
 with pytest.raises(ValueError):call(NOW)
 if broker:
  c.engine._set('best_first_execution',g);c.metadata={**c.metadata,'signal_date':'2026-10-08'}
 else:c.meta['paper_first_execution']=g;s.opening+=timedelta(days=1)
 assert call(NOW+timedelta(days=1)) is None


@pytest.mark.parametrize('broker',[False,True])
def test_display_request_must_cas_current_new_package_not_old_economic_hash(paper,sim,tmp_path,broker):
 c,s,q=sim if broker else paper;d=display_fixture(c,s,tmp_path,broker)
 with pytest.raises(ValueError,match='REVIEWED_PLAN_CHANGED'):
  (sim_grant if broker else paper_grant)(c,expected_package_sha256=d['refs']['selected/package.json']['sha256'])
 assert (c.engine._get('best_first_execution',None) if broker else c.meta.get('paper_first_execution')) is None

@pytest.mark.parametrize('broker',[False,True])
def test_display_postgrant_original_close_state_tamper_rejected(paper,sim,tmp_path,broker):
 c,s,q=sim if broker else paper;d=display_fixture(c,s,tmp_path,broker)
 g=sg(c,d) if broker else dg(c,d)
 if broker:
  saved=c.engine._get('best_plan',{});saved['close_state']['cash_weight']-=.01;c.engine._set('best_plan',saved)
 else:c.close_states[SID]['cash_weight']-=.01
 with pytest.raises(ValueError):
  c._first_execution_end(NOW) if broker else c._first_execution_end(s.status(NOW),NOW)
 assert (c.engine._get('best_first_execution',{}) if broker else c.meta['paper_first_execution'])==g

@pytest.mark.parametrize('broker',[False,True])
def test_display_expired_tick_cannot_submit_on_later_equivalent_chart_package(paper,sim,tmp_path,broker):
 c,s,q=sim if broker else paper;d=display_fixture(c,s,tmp_path,broker)
 g=sg(c,d) if broker else dg(c,d);deadline=datetime.fromisoformat(g['deadline_utc'])
 display_republish(d)
 if broker:
  sim_tick(c,q,deadline)
  assert q.submissions==[] and count(c.engine,'orders')==0
 else:
  result=paper_tick(c,q,deadline)
  assert result['status']=='MISSED_OPEN',result
  assert all(count(e,'orders')==count(e,'paper_batches')==0 for e in c._active_engines().values())
 assert (c.engine._get('best_first_execution',{}) if broker else c.meta['paper_first_execution'])==g


def test_display_coordinated_archive_history_application_rewrite_cannot_replace_original_plan_hash_anchor(paper,tmp_path):
 c,s,q=paper;d=display_fixture(c,s,tmp_path);h='history/2026-10-07.json'
 d['snapshot']['applications'][SID]['rows'][0]['target_weight']+=.01
 d['package']['strategies'][SID]['application']=deepcopy(d['snapshot']['applications'][SID])
 new=BF._closed_write(d['folder']/'snapshot.json',d['snapshot'])
 d['package']['source_refs'][h]=new;d['package']['source_hashes'][h]=new['sha256']
 d['archive']['source_hashes'][h]=new['sha256']
 BF._closed_write(Path(d['archive_ref']['path']),d['archive']);display_republish(d)
 with pytest.raises(ValueError,match='PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):dg(c,d)
 assert c.meta.get('paper_first_execution') is None
 assert all(count(e,'paper_batches')==count(e,'orders')==0 for e in c._active_engines().values())


@pytest.mark.parametrize('foreign',[False,True])
def test_display_archive_policy_location_follows_original_owner_without_cross_account(foreign,sim,tmp_path):
 from moomoo_component.applied_source import LEGACY_POLICY
 r,s,f=sim;d=display_fixture(r,s,tmp_path,True)
 r.plan['policy_id']=LEGACY_POLICY
 saved=r.engine._get('best_plan',{});saved['plan']=deepcopy(r.plan)
 d['archive']['plans'][SID]=deepcopy(r.plan)
 path=(tmp_path/'foreign_owner' if foreign else s.runtime_root)/'policies'/LEGACY_POLICY/'2026-10-07'/'plans.json'
 path.parent.mkdir(parents=True);ref=BF._closed_write(path,d['archive'])
 r.metadata['archive']=ref;saved['metadata']=deepcopy(r.metadata);r.engine._set('best_plan',saved)
 if foreign:
  with pytest.raises(ValueError,match='DISPLAY_BINDING_CHANGED'):sg(r,d)
  assert r.engine._get('best_first_execution',None) is None
 else:
  g=sg(r,d);assert g['display_binding']['archive_ref']==ref


def test_display_missing_legacy_snapshot_policy_is_account_mode_only(paper,tmp_path):
 c,s,q=paper;d=display_fixture(c,s,tmp_path)
 assert 'policy_id' not in d['snapshot']
 assert BestBroker._first_execution_display_binding({sid:c.plans[sid] for sid in HGB_STRATEGIES},
  c.plan_metadata,s.status(NOW),s,account_states=c.close_states)['accepted_package_ref']==d['live_refs']['selected/package.json']
 with pytest.raises(ValueError,match='PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):
  BestBroker._closed_history_binding({sid:c.plans[sid] for sid in HGB_STRATEGIES},
   c.plan_metadata,s.status(NOW),d['archive_ref'])


@pytest.mark.parametrize('policy',[None,'HGB_TOP20_RISK_R1','RAW_TOP20_FROZEN_LEGACY'])
def test_display_explicit_snapshot_policy_never_uses_missing_field_fallback(paper,tmp_path,policy):
 c,s,q=paper;d=display_fixture(c,s,tmp_path,snapshot_policy=policy)
 if policy=='RAW_TOP20_FROZEN_LEGACY':assert dg(c,d)['display_binding']
 else:
  with pytest.raises(ValueError,match='PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):dg(c,d)
  assert c.meta.get('paper_first_execution') is None


# State presentation must not compete with the canonical source worker.
def test_state_deadline_original_busy_counterexample_and_new_read_only_display(sim):
 r,s,f=sim;g=sim_grant(r)
 with patch.object(s,'status',side_effect=RuntimeError('CANONICAL_SOURCE_WORKER_BUSY')) as source:
  # Original state called the strict execution function; reproduce that exact call.
  with patch.object(r,'_display_execution_end',side_effect=r._execution_end):
   with pytest.raises(RuntimeError,match='CANONICAL_SOURCE_WORKER_BUSY'):r.state()
  source.reset_mock()
  assert r.state()['execution_deadline_utc']==g['deadline_utc']
  source.assert_not_called()
  with pytest.raises(RuntimeError,match='CANONICAL_SOURCE_WORKER_BUSY'):r._execution_end()
 assert f.submissions==[]

def test_state_deadline_repeated_reads_do_not_call_source_sdk_audit_or_mutate_permission(sim):
 r,s,f=sim;g=sim_grant(r);before=(r.engine._get('best_plan',{}),r.engine._get('best_execution',{}),count(r.engine,'orders'))
 with patch.object(s,'status',side_effect=AssertionError('no source worker')),patch.object(f,'snapshot',side_effect=AssertionError('no SDK')),patch.object(r.engine,'_audit',side_effect=AssertionError('no audit')):
  assert [r.state()['execution_deadline_utc'] for _ in range(3)]==[g['deadline_utc']]*3
 assert before==(r.engine._get('best_plan',{}),r.engine._get('best_execution',{}),count(r.engine,'orders'))
 assert r.engine._get('best_first_execution',{})==g

@pytest.mark.parametrize('offset',[timedelta(seconds=600),timedelta(days=1)])
def test_state_deadline_expired_record_is_original_past_time_not_new_authority(sim,offset):
 r,s,f=sim;g=sim_grant(r);r._now=lambda:NOW+offset
 with patch.object(s,'status',side_effect=AssertionError('no worker for historical display')):
  out=r.state()
 assert out['execution_deadline_utc']==g['deadline_utc']
 assert datetime.fromisoformat(out['execution_deadline_utc'])<=r._now()
 assert out['next_expected_execution_utc'] is None
 assert r.engine._get('best_first_execution',{})==g and f.submissions==[]

def test_state_deadline_next_signal_does_not_inherit_first_permission(sim):
 r,s,f=sim;sim_grant(r);opening=OPEN+timedelta(days=1)
 r.metadata={**r.metadata,'signal_date':'2026-10-08','execution_date':'2026-10-09','next_open_utc':opening.isoformat(),
  'next_close_utc':(opening+timedelta(hours=6,minutes=30)).isoformat(),'signal_close_utc':(CLOSE+timedelta(days=1)).isoformat()}
 with patch.object(s,'status',side_effect=AssertionError('display does not read source')):
  assert r.state()['execution_deadline_utc']==(opening+timedelta(seconds=600)).isoformat()

@pytest.mark.parametrize('field',['permission','plan','metadata','account'])
def test_state_deadline_tampered_local_binding_rejects_without_source(sim,field):
 r,s,f=sim;g=sim_grant(r)
 if field=='permission':
  changed=deepcopy(g);changed['deadline_utc']=(NOW+timedelta(seconds=601)).isoformat();r.engine._set('best_first_execution',changed)
 elif field=='plan':r.plan['rows'][0]['target_weight']=.09
 elif field=='metadata':
  saved=r.engine._get('best_plan',{});saved['metadata']['source_refs']['selected/package.json']['sha256']='0'*64;r.engine._set('best_plan',saved)
 else:r.engine._set('best_account','different_saved_account')
 with patch.object(s,'status',side_effect=AssertionError('no source')):
  with pytest.raises(ValueError):r.state()
 assert f.submissions==[]

def test_state_deadline_restart_unconnected_uses_original_sealed_deadline(sim):
 r,s,f=sim;g=sim_grant(r);saved=r.engine._get('best_plan',{});path=r.engine.path
 r.close();r._fixture_closed=True
 e=Engine(path,broker_factory=f);n=BestBroker(path,s,engine=e,now=lambda:NOW)
 try:
  # Original reconcile restores these saved fields; display needs no SDK connection.
  n.plan=saved['plan'];n.metadata=saved['metadata']
  assert e.mode=='paper' and e.broker is None
  with patch.object(s,'status',side_effect=AssertionError('no source')):
   assert n.state()['execution_deadline_utc']==g['deadline_utc']
  assert e._get('best_first_execution',{})==g
 finally:n.close()

def test_state_deadline_active_display_package_drift_still_blocks_real_execution(sim,tmp_path):
 r,s,f=sim;d=display_fixture(r,s,tmp_path,True);g=sg(r,d);display_republish(d)
 with patch.object(s,'status',side_effect=AssertionError('state must not read changed package')):
  assert r.state()['execution_deadline_utc']==g['deadline_utc']
 with pytest.raises(ValueError,match='DISPLAY_BINDING_CHANGED'):r._execution_end()
 assert f.submissions==[]

def test_state_deadline_busy_tick_still_uses_strict_source_guard(sim):
 r,s,f=sim;sim_grant(r)
 with patch.object(s,'status',side_effect=RuntimeError('CANONICAL_SOURCE_WORKER_BUSY')):
  with pytest.raises(RuntimeError,match='CANONICAL_SOURCE_WORKER_BUSY'):sim_tick(r,f)
 assert f.submissions==[] and count(r.engine,'orders')==0

def test_state_deadline_ordinary_no_permission_matches_original_without_source(sim):
 r,s,f=sim
 with patch.object(s,'status',side_effect=AssertionError('no ordinary display worker')):
  assert r.state()['execution_deadline_utc']==r._execution_end().isoformat()


def z_source_paper(c,s):
 from moomoo_component.applied_source import _iso
 from moomoo_component.strategy import timestamp
 original=s.status
 keys=('next_open_utc','signal_close_utc','next_close_utc')
 def native_status(now=None):
  data=original(now)
  return {**data,**{key:_iso(timestamp(data[key])) for key in keys}}
 s.status=native_status
 for key in keys:c.plan_metadata[key]=s.status(NOW)[key]
 c._persist()

def test_original_daily_source_z_to_cohort_offset_first_paper_batch_preserves_grant(paper):
 c,s,q=paper;z_source_paper(c,s);g=paper_grant(c)
 assert g['books'][SID]['next_open_utc'].endswith('Z')
 assert c.plan_metadata['execution_time_utc'].endswith('+00:00')
 result=paper_tick(c,q)
 assert result['status']=='EXECUTED',{sid:result['books'][sid].get('reason') for sid in HGB_STRATEGIES}
 for sid,e in c._active_engines().items():
  assert count(e,'paper_batches')==1 and count(e,'paper_fills')==3
  batch=json.loads(e.db.execute('SELECT payload FROM paper_batches').fetchone()[0])
  assert batch['first_execution_permission_sha256']==_first_execution_sha(g['books'][sid])
  assert e._get('paper_first_execution',{})==g['books'][sid]
 assert c.meta['paper_first_execution']==g


@pytest.mark.parametrize('key',['next_open_utc','signal_close_utc','next_close_utc'])
@pytest.mark.parametrize('shift',[timedelta(seconds=1),timedelta(microseconds=1),'naive'])
def test_shared_first_clock_equivalence_still_rejects_real_time_or_timezone_changes(paper,key,shift):
 c,s,q=paper;z_source_paper(c,s);g=paper_grant(c);permission=g['books'][SID]
 metadata={**c.plan_metadata,'next_close_utc':s.status(NOW)['next_close_utc']}
 value=datetime.fromisoformat(metadata[key].replace('Z','+00:00'))
 metadata[key]=(value.replace(tzinfo=None) if shift=='naive' else value+shift).isoformat()
 with pytest.raises(ValueError):
  core._first_execution_end(permission,plan=c.plans[SID],metadata=metadata,account_id=c.engines[SID].paper_account_id,
   clock=NOW,execution_delay_minutes=0,execution_window_seconds=600)
 assert all(count(e,'paper_batches')==count(e,'paper_fills')==0 for e in c._active_engines().values())
 assert c.meta['paper_first_execution']==g

def test_shared_first_clock_accepts_same_instant_offset_without_rewriting_record(paper):
 c,s,q=paper;z_source_paper(c,s);g=paper_grant(c);permission=g['books'][SID]
 metadata={**c.plan_metadata,'next_close_utc':s.status(NOW)['next_close_utc']}
 for key in ('next_open_utc','signal_close_utc','next_close_utc'):
  metadata[key]=datetime.fromisoformat(metadata[key].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=9))).isoformat()
 before=json.dumps(permission,sort_keys=True)
 assert core._first_execution_end(permission,plan=c.plans[SID],metadata=metadata,account_id=c.engines[SID].paper_account_id,
  clock=NOW,execution_delay_minutes=0,execution_window_seconds=600).isoformat()==g['deadline_utc']
 assert json.dumps(permission,sort_keys=True)==before and c.meta['paper_first_execution']==g

# A continuation is a separate human-reviewed lease, never a renewal of first bytes.
LATER=NOW+timedelta(seconds=601)

def paper_continue(c,now=LATER,**changes):
 args=dict(execution_date='2026-10-08',deadline_utc=(now+timedelta(seconds=600)).isoformat(),
  authorization_id='offline_paper_continuation',expected_package_sha256='a'*64,
  expected_plan_sha256_by_book={sid:_first_execution_sha(c.plans[sid]) for sid in HGB_STRATEGIES},now=now,
  continuation={'expected_prior_sha256':_first_execution_sha(c.meta['paper_first_execution']),
   'expected_ledger_sha256_by_book':{sid:e._paper_first_baseline() for sid,e in c._active_engines().items()}})
 args.update(changes);return c.authorize_first_execution(**args)

def prepare_sim_remainder(r,s,f,display_path=None):
 # Synthetic original account: DINO four shares actually bought, MSFT unavailable.
 # Five valid original securities exit for 44 shares before the original DINO4 buy.
 exits={'US.EXIT'+letter:qty for letter,qty in zip('ABCDE',[8,9,9,9,9])}
 for i,(code,qty) in enumerate(exits.items()):
  oid='original_pre_signal_fill_'+str(i);f.positions[code]=qty;f.cash-=qty*100.
  r.engine.db.execute('INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
   (oid,(CLOSE-timedelta(hours=1)).isoformat(),SID,'moomoo_simulate',r.engine.account_id,code,'BUY',qty,100.,'FILLED_ALL',oid))
  r.engine.db.execute('INSERT INTO order_fills VALUES (?,?)',(oid,json.dumps({'fill_qty':qty,'fill_price':100.})))
 r.engine.db.commit();r._accept_snapshot(r.engine.broker.snapshot([],include_quotes=False))
 # Reuse the original fixture source plan kernel, including ticker/weight_before.
 s.weights={SID:{'US.DINO':.05,'US.MSFT':.1,'US.SION':0.,**{code:0. for code in exits}}}
 states=s.close_states({SID:r._book()},signal_date='2026-10-07')
 result=s.load(states,now=NOW);r.plan=result['plans'][SID]
 r.metadata={key:value for key,value in result.items() if key!='plans'}
 r.engine._set('best_plan',{'plan':deepcopy(r.plan),'metadata':deepcopy(r.metadata),'close_state':deepcopy(states[SID])})
 d=display_fixture(r,s,display_path,True) if display_path is not None else None
 r._continuation_display_fixture=d
 g=sg(r,d) if d is not None else sim_grant(r)
 f.quote_errors={'US.MSFT':'fixture unavailable'}
 for i in range(12):
  sim_tick(r,f,NOW+timedelta(seconds=i))
  if len(f.submissions)==6 and not r.engine._pending():break
 assert not r.engine._pending()
 assert f.positions['US.DINO']==4
 assert len(f.submissions)==6 and sum(x['qty'] for x in f.submissions)==48
 assert [x['side'] for x in f.submissions].count('SELL')==5
 buy=deepcopy(r.engine._get('best_execution',{}))
 assert buy['phase']=='BUY' and buy['target_quantities']['US.DINO']==4
 # The persisted SELL detour resumes this original BUY, as in today's real shape.
 top=deepcopy(buy);top.update(phase='SELL',manifest=None,target_quantities={'US.SION':0},processed_codes=[],
  deferred_sells=[],sell_codes=['US.SION'],resume_buy_state=buy)
 r.engine._set('best_execution',top);r.stop();r._accept_snapshot(r.engine.broker.snapshot([],include_quotes=False))
 return g,deepcopy(top)

def sim_continue(r,now=LATER,**changes):
 args=dict(execution_date='2026-10-08',deadline_utc=(now+timedelta(seconds=600)).isoformat(),
  authorization_id='offline_sim_continuation',expected_package_sha256='a'*64,
  expected_plan_sha256=_first_execution_sha(r.plan),account_id=r.engine.account_id,now=now,
  continuation={'expected_prior_sha256':_first_execution_sha(r.engine._get('best_first_execution', None)),
   'expected_execution_sha256':_first_execution_sha(r.engine._get('best_execution',{}))})
 args.update(changes);r._now=lambda:args['now'];return r.authorize_first_execution(**args)

def test_continuation_paper_first_batch_uses_new_lease_preserves_first_and_initializes_once(paper):
 c,s,q=paper;old=paper_grant(c);oldbytes={sid:e.db.execute("SELECT value FROM settings WHERE key='paper_first_execution'").fetchone()[0] for sid,e in c._active_engines().items()}
 g=paper_continue(c)
 assert c.stop_event.is_set() and all(count(e,'paper_batches')==0 for e in c._active_engines().values())
 assert c.meta['paper_first_execution']==old
 result=paper_tick(c,q,LATER)
 assert result['status']=='EXECUTED',result.get('last_error')
 for sid,e in c._active_engines().items():
  batch=json.loads(e.db.execute('SELECT payload FROM paper_batches').fetchone()[0])
  assert batch['first_execution_permission_sha256']==_first_execution_sha(old['books'][sid])
  assert batch['first_continuation_permission_sha256']==_first_execution_sha(g['books'][sid])
  assert count(e,'paper_fills')==3 and e.db.execute("SELECT value FROM settings WHERE key='paper_first_execution'").fetchone()[0]==oldbytes[sid]
 counts=[count(e,'paper_fills') for e in c._active_engines().values()];paper_tick(c,q,LATER+timedelta(seconds=1))
 assert counts==[count(e,'paper_fills') for e in c._active_engines().values()]

def test_continuation_sim_sell_resume_buy_keeps_dino4_fills_and_all_fixed_quantities(sim):
 r,s,f=sim;old,state=prepare_sim_remainder(r,s,f);n=len(f.submissions)
 oldraw=r.engine.db.execute("SELECT value FROM settings WHERE key='best_first_execution'").fetchone()[0]
 g=sim_continue(r)
 assert len(f.submissions)==n and r.stop_event.is_set() and r.engine._get('best_execution', None)==state
 f.quote_errors={}
 for i in range(5):sim_tick(r,f,LATER+timedelta(seconds=i))
 assert r.engine._get('best_execution', None)['phase']=='DONE'
 assert len([x for x in f.submissions if x['code']=='US.DINO'])==1 and f.positions['US.DINO']==4
 assert any(x['code']=='US.MSFT' for x in f.submissions[n:])
 assert r.engine.db.execute("SELECT value FROM settings WHERE key='best_first_execution'").fetchone()[0]==oldraw
 assert r.engine._get('best_first_execution:2026-10-07', None)==old
 assert all(o['execution_deadline_utc']==g['deadline_utc'] for o in f.submit_options[n:])

@pytest.mark.parametrize('failure',['active','wrong_prior','wrong_ledger','plan','source','alive','pending','unknown','already_batch','over600','wrong_day'])
def test_continuation_paper_rejects_before_any_permission_or_batch(paper,failure):
 from unittest.mock import Mock
 c,s,q=paper;paper_grant(c);args={}
 if failure=='active':args['now']=NOW+timedelta(seconds=599)
 elif failure=='wrong_prior':args['continuation']={'expected_prior_sha256':'b'*64,'expected_ledger_sha256_by_book':{sid:e._paper_first_baseline() for sid,e in c._active_engines().items()}}
 elif failure=='wrong_ledger':args['continuation']={'expected_prior_sha256':_first_execution_sha(c.meta['paper_first_execution']),'expected_ledger_sha256_by_book':{sid:'b'*64 for sid in HGB_STRATEGIES}}
 elif failure=='plan':c.plans[SID]['rows'][0]['target_weight']=.09
 elif failure=='source':
  old=s.status;s.status=lambda now=None:{**old(now),'source_refs':{**REFS,'extra':{'sha256':'b'*64}}}
 elif failure=='alive':c.worker=Mock();c.worker.is_alive.return_value=True
 elif failure=='pending':c.engines[SID]._pending=lambda:True
 elif failure=='unknown':c.engines[SID].halt_event.set()
 elif failure=='already_batch':paper_tick(c,q);c.stop()
 elif failure=='over600':args['deadline_utc']=(LATER+timedelta(seconds=601)).isoformat()
 else:args['now']=LATER+timedelta(days=1)
 with pytest.raises(ValueError):paper_continue(c,**args)
 assert 'paper_first_continuation' not in c.meta
 if failure=='alive':c.worker=None

@pytest.mark.parametrize('failure',['active','wrong_prior','state','done','source','alive','pending','unknown','stale','account','budget','over600','wrong_day'])
def test_continuation_sim_rejects_before_permission_or_submission(sim,failure):
 from unittest.mock import Mock
 r,s,f=sim;prepare_sim_remainder(r,s,f);n=len(f.submissions);args={}
 if failure=='active':args['now']=NOW+timedelta(seconds=599)
 elif failure=='wrong_prior':args['continuation']={'expected_prior_sha256':'b'*64,'expected_execution_sha256':_first_execution_sha(r.engine._get('best_execution', None))}
 elif failure=='state':args['continuation']={'expected_prior_sha256':_first_execution_sha(r.engine._get('best_first_execution', None)),'expected_execution_sha256':'b'*64}
 elif failure=='done':state=r.engine._get('best_execution', None);state['phase']='DONE';r.engine._set('best_execution',state)
 elif failure=='source':
  old=s.status;s.status=lambda now=None:{**old(now),'source_refs':{**REFS,'extra':{'sha256':'b'*64}}}
 elif failure=='alive':r.worker=Mock();r.worker.is_alive.return_value=True
 elif failure=='pending':r.engine._pending=lambda:True
 elif failure=='unknown':r.engine.halt_event.set()
 elif failure=='stale':r.last_snapshot_at-=61
 elif failure=='account':args['account_id']='different'
 elif failure=='budget':r.budget+=1
 elif failure=='over600':args['deadline_utc']=(LATER+timedelta(seconds=601)).isoformat()
 else:args['now']=LATER+timedelta(days=1)
 with pytest.raises(ValueError):sim_continue(r,**args)
 assert r.engine._get('best_first_continuation',None) is None and len(f.submissions)==n
 if failure=='alive':r.worker=None

@pytest.mark.parametrize('kind',['paper','sim'])
def test_continuation_once_idempotent_not_extendable(kind,paper,sim):
 if kind=='paper':
  c,s,q=paper;paper_grant(c);g=paper_continue(c);assert paper_continue(c)==g
  with pytest.raises(ValueError,match='NO_RENEWAL'):paper_continue(c,authorization_id='another_new_window')
 else:
  r,s,f=sim;prepare_sim_remainder(r,s,f);g=sim_continue(r);assert sim_continue(r)==g
  with pytest.raises(ValueError,match='NO_RENEWAL'):sim_continue(r,authorization_id='another_new_window')

@pytest.mark.parametrize('failure',['fixed_buy','fixed_sell','processed','active_record','immutable_slot'])
def test_continuation_sim_runtime_prefix_tamper_rejects(sim,failure):
 r,s,f=sim;prepare_sim_remainder(r,s,f);sim_continue(r);n=len(f.submissions)
 state=r.engine._get('best_execution', None)
 if failure=='fixed_buy':state['resume_buy_state']['target_quantities']['US.DINO']=5;r.engine._set('best_execution',state)
 elif failure=='fixed_sell':state['target_quantities']['US.SION']=1;r.engine._set('best_execution',state)
 elif failure=='processed':state['resume_buy_state']['processed_codes']=[];r.engine._set('best_execution',state)
 else:
  key='best_first_continuation' if failure=='active_record' else 'best_first_continuation:2026-10-07'
  record=r.engine._get(key, None);record['deadline_utc']=(LATER+timedelta(seconds=601)).isoformat();r.engine._set(key,record)
 with pytest.raises(ValueError):sim_tick(r,f,LATER)
 assert len(f.submissions)==n

def test_continuation_paper_group_commit_failure_orphan_cannot_execute(paper):
 c,s,q=paper;paper_grant(c)
 with patch.object(c,'_persist',side_effect=OSError('group commit failed')):
  with pytest.raises(OSError):paper_continue(c)
 assert 'paper_first_continuation' not in c.meta
 result=paper_tick(c,q,LATER)
 assert result['status']=='BLOCKED' and all(count(e,'paper_batches')==0 for e in c._active_engines().values())

def test_continuation_expired_paper_never_initializes_and_cannot_second_lease(paper):
 c,s,q=paper;paper_grant(c);g=paper_continue(c,deadline_utc=(LATER+timedelta(seconds=1)).isoformat())
 result=paper_tick(c,q,LATER+timedelta(seconds=2))
 assert result['status']=='MISSED_OPEN' and all(count(e,'paper_batches')==0 for e in c._active_engines().values())
 c.stop()
 with pytest.raises(ValueError,match='NO_RENEWAL'):paper_continue(c,now=LATER+timedelta(seconds=2))


@pytest.mark.parametrize('broker',[False,True])
def test_continuation_server_explicit_nested_cas_routes_same_owner_and_never_starts(broker):
 from unittest.mock import Mock
 from moomoo_component import server
 sf=fixture_module('server_configuration');fixture=sf.CatchupRoutingTests();fixture.setUp()
 owner=Mock(spec=['authorize_first_execution','start','best_broker']);owner.authorize_first_execution.return_value={'ok':True}
 child=Mock(spec=['authorize_first_execution','start','engine']);child.engine._get.return_value='3604';child.authorize_first_execution.return_value={'ok':True}
 owner.best_broker=child;fixture.fixture.cohort=owner
 body={'execution_date':'2026-10-08','deadline_utc':(LATER+timedelta(seconds=600)).isoformat(),
  'authorization_id':'offline_continuation_route','expected_package_sha256':'a'*64,
  ('expected_plan_sha256' if broker else 'expected_plan_sha256_by_book'):('b'*64 if broker else {sid:'b'*64 for sid in HGB_STRATEGIES}),
  'continuation':{'expected_prior_sha256':'c'*64,
   ('expected_execution_sha256' if broker else 'expected_ledger_sha256_by_book'):('d'*64 if broker else {sid:'d'*64 for sid in HGB_STRATEGIES})}}
 with patch.object(server,'datetime') as clock:
  clock.now.return_value=LATER;code,response=fixture.request(body,path='/api/applied/broker-first-execution' if broker else '/api/applied/first-execution')
 assert code==200,response
 (child if broker else owner).authorize_first_execution.assert_called_once_with(**body,now=LATER,**({'account_id':'3604'} if broker else {}))
 owner.start.assert_not_called();child.start.assert_not_called()

@pytest.mark.parametrize('field',['allowed_codes','qty','deadline_utc','now','budget'])
def test_continuation_server_rejects_nested_unreviewed_controls(field):
 from unittest.mock import Mock
 sf=fixture_module('server_configuration');fixture=sf.CatchupRoutingTests();fixture.setUp();owner=Mock(spec=['authorize_first_execution','start','best_broker']);fixture.fixture.cohort=owner
 body={'execution_date':'2026-10-08','deadline_utc':(LATER+timedelta(seconds=600)).isoformat(),
  'authorization_id':'offline_continuation_route','expected_package_sha256':'a'*64,
  'expected_plan_sha256_by_book':{sid:'b'*64 for sid in HGB_STRATEGIES},
  'continuation':{'expected_prior_sha256':'c'*64,'expected_ledger_sha256_by_book':{sid:'d'*64 for sid in HGB_STRATEGIES},field:1}}
 code,response=fixture.request(body,path='/api/applied/first-execution');assert code==400
 owner.authorize_first_execution.assert_not_called()

def test_continuation_paper_restart_then_original_remaining_batch_and_next_day_noninheritance(paper):
 c,s,q=paper;old=paper_grant(c);g=paper_continue(c);path=c.path;c.close();new=Cohort(path,s,q)
 try:
  assert new.meta['paper_first_execution']==old and new.meta['paper_first_continuation']==g
  q.errors={'US.MSFT':'fixture unavailable'};assert paper_tick(new,q,LATER)['status']=='PARTIALLY_EXECUTED'
  q.errors={};assert paper_tick(new,q,LATER+timedelta(seconds=1))['status']=='EXECUTED'
  before=[count(e,'paper_fills') for e in new._active_engines().values()]
  s.opening+=timedelta(days=1);assert paper_tick(new,q,LATER+timedelta(days=1))['status']=='MISSED_OPEN'
  assert before==[count(e,'paper_fills') for e in new._active_engines().values()]
 finally:new.close()

def test_continuation_paper_sql_lock_elapsed_cannot_cross_new_deadline(paper):
 from types import SimpleNamespace
 c,s,q=paper;paper_grant(c);paper_continue(c);e=c.engines[SID];q.clock=LATER
 values=iter([100.,701.])
 with patch.object(core,'time',SimpleNamespace(monotonic=lambda:next(values))):
  with pytest.raises(ValueError,match='EXPIRED_BEFORE_COMMIT'):
   e.paper_rebalance(SID,c.plans[SID],q.quotes(['US.OLD','US.AAPL','US.MSFT']),now=LATER,
    next_open_utc=OPEN.isoformat(),signal_date='2026-10-07',execution_date='2026-10-08',signal_close_utc=CLOSE.isoformat(),
    source_refs=c.plan_metadata['source_refs'],allow_partial_quotes=True,execution_window_seconds=600)
 assert count(e,'orders')==0 and count(e,'paper_batches')==0

def test_continuation_sim_synchronous_quote_crosses_new_deadline_no_submit(sim):
 r,s,f=sim;prepare_sim_remainder(r,s,f);g=sim_continue(r);n=len(f.submissions);original=r.engine.broker.snapshot_partial
 def slow(codes):
  result=original(codes);r._now=lambda:datetime.fromisoformat(g['deadline_utc']);return result
 with patch.object(r.engine.broker,'snapshot_partial',side_effect=slow):sim_tick(r,f,LATER)
 assert len(f.submissions)==n and r.status=='PARTIALLY_EXECUTED'

def test_continuation_sim_restart_uses_same_lease_no_new_first_or_duplicate_dino(sim):
 r,s,f=sim;old,state=prepare_sim_remainder(r,s,f);g=sim_continue(r);n=len(f.submissions)
 new=BestBroker(r.engine.path,s,engine=r.engine,now=lambda:LATER)
 new.plan=deepcopy(r.plan);new.metadata=deepcopy(r.engine._get('best_plan',{})['metadata'])
 new.snapshot=deepcopy(r.snapshot);new.prepared_at=time.monotonic();new.last_snapshot_at=time.monotonic()
 new._connect()  # Original restart reconnect binds cancel_check to this new owner.
 f.quote_errors={}
 for i in range(5):sim_tick(new,f,LATER+timedelta(seconds=i))
 assert new.engine._get('best_first_continuation',None)==g and new.engine._get('best_first_execution',None)==old
 assert len([x for x in f.submissions if x['code']=='US.DINO'])==1
 assert f.positions['US.DINO']==4 and len(f.submissions)>n

@pytest.mark.parametrize('change',['mu','target','cash','leaf'])
def test_continuation_display_republish_economic_changes_reject_before_group(paper,tmp_path,change):
 c,s,q=paper;d=display_fixture(c,s,tmp_path);dg(c,d)
 if change=='mu':d['package']['shared_scores']['current']['rows'][0]['pred_hgb']+=.1
 elif change=='target':d['package']['strategies'][SID]['application']['rows'][0]['target_weight']+=.1
 elif change=='cash':d['package']['strategies'][SID]['application']['target_cash_weight']+=.1
 else:Path(d['refs']['current/features.parquet']['path']).write_bytes(b'changed')
 display_republish(d)
 with pytest.raises(ValueError):paper_continue(c,expected_package_sha256=d['live_refs']['selected/package.json']['sha256'])
 assert 'paper_first_continuation' not in c.meta and all(count(e,'orders')==0 for e in c._active_engines().values())

def test_continuation_display_binds_only_new_package_active_and_exact_deadline_readonly(paper,tmp_path):
 c,s,q=paper;d=display_fixture(c,s,tmp_path);old=dg(c,d);display_republish(d)
 g=paper_continue(c,expected_package_sha256=d['live_refs']['selected/package.json']['sha256'])
 assert g['display_binding']['accepted_package_ref']==d['live_refs']['selected/package.json']
 deadline=datetime.fromisoformat(g['deadline_utc']);display_republish(d)
 with pytest.raises(ValueError,match='DISPLAY_BINDING_CHANGED'):c._first_execution_end(s.status(deadline),deadline-timedelta(microseconds=1))
 assert c._first_execution_end(s.status(deadline),deadline)==deadline
 assert c.meta['paper_first_execution']==old and c.meta['paper_first_continuation']==g
 assert all(count(e,'orders')==0 for e in c._active_engines().values())


def test_continuation_sim_display_new_package_cas_local_deadline_and_expired_readonly(sim,tmp_path):
 r,s,f=sim;old,state=prepare_sim_remainder(r,s,f,display_path=tmp_path)
 d=r._continuation_display_fixture;display_republish(d)
 g=sim_continue(r,expected_package_sha256=d['live_refs']['selected/package.json']['sha256'])
 deadline=datetime.fromisoformat(g['deadline_utc'])
 assert r._first_execution_end(LATER)==deadline
 with patch.object(s,'status',side_effect=RuntimeError('CANONICAL_SOURCE_WORKER_BUSY')) as source:
  assert r.state()['execution_deadline_utc']==g['deadline_utc'];source.assert_not_called()
  with pytest.raises(RuntimeError):r._execution_end()
 display_republish(d)
 with pytest.raises(ValueError,match='DISPLAY_BINDING_CHANGED'):r._first_execution_end(deadline-timedelta(microseconds=1))
 assert r._first_execution_end(deadline)==deadline
 assert r.engine._get('best_first_execution',None)==old and len(f.submissions)==6

def test_continuation_authorize_only_never_quotes_sizes_or_starts(sim):
 r,s,f=sim;prepare_sim_remainder(r,s,f);before=deepcopy(r.engine._get('best_execution',{}))
 with patch.object(r.engine.broker,'snapshot',side_effect=AssertionError('no SDK in grant')),patch.object(r.engine.broker,'snapshot_partial',side_effect=AssertionError('no quote batch')),patch.object(r.engine,'set_limits',side_effect=AssertionError('no sizing in grant')),patch.object(r,'start',side_effect=AssertionError('no start in grant')):
  sim_continue(r)
 assert r.engine._get('best_execution',{})==before and len(f.submissions)==6
