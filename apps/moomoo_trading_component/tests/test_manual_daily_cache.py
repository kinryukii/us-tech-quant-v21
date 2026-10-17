"""Manual daily maintenance; disposable owners, quotes and SDK fixtures only."""
from copy import deepcopy
from datetime import timedelta,datetime,timezone
from pathlib import Path
import http.client,json,tempfile,threading,unittest
from unittest.mock import Mock,patch
from moomoo_component.cohort import Cohort
from moomoo_component.best_broker import BestBroker,SID
from moomoo_component.core import Engine
from moomoo_component.server import LocalServer
from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
from test_five_strategy_execution import FiveSource,original_auto_policy
from test_cohort import Quotes,NoWorker,OPEN,CLOSE,CODES
from test_best_broker import FakeBroker
import test_best_broker as broker_tests
from test_http import FakeLive

class ManualPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.inception=patch('moomoo_component.core.now_iso',return_value=(CLOSE-timedelta(hours=6)).isoformat())
        self.inception.start();self.addCleanup(self.inception.stop)
        self.source,self.quotes=FiveSource(),Quotes()
        self.source.daily_root=Path(self.temp.name)/"daily"
        self.cohort=Cohort(Path(self.temp.name)/'books',self.source,self.quotes,
            execution_window_seconds=600,allow_partial_quotes=True,manual_data_updates=True)
        self.addCleanup(self.cohort.close)
        self.cohort.migrate_strategy_membership(migration_id='manual-five',requested_at=(CLOSE+timedelta(minutes=5)).isoformat(),
            expected_precondition_sha256=self.cohort.state()['membership_precondition_sha256'],
            target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS),now=CLOSE+timedelta(minutes=5))
    def tick(self,clock):
        self.quotes.clock=clock
        with patch('moomoo_component.cohort.threading.Thread',NoWorker):self.cohort.start()
        return self.cohort.tick(now=clock)
    def pause(self):self.cohort.stop()
    def counts(self):
        return {sid:tuple(e.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            for table in ('orders','order_fills','paper_fills','paper_batches')) for sid,e in self.cohort.engines.items()}
    def prepare(self):return self.cohort.prepare_published_inputs(expected_signal_date='2026-09-28',now=CLOSE+timedelta(minutes=10))
    def test_idle_ticks_never_acquire_infer_or_start_charts(self):
        self.source.start_execution_charts=Mock(side_effect=AssertionError('no chart job'))
        self.source.execution_charts_status=Mock(side_effect=AssertionError('no chart metadata during idle'))
        before=self.counts()
        with patch.object(self.source,'load',side_effect=AssertionError('no model load')) as load,patch.object(self.source,'refresh',side_effect=AssertionError('no acquisition')) as refresh:
            for clock in (OPEN-timedelta(minutes=10),OPEN+timedelta(seconds=10),OPEN+timedelta(hours=7)):
                state=self.tick(clock)
            load.assert_not_called();refresh.assert_not_called()
        self.source.start_execution_charts.assert_not_called();self.source.execution_charts_status.assert_not_called()
        self.assertEqual(self.counts(),before)
        self.assertTrue(all(b['status']=='WAITING_MANUAL_UPDATE' for b in state['books'].values()))
    def test_explicit_prepare_only_all_five_preserves_accounts_balances_and_order_rows(self):
        before=self.counts();books={sid:e.paper_book() for sid,e in self.cohort.engines.items()}
        result=self.prepare();self.assertEqual(result['status'],'READY');self.assertEqual(result['orders_created'],0)
        self.assertFalse(result['running']);self.assertEqual(set(result['books']),set(ACTIVE_PAPER_STRATEGY_IDS))
        self.assertEqual(self.counts(),before)
        self.assertEqual({sid:e.paper_book() for sid,e in self.cohort.engines.items()},books)
        self.assertEqual(len(self.source.loads),1);self.assertEqual(set(self.source.loads[0]),set(ACTIVE_PAPER_STRATEGY_IDS))
        self.assertEqual(self.source.loads[0]['R7_GROSS_LINEAR']['previous_requested_gross'],1)
        frozen=deepcopy((self.cohort.plans,self.cohort.close_states,self.cohort.meta['strategy_requested_state']))
        self.prepare();self.assertEqual(len(self.source.loads),1)
        self.assertEqual((self.cohort.plans,self.cohort.close_states,self.cohort.meta['strategy_requested_state']),frozen)
    def test_published_cached_plans_execute_with_quotes_without_model_reload(self):
        self.prepare();plans=deepcopy(self.cohort.plans)
        with patch.object(self.source,'load',side_effect=AssertionError('cached consumer no load')),patch.object(self.source,'refresh',side_effect=AssertionError('no acquisition')):
            first=self.tick(OPEN+timedelta(seconds=5));counts=self.counts()
            self.tick(OPEN+timedelta(seconds=6))
        self.assertTrue(all(b['status']=='EXECUTED' for b in first['books'].values()))
        self.assertEqual(self.counts(),counts);self.assertEqual(self.cohort.plans,plans);self.assertTrue(self.quotes.calls)
    def test_source_change_blocks_cached_targets_without_inference(self):
        self.prepare();status=self.source.status
        self.source.status=lambda now=None:{**status(now),'source_refs':{'manifest':'c'*64}}
        with patch.object(self.source,'load',side_effect=AssertionError('no replacement infer')):
            state=self.tick(OPEN+timedelta(seconds=5))
        self.assertTrue(all(b['status']=='BLOCKED' for b in state['books'].values()))
        self.assertTrue(all('FROZEN_BOOK_SOURCE_CHANGED' in b['reason'] for b in state['books'].values()))
        self.assertTrue(all(count[0]==0 for count in self.counts().values()))
    def test_blocked_peer_requires_another_explicit_update_not_idle_retry(self):
        self.source.blocked.add('R10_DIRECT_H5_RIDGE_MID');result=self.prepare()
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['books']['RAW_A2']['status'],'READY')
        self.assertEqual(result['books']['R10_DIRECT_H5_RIDGE_MID']['status'],'BLOCKED')
        loads=len(self.source.loads)
        self.tick(OPEN-timedelta(minutes=5));self.tick(OPEN-timedelta(minutes=4))
        self.assertEqual(len(self.source.loads),loads)
        self.pause();self.source.blocked.clear();self.prepare();self.assertEqual(len(self.source.loads),loads+1)
    def test_prepare_requires_same_current_source_and_paused_idle_owner(self):
        for guard in ('running','halt','pending','wrong_signal','mode'):
            with self.subTest(guard=guard):
                self.cohort.stop_event.set();self.cohort.halt_event.clear();self.cohort.manual_data_updates=True
                if guard=='running':self.cohort.stop_event.clear()
                if guard=='halt':self.cohort.halt_event.set()
                if guard=='mode':self.cohort.manual_data_updates=False
                pending=patch.object(self.cohort.engines['RAW_A2'],'_pending',return_value=['unknown']) if guard=='pending' else patch.object(self.cohort.engines['RAW_A2'],'_pending',return_value=[])
                with pending,self.assertRaises(ValueError):
                    self.cohort.prepare_published_inputs(expected_signal_date='2026-09-29' if guard=='wrong_signal' else '2026-09-28',now=CLOSE+timedelta(minutes=10))
                self.assertEqual(self.source.loads,[])
        self.cohort.manual_data_updates=True;self.cohort.stop_event.set();self.cohort.halt_event.clear()
    def test_unreconciled_sim_rejects_before_any_paper_model_or_account_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=Engine(tmp,broker_factory=FakeBroker)
            broker=BestBroker(tmp,self.source,engine=engine,manual_data_updates=True)
            self.cohort.best_broker=broker
            try:
                with self.assertRaisesRegex(ValueError,'ORIGINAL_ACCOUNT_RECONCILE'):self.prepare()
                self.assertEqual(self.source.loads,[]);self.assertEqual(engine.mode,'paper')
                self.assertIsNone(engine._get('best_account',None));self.assertIsNone(engine._get('best_capital',None))
            finally:self.cohort.best_broker=None;broker.close()

    def test_next_source_requires_manual_prepare_and_keeps_previous_plan_bytes(self):
        self.prepare();plans=deepcopy(self.cohort.plans);status=self.source.status
        self.source.status=lambda now=None:{**status(now),'signal_date':'2026-09-29','source_date':'2026-09-29','execution_date':'2026-09-30',
            'signal_close_utc':(CLOSE+timedelta(days=1)).isoformat(),'next_open_utc':(OPEN+timedelta(days=1)).isoformat(),
            'next_close_utc':(OPEN+timedelta(days=1,hours=6,minutes=30)).isoformat()}
        state=self.tick(OPEN+timedelta(days=1,seconds=5))
        self.assertEqual(self.cohort.plans,plans);self.assertEqual(len(self.source.loads),1)
        self.assertTrue(all(b['status']=='WAITING_MANUAL_UPDATE' for b in state['books'].values()))
    def chart_fixture(self):
        clock=OPEN+timedelta(minutes=11);data=self.source.status(clock)
        data['source_refs']['selected/package.json']={'path':'synthetic-package','sha256':'a'*64}
        self.source.status=Mock(return_value=data)
        self.source.execution_charts_status=Mock(return_value={'status':'UNAVAILABLE'})
        self.source.main_execution_charts_status=Mock(return_value=dict(status='READY',end='2026-09-28',models_loaded=0,
            ledger_values_decoded=0,broker_action_allowed=False,context={'target_session':'2026-09-28',
            'driver_ref':{'path':'synthetic-driver','sha256':'d'*64},'publication_ref':{'path':'synthetic-pub','sha256':'b'*64}}))
        job=Mock();job.poll.return_value=None;job.quarantine_reason.return_value=None
        self.source.start_execution_charts=Mock(return_value=job)
        self.addCleanup(lambda:setattr(job.poll,'return_value',0))
        return clock,job
    def test_charts_require_explicit_running_request_and_cancel_on_window(self):
        clock,job=self.chart_fixture()
        with self.assertRaisesRegex(ValueError,'RUNNING_OWNER'):self.cohort.request_execution_charts(expected_signal_date='2026-09-28',now=clock)
        self.source.start_execution_charts.assert_not_called()
        self.cohort.stop_event.clear()
        self.cohort._execution_charts_tick(self.source.status(clock),clock)
        self.source.start_execution_charts.assert_not_called()
        self.cohort.request_execution_charts(expected_signal_date='2026-09-28',now=clock)
        self.source.start_execution_charts.assert_called_once_with(legacy=True,main_request=None)
        self.cohort._execution_charts_tick(self.source.status(OPEN),OPEN+timedelta(seconds=10))
        self.assertTrue(job.cancel.called);job.poll.return_value=0
    def test_completed_job_is_polled_but_never_automatically_restarted(self):
        clock,job=self.chart_fixture();self.cohort.stop_event.clear()
        self.cohort.request_execution_charts(expected_signal_date='2026-09-28',now=clock)
        job.poll.return_value=2;job.result.return_value={'exit_code':2,'stages':{'legacy':{'exit_code':2}}}
        self.cohort._execution_charts_tick(self.source.status(clock),clock+timedelta(minutes=20))
        self.cohort._execution_charts_tick(self.source.status(clock),clock+timedelta(minutes=40))
        self.assertEqual(self.source.start_execution_charts.call_count,1)
    def reopen_clock_delay(self, delay=30):
        path=self.cohort.path
        self.cohort.close()
        self.cohort=Cohort(path,self.source,self.quotes,execution_delay_minutes=delay,
            execution_window_seconds=600,allow_partial_quotes=True,manual_data_updates=True)
        self.addCleanup(self.cohort.close)

    def test_future_five_book_clock_rebind_uses_cached_targets_and_is_idempotent(self):
        self.prepare()
        frozen=deepcopy((self.cohort.plans,self.cohort.close_states,self.cohort.meta['strategy_requested_state']))
        old=deepcopy(self.cohort.meta['book_plan_metadata']);before=self.counts()
        self.reopen_clock_delay()
        with patch.object(self.source,'load',side_effect=AssertionError('clock change cannot infer')),patch.object(self.source,'refresh',side_effect=AssertionError('clock change cannot acquire')):
            receipt=self.prepare()
            self.assertEqual(receipt['status'],'READY');self.assertFalse(receipt['running'])
            self.assertEqual(receipt['orders_created'],0)
            for sid in ACTIVE_PAPER_STRATEGY_IDS:
                changed=self.cohort.meta['book_plan_metadata'][sid]
                self.assertEqual(changed['execution_time_utc'],(OPEN+timedelta(minutes=30)).isoformat())
                self.assertEqual((changed['execution_delay_minutes'],changed['execution_window_seconds']),(30,600))
                for key in set(old[sid])-{'execution_time_utc','execution_delay_minutes','execution_window_seconds'}:
                    self.assertEqual(changed[key],old[sid][key])
            events=[json.loads(row[0]) for row in self.cohort.db.execute(
                "SELECT detail FROM events WHERE event='PAPER_EXECUTION_SCHEDULE_CHANGED'")]
            self.assertEqual({row['strategy_id'] for row in events},set(ACTIVE_PAPER_STRATEGY_IDS))
            self.assertTrue(all(row['orders_created']==0 for row in events))
            self.prepare()
            self.assertEqual(self.cohort.db.execute("SELECT COUNT(*) FROM events WHERE event='PAPER_EXECUTION_SCHEDULE_CHANGED'").fetchone()[0],len(events))
        self.assertEqual(self.counts(),before)
        self.assertEqual((self.cohort.plans,self.cohort.close_states,self.cohort.meta['strategy_requested_state']),frozen)

    def test_restart_delay_change_preserves_sealed_manual_global_clock(self):
        self.prepare()
        record=dict(signal_date='2026-09-28',execution_date='2026-09-29',deadline_utc=(OPEN+timedelta(hours=1)).isoformat())
        self.cohort.meta['paper_first_execution']=deepcopy(record);self.cohort._persist()
        metadata=deepcopy(self.cohort.plan_metadata);books=deepcopy(self.cohort.meta['book_plan_metadata'])
        self.reopen_clock_delay()
        self.assertEqual(self.cohort.plan_metadata,metadata)
        self.assertEqual(self.cohort.meta['book_plan_metadata'],books)
        self.assertEqual(self.cohort.meta['paper_first_execution'],record)
        self.assertEqual(self.cohort.execution_delay_minutes,30)

    def test_clock_rebind_refuses_any_execution_attempt_including_empty_batch(self):
        self.prepare();sid='RAW_A2';old=deepcopy(self.cohort.meta['book_plan_metadata'][sid])
        self.reopen_clock_delay();engine=self.cohort.engines[sid]
        for table in ('orders','paper_batches','paper_fills'):
            with self.subTest(table=table):
                if table=='orders':
                    engine.db.execute('INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status) VALUES (?,?,?,?,?,?,?,?,?,?)',
                        ('clock-attempt',OPEN.isoformat(),sid,'paper',engine.account_id,CODES[0],'BUY',1,100,'FAILED'))
                else:
                    payload=dict(strategy_id=sid,signal_date='2026-09-28',execution_date='2026-09-29',
                        status='WAITING_QUOTES',processed_codes=[],executed_codes=[])
                    engine.db.execute('INSERT INTO '+table+' VALUES (?,?)',('clock-attempt',json.dumps(payload)))
                engine.db.commit();before=self.counts()
                with patch.object(self.source,'load',side_effect=AssertionError('attempted signal cannot infer')):
                    receipt=self.prepare()
                self.assertEqual(receipt['books'][sid]['status'],'BLOCKED')
                self.assertEqual(self.cohort.meta['book_plan_metadata'][sid],old)
                self.assertEqual(self.counts(),before)
                engine.db.execute('DELETE FROM '+table+' WHERE id=?',('clock-attempt',));engine.db.commit()

    def test_clock_rebind_preserves_plain_and_archived_manual_permission_slots(self):
        self.prepare();sid='RAW_A2';old=deepcopy(self.cohort.meta['book_plan_metadata'][sid])
        self.reopen_clock_delay();engine=self.cohort.engines[sid]
        keys=('paper_first_execution','paper_first_continuation','paper_same_day_catchup','paper_same_day_catchup_renewal')
        slots=('paper_first_execution:2026-09-28','paper_first_continuation:2026-09-28')
        cases=[('meta',key) for key in keys]+[('cohort',key) for key in slots]+[('engine',key) for key in keys+slots]
        for location,key in cases:
            with self.subTest(location=location,key=key):
                record=dict(signal_date='2026-09-28',execution_date='2026-09-29',deadline_utc=(OPEN+timedelta(hours=1)).isoformat())
                raw=json.dumps(record)
                db=self.cohort.db if location=='cohort' else engine.db
                if location=='meta':self.cohort.meta[key]=deepcopy(record);self.cohort._persist()
                else:db.execute('INSERT INTO settings VALUES (?,?)',(key,raw));db.commit()
                with patch.object(self.source,'load',side_effect=AssertionError('manual-bound signal cannot infer')):
                    receipt=self.prepare()
                self.assertEqual(receipt['books'][sid]['status'],'BLOCKED')
                self.assertEqual(self.cohort.meta['book_plan_metadata'][sid],old)
                if location=='meta':
                    self.assertEqual(self.cohort.meta[key],record);self.cohort.meta.pop(key);self.cohort._persist()
                else:
                    self.assertEqual(db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0],raw)
                    db.execute('DELETE FROM settings WHERE key=?',(key,));db.commit()

    def test_rebound_clock_waits_until_ten_and_executes_cached_five_only_once(self):
        self.prepare();self.reopen_clock_delay();self.prepare()
        opening=OPEN+timedelta(minutes=30)
        with patch.object(self.source,'load',side_effect=AssertionError('clock consumer cannot infer')),patch.object(self.source,'refresh',side_effect=AssertionError('clock consumer cannot acquire')):
            before=self.counts();self.tick(opening-timedelta(microseconds=1))
            self.assertEqual(self.counts(),before);self.assertEqual(self.quotes.calls,[])
            state=self.tick(opening)
            self.assertTrue(all(book['status']=='EXECUTED' for book in state['books'].values()))
            after=self.counts();self.tick(opening+timedelta(minutes=10))
            self.assertEqual(self.counts(),after)

    def test_ten_clock_preserves_only_original_hgb_standing_completion_scope(self):
        self.prepare();policy=original_auto_policy()
        self.cohort.meta['automatic_completion_policy']=deepcopy(policy)
        for engine in self.cohort.engines.values():
            engine._set('automatic_completion_policy',policy)
            engine.db.execute('INSERT INTO audit VALUES (?,?,?)',(policy['authorized_at_utc'],
                'AUTOMATIC_COMPLETION_POLICY_AUTHORIZED',json.dumps(policy)))
            engine.db.commit()
        self.cohort._persist();self.reopen_clock_delay();self.prepare()
        with patch.object(self.source,'load',side_effect=AssertionError('standing consumer cannot infer')),patch.object(self.source,'refresh',side_effect=AssertionError('standing consumer cannot acquire')):
            state=self.tick(OPEN+timedelta(minutes=40))
        self.assertEqual(state['books'][SID]['status'],'EXECUTED')
        for sid in set(ACTIVE_PAPER_STRATEGY_IDS)-{SID}:
            self.assertEqual(state['books'][sid]['status'],'MISSED_OPEN')
        self.assertEqual(self.cohort.meta['automatic_completion_policy'],policy)
        self.assertTrue(all(engine._get('paper_same_day_catchup',None) is None for engine in self.cohort.engines.values()))

    def test_rebound_ten_minute_end_does_not_create_or_extend_manual_authority(self):
        self.prepare();self.reopen_clock_delay();self.prepare();before=self.counts()
        with patch.object(self.source,'load',side_effect=AssertionError('expired consumer cannot infer')),patch.object(self.source,'refresh',side_effect=AssertionError('expired consumer cannot acquire')):
            state=self.tick(OPEN+timedelta(minutes=40))
        self.assertTrue(all(book['status']=='MISSED_OPEN' for book in state['books'].values()))
        self.assertEqual(self.counts(),before);self.assertEqual(self.quotes.calls,[])
        for key in ('paper_first_execution','paper_first_continuation','paper_same_day_catchup','paper_same_day_catchup_renewal'):
            self.assertNotIn(key,self.cohort.meta)
            self.assertTrue(all(engine._get(key,None) is None for engine in self.cohort.engines.values()))

    def test_legacy_cached_plan_keeps_full_clock_and_source_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy=Cohort(tmp,self.source,self.quotes,manual_data_updates=True)
            try:
                legacy.prepare_published_inputs(expected_signal_date='2026-09-28',now=CLOSE+timedelta(minutes=10))
                data=self.source.status(OPEN-timedelta(minutes=1))
                with patch.object(self.source,'load',side_effect=AssertionError('legacy current no inference')):
                    legacy._prepare(data,OPEN-timedelta(minutes=1))
                    for field in ('execution_date','next_open_utc','signal_close_utc','source_refs'):
                        changed=deepcopy(data)
                        changed[field]='changed' if field!='source_refs' else {'manifest':'b'*64}
                        with self.subTest(field=field),self.assertRaisesRegex(ValueError,'FROZEN_BOOK_'):
                            legacy._prepare(changed,OPEN-timedelta(minutes=1))
            finally:legacy.close()
    def test_library_default_automatic_and_explicit_cli_flag_remain_compatible(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as tmp:
            normal=Cohort(tmp,self.source,self.quotes)
            try:self.assertFalse(normal.manual_data_updates)
            finally:normal.close()
        command=[sys.executable,'-B','-m','apps.moomoo_trading_component.moomoo_component']
        help_result=subprocess.run(command+['--help'],capture_output=True,text=True,timeout=10)
        self.assertEqual(help_result.returncode,0);self.assertIn('--manual-data-updates',help_result.stdout)
        rejected=subprocess.run(command+['--manual-data-updates'],capture_output=True,text=True,timeout=10)
        self.assertEqual(rejected.returncode,2);self.assertIn('requires --applied-strategies',rejected.stderr)

    def test_http_controls_allow_only_published_date_not_trade_permissions(self):
        engine=self.cohort.engines['RAW_A2'];server=LocalServer(0,engine,live=FakeLive(),cohort=self.cohort)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(self.cohort,'state',side_effect=AssertionError('health cannot read cache or account state')):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                conn.request('GET','/api/health');response=conn.getresponse();health=json.loads(response.read());conn.close()
                self.assertEqual(response.status,200);self.assertIs(health['data']['manual_data_updates'],True)
            with patch('moomoo_component.server.datetime') as timer:
                timer.now.return_value=CLOSE+timedelta(minutes=10)
                for body,expected in (({'expected_signal_date':'2026-09-28'},200),
                        ({'expected_signal_date':'2026-09-28','target_weights':{}},400),({'expected_signal_date':'2026-09-28','authorize':True},400)):
                    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                    conn.request('POST','/api/applied/prepare-current',json.dumps(body),{'Content-Type':'application/json','X-CSRF-Token':server.token})
                    response=conn.getresponse();payload=json.loads(response.read());conn.close();self.assertEqual(response.status,expected,payload)
        finally:server.shutdown();server.server_close();thread.join(2)

class ManualBrokerTests(unittest.TestCase):
    def setUp(self):
        self.base=broker_tests.BestBrokerTests(methodName='runTest')
        self.base.setUp();self.addCleanup(self.base.tearDown)
        self.broker,self.engine,self.source=self.base.runner,self.base.engine,self.base.source
        self.broker.manual_data_updates=True
        self.source.daily_root=Path(self.base.temp.name)/"daily"
        status=self.source.status
        self.source.status=lambda now=None:{**status(now),'source_date':'2026-09-25'}
        self.source.load=Mock(wraps=self.source.load)
        self.broker._connect()
        self.clock=datetime(2026,9,25,20,10,tzinfo=timezone.utc)
    def test_paused_prepare_only_and_saved_plan_reuse_do_not_submit_or_repeat_models(self):
        before=len(FakeBroker.submissions)
        receipt=self.broker.prepare_published_inputs(expected_signal_date='2026-09-25',now=self.clock)
        self.assertTrue(receipt['prepared']);self.assertFalse(receipt['running']);self.assertEqual(receipt['orders_created'],0)
        raw=self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0]
        self.broker.prepare_published_inputs(expected_signal_date='2026-09-25',now=self.clock)
        self.assertEqual(self.source.load.call_count,1)
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],raw)
        self.assertEqual(len(FakeBroker.submissions),before)
    def test_running_tick_missing_plan_waits_for_manual_update_without_inference(self):
        self.broker.stop_event.clear();self.broker._prepare(self.base.opening-timedelta(minutes=10))
        self.assertEqual(self.broker.status,'WAITING_MANUAL_UPDATE');self.source.load.assert_not_called()
        self.assertEqual(FakeBroker.submissions,[])
    def test_current_cached_plan_keeps_original_before_send_source_gate(self):
        self.broker.prepare_published_inputs(expected_signal_date='2026-09-25',now=self.clock)
        self.broker.stop_event.clear()
        FakeBroker.clock=staticmethod(lambda:self.base.opening+timedelta(seconds=10))
        self.broker._now=lambda:self.base.opening+timedelta(seconds=10)
        self.engine.cancel_step.clear()
        self.assertTrue(self.broker._source_send_ready(self.broker._now()))
        self.assertEqual(self.source.load.call_count,1)
        self.source.status=lambda now=None:{'status':'BLOCKED','signal_date':'2026-09-25','source_date':'2026-09-25','data_gaps':['changed'],
            'execution_date':'2026-09-28','next_open_utc':self.base.opening.isoformat(),'signal_close_utc':'2026-09-25T20:00:00+00:00'}
        self.assertFalse(self.broker._source_send_ready(self.broker._now()))
        self.assertEqual(FakeBroker.submissions,[])
    def test_paused_existing_conversion_prepares_successor_from_same_owner_without_orders(self):
        import test_published_target_alignment as alignment_tests
        fixture=alignment_tests.AlignmentTests(methodName='runTest');fixture.setUp()
        try:
            runner,engine=fixture.runner,fixture.engine
            fixture.align();runner.manual_data_updates=True
            target,_=fixture.successor_target();fixture.now=fixture.source.opening-timedelta(minutes=5)
            runner._now=lambda:fixture.now
            before={table:[tuple(row) for row in engine.db.execute('SELECT * FROM '+table)] for table in ('orders','order_fills')}
            loads=len(fixture.source.loads)
            receipt=runner.prepare_published_inputs(expected_signal_date=fixture.source.signal,now=fixture.now)
            self.assertTrue(receipt['prepared']);self.assertEqual(receipt['orders_created'],0);self.assertTrue(runner.stop_event.is_set())
            self.assertEqual(len(fixture.source.loads),loads)
            self.assertEqual({table:[tuple(row) for row in engine.db.execute('SELECT * FROM '+table)] for table in before},before)
            self.assertEqual(engine._get('best_published_target_conversion',{})['status'],'ACTIVE')
            self.assertEqual(engine._get('best_requested_strategy_state',{})[alignment_tests.R7]['previous_requested_gross'],target['requested_gross'])
        finally:fixture.doCleanups()

    def test_prepare_rejects_running_halt_pending_and_account_change(self):
        for guard in ('running','halt','pending','account','date','mode'):
            with self.subTest(guard=guard):
                self.broker.stop_event.set();self.engine.halt_event.clear();self.broker.manual_data_updates=True
                if guard=='running':self.broker.stop_event.clear()
                if guard=='halt':self.engine.halt_event.set()
                if guard=='mode':self.broker.manual_data_updates=False
                account=self.engine.account_id
                if guard=='account':self.engine.account_id='other'
                pending=patch.object(self.engine,'_pending',return_value=['unknown'] if guard=='pending' else [])
                try:
                    with pending,self.assertRaises(ValueError):
                        self.broker.prepare_published_inputs(expected_signal_date='2026-09-26' if guard=='date' else '2026-09-25',now=self.clock)
                finally:self.engine.account_id=account
                self.assertEqual(FakeBroker.submissions,[]);self.source.load.assert_not_called()
        self.broker.stop_event.set();self.engine.halt_event.clear();self.broker.manual_data_updates=True

if __name__=='__main__':unittest.main()
