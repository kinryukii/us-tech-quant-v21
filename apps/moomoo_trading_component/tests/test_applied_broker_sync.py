"""The applied sync route must reach the original strategy account only."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import Mock

from moomoo_component.server import LocalServer


class AppliedBrokerSyncTests(unittest.TestCase):
    def setUp(self):
        self.manual = SimpleNamespace(reconcile=Mock(side_effect=AssertionError("Wrong ledger")))
        self.best = SimpleNamespace(reconcile=Mock(return_value={"running": False, "status": "HALTED", "orders": [{"code": "US.DNA", "dealt_qty": 88, "dealt_avg_price": 11.24, "status": "FILLED_ALL"}]}))
        self.cohort = SimpleNamespace(best_broker=self.best, state=Mock(return_value={"broker": {"running": False}}))
        self.server = LocalServer(0, self.manual, cohort=self.cohort)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post(self, body, token=None, path="/api/applied/reconcile"):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-CSRF-Token": token or self.server.token, "Origin": self.url}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_sync_only_the_original_strategy_account_not_manual_ledger(self):
        code, result = self.post({})
        self.assertEqual(code, 200)
        self.assertEqual(result["data"]["orders"][0]["dealt_qty"], 88)
        self.assertFalse(result["data"]["running"])
        self.best.reconcile.assert_called_once_with()
        self.manual.reconcile.assert_not_called()

    def test_read_state_does_not_issue_broker_queries(self):
        with urllib.request.urlopen(self.url + "/api/applied/state", timeout=2) as response:
            self.assertTrue(json.load(response)["ok"])
        self.best.reconcile.assert_not_called()

    def test_bad_token_cannot_sync(self):
        code, result = self.post({}, token="invalid")
        self.assertEqual(code, 403)
        self.assertFalse(result["ok"])
        self.best.reconcile.assert_not_called()

    def test_sync_cannot_override_account_quantity_or_execution(self):
        code, result = self.post({"account_id": "other", "qty": 100, "start": True})
        self.assertEqual(code, 400)
        self.assertFalse(result["ok"])
        self.best.reconcile.assert_not_called()

    def test_no_strategy_broker_does_not_fall_back_to_manual(self):
        self.cohort.best_broker = None
        code, result = self.post({})
        self.assertEqual(code, 400)
        self.assertFalse(result["ok"])
        self.manual.reconcile.assert_not_called()

    def test_cancel_reset_only_reaches_original_broker_without_starting_paper_books(self):
        self.best.cancel_full_liquidation_reset = Mock(return_value={"status": "STOPPED", "full_liquidation_reset": {}})
        self.best.prepare_current_target_rebalance = Mock(return_value={"status": "STOPPED", "full_liquidation_reset": {}, "mode": "REBALANCE_EXISTING_POSITIONS"})
        code, result = self.post({"reset_id": "HGB_R1_RESET_20261004"}, path="/api/applied/broker-cancel-reset")
        self.assertEqual(code, 200)
        self.assertEqual(result["data"]["full_liquidation_reset"], {})
        self.best.cancel_full_liquidation_reset.assert_called_once()
        args, kwargs = self.best.cancel_full_liquidation_reset.call_args
        self.assertEqual(args, ("HGB_R1_RESET_20261004",))
        self.assertIsNotNone(kwargs["now"].tzinfo)
        self.best.prepare_current_target_rebalance.assert_called_once_with("HGB_R1_RESET_20261004", now=kwargs["now"])
        self.manual.reconcile.assert_not_called()
        self.best.reconcile.assert_not_called()

    def test_cancel_reset_rejects_extra_controls_wrong_identity_and_bad_token(self):
        self.best.cancel_full_liquidation_reset = Mock()
        for body in ({}, {"reset_id": ""}, {"reset_id": "../other"},
                     {"reset_id": "same", "start": True}, {"reset_id": 1}):
            with self.subTest(body=body):
                code, result = self.post(body, path="/api/applied/broker-cancel-reset")
                self.assertEqual(code, 400)
                self.assertFalse(result["ok"])
        code, result = self.post({"reset_id": "same"}, token="invalid", path="/api/applied/broker-cancel-reset")
        self.assertEqual(code, 403)
        self.best.cancel_full_liquidation_reset.assert_not_called()

    def test_cancel_failure_cannot_prepare_or_start_rebalance(self):
        self.best.cancel_full_liquidation_reset = Mock(side_effect=ValueError("RESET_NOT_UNSUBMITTED"))
        self.best.prepare_current_target_rebalance = Mock()
        code, result = self.post({"reset_id": "same"}, path="/api/applied/broker-cancel-reset")
        self.assertEqual(code, 400)
        self.assertFalse(result["ok"])
        self.best.prepare_current_target_rebalance.assert_not_called()

    def test_cancel_reset_requires_original_strategy_broker(self):
        self.cohort.best_broker = None
        code, result = self.post({"reset_id": "same"}, path="/api/applied/broker-cancel-reset")
        self.assertEqual(code, 400)
        self.assertFalse(result["ok"])
        self.manual.reconcile.assert_not_called()


    def test_revise_target_only_prepares_bound_original_broker_without_start(self):
        self.best.revise_current_target_rebalance = Mock(return_value={"status": "STOPPED", "execution_mode": "REBALANCE_EXISTING_POSITIONS"})
        code, result = self.post({"reset_id": "HGB_R1_RESET_20261004", "expected_package_sha256": "a" * 64}, path="/api/applied/broker-revise-target")
        self.assertEqual(code, 200)
        self.assertEqual(result["data"]["status"], "STOPPED")
        args, kwargs = self.best.revise_current_target_rebalance.call_args
        self.assertEqual(args, ("HGB_R1_RESET_20261004", "a" * 64))
        self.assertIsNotNone(kwargs["now"].tzinfo)
        self.manual.reconcile.assert_not_called()
        self.best.reconcile.assert_not_called()

    def test_revise_target_rejects_extra_controls_invalid_binding_and_bad_token(self):
        self.best.revise_current_target_rebalance = Mock()
        valid = {"reset_id": "same", "expected_package_sha256": "a" * 64}
        for body in ({}, {"reset_id": "same"}, {**valid, "start": True},
                     {**valid, "account_id": "other"}, {**valid, "expected_package_sha256": "A" * 64},
                     {**valid, "expected_package_sha256": 1}, {**valid, "reset_id": "../other"}):
            with self.subTest(body=body):
                code, result = self.post(body, path="/api/applied/broker-revise-target")
                self.assertEqual(code, 400)
                self.assertFalse(result["ok"])
        code, result = self.post(valid, token="invalid", path="/api/applied/broker-revise-target")
        self.assertEqual(code, 403)
        self.best.revise_current_target_rebalance.assert_not_called()

    def test_revise_target_requires_original_broker_and_propagates_safe_failure(self):
        valid = {"reset_id": "same", "expected_package_sha256": "a" * 64}
        self.best.revise_current_target_rebalance = Mock(side_effect=ValueError("SOURCE_IDENTITY_CHANGED"))
        code, result = self.post(valid, path="/api/applied/broker-revise-target")
        self.assertEqual(code, 400)
        self.assertFalse(result["ok"])
        self.cohort.best_broker = None
        code, result = self.post(valid, path="/api/applied/broker-revise-target")
        self.assertEqual(code, 400)
        self.manual.reconcile.assert_not_called()

    def configure_revision(self):
        self.cohort.stop_event = threading.Event()
        self.best.stop_event = threading.Event()
        self.cohort.stop_event.set()
        self.best.stop_event.set()
        self.cohort.worker = self.best.worker = None
        self.cohort.revise_hgb_targets = Mock()
        self.best.revise_current_target_rebalance = Mock()
        return {"reset_id": "HGB_R1_RESET_20261004", "expected_package_sha256": "a" * 64}

    def test_combined_revision_prepares_two_books_and_original_broker_at_same_clock(self):
        body = self.configure_revision()
        code, result = self.post(body, path="/api/applied/revise-targets")
        self.assertEqual(code, 200)
        self.assertEqual(result["data"], {"broker": {"running": False}})
        self.cohort.revise_hgb_targets.assert_called_once()
        self.assertEqual(self.cohort.revise_hgb_targets.call_args, self.best.revise_current_target_rebalance.call_args)
        self.assertEqual(self.cohort.revise_hgb_targets.call_args.args, (body["reset_id"], body["expected_package_sha256"]))
        self.best.reconcile.assert_not_called()
        self.manual.reconcile.assert_not_called()

    def test_combined_revision_rejects_running_or_live_worker_without_mutation(self):
        for target in ("cohort", "broker"):
            for state in ("running", "worker"):
                with self.subTest(target=target, state=state):
                    body = self.configure_revision()
                    component = self.cohort if target == "cohort" else self.best
                    if state == "running":
                        component.stop_event.clear()
                    else:
                        component.worker = SimpleNamespace(is_alive=lambda: True)
                    code, result = self.post(body, path="/api/applied/revise-targets")
                    self.assertEqual(code, 400)
                    self.assertFalse(result["ok"])
                    self.cohort.revise_hgb_targets.assert_not_called()
                    self.best.revise_current_target_rebalance.assert_not_called()

    def test_combined_revision_failure_stays_stopped_and_does_not_start_execution(self):
        body = self.configure_revision()
        self.cohort.revise_hgb_targets.side_effect = ValueError("HGB_REVISION_SOURCE_NOT_READY")
        code, result = self.post(body, path="/api/applied/revise-targets")
        self.assertEqual(code, 400)
        self.best.revise_current_target_rebalance.assert_not_called()
        self.assertTrue(self.cohort.stop_event.is_set())
        self.assertTrue(self.best.stop_event.is_set())
        self.cohort.revise_hgb_targets.side_effect = None
        self.best.revise_current_target_rebalance.side_effect = ValueError("PUBLISHED_TARGET_REVISION_SOURCE_INVALID")
        code, result = self.post(body, path="/api/applied/revise-targets")
        self.assertEqual(code, 400)
        self.assertFalse(result["ok"])
        self.assertTrue(self.cohort.stop_event.is_set())
        self.assertTrue(self.best.stop_event.is_set())

    def test_combined_revision_rejects_controls_invalid_binding_and_bad_token(self):
        body = self.configure_revision()
        for invalid in ({}, {**body, "start": True}, {**body, "account_id": "other"},
                        {**body, "expected_package_sha256": "A" * 64}, {**body, "reset_id": "../other"}):
            with self.subTest(body=invalid):
                code, result = self.post(invalid, path="/api/applied/revise-targets")
                self.assertEqual(code, 400)
                self.assertFalse(result["ok"])
        code, result = self.post(body, token="invalid", path="/api/applied/revise-targets")
        self.assertEqual(code, 403)
        self.cohort.revise_hgb_targets.assert_not_called()
        self.best.revise_current_target_rebalance.assert_not_called()


    def test_broker_catchup_explicit_quote_refresh_and_original_two_field_mode(self):
        self.best.authorize_catchup=Mock(return_value={"status":"AUTHORIZED"})
        self.best.engine=SimpleNamespace(account_id="original-account",_get=Mock(return_value="original-account"))
        body={"execution_date":"2026-10-05","deadline_utc":"2026-10-05T15:00:00+00:00"}
        for extra in ({},{"quote_refresh":False},{"quote_refresh":True}):
            self.best.authorize_catchup.reset_mock()
            code,result=self.post({**body,**extra},path="/api/applied/broker-catchup")
            self.assertEqual(code,200)
            self.best.authorize_catchup.assert_called_once()
            args=self.best.authorize_catchup.call_args.kwargs
            self.assertIs(args.get("quote_refresh",False),extra.get("quote_refresh",False))
            self.assertIs(args["include_deferred_sells"],True)
            self.assertEqual(args["account_id"],"original-account")

    def test_broker_catchup_quote_refresh_is_strict_and_cannot_reach_paper_route(self):
        self.best.authorize_catchup=Mock()
        self.best.engine=SimpleNamespace(account_id="original-account",_get=Mock(return_value="original-account"))
        self.cohort.authorize_catchup=Mock()
        body={"execution_date":"2026-10-05","deadline_utc":"2026-10-05T15:00:00+00:00"}
        for value in (1,None,"true",[]):
            with self.subTest(value=value):
                code,result=self.post({**body,"quote_refresh":value},path="/api/applied/broker-catchup")
                self.assertEqual(code,400)
        for invalid in ({**body,"quote_refresh":True,"account_id":"other"},{**body,"qty":1}):
            code,result=self.post(invalid,path="/api/applied/broker-catchup");self.assertEqual(code,400)
        code,result=self.post({**body,"quote_refresh":True},path="/api/applied/catchup")
        self.assertEqual(code,400)
        code,result=self.post({**body,"quote_refresh":True},token="invalid",path="/api/applied/broker-catchup")
        self.assertEqual(code,403)
        self.best.authorize_catchup.assert_not_called();self.cohort.authorize_catchup.assert_not_called()


    def scope_request(self, body, path='/api/applied/catchup-renew'):
        from email.message import Message
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import Mock
        from moomoo_component.server import Handler
        raw = json.dumps(body).encode()
        headers = Message()
        headers['Content-Type'] = 'application/json'
        headers['Content-Length'] = str(len(raw))
        headers['X-CSRF-Token'] = 'synthetic-token'
        broker = SimpleNamespace(renew_catchup=Mock(return_value={}), engine=Mock())
        cohort = SimpleNamespace(renew_catchup=Mock(return_value={}), best_broker=broker)
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = headers
        handler.rfile = BytesIO(raw)
        handler.server = SimpleNamespace(server_port=9876, token='synthetic-token', cohort=cohort, engine=Mock())
        handler._host_ok = lambda: True
        handler._reply = Mock()
        Handler.do_POST(handler)
        return (handler._reply.call_args.args[0], cohort)

    def scope_request_body(self):
        return dict(execution_date='2026-09-29', deadline_utc='2026-09-29T15:00:00+00:00', expected_prior_sha256='a' * 64, renewal_id='synthetic_scope_r1', allowed_codes=['US.KDK'])

    def test_paper_renewal_optional_sixty_is_explicit_and_default_body_unchanged(self):
        for scoped in (False, True):
            body = self.scope_request_body()
            if scoped:
                body['single_sell_spread_bps'] = 60
            code, cohort = self.scope_request(body)
            self.assertEqual(code, 200)
            called = cohort.renew_catchup.call_args.kwargs
            self.assertEqual(set(called), set(body) | {'now'})
            self.assertTrue(all((called[key] == value for key, value in body.items())))
            cohort.best_broker.renew_catchup.assert_not_called()

    def test_paper_spread_field_rejects_wrong_types_codes_broker_route_and_extra_control(self):
        body = self.scope_request_body()
        invalid = [{**body, 'single_sell_spread_bps': value} for value in (50, 61, True, 60.0, '60', None)]
        invalid.extend([{**body, 'single_sell_spread_bps': 60, 'allowed_codes': ['US.OTHER']}, {**body, 'single_sell_spread_bps': 60, 'reset_cash': True}])
        for value in invalid:
            with self.subTest(body=value):
                code, cohort = self.scope_request(value)
                self.assertEqual(code, 400)
                cohort.renew_catchup.assert_not_called()
                cohort.best_broker.renew_catchup.assert_not_called()
        code, cohort = self.scope_request({**body, 'single_sell_spread_bps': 60}, path='/api/applied/broker-catchup-renew')
        self.assertEqual(code, 400)
        cohort.best_broker.renew_catchup.assert_not_called()



    def test_standing_rule_uses_original_owner_and_never_starts_or_trades(self):
        self.cohort.authorize_automatic_completion_policy=Mock(return_value={"enabled":True})
        body={"enabled":True,"close_buffer_seconds":600,"one_tick_spread":True}
        code,result=self.post(body,path="/api/applied/automatic-completion-policy")
        self.assertEqual(code,200)
        call=self.cohort.authorize_automatic_completion_policy.call_args.kwargs
        self.assertEqual({k:v for k,v in call.items() if k!="now"},body)
        self.assertIsNotNone(call["now"].tzinfo)
        self.best.reconcile.assert_not_called();self.manual.reconcile.assert_not_called()

    def test_standing_rule_rejects_account_order_or_window_override_and_bad_token(self):
        self.cohort.authorize_automatic_completion_policy=Mock()
        body={"enabled":True,"close_buffer_seconds":600,"one_tick_spread":True}
        for changes in ({"account_id":"other"},{"start":True},{"qty":100},{"deadline_utc":"tomorrow"},{"parameter":"other"}):
            with self.subTest(changes=changes):
                code,result=self.post({**body,**changes},path="/api/applied/automatic-completion-policy")
                self.assertEqual(code,400)
        code,result=self.post(body,token="invalid",path="/api/applied/automatic-completion-policy")
        self.assertEqual(code,403);self.cohort.authorize_automatic_completion_policy.assert_not_called()


class AutomaticCompletionOwnerTests(unittest.TestCase):
    """Real original Cohort/Engine SQLite authority; only SDK and clocks are fake."""
    def setUp(self):
        import importlib.util
        import tempfile
        import time
        from pathlib import Path
        from moomoo_component.cohort import Cohort
        from moomoo_component.core import Engine
        from moomoo_component.best_broker import BestBroker
        def fixture(name):
            spec=importlib.util.spec_from_file_location("auto_owner_"+name,Path(__file__).with_name(name+".py"))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            return module
        self.ct,self.bt=fixture("test_cohort"),fixture("test_best_broker")
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source,self.quotes=self.ct.Source(),self.ct.Quotes()
        self.c=Cohort(Path(self.temp.name)/"cohort",self.source,self.quotes,
            execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
        self.addCleanup(lambda:self.c.close() if not self.c.closed else None)
        self.c.meta["active_strategy_ids"]=["HGB_DIAG_5","HGB_FACTOR_5"];self.c._persist()
        engine=Engine(Path(self.temp.name)/"best",broker_factory=self.bt.FakeBroker)
        self.b=BestBroker(Path(self.temp.name)/"best",self.bt.FakeSource(self.ct.OPEN),engine=engine,
            execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
        self.bt.FakeBroker.positions={};self.bt.FakeBroker.cash=1000000;self.bt.FakeBroker.submissions=[]
        self.b._connect()
        self.b.stop_event.set();self.b.engine.stop_event.set()
        self.b.snapshot["funds_only"]=True;self.b.snapshot["open_orders"]=[]
        self.b.last_snapshot_at=time.monotonic()
        self.c.best_broker=self.b;self.c._bind_automatic_completion_policy()
        self.clock=self.ct.CLOSE

    def authorize(self,**extra):
        return self.c.authorize_automatic_completion_policy(
            enabled=True,close_buffer_seconds=600,one_tick_spread=True,now=self.clock,**extra)

    def test_original_three_accounts_persist_policy_once_and_reuse_after_restart(self):
        import json
        from datetime import timedelta
        from moomoo_component.cohort import Cohort
        policy=self.authorize()
        self.assertEqual(policy["effective_execution_date"],"2026-09-29")
        self.assertIsNone(self.c.engines["HGB_DIAG_5"]._automatic_completion_policy(self.clock,"HGB_DIAG_5"))
        self.assertEqual(self.authorize(),policy)
        for sid in ("HGB_DIAG_5","HGB_FACTOR_5"):
            e=self.c.engines[sid]
            self.assertEqual(e._automatic_completion_policy(self.ct.OPEN,sid),policy)
            self.assertEqual(e.db.execute("SELECT COUNT(*) FROM audit WHERE event='AUTOMATIC_COMPLETION_POLICY_AUTHORIZED'").fetchone()[0],1)
        self.assertIsNone(self.c.engines["RAW_A2"]._get("automatic_completion_policy",None))
        self.c.close()
        self.c=Cohort(self.c.path,self.source,self.quotes)
        from moomoo_component.core import Engine
        from moomoo_component.best_broker import BestBroker
        from pathlib import Path
        engine=Engine(Path(self.temp.name)/"best",broker_factory=self.bt.FakeBroker)
        self.b=BestBroker(Path(self.temp.name)/"best",self.bt.FakeSource(self.ct.OPEN),engine=engine)
        self.c.best_broker=self.b;self.c._bind_automatic_completion_policy()
        self.assertEqual(self.c._current_automatic_completion_policy(),policy)
        self.assertEqual(self.c.engines["HGB_DIAG_5"]._automatic_completion_policy(self.ct.OPEN,"HGB_DIAG_5"),policy)
        self.assertEqual(self.b.engine._get("automatic_completion_policy",None),policy)
        self.assertEqual(self.bt.FakeBroker.submissions,[])

    def test_projection_or_audit_changes_fail_closed_without_any_order(self):
        from copy import deepcopy
        policy=self.authorize()
        engine=self.c.engines["HGB_DIAG_5"]
        engine._set("automatic_completion_policy",{**policy,"one_tick_spread":False})
        with self.assertRaisesRegex(ValueError,"PROJECTION_CHANGED"):
            engine._automatic_completion_policy(self.ct.OPEN,"HGB_DIAG_5")
        engine._set("automatic_completion_policy",policy)
        engine.db.execute("DELETE FROM audit WHERE event='AUTOMATIC_COMPLETION_POLICY_AUTHORIZED'");engine.db.commit()
        with self.assertRaisesRegex(ValueError,"AUDIT_CHANGED"):
            engine._automatic_completion_policy(self.ct.OPEN,"HGB_DIAG_5")
        self.assertEqual(self.bt.FakeBroker.submissions,[])

    def test_unknown_order_or_running_owner_cannot_issue_authority(self):
        from unittest.mock import patch
        for target in (self.c,self.b):
            target.stop_event.clear()
            with self.assertRaisesRegex(ValueError,"REQUIRES_STOPPED"):
                self.authorize()
            target.stop_event.set()
        with patch.object(self.b.engine,"_pending",return_value=[{"status":"UNKNOWN"}]):
            with self.assertRaisesRegex(ValueError,"UNKNOWN_OR_PENDING"):
                self.authorize()
        self.assertIsNone(self.c._current_automatic_completion_policy())

    def test_failed_projection_write_never_activates_master(self):
        from unittest.mock import patch
        engine=self.c.engines["HGB_FACTOR_5"]
        engine.db.execute("CREATE TRIGGER reject_auto BEFORE INSERT ON settings WHEN NEW.key='automatic_completion_policy' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        engine.db.commit()
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.authorize()
        self.assertIsNone(self.c._current_automatic_completion_policy())
        for sid in ("HGB_DIAG_5","HGB_FACTOR_5"):
            self.assertIsNone(self.c.engines[sid]._get("automatic_completion_policy",None))
        self.assertEqual(self.bt.FakeBroker.submissions,[])

    def test_partial_commit_can_restore_original_master_without_new_authorization(self):
        import sqlite3
        policy=self.authorize()
        engine=self.c.engines["HGB_FACTOR_5"]
        original_db=engine.db
        class FailCommit:
            def __getattr__(self,key):
                return getattr(original_db,key)
            def __enter__(self):
                original_db.__enter__();return self
            def __exit__(self,kind,value,traceback):
                if kind is None:
                    original_db.rollback()
                    raise sqlite3.OperationalError("synthetic COMMIT failed")
                return original_db.__exit__(kind,value,traceback)
        engine.db=FailCommit()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.c.authorize_automatic_completion_policy(enabled=True,
                    close_buffer_seconds=600,one_tick_spread=False,now=self.clock)
        finally:
            engine.db=original_db
        self.assertEqual(self.c._current_automatic_completion_policy(),policy)
        self.assertNotEqual(self.b.engine._get("automatic_completion_policy",None),policy)
        with self.assertRaisesRegex(ValueError,"PROJECTION_CHANGED"):
            self.b.engine._automatic_completion_policy(self.ct.OPEN,"HGB_DIAG_5")
        self.assertEqual(self.authorize(),policy)
        self.assertEqual(self.b.engine._automatic_completion_policy(self.ct.OPEN,"HGB_DIAG_5"),policy)
        self.assertEqual(self.bt.FakeBroker.submissions,[])
        self.assertEqual(self.c.db.execute("SELECT COUNT(*) FROM events WHERE event='AUTOMATIC_COMPLETION_POLICY_PROJECTION_REPAIRED'").fetchone()[0],1)

    def test_disable_original_policy_stops_auto_authority_without_erasing_history(self):
        policy=self.authorize()
        disabled=self.c.authorize_automatic_completion_policy(enabled=False,close_buffer_seconds=600,one_tick_spread=True,now=self.clock)
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["policy_id"],policy["policy_id"])
        for sid in ("HGB_DIAG_5","HGB_FACTOR_5"):
            e=self.c.engines[sid]
            self.assertIsNone(e._automatic_completion_policy(self.ct.OPEN,sid))
            self.assertEqual(e.db.execute("SELECT COUNT(*) FROM audit WHERE event='AUTOMATIC_COMPLETION_POLICY_AUTHORIZED'").fetchone()[0],2)
        self.assertEqual(self.bt.FakeBroker.submissions,[])


if __name__ == "__main__":
    unittest.main()
