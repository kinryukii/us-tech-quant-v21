"""Reusable owner-published SIM target alignment; no real SDK, data or clock."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import http.client,json,sqlite3,tempfile,threading,time,unittest
from unittest.mock import patch
from moomoo_component.best_broker import BestBroker,SID
from moomoo_component.core import Engine
from moomoo_component.cohort import Cohort
from moomoo_component.server import LocalServer
from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
import test_best_broker as fixtures
from test_http import FakeLive

R7="R7_GROSS_LINEAR"

class Source(fixtures.FakeSource):
    def __init__(self,opening):
        super().__init__(opening);self.signal="2026-09-25";self.execution="2026-09-28";self.loads=[]
        self.refs={key:{"path":key,"sha256":"a"*64} for key in ("consensus/flags","consensus/pool","consensus/publication","model/R7_GROSS_LINEAR")}
    def status(self,now=None):
        return dict(status="READY",ready=True,signal_date=self.signal,source_date=self.signal,execution_date=self.execution,
            next_open_utc=self.opening.isoformat(),signal_close_utc=self.signal+"T20:00:00+00:00",data_gaps=[],
            next_close_utc=(self.opening+timedelta(hours=6,minutes=30)).isoformat(),candidate_source_scope="PAPER_CANDIDATE_REFS_V1",
            strategy_status={R7:{"status":"READY","signal_date":self.signal}},source_refs={R7+"/"+key:value for key,value in self.refs.items()})
    def close_states(self,books,signal_date):
        out={}
        for sid,book in books.items():
            equity=book["cash"]+sum(qty*100 for qty in book["positions"].values())
            out[sid]=dict(weights={code[3:]:qty*100/equity for code,qty in book["positions"].items()},cash_weight=book["cash"]/equity,
                signal_date=signal_date,valuation_basis="SIGNAL_CLOSE",equity=equity,
                security_ids={code[3:]:"ID_"+code[3:] for code in book["positions"]})
        return out
    def load(self,states,now=None):
        self.loads.append(deepcopy(states));plans={}
        for sid,state in states.items():
            previous=state.get("previous_requested_gross",1.)
            rows=[dict(code="US.OLD",ticker="OLD",security_id="ID_OLD",target_weight=state["weights"].get("OLD",0),
                explicit_target=False,action="HOLD",exact_hold_units=state["units"].get("OLD",0)),
                dict(code="US.KEEP",ticker="KEEP",security_id="ID_KEEP",target_weight=.1,explicit_target=True,action="TARGET")]
            plans[sid]=dict(strategy_id=sid,status="READY",signal_date=self.signal,source_date=self.signal,execution_date=self.execution,
                rows=rows,target_cash_weight=1.-sum(x["target_weight"] for x in rows),source_refs=deepcopy(self.refs),model_fit_calls=0,
                previous_requested_gross=previous,requested_gross=.6,strategy_state_after={"last_signal_date":self.signal,"previous_requested_gross":.6})
        return {**self.status(now),"plans":plans}

class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.opening=datetime(2026,9,28,13,30,tzinfo=timezone.utc);self.now=self.opening-timedelta(minutes=5)
        self.source=Source(self.opening);b=fixtures.FakeBroker
        b.positions,b.submissions={},[];b.cash=1000000.;b.clock=staticmethod(lambda:self.now)
        b.prewarm_calls,b.snapshot_calls,b.quote_errors=[],[],{};b.prewarm_error=None
        b.submit_options,b.before_send_error=[],None;b.reconcile_result,b.reconcile_calls,b.market_prices=None,[],{}
        self.engine=Engine(self.temp.name,broker_factory=b)
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        self.addCleanup(lambda:self.runner.close());self.runner._connect()
        self.runner.bind_strategy(binding_id="bind-r7",requested_at=self.now.isoformat(),expected_strategy_id=SID,
            target_strategy_id=R7,expected_precondition_sha256=self.runner._strategy_binding_precondition(),now=self.now)
        b.positions={"US.OLD":8,"US.KEEP":4};b.cash-=1200
        for code,qty in (("US.OLD",8),("US.KEEP",4)):
            ident="prior-"+code
            self.engine.db.execute("INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ident,"2026-09-24T20:00:00+00:00",SID,"moomoo_simulate","3604",code,"BUY",qty,100,"FILLED","native-"+ident))
            self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",(ident,json.dumps({"fill_qty":qty,"fill_price":100,"fill_fee":0})))
        self.engine.db.commit()
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        self.runner.stop_event.clear();self.runner._prepare(self.now);self.runner.stop_event.set()
        self.normal_raw=self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0]
        self.normal_requested=self.engine.db.execute("SELECT value FROM settings WHERE key='best_requested_strategy_state'").fetchone()[0]
        current=Cohort._book_source_data(R7,self.source.status(self.now))
        self.frozen={key:current[key] for key in ("signal_date","source_date","execution_date","next_open_utc","signal_close_utc","source_refs")}
        self.target=dict(strategy_id=R7,status="READY",signal_date=self.source.signal,source_date=self.source.signal,
            execution_date=self.source.execution,model_fit_calls=0,data_gaps=[],source_refs=deepcopy(self.source.refs),
            rows=[dict(code="US.KEEP",ticker="KEEP",security_id="ID_KEEP",target_weight=.4,explicit_target=True,action="TARGET"),
                  dict(code="US.NEW",ticker="NEW",security_id="ID_NEW",target_weight=.6,explicit_target=True,action="TARGET")],
            target_cash_weight=0.,previous_requested_gross=1.,requested_gross=1.,
            strategy_state_after={"last_signal_date":self.source.signal,"previous_requested_gross":1.})
    def request(self):
        return dict(alignment_id="align-current",requested_at=self.now.isoformat(),expected_strategy_id=R7,
            signal_date=self.source.signal,expected_target_sha256=self.runner._content_sha(self.target),
            expected_precondition_sha256=self.runner._target_alignment_precondition())
    def align(self,request=None):
        req=request or self.request();self.runner.align_published_target(**req,published_plan=self.target,published_metadata=self.frozen,now=self.now);return req
    def tick_at(self,now):
        fixtures.BestBrokerTests.tick_at(self,now)
    def test_alignment_is_owner_bound_differential_and_keeps_raw_previous_plan(self):
        capital=deepcopy(self.engine._get("best_capital",None));positions=deepcopy(self.runner.snapshot["positions"])
        calls=len(self.source.loads);request=self.align()
        self.assertEqual(len(self.source.loads),calls)
        saved=self.engine._get("best_plan",None);rows={x["code"]:x for x in saved["plan"]["rows"]}
        self.assertEqual(rows["US.OLD"]["target_weight"],0)
        self.assertEqual(rows["US.OLD"]["action"],"SELL")
        self.assertAlmostEqual(rows["US.OLD"]["weight_before"],.08)
        self.assertTrue(all(x["explicit_target"] and "exact_hold_units" not in x for x in rows.values()))
        self.assertEqual({x["code"]:x["target_weight"] for x in rows.values() if x["target_weight"]>0},{"US.KEEP":.4,"US.NEW":.6})
        record=self.engine._get("best_published_target_alignment",None)
        self.assertEqual(record["preserved_settings"]["best_plan"],self.normal_raw)
        self.assertEqual(self.engine._get("best_capital",None),capital)
        self.assertEqual(self.runner.snapshot["positions"],positions)
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.assertEqual(self.engine._get("best_requested_strategy_state",None)[R7]["previous_requested_gross"],1.)
        before=self.engine._get("best_plan",None);self.align(request)
        self.assertEqual(self.engine._get("best_plan",None),before)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_ALIGNED'").fetchone()[0],1)
    def test_restart_uses_same_alignment_without_inference_and_only_differences_trade(self):
        self.align();self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        self.runner._connect();self.runner.stop_event.clear()
        self.source.load=lambda *a,**kw:(_ for _ in ()).throw(AssertionError("same signal must not infer"))
        for second in range(1,8):
            self.tick_at(self.opening+timedelta(seconds=second))
            if self.runner.status=="EXECUTED":break
        submissions=fixtures.FakeBroker.submissions
        self.assertEqual(self.runner.status,"EXECUTED",self.runner.last_error)
        self.assertEqual(fixtures.FakeBroker.positions.get("US.OLD",0),0)
        self.assertGreater(fixtures.FakeBroker.positions.get("US.NEW",0),0)
        self.assertGreaterEqual(fixtures.FakeBroker.positions.get("US.KEEP",0),4)
        count=len(submissions)
        self.tick_at(self.opening+timedelta(seconds=8))
        self.assertEqual(len(fixtures.FakeBroker.submissions),count)
        self.assertTrue(any(x["code"]=="US.OLD" and x["side"]=="SELL" and x["qty"]==8 for x in submissions))
        self.assertFalse(any(x["code"]=="US.KEEP" and x["side"]=="SELL" and x["qty"]==4 for x in submissions))
    def test_rollback_restores_bytes_and_requested_state_before_any_submission(self):
        self.align();self.runner.rollback_published_target_alignment(alignment_id="align-current",
            expected_precondition_sha256=self.runner._target_alignment_precondition(),now=self.now)
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],self.normal_raw)
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_requested_strategy_state'").fetchone()[0],self.normal_requested)
        self.assertIsNone(self.engine._get("best_published_target_alignment",None))
        self.assertEqual(fixtures.FakeBroker.positions["US.OLD"],8)
    def test_next_signal_returns_to_normal_strategy_with_last_requested_g_not_realized(self):
        self.align();self.runner.stop_event.clear()
        for second in range(1,9):self.tick_at(self.opening+timedelta(seconds=second))
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"COMPLETED")
        self.source.signal="2026-09-28";self.source.execution="2026-09-29";self.source.opening+=timedelta(days=1)
        self.runner._prepare(self.source.opening-timedelta(minutes=5))
        self.assertEqual(self.source.loads[-1][R7]["previous_requested_gross"],1.)
        self.assertNotIn("published_target_alignment_id",self.runner.plan)
        self.assertTrue(any(row["action"]=="HOLD" for row in self.runner.plan["rows"]))
    def successor_target(self, *, requested=.75):
        self.source.signal=self.source.execution
        self.source.execution=(datetime.fromisoformat(self.source.execution)+timedelta(days=1)).date().isoformat()
        self.source.opening+=timedelta(days=1)
        self.source.refs["consensus/publication"]["sha256"]="c"*64
        target=deepcopy(self.target);target.update(signal_date=self.source.signal,source_date=self.source.signal,
            execution_date=self.source.execution,source_refs=deepcopy(self.source.refs),previous_requested_gross=1.,requested_gross=requested,
            target_cash_weight=1-requested,strategy_state_after={"last_signal_date":self.source.signal,"previous_requested_gross":requested})
        target["rows"][0]["target_weight"]=requested*.4;target["rows"][1]["target_weight"]=requested*.6
        frozen=Cohort._book_source_data(R7,self.source.status(self.source.opening-timedelta(minutes=5)))
        self.runner.published_target_provider=lambda sid,day:dict(plan=deepcopy(target),metadata=deepcopy(frozen))
        return target,frozen

    def test_incomplete_conversion_uses_new_owner_target_on_new_window_without_normal_hold_inference(self):
        self.align();self.runner.stop_event.clear();origin=self.engine._get("best_published_target_alignment",None)
        self.engine._set("best_execution",dict(signal_date=self.source.signal,phase="SELL",skipped=[dict(code="US.OLD",reason="unavailable")]))
        self.tick_at(self.opening+timedelta(seconds=600));self.assertEqual(fixtures.FakeBroker.submissions,[])
        target,frozen=self.successor_target();calls=len(self.source.loads)
        self.runner._prepare(self.source.opening-timedelta(minutes=5))
        rows={row["code"]:row for row in self.runner.plan["rows"]}
        self.assertEqual(rows["US.OLD"]["target_weight"],0);self.assertTrue(rows["US.OLD"]["explicit_target"])
        self.assertTrue(all(row["action"]!="HOLD" for row in rows.values()))
        self.assertEqual(len(self.source.loads),calls);self.assertEqual(self.runner.plan["requested_gross"],.75)
        self.assertEqual(self.runner.metadata["next_open_utc"],frozen["next_open_utc"])
        requested=self.engine._get("best_requested_strategy_state",{})[R7]
        self.assertEqual(requested["previous_requested_gross"],.75);self.assertEqual(requested["previous_input_gross"],1.)
        current=self.engine._get("best_published_target_alignment",{})
        self.assertEqual(current["previous_alignment_id"],origin["request"]["alignment_id"])
        self.assertEqual(current["conversion_id"],"align-current")
        self.assertEqual(self.runner._alignment_record("align-current"),origin)
        self.assertEqual(self.runner._execution_end(),self.source.opening+timedelta(seconds=600))
        raw=self.engine._get("best_plan",None);count=self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_ALIGNED'").fetchone()[0]
        self.runner.published_target_provider=lambda *a:(_ for _ in ()).throw(AssertionError("same signal frozen once"))
        self.runner._prepare(self.source.opening-timedelta(minutes=4))
        self.assertEqual(self.engine._get("best_plan",None),raw)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_ALIGNED'").fetchone()[0],count)
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True)
        self.runner._connect();self.runner.stop_event.clear();self.runner._prepare(self.source.opening-timedelta(minutes=3))
        self.assertEqual(self.runner.plan,raw["plan"]);self.assertEqual(self.engine._get("best_requested_strategy_state",{})[R7],requested)
        for second in range(1,9):self.tick_at(self.source.opening+timedelta(seconds=second))
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"COMPLETED")
        self.assertEqual(fixtures.FakeBroker.positions.get("US.OLD",0),0)
        self.source.signal=self.source.execution;self.source.execution="2026-09-30";self.source.opening+=timedelta(days=1)
        self.runner._prepare(self.source.opening-timedelta(minutes=5))
        self.assertEqual(self.source.loads[-1][R7]["previous_requested_gross"],.75)
        self.assertNotIn("published_target_alignment_id",self.runner.plan)

    def test_incomplete_conversion_waits_for_committed_owner_instead_of_inventing_normal_target(self):
        self.align();self.runner.stop_event.clear();raw=self.engine._get("best_plan",None)
        self.successor_target();self.runner.published_target_provider=lambda *args:None
        calls=len(self.source.loads);requested=deepcopy(self.engine._get("best_requested_strategy_state",{}))
        self.runner._prepare(self.source.opening-timedelta(minutes=5))
        self.assertIsNone(self.runner.plan);self.assertEqual(self.runner.status,"WAITING_SOURCE")
        self.assertIn("统一持仓尚未完成",self.runner.reason);self.assertEqual(len(self.source.loads),calls)
        self.assertEqual(self.engine._get("best_plan",None),raw);self.assertEqual(self.engine._get("best_requested_strategy_state",{}),requested)

    def test_conversion_rejects_requested_g_or_audit_tamper_before_successor_receipt(self):
        self.align();self.runner.stop_event.clear();target,frozen=self.successor_target()
        original=self.engine._get("best_plan",None)
        target["previous_requested_gross"]=.5
        with self.assertRaisesRegex(ValueError,"REQUESTED_G_INPUT_CHANGED"):self.runner._prepare(self.source.opening-timedelta(minutes=5))
        self.assertEqual(self.engine._get("best_plan",None),original)
        state=self.engine._get("best_published_target_conversion",{});state["status"]="COMPLETED";self.engine._set("best_published_target_conversion",state)
        with self.assertRaisesRegex(ValueError,"AUDIT_OR_BINDING_CHANGED"):self.runner._prepare(self.source.opening-timedelta(minutes=4))
        self.assertEqual(fixtures.FakeBroker.submissions,[])

    def test_existing_receipt_conversion_authorization_keeps_plan_orders_and_idempotency(self):
        self.align();self.engine._set("best_published_target_conversion",None)
        self.engine.db.execute("DELETE FROM audit WHERE event='PUBLISHED_TARGET_CONVERSION_AUTHORIZED'");self.engine.db.commit()
        raw=self.engine._get("best_plan",None);orders=deepcopy(self.engine.state()["orders"])
        request=dict(conversion_id="resume-goal",alignment_id="align-current",requested_at=self.now.isoformat(),
            expected_precondition_sha256=self.runner._target_alignment_precondition())
        self.runner.authorize_target_conversion(**request,now=self.now);self.runner.authorize_target_conversion(**request,now=self.now)
        self.assertEqual(self.engine._get("best_plan",None),raw);self.assertEqual(self.engine.state()["orders"],orders)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_CONVERSION_AUTHORIZED'").fetchone()[0],1)
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"ACTIVE")
        self.assertEqual(fixtures.FakeBroker.submissions,[])

    def test_conversion_owner_reads_only_committed_same_signal_plan_snapshot(self):
        from pathlib import Path
        owner=Cohort.__new__(Cohort);owner.path=Path(self.temp.name)/"owner";owner.path.mkdir()
        owner._active_ids=lambda:ACTIVE_PAPER_STRATEGY_IDS
        writer=sqlite3.connect(owner.path/"cohort.sqlite3")
        writer.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        data=dict(plans={R7:deepcopy(self.target)},book_plan_metadata={R7:deepcopy(self.frozen)})
        writer.execute("INSERT INTO settings VALUES ('cohort',?)",(json.dumps(data),));writer.commit()
        try:
            self.assertEqual(owner._published_target_for_conversion(R7,self.source.signal)["plan"],self.target)
            changed=deepcopy(data);changed["plans"][R7]["signal_date"]="2026-09-28"
            changed["book_plan_metadata"][R7]["signal_date"]="2026-09-28"
            writer.execute("UPDATE settings SET value=? WHERE key='cohort'",(json.dumps(changed),))
            self.assertIsNone(owner._published_target_for_conversion(R7,"2026-09-28"))
            writer.commit()
            self.assertIsNotNone(owner._published_target_for_conversion(R7,"2026-09-28"))
            with self.assertRaisesRegex(ValueError,"INACTIVE_OWNER"):owner._published_target_for_conversion("HGB_FACTOR_5","2026-09-28")
        finally:writer.close()

    def test_identity_hash_precondition_stopped_and_current_order_guards(self):
        for case in ("hash","precondition","running","stale_snapshot","submitted"):
            with self.subTest(case=case):
                request=self.request()
                if case=="hash":request["expected_target_sha256"]="b"*64
                if case=="precondition":request["expected_precondition_sha256"]="b"*64
                if case=="running":self.runner.stop_event.clear()
                if case=="stale_snapshot":self.runner.last_snapshot_at-=61
                if case=="submitted":
                    self.engine.db.execute("INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        ("same-signal",self.now.isoformat(),R7,"moomoo_simulate","3604","US.OLD","SELL",1,100,"FILLED","native"));self.engine.db.commit()
                with self.assertRaises(ValueError):self.align(request)
                self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],self.normal_raw)
                self.runner.stop_event.set();self.runner.last_snapshot_at=time.monotonic()
    def test_changed_current_publication_rejects_same_signal_without_inference_or_orders(self):
        self.align();self.runner.stop_event.clear()
        self.source.refs["consensus/publication"]["sha256"]="b"*64
        calls=len(self.source.loads)
        with self.assertRaisesRegex(ValueError,"PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED"):
            self.runner._prepare(self.now)
        self.assertEqual(len(self.source.loads),calls)
        self.assertEqual(fixtures.FakeBroker.submissions,[])

    def test_owner_busy_preserves_plan_and_retries_in_five_seconds_without_early_send(self):
        from moomoo_component.applied_source import DailySourceError
        self.align();self.runner.stop_event.clear()
        old = (self.runner.plan, self.runner.metadata, self.runner.prepared_at)
        raw = self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0]
        with patch.object(self.source,"status",side_effect=DailySourceError("CANONICAL_SOURCE_WORKER_BUSY")), \
                patch("moomoo_component.best_broker.time.monotonic",return_value=1000):
            with self.assertRaises(DailySourceError):self.runner._prepare(self.opening)
        self.assertIs(self.runner.plan,old[0]);self.assertIs(self.runner.metadata,old[1])
        self.assertEqual(self.runner.prepared_at,old[2]);self.assertEqual(self.runner._source_retry_at,1005)
        self.assertTrue(self.runner._source_validation_pending)
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],raw)
        with patch("moomoo_component.best_broker.time.monotonic",return_value=1004), \
                patch.object(self.source,"status",side_effect=AssertionError("too early")):
            self.tick_at(self.opening+timedelta(seconds=1))
        self.assertEqual(self.runner.status,"WAITING_SOURCE");self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.runner.last_error="CANONICAL_SOURCE_WORKER_BUSY";self.engine._set("best_last_error",self.runner.last_error)
        with patch("moomoo_component.best_broker.time.monotonic",return_value=1006), \
                patch.object(self.source,"load",side_effect=AssertionError("same signal must not infer")):
            self.tick_at(self.opening+timedelta(seconds=6))
        self.assertFalse(self.runner._source_validation_pending);self.assertEqual(self.runner.last_error,"")
        self.assertEqual(len(fixtures.FakeBroker.submissions),1)
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],raw)

    def test_busy_recovery_does_not_accept_changed_source_or_extend_window(self):
        from moomoo_component.applied_source import DailySourceError
        self.align();self.runner.stop_event.clear()
        with patch.object(self.source,"status",side_effect=DailySourceError("CANONICAL_SOURCE_WORKER_BUSY")):
            with self.assertRaises(DailySourceError):self.runner._prepare(self.opening)
        self.runner._source_retry_at=0
        self.source.refs["consensus/publication"]["sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED"):
            self.tick_at(self.opening+timedelta(seconds=5))
        self.assertIsNone(self.runner.plan);self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.source.refs["consensus/publication"]["sha256"]="a"*64
        self.tick_at(self.opening+timedelta(seconds=600))
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.assertEqual(self.runner.metadata["next_open_utc"],self.opening.isoformat())
        self.assertEqual(self.runner._execution_end(),self.opening+timedelta(seconds=600))

    def test_current_owner_is_rechecked_after_quote_batch_before_any_send(self):
        from moomoo_component.applied_source import DailySourceError
        self.align();self.runner.stop_event.clear();self.runner._prepare(self.opening)
        raw=self.engine._get("best_plan",None);snapshots=len(fixtures.FakeBroker.snapshot_calls)
        with patch.object(self.source,"status",side_effect=DailySourceError("CANONICAL_SOURCE_WORKER_BUSY")) as status:
            with self.assertRaises(DailySourceError):self.tick_at(self.opening+timedelta(seconds=1))
        status.assert_called_once();self.assertGreater(len(fixtures.FakeBroker.snapshot_calls),snapshots)
        self.assertTrue(self.runner._source_validation_pending);self.assertIsNotNone(self.runner.plan)
        self.assertEqual(fixtures.FakeBroker.submissions,[]);self.assertEqual(self.engine._get("best_plan",None),raw)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM orders WHERE strategy_id=?",(R7,)).fetchone()[0],0)

    def test_source_change_during_quote_batch_stops_before_submission(self):
        self.align();self.runner.stop_event.clear();self.runner._prepare(self.opening)
        raw=self.engine._get("best_plan",None)
        snapshot=fixtures.FakeBroker.snapshot_partial
        def changed(broker,codes):
            result=snapshot(broker,codes)
            self.source.refs["consensus/publication"]["sha256"]="b"*64
            return result
        with patch.object(fixtures.FakeBroker,"snapshot_partial",changed):
            with self.assertRaisesRegex(ValueError,"PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED"):
                self.tick_at(self.opening+timedelta(seconds=1))
        self.assertIsNone(self.runner.plan);self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.assertEqual(self.engine._get("best_plan",None),raw)

    def test_busy_pause_still_reconciles_existing_order_without_amend_or_submit(self):
        self.align();self.runner.stop_event.clear();self.runner._source_validation_pending=True
        self.engine.db.execute("INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("pending",self.opening.isoformat(),R7,"moomoo_simulate","3604","US.OLD","SELL",8,100,"PENDING_RECONCILE","native-pending"))
        self.engine.db.commit()
        with patch.object(self.engine,"reconcile",return_value=[{"status":"SUBMITTED"}]) as reconcile, \
                patch.object(self.runner,"_maybe_reprice_pending",side_effect=AssertionError("amendment must pause")):
            self.tick_at(self.opening+timedelta(seconds=1))
        reconcile.assert_called_once();self.assertEqual(self.runner.status,"PENDING_RECONCILE")
        self.assertEqual(fixtures.FakeBroker.submissions,[])

    def test_alignment_uses_verified_owner_close_without_mutating_caller_metadata(self):
        caller=deepcopy(self.frozen);self.align()
        saved=self.engine._get("best_plan",None)
        self.assertEqual(saved["metadata"]["next_close_utc"],self.source.status()["next_close_utc"])
        self.assertEqual(self.frozen,caller);self.assertNotIn("next_close_utc",self.frozen)
        self.assertEqual(saved["plan"]["published_target_alignment_id"],"align-current")
        self.assertEqual(self.runner._execution_end(),self.opening+timedelta(seconds=600))

    def test_alignment_rejects_missing_or_conflicting_owner_session_close(self):
        status=self.source.status
        for changed in (None,(self.opening+timedelta(days=1)).isoformat(),self.opening.isoformat()):
            with self.subTest(close=changed),patch.object(self.source,"status",side_effect=lambda now=None:{**status(now),"next_close_utc":changed}):
                with self.assertRaisesRegex(ValueError,"CURRENT_SESSION_CLOSE_REQUIRED"):self.align()
                self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],self.normal_raw)
        self.frozen["next_close_utc"]=(self.opening+timedelta(hours=5)).isoformat()
        with self.assertRaisesRegex(ValueError,"CURRENT_SESSION_CLOSE_REQUIRED"):self.align()

    def test_sqlite_failure_rolls_back_entire_transition_without_changing_runtime_plan(self):
        plan=deepcopy(self.runner.plan)
        self.engine.db.execute("CREATE TRIGGER fail_alignment BEFORE INSERT ON settings WHEN NEW.key='best_published_target_alignment' BEGIN SELECT RAISE(ABORT,'synthetic fail'); END;")
        with self.assertRaises(sqlite3.IntegrityError):self.align()
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],self.normal_raw)
        self.assertEqual(self.runner.plan,plan)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_ALIGNED'").fetchone()[0],0)
    def test_http_schema_uses_owner_plan_and_rejects_arbitrary_weights(self):
        outer=self
        class Owner:
            lock=threading.RLock();best_broker=outer.runner;plans={R7:outer.target};plan_metadata=outer.frozen
            meta={"book_plan_metadata":{R7:outer.frozen}}
            def _active_ids(self):return ACTIVE_PAPER_STRATEGY_IDS
            def state(self,*,compact=False):return {"broker":self.best_broker.state()}
        server=LocalServer(0,self.engine,live=FakeLive());server.cohort=Owner()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return outer.now
        def post(body):
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=10)
            conn.request("POST","/api/applied/broker-published-target-alignment",json.dumps(body),
                {"Content-Type":"application/json","X-CSRF-Token":server.token,"Origin":"http://127.0.0.1:"+str(server.server_port)})
            res=conn.getresponse();out=(res.status,json.loads(res.read()));conn.close();return out
        request=self.request()
        with patch("moomoo_component.server.datetime",Clock):
            self.assertEqual(post({**request,"weights":{"US.NEW":1}})[0],400)
            status,response=post(request)
        self.assertEqual(status,200,response)
        self.assertEqual(response["data"]["broker"]["published_target_alignment"]["request"]["alignment_id"],"align-current")

if __name__=="__main__":unittest.main()
