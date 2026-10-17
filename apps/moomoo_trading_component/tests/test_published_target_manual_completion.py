"""Synthetic current SIM published-target completion; no real SDK/provider."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import http.client,json,threading,time,unittest
from unittest.mock import patch
from moomoo_component.best_broker import BestBroker
from moomoo_component.server import LocalServer
from test_published_target_alignment import AlignmentTests,R7
from test_http import FakeLive
import test_best_broker as fixtures

class ManualCompletionTests(unittest.TestCase):
    setUp=AlignmentTests.setUp
    request=AlignmentTests.request
    align=AlignmentTests.align
    tick_at=AlignmentTests.tick_at
    def prepare_manual(self):
        self.align()
        self.now=self.opening+timedelta(hours=1)
        self.runner._now=lambda:self.now
        self.engine._set("best_execution",dict(signal_date=self.source.signal,phase="SELL",target_quantities={},processed_codes=[],skipped=[]))
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
    def manual_request(self,ident="manual-1",seconds=600):
        return dict(manual_id=ident,requested_at=self.now.isoformat(),deadline_utc=(self.now+timedelta(seconds=seconds)).isoformat(),
            expected_strategy_id=R7,signal_date=self.source.signal,expected_target_sha256=self.runner._content_sha(self.target),
            expected_precondition_sha256=self.runner._target_alignment_precondition())
    def authorize(self,request=None):
        req=request or self.manual_request()
        self.runner.authorize_manual_published_completion(**req,now=self.now)
        return req
    def test_authorization_keeps_original_plan_phase_and_orders_then_completes_differences(self):
        self.prepare_manual()
        before={key:self.engine.db.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()[0]
            for key in ("best_plan","best_execution","best_published_target_alignment","best_requested_strategy_state")}
        orders=[dict(row) for row in self.engine.db.execute("SELECT * FROM orders")]
        self.authorize()
        for key,value in before.items():self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()[0],value)
        self.assertEqual([dict(row) for row in self.engine.db.execute("SELECT * FROM orders")],orders)
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.runner.stop_event.clear()
        for second in range(1,9):
            self.now=self.opening+timedelta(hours=1,seconds=second);self.tick_at(self.now)
        self.assertEqual(self.runner.status,"EXECUTED",self.runner.last_error)
        self.assertEqual(fixtures.FakeBroker.positions.get("US.OLD",0),0)
        self.assertGreater(fixtures.FakeBroker.positions.get("US.NEW",0),0)
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"COMPLETED")
        self.assertEqual(self.runner.state()["ordinary_execution_deadline_utc"],(self.opening+timedelta(seconds=600)).isoformat())
        for opt in fixtures.FakeBroker.submit_options:
            self.assertNotIn("allow_single_tick_spread",opt);self.assertNotIn("single_sell_spread_bps",opt)
    def test_restart_and_identical_request_never_extend_or_reinfer(self):
        self.prepare_manual();req=self.authorize();record=deepcopy(self.engine._get("best_published_target_manual_completion",None))
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_window_seconds=600,allow_partial_quotes=True,now=lambda:self.now)
        self.runner._connect();self.runner.authorize_manual_published_completion(**req,now=self.now)
        self.assertEqual(self.engine._get("best_published_target_manual_completion",None),record)
        self.source.load=lambda *a,**k:(_ for _ in ()).throw(AssertionError("same signal infer"))
        self.runner.stop_event.clear();self.now+=timedelta(seconds=1);self.tick_at(self.now)
        self.assertTrue(fixtures.FakeBroker.submissions)
        self.assertEqual(self.engine._get("best_requested_strategy_state",{})[R7]["previous_requested_gross"],1.)
    def test_same_id_replay_after_expiry_returns_old_receipt_without_renewal(self):
        self.prepare_manual();req=self.authorize();old=deepcopy(self.engine._get("best_published_target_manual_completion",{}))
        self.now+=timedelta(seconds=601);self.authorize(req)
        self.assertEqual(self.engine._get("best_published_target_manual_completion",{}),old)
        self.assertEqual(self.runner.state()["published_target_manual_completion"]["status"],"EXPIRED")
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        with self.assertRaisesRegex(ValueError,"FRESH_REQUEST_REQUIRED"):
            self.authorize({**req,"manual_id":"manual-2"})

    def test_expiry_does_not_send_and_new_segment_retains_prior_audit(self):
        self.prepare_manual();first=self.authorize(self.manual_request(seconds=2))
        old=deepcopy(self.engine._get("best_published_target_manual_completion",None));self.runner.stop_event.clear()
        self.now+=timedelta(seconds=2);self.tick_at(self.now)
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.runner.stop_event.set();self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        second=self.manual_request("manual-2");self.authorize(second)
        new=self.engine._get("best_published_target_manual_completion",{})
        self.assertEqual(new["previous_manual_receipt_sha256"],self.runner._content_sha(old))
        rows=self.engine.db.execute("SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED'").fetchall()
        self.assertEqual(len(rows),2);self.assertEqual(json.loads(rows[0][0]),old)
        with self.assertRaisesRegex(ValueError,"SUPERSEDED"):self.authorize(first)
    def test_active_segment_cannot_overlap_and_changed_id_request_fails(self):
        self.prepare_manual();req=self.authorize()
        with self.assertRaisesRegex(ValueError,"ALREADY_ACTIVE"):self.authorize(self.manual_request("manual-2"))
        req["deadline_utc"]=(self.now+timedelta(seconds=500)).isoformat()
        with self.assertRaisesRegex(ValueError,"ID_REUSED"):self.authorize(req)
    def test_request_window_identity_account_and_source_guards(self):
        self.prepare_manual();base=self.manual_request()
        cases=[{"deadline_utc":(self.now+timedelta(seconds=601)).isoformat()},
            {"deadline_utc":self.now.isoformat()},{"expected_target_sha256":"b"*64},
            {"expected_precondition_sha256":"b"*64},{"expected_strategy_id":"RAW_A2"},{"signal_date":"2026-09-24"}]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ValueError):self.authorize({**base,**change})
        self.source.refs["consensus/pool"]["sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"SOURCE_BINDING"):self.authorize(base)
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.assertIsNone(self.engine._get("best_published_target_manual_completion",None))
    def test_running_stale_account_open_orders_and_halt_reject(self):
        self.prepare_manual()
        for condition in ("running","stale","open_orders","halt"):
            self.runner.stop_event.set();self.engine.halt_event.clear();self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
            if condition=="running":self.runner.stop_event.clear()
            if condition=="stale":self.runner.last_snapshot_at-=61
            if condition=="open_orders":self.runner.snapshot["open_orders"]=[{"order_id":"pending"}]
            if condition=="halt":self.engine.halt_event.set()
            with self.subTest(condition=condition),self.assertRaises(ValueError):self.authorize()
        self.assertEqual(fixtures.FakeBroker.submissions,[])
    def test_missing_old_close_is_verified_in_new_receipt_only(self):
        self.prepare_manual();saved=self.engine._get("best_plan",{});saved["metadata"].pop("next_close_utc",None)
        record=self.engine._get("best_published_target_alignment",{});record["metadata_sha256"]=self.runner._content_sha(saved["metadata"])
        self.engine._set("best_plan",saved);self.engine._set("best_published_target_alignment",record)
        self.engine.db.execute("UPDATE audit SET detail=? WHERE event='PUBLISHED_TARGET_ALIGNED'",(json.dumps(record,ensure_ascii=False),));self.engine.db.commit()
        self.runner.plan,self.runner.metadata=saved["plan"],saved["metadata"]
        raw=self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0]
        self.authorize()
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0],raw)
        self.assertEqual(self.engine._get("best_published_target_manual_completion",{})["session_close_utc"],self.source.status()["next_close_utc"])
    def test_manifest_tamper_and_missing_owner_fail_closed(self):
        self.prepare_manual();self.authorize();self.runner.stop_event.clear()
        self.now+=timedelta(seconds=1)
        snap=self.engine.broker.snapshot_partial(["US.OLD","US.KEEP","US.NEW"]);self.runner._accept_snapshot(snap)
        state=self.runner._partial_execution(self.now,"SELL",snap);manifest=state["manifest"]
        self.assertIsNotNone(manifest)
        self.runner._manual_manifest_guard(manifest,self.now)
        altered=deepcopy(manifest);altered["expires_at"]=(self.now+timedelta(seconds=1000)).isoformat()
        with self.assertRaises(ValueError):self.runner._manual_manifest_guard(altered,self.now)
        removed=deepcopy(manifest);origin=json.loads(removed["source"]);origin.pop("published_target_manual_completion_sha256");removed["source"]=json.dumps(origin)
        with self.assertRaisesRegex(ValueError,"PERMISSION_REQUIRED"):self.engine._validate_published_manual_completion(removed,self.now)
        self.engine.published_target_manual_validator=None
        with self.assertRaisesRegex(ValueError,"OWNER_REQUIRED"):self.engine._validate_published_manual_completion(manifest,self.now)
        self.assertEqual(fixtures.FakeBroker.submissions,[])
    def test_already_filled_current_sell_is_preserved_and_not_resold(self):
        self.align();self.runner.stop_event.clear()
        self.tick_at(self.opening+timedelta(seconds=1))
        self.assertEqual(fixtures.FakeBroker.positions.get("US.OLD",0),0)
        self.engine.reconcile()
        prefix=[dict(r) for r in self.engine.db.execute("SELECT * FROM orders")]
        fills=[tuple(r) for r in self.engine.db.execute("SELECT * FROM order_fills")]
        self.runner.stop_event.set();self.now=self.opening+timedelta(hours=1);self.runner._now=lambda:self.now
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False));self.authorize()
        self.runner.stop_event.clear()
        for sec in range(1,8):self.tick_at(self.now+timedelta(seconds=sec))
        for row in prefix:self.assertEqual(dict(self.engine.db.execute("SELECT * FROM orders WHERE id=?",(row["id"],)).fetchone()),row)
        for row in fills:self.assertEqual(tuple(self.engine.db.execute("SELECT * FROM order_fills WHERE id=?",(row[0],)).fetchone()),row)
        self.assertEqual(len([x for x in fixtures.FakeBroker.submissions if x["code"]=="US.OLD" and x["side"]=="SELL"]),1)
    def test_done_partial_reopens_only_residuals_and_keeps_previous_record(self):
        self.prepare_manual();self.authorize(self.manual_request(seconds=2));first=deepcopy(self.engine._get("best_published_target_manual_completion",{}))
        done=dict(signal_date=self.source.signal,phase="DONE",completion_status="PARTIALLY_EXECUTED",
            target_quantities={"US.KEEP":4},processed_codes=["US.KEEP"],skipped=[dict(code="US.OLD",reason="bad quote")],deferred_sells=[dict(code="US.OLD",reason="bad quote")])
        self.engine._set("best_execution",done);self.now+=timedelta(seconds=3)
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False));self.authorize(self.manual_request("manual-2"))
        receipt=self.engine._get("best_published_target_manual_completion",{})
        self.assertEqual(receipt["original_execution"],done);self.assertEqual(receipt["previous_manual_receipt_sha256"],self.runner._content_sha(first))
        self.assertEqual(self.engine._get("best_execution",{})["phase"],"BUY")
        self.runner.stop_event.clear()
        for sec in range(1,10):self.tick_at(self.now+timedelta(seconds=sec))
        self.assertEqual(self.runner.status,"EXECUTED",self.runner.last_error)
        self.assertEqual(fixtures.FakeBroker.positions.get("US.OLD",0),0)
        self.assertGreater(fixtures.FakeBroker.positions.get("US.NEW",0),0)
    def test_completed_zero_difference_cannot_reopen(self):
        self.prepare_manual()
        self.runner._now=lambda:self.opening+timedelta(seconds=1)
        self.runner.stop_event.clear();self.tick_at(self.opening+timedelta(seconds=1));self.engine.reconcile()
        self.runner._now=lambda:self.now;self.runner.stop_event.set()
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        self.engine._set("best_execution",dict(signal_date=self.source.signal,phase="DONE",completion_status="PARTIALLY_EXECUTED",
            target_quantities={"US.KEEP":4,"US.NEW":0},processed_codes=[],skipped=[]))
        with self.assertRaisesRegex(ValueError,"NO_REMAINING_DIFFERENCE"):self.authorize()

    def test_http_accepts_only_exact_guard_fields_and_does_not_send(self):
        self.prepare_manual();outer=self
        class Owner:
            best_broker=outer.runner
            def state(self,*,compact=False):return {"broker":self.best_broker.state()}
        server=LocalServer(0,self.engine,live=FakeLive());server.cohort=Owner()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return outer.now
        def post(body):
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=10)
            try:
                conn.request("POST","/api/applied/broker-published-target-manual-completion",body=json.dumps(body),headers={"Content-Type":"application/json","X-CSRF-Token":server.token,"Origin":"http://127.0.0.1:"+str(server.server_port)})
                response=conn.getresponse();payload=json.loads(response.read());return response.status,payload
            finally:conn.close()
        req=self.manual_request()
        with patch("moomoo_component.server.datetime",Clock):
            status,payload=post({**req,"target_weights":{"US.NEW":1}});self.assertEqual(status,400,payload)
            status,payload=post(req);self.assertEqual(status,200,payload)
            self.assertEqual(payload["data"]["broker"]["published_target_manual_completion"]["manual_id"],"manual-1")
        self.assertEqual(fixtures.FakeBroker.submissions,[])

    def test_manual_source_busy_and_quote_batch_deadline_prevent_send(self):
        from moomoo_component.applied_source import DailySourceError
        self.prepare_manual();self.authorize(self.manual_request(seconds=2));self.runner.stop_event.clear()
        with patch.object(self.source,"status",side_effect=DailySourceError("CANONICAL_SOURCE_WORKER_BUSY")):
            with self.assertRaises(DailySourceError):self.tick_at(self.now+timedelta(seconds=1))
        self.assertEqual(fixtures.FakeBroker.submissions,[])
        self.runner._source_retry_at=0
        original=fixtures.FakeBroker.snapshot_partial
        def delayed(broker,codes):
            result=original(broker,codes);self.now+=timedelta(seconds=2);return result
        with patch.object(fixtures.FakeBroker,"snapshot_partial",delayed):self.tick_at(self.now+timedelta(seconds=1))
        self.assertEqual(fixtures.FakeBroker.submissions,[])

    def late_terminal_match(self, *, zero_target=False):
        if zero_target:
            self.target["rows"][1]["target_weight"]-=.000001
            self.target["rows"].append(dict(code="US.ZERO",ticker="ZERO",security_id="ID_ZERO",target_weight=.000001,explicit_target=True,action="TARGET"))
        self.prepare_manual();self.authorize(self.manual_request(seconds=10));self.runner.stop_event.clear()
        base=self.now
        for sec in range(1,4):
            self.now=base+timedelta(seconds=sec);self.tick_at(self.now)
        self.assertEqual(self.engine._get("best_execution",{})["phase"],"BUY")
        self.assertEqual(fixtures.FakeBroker.positions.get("US.OLD",0),0)
        self.now=base+timedelta(seconds=11);self.runner.stop_event.set();self.engine.reconcile()
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
    def test_late_terminal_receipt_closes_exact_targets_without_new_permission_or_order(self):
        self.late_terminal_match()
        old_plan=self.engine._get("best_plan",{});manual=deepcopy(self.engine._get("best_published_target_manual_completion",{}))
        prefix=[dict(r) for r in self.engine.db.execute("SELECT * FROM orders")];fills=[tuple(r) for r in self.engine.db.execute("SELECT * FROM order_fills")]
        self.runner.reconcile()
        state=self.engine._get("best_execution",{})
        self.assertEqual((state["phase"],state["completion_status"]),("DONE","EXECUTED"))
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"COMPLETED")
        self.assertEqual(self.engine._get("best_plan",{}),old_plan);self.assertEqual(self.engine._get("best_published_target_manual_completion",{}),manual)
        self.assertEqual([dict(r) for r in self.engine.db.execute("SELECT * FROM orders")],prefix)
        self.assertEqual([tuple(r) for r in self.engine.db.execute("SELECT * FROM order_fills")],fills)
        count=len(fixtures.FakeBroker.submissions);self.runner.reconcile()
        self.assertEqual(len(fixtures.FakeBroker.submissions),count)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_COMPLETION_ACKNOWLEDGED'").fetchone()[0],1)
    def test_late_confirm_accepts_positive_weight_resolved_zero_integer_target(self):
        self.late_terminal_match(zero_target=True)
        self.assertEqual(self.engine._get("best_execution",{})["target_quantities"]["US.ZERO"],0)
        self.runner.reconcile()
        self.assertEqual(self.engine._get("best_execution",{})["completion_status"],"EXECUTED")
        self.assertNotIn("US.ZERO",fixtures.FakeBroker.positions)
    def test_late_confirm_partial_difference_or_halt_does_not_close(self):
        self.late_terminal_match();original=deepcopy(self.engine._get("best_execution",{}))
        partial=deepcopy(original);partial["target_quantities"]["US.NEW"]+=1;self.engine._set("best_execution",partial)
        self.runner.reconcile();self.assertEqual(self.engine._get("best_execution",{})["phase"],"BUY")
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"ACTIVE")
        self.engine._set("best_execution",original);self.engine.halt_event.set()
        self.runner.reconcile();self.assertEqual(self.engine._get("best_execution",{})["phase"],"BUY")
        self.engine.halt_event.clear();self.now+=timedelta(days=1)
        self.runner.reconcile();self.assertEqual(self.engine._get("best_execution",{})["phase"],"BUY")
    def test_late_confirm_source_or_manifest_mismatch_fails_without_closing(self):
        self.late_terminal_match();original=deepcopy(self.engine._get("best_execution",{}))
        self.source.refs["consensus/pool"]["sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"SOURCE_BINDING"):self.runner.reconcile()
        self.assertEqual(self.engine._get("best_execution",{}),original)
        self.source.refs["consensus/pool"]["sha256"]="a"*64
        altered=deepcopy(original);origin=json.loads(altered["manifest"]["source"]);origin["published_target_manual_completion_sha256"]="b"*64
        altered["manifest"]["source"]=json.dumps(origin);self.engine._set("best_execution",altered)
        with self.assertRaisesRegex(ValueError,"MANUAL_RECEIPT_CHANGED"):self.runner.reconcile()
        self.assertEqual(self.engine._get("best_execution",{}),altered)
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"ACTIVE")
    def test_late_confirm_conversion_audit_failure_rolls_back_done_and_ack(self):
        self.late_terminal_match();before=deepcopy(self.engine._get("best_execution",{}))
        self.engine.db.execute("CREATE TRIGGER fail_complete BEFORE INSERT ON audit WHEN NEW.event='PUBLISHED_TARGET_CONVERSION_STATE' BEGIN SELECT RAISE(ABORT,'atomic close'); END")
        self.engine.db.commit()
        with self.assertRaises(Exception):self.runner.reconcile()
        self.assertEqual(self.engine._get("best_execution",{}),before)
        self.assertEqual(self.engine._get("best_published_target_conversion",{})["status"],"ACTIVE")
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_COMPLETION_ACKNOWLEDGED'").fetchone()[0],0)

    def completed_idle(self):
        self.late_terminal_match();self.runner.reconcile();self.runner.stop_event.clear()
        self.runner._prepare(self.now)
        self.assertTrue(self.runner._closed_current_signal)
        self.runner.metadata["next_refresh_utc"]=(self.opening+timedelta(hours=6,minutes=31)).isoformat()
        self.runner.metadata["next_expected_open_utc"]=(self.opening+timedelta(days=1)).isoformat()
    def test_closed_done_reuses_original_sixty_second_prepare_without_source_or_orders(self):
        self.completed_idle();clock=self.runner.prepared_at
        before=len(fixtures.FakeBroker.submissions);calls=len(fixtures.FakeBroker.snapshot_calls)
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1),patch.object(self.source,"status",wraps=self.source.status) as status:
            for sec in range(1,5):self.tick_at(self.now+timedelta(seconds=sec))
            status.assert_not_called()
        self.assertEqual(len(fixtures.FakeBroker.submissions),before);self.assertEqual(len(fixtures.FakeBroker.snapshot_calls),calls)
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+60),patch.object(self.source,"status",wraps=self.source.status) as status:
            self.tick_at(self.now+timedelta(seconds=60));status.assert_called_once()
    def test_closed_done_refresh_clock_new_day_and_pending_validation_restore_prepare(self):
        self.completed_idle();clock=self.runner.prepared_at;order_count=len(fixtures.FakeBroker.submissions)
        self.runner.metadata["next_refresh_utc"]=self.now.isoformat()
        self.runner.metadata["now_utc"]=(self.now-timedelta(seconds=1)).isoformat()
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1),patch.object(self.source,"status",wraps=self.source.status) as status:
            self.tick_at(self.now);status.assert_called_once()
        self.runner.metadata["next_refresh_utc"]=(self.now+timedelta(days=2)).isoformat();self.runner._source_validation_pending=True;self.runner._source_retry_at=0
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1),patch.object(self.source,"status",wraps=self.source.status) as status:
            self.tick_at(self.now);status.assert_called_once()
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1),patch.object(self.source,"status",wraps=self.source.status) as status:
            self.tick_at(self.now+timedelta(days=1));status.assert_called_once()
        self.assertEqual(len(fixtures.FakeBroker.submissions),order_count)

    def test_closed_done_plan_phase_opening_and_new_manual_never_reuse(self):
        self.completed_idle();saved=self.engine._get("best_plan",{});clock=self.runner.prepared_at
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1):
            self.assertTrue(self.runner._reuse_closed_completed_prepare(saved,self.now))
            old_plan=self.runner.plan;self.runner.plan=deepcopy(old_plan);self.runner.plan["rows"][0]["target_weight"]+=.01
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now));self.runner.plan=old_plan
            refs=self.runner.metadata["source_refs"];self.runner.metadata["source_refs"]={**refs,"known_changed":{"path":"changed","sha256":"b"*64}}
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now));self.runner.metadata["source_refs"]=refs
            self.runner.metadata["data_gaps"]=["known gap"]
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now));self.runner.metadata["data_gaps"]=[]
            self.runner.metadata["next_expected_open_utc"]=self.now.isoformat()
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now))
            self.runner.metadata["next_expected_open_utc"]=(self.now+timedelta(days=1)).isoformat()
            partial=self.engine._get("best_execution",{});partial.update(phase="BUY");self.engine._set("best_execution",partial)
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now))
        self.runner.stop_event.set();self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        self.authorize(self.manual_request("manual-new"))
        self.assertFalse(self.runner._closed_execution(saved,self.now))

    def test_past_refresh_processed_by_successful_owner_check_reuses_only_until_canonical_close(self):
        self.completed_idle();saved=self.engine._get("best_plan",{});clock=self.runner.prepared_at
        self.runner.metadata["next_refresh_utc"]=(self.now-timedelta(days=1)).isoformat()
        self.runner.metadata["now_utc"]=self.now.isoformat()
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1):
            self.assertTrue(self.runner._reuse_closed_completed_prepare(saved,self.now))
            checked=self.runner.metadata.pop("now_utc")
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now));self.runner.metadata["now_utc"]=checked
            self.runner.metadata["now_utc"]=(self.now-timedelta(days=2)).isoformat()
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now))
            closing=datetime.fromisoformat(self.runner.metadata["next_close_utc"])
            self.runner.metadata["now_utc"]=(closing-timedelta(seconds=1)).isoformat()
            self.assertTrue(self.runner._reuse_closed_completed_prepare(saved,closing-timedelta(seconds=1)))
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,closing))
    def test_idle_close_requires_current_same_day_exact_frozen_or_audited_manual_anchor(self):
        self.completed_idle();saved=self.engine._get("best_plan",{});clock=self.runner.prepared_at
        self.runner.metadata["now_utc"]=self.now.isoformat();closing=self.runner.metadata["next_close_utc"]
        with patch("moomoo_component.best_broker.time.monotonic",return_value=clock+1):
            self.runner.metadata["next_close_utc"]=(datetime.fromisoformat(closing)-timedelta(seconds=1)).isoformat()
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now))
            self.runner.metadata["next_close_utc"]=(datetime.fromisoformat(closing)+timedelta(days=1)).isoformat()
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now))
            self.runner.metadata["next_close_utc"]=None
            self.assertFalse(self.runner._reuse_closed_completed_prepare(saved,self.now));self.runner.metadata["next_close_utc"]=closing
            raw=json.dumps(saved,sort_keys=True);manual_raw=json.dumps(self.engine._get("best_published_target_manual_completion",{}),sort_keys=True)
            status=self.source.status
            with patch.object(self.source,"status",side_effect=lambda now=None:{**status(now),"now_utc":self.now.isoformat(),"next_refresh_utc":(self.now+timedelta(hours=1)).isoformat()}):
                self.runner._prepare(self.now)
            self.assertEqual(json.dumps(self.engine._get("best_plan",{}),sort_keys=True),raw)
            self.assertEqual(json.dumps(self.engine._get("best_published_target_manual_completion",{}),sort_keys=True),manual_raw)
            self.assertEqual(self.runner.metadata["next_close_utc"],self.source.status()["next_close_utc"])

    def test_authorization_failure_is_atomic(self):
        self.prepare_manual();before=self.engine._get("best_execution",{})
        self.engine.db.execute("CREATE TRIGGER fail_manual BEFORE INSERT ON audit WHEN NEW.event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' BEGIN SELECT RAISE(ABORT,'test atomic'); END")
        self.engine.db.commit()
        with self.assertRaises(Exception):self.authorize()
        self.assertIsNone(self.engine._get("best_published_target_manual_completion",None))
        self.assertEqual(self.engine._get("best_execution",{}),before)

if __name__=="__main__":unittest.main()
