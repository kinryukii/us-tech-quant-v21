"""Equivalent bounded presentation reads; synthetic SQLite only."""
from datetime import timedelta
from copy import deepcopy
import http.client,json,tempfile,threading,unittest
from unittest.mock import patch
from moomoo_component.core import Engine
from moomoo_component.cohort import Cohort
from moomoo_component.server import LocalServer,applied_display_view,_APPLIED_DISPLAY_OMITTED_RECORD_FIELDS
from test_cohort import Source,Quotes,OPEN,CLOSE
from test_http import FakeLive

class CompactOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cohort=Cohort(self.temp.name,Source(),Quotes());self.addCleanup(self.cohort.close)
        self.engine=self.cohort.engines["RAW_A2"]
    def payload(self,seq=0):
        return dict(id=str(seq),strategy_id="RAW_A2",sequence=seq,filled_at=f"2026-09-28T20:00:{seq%60:02}+00:00",
            execution_date="2026-09-29",code="US.AAA",qty=1,fill_price=100,fee=.05,
            signal_source_refs={"huge":"x"*65536},source_plan={"excluded":"y"*4096},
            source_refs={"qualified":{"path":"D:/qualified.json","sha256":"a"*64,"metadata":"z"*4096}},
            quote_source="MOOMOO_OPEND",nested={"keep":1,"source_plan":{"removed":1}})
    def test_compact_owner_equals_original_projection_and_full_history_bytes_stay(self):
        for i in range(3):
            value=self.payload(i)
            self.engine.db.execute("INSERT INTO paper_fills VALUES (?,?)",(str(i),json.dumps(value)))
            self.engine.db.execute("INSERT INTO paper_nav VALUES (?,?)",(f"2026-09-{i+1:02}",json.dumps({**value,"day":f"2026-09-{i+1:02}"})))
        self.engine.db.commit()
        raw=[tuple(r) for r in self.engine.db.execute("SELECT * FROM paper_fills")]
        full=self.cohort.state();expected=applied_display_view(full)
        compact=self.cohort.state(compact=True)
        self.assertEqual(compact,expected)
        self.assertEqual(self.cohort._membership_precondition(),full["membership_precondition_sha256"])
        self.assertEqual([tuple(r) for r in self.engine.db.execute("SELECT * FROM paper_fills")],raw)
        self.assertIn("signal_source_refs",self.engine.paper_trades()[0])
        self.assertIn("source_plan",self.engine.paper_nav_history()[0])
    def test_projection_occurs_before_python_decode_and_read_is_limited(self):
        for i in range(120):self.engine.db.execute("INSERT INTO paper_fills VALUES (?,?)",(str(i),json.dumps(self.payload(i))))
        self.engine.db.commit();seen=[];loads=json.loads
        def observe(value,*args,**kwargs):seen.append(len(value));return loads(value,*args,**kwargs)
        with patch("moomoo_component.core.json.loads",side_effect=observe):rows=self.engine.paper_trades(limit=100,compact=True)
        self.assertEqual(len(rows),100);self.assertEqual(len(seen),100);self.assertLess(max(seen),6000)
        self.assertEqual([r["sequence"] for r in rows],list(range(20,120)))
        for name in _APPLIED_DISPLAY_OMITTED_RECORD_FIELDS:self.assertTrue(all(name not in row for row in rows))
        with self.assertRaises(ValueError):self.engine.paper_trades(compact=True)
        with self.assertRaises(ValueError):self.engine.paper_nav_history(compact=True)
    def test_engine_reads_only_recent_order_fill_payloads(self):
        for i in range(120):
            self.engine.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(i),f"2026-09-28T20:{i//60:02}:{i%60:02}+00:00","demo","paper","paper","US.AAA","BUY",1,100,"FILLED","native-"+str(i)))
            self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",(str(i),json.dumps({"fill_qty":i})))
        self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",("orphan","THIS OLD UNUSED PAYLOAD MUST NOT BE DECODED"))
        self.engine.db.commit();seen=[];loads=json.loads
        def observe(value,*args,**kwargs):seen.append(value);return loads(value,*args,**kwargs)
        with patch("moomoo_component.core.json.loads",side_effect=observe):state=self.engine.state()
        self.assertEqual(len(state["orders"]),100)
        self.assertEqual([r["fill_qty"] for r in state["orders"]],list(range(119,19,-1)))
        self.assertEqual(sum(v.startswith('{"fill_qty":') for v in seen),100)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM order_fills").fetchone()[0],121)
    def test_fresh_source_display_clocks_sync_without_touching_frozen_plan_or_prefix(self):
        old_plan=deepcopy(self.cohort.plans);old_metadata=deepcopy(self.cohort.plan_metadata)
        self.cohort.meta["next_refresh_utc"]=CLOSE.isoformat()
        data=self.cohort.source.status(now=OPEN+timedelta(hours=1))
        data.update(next_refresh_utc=(OPEN+timedelta(hours=6,minutes=31)).isoformat(),refresh_not_before_utc=(CLOSE+timedelta(seconds=60)).isoformat())
        self.cohort._tick_active_members(data,OPEN+timedelta(hours=1),supplied_now=True)
        for key in ("next_refresh_utc","refresh_not_before_utc"):self.assertEqual(self.cohort.meta[key],data[key])
        self.assertEqual(self.cohort.plans,old_plan);self.assertEqual(self.cohort.plan_metadata,old_metadata)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0],0)
        old={key:self.cohort.meta[key] for key in ("next_refresh_utc","refresh_not_before_utc")}
        self.cohort._tick_active_members({**data,"status":"WAITING_SOURCE","data_gaps":["missing"],"next_refresh_utc":"not a clock"},OPEN+timedelta(hours=1),supplied_now=True)
        self.assertEqual({key:self.cohort.meta[key] for key in old},old)
        with self.assertRaises(ValueError):self.cohort._tick_active_members({**data,"next_refresh_utc":"not a clock"},OPEN+timedelta(hours=1),supplied_now=True)
        self.assertEqual({key:self.cohort.meta[key] for key in old},old)

    def test_view_owner_failure_returns_structured_503(self):
        class Broken:
            def state(self,*,compact=False):raise ValueError("PRIVATE payload must not be echoed")
        server=LocalServer(0,self.engine,live=FakeLive(),cohort=Broken())
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            conn.request("GET","/api/applied/view");response=conn.getresponse();body=json.loads(response.read());conn.close()
            self.assertEqual(response.status,503);self.assertEqual(body["error"],"APPLIED_DISPLAY_UNAVAILABLE")
            self.assertEqual(body["error_type"],"ValueError");self.assertNotIn("PRIVATE",json.dumps(body))
        finally:
            server.shutdown();server.server_close();thread.join(2)


class FiniteDisplayOwnerTests(unittest.TestCase):
    """Real owner locks and broker tick, blocking fake source, disposable SQLite."""
    def setUp(self):
        from pathlib import Path
        from moomoo_component.best_broker import BestBroker
        from test_best_broker import FakeBroker, FakeSource
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        class BlockingSource(FakeSource):
            def __init__(inner):
                super().__init__(OPEN);inner.entered=threading.Event();inner.release=threading.Event();inner.block=False
            def status(inner,now=None):
                if inner.block:
                    inner.entered.set()
                    if not inner.release.wait(20):raise RuntimeError("SYNTHETIC_SOURCE_RELEASE_NOT_SET")
                return {**super().status(now),"status":"WAITING_SOURCE","data_gaps":["synthetic missing source"]}
        self.source=BlockingSource()
        self.cohort=Cohort(Path(self.temp.name)/"books",Source(),Quotes())
        self.engine=Engine(Path(self.temp.name)/"broker",broker_factory=FakeBroker)
        self.broker=BestBroker(Path(self.temp.name)/"broker",self.source,engine=self.engine)
        self.cohort.best_broker=self.broker
        # Preserve the original automatic SIM start, while avoiding an unrelated PAPER tick.
        self.paper_run=patch.object(self.cohort,"_run",side_effect=lambda:self.cohort.stop_event.wait(20))
        self.paper_run.start()
        self.server=LocalServer(0,self.engine,live=FakeLive(),cohort=self.cohort)
        self.http=threading.Thread(target=self.server.serve_forever,daemon=True);self.http.start()
        self.addCleanup(self.cleanup_owners)
    def cleanup_owners(self):
        # This always runs even if an assertion fails; no blocked worker escapes a fixture.
        self.source.block=False;self.source.release.set()
        self.cohort.stop_event.set();self.broker.stop_event.set()
        if self.broker.worker:self.broker.worker.join(3)
        if self.cohort.worker:self.cohort.worker.join(3)
        self.server.shutdown();self.server.server_close();self.http.join(2)
        self.paper_run.stop();self.cohort.close()
    def request(self,method="GET",path="/api/applied/view"):
        headers={"Content-Type":"application/json","X-CSRF-Token":self.server.token}
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        try:
            conn.request(method,path,"{}" if method=="POST" else None,headers)
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()
    def rows(self):
        dbs=[self.cohort.db,self.engine.db,*(e.db for e in self.cohort.engines.values())]
        return [[(name,[tuple(r) for r in db.execute('SELECT * FROM "'+name+'"')])
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            for db in dbs]
    def test_blocked_source_start_ack_stale_view_nocache_and_recovery_are_finite(self):
        import time
        self.assertEqual(self.request()[0],200)
        cached=self.server._applied_view_snapshot
        self.source.block=True
        begin=time.monotonic();status,ack=self.request("POST","/api/applied/start")
        self.assertLess(time.monotonic()-begin,1.5)
        self.assertEqual(status,200);self.assertTrue(ack["data"]["applied"])
        self.assertEqual(ack["data"]["control_ack"],"START")
        self.assertTrue(ack["data"]["running"]);self.assertTrue(ack["data"]["broker_start_requested"])
        self.assertNotIn("books",ack["data"]);self.assertNotIn("plan",ack["data"])
        self.assertTrue(self.source.entered.wait(1));self.assertTrue(self.broker.worker.is_alive())
        before=self.rows();begin=time.monotonic();status,value=self.request()
        self.assertLess(time.monotonic()-begin,.9);self.assertEqual(status,200)
        self.assertEqual(value["display"]["status"],"STALE");self.assertTrue(value["display"]["owner_busy"])
        self.assertEqual(value["display"]["captured_at_utc"],cached[1])
        self.assertFalse(value["data"]["running"])  # Never used as the successful control acknowledgement.
        value["data"]["books"].clear()
        self.assertTrue(json.loads(cached[0])["books"])
        self.assertIs(self.server._applied_view_snapshot,cached);self.assertEqual(self.rows(),before)
        self.server._applied_view_snapshot=None;begin=time.monotonic();status,value=self.request()
        self.assertLess(time.monotonic()-begin,.9);self.assertEqual(status,503)
        self.assertEqual(value["error"],"APPLIED_DISPLAY_OWNER_BUSY")
        self.broker.stop_event.set();self.source.block=False;self.source.release.set();self.broker.worker.join(3)
        status,value=self.request();self.assertEqual(status,200)
        self.assertEqual(value["display"]["status"],"CURRENT");self.assertFalse(value["display"]["owner_busy"])
        self.assertTrue(value["data"]["running"]);self.assertNotEqual(value["display"]["captured_at_utc"],cached[1])
    def test_full_state_wait_does_not_hold_paper_lock_or_block_control_ack(self):
        held=threading.Event();release=threading.Event();state_done=threading.Event()
        def holder():
            with self.broker.lock:held.set();release.wait(10)
        thread=threading.Thread(target=holder,daemon=True);thread.start();self.assertTrue(held.wait(1))
        reader=threading.Thread(target=lambda:(self.cohort.state(),state_done.set()),daemon=True)
        try:
            reader.start()
            # Wait until the full reader reaches the separate SIM owner.
            import time
            time.sleep(.05)
            acquired=self.cohort.lock.acquire(timeout=.3)
            self.assertTrue(acquired)
            if acquired:self.cohort.lock.release()
            self.assertFalse(state_done.is_set())
        finally:
            release.set();thread.join(2);reader.join(2)
        self.assertTrue(state_done.is_set())
    def test_fresh_compact_with_broker_equals_full_projection_without_mutating_owner_bytes(self):
        from test_applied_display_view import fixture
        value=fixture()["broker"]
        value.update(source_refs={"proof":{"path":"D:/synthetic.json","sha256":"a"*64,"inputs":["old"]}},
            close_state={"audit_only":True},preserved_settings={"old":"exact"})
        before=self.rows()
        with patch.object(self.broker,"state",return_value=deepcopy(value)):
            full=self.cohort.state()
            self.assertEqual(self.cohort.display_state(),applied_display_view(full))
            self.assertEqual(full["broker"],value)
        self.assertEqual(self.rows(),before)
    def test_failed_automatic_broker_start_is_explicit_in_scalar_ack(self):
        with patch.object(self.broker,"start",side_effect=ValueError("SYNTHETIC_ACCOUNT_BLOCKED")):
            status,value=self.request("POST","/api/applied/start")
        self.assertEqual(status,200)
        self.assertTrue(value["data"]["applied"]);self.assertTrue(value["data"]["running"])
        self.assertEqual(value["data"]["broker_error"],"SYNTHETIC_ACCOUNT_BLOCKED")
        self.assertIsNone(self.broker.worker)

    def test_each_existing_owner_lock_has_a_finite_budget_and_releases_prior_locks(self):
        owners=[self.cohort.lock,self.engine.lock,self.broker.lock,self.cohort.engines["RAW_A2"].lock]
        for lock in owners:
            held=threading.Event();release=threading.Event()
            def holder():
                with lock:held.set();release.wait(10)
            worker=threading.Thread(target=holder,daemon=True);worker.start()
            try:
                self.assertTrue(held.wait(1))
                import time
                begin=time.monotonic()
                with self.assertRaises(TimeoutError):self.cohort.display_state(lock_timeout_seconds=.03)
                self.assertLess(time.monotonic()-begin,.4)
            finally:release.set();worker.join(2)
            self.assertEqual(self.cohort.display_state(lock_timeout_seconds=.1),self.cohort.state(compact=True))

    def test_stop_http_uses_existing_scalar_ack_without_display_or_authority_changes(self):
        self.cohort.stop_event.clear();self.broker.stop_event.clear()
        class OwnedChartFixture:
            calls=0
            def cancel(inner):inner.calls+=1
        chart=OwnedChartFixture();self.cohort._execution_charts_job=chart
        self.engine.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("pending-stop","2026-09-28T13:30:00+00:00","synthetic","moomoo_simulate","synthetic-1234","US.AAA","BUY",1,100,"PENDING_RECONCILE","native-pending"))
        self.engine.db.commit()
        before=[tuple(row) for row in self.engine.db.execute("SELECT * FROM settings ORDER BY key")]
        orders=[tuple(row) for row in self.engine.db.execute("SELECT * FROM orders ORDER BY id")]
        fills=[tuple(row) for row in self.engine.db.execute("SELECT * FROM order_fills ORDER BY id")]
        with patch.object(self.cohort,"state",side_effect=AssertionError("stop must not build a display")), \
                patch.object(self.broker,"state",side_effect=AssertionError("stop must not read SIM display")):
            status,value=self.request("POST","/api/applied/stop")
        self.assertEqual(status,200)
        self.assertEqual(value,{"ok":True,"data":{"control_ack":"STOP","applied":True,"running":False}})
        self.assertLess(len(json.dumps(value)),256)
        self.assertTrue(self.cohort.stop_event.is_set());self.assertTrue(self.broker.stop_event.is_set())
        self.assertTrue(all(engine.cancel_step.is_set() for engine in self.cohort.engines.values()))
        self.assertEqual(chart.calls,1);self.assertIsNone(self.cohort._execution_charts_job)
        self.assertEqual([tuple(row) for row in self.engine.db.execute("SELECT * FROM settings ORDER BY key")],before)
        self.assertEqual([tuple(row) for row in self.engine.db.execute("SELECT * FROM orders ORDER BY id")],orders)
        self.assertEqual([tuple(row) for row in self.engine.db.execute("SELECT * FROM order_fills ORDER BY id")],fills)

    def test_stop_default_full_state_and_http_failure_contract_remain(self):
        expected={"original_full_state":True}
        with patch.object(self.cohort,"state",return_value=expected) as reader:
            self.assertIs(self.cohort.stop(),expected);reader.assert_called_once_with()
        with patch.object(self.cohort,"stop",side_effect=ValueError("SYNTHETIC_STOP_FAILURE")) as stop:
            status,value=self.request("POST","/api/applied/stop")
        self.assertEqual(status,400);self.assertFalse(value["ok"])
        self.assertEqual(value["error"],"SYNTHETIC_STOP_FAILURE");stop.assert_called_once_with(scalar=True)

if __name__=="__main__":unittest.main()


class OrderSnapshotPresentationTests(unittest.TestCase):
    """Only disposable SQLite/local objects; no source, SDK, or model calls."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.engine=Engine(self.temp.name);self.addCleanup(self.engine.close)
        self.engine.account_id="synthetic-1234"

    def seed(self,count=120):
        for i in range(count):
            self.engine.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{i:03}",f"2026-09-28T20:{i//60:02}:{i%60:02}+00:00","synthetic","paper","synthetic-1234","US.AAA","BUY",2,100,"FILLED_ALL","native-"+str(i)))
            self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",(f"{i:03}",json.dumps({"fill_qty":i,"fill_price":100.5,"code":"US.MERGED","nested":{"ref":[i]}})))
        self.engine.db.commit()

    def raw_rows(self):
        return {table:[tuple(row) for row in self.engine.db.execute("SELECT * FROM "+table+" ORDER BY rowid")]
                for table in ("settings","strategies","orders","order_fills","audit")}

    def test_bounded_order_merge_account_order_and_full_state_equivalence(self):
        self.seed();self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",("orphan","INVALID_UNUSED_FILL"));self.engine.db.commit()
        before=self.raw_rows();queries=[];self.engine.db.set_trace_callback(queries.append)
        try:light=self.engine.order_snapshot()
        finally:self.engine.db.set_trace_callback(None)
        self.assertEqual(set(light),{"account_id","orders"});self.assertEqual(light["account_id"],"synthetic-1234")
        self.assertEqual([row["id"] for row in light["orders"]],[f"{i:03}" for i in range(119,19,-1)])
        self.assertEqual([row["fill_qty"] for row in light["orders"]],list(range(119,19,-1)))
        self.assertTrue(all(row["code"]=="US.MERGED" for row in light["orders"]))
        self.assertEqual(len(queries),2);self.assertFalse(any("strategies" in query or "audit" in query for query in queries))
        with patch.object(self.engine,"order_snapshot",wraps=self.engine.order_snapshot) as reader:
            full=self.engine.state()
        reader.assert_called_once_with();self.assertEqual(light,{key:full[key] for key in light})
        self.assertEqual(self.raw_rows(),before)

    def test_snapshots_detach_order_rows_and_nested_fills(self):
        self.seed(1);before=self.raw_rows();first=self.engine.order_snapshot();original=deepcopy(first)
        first["orders"][0]["nested"]["ref"].append("changed");first["orders"][0]["qty"]=999
        first["orders"].append({"fake":True});first["account_id"]="changed"
        self.assertEqual(self.engine.order_snapshot(),original);self.assertEqual(self.raw_rows(),before)
        self.assertEqual(Engine.order_snapshot(self.engine)["account_id"],self.engine.account_id)

    def test_empty_orders_keep_original_fill_decode_and_account_behavior(self):
        self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",("orphan","INVALID_UNUSED_FILL"));self.engine.db.commit()
        with patch("moomoo_component.core.json.loads",side_effect=AssertionError("no fill should decode")):
            self.assertEqual(self.engine.order_snapshot(),{"account_id":"synthetic-1234","orders":[]})

    def test_used_malformed_fill_is_not_hidden_by_light_path(self):
        self.seed(1)
        for payload,error in (("INVALID_JSON",json.JSONDecodeError),("[]",TypeError)):
            with self.subTest(payload=payload):
                self.engine.db.execute("UPDATE order_fills SET payload=?",(payload,));self.engine.db.commit()
                for reader in (self.engine.order_snapshot,self.engine.state):
                    with self.assertRaises(error):reader()

    def test_light_snapshot_respects_the_original_engine_lock(self):
        held=threading.Event();release=threading.Event();started=threading.Event();done=threading.Event();values=[]
        def holder():
            with self.engine.lock:held.set();release.wait(3)
        def read():started.set();values.append(self.engine.order_snapshot());done.set()
        owner=threading.Thread(target=holder);reader=threading.Thread(target=read)
        owner.start();self.assertTrue(held.wait(1))
        try:
            reader.start();self.assertTrue(started.wait(1));self.assertFalse(done.wait(.05))
        finally:release.set();owner.join(2);reader.join(2)
        self.assertTrue(done.is_set());self.assertEqual(values,[{"account_id":"synthetic-1234","orders":[]}])

    def test_best_broker_display_skips_unused_bad_strategy_but_full_state_still_rejects(self):
        from moomoo_component.best_broker import BestBroker
        self.seed(2);runner=BestBroker(self.temp.name,object(),engine=self.engine,now=lambda:OPEN)
        full=self.engine.state()
        with patch.object(self.engine,"order_snapshot",return_value={"account_id":full["account_id"],"orders":deepcopy(full["orders"])}):expected=runner.state()
        self.engine.db.execute("INSERT INTO strategies VALUES (?,?)",("invalid","INVALID_UNUSED_STRATEGY"));self.engine.db.commit()
        before=self.raw_rows()
        with patch.object(self.engine,"state",side_effect=AssertionError("display must not decode unrelated engine state")):
            actual=runner.state()
        self.assertEqual(actual,expected);self.assertEqual(actual["account_id"],"****1234")
        self.assertTrue(all(row["account_id"]=="****1234" for row in actual["orders"]))
        self.assertEqual(self.raw_rows(),before)
        with self.assertRaises(json.JSONDecodeError):Engine.state(self.engine)
        self.assertEqual(runner.snapshot,{});self.assertIsNone(self.engine.broker)
