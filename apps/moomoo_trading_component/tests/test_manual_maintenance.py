"""Explicit daily maintenance; disposable original owners and synthetic provider only."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import http.client,json,threading,unittest
from unittest.mock import Mock,patch
from moomoo_component.cohort import Cohort
from moomoo_component.best_broker import BestBroker
from moomoo_component.core import Engine
from moomoo_component.server import LocalServer
from test_manual_daily_cache import ManualPaperTests
from test_cohort import CLOSE,OPEN,NoWorker
from test_best_broker import FakeBroker
from test_http import FakeLive

class Job:
    def __init__(self):self.code=None;self.cancelled=False;self.pending=False
    def poll(self):return self.code
    def quarantine_reason(self):return None
    def result(self):return {'exit_code':self.code,'stages':{'main':{'exit_code':self.code}},'cancelled':self.cancelled}
    def cancel(self):
        self.cancelled=True
        if self.pending:raise RuntimeError('EXECUTION_CHART_CLEANUP_PENDING')
        self.code=-1

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=ManualPaperTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.c,self.source=self.fixture.cohort,self.fixture.source
        self.clock=CLOSE+timedelta(minutes=10)
        FakeBroker.positions={};FakeBroker.cash=1000000.;FakeBroker.submissions=[];FakeBroker.reconcile_result=None
        FakeBroker.before_send_error=None;FakeBroker.prewarm_error=None;FakeBroker.snapshot_calls=[]
        FakeBroker.clock=staticmethod(lambda:self.clock)
        engine=Engine(Path(self.fixture.temp.name)/'broker',broker_factory=FakeBroker)
        self.b=BestBroker(Path(self.fixture.temp.name)/'broker',self.source,engine=engine,now=lambda:self.clock,
            manual_data_updates=True,execution_window_seconds=600,allow_partial_quotes=True)
        self.b._connect();self.c.best_broker=self.b
        self.addCleanup(self.b.close)
        self.addCleanup(lambda:setattr(self.c,'best_broker',None))
        self.main=Mock(side_effect=lambda now=None:self.metadata(now,'READY'))
        self.source.main_execution_charts_status=self.main
        self.job=Job();self.source.start_execution_charts=Mock(return_value=self.job)
    def metadata(self,clock,status):
        context={'target_session':'2026-09-28','driver_ref':{'path':'driver','sha256':'d'*64},
            'publication_ref':{'path':'pub','sha256':'b'*64}}
        result=dict(status=status,end='2026-09-28',context=context,models_loaded=0,ledger_values_decoded=0,
            broker_action_allowed=False,manifest_ref={'path':'qualified','sha256':'e'*64})
        if status=='PREFLIGHT':
            context.update(capture_ref={'path':'capture','sha256':'c'*64},daily_report_ref={'path':'report','sha256':'f'*64})
            result['request']={'as_of':clock.isoformat(),'capture_ref':context['capture_ref'],'context':deepcopy(context)}
        return result
    def begin(self,running=False):
        if running:self.c.stop_event.clear();self.b.stop_event.clear()
        return self.c.begin_manual_maintenance(maintenance_id='daily-1',now=self.clock)
    def prepare(self):return self.c.prepare_published_inputs(expected_signal_date='2026-09-28',maintenance_id='daily-1',now=self.clock)
    def charts(self):return self.c.request_execution_charts(expected_signal_date='2026-09-28',maintenance_id='daily-1',now=self.clock)
    def end(self,abort=False,clock=None):return self.c.end_manual_maintenance(maintenance_id='daily-1',abort=abort,now=clock or self.clock)
    def ready(self,running=False):self.begin(running);self.prepare();self.charts()
    def test_running_stop_prepare_main_and_original_coupled_resume(self):
        before=self.fixture.counts()
        with patch('moomoo_component.cohort.threading.Thread',NoWorker):
            self.assertEqual(self.begin(True)['phase'],'PAUSED');self.assertTrue(self.c.stop_event.is_set());self.assertTrue(self.b.stop_event.is_set())
            self.assertEqual(self.prepare()['status'],'READY');self.assertEqual(self.charts()['main_status'],'READY')
            result=self.end()
        self.assertEqual(result['phase'],'FINISHED');self.assertTrue(result['resumed']);self.assertEqual(result['current_running'],{'cohort':True,'broker':True})
        self.assertTrue(result['cleanup_verified_before_resume']);self.assertEqual(before,self.fixture.counts());self.assertEqual(FakeBroker.submissions,[])
        self.source.start_execution_charts.assert_not_called()
    def test_prepare_current_uses_current_roster_and_retains_all_ready_requirement(self):
        from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
        selected=("RAW_A2","HGB_DIAG_5","R7_GROSS_LINEAR","R6_DURATION_TREE","R10_DIRECT_H5_RIDGE_MID")
        for outcome in ("accepted", "old_books", "blocked_duration"):
            with self.subTest(outcome=outcome):
                self.c._maintenance=None;self.begin();before=self.fixture.counts()
                receipt_ids=ACTIVE_PAPER_STRATEGY_IDS if outcome=="old_books" else selected
                receipt=dict(action="PREPARE_CURRENT_PUBLISHED_INPUTS",status="PARTIAL" if outcome=="blocked_duration" else "READY",
                    signal_date="2026-09-28",execution_date="2026-09-29",orders_created=0,running=False,
                    books={sid:dict(status="BLOCKED" if outcome=="blocked_duration" and sid=="R6_DURATION_TREE" else "READY",
                        signal_date="2026-09-28",execution_date="2026-09-29") for sid in receipt_ids},broker=dict(prepared=True))
                with patch.object(self.c,'_active_ids',return_value=selected), \
                     patch.object(self.c,'_prepare_published_inputs',return_value=receipt) as original_prepare, \
                     patch.object(self.source,'load',side_effect=AssertionError('wrapper may not rebuild input')):
                    self.assertEqual(self.prepare(),receipt)
                original_prepare.assert_called_once_with(expected_signal_date="2026-09-28",now=self.clock)
                self.assertEqual(self.c._maintenance['prepared'],outcome=="accepted")
                self.assertEqual(self.c._maintenance['phase'],'PAUSED' if outcome=="accepted" else 'FAILED')
                self.assertEqual(before,self.fixture.counts());self.assertEqual(FakeBroker.submissions,[])
                self.assertTrue(self.c.stop_event.is_set());self.assertTrue(self.b.stop_event.is_set())

    def future_clock_fixture(self, delay=30, schema=2):
        from datetime import datetime
        from test_five_strategy_execution import original_auto_policy
        self.clock=datetime.fromisoformat("2026-10-17T12:00:00+00:00")
        data=deepcopy(self.source.status(now=self.clock))
        data.update(signal_date="2026-10-16",source_date="2026-10-16",execution_date="2026-10-19",
            signal_close_utc="2026-10-16T20:00:00+00:00",next_open_utc="2026-10-19T13:30:00+00:00",
            next_close_utc="2026-10-19T20:00:00+00:00",status="READY",data_gaps=[])
        record=dict(after_signal_date="2026-10-15",previous_delay_minutes=delay,previous_window_seconds=600,
            execution_delay_minutes=25,execution_window_seconds=1500)
        self.c.execution_delay_minutes=self.b.execution_delay_minutes=delay
        self.c.execution_window_seconds=self.b.execution_window_seconds=600
        self.c.meta.update(execution_delay_minutes=delay,execution_window_seconds=600,next_ordinary_execution_clock=deepcopy(record))
        self.c._persist(event=("ORDINARY_EXECUTION_CLOCK_DEFERRED",record,self.clock))
        self.b.engine._set("best_next_ordinary_execution_clock",record)
        self.b.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(self.clock.isoformat(),"ORDINARY_EXECUTION_CLOCK_DEFERRED",json.dumps(record)))
        self.b.engine.db.commit()
        policy=original_auto_policy()
        policy.update(authorized_at_utc="2026-10-16T21:00:00+00:00",effective_execution_date="2026-10-17")
        if schema==2:policy.update(schema_version=2,execution_delay_minutes=25,priority_window_seconds=1500)
        self.c.meta["automatic_completion_policy"]=deepcopy(policy)
        for sid in policy["active_strategy_ids"]:
            engine=self.c.engines[sid]
            engine._set("automatic_completion_policy",policy)
            engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(policy["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(policy)))
            engine.db.commit()
        self.c._bind_automatic_completion_policy();self.c._persist()
        return data,record,policy

    def test_maintenance_projects_only_audited_future_clock_without_committing_it(self):
        from moomoo_component.strategy import timestamp
        data,record,policy=self.future_clock_fixture()
        def stored():
            return (tuple(self.c.db.execute("SELECT key,value FROM settings ORDER BY key")),
                tuple(self.c.db.execute("SELECT time,event,detail FROM events ORDER BY rowid")),
                tuple(self.b.engine.db.execute("SELECT key,value FROM settings ORDER BY key")),
                tuple(self.b.engine.db.execute("SELECT time,event,detail FROM audit ORDER BY rowid")))
        before=stored();plans=deepcopy((self.c.plans,self.c.plan_metadata,self.b.plan,self.b.metadata))
        with self.assertRaisesRegex(ValueError,"AUTOMATIC_COMPLETION_BOOK_POLICY_CHANGED"):
            self.c._book_execution_window("HGB_DIAG_5",data,self.clock)
        bounds=self.c._maintenance_window_bounds(data,self.clock)
        opening=timestamp(data["next_open_utc"])
        self.assertIn((opening+timedelta(minutes=25),opening+timedelta(minutes=50)),bounds)
        self.assertIn((opening+timedelta(minutes=30),opening+timedelta(minutes=40)),bounds)
        self.assertEqual(stored(),before)
        self.assertEqual((self.c.execution_delay_minutes,self.c.execution_window_seconds,self.b.execution_delay_minutes,self.b.execution_window_seconds),(30,600,30,600))
        self.assertEqual(self.c.meta["next_ordinary_execution_clock"],record)
        self.assertEqual(self.b.engine._get("best_next_ordinary_execution_clock",None),record)
        self.assertEqual((self.c.plans,self.c.plan_metadata,self.b.plan,self.b.metadata),plans)
        self.assertEqual(policy["active_strategy_ids"],["HGB_DIAG_5","HGB_FACTOR_5"])
        with patch.object(self.source,"status",return_value=deepcopy(data)), \
             patch.object(self.source,"load",side_effect=AssertionError("begin does not infer")), \
             patch.object(self.c,"_activate_next_ordinary_clock",side_effect=AssertionError("only prepare commits")):
            result=self.begin(False)
            self.assertEqual(result["phase"],"PAUSED")
        self.assertEqual(self.c.meta["next_ordinary_execution_clock"],record)
        self.assertEqual((self.c.execution_delay_minutes,self.c.execution_window_seconds),(30,600))
        self.assertEqual(FakeBroker.submissions,[])

    def test_maintenance_projects_waiting_source_without_qualifying_or_preparing_it(self):
        from moomoo_component.strategy import timestamp
        data,record,_=self.future_clock_fixture()
        data.update(status="WAITING_SOURCE",source_date="2026-10-15",data_gaps=["CURRENT_SOURCE_NOT_PUBLISHED"])
        plans=deepcopy((self.c.plans,self.c.plan_metadata,self.c.meta.get("book_plan_metadata"),self.b.plan,self.b.metadata))
        counts=self.fixture.counts()
        before=(tuple(self.c.db.execute("SELECT key,value FROM settings ORDER BY key")),
            tuple(self.c.db.execute("SELECT time,event,detail FROM events ORDER BY rowid")))
        self.assertIsNone(self.c._next_ordinary_clock(data,self.clock,explicit_update=True))
        opening=timestamp(data["next_open_utc"])
        bounds=self.c._maintenance_window_bounds(data,self.clock)
        self.assertIn((opening+timedelta(minutes=25),opening+timedelta(minutes=50)),bounds)
        self.assertIn((opening+timedelta(minutes=30),opening+timedelta(minutes=40)),bounds)
        self.assertEqual(before,(tuple(self.c.db.execute("SELECT key,value FROM settings ORDER BY key")),
            tuple(self.c.db.execute("SELECT time,event,detail FROM events ORDER BY rowid"))))
        with patch.object(self.source,"status",return_value=deepcopy(data)), \
             patch.object(self.source,"load",side_effect=AssertionError("waiting source cannot infer")), \
             patch.object(self.source,"close_states",side_effect=AssertionError("waiting source cannot prepare")), \
             patch.object(self.c,"_activate_next_ordinary_clock",side_effect=AssertionError("only qualified prepare commits")):
            self.assertEqual(self.begin(False)["phase"],"PAUSED")
            with self.assertRaisesRegex(ValueError,"MANUAL_CACHE_CURRENT_PUBLISHED_SOURCE_REQUIRED"):
                self.c.prepare_published_inputs(expected_signal_date=data["signal_date"],maintenance_id="daily-1",now=self.clock)
        self.assertIsNone(self.c._next_ordinary_clock(data,self.clock,explicit_update=True))
        self.assertEqual((self.c.execution_delay_minutes,self.c.execution_window_seconds,self.b.execution_delay_minutes,self.b.execution_window_seconds),(30,600,30,600))
        self.assertEqual(self.c.meta["next_ordinary_execution_clock"],record)
        self.assertEqual(self.b.engine._get("best_next_ordinary_execution_clock",None),record)
        self.assertEqual((self.c.plans,self.c.plan_metadata,self.c.meta.get("book_plan_metadata"),self.b.plan,self.b.metadata),plans)
        self.assertEqual(self.fixture.counts(),counts);self.assertEqual(FakeBroker.submissions,[])

    def test_maintenance_future_window_boundaries_keep_old_zero_delay_window(self):
        from moomoo_component.strategy import timestamp
        data,_,_=self.future_clock_fixture(delay=0)
        opening=timestamp(data["next_open_utc"])
        for delta,blocked in ((timedelta(minutes=5),True),(timedelta(minutes=25)-timedelta(microseconds=1),False),
            (timedelta(minutes=25),True),(timedelta(minutes=50)-timedelta(microseconds=1),True),(timedelta(minutes=50),False)):
            with self.subTest(delta=delta):
                self.clock=opening+delta
                if blocked:
                    with self.assertRaisesRegex(ValueError,"FINANCIAL_WINDOW_ACTIVE"):
                        self.c._maintenance_financial_idle(data,self.clock)
                else:self.c._maintenance_financial_idle(data,self.clock)
        self.assertEqual((self.c.execution_delay_minutes,self.c.execution_window_seconds),(0,600))
        self.assertEqual(FakeBroker.submissions,[])

    def test_maintenance_clock_projection_rejects_drift_and_keeps_older_signal_clock(self):
        data,record,_=self.future_clock_fixture()
        for fault in ("record","audit","pending"):
            with self.subTest(fault=fault):
                if fault=="record":
                    self.c.meta["next_ordinary_execution_clock"]={**record,"previous_delay_minutes":29}
                    with self.assertRaisesRegex(ValueError,"DEFERRED_ORDINARY_CLOCK_CHANGED"):
                        self.c._maintenance_window_bounds(data,self.clock)
                    self.c.meta["next_ordinary_execution_clock"]=deepcopy(record)
                elif fault=="audit":
                    with patch.object(self.c,"_active_engines",return_value={}):
                        self.c.db.execute("DELETE FROM events WHERE event='ORDINARY_EXECUTION_CLOCK_DEFERRED'");self.c.db.commit()
                        with self.assertRaisesRegex(ValueError,"DEFERRED_ORDINARY_CLOCK_AUDIT_CHANGED"):
                            self.c._maintenance_window_bounds(data,self.clock)
                        self.c._persist(event=("ORDINARY_EXECUTION_CLOCK_DEFERRED",record,self.clock))
                else:
                    with patch.object(self.c.engines['RAW_A2'],'_pending',return_value=['UNKNOWN']):
                        with self.assertRaisesRegex(ValueError,"DEFERRED_ORDINARY_CLOCK_REQUIRES_RECONCILED_ACCOUNT"):
                            self.c._maintenance_window_bounds(data,self.clock)
        old={**data,"signal_date":"2026-10-15","source_date":"2026-10-15","execution_date":"2026-10-16",
            "signal_close_utc":"2026-10-15T20:00:00+00:00","next_open_utc":"2026-10-16T13:30:00+00:00","next_close_utc":"2026-10-16T20:00:00+00:00"}
        bounds=self.c._maintenance_window_bounds(old,self.clock)
        self.assertTrue(all(start.isoformat().startswith('2026-10-16T14:00:00') for start,_ in bounds))
        self.assertEqual(self.c.meta["next_ordinary_execution_clock"],record)

    def test_maintenance_clock_projection_keeps_schema1_and_all_bound_manual_windows(self):
        from moomoo_component.strategy import timestamp
        data,_,_=self.future_clock_fixture(schema=1);opening=timestamp(data['next_open_utc'])
        first=opening+timedelta(hours=2);catchup=opening+timedelta(hours=3)
        old_open=opening-timedelta(days=3);old_end=old_open+timedelta(minutes=45)
        self.b.plan={"rows":[]};self.b.metadata={"next_open_utc":old_open.isoformat()}
        with patch.object(self.c,'_first_execution_end',return_value=first), \
             patch.object(self.c,'_catchup_end',return_value=catchup),patch.object(self.b,'_execution_end',return_value=old_end):
            bounds=self.c._maintenance_window_bounds(data,self.clock)
        self.assertIn((opening+timedelta(minutes=30),timestamp(data['next_close_utc'])-timedelta(seconds=600)),bounds)
        self.assertIn((opening+timedelta(minutes=30),first),bounds)
        self.assertIn((opening+timedelta(minutes=30),catchup),bounds)
        self.assertIn((old_open+timedelta(minutes=30),old_end),bounds)
        self.assertEqual((self.c.execution_delay_minutes,self.c.execution_window_seconds),(30,600))

    def test_maintenance_watch_bindings_use_current_roster_and_cancel_invalid_identity(self):
        selected=("RAW_A2","HGB_DIAG_5","R7_GROSS_LINEAR","R6_DURATION_TREE","R10_DIRECT_H5_RIDGE_MID")
        stub=Mock();stub.halt_event=threading.Event();stub._pending.return_value=[]
        with patch.object(self.c,'_active_ids',return_value=selected),patch.dict(self.c.engines,{"R6_DURATION_TREE":stub}):
            bindings=self.c._maintenance_watch_bindings()
            self.assertEqual(bindings['active_ids'],list(selected))
            record=dict(watch_windows=[],watch_bindings=bindings)
            self.assertIsNone(self.c._maintenance_watchdog_reason(record))
            with patch.object(self.c,'_active_ids',return_value=selected[:-1]+('R10_DIRECT_MEAN4_ELASTICNET_MID',)):
                self.assertEqual(self.c._maintenance_watchdog_reason(record),'MANUAL_MAINTENANCE_QUEUED_BINDING_CHANGED')
            stub._pending.return_value=['UNKNOWN']
            self.assertEqual(self.c._maintenance_watchdog_reason(record),'MANUAL_MAINTENANCE_PENDING_UNKNOWN_OR_HALT')
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
        self.job.pending=True
        with patch.object(self.c,'_active_ids',side_effect=ValueError('SHOWCASE_ROSTER_AUDIT_CHANGED')):
            self.assertEqual(self.c._maintenance_watchdog_reason(self.c._maintenance),'MANUAL_MAINTENANCE_QUEUED_BINDING_CHANGED')
            status=self.c.maintenance_status()
        self.assertEqual(status['reason'],'EXECUTION_CHART_CLEANUP_PENDING')
        self.assertTrue(self.job.cancelled);self.assertTrue(status['job_active']);self.assertFalse(status['cleanup_verified'])
        self.assertFalse(status['restore_requested']);self.assertIs(self.c._execution_charts_job,self.job)
        self.job.pending=False;self.c.maintenance_status();self.assertFalse(self.end(abort=True)['resumed'])

    def test_restoring_worker_initial_tick_does_not_query_source_or_write_maintenance_error(self):
        self.begin(True);before=self.b.engine._get('best_last_error',None)
        self.b.stop_event.clear()
        try:
            with patch.object(self.source,'status',side_effect=AssertionError('restoring tick no source')):
                self.b.tick(now=self.clock)
            self.assertEqual(self.b.engine._get('best_last_error',None),before);self.assertEqual(FakeBroker.submissions,[])
        finally:self.b.stop_event.set()
    def test_finished_status_current_running_reads_original_events_after_user_stop(self):
        self.ready(True)
        with patch('moomoo_component.cohort.threading.Thread',NoWorker):result=self.end()
        self.assertEqual(result['current_running'],{'cohort':True,'broker':True})
        self.c.stop(scalar=True)
        status=self.c.maintenance_status();self.assertEqual(status['phase'],'FINISHED')
        self.assertEqual(status['current_running'],{'cohort':False,'broker':False})
        self.assertTrue(status['resumed'])  # Historical action is separate from current owner controls.
    def test_user_stop_between_broker_start_guard_and_clear_cannot_revive_financial_workers(self):
        self.ready(True);guard=self.c._maintenance_start_guard;calls=[]
        def stop_after_guard():
            guard();calls.append(1)
            if len(calls)==2:self.b.stop()
        with patch.object(self.c,'_maintenance_start_guard',side_effect=stop_after_guard),patch('moomoo_component.cohort.threading.Thread',NoWorker):
            result=self.end()
        self.assertEqual(len(calls),2);self.assertEqual(result['phase'],'FINISHED');self.assertFalse(result['resumed'])
        self.assertEqual(result['current_running'],{'cohort':False,'broker':False})
        self.assertTrue(self.b.engine.cancel_step.is_set());self.assertEqual(FakeBroker.submissions,[])
    def test_concurrent_same_id_end_cannot_clear_an_active_owner_operation(self):
        self.ready();entered=threading.Event();release=threading.Event();errors=[];results=[];status=self.source.status
        def held_status(*args,**kwargs):entered.set();release.wait(8);return status(*args,**kwargs)
        def finish():
            try:results.append(self.end())
            except Exception as exc:errors.append(exc)
        with patch.object(self.source,'status',held_status):
            thread=threading.Thread(target=finish);thread.start()
            try:
                self.assertTrue(entered.wait(3));self.assertTrue(self.c.maintenance_status()['operation_active'])
                with self.assertRaisesRegex(ValueError,'CLEANUP_PENDING'):self.end()
                self.assertTrue(self.c.maintenance_status()['operation_active'])
            finally:release.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);self.assertEqual(len(results),1)
        self.assertEqual(results[0]['phase'],'FINISHED');self.assertFalse(self.c.maintenance_status()['operation_active'])
    def test_paused_all_success_never_starts_financial_worker(self):
        self.ready()
        with patch.object(self.c,'start',side_effect=AssertionError('paused intent')):
            result=self.end()
        self.assertFalse(result['resumed']);self.assertEqual(result['current_running'],{'cohort':False,'broker':False})
    def test_half_running_rejected_without_unifying_modes(self):
        for pair in ((True,False),(False,True)):
            with self.subTest(pair=pair):
                (self.c.stop_event.clear if pair[0] else self.c.stop_event.set)();(self.b.stop_event.clear if pair[1] else self.b.stop_event.set)()
                with self.assertRaisesRegex(ValueError,'HALF_RUNNING'):self.begin()
                self.assertEqual((not self.c.stop_event.is_set(),not self.b.stop_event.is_set()),pair)
        self.c.stop_event.set();self.b.stop_event.set()
    def test_window_pending_halt_and_unreconciled_begin_fail_closed(self):
        for guard in ('ordinary','standing','manual','pending','halt','account'):
            with self.subTest(guard=guard):
                self.c._maintenance=None;self.clock=CLOSE+timedelta(minutes=10)
                patches=[]
                if guard=='ordinary':self.clock=OPEN+timedelta(seconds=5)
                if guard=='standing':
                    self.clock=OPEN+timedelta(minutes=15)
                    patches.append(patch.object(self.c.engines['HGB_DIAG_5'],'_automatic_completion_policy',return_value={'priority_window_seconds':600,'close_buffer_seconds':600}))
                if guard=='manual':
                    self.b.plan={'rows':[]};self.b.metadata={'next_open_utc':(self.clock-timedelta(minutes=1)).isoformat()}
                    patches.append(patch.object(self.b,'_execution_end',return_value=self.clock+timedelta(minutes=9)))
                if guard=='pending':patches.append(patch.object(self.b.engine,'_pending',return_value=['UNKNOWN']))
                if guard=='halt':self.c.halt_event.set()
                if guard=='account':patches.append(patch.object(self.b.engine,'broker',None))
                for item in patches:item.start()
                try:
                    with self.assertRaises(ValueError):self.begin(True)
                    self.assertTrue(self.c.stop_event.is_set());self.assertTrue(self.b.stop_event.is_set());self.assertFalse(self.c._maintenance['restore_requested'])
                finally:
                    for item in reversed(patches):item.stop()
                    self.c.halt_event.clear();self.b.plan=None;self.b.metadata={}
        self.assertEqual(self.source.loads,[]);self.assertEqual(FakeBroker.submissions,[])
    def test_same_id_is_control_idempotent_and_other_clients_cannot_start_prepare_charts(self):
        first=self.begin();calls=Mock(side_effect=AssertionError('no source reentry'))
        with patch.object(self.source,'status',calls):self.assertEqual(self.begin()['phase'],first['phase'])
        for action in (self.c.start,self.b.start,lambda:self.c.begin_manual_maintenance(maintenance_id='other',now=self.clock),
            lambda:self.c.prepare_published_inputs(expected_signal_date='2026-09-28',now=self.clock),
            lambda:self.c.request_execution_charts(expected_signal_date='2026-09-28',now=self.clock),self.b._require_running):
            with self.subTest(action=action),self.assertRaises(ValueError):action()
    def test_main_preopen_job_supervised_and_cleanup_required_before_finish(self):
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT')
        self.charts();self.assertEqual(self.c.maintenance_status()['phase'],'CHARTS_RUNNING')
        self.source.start_execution_charts.assert_called_once();self.assertIs(self.source.start_execution_charts.call_args.kwargs['legacy'],False)
        with self.assertRaisesRegex(ValueError,'CLEANUP_PENDING'):self.end()
        self.job.code=0;self.assertEqual(self.c.maintenance_status()['phase'],'CHARTS_FINISHED')
        self.main.side_effect=lambda now=None:self.metadata(now,'READY')
        with patch('moomoo_component.cohort.threading.Thread',NoWorker):self.assertTrue(self.end()['resumed'])
    def test_main_blocked_without_end_preserves_source_reason_and_never_starts_job(self):
        self.begin(True);self.prepare()
        self.main.side_effect=None
        self.main.return_value=dict(status='BLOCKED',reason='CONSENSUS_RESOURCE_FLOOR',resource_blocked=True,
            models_loaded=0,ledger_values_decoded=0,broker_action_allowed=False,args=['PRIVATE_ARGS'],log='PRIVATE_LOG')
        with self.assertRaisesRegex(ValueError,'CONSENSUS_RESOURCE_FLOOR'):self.charts()
        state=self.c.maintenance_status()
        self.assertEqual(state['phase'],'FAILED');self.assertEqual(state['main_status'],'BLOCKED')
        self.assertEqual(state['reason'],'CONSENSUS_RESOURCE_FLOOR');self.assertTrue(state['resource_blocked'])
        self.assertEqual(state['main_receipt'],{'status':'BLOCKED','reason':'CONSENSUS_RESOURCE_FLOOR','resource_blocked':True})
        self.assertTrue(state['cleanup_verified']);self.assertTrue(state['workers_drained'])
        self.assertFalse(state['job_active']);self.assertFalse(state['restore_requested'])
        self.assertNotIn('job_result',state);self.assertNotIn('PRIVATE_',json.dumps(state))
        self.source.start_execution_charts.assert_not_called();self.assertEqual(FakeBroker.submissions,[])
        self.assertEqual(self.end(abort=True)['current_running'],{'cohort':False,'broker':False})
    def test_main_blocked_reason_is_bounded_and_resource_flag_requires_bool(self):
        self.begin();self.prepare();reason='限'*700
        self.main.side_effect=None
        self.main.return_value=dict(status='BLOCKED',reason=reason,resource_blocked=1,
            models_loaded=0,ledger_values_decoded=0,broker_action_allowed=False)
        with self.assertRaises(ValueError) as error:self.charts()
        state=self.c.maintenance_status()
        self.assertEqual(str(error.exception),reason[:500]);self.assertEqual(state['reason'],reason[:500])
        self.assertEqual(state['main_receipt'],{'status':'BLOCKED','reason':reason[:500]})
        self.assertNotIn('resource_blocked',state);self.assertEqual(state['main_status'],'BLOCKED')
        self.source.start_execution_charts.assert_not_called();self.assertEqual(FakeBroker.submissions,[])

    def failed_main_receipt(self,outcome,code=2):
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT')
        self.charts();self.job.code=code
        with patch.object(self.job,'result',return_value=outcome):return self.c.maintenance_status()
    def test_failed_main_retains_controlled_reason_resource_and_stage_summary(self):
        marker='PRIVATE_ARGS_OR_LOG_MUST_NOT_LEAK'
        outcome=dict(exit_code=2,cancelled=False,args=[marker],log=marker,
            stages={'legacy':{'exit_code':0,'args':[marker]},'main':{'exit_code':2,
                'reason':'AVAILABLE_MEMORY_BELOW_MINIMUM','resource_blocked':True,'args':[marker],'log':marker},
                marker:{'reason':marker}})
        state=self.failed_main_receipt(outcome)
        self.assertEqual(state['phase'],'FAILED');self.assertTrue(state['resource_blocked'])
        self.assertEqual(state['reason'],'MAIN_CHART_WORKER_NOT_VERIFIED_READY:2:AVAILABLE_MEMORY_BELOW_MINIMUM')
        self.assertEqual(state['job_result'],{'exit_code':2,'cancelled':False,
            'reason':'AVAILABLE_MEMORY_BELOW_MINIMUM','resource_blocked':True,
            'stages':{'legacy':{'exit_code':0},'main':{'exit_code':2,
                'reason':'AVAILABLE_MEMORY_BELOW_MINIMUM','resource_blocked':True}}})
        self.assertNotIn(marker,json.dumps(state));self.assertTrue(state['cleanup_verified'])
        self.assertFalse(state['job_active']);self.assertFalse(state['restore_requested'])
        self.assertEqual(self.c.maintenance_status()['job_result'],state['job_result'])
        self.assertEqual(self.end(abort=True)['job_result'],state['job_result'])
    def test_failed_main_bounds_reason_and_omits_wrong_typed_fields(self):
        reason='界'*800
        state=self.failed_main_receipt({'exit_code':'spoof','cancelled':1,'resource_blocked':'yes',
            'stages':{'legacy':{'exit_code':True},'main':{'exit_code':2,'reason':reason,
                'resource_blocked':'false','cancelled':0,'log':'PRIVATE_LOG'}}})
        self.assertEqual(state['job_result']['exit_code'],2)
        self.assertEqual(state['job_result']['reason'],reason[:500])
        self.assertEqual(state['job_result']['stages']['main'],{'exit_code':2,'reason':reason[:500]})
        self.assertEqual(state['job_result']['stages']['legacy'],{})
        self.assertEqual(len(state['reason']),500)
        self.assertTrue(state['reason'].startswith('MAIN_CHART_WORKER_NOT_VERIFIED_READY:2:'))
        for key in ('cancelled','resource_blocked'):self.assertNotIn(key,state['job_result'])
        self.assertNotIn('resource_blocked',state);self.assertNotIn('PRIVATE_LOG',json.dumps(state))
    def test_failed_main_unknown_diagnostics_are_not_fabricated(self):
        state=self.failed_main_receipt({'cancelled':False,'stages':{'main':{'reason':17,'resource_blocked':None}}})
        self.assertEqual(state['reason'],'MAIN_CHART_WORKER_NOT_VERIFIED_READY:2')
        self.assertEqual(state['job_result'],{'exit_code':2,'cancelled':False,'stages':{'main':{}}})
        self.assertNotIn('resource_blocked',state)
    def test_wrong_typed_poll_keeps_job_until_cleanup_is_known(self):
        state=self.failed_main_receipt({'reason':'untrusted'},code='2')
        self.assertEqual(state['phase'],'FAILED');self.assertTrue(state['job_active'])
        self.assertEqual(state['reason'],'MAIN_CHART_WORKER_EXIT_CODE_INVALID')
        self.assertFalse(state['restore_requested']);self.assertNotIn('job_result',state)
        self.job.code=2

    def test_stop_during_main_cancels_and_overrides_original_running(self):
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
        self.c.stop(scalar=True);self.assertTrue(self.job.cancelled);self.assertFalse(self.c._maintenance['restore_requested'])
        with patch.object(self.c,'start',side_effect=AssertionError('user stop overrides')):result=self.end()
        self.assertFalse(result['resumed']);self.assertEqual(result['current_running'],{'cohort':False,'broker':False})
    def test_halt_during_maintenance_cannot_resume(self):
        self.begin(True);self.c.halt()
        result=self.end(abort=True);self.assertFalse(result['resumed']);self.assertTrue(self.c.halt_event.is_set())
    def test_unknown_cleanup_retains_handle_and_blocks_finish(self):
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
        self.job.pending=True
        with self.assertRaisesRegex(ValueError,'CLEANUP_PENDING'):self.end(abort=True)
        self.assertIs(self.c._execution_charts_job,self.job);self.assertTrue(self.c.maintenance_status()['job_active'])
        self.job.pending=False;self.c.maintenance_status();result=self.end(abort=True);self.assertFalse(result['resumed'])
    def test_long_prepare_operation_status_is_scalar_and_timeout_cannot_resume(self):
        self.begin(True);entered=threading.Event();release=threading.Event();old=self.source.load;errors=[]
        def load(*args,**kwargs):entered.set();release.wait(8);return old(*args,**kwargs)
        def work():
            try:self.prepare()
            except Exception as exc:errors.append(exc)
        with patch.object(self.source,'load',load):
            thread=threading.Thread(target=work);thread.start()
            try:
                self.assertTrue(entered.wait(3));status=self.c.maintenance_status();self.assertEqual(status['phase'],'PREPARING');self.assertTrue(status['operation_active'])
                with self.assertRaisesRegex(ValueError,'CLEANUP_PENDING'):self.end(abort=True)
                self.assertTrue(self.c.stop_event.is_set());self.assertTrue(self.b.stop_event.is_set())
            finally:release.set();thread.join(10)
        self.assertFalse(thread.is_alive());result=self.end(abort=True);self.assertFalse(result['resumed']);self.assertEqual(FakeBroker.submissions,[])
    def test_partial_peer_or_main_failure_stays_paused_and_no_automatic_retry(self):
        self.begin(True);self.source.blocked.add('R10_DIRECT_H5_RIDGE_MID')
        self.assertEqual(self.prepare()['status'],'PARTIAL')
        with self.assertRaises(ValueError):self.end()
        self.assertFalse(self.c._maintenance['restore_requested']);self.assertFalse(self.end(abort=True)['resumed'])
        self.c._maintenance=None;self.source.blocked.clear();self.begin(True);self.prepare()
        self.main.side_effect=lambda now=None:{**self.metadata(now,'READY'),'status':'BLOCKED','reason':'CONSENSUS_RESOURCE_FLOOR'}
        with self.assertRaisesRegex(ValueError,'CONSENSUS_RESOURCE_FLOOR'):self.charts()
        self.source.start_execution_charts.assert_not_called();self.assertFalse(self.end(abort=True)['resumed'])
    def test_source_plan_account_or_main_current_receipt_changed_rejects_resume(self):
        for change in ('source','plan','account','main_session','main_blocked'):
            with self.subTest(change=change):
                self.c._maintenance=None;self.main.side_effect=lambda now=None:self.metadata(now,'READY');self.ready(True)
                status=self.source.status;plan=deepcopy(self.b.plan);cash=FakeBroker.cash
                if change=='source':self.source.status=lambda now=None:{**status(now),'source_refs':{'manifest':'z'*64}}
                if change=='plan':self.b.plan['rows'][0]['target_weight']+=.01
                if change=='account':FakeBroker.cash-=100
                if change=='main_session':self.main.side_effect=lambda now=None:{**self.metadata(now,'READY'),'end':'2026-09-25','context':{**self.metadata(now,'READY')['context'],'target_session':'2026-09-25'}}
                if change=='main_blocked':self.main.side_effect=lambda now=None:{**self.metadata(now,'READY'),'status':'BLOCKED'}
                try:
                    with self.assertRaises(ValueError):self.end()
                    self.assertTrue(self.c.stop_event.is_set());self.assertTrue(self.b.stop_event.is_set());self.assertFalse(self.c._maintenance['restore_requested'])
                finally:self.source.status=status;self.b.plan=plan;FakeBroker.cash=cash;self.end(abort=True)
    def test_crossed_execution_window_rejects_restore_without_grant_or_order(self):
        self.ready(True)
        with self.assertRaisesRegex(ValueError,'WINDOW_ACTIVE'):self.end(clock=OPEN+timedelta(seconds=5))
        self.assertFalse(self.c._maintenance['restore_requested']);self.assertEqual(FakeBroker.submissions,[])
    def test_begin_waits_for_original_thread_drain_without_new_scheduler(self):
        alive=Mock();alive.is_alive.return_value=True;self.c.worker=alive
        result=self.begin(True);self.assertEqual(result['phase'],'DRAINING');self.assertFalse(result['workers_drained'])
        with self.assertRaisesRegex(ValueError,'DRAINED'):self.prepare()
        alive.is_alive.return_value=False;self.assertEqual(self.c.maintenance_status()['phase'],'PAUSED');self.c.worker=None
    def test_window_watchdog_uses_admitted_owner_clock_without_source_or_sdk_and_retains_pending_cleanup(self):
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
        self.job.pending=True
        with (patch('moomoo_component.cohort._now',return_value=OPEN),patch.object(self.source,'status',side_effect=AssertionError('poll no source')),
                patch.object(self.b.engine.broker,'snapshot',side_effect=AssertionError('poll no SDK'))):
            status=self.c.maintenance_status()
        self.assertTrue(self.job.cancelled);self.assertTrue(status['job_active']);self.assertFalse(status['cleanup_verified']);self.assertFalse(status['restore_requested'])
        self.assertIs(self.c._execution_charts_job,self.job)
        with self.assertRaisesRegex(ValueError,'CLEANUP_PENDING'):self.end(abort=True)
        self.job.pending=False;self.c.maintenance_status();self.assertFalse(self.end(abort=True)['resumed'])
    def test_window_watchdog_pending_or_changed_binding_cancel_without_reading_new_source(self):
        for change in ('pending','binding'):
            with self.subTest(change=change):
                self.c._maintenance=None;self.job=Job();self.source.start_execution_charts.return_value=self.job
                self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
                item=patch.object(self.b.engine,'_pending',return_value=['UNKNOWN']) if change=='pending' else patch.object(self.b,'budget',9999)
                with item,patch('moomoo_component.cohort._now',return_value=self.clock),patch.object(self.source,'status',side_effect=AssertionError('poll no source')):
                    status=self.c.maintenance_status()
                self.assertTrue(self.job.cancelled);self.assertFalse(status['restore_requested']);self.assertFalse(self.end(abort=True)['resumed'])
                self.main.side_effect=lambda now=None:self.metadata(now,'READY')
    def test_watchdog_binding_diagnostics_cancel_and_never_expose_values(self):
        cases = (("budget", 9876.54321), ("account_id", "PRIVATE_ACCOUNT_24680"),
            ("strategy_id", "PRIVATE_STRATEGY_13579"), ("active_ids", None))
        for field, value in cases:
            with self.subTest(field=field):
                self.c._maintenance=None;self.job=Job();self.source.start_execution_charts.return_value=self.job
                self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
                before=self.fixture.counts()
                if field == "active_ids":
                    change=patch.object(self.c,'_active_ids',return_value=tuple(reversed(self.c._active_ids())))
                else:
                    target=self.b.engine if field == "account_id" else self.b
                    change=patch.object(target,field,value)
                with change,patch('moomoo_component.cohort._now',return_value=self.clock), \
                        patch.object(self.source,'status',side_effect=AssertionError('watchdog must not query source')):
                    status=self.c.maintenance_status()
                diagnostic=dict(kind="BINDING_SNAPSHOT_CHANGED",changed_fields=[field])
                self.assertEqual(status['watchdog_diagnostic'],diagnostic)
                self.assertTrue(self.job.cancelled);self.assertFalse(status['restore_requested'])
                self.assertEqual(status['reason'],'MANUAL_MAINTENANCE_QUEUED_BINDING_CHANGED')
                rendered=json.dumps(diagnostic)
                for secret in ('PRIVATE_ACCOUNT_24680','PRIVATE_STRATEGY_13579','9876.54321'):
                    self.assertNotIn(secret,rendered)
                finished=self.end(abort=True)
                self.assertEqual(finished['phase'],'FINISHED');self.assertFalse(finished['resumed'])
                self.assertEqual(finished['watchdog_diagnostic'],diagnostic)
                self.assertEqual(before,self.fixture.counts());self.assertEqual(FakeBroker.submissions,[])
                self.main.side_effect=lambda now=None:self.metadata(now,'READY')

    def test_watchdog_validation_diagnostic_is_bounded_and_survives_pending_cleanup(self):
        cases=(("SHOWCASE_ROSTER_AUDIT_MISSING","SHOWCASE_ROSTER_AUDIT_MISSING"),
            ("ACCOUNT_CHANGED:PRIVATE_ACCOUNT_24680 budget=9876.54321","UNKNOWN"),
            ("A"*65,"UNKNOWN"),
            ("SHOWCASE_ROSTER_ORIGINAL_V1_BINDING_CHANGED","SHOWCASE_ROSTER_ORIGINAL_V1_BINDING_CHANGED"),
            ("ACCOUNT_123","UNKNOWN"))
        for message, code in cases:
            with self.subTest(message=message):
                self.c._maintenance=None;self.job=Job();self.source.start_execution_charts.return_value=self.job
                self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
                self.job.pending=True
                with patch.object(self.c,'_active_ids',side_effect=ValueError(message)), \
                        patch('moomoo_component.cohort._now',return_value=self.clock):
                    status=self.c.maintenance_status()
                diagnostic=dict(kind="BINDING_VALIDATION_ERROR",error_code=code)
                self.assertEqual(status['watchdog_diagnostic'],diagnostic)
                self.assertEqual(status['reason'],'EXECUTION_CHART_CLEANUP_PENDING')
                self.assertTrue(status['job_active']);self.assertFalse(status['cleanup_verified'])
                self.assertFalse(status['restore_requested']);self.assertTrue(self.job.cancelled)
                rendered=json.dumps(diagnostic)
                self.assertNotIn('PRIVATE_ACCOUNT_24680',rendered);self.assertNotIn('9876.54321',rendered)
                self.assertLessEqual(len(diagnostic['error_code']),64)
                self.job.pending=False
                with patch('moomoo_component.cohort._now',return_value=self.clock):
                    cleaned=self.c.maintenance_status()
                self.assertEqual(cleaned['watchdog_diagnostic'],diagnostic)
                finished=self.end(abort=True)
                self.assertEqual(finished['phase'],'FINISHED');self.assertFalse(finished['resumed'])
                self.assertEqual(finished['watchdog_diagnostic'],diagnostic)
                self.assertEqual(FakeBroker.submissions,[])
                self.main.side_effect=lambda now=None:self.metadata(now,'READY')

    def test_watchdog_main_publication_and_receipt_changes_do_not_cancel(self):
        self.begin(True);self.prepare();self.main.side_effect=lambda now=None:self.metadata(now,'PREFLIGHT');self.charts()
        bindings=deepcopy(self.c._maintenance['watch_bindings']);before=self.fixture.counts()
        main_ref=dict(path='synthetic/new_MAIN_manifest.json',sha256='a'*64)
        self.c._maintenance['main_receipt']=dict(status='READY',manifest_ref=main_ref)
        self.c.meta['execution_charts_update']=dict(status='COMPLETED',manifest_ref=main_ref)
        with patch('moomoo_component.cohort._now',return_value=self.clock), \
                patch.object(self.source,'status',side_effect=AssertionError('watchdog must not query source')):
            status=self.c.maintenance_status()
        self.assertFalse(self.job.cancelled);self.assertFalse(self.c._maintenance['cancel_requested'])
        self.assertEqual(status['phase'],'CHARTS_RUNNING');self.assertNotIn('watchdog_diagnostic',status)
        self.assertEqual(self.c._maintenance['watch_bindings'],bindings)
        self.job.code=0
        with patch('moomoo_component.cohort._now',return_value=self.clock):
            finished=self.c.maintenance_status()
        self.assertEqual(finished['phase'],'CHARTS_FINISHED');self.assertEqual(finished['job_exit_code'],0)
        self.assertEqual(finished['main_status'],'AWAITING_OWNER_RECEIPT')
        self.assertNotIn('watchdog_diagnostic',finished);self.assertFalse(self.job.cancelled)
        self.assertEqual(before,self.fixture.counts());self.assertEqual(FakeBroker.submissions,[])

    def test_http_exact_control_fields_and_status_no_cached_view(self):
        server=LocalServer(0,self.c.engines['RAW_A2'],live=FakeLive(),cohort=self.c);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),{'Content-Type':'application/json','X-CSRF-Token':server.token})
            response=conn.getresponse();value=json.loads(response.read());conn.close();return response.status,value
        try:
            with patch('moomoo_component.cohort._now',return_value=self.clock),patch.object(server,'applied_view_body',side_effect=AssertionError('not view')):
                code,value=request('/api/applied/maintenance-begin',{'maintenance_id':'http-1'});self.assertEqual(code,200,value)
                code,value=request('/api/applied/maintenance-status');self.assertEqual(code,200);self.assertEqual(value['data']['maintenance_id'],'http-1')
                for path in ('broker-strategy-binding','broker-published-target-alignment','broker-published-target-manual-completion','start'):
                    code,value=request('/api/applied/'+path,{})
                    self.assertEqual(code,400,value);self.assertEqual(value['error'],'MANUAL_MAINTENANCE_ACTIVE')
                for body in ({'maintenance_id':'http-1','success':True},{'maintenance_id':'http-1','abort':'yes'}):
                    self.assertEqual(request('/api/applied/maintenance-end',body)[0],400)
                code,value=request('/api/applied/maintenance-end',{'maintenance_id':'http-1','abort':True});self.assertEqual(code,200,value);self.assertFalse(value['data']['resumed'])
        finally:server.shutdown();server.server_close();thread.join(2)


class FiniteAdmissionMaintenanceTests(unittest.TestCase):
    def fixture(self):
        case = MaintenanceTests('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        return case

    def test_finite_ref_requires_manual_owner_and_end_rechecks_same_identity(self):
        case = self.fixture(); admission = {'path': 'finite.json', 'sha256': 'a' * 64}
        with self.assertRaisesRegex(ValueError, 'FINITE_CA_REQUIRES_MANUAL_MAINTENANCE'):
            case.c.request_execution_charts(expected_signal_date='2026-09-28', finite_ca_admission_ref=admission, now=case.clock)
        case.begin(False); case.prepare()
        def metadata(now=None, finite_ca_admission_ref=None):
            self.assertEqual(finite_ca_admission_ref, admission)
            result = case.metadata(now, 'READY')
            result['context'].update(finite_ca_admission_ref=deepcopy(admission), original_driver_ref={'path': 'old.py', 'sha256': 'd' * 64})
            return result
        case.main.side_effect = metadata
        case.c.request_execution_charts(expected_signal_date='2026-09-28', maintenance_id='daily-1', now=case.clock, finite_ca_admission_ref=admission)
        self.assertEqual(case.c._maintenance['main_context']['finite_ca_admission_ref'], admission)
        result = case.end(); self.assertFalse(result['resumed'])
        self.assertEqual(case.main.call_count, 2)
        self.assertEqual(FakeBroker.submissions, [])

    def test_http_finite_field_is_exact_and_only_charts_accepts_it(self):
        case = self.fixture(); admission = {'path': 'finite.json', 'sha256': 'a' * 64}
        server = LocalServer(0, case.c.engines['RAW_A2'], live=FakeLive(), cohort=case.c)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(path, body):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('POST', path, json.dumps(body), {'Content-Type': 'application/json', 'X-CSRF-Token': server.token})
            response = connection.getresponse(); response.read(); code = response.status; connection.close(); return code
        body = {'expected_signal_date': '2026-09-28', 'maintenance_id': 'explicit', 'finite_ca_admission_ref': admission}
        try:
            with patch.object(case.c, 'request_execution_charts', return_value={'status': 'READY'}) as charts:
                self.assertEqual(request('/api/applied/charts-update', body), 200)
                charts.assert_called_once_with(**body)
                for invalid in ({'path': 'finite.json'}, {'path': 'finite.json', 'sha256': True}, {**admission, 'extra': 1}, None):
                    self.assertEqual(request('/api/applied/charts-update', {**body, 'finite_ca_admission_ref': invalid}), 400)
                self.assertEqual(charts.call_count, 1)
                self.assertEqual(request('/api/applied/prepare-current', body), 400)
        finally: server.shutdown(); server.server_close(); thread.join(2)


class SharedSQLiteReadTests(unittest.TestCase):
    """Concurrent reads on disposable production-constructed owner connections."""
    def setUp(self):
        self.fixture=ManualPaperTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def assert_shared_read_consistency(self, connection):
        from concurrent.futures import ThreadPoolExecutor
        workers, repeats = 24, 100
        expected={worker:[(worker,row,'synthetic_%02d_%02d' % (worker,row)) for row in range(3)]
            for worker in range(workers)}
        connection.execute('CREATE TABLE synthetic_shared_reads(worker INTEGER,row_number INTEGER,label TEXT)')
        connection.executemany('INSERT INTO synthetic_shared_reads VALUES (?,?,?)',
            [row for rows in expected.values() for row in rows])
        connection.commit()
        barrier=threading.Barrier(workers)
        def read(worker):
            barrier.wait(timeout=10)
            for turn in range(repeats):
                group=(worker+turn) % workers
                rows=[tuple(row) for row in connection.execute(
                    'SELECT worker,row_number,label FROM synthetic_shared_reads WHERE worker=? ORDER BY row_number',
                    (group,)).fetchall()]
                self.assertEqual(rows,expected[group])
            return repeats
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(read,worker) for worker in range(workers)]
            counts=[future.result(timeout=30) for future in futures]
        self.assertEqual(counts,[repeats]*workers)
        self.assertEqual(sum(counts),2400)
        self.assertEqual(self.fixture.source.loads,[])
        self.assertEqual(self.fixture.quotes.calls,[])

    def test_cohort_production_connection_concurrent_reads_are_exact(self):
        self.assert_shared_read_consistency(self.fixture.cohort.db)

    def test_engine_production_connection_concurrent_reads_are_exact(self):
        self.assert_shared_read_consistency(self.fixture.cohort.engines['RAW_A2'].db)
