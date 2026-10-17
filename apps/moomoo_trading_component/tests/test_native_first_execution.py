"""Pre2026 synthetic native-first custody/timing tests, no real SDK/data/models."""
from pathlib import Path
from datetime import timedelta
from copy import deepcopy
from contextlib import contextmanager
from unittest.mock import patch
import importlib.util,json,os,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
root=Path(os.environ["NATIVE_FIRST_PROPOSAL_ROOT"]) if os.environ.get("NATIVE_FIRST_PROPOSAL_ROOT") else None
if root:
    for name in ("core","best_broker","server"):
        spec=importlib.util.spec_from_file_location("moomoo_component."+name,root/(name+"_proposed.py"))
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        import moomoo_component
        setattr(moomoo_component,name,module)
from moomoo_component import core as C,best_broker as B
spec=importlib.util.spec_from_file_location("native_reset_fixture",Path(__file__).parents[0]/"fixture_native_reset.py" if root else Path(__file__).with_name("test_native_sim_reset_adoption.py"))
F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)
class NativeFirstTests(unittest.TestCase):
    def setUp(self):
        self.f=F.ResetTests("test_adopt_preserves_raw_namespace_old_ledger_and_no_permission");self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.b=self.f.runner;self.e=self.f.engine;self.s=self.f.source;self.now=F.NOW
        if root:
            self.assertEqual(Path(sys.modules[type(self.b).__module__].__file__).resolve(),(root/"best_broker_proposed.py").resolve())
            self.assertEqual(Path(sys.modules[type(self.e).__module__].__file__).resolve(),(root/"core_proposed.py").resolve())
        original=self.s.load
        def load(*args,**kw):
            value=original(*args,**kw)
            archive=self.f.path/"current-source.json"
            archive.write_text(F.canon({"plans":value["plans"]}),encoding="utf8")
            value["archive"]={"path":str(archive),"sha256":B.hashlib.sha256(archive.read_bytes()).hexdigest()}
            return value
        self.s.load=load;self.f.adopt();self.b.prepare_published_inputs(expected_signal_date="2025-10-13",now=self.now)
        saved=self.e._get("best_plan",{});epoch=self.b._native_reset_record()
        self.request=dict(authorization_id="native_first_once",requested_at=self.now.isoformat(),
            deadline_utc=(self.now+timedelta(seconds=600)).isoformat(),expected_strategy_id=F.RIDGE,
            expected_plan_sha256=self.b._content_sha(saved["plan"]),expected_source_sha256=saved["metadata"]["archive"]["sha256"],
            expected_reset_receipt_sha256=self.b._content_sha(epoch),expected_precondition_sha256=self.b._target_alignment_precondition())
    def grant(self,**changes):return self.b.authorize_native_first_execution(**{**self.request,**changes},now=self.now)
    def make_manifest(self):
        r=self.b._native_first_record();source=dict(kind="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN",signal_date=r["signal_date"],
            phase="BUY",budget=10000,execution_delay_minutes=0,execution_window_seconds=600,
            next_open_utc=r["next_open_utc"],signal_close_utc=r["signal_close_utc"],source_hash=B.hashlib.sha256(json.dumps(self.b.plan["source_refs"],sort_keys=True).encode()).hexdigest(),
            native_first_execution_permission_sha256=self.b._content_sha(r))
        manifest=dict(strategy_id=F.RIDGE,expires_at=r["deadline_utc"],source=json.dumps(source),targets=[{"code":"US.AAA","target_qty":1}])
        self.e._set("best_execution",dict(signal_date=r["signal_date"],phase="BUY",manifest=manifest,
            native_first_execution_permission_sha256=self.b._content_sha(r)))
        return manifest
    def test_authorization_is_separate_finite_idempotent_no_phase_or_start(self):
        old=self.f.prefix();plan=self.f.rawsettings()["best_plan"];ack=self.grant()
        self.assertEqual(ack["orders_created"],0);self.assertFalse(ack["running"])
        self.assertEqual(self.e._get("best_execution",None),{});self.assertTrue(self.b.stop_event.is_set())
        self.assertIsNone(self.e._get("best_first_execution",None));self.assertEqual(self.f.rawsettings()["best_plan"],plan)
        self.assertEqual(self.f.prefix()["orders"],old["orders"])
        self.assertEqual(self.grant()["deadline_utc"],ack["deadline_utc"])
        with self.assertRaisesRegex(ValueError,"NO_RENEWAL"):self.grant(authorization_id="different_once")
    def test_original_core_before_send_seam_checks_native_and_missing_marker(self):
        self.grant();manifest=self.make_manifest()
        self.e._validate_first_execution_manifest(manifest,self.now)
        source=json.loads(manifest["source"]);source.pop("native_first_execution_permission_sha256")
        with self.assertRaisesRegex(ValueError,"MANIFEST_CHANGED"):self.e._validate_first_execution_manifest({**manifest,"source":json.dumps(source)},self.now)
        source["signal_date"]="2025-10-14"
        with self.assertRaisesRegex(ValueError,"SIGNAL_CHANGED"):self.e._validate_first_execution_manifest({**manifest,"source":json.dumps(source)},self.now)
        with self.assertRaisesRegex(ValueError,"EXPIRED"):self.e._validate_first_execution_manifest(manifest,self.now+timedelta(seconds=600))
    def test_unknown_marker_and_ownerless_engine_refused(self):
        self.grant();manifest=self.make_manifest()
        self.e.native_first_execution_validator=None
        with self.assertRaisesRegex(ValueError,"CANONICAL_OWNER"):self.e._validate_first_execution_manifest(manifest,self.now)
        origin=json.loads(manifest["source"]);origin.pop("native_first_execution_permission_sha256")
        with self.assertRaisesRegex(ValueError,"CANONICAL_OWNER"):self.e._validate_first_execution_manifest({**manifest,"source":json.dumps(origin)},self.now)
    def test_binding_or_permission_mutation_refused(self):
        self.grant();manifest=self.make_manifest();before=self.e._get("best_native_first_execution",None)
        for field,value in (("account_id","wrong"),("plan_sha256","b"*64),("deadline_utc",(self.now+timedelta(seconds=601)).isoformat())):
            with self.subTest(field=field):
                self.e._set("best_native_first_execution",{**before,field:value})
                with self.assertRaises(ValueError):self.e._validate_first_execution_manifest(manifest,self.now)
        self.e._set("best_native_first_execution",before)
    def test_request_and_account_guards(self):
        for changes in ({"deadline_utc":(self.now+timedelta(seconds=601)).isoformat()},
                        {"deadline_utc":self.now.isoformat()}, {"requested_at":(self.now+timedelta(seconds=1)).isoformat()},
                        {"requested_at":(self.now-timedelta(seconds=61)).isoformat()},
                        {"expected_strategy_id":F.R7},{"expected_plan_sha256":"f"*64},
                        {"expected_source_sha256":"f"*64},{"expected_reset_receipt_sha256":"f"*64},
                        {"expected_precondition_sha256":"f"*64}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):self.grant(**changes)
                self.assertIsNone(self.e._get("best_native_first_execution",None))
    def test_future_execution_or_closed_market_refused(self):
        for delta in (timedelta(hours=-4),timedelta(hours=4)):
            with self.subTest(delta=delta):
                with self.assertRaises(ValueError):self.b.authorize_native_first_execution(**self.request,now=self.now+delta)
    def test_stale_or_nonflat_snapshot_refused(self):
        original=deepcopy(self.b.snapshot);mono=self.b.last_snapshot_at
        for kind in ("stale","cash","positions","open_orders"):
            with self.subTest(kind=kind):
                self.b.snapshot=deepcopy(original);self.b.last_snapshot_at=mono
                if kind=="stale":self.b.last_snapshot_at=time.monotonic()-61
                elif kind=="cash":self.b.snapshot["cash"]=9999
                elif kind=="positions":self.b.snapshot["positions"]={"US.AAA":{"qty":1}}
                else:self.b.snapshot["open_orders"]=[{"id":"unknown"}]
                with self.assertRaises(ValueError):self.grant()
        self.b.snapshot=original;self.b.last_snapshot_at=mono
    def test_current_epoch_order_or_existing_phase_refused(self):
        self.e._set("best_execution",{"phase":"BUY","signal_date":"2025-10-13"})
        with self.assertRaises(ValueError):self.grant()
        self.e._set("best_execution",{});self.f.order("new-account-order",F.NEW,"US.AAA",1)
        with self.assertRaises(ValueError):self.grant()
    def test_source_or_bootstrap_drift_rejects_before_send(self):
        self.grant();manifest=self.make_manifest();status=self.s.status
        for changes in ({"signal_date":"2025-10-14"},{"next_close_utc":"2025-10-14T20:01:00+00:00"}):
            with self.subTest(changes=changes):
                self.s.status=lambda now=None,changes=changes:{**status(now),**changes}
                with self.assertRaisesRegex(ValueError,"SOURCE_CHANGED"):self.e._validate_first_execution_manifest(manifest,self.now)
    def test_actual_partial_engine_creates_phase_with_permission_marker(self):
        self.grant();self.b.stop_event.clear()
        snap=deepcopy(self.b.snapshot);snap["quotes"]={"US.AAA":dict(price=100,bid=99.99,ask=100.01,asof=self.now.isoformat(),lot_size=1,tradable=True)}
        # Original Engine builds SELL naturally from no phase; no native submission here.
        state=self.b._partial_execution(self.now,"SELL",snap)
        self.assertEqual(state["phase"],"SELL");self.assertIn("native_first_execution_permission_sha256",state)
        state=self.b._partial_execution(self.now,"BUY",snap)
        self.assertTrue(state["manifest"]);self.e._validate_first_execution_manifest(state["manifest"],self.now)
    def test_successor_signal_does_not_inherit_deadline(self):
        self.grant();saved=self.e._get("best_plan",None);saved["metadata"]["signal_date"]="2025-10-14"
        self.e._set("best_plan",saved);self.assertIsNone(self.b._native_first_record())
    def test_quote_batch_crossing_absolute_deadline_creates_no_phase_or_order(self):
        self.grant();self.b.stop_event.clear();snap=deepcopy(self.b.snapshot)
        self.b.engine.broker.snapshot_partial=lambda codes:snap
        self.b._now=lambda:self.now+timedelta(seconds=600)
        self.b._tick_partial(self.now)
        self.assertEqual(self.b.status,"PARTIALLY_EXECUTED")
        self.assertEqual(self.e._get("best_execution",{}),{})
        self.assertFalse(self.e.db.execute("SELECT 1 FROM orders WHERE account_id=?",(F.NEW,)).fetchone())
    def test_http_exact_fields_uses_server_clock_and_never_starts(self):
        from unittest.mock import Mock
        from moomoo_component import server
        source=Path("D:/us-tech-quant/apps/moomoo_trading_component/tests/test_server_configuration.py")
        spec=importlib.util.spec_from_file_location("native_first_http_fixture",source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.CatchupRoutingTests();fixture.setUp()
        owner=Mock(spec=["best_broker"]);broker=Mock(spec=["authorize_native_first_execution","start"])
        broker.authorize_native_first_execution.return_value={"authorized":True};owner.best_broker=broker
        fixture.fixture.cohort=owner
        with patch.object(server,"datetime") as clock:
            clock.now.return_value=self.now
            code,response=fixture.request(self.request,path="/api/applied/broker-native-first-execution")
        self.assertEqual(code,200);broker.authorize_native_first_execution.assert_called_once_with(**self.request,now=self.now)
        broker.start.assert_not_called();broker.authorize_native_first_execution.reset_mock()
        for key in ("account_id","weights","qty","now","budget"):
            with self.subTest(key=key):
                code,response=fixture.request({**self.request,key:1},path="/api/applied/broker-native-first-execution")
                self.assertEqual(code,400)
        broker.authorize_native_first_execution.assert_not_called()
class NativeManualCompletionTests(unittest.TestCase):
    def setUp(self):
        fixture = NativeFirstTests("test_authorization_is_separate_finite_idempotent_no_phase_or_start")
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.f, self.b, self.e, self.s = fixture.f, fixture.b, fixture.e, fixture.s
        self.now = fixture.now + timedelta(days=1)
        old_status = self.s.status
        def status(now=None):
            old = old_status(now)
            return {**old, **{k:(F.datetime.fromisoformat(old[k])+timedelta(days=1)).isoformat()
                for k in ("next_open_utc", "next_close_utc", "signal_close_utc")},
                "signal_date":"2025-10-14", "source_date":"2025-10-14", "execution_date":"2025-10-15"}
        self.s.status = status; self.b._now = lambda:self.now
        # A filled predecessor and live holding are valid; no new-signal phase is invented.
        self.f.order("predecessor-filled", F.NEW, "US.AAA", 2)
        F.Native.native[F.NEW] = dict(cash=9800., equity=10000., positions={"US.AAA":dict(qty=2,sellable=2,market_value=200.)}, open_orders=[])
        self.e.db.commit(); self.e._set("best_execution", dict(signal_date="2025-10-13",phase="BUY",processed_codes=["US.AAA"]))
        self.b.prepare_published_inputs(expected_signal_date="2025-10-14", now=self.now)
        saved = self.e._get("best_plan", {})
        self.request = dict(manual_id="native_manual_once", requested_at=self.now.isoformat(),
            deadline_utc=(self.now+timedelta(seconds=600)).isoformat(), expected_strategy_id=F.RIDGE, signal_date="2025-10-14",
            expected_plan_sha256=self.b._content_sha(saved["plan"]), expected_source_sha256=saved["metadata"]["archive"]["sha256"],
            expected_reset_receipt_sha256=self.b._content_sha(self.b._native_reset_record()), expected_precondition_sha256=self.b._target_alignment_precondition())
    def grant(self, **changes):
        return self.b.authorize_native_manual_completion(**{**self.request, **changes}, now=self.now)
    def manifest(self):
        record = self.b._manual_completion_record()
        origin = dict(kind="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN", signal_date=record["signal_date"], phase="BUY",
            budget=10000, execution_delay_minutes=0, execution_window_seconds=600, next_open_utc=record["next_open_utc"],
            signal_close_utc=record["signal_close_utc"], source_hash=B.hashlib.sha256(json.dumps(self.b.plan["source_refs"],sort_keys=True).encode()).hexdigest(),
            manual_id=record["manual_id"], published_target_manual_completion_sha256=self.b._content_sha(record))
        manifest = dict(strategy_id=F.RIDGE, expires_at=record["deadline_utc"], source=json.dumps(origin), targets=[dict(code="US.AAA",target_qty=3)])
        self.e._set("best_execution",dict(signal_date=record["signal_date"],phase="BUY",manifest=manifest))
        return manifest
    def test_grant_preserves_plan_predecessor_phase_history_and_normal_window(self):
        before = self.f.rawsettings(); orders = self.f.prefix()["orders"]; reads = F.Native.reads
        with patch.object(self.s, "load", side_effect=AssertionError("NO_INFERENCE")), patch.object(self.e.broker, "submit", side_effect=AssertionError("NO_SEND")):
            ack = self.grant()
        self.assertFalse(ack["running"]); self.assertEqual(ack["orders_created"],0); self.assertEqual(F.Native.reads,reads)
        for key in ("best_plan", "best_execution", "execution_window_seconds", "execution_delay_minutes", "best_native_reset_bootstrap"):
            self.assertEqual(self.f.rawsettings()[key],before[key])
        self.assertEqual(self.f.prefix()["orders"],orders); self.assertTrue(self.b.stop_event.is_set())
        self.assertTrue(self.grant()["idempotent"])
        with self.assertRaisesRegex(ValueError,"ONCE_ONLY"): self.grant(manual_id="different_once")
    def test_request_hash_account_snapshot_and_window_guards(self):
        for change in ({"deadline_utc":(self.now+timedelta(seconds=601)).isoformat()}, {"requested_at":(self.now-timedelta(seconds=61)).isoformat()},
                {"expected_strategy_id":F.R7}, {"signal_date":"2025-10-13"}, {"expected_plan_sha256":"b"*64},
                {"expected_source_sha256":"b"*64}, {"expected_reset_receipt_sha256":"b"*64}, {"expected_precondition_sha256":"b"*64}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.grant(**change)
        snapshot = deepcopy(self.b.snapshot)
        for change in ({"funds_only":False}, {"open_orders":[{"unknown":True}]}, {"quotes":{"US.AAA":{}}}, {"cash":float("nan")}):
            self.b.snapshot={**snapshot,**change}
            with self.subTest(change=change), self.assertRaises(ValueError): self.grant()
        self.b.snapshot=snapshot; self.b.last_snapshot_at=time.monotonic()-61
        with self.assertRaises(ValueError): self.grant()
        self.assertIsNone(self.e._get("best_published_target_manual_completion",None))
    def test_existing_current_attempt_or_phase_is_never_cleared(self):
        self.e._set("best_execution",dict(signal_date="2025-10-14",phase="DONE"))
        self.request["expected_precondition_sha256"]=self.b._target_alignment_precondition()
        with self.assertRaisesRegex(ValueError,"ONCE_ONLY"): self.grant()
        self.e._set("best_execution",{})
        self.f.order("today-attempt",F.NEW,"US.AAA",1,status="FAILED")
        self.e.db.execute("UPDATE orders SET created_at=? WHERE id='today-attempt'",(self.now.isoformat(),));self.e.db.commit()
        self.request["expected_precondition_sha256"]=self.b._target_alignment_precondition()
        with self.assertRaisesRegex(ValueError,"ONCE_ONLY"): self.grant()
    def test_successor_manual_ticks_submit_reconcile_sell_buy_once_and_preserve_history(self):
        spec = importlib.util.spec_from_file_location("native_manual_execution_fixture", Path(__file__).with_name("test_best_broker.py"))
        fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        FakeBroker = fixture.FakeBroker
        self.f.order("predecessor-exit", F.NEW, "US.EXIT", 3); self.e.db.commit()
        with patch.multiple(FakeBroker, positions={"US.AAA":2, "US.EXIT":3}, cash=9500.,
                clock=staticmethod(lambda:self.now), submissions=[], submit_options=[], reconcile_calls=[],
                snapshot_calls=[], quote_errors={}, market_prices={}, before_send_error=None, reconcile_result=None):
            with patch.object(self.e, "broker", FakeBroker(account_id=F.NEW)):
                self.b.reconcile()
                self.request["expected_precondition_sha256"] = self.b._target_alignment_precondition()
                before = self.f.prefix(); saved = self.f.rawsettings()["best_plan"]
                self.assertEqual({row[1] for row in before["orders"]}, {"old-buy", "predecessor-filled", "predecessor-exit"})
                self.grant(); permission = self.b._manual_completion_record(); start = self.now
                self.assertEqual(self.e._get("best_execution", {})["signal_date"], "2025-10-13")

                class Clock(F.datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return self.now if tz is None else self.now.astimezone(tz)

                with patch.object(C, "datetime", Clock), patch.object(B, "datetime", Clock), \
                        patch("moomoo_component.strategy.datetime", Clock), \
                        patch.object(self.e, "step", wraps=self.e.step) as step, \
                        patch.object(self.b, "_tick_partial", wraps=self.b._tick_partial) as partial:
                    self.b.stop_event.clear(); self.e.cancel_step.clear()
                    phases = []
                    for second in (1, 2, 3):
                        self.now = start + timedelta(seconds=second)
                        self.b.tick(now=self.now)
                        phases.append(self.e._get("best_execution", {})["phase"])
                    self.assertEqual(phases, ["SELL", "BUY", "DONE"])
                    self.assertEqual(self.b.status, "EXECUTED")
                    self.assertEqual((partial.call_count, step.call_count), (3, 2))
                    self.assertEqual([(row["code"], row["side"]) for row in FakeBroker.submissions],
                        [("US.EXIT", "SELL"), ("US.AAA", "BUY")])
                    self.assertEqual(len(FakeBroker.reconcile_calls), 2)
                    current = self.e._get("best_execution", {})
                    self.assertEqual(FakeBroker.positions["US.EXIT"], 0)
                    self.assertEqual(FakeBroker.positions["US.AAA"], current["target_quantities"]["US.AAA"])
                    for sent, options in zip(FakeBroker.submissions, FakeBroker.submit_options):
                        row = self.e.db.execute("SELECT account_id,status FROM orders WHERE id=?", (sent["client_id"],)).fetchone()
                        self.assertEqual(tuple(row), (F.NEW, "FILLED_ALL"))
                        self.assertTrue(options["allow_partial_quotes"])
                        self.assertEqual(options["execution_deadline_utc"], permission["deadline_utc"])
                    submissions = deepcopy(FakeBroker.submissions); completed = self.f.prefix()
                    self.now = start + timedelta(seconds=4); self.b.tick(now=self.now)
                    self.assertEqual(FakeBroker.submissions, submissions)
                    self.assertEqual(step.call_count, 2)
                    self.assertEqual(self.f.prefix()["orders"], completed["orders"])
                    self.assertEqual(self.f.prefix()["order_fills"], completed["order_fills"])
                after = self.f.prefix()
                for table, rows in before.items():
                    self.assertEqual(after[table][:len(rows)], rows, table)
                self.assertEqual(self.f.rawsettings()["best_plan"], saved)
                self.assertEqual(self.b._manual_completion_record(), permission)

    @contextmanager
    def _partial_native_manual_window(self, *, expired=True):
        spec = importlib.util.spec_from_file_location("native_manual_continuation_fixture", Path(__file__).with_name("test_best_broker.py"))
        fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        FakeBroker = fixture.FakeBroker
        prior_status = self.s.status; self.now += timedelta(days=1)
        def status(now=None):
            old = prior_status(now)
            return {**old, **{k:(F.datetime.fromisoformat(old[k])+timedelta(days=1)).isoformat()
                for k in ("next_open_utc", "next_close_utc", "signal_close_utc")},
                "signal_date":"2025-10-15", "source_date":"2025-10-15", "execution_date":"2025-10-16"}
        self.s.status = status
        self.s.plan_mut = {"target_cash_weight":.2, "rows":[
            dict(code="US.AAA",target_weight=.4,action="TARGET",explicit_target=True),
            dict(code="US.BBB",target_weight=.4,action="TARGET",explicit_target=True)]}
        self.b.prepare_published_inputs(expected_signal_date="2025-10-15", now=self.now)
        saved = self.e._get("best_plan", {})
        self.request.update(signal_date="2025-10-15", requested_at=self.now.isoformat(),
            deadline_utc=(self.now+timedelta(seconds=600)).isoformat(),
            expected_plan_sha256=self.b._content_sha(saved["plan"]), expected_source_sha256=saved["metadata"]["archive"]["sha256"])
        with patch.multiple(FakeBroker, positions={"US.AAA":2}, cash=9800., clock=staticmethod(lambda:self.now),
                submissions=[], submit_options=[], reconcile_calls=[], snapshot_calls=[],
                quote_errors={"US.BBB":"SYNTHETIC_WINDOW_ONE_MISSING_QUOTE"}, market_prices={},
                before_send_error=None, reconcile_result=None):
            with patch.object(self.e, "broker", FakeBroker(account_id=F.NEW)):
                self.b.reconcile(); self.request["expected_precondition_sha256"] = self.b._target_alignment_precondition()
                self.grant(); first = self.b._manual_completion_record(); start = self.now
                class Clock(F.datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return self.now if tz is None else self.now.astimezone(tz)
                with patch.object(C, "datetime", Clock), patch("moomoo_component.strategy.datetime", Clock):
                    self.b.stop_event.clear(); self.e.cancel_step.clear()
                    self.now = start+timedelta(seconds=1); self.b.tick(now=self.now)
                    self.assertEqual([(r["code"],r["side"]) for r in FakeBroker.submissions], [("US.AAA","BUY")])
                    self.e.reconcile()
                    self.assertFalse(self.e._pending())
                    state = self.e._get("best_execution", {})
                    self.assertEqual(state["phase"], "BUY"); self.assertIsNotNone(state["manifest"])
                    self.b.stop(); self.now = start+timedelta(seconds=601 if expired else 3); self.b.reconcile()
                    request = {**self.request, "manual_id":"native_manual_continuation", "requested_at":self.now.isoformat(),
                        "deadline_utc":(self.now+timedelta(seconds=600)).isoformat(),
                        "expected_precondition_sha256":self.b._target_alignment_precondition(),
                        "continuation":{"expected_prior_sha256":self.b._content_sha(first),
                            "expected_execution_sha256":self.b._content_sha(self.e._get("best_execution", {}))}}
                    yield FakeBroker, first, request

    def test_native_manual_continuation_two_windows_send_only_unfinished_buy_once(self):
        with self._partial_native_manual_window() as (FakeBroker, first, request):
            before = self.f.prefix(); state = deepcopy(self.e._get("best_execution", {})); plan = self.f.rawsettings()["best_plan"]
            ack = self.b.authorize_native_manual_completion(**request, now=self.now)
            latest = self.b._manual_completion_record()
            self.assertFalse(ack["running"]); self.assertEqual(ack["orders_created"], 0)
            self.assertEqual(self.e._get("best_execution", {}), state)
            self.assertEqual(self.f.rawsettings()["best_plan"], plan)
            self.assertEqual(latest["prior_manual_id"], first["manual_id"])
            self.assertEqual(latest["prior_manual_sha256"], self.b._content_sha(first))
            self.assertEqual(latest["request"]["continuation"], request["continuation"])
            for table, rows in before.items(): self.assertEqual(self.f.prefix()[table][:len(rows)], rows, table)
            self.assertTrue(self.b.authorize_native_manual_completion(**request, now=self.now)["idempotent"])
            with self.assertRaises(ValueError):
                self.b.authorize_native_manual_completion(**{**request,"deadline_utc":(self.now+timedelta(seconds=599)).isoformat()}, now=self.now)
            unchanged = self.f.rawsettings(); prefix = self.f.prefix()
            with self.assertRaisesRegex(ValueError, "NATIVE_MANUAL_ID_REUSED_OR_SUPERSEDED"):
                self.b.authorize_native_manual_completion(**self.request, now=self.now)
            for name, guard in (("native", self.e._validate_first_execution_manifest),
                    ("manual", self.e._validate_published_manual_completion)):
                with self.subTest(old_manifest_guard=name), self.assertRaises(ValueError):
                    guard(state["manifest"], self.now)
            self.assertEqual(self.f.rawsettings(), unchanged); self.assertEqual(self.f.prefix(), prefix)
            old_audit = self.e.db.execute("SELECT rowid,detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' "
                "AND json_extract(detail,'$.request.manual_id')=?", (first["manual_id"],)).fetchone()
            self.assertIsNotNone(old_audit)
            altered = json.loads(old_audit[1]); altered["deadline_utc"] = (F.datetime.fromisoformat(first["deadline_utc"])+timedelta(seconds=1)).isoformat()
            try:
                self.e.db.execute("UPDATE audit SET detail=? WHERE rowid=?", (json.dumps(altered),old_audit[0])); self.e.db.commit()
                with self.assertRaisesRegex(ValueError, "NATIVE_MANUAL_CONTINUATION_HISTORY_CHANGED"):
                    self.b._manual_completion_record()
            finally:
                self.e.db.execute("UPDATE audit SET detail=? WHERE rowid=?", (old_audit[1],old_audit[0])); self.e.db.commit()
            self.assertEqual(self.f.rawsettings(), unchanged); self.assertEqual(self.f.prefix(), prefix)
            FakeBroker.quote_errors = {}; self.b.stop_event.clear(); self.e.cancel_step.clear()
            self.now += timedelta(seconds=1); self.b.tick(now=self.now)
            rebuilt = self.e._get("best_execution", {})["manifest"]
            self.assertEqual(rebuilt["expires_at"], latest["deadline_utc"])
            self.assertEqual(json.loads(rebuilt["source"])["published_target_manual_completion_sha256"], self.b._content_sha(latest))
            self.assertNotEqual(rebuilt, state["manifest"])
            self.now += timedelta(seconds=1); self.b.tick(now=self.now)
            self.assertEqual(self.b.status, "EXECUTED")
            self.assertEqual(self.e._get("best_execution", {})["phase"], "DONE")
            self.assertEqual([(r["code"],r["side"]) for r in FakeBroker.submissions], [("US.AAA","BUY"),("US.BBB","BUY")])
            self.assertEqual(len(FakeBroker.reconcile_calls), 2)
            completed = self.f.prefix(); submissions = deepcopy(FakeBroker.submissions)
            self.now += timedelta(seconds=1); self.b.tick(now=self.now)
            self.assertEqual(FakeBroker.submissions, submissions)
            self.assertEqual(self.f.prefix()["orders"], completed["orders"])
            self.assertEqual(self.f.prefix()["order_fills"], completed["order_fills"])
            for table, rows in before.items(): self.assertEqual(self.f.prefix()[table][:len(rows)], rows, table)
            self.assertEqual(self.f.rawsettings()["best_plan"], plan)

    def test_native_manual_continuation_rejects_active_prior(self):
        with self._partial_native_manual_window(expired=False) as (_, first, request):
            before = self.f.rawsettings(); prefix = self.f.prefix()
            self.assertLess(self.now, F.datetime.fromisoformat(first["deadline_utc"]))
            with self.assertRaises(ValueError): self.b.authorize_native_manual_completion(**request, now=self.now)
            self.assertEqual(self.f.rawsettings(), before); self.assertEqual(self.f.prefix(), prefix)

    def test_native_manual_continuation_rejects_mutations_done_pending_and_unbound_repeat(self):
        with self._partial_native_manual_window() as (_, first, request):
            before = self.f.rawsettings(); prefix = self.f.prefix()
            changes = ({"manual_id":first["manual_id"]}, {"continuation":None},
                {"continuation":{**request["continuation"],"expected_prior_sha256":"b"*64}},
                {"continuation":{**request["continuation"],"expected_execution_sha256":"b"*64}},
                {"expected_precondition_sha256":"b"*64}, {"expected_plan_sha256":"b"*64},
                {"expected_source_sha256":"b"*64}, {"deadline_utc":(self.now+timedelta(seconds=601)).isoformat()},
                {"deadline_utc":(self.now-timedelta(seconds=1)).isoformat()})
            for change in changes:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.b.authorize_native_manual_completion(**{**request,**change}, now=self.now)
                self.assertEqual(self.f.rawsettings(), before); self.assertEqual(self.f.prefix(), prefix)
            plan = self.b.plan; self.b.plan = {**plan,"target_cash_weight":.3}
            try:
                with self.assertRaises(ValueError): self.b.authorize_native_manual_completion(**request, now=self.now)
            finally: self.b.plan = plan
            original_status = self.s.status
            self.s.status = lambda now=None:{**original_status(now),"next_close_utc":"2025-10-16T20:01:00+00:00"}
            try:
                with self.assertRaises(ValueError): self.b.authorize_native_manual_completion(**request, now=self.now)
            finally: self.s.status = original_status
            state = self.e._get("best_execution", {}); done = {**state,"phase":"DONE","completion_status":"EXECUTED"}
            self.e._set("best_execution", done)
            rejected = {**request,"expected_precondition_sha256":self.b._target_alignment_precondition(),
                "continuation":{**request["continuation"],"expected_execution_sha256":self.b._content_sha(done)}}
            with self.assertRaises(ValueError): self.b.authorize_native_manual_completion(**rejected, now=self.now)
            self.assertEqual(self.e._get("best_execution", {}), done); self.e._set("best_execution", state)
            self.f.order("continuation-pending", F.NEW, "US.BBB", 1, status="SUBMITTED"); self.e.db.commit()
            pending = self.f.prefix(); rejected = {**request,"expected_precondition_sha256":self.b._target_alignment_precondition()}
            with self.assertRaises(ValueError): self.b.authorize_native_manual_completion(**rejected, now=self.now)
            self.assertEqual(self.f.prefix(), pending)
            self.assertEqual(self.e._get("best_published_target_manual_completion", {}), first)

    def test_http_native_manual_continuation_requires_exact_two_hashes_and_never_starts(self):
        from unittest.mock import Mock
        from moomoo_component import server
        spec = importlib.util.spec_from_file_location("native_manual_continuation_http_fixture", Path(__file__).with_name("test_server_configuration.py"))
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        fixture = module.CatchupRoutingTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        owner = Mock(spec=["best_broker"]); broker = Mock(spec=["authorize_native_manual_completion","start"])
        broker.authorize_native_manual_completion.return_value = {"orders_created":0,"running":False}; owner.best_broker = broker; fixture.fixture.cohort = owner
        hashes = {"expected_prior_sha256":"a"*64,"expected_execution_sha256":"b"*64}
        request = {**self.request,"continuation":hashes}
        with patch.object(server,"datetime") as clock:
            clock.now.return_value = self.now
            code, _ = fixture.request(request, path="/api/applied/broker-native-manual-completion")
        self.assertEqual(code, 200); broker.authorize_native_manual_completion.assert_called_once_with(**request,now=self.now)
        for malformed in ({}, {"expected_prior_sha256":"a"*64}, {**hashes,"extra":"c"*64},
                {**hashes,"expected_prior_sha256":"a"*63}, {**hashes,"expected_execution_sha256":"g"*64},
                {**hashes,"expected_execution_sha256":1}, []):
            with self.subTest(malformed=malformed):
                self.assertEqual(fixture.request({**request,"continuation":malformed},path="/api/applied/broker-native-manual-completion")[0],400)
        self.assertEqual(broker.authorize_native_manual_completion.call_count, 1); broker.start.assert_not_called()

    def test_exact_manifest_native_and_manual_core_seams_then_expiry(self):
        self.grant();manifest=self.manifest()
        self.e._validate_first_execution_manifest(manifest,self.now);self.e._validate_published_manual_completion(manifest,self.now)
        origin=json.loads(manifest["source"]);origin.pop("published_target_manual_completion_sha256")
        with self.assertRaises(ValueError):self.e._validate_published_manual_completion({**manifest,"source":json.dumps(origin)},self.now)
        with self.assertRaises(ValueError):self.e._validate_published_manual_completion(manifest,self.now+timedelta(seconds=600))
        self.e.published_target_manual_validator=None
        with self.assertRaisesRegex(ValueError,"OWNER_REQUIRED"):self.e._validate_published_manual_completion(manifest,self.now)
    def test_current_source_drift_restart_and_next_signal_do_not_extend(self):
        self.grant();manifest=self.manifest();old_status=self.s.status
        self.s.status=lambda now=None:{**old_status(now),"next_close_utc":"2025-10-15T20:01:00+00:00"}
        with self.assertRaisesRegex(ValueError,"SOURCE_CHANGED"):self.e._validate_published_manual_completion(manifest,self.now)
        self.s.status=old_status
        deadline=self.b._execution_end();self.b.close()
        self.e=C.Engine(self.f.path/'applied/moomoo-best',broker_factory=F.Native)
        self.b=B.BestBroker(self.e.path,self.s,engine=self.e,now=lambda:self.now,manual_data_updates=True)
        self.f.runner=self.b;self.f.engine=self.e;self.f.owner.best_broker=self.b;self.b._maintenance_owner=self.f.owner
        self.b.reconcile();self.assertEqual(self.b._execution_end(),deadline)
        saved=self.e._get("best_plan",{});saved["metadata"]["signal_date"]="2025-10-15";self.e._set("best_plan",saved)
        self.assertIsNone(self.b._manual_completion_record(saved["plan"],saved["metadata"]))
    def test_quote_return_after_deadline_creates_no_new_phase(self):
        self.grant();old=self.e._get("best_execution",{});snap=deepcopy(self.b.snapshot)
        self.b.stop_event.clear();self.e.broker.snapshot_partial=lambda codes:snap
        self.b._now=lambda:self.now+timedelta(seconds=600)
        self.b._tick_partial(self.now)
        self.assertEqual(self.e._get("best_execution",{}),old);self.assertEqual(self.b.status,"PARTIALLY_EXECUTED")
    def test_http_exact_fields_never_starts(self):
        from unittest.mock import Mock
        from moomoo_component import server
        spec=importlib.util.spec_from_file_location("native_manual_http_fixture",Path(__file__).with_name("test_server_configuration.py"))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=module.CatchupRoutingTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        owner=Mock(spec=["best_broker"]);broker=Mock(spec=["authorize_native_manual_completion","start"])
        broker.authorize_native_manual_completion.return_value={"orders_created":0,"running":False};owner.best_broker=broker;fixture.fixture.cohort=owner
        with patch.object(server,"datetime") as clock:
            clock.now.return_value=self.now;code,response=fixture.request(self.request,path="/api/applied/broker-native-manual-completion")
        self.assertEqual(code,200);broker.authorize_native_manual_completion.assert_called_once_with(**self.request,now=self.now);broker.start.assert_not_called()
        for key in ("account_id","qty","budget","now","weights"):
            with self.subTest(key=key):self.assertEqual(fixture.request({**self.request,key:1},path="/api/applied/broker-native-manual-completion")[0],400)


    def _use_ordinary_manual_clock(self, delay):
        self.b.execution_delay_minutes = delay
        self.e._set("execution_delay_minutes", delay)
        opening = self.b._scheduled_open(self.b.metadata["next_open_utc"])
        self.now = max(self.now, opening + timedelta(seconds=601))
        self.b.last_snapshot_at = time.monotonic()
        self.request.update(requested_at=self.now.isoformat(), deadline_utc=(self.now+timedelta(seconds=600)).isoformat(),
            expected_precondition_sha256=self.b._target_alignment_precondition())

    def test_native_manual_30_clock_is_signed_without_changing_ordinary_plan_or_history(self):
        self._use_ordinary_manual_clock(30)
        before = self.f.rawsettings(); prefix = self.f.prefix()
        ack = self.grant(); record = self.b._manual_completion_record()
        self.assertFalse(ack["running"]); self.assertEqual(ack["orders_created"], 0)
        self.assertEqual(record["ordinary_execution_clock"], dict(execution_delay_minutes=30,
            execution_time_utc=self.b._scheduled_open(self.b.metadata["next_open_utc"]).isoformat(), execution_window_seconds=600))
        for key in ("best_plan", "best_execution", "execution_window_seconds", "execution_delay_minutes", "best_native_reset_bootstrap"):
            self.assertEqual(self.f.rawsettings()[key], before[key])
        self.assertEqual(self.f.prefix()["orders"], prefix["orders"])
        self.assertTrue(self.grant()["idempotent"])
        with self.assertRaises(ValueError): self.grant(manual_id="second_30_window")

    def test_native_manual_30_window_uses_ordinary_end_and_keeps_600_second_cap(self):
        self._use_ordinary_manual_clock(30)
        with self.assertRaises(ValueError): self.grant(deadline_utc=(self.now+timedelta(seconds=601)).isoformat())
        self.now = self.b._scheduled_open(self.b.metadata["next_open_utc"])+timedelta(seconds=599)
        self.request.update(requested_at=self.now.isoformat(), deadline_utc=(self.now+timedelta(seconds=600)).isoformat())
        with self.assertRaises(ValueError): self.grant()
        self.assertIsNone(self.e._get("best_published_target_manual_completion", None))

    def test_native_manual_30_manifest_rechecks_the_signed_ordinary_clock(self):
        self._use_ordinary_manual_clock(30); self.grant()
        record = self.b._manual_completion_record(); manifest = self.manifest()
        origin = json.loads(manifest["source"]); origin.update(record["ordinary_execution_clock"])
        manifest["source"] = json.dumps(origin)
        self.e._set("best_execution", dict(signal_date=record["signal_date"], phase="BUY", manifest=manifest))
        self.e._validate_first_execution_manifest(manifest, self.now)
        self.e._validate_published_manual_completion(manifest, self.now)
        for change in ({"execution_delay_minutes": 0}, {"execution_time_utc": record["next_open_utc"]}):
            changed = {**manifest, "source":json.dumps({**origin, **change})}
            self.e._set("best_execution", dict(signal_date=record["signal_date"], phase="BUY", manifest=changed))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.e._validate_published_manual_completion(changed, self.now)
        self.b.execution_delay_minutes = 0
        with self.assertRaisesRegex(ValueError, "ORDINARY_CLOCK_CHANGED"): self.b._manual_completion_record()

    def test_native_manual_legacy_zero_receipt_stays_verifiable_only_at_its_original_clock(self):
        self.grant(); record = self.b._manual_completion_record()
        self.assertNotIn("ordinary_execution_clock", record)
        self.b.execution_delay_minutes = 30
        with self.assertRaisesRegex(ValueError, "ORDINARY_CLOCK_CHANGED"): self.b._manual_completion_record()
        self.b.execution_delay_minutes = 0
        self.assertEqual(self.b._manual_completion_record(), record)

    def test_native_manual_30_two_windows_send_only_unfinished_buy_once(self):
        self._use_ordinary_manual_clock(30)
        self.test_native_manual_continuation_two_windows_send_only_unfinished_buy_once()


class NewOrdinaryWindowNativeTests(unittest.TestCase):
    setUp = NativeManualCompletionTests.setUp
    grant = NativeManualCompletionTests.grant
    manifest = NativeManualCompletionTests.manifest
    _use_ordinary_manual_clock = NativeManualCompletionTests._use_ordinary_manual_clock

    def use_new_clock(self):
        self.b.execution_delay_minutes = 25
        self.b.execution_window_seconds = 1500
        self.e._set("execution_delay_minutes", 25)
        self.e._set("execution_window_seconds", 1500)
        self._use_ordinary_manual_clock(25)
        opening = self.b._scheduled_open(self.b.metadata["next_open_utc"])
        self.now = opening + timedelta(seconds=1501)
        self.b.last_snapshot_at = time.monotonic()
        self.request.update(requested_at=self.now.isoformat(),deadline_utc=(self.now+timedelta(seconds=600)).isoformat(),
            expected_precondition_sha256=self.b._target_alignment_precondition())

    def test_new_clock_signs_1500_ordinary_but_caps_manual_at_600(self):
        self.use_new_clock()
        original = self.f.rawsettings(); prefix = self.f.prefix()
        with self.assertRaises(ValueError):
            self.grant(deadline_utc=(self.now+timedelta(seconds=601)).isoformat())
        record = self.grant()
        self.assertEqual(record["orders_created"],0)
        permission = self.b._manual_completion_record()
        self.assertEqual(permission["ordinary_execution_clock"]["execution_window_seconds"],1500)
        self.assertEqual((B.timestamp(permission["deadline_utc"])-B.timestamp(permission["authorized_at_utc"])).total_seconds(),600)
        for key in ("best_plan","best_execution","best_native_reset_bootstrap"):
            self.assertEqual(self.f.rawsettings()[key],original[key])
        self.assertEqual(self.f.prefix()["orders"],prefix["orders"])
        self.assertFalse(record["running"])

    def test_new_clock_manual_cannot_start_before_1020(self):
        self.use_new_clock()
        self.now = self.b._scheduled_open(self.b.metadata["next_open_utc"])+timedelta(seconds=1499)
        self.request.update(requested_at=self.now.isoformat(),deadline_utc=(self.now+timedelta(seconds=600)).isoformat())
        with self.assertRaises(ValueError): self.grant()
        self.assertIsNone(self.e._get("best_published_target_manual_completion",None))

    def test_new_clock_manifest_rechecks_ordinary_window_and_never_reuses_old_clock(self):
        self.use_new_clock();self.grant();permission=self.b._manual_completion_record()
        manifest=self.manifest();origin=json.loads(manifest["source"]);origin.update(permission["ordinary_execution_clock"])
        manifest["source"]=json.dumps(origin);self.e._set("best_execution",dict(signal_date=permission["signal_date"],phase="BUY",manifest=manifest))
        self.e._validate_first_execution_manifest(manifest,self.now)
        self.e._validate_published_manual_completion(manifest,self.now)
        changed={**manifest,"source":json.dumps({**origin,"execution_window_seconds":600})}
        self.e._set("best_execution",dict(signal_date=permission["signal_date"],phase="BUY",manifest=changed))
        with self.assertRaises(ValueError):self.e._validate_published_manual_completion(changed,self.now)
        self.b.execution_delay_minutes,self.b.execution_window_seconds=30,600
        with self.assertRaisesRegex(ValueError,"ORDINARY_CLOCK_CHANGED"):self.b._manual_completion_record()

    def assert_completed_signal_clock_history_until_successor(self,delay):
        self._use_ordinary_manual_clock(delay);self.grant()
        permission=deepcopy(self.b._manual_completion_record());before=self.f.rawsettings();prefix=self.f.prefix()
        self.e._set("best_execution",dict(signal_date=permission["signal_date"],phase="DONE",completion_status="EXECUTED"))
        new=B.BestBroker(self.f.path,self.s,engine=self.e,now=lambda:self.now,
            execution_delay_minutes=25,execution_window_seconds=1500,allow_partial_quotes=True,manual_data_updates=True)
        self.assertEqual((new.execution_delay_minutes,new.execution_window_seconds),(delay,600))
        self.assertEqual(new.engine._get("best_next_ordinary_execution_clock", None)["after_signal_date"],permission["signal_date"])
        new.prepare_published_inputs(expected_signal_date=permission["signal_date"],now=self.now)
        self.assertEqual(new._manual_completion_record(),permission)
        self.assertEqual(new._manual_completion_summary()["status"],"COMPLETED")
        self.assertEqual(self.f.rawsettings()["best_plan"],before["best_plan"])
        self.assertEqual(self.f.prefix()["orders"],prefix["orders"])
        previous_status=self.s.status
        def successor(now=None):
            old=previous_status(now)
            return {**old,**{k:(F.datetime.fromisoformat(old[k])+timedelta(days=1)).isoformat()
                for k in ("next_open_utc","next_close_utc","signal_close_utc")},
                "signal_date":"2025-10-15","source_date":"2025-10-15","execution_date":"2025-10-16"}
        self.s.status=successor;self.now+=timedelta(days=1)
        new.prepare_published_inputs(expected_signal_date="2025-10-15",now=self.now)
        self.assertEqual((new.execution_delay_minutes,new.execution_window_seconds),(25,1500))
        self.assertIsNone(self.e._get("best_next_ordinary_execution_clock",None))
        self.assertIsNone(new._manual_completion_record())
        self.assertEqual(self.e._get("best_published_target_manual_completion", None),permission)
        self.assertTrue(any(json.loads(row[0])==permission for row in self.e.db.execute(
            "SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED'")))
        self.assertEqual(self.f.prefix()["orders"],prefix["orders"])

    def test_completed_30_signal_retains_clock_history_until_successor_prepared(self):
        self.assert_completed_signal_clock_history_until_successor(30)

    def test_completed_zero_signal_retains_clock_history_until_successor_prepared(self):
        self.assert_completed_signal_clock_history_until_successor(0)

    def assert_legacy_receipt_cannot_move_to_new_clock(self,delay):
        self._use_ordinary_manual_clock(delay)
        self.grant(manual_id="clock_"+str(delay))
        record=deepcopy(self.b._manual_completion_record())
        self.b.execution_delay_minutes,self.b.execution_window_seconds=25,1500
        with self.assertRaisesRegex(ValueError,"ORDINARY_CLOCK_CHANGED"):self.b._manual_completion_record()
        self.b.execution_delay_minutes,self.b.execution_window_seconds=delay,600
        self.assertEqual(self.b._manual_completion_record(),record)

    def test_legacy_zero_receipt_does_not_authorize_25(self):
        self.assert_legacy_receipt_cannot_move_to_new_clock(0)

    def test_legacy_30_receipt_does_not_authorize_25(self):
        self.assert_legacy_receipt_cannot_move_to_new_clock(30)

if __name__=="__main__":unittest.main()
