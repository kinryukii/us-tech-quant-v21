"""Offline proposed native-reset tests: no real broker, models, data, or service."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from contextlib import nullcontext,closing
import hashlib,http.client,importlib.util,json,os,sys,tempfile,threading,unittest
from unittest.mock import patch

CACHE=Path(os.environ['NATIVE_RESET_PROPOSAL_ROOT']) if os.environ.get('NATIVE_RESET_PROPOSAL_ROOT') else None
def proposed(name):
    p=CACHE/f"native_reset_proposed_{name}_{'r3' if name in ('server','cohort') else 'r2' if name=='best_broker' else 'r1'}.py"
    spec=importlib.util.spec_from_file_location('moomoo_component._offline_native_'+name,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
if CACHE is None:
    from moomoo_component import core as C,best_broker as B,server as S,cohort as D
else:
    C=proposed('core');B=proposed('best_broker');S=proposed('server');D=proposed('cohort')
OLD,NEW='3604','6260';RIDGE='R10_DIRECT_H5_RIDGE_MID';R7='R7_GROSS_LINEAR'
NOW=datetime(2025,10,14,16,35,tzinfo=timezone.utc)
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

class Native:
    def __init__(self,**kw):self.account_id=kw.get('account_id');self.closed=False;self.cancel_check=lambda:False
    def probe(self):
        type(self).probes+=1
        if self.probe_error:raise RuntimeError('SYNTHETIC_PROBE_FAILURE')
        return dict(connected=True,accounts=deepcopy(self.accounts),host='127.0.0.1',port=18441,live_enabled=False)
    def snapshot(self,codes,*,include_quotes=True):
        type(self).reads+=1
        if self.snapshot_error:raise RuntimeError('SYNTHETIC_SNAPSHOT_FAILURE')
        a=deepcopy(self.native.get(self.account_id,self.native[OLD]));a['quotes']={};a['funds_only']=not include_quotes
        a.update(deepcopy(self.override));return a
    def close(self):self.closed=True
    def submit(self,*a,**k):raise AssertionError('NO_NATIVE_SEND_IN_ADOPTION')

class Source:
    def __init__(self,daily):self.daily_root=Path(daily);self.calls=[];self.fail=False;self.plan_mut={}
    def status(self,now=None):
        self.calls.append('status')
        return dict(status='READY',source_date='2025-10-13',signal_date='2025-10-13',execution_date='2025-10-14',
            signal_close_utc='2025-10-13T20:00:00+00:00',next_open_utc='2025-10-14T13:30:00+00:00',
            next_close_utc='2025-10-14T20:00:00+00:00',source_refs={'fixture':{'path':'SYNTHETIC_ONLY','sha256':'a'*64}})
    def close_states(self,books,signal_date):
        self.calls.append(('close_states',deepcopy(books)))
        return {sid:dict(weights={},cash_weight=1.0,units={},signal_date=signal_date,valuation_basis='SIGNAL_CLOSE') for sid in books}
    def load(self,states,now=None):
        self.calls.append(('load',deepcopy(states)))
        if self.fail:raise ValueError('SYNTHETIC_QUALIFICATION_FAILURE')
        p=dict(strategy_id=RIDGE,status='READY',model_fit_calls=0,source_refs=self.status()['source_refs'],
            account_basis='OWN_SIGNAL_CLOSE_FROZEN_CONSENSUS',target_cash_weight=.5,
            rows=[dict(code='US.AAA',target_weight=.5,action='TARGET',explicit_target=True)])
        p.update(self.plan_mut)
        return {**self.status(),'plans':{RIDGE:p}}

class Owner:
    def __init__(self,b):
        self.lock=threading.RLock();self.stop_event=threading.Event();self.stop_event.set()
        self.halt_event=threading.Event();self.worker=None;self.best_broker=b;self.cleanup=True;self.maintenance=False
    def _maintenance_user_stop(self):pass
    def _maintenance_active(self):return self.maintenance
    def _maintenance_cleanup_verified(self):return self.cleanup

class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        Native.accounts=[dict(account_id=OLD,market='US',environment='SIMULATE')]
        Native.native={OLD:dict(cash=1000000.,equity=1000000.,positions={},open_orders=[]),
            NEW:dict(cash=10000.,equity=10000.,positions={},open_orders=[])}
        Native.probes=Native.reads=0;Native.override={};Native.probe_error=Native.snapshot_error=False
        self.source=Source(self.path/'daily');self.engine=C.Engine(self.path/'applied/moomoo-best',broker_factory=Native)
        self.runner=B.BestBroker(self.engine.path,self.source,engine=self.engine,now=lambda:NOW,
            manual_data_updates=True,execution_window_seconds=600,allow_partial_quotes=True)
        self.runner._connect()
        self.runner.bind_strategy(binding_id='original-r7',requested_at=NOW.isoformat(),expected_strategy_id=B.SID,
            target_strategy_id=R7,expected_precondition_sha256=self.runner._strategy_binding_precondition(),now=NOW)
        self.owner=Owner(self.runner);self.runner._maintenance_owner=self.owner
        self.engine._set('best_plan',{'metadata':{'signal_date':'2025-10-13'},'plan':{'opaque':'x'*256000}})
        self.engine._set('best_execution',{'phase':'BUY','processed_codes':['US.OLD'],'signal_date':'2025-10-13'})
        self.engine._set('best_first_execution_permission',{'old':'unchanged','deadline_utc':'2025-10-14T13:40:00Z'})
        self.engine._set('best_published_target_manual_completion',{'old':'EXPIRED'})
        self.engine._set('best_published_target_conversion',{'old':'COMPLETED'})
        self.engine.db.execute('INSERT INTO settings VALUES (?,?)',('raw_unknown',' { "keep" : [1, 2], "label":"原字节" } '))
        self.order('old-buy',OLD,'US.OLD',3)
        Native.native[OLD]=dict(cash=999700.,equity=1000000.,positions={'US.OLD':dict(qty=3,sellable=3,market_value=300.)},open_orders=[])
        self.engine.db.commit();Native.accounts=[dict(account_id=NEW,market='US',environment='SIMULATE')]
        self.old_settings=self.rawsettings();self.old_prefix=self.prefix();self.request=self.request_for()
    def tearDown(self):self.runner.close();self.temp.cleanup()
    def rawsettings(self):return dict(self.engine.db.execute('SELECT key,value FROM settings ORDER BY key'))
    def prefix(self):return {t:[tuple(r) for r in self.engine.db.execute('SELECT rowid,* FROM '+t+' ORDER BY rowid')] for t in ('orders','order_fills','audit')}
    def order(self,id,account,code,qty,status='FILLED_ALL',fill=None):
        self.engine.db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(id,'2025-10-14T13:30:10Z',self.runner.strategy_id,'moomoo_simulate',account,code,'BUY',qty,100.,status,'native-'+id,'NORMAL'))
        if status=='FILLED_ALL':self.engine.db.execute('INSERT INTO order_fills VALUES (?,?)',(id,canon(fill or dict(fill_qty=qty,fill_price=100.,status='FILLED_ALL'))))
    def request_for(self,**kw):
        return {**dict(reset_id='native-reset-ridge',requested_at=NOW.isoformat(),expected_old_account_id=OLD,new_account_id=NEW,
            target_strategy_id=RIDGE,expected_precondition_sha256=self.runner.native_reset_precondition()['expected_precondition_sha256'],budget=10000),**kw}
    def adopt(self,**kw):return self.runner.adopt_native_reset(**{**self.request,**kw},now=NOW)
    def assert_old(self):self.assertEqual(self.rawsettings(),self.old_settings);self.assertEqual(self.prefix(),self.old_prefix)
    def test_adopt_preserves_raw_namespace_old_ledger_and_no_permission(self):
        self.source.load=lambda *a,**k:(_ for _ in ()).throw(AssertionError('NO_MODEL_OR_SOURCE_LOAD'))
        ack=self.adopt();self.assertEqual(len(canon(ack))<1500,True);self.assertEqual(ack['orders_created'],0);self.assertFalse(ack['running'])
        record=self.runner._native_reset_record();self.assertEqual(record['initial_capital']['unused_cash'],0)
        for key,raw in self.old_settings.items():self.assertEqual(self.engine.db.execute('SELECT value FROM settings WHERE key=?',(record['archive_namespace']+key,)).fetchone()[0],raw)
        nowprefix=self.prefix()
        for table,rows in self.old_prefix.items():self.assertEqual(nowprefix[table][:len(rows)],rows)
        self.assertEqual(self.engine._get('best_plan',9),None);self.assertEqual(self.engine._get('best_execution',9),{})
        for k in ('best_first_execution_permission','best_published_target_manual_completion','best_published_target_conversion'):self.assertIsNone(self.engine._get(k,None))
        self.assertEqual(self.runner.strategy_id,RIDGE);self.assertEqual(self.engine.account_id,NEW);self.assertEqual(self.runner.snapshot['positions'],{})
        self.assertEqual(self.engine._get('best_strategy_lineage',None),[RIDGE]);self.assertEqual(self.engine.limits['min_cash_reserve'],0)
        self.assertTrue(self.owner.stop_event.is_set());self.assertTrue(self.runner.stop_event.is_set());self.assertTrue(self.engine.stop_event.is_set())
        self.assertEqual(len(record['archive_manifest']),len(self.old_settings));self.assertFalse(any('SIM_STRATEGY_BOUND'==r[2] for r in self.prefix()['audit'][len(self.old_prefix['audit']):]))
    def test_same_id_idempotent_and_changed_id_request_rejected(self):
        self.adopt();p=self.prefix();reads=Native.reads;probes=Native.probes
        ack=self.runner.adopt_native_reset(**self.request,now=NOW+timedelta(days=1));self.assertTrue(ack['idempotent']);self.assertEqual(self.prefix(),p);self.assertEqual((Native.reads,Native.probes),(reads,probes))
        with self.assertRaisesRegex(ValueError,'ID_REUSED'):self.adopt(target_strategy_id='RAW_A2')
        self.runner.stop_event.clear()
        with self.assertRaisesRegex(ValueError,'PAUSED'):self.adopt()
        self.runner.stop_event.set()
    def test_restart_new_binding_current_display_is_account_scoped(self):
        self.adopt();self.runner.close();self.engine=C.Engine(self.path/'applied/moomoo-best',broker_factory=Native)
        self.runner=B.BestBroker(self.engine.path,self.source,engine=self.engine,now=lambda:NOW,manual_data_updates=True)
        self.runner._maintenance_owner=self.owner;self.owner.best_broker=self.runner;self.runner._connect()
        self.assertEqual(self.runner.strategy_id,RIDGE);self.assertEqual(self.engine.account_id,NEW);self.assertEqual(self.runner.state()['orders'],[])
        self.assertEqual(len(self.engine.state()['orders']),1);self.assertEqual(self.runner.snapshot['cash'],10000)
        with self.assertRaisesRegex(ValueError,'EXPLICIT_BINDING'):B.BestBroker(self.engine.path,self.source,engine=self.engine,strategy_id=R7)
    def test_nonexact_flat_or_funds_proof_rejected_without_writes(self):
        cases=[{'cash':9999},{'cash':10001},{'cash':float('nan')},{'cash':True},{'equity':10001},
            {'positions':{'US.OTHER':{'qty':1}}},{'positions':{'US.OLD':{'qty':0}}},{'open_orders':[{'id':'pending'}]},
            {'funds_only':False},{'quotes':{'US.AAA':{}}}]
        for change in cases:
            with self.subTest(change=repr(change)):
                Native.override=change
                with self.assertRaisesRegex(ValueError,'EXACT_BUDGET_FLAT'):self.adopt()
                self.assert_old()
        Native.override={}
    def test_eligible_identity_rejects_old_present_ambiguous_or_non_us_sim(self):
        cases=[[dict(account_id=OLD,market='US',environment='SIMULATE')],
            [dict(account_id=NEW,market='US',environment='SIMULATE'),dict(account_id=OLD,market='US',environment='SIMULATE')],
            [dict(account_id=NEW,market='HK',environment='SIMULATE')],[dict(account_id=NEW,market='US',environment='REAL')],[],None]
        for accounts in cases:
            with self.subTest(accounts=accounts):
                Native.accounts=accounts
                with self.assertRaisesRegex(ValueError,'UNIQUE_REPLACEMENT'):self.adopt()
                self.assert_old()
    def test_explicit_request_shapes_and_stale_precondition_fail_closed(self):
        cases=[{'budget':True},{'budget':10001},{'budget':float('inf')},{'target_strategy_id':'HGB_FACTOR_5'},
            {'reset_id':'../bad'},{'new_account_id':OLD},{'new_account_id':'new-game'},
            {'expected_precondition_sha256':'f'*64},{'requested_at':(NOW-timedelta(seconds=61)).isoformat()},
            {'requested_at':(NOW+timedelta(seconds=1)).isoformat()}]
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):self.adopt(**change)
                self.assert_old()
    def test_paused_pending_halt_owner_busy_no_native_calls(self):
        guards=[(self.runner.stop_event,'clear'),(self.engine.stop_event,'clear'),(self.engine.halt_event,'set'),(self.owner.stop_event,'clear'),(self.owner.halt_event,'set')]
        for ev,action in guards:
            before=Native.probes;getattr(ev,action)()
            with self.subTest(action=action),self.assertRaises(ValueError):self.adopt()
            self.assertEqual(Native.probes,before)
            (ev.set if action=='clear' else ev.clear)()
        for attr in ('cleanup','maintenance'):
            setattr(self.owner,attr,attr!='cleanup')
            with self.assertRaises(ValueError):self.adopt()
            setattr(self.owner,attr,attr=='cleanup')
        self.engine.db.execute("UPDATE orders SET status='UNKNOWN' WHERE id='old-buy'");self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'PAUSED_TERMINAL'):self.adopt()
    def test_probe_snapshot_failure_and_transaction_rollback(self):
        for attr in ('probe_error','snapshot_error'):
            setattr(Native,attr,True)
            with self.assertRaises(RuntimeError):self.adopt()
            setattr(Native,attr,False);self.assert_old()
        self.engine.db.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON audit WHEN NEW.event='NATIVE_SIM_RESET_ADOPTED' BEGIN SELECT RAISE(ABORT,'SYNTHETIC_ROLLBACK'); END;");self.engine.db.commit()
        with self.assertRaisesRegex(Exception,'SYNTHETIC_ROLLBACK'):self.adopt()
        self.assert_old();self.assertEqual(self.engine.account_id,OLD)
    def test_archive_binding_audit_prefix_tamper_rejected(self):
        self.adopt();record=self.runner._native_reset_record();raw=self.rawsettings();audit=self.prefix()['audit'][-1]
        changes=[('raw',record['archive_namespace']+'raw_unknown','changed'),('raw','native_reset_receipt/'+record['reset_id'],'{}'),
            ('raw','best_capital',canon({'budget':10000,'account_id':NEW})),('raw','best_strategy_binding',canon({**self.engine._get('best_strategy_binding',{}),'account_id':OLD}))]
        for _,key,value in changes:
            self.engine.db.execute('UPDATE settings SET value=? WHERE key=?',(value,key));self.engine.db.commit()
            with self.subTest(key=key),self.assertRaises(ValueError):self.runner._validate_strategy_binding(self.engine._get('best_strategy_binding',None))
            self.engine.db.execute('UPDATE settings SET value=? WHERE key=?',(raw[key],key));self.engine.db.commit()
        self.engine.db.execute("UPDATE orders SET qty=4 WHERE id='old-buy'");self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'PREFIX_CHANGED'):self.runner._native_reset_record()
        self.engine.db.execute("UPDATE orders SET qty=3 WHERE id='old-buy'");self.engine.db.execute("UPDATE audit SET detail='{}' WHERE rowid=?",(audit[0],));self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'BINDING_CHANGED'):self.runner._native_reset_record()
    def test_new_account_history_and_invalid_archive_key_fail_before_probe(self):
        self.order('existing-new',NEW,'US.AAA',1);self.engine.db.commit();self.request=self.request_for();before=Native.probes
        with self.assertRaisesRegex(ValueError,'PRECONDITION_CHANGED'):self.adopt()
        self.assertEqual(Native.probes,before)
        self.engine.db.execute('DELETE FROM order_fills WHERE id=?',('existing-new',));self.engine.db.execute('DELETE FROM orders WHERE id=?',('existing-new',));self.engine.db.execute('INSERT INTO settings VALUES (?,?)',('../bad','{}'));self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'ARCHIVE_KEY'):self.runner.native_reset_precondition()
    def test_optional_account_snapshot_limits_before_filter_and_original_identity(self):
        for i in range(105):self.order('old-'+str(i),OLD,'US.OLD',0,fill={'fill_qty':0,'account_id':NEW})
        self.order('new-one',NEW,'US.AAA',0,fill={'fill_qty':0,'id':'spoof','account_id':OLD});self.engine.db.commit()
        rows=self.engine.order_snapshot(account_id=NEW)['orders'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['account_id'],NEW);self.assertEqual(rows[0]['id'],'new-one')
        legacy=self.engine.order_snapshot()['orders'];self.assertEqual(len(legacy),100)
        self.assertTrue(any(row['account_id']==NEW for row in legacy)) # Default merge intentionally unchanged.
        self.assertEqual(self.engine.order_snapshot(account_id="x' OR 1=1 --")['orders'],[])
    def test_bootstrap_preserves_frozen_plan_and_marks_actual_not_historical(self):
        self.adopt();receipt=self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertTrue(receipt['prepared']);saved=self.engine._get('best_plan',None);origin=saved['account_state_origin']
        self.assertEqual(origin['kind'],'USER_NATIVE_RESET_CASH_BOOTSTRAP');self.assertTrue(origin['not_historical_native_signal_close_snapshot'])
        self.assertEqual(saved['close_state']['valuation_basis'],'SIGNAL_CLOSE');self.assertEqual(saved['plan']['account_basis'],'OWN_SIGNAL_CLOSE_FROZEN_CONSENSUS')
        self.assertEqual(saved['plan'],self.source.load({RIDGE:{}},now=NOW)['plans'][RIDGE])
        self.assertEqual(origin['account_id'],NEW);self.assertEqual(origin['native_asof_utc'],NOW.isoformat());self.assertEqual(origin['calculation_signal_date'],'2025-10-13')
        n=len([c for c in self.source.calls if isinstance(c,tuple) and c[0]=='load']);raw=self.rawsettings()['best_plan']
        self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertEqual(len([c for c in self.source.calls if isinstance(c,tuple) and c[0]=='load']),n);self.assertEqual(raw,self.rawsettings()['best_plan'])
        self.assertEqual(self.runner.state()['account_state_origin'],origin);self.assertEqual(self.engine._get('best_execution',None),{})
    def test_bootstrap_failure_or_plan_not_frozen_cannot_publish_provenance(self):
        self.adopt();self.source.fail=True
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_QUALIFICATION'):self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertIsNone(self.engine._get('best_native_reset_bootstrap',None));self.assertIsNone(self.engine._get('best_plan',None))
        self.source.fail=False;self.source.plan_mut={'model_fit_calls':1}
        with self.assertRaisesRegex(ValueError,'CURRENT_FROZEN_PLAN'):self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertIsNone(self.engine._get('best_native_reset_bootstrap',None));self.assertIsNone(self.engine._get('best_plan',None))
    def test_bootstrap_requires_canonical_integer_zero_fit_evidence(self):
        self.adopt()
        for value in (None, True, False, 0.0, "0", 1, -1):
            with self.subTest(model_fit_calls=value):
                self.source.plan_mut={'model_fit_calls':value,'fit_calls':0}
                with self.assertRaisesRegex(ValueError,'CURRENT_FROZEN_PLAN'):
                    self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
                self.assertIsNone(self.engine._get('best_native_reset_bootstrap',None))
                self.assertIsNone(self.engine._get('best_plan',None))
        self.source.plan_mut={}
        original=self.source.load
        def missing(states,now=None):
            result=original(states,now=now)
            result['plans'][RIDGE].pop('model_fit_calls')
            result['plans'][RIDGE]['fit_calls']=0
            return result
        with patch.object(self.source,'load',new=missing):
            with self.assertRaisesRegex(ValueError,'CURRENT_FROZEN_PLAN'):
                self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertIsNone(self.engine._get('best_native_reset_bootstrap',None))
        self.assertIsNone(self.engine._get('best_plan',None))
    def test_bootstrap_cannot_adopt_cash_coordinate_after_new_native_fill(self):
        self.adopt();self.order('new-fill',NEW,'US.AAA',1);self.engine.db.commit()
        Native.native[NEW]=dict(cash=9900.,equity=10000.,positions={'US.AAA':dict(qty=1,market_value=100)},open_orders=[])
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_FRESH_FLAT'):self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertIsNone(self.engine._get('best_native_reset_bootstrap',None))
    def test_real_typed_source_guard_consumes_exact_archive_without_marker_change(self):
        import sqlite3
        from moomoo_component import applied_source as authority
        prior=dict(plan=dict(policy_id=R7,rows=[]),metadata=dict(signal_date='2025-10-13'),close_state=dict(cash=1))
        cohort=dict(plans={},plan_close_states={},plan_metadata=dict(signal_date='2025-10-13'))
        peer=self.engine.path.parent/'books/cohort.sqlite3';peer.parent.mkdir(parents=True,exist_ok=True)
        marker=dict(phase='COMMITTED',repair_id='synthetic-paired-native',signal_date='2025-10-13',
            cohort_db=str(peer),broker_db=str(self.engine.path/'state.sqlite3'),
            new_hashes=dict(cohort=authority._pending_plan_digest(cohort,'cohort'),broker=authority._pending_plan_digest(prior,'broker')))
        raw=json.dumps(marker,indent=2)+'\n'
        with closing(sqlite3.connect(peer)) as db:
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)');db.execute('CREATE TABLE audit(time TEXT,event TEXT,detail TEXT)')
            db.executemany('INSERT INTO settings VALUES (?,?)',[('pending_plan_repair',raw),('cohort',canon(cohort))]);db.commit()
        self.engine._set('best_plan',prior)
        self.engine.db.execute('INSERT INTO settings VALUES (?,?)',('pending_plan_repair',raw));self.engine.db.commit()
        self.request=self.request_for();self.runner._pending_repair_guard();self.adopt();self.runner._pending_repair_guard()
        self.assertEqual(self.rawsettings()['pending_plan_repair'],raw)
        with closing(sqlite3.connect(peer)) as db:self.assertEqual(db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()[0],raw)
        self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW);self.runner._pending_repair_guard()
        self.engine.db.execute("UPDATE settings SET value='{}' WHERE key=?",('native_reset_archive/'+self.request['reset_id']+'/best_plan',));self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'PENDING_REPAIR'):self.runner._pending_repair_guard()
    def test_default_snapshot_full_state_and_copy_isolation_remain_exact(self):
        from moomoo_component.core import Engine as Original
        self.assertEqual(self.engine.order_snapshot(),Original.order_snapshot(self.engine))
        self.assertEqual(self.engine.state(),Original.state(self.engine))
        result=self.engine.order_snapshot();result['orders'][0]['code']='MUTATED'
        self.assertEqual(self.engine.order_snapshot()['orders'][0]['code'],'US.OLD')
        self.engine.db.execute("UPDATE order_fills SET payload='broken-json' WHERE id='old-buy'");self.engine.db.commit()
        with self.assertRaises(json.JSONDecodeError):self.engine.order_snapshot()
        self.assertEqual(self.engine.order_snapshot(account_id=NEW)['orders'],[])
    def test_native_epoch_does_not_borrow_old_first_catchup_or_manual_permission(self):
        self.adopt()
        self.assertIsNone(self.runner._scoped_legacy_setting('best_first_execution_permission',None))
        self.assertIsNone(self.runner._first_execution_end(NOW))
        with self.assertRaises(ValueError):self.runner._require_legacy_strategy()
        self.assertIsNone(self.engine._get('best_same_day_catchup',None))
    def test_bootstrap_current_wrapper_and_one_time_proof_survive_restart(self):
        self.adopt();self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        raw=self.rawsettings()['best_native_reset_bootstrap'];saved=self.engine._get('best_plan',None)
        self.runner.close();self.engine=C.Engine(self.path/'applied/moomoo-best',broker_factory=Native)
        self.runner=B.BestBroker(self.engine.path,self.source,engine=self.engine,now=lambda:NOW,manual_data_updates=True)
        self.runner._connect();self.runner._maintenance_owner=self.owner;self.owner.best_broker=self.runner
        n=len([c for c in self.source.calls if isinstance(c,tuple) and c[0]=='load'])
        self.runner.prepare_published_inputs(expected_signal_date='2025-10-13',now=NOW)
        self.assertEqual(raw,self.rawsettings()['best_native_reset_bootstrap']);self.assertEqual(saved,self.engine._get('best_plan',None))
        self.assertEqual(n,len([c for c in self.source.calls if isinstance(c,tuple) and c[0]=='load']))
        record=self.engine._get('best_native_reset_bootstrap',None);record['origin']['not_historical_native_signal_close_snapshot']=False
        self.engine._set('best_native_reset_bootstrap',record)
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_AUDIT'):self.runner._validate_strategy_binding(self.engine._get('best_strategy_binding',None))
    def test_missing_or_foreign_canonical_owner_cannot_adopt(self):
        for owner in (None,Owner(object())):
            self.runner._maintenance_owner=owner
            with self.assertRaisesRegex(ValueError,'CANONICAL_COHORT'):self.adopt()
            self.assert_old()
        self.runner._maintenance_owner=self.owner
    def test_sql_admission_bounds_raw_fetch_and_epoch_before_decode(self):
        self.engine.db.execute('INSERT INTO settings VALUES (?,?)',('oversized','x'*(16*1024*1024+1)));self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'SIZE_LIMIT'):self.runner.native_reset_precondition()
        self.engine.db.execute("DELETE FROM settings WHERE key='oversized'")
        for i in range(513):self.engine.db.execute('INSERT INTO settings VALUES (?,?)',('synthetic_'+str(i),'{}'))
        self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'ENTRY_LIMIT'):self.runner.native_reset_precondition()
        self.engine.db.execute("DELETE FROM settings WHERE key LIKE 'synthetic_%'");self.engine.db.commit()
        self.adopt();self.engine.db.execute("UPDATE settings SET value=? WHERE key='best_native_reset_epoch'",('x'*(1024*1024+1),));self.engine.db.commit()
        with patch.object(B.json,'loads',side_effect=AssertionError('oversize cannot reach JSON decode')):
            with self.assertRaisesRegex(ValueError,'RECEIPT_REQUIRED'):self.runner._native_reset_record()
    def test_slow_old_close_cannot_retimestamp_or_commit_expired_native_snapshot(self):
        timer={'seconds':0};candidates=[];observations=[]
        factory=self.engine._factory;old=self.engine.broker;close=old.close
        def candidate_factory(**kwargs):
            result=factory(**kwargs);candidates.append(result)
            snapshot=result.snapshot
            def observed_snapshot(*a,**k):
                result=snapshot(*a,**k);observations.append(NOW+timedelta(seconds=timer['seconds']));return result
            result.snapshot=observed_snapshot;return result
        def slow_close():timer['seconds']=61;close()
        self.engine._factory=candidate_factory;old.close=slow_close
        self.runner._now=lambda:NOW+timedelta(seconds=timer['seconds'])
        with patch.object(B.time,'monotonic',side_effect=lambda:100+timer['seconds']):
            with self.assertRaisesRegex(ValueError,'SNAPSHOT_EXPIRED_BEFORE_COMMIT'):self.adopt()
        self.assert_old();self.assertEqual(observations,[NOW]);self.assertEqual(len(candidates),1)
        self.assertTrue(candidates[0].closed);self.assertEqual(self.engine.account_id,OLD)
        self.assertTrue(self.runner.stop_event.is_set());self.assertTrue(self.owner.stop_event.is_set())
        self.assertIsNone(self.engine._get('best_native_reset_epoch',None))
    def test_fresh_real_cohort_localserver_binds_owner_before_any_maintenance(self):
        class NoQuotes:
            def quotes(self,*a,**k):raise AssertionError('fresh native control must not load quotes')
        fresh=D.Cohort(self.path/'fresh-books',self.source,NoQuotes(),manual_data_updates=True)
        fresh.best_broker=self.runner
        del self.runner._maintenance_owner  # Mirror fresh production construction; no manual owner assignment.
        self.assertIsNone(fresh._maintenance);self.assertTrue(fresh.stop_event.is_set())
        before=(Native.probes,Native.reads,self.rawsettings(),self.prefix())
        server=None;thread=None
        try:
            server=S.LocalServer(0,self.engine,live=object(),cohort=fresh)
            self.assertIs(self.runner._maintenance_owner,fresh);self.assertIsNone(fresh._maintenance)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            c.request('GET','/api/applied/broker-native-reset-precondition');r=c.getresponse();v=json.loads(r.read());status=r.status;c.close()
            self.assertEqual(status,200);self.assertEqual(v['data']['expected_precondition_sha256'],self.request['expected_precondition_sha256'])
            self.assertIsNone(fresh._maintenance);self.assertEqual((Native.probes,Native.reads,self.rawsettings(),self.prefix()),before)
            self.assertTrue(fresh.stop_event.is_set());self.assertTrue(self.runner.stop_event.is_set())
            with self.assertRaisesRegex(ValueError,'CANONICAL_OWNER_CONFLICT'):
                S.LocalServer(0,self.engine,live=object(),cohort=self.owner)
        finally:
            if server is not None:server.shutdown();server.server_close()
            if thread is not None:thread.join(5)
            fresh.best_broker=None;fresh.close()
            self.runner._maintenance_owner=self.owner  # Restore fixture only after the fresh lifecycle was tested.
    def test_fresh_precondition_get_and_strict_post_local_http_only(self):
        server=S.LocalServer(0,self.engine,live=object(),cohort=self.owner);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(method,path,body=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5);payload=None if body is None else json.dumps(body)
            c.request(method,path,body=payload,headers={'X-CSRF-Token':server.token,'Content-Type':'application/json'});r=c.getresponse();v=json.loads(r.read());code=r.status;c.close();return code,v
        try:
            code,v=call('GET','/api/applied/broker-native-reset-precondition');self.assertEqual(code,200);self.assertEqual(v['data']['expected_precondition_sha256'],self.request['expected_precondition_sha256'])
            with patch.object(S,'datetime') as clock:
                clock.now.return_value=NOW
                code,v=call('POST','/api/applied/broker-native-reset-adoption',{**self.request,'arbitrary_weights':{}});self.assertEqual(code,400)
                code,v=call('POST','/api/applied/broker-native-reset-adoption',self.request);self.assertEqual(code,200);self.assertEqual(v['data']['phase'],'ADOPTED_PAUSED')
            self.assertEqual(self.runner.strategy_id,RIDGE);self.assertEqual(self.engine._get('best_plan',None),None)
        finally:server.shutdown();server.server_close();thread.join(5)

if __name__=='__main__':unittest.main(verbosity=2)
