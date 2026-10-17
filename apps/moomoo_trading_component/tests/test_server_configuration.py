"""Exercise startup policy routing without opening a broker or server."""
from contextlib import redirect_stdout, redirect_stderr
import io
import unittest
from unittest.mock import patch

from moomoo_component import server


class ServerConfigurationTests(unittest.TestCase):
    def test_invalid_policy_is_rejected_before_engine_or_sdk_creation(self):
        cases = [
            ["--execution-window-seconds", "600"],
            ["--qualified-quotes-only"],
            ["--no-qualified-quotes-only"],
            ["--applied-strategies", "--execution-window-seconds", "0"],
            ["--applied-strategies", "--execution-window-seconds", "601"],
            ["--applied-strategies", "--execution-window-seconds", "1499"],
            ["--applied-strategies", "--execution-window-seconds", "1501"],
            ["--applied-strategies", "--execution-window-seconds", "3600"],
            ["--applied-strategies", "--execution-delay-minutes", "30", "--execution-window-seconds", "1500"],
            ["--applied-strategies", "--execution-delay-minutes", "0", "--execution-window-seconds", "1500"],
            ["--applied-strategies", "--execution-window-seconds", "3601"],
            ["--applied-strategies", "--execution-delay-minutes", "181"],
            ["--broker-execution-window-seconds", "3600"],
            ["--applied-strategies", "--moomoo-best", "--broker-execution-window-seconds", "3601"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), patch("sys.argv", ["component", *arguments]), \
                    patch.object(server, "Engine") as engine, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    server.main()
                self.assertEqual(result.exception.code, 2)
                engine.assert_not_called()

    def _start(self, extra, *, with_broker=True):
        flags = ["--applied-strategies", *( ["--moomoo-best"] if with_broker else [])]
        with patch("sys.argv", ["component", *flags, *extra]), \
                patch.object(server, "Engine"), patch.object(server, "LocalServer") as local, \
                patch("moomoo_component.applied_source.DailySource"), \
                patch("moomoo_component.quotes.MoomooQuoteFeed"), \
                patch("moomoo_component.cohort.Cohort") as cohort, \
                patch("moomoo_component.best_broker.BestBroker") as best, redirect_stdout(io.StringIO()):
            server.main()
            local.return_value.serve_forever.assert_called_once()
            local.return_value.server_close.assert_called_once()
            cohort.return_value.close.assert_called_once()
            return cohort.call_args.kwargs, best.call_args.kwargs if best.called else None, cohort.return_value.start.call_count

    def test_authorized_partial_policy_reaches_both_account_workers(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "45", "--execution-window-seconds", "600",
            "--qualified-quotes-only", "--activate-applied"])
        for policy in (paper, broker):
            self.assertEqual(policy, dict(execution_delay_minutes=45,
                execution_window_seconds=600, allow_partial_quotes=True, manual_data_updates=False))
        self.assertEqual(starts, 1)

    def test_omitted_clock_defaults_to_new_york_0955_1020_without_activation(self):
        paper, broker, starts = self._start([])
        for policy in (paper, broker):
            self.assertEqual(policy, dict(execution_delay_minutes=25,
                execution_window_seconds=1500, allow_partial_quotes=None, manual_data_updates=False))
        self.assertEqual(starts, 0)

    def test_paper_only_start_uses_same_new_york_0955_1020_default(self):
        paper, broker, starts = self._start([], with_broker=False)
        self.assertEqual(paper, dict(execution_delay_minutes=25,
            execution_window_seconds=1500, allow_partial_quotes=None, manual_data_updates=False))
        self.assertIsNone(broker)
        self.assertEqual(starts, 0)

    def test_manual_daily_mode_reaches_both_workers_without_activation(self):
        paper, broker, starts = self._start(["--manual-data-updates"])
        for policy in (paper, broker):
            self.assertIs(policy["manual_data_updates"], True)
            self.assertEqual(policy["execution_delay_minutes"], 25)
        self.assertEqual(starts, 0)

    def test_explicit_shorter_window_is_shared_without_broker_override(self):
        paper, broker, starts = self._start(["--execution-window-seconds", "120"])
        self.assertEqual(paper["execution_window_seconds"], 120)
        self.assertEqual(broker["execution_window_seconds"], 120)
        self.assertEqual(starts, 0)

    def test_explicit_1500_second_window_reaches_both_workers(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "25", "--execution-window-seconds", "1500"])
        for policy in (paper, broker):
            self.assertEqual(policy["execution_delay_minutes"], 25)
            self.assertEqual(policy["execution_window_seconds"], 1500)
        self.assertEqual(starts, 0)

    def test_legacy_paper_window_accepts_inclusive_600_second_limit(self):
        paper, broker, starts = self._start(["--execution-window-seconds", "600"])
        self.assertEqual(paper["execution_window_seconds"], 600)
        self.assertEqual(broker["execution_window_seconds"], 600)
        self.assertEqual(starts, 0)

    def test_explicit_1500_uses_default_twenty_five_minute_delay(self):
        paper, broker, starts = self._start(["--execution-window-seconds", "1500"])
        for policy in (paper, broker):
            self.assertEqual(policy["execution_delay_minutes"], 25)
            self.assertEqual(policy["execution_window_seconds"], 1500)
        self.assertEqual(starts, 0)

    def test_non_default_delay_without_window_keeps_legacy_six_hundred_seconds(self):
        for delay in (0, 30, 45):
            with self.subTest(delay=delay):
                paper, broker, starts = self._start(["--execution-delay-minutes", str(delay)])
                for policy in (paper, broker):
                    self.assertEqual(policy["execution_delay_minutes"], delay)
                    self.assertEqual(policy["execution_window_seconds"], 600)
                self.assertEqual(starts, 0)

    def test_explicit_previous_thirty_minute_clock_and_window_are_preserved(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "30", "--execution-window-seconds", "600"])
        for policy in (paper, broker):
            self.assertEqual(policy["execution_delay_minutes"], 30)
            self.assertEqual(policy["execution_window_seconds"], 600)
        self.assertEqual(starts, 0)

    def test_manual_start_does_not_create_account_workers(self):
        with patch("sys.argv", ["component"]), patch.object(server, "Engine"), \
                patch.object(server, "LocalServer") as local, \
                patch("moomoo_component.cohort.Cohort") as cohort, \
                patch("moomoo_component.best_broker.BestBroker") as best, redirect_stdout(io.StringIO()):
            server.main()
        cohort.assert_not_called()
        best.assert_not_called()
        self.assertIsNone(local.call_args.kwargs["cohort"])

    def test_repository_and_cache_state_destinations_reject_before_engine(self):
        from pathlib import Path
        from scripts.common.storage_paths import resolve
        paths = resolve(Path("D:/us-tech-quant"))
        for invalid in (paths.repo_root / "runtime", paths.cache_root / "paper", paths.data_root / "paper", paths.daily_root):
            with self.subTest(path=invalid), patch("sys.argv", ["component", "--data-dir", str(invalid)]), \
                    patch.object(server, "Engine") as engine, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    server.main()
                engine.assert_not_called()

    def test_open_policy_reaches_both_workers(self):
        paper, broker, starts = self._start(["--execution-delay-minutes", "0", "--activate-applied"])
        self.assertEqual(paper["execution_delay_minutes"], 0)
        self.assertEqual(broker["execution_delay_minutes"], 0)
        self.assertEqual(starts, 1)

    def test_noon_policy_reaches_both_workers(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "150", "--execution-window-seconds", "600",
            "--qualified-quotes-only", "--activate-applied"])
        for policy in (paper, broker):
            self.assertEqual(policy, dict(execution_delay_minutes=150,
                execution_window_seconds=600, allow_partial_quotes=True, manual_data_updates=False))
        self.assertEqual(starts, 1)

    def test_broker_window_does_not_change_three_paper_accounts(self):
        paper, broker, starts = self._start([
            "--execution-delay-minutes", "150", "--execution-window-seconds", "600",
            "--broker-execution-window-seconds", "3600",
            "--qualified-quotes-only", "--activate-applied"])
        self.assertEqual(paper["execution_window_seconds"], 600)
        self.assertEqual(broker["execution_window_seconds"], 3600)
        self.assertEqual(starts, 1)


class CatchupRoutingTests(unittest.TestCase):
    """Exercise the real HTTP handler with fake streams and no socket or SDK."""

    def setUp(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        self.cohort = Mock(spec=["authorize_catchup", "start", "stop", "halt", "state", "best_broker"])
        self.cohort.authorize_catchup.return_value = {"status": "AUTHORIZED", "automatic_execution_started": False}
        self.engine = Mock()
        self.live = Mock()
        self.fixture = SimpleNamespace(server_port=8766, token="paper-test-token",
            live_token="live-test-token", cohort=self.cohort, engine=self.engine, live=self.live)
        self.valid_body = {"execution_date": "2026-10-01", "deadline_utc": "2026-10-01T14:05:00+00:00"}

    def request(self, body, *, path="/api/applied/catchup", headers=None, raw=False):
        import json
        from email.message import Message
        payload = body if raw else json.dumps(body)
        encoded = payload.encode("utf-8")
        request_headers = {"Host": "127.0.0.1:8766", "Content-Type": "application/json",
            "Content-Length": str(len(encoded)), "X-CSRF-Token": self.fixture.token}
        request_headers.update(headers or {})
        handler = server.Handler.__new__(server.Handler)
        handler.server, handler.path = self.fixture, path
        handler.headers = Message()
        for key, value in request_headers.items():
            handler.headers[key] = value
        handler.rfile = io.BytesIO(encoded)
        replies = []
        handler._reply = lambda code, response, **kwargs: replies.append((code, response))
        handler.do_POST()
        self.assertEqual(len(replies), 1)
        self.engine.assert_not_called()
        self.assertEqual(self.engine.mock_calls, [])
        self.assertEqual(self.live.mock_calls, [])
        return replies[0]

    def test_catchup_passes_exact_arguments_and_server_utc_clock_without_start(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 1, 13, 55, 10, tzinfo=timezone.utc)
        with patch.object(server, "datetime") as clock:
            clock.now.return_value = now
            code, response = self.request(self.valid_body)
            clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(code, 200)
        self.assertEqual(response, {"ok": True, "data": self.cohort.authorize_catchup.return_value})
        self.cohort.authorize_catchup.assert_called_once_with(**self.valid_body, now=now)
        self.cohort.start.assert_not_called()
        self.cohort.stop.assert_not_called()
        self.cohort.halt.assert_not_called()
        self.cohort.best_broker.reconcile.assert_not_called()

    def test_catchup_rejects_missing_extra_and_injected_authority_fields(self):
        invalid = [{}, {"execution_date": "2026-10-01"},
            {"deadline_utc": self.valid_body["deadline_utc"]}]
        invalid += [{**self.valid_body, key: value} for key, value in (
            ("account_id", "other-account"), ("budget", 1), ("force", True),
            ("now", "2026-10-01T13:55:00+00:00"), ("prices", {}), ("targets", []),
            ("mode", "real"), ("strategy_id", "OTHER"))]
        for body in invalid:
            with self.subTest(keys=sorted(body)):
                code, response = self.request(body)
                self.assertEqual(code, 400)
                self.assertFalse(response["ok"])
        self.cohort.authorize_catchup.assert_not_called()
        self.cohort.start.assert_not_called()

    def test_catchup_rejects_non_string_arguments_and_non_object_json(self):
        invalid = [[], None, "2026-10-01"]
        for key in self.valid_body:
            invalid += [{**self.valid_body, key: value} for value in (None, False, 600, 0.5, {}, [])]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.request(body)[0], 400)
        self.assertEqual(self.request('{"execution_date":"2026-10-01","deadline_utc":NaN}', raw=True)[0], 400)
        self.cohort.authorize_catchup.assert_not_called()

    def test_original_stopped_source_and_time_guards_propagate_without_execution(self):
        reasons = ("worker still active", "halt preserved", "frozen source changed",
                   "signal date mismatch", "not same NY session", "window exceeds ten minutes",
                   "pending broker order", "original ledger is not qualified quotes only")
        for reason in reasons:
            with self.subTest(reason=reason):
                self.cohort.authorize_catchup.side_effect = ValueError(reason)
                code, response = self.request(self.valid_body)
                self.assertEqual(code, 400)
                self.assertEqual(response, {"ok": False, "error": reason})
        self.assertEqual(self.cohort.authorize_catchup.call_count, len(reasons))
        self.cohort.start.assert_not_called()
        self.cohort.best_broker.reconcile.assert_not_called()

    def test_missing_cohort_fails_without_generic_engine_fallback(self):
        self.fixture.cohort = None
        self.assertEqual(self.request(self.valid_body)[0], 400)
        self.cohort.authorize_catchup.assert_not_called()

    def test_wrong_token_origin_fetch_site_or_host_rejects_before_authorization(self):
        invalid_headers = ({"X-CSRF-Token": ""}, {"X-CSRF-Token": "wrong"},
            {"X-CSRF-Token": self.fixture.live_token}, {"Origin": "https://attacker.test"},
            {"Sec-Fetch-Site": "cross-site"}, {"Host": "attacker.test"})
        for headers in invalid_headers:
            with self.subTest(headers=headers):
                self.assertEqual(self.request(self.valid_body, headers=headers)[0], 403)
        self.cohort.authorize_catchup.assert_not_called()
        self.cohort.start.assert_not_called()

    def test_same_origin_request_uses_only_paper_token(self):
        code, _ = self.request(self.valid_body, headers={"Origin": "http://127.0.0.1:8766"})
        self.assertEqual(code, 200)
        self.cohort.authorize_catchup.assert_called_once()

    def test_live_catchup_is_forbidden_with_either_token(self):
        for token in (self.fixture.token, self.fixture.live_token):
            with self.subTest(token=token):
                code, _ = self.request(self.valid_body, path="/api/live/catchup", headers={"X-CSRF-Token": token})
                self.assertEqual(code, 403)
        self.cohort.authorize_catchup.assert_not_called()

    def test_non_json_or_transfer_encoding_rejects_before_authorization(self):
        self.assertEqual(self.request(self.valid_body, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request(self.valid_body, headers={"Transfer-Encoding": "chunked"})[0], 413)
        self.cohort.authorize_catchup.assert_not_called()

    def test_other_applied_controls_still_reject_nonempty_body(self):
        for action in ("start", "stop", "halt", "reconcile"):
            with self.subTest(action=action):
                self.assertEqual(self.request(self.valid_body, path="/api/applied/" + action)[0], 400)
        self.cohort.start.assert_not_called()
        self.cohort.stop.assert_not_called()
        self.cohort.halt.assert_not_called()
        self.cohort.best_broker.reconcile.assert_not_called()

    def test_existing_empty_control_body_remains_compatible(self):
        for action in ("start", "stop", "halt", "reconcile"):
            method = self.cohort.best_broker.reconcile if action == "reconcile" else getattr(self.cohort, action)
            method.return_value = {"status": "STOPPED", "automatic_execution_started": False}
            with self.subTest(action=action):
                code, response = self.request({}, path="/api/applied/" + action)
                self.assertEqual(code, 200)
                self.assertTrue(response["ok"])
                # The existing stop route returns only its bounded control receipt.
                method.assert_called_once_with(**({"scalar": True} if action == "stop" else {}))
        self.cohort.authorize_catchup.assert_not_called()


class BrokerCatchupRoutingTests(unittest.TestCase):
    """Reuse the socket-free handler fixture; the original broker binding is synthetic."""
    def setUp(self):
        CatchupRoutingTests.setUp(self)
        self.valid_body["deadline_utc"] = "2026-10-01T14:50:00+00:00"
        self.best = self.cohort.best_broker
        self.best.engine._get.return_value = "original-simulate-account"
        self.best.authorize_catchup.return_value = {"status":"AUTHORIZED", "automatic_execution_started":False}

    def request(self, body, *, path="/api/applied/broker-catchup", headers=None, raw=False):
        result = CatchupRoutingTests.request(self,body,path=path,headers=headers,raw=raw)
        for owner in (self.cohort,self.best):
            for action in ("start","stop","halt"):
                getattr(owner,action).assert_not_called()
        self.cohort.authorize_catchup.assert_not_called()
        self.best.reconcile.assert_not_called()
        self.best.tick.assert_not_called()
        self.best.engine.connect.assert_not_called()
        self.best.engine.step.assert_not_called()
        return result

    def test_broker_catchup_binds_original_account_server_actual_utc_and_deferred_sell_permission(self):
        from datetime import datetime,timezone
        now=datetime(2026,10,1,14,40,5,tzinfo=timezone.utc)
        with patch.object(server,"datetime") as clock:
            clock.now.return_value=now
            code,response=self.request(self.valid_body)
            clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(code,200)
        self.assertEqual(response,{"ok":True,"data":self.best.authorize_catchup.return_value})
        self.best.engine._get.assert_called_once_with("best_account",None)
        self.best.authorize_catchup.assert_called_once_with(**self.valid_body,
            account_id="original-simulate-account",include_deferred_sells=True,now=now)

    def test_client_account_budget_price_target_clock_and_real_authority_injections_are_rejected(self):
        invalid=[{}, {"execution_date":self.valid_body["execution_date"]},
                 {"deadline_utc":self.valid_body["deadline_utc"]}]
        invalid += [{**self.valid_body,key:value} for key,value in (
            ("account_id","other-account"),("budget",10000),("include_deferred_sells",False),
            ("include_deferred_sells",True),("now","2026-10-01T13:30:00+00:00"),
            ("force",True),("prices",{}),("targets",[]),("mode","real"),
            ("environment","REAL"),("strategy_id","OTHER"))]
        for body in invalid:
            with self.subTest(keys=tuple(body)):
                code,response=self.request(body)
                self.assertEqual(code,400)
                self.assertFalse(response["ok"])
        self.best.engine._get.assert_not_called()
        self.best.authorize_catchup.assert_not_called()

    def test_non_object_non_string_or_nonfinite_json_is_rejected_before_account_lookup(self):
        invalid=[[],None,"date"]
        for key in self.valid_body:
            invalid += [{**self.valid_body,key:value} for value in (None,True,600,0.5,{},[])]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.request(body)[0],400)
        for raw in ('{"execution_date":"2026-10-01","deadline_utc":NaN}',
                    '{"execution_date":"2026-10-01","deadline_utc":Infinity}','{invalid'):
            with self.subTest(raw=raw):
                self.assertEqual(self.request(raw,raw=True)[0],400)
        self.best.engine._get.assert_not_called()
        self.best.authorize_catchup.assert_not_called()

    def test_cross_origin_wrong_host_fetch_site_or_wrong_token_blocks_before_bound_account_read(self):
        invalid=({"Host":"attacker.test"},{"Host":"127.0.0.1:9999"},
            {"Origin":"https://attacker.test"},{"Origin":"http://127.0.0.1:8506"},
            {"Sec-Fetch-Site":"cross-site"},{"X-CSRF-Token":""},
            {"X-CSRF-Token":"wrong"},{"X-CSRF-Token":self.fixture.live_token})
        for headers in invalid:
            with self.subTest(headers=headers):
                self.assertEqual(self.request(self.valid_body,headers=headers)[0],403)
        self.best.engine._get.assert_not_called()
        self.best.authorize_catchup.assert_not_called()

    def test_only_existing_loopback_origin_and_main_token_are_accepted(self):
        for host in ("127.0.0.1","localhost"):
            with self.subTest(host=host):
                code,_=self.request(self.valid_body,headers={"Host":host+":8766","Origin":"http://"+host+":8766"})
                self.assertEqual(code,200)
        self.assertEqual(self.best.authorize_catchup.call_count,2)
        self.assertTrue(all(call.kwargs["account_id"] == "original-simulate-account"
                            for call in self.best.authorize_catchup.call_args_list))

    def test_content_type_length_and_transfer_guards_reject_without_authorization(self):
        for headers,expected in (({"Content-Type":"text/plain"},415),
                ({"Transfer-Encoding":"chunked"},413),({"Content-Length":"0"},413),
                ({"Content-Length":"1048577"},413),({"Content-Length":"invalid"},400)):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(self.valid_body,headers=headers)[0],expected)
        self.best.engine._get.assert_not_called()
        self.best.authorize_catchup.assert_not_called()

    def test_missing_cohort_or_original_best_broker_never_falls_back_to_another_account(self):
        self.fixture.cohort=None
        self.assertEqual(self.request(self.valid_body)[0],400)
        self.fixture.cohort=self.cohort
        self.cohort.best_broker=None
        self.assertEqual(self.request(self.valid_body)[0],400)
        self.best.engine._get.assert_not_called()
        self.best.authorize_catchup.assert_not_called()

    def test_authorization_guard_exceptions_propagate_fail_closed_without_start_or_reconcile(self):
        reasons=("worker still active","original account mismatch","frozen source changed",
            "original SELL quantity missing","deferred sale absent","pending or unknown order",
            "not same NY trading day","deadline exceeds ten minutes","halt remains locked")
        for reason in reasons:
            self.best.authorize_catchup.side_effect=ValueError(reason)
            with self.subTest(reason=reason):
                code,response=self.request(self.valid_body)
                self.assertEqual(code,400)
                self.assertEqual(response,{"ok":False,"error":reason})
        self.assertEqual(self.best.authorize_catchup.call_count,len(reasons))
        self.assertTrue(all(call.kwargs["account_id"] == "original-simulate-account"
                            and call.kwargs["include_deferred_sells"] is True
                            for call in self.best.authorize_catchup.call_args_list))

    def test_original_account_lookup_exception_cannot_authorize_or_trigger_reconciliation(self):
        self.best.engine._get.side_effect=RuntimeError("original binding unavailable")
        code,response=self.request(self.valid_body)
        self.assertEqual(code,400)
        self.assertEqual(response,{"ok":False,"error":"original binding unavailable"})
        self.best.authorize_catchup.assert_not_called()

    def test_missing_original_binding_is_passed_to_existing_guard_without_client_or_paper_fallback(self):
        self.best.engine._get.return_value=None
        self.best.authorize_catchup.side_effect=ValueError("original SIMULATE account required")
        code,response=self.request(self.valid_body)
        self.assertEqual(code,400)
        self.assertEqual(response,{"ok":False,"error":"original SIMULATE account required"})
        self.assertIsNone(self.best.authorize_catchup.call_args.kwargs["account_id"])
        self.assertIs(self.best.authorize_catchup.call_args.kwargs["include_deferred_sells"],True)

    def test_live_broker_catchup_paths_are_forbidden_with_main_and_live_tokens(self):
        for path in ("/api/live/broker-catchup","/api/live/catchup","/api/live/order"):
            for token in (self.fixture.token,self.fixture.live_token):
                with self.subTest(path=path,token=token):
                    self.assertEqual(self.request(self.valid_body,path=path,
                        headers={"X-CSRF-Token":token})[0],403)
        self.best.engine._get.assert_not_called()
        self.best.authorize_catchup.assert_not_called()

    def test_query_string_cannot_override_original_account_or_server_permission(self):
        code,_=self.request(self.valid_body,
            path="/api/applied/broker-catchup?account_id=attacker&budget=1&mode=real&include_deferred_sells=false")
        self.assertEqual(code,200)
        args=self.best.authorize_catchup.call_args.kwargs
        self.assertEqual(set(args),{"execution_date","deadline_utc","account_id","include_deferred_sells","now"})
        self.assertEqual(args["account_id"],"original-simulate-account")
        self.assertIs(args["include_deferred_sells"],True)


class BrokerOnlyStartRoutingTests(unittest.TestCase):
    setUp = BrokerCatchupRoutingTests.setUp

    def request(self, body, *, path="/api/applied/broker-start", headers=None):
        result=CatchupRoutingTests.request(self,body,path=path,headers=headers)
        for action in ("start","stop","halt","authorize_catchup","state"):
            getattr(self.cohort,action).assert_not_called()
        for action in ("reconcile","authorize_catchup","tick","stop","halt"):
            getattr(self.best,action).assert_not_called()
        self.best.engine.connect.assert_not_called()
        self.best.engine.step.assert_not_called()
        return result

    def test_empty_body_starts_only_original_best_without_paper_actions_or_implicit_reconcile(self):
        self.best.start.return_value={"status":"WAITING_QUOTES","mode":"SIMULATE"}
        code,response=self.request({})
        self.assertEqual(code,200)
        self.assertEqual(response,{"ok":True,"data":self.best.start.return_value})
        self.best.start.assert_called_once_with()
        self.best.engine._get.assert_not_called()

    def test_nonempty_body_and_account_budget_force_real_clock_price_target_injections_are_rejected(self):
        invalid=[self.valid_body,[],None,"start"]
        invalid += [{key:value} for key,value in (("account_id","other"),("budget",1),
            ("force",True),("mode","real"),("now","2026-10-01T13:30:00+00:00"),
            ("prices",{}),("targets",[]),("include_deferred_sells",True))]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.request(body)[0],400)
        self.best.start.assert_not_called()
        self.best.engine._get.assert_not_called()

    def test_missing_original_best_and_native_start_guard_exceptions_fail_closed(self):
        self.cohort.best_broker=None
        self.assertEqual(self.request({})[0],400)
        self.best.start.assert_not_called()
        self.cohort.best_broker=self.best
        reasons=("original account mismatch","independent budget changed","unknown order pending",
                 "halt remains locked","authorized window expired")
        for reason in reasons:
            self.best.start.side_effect=ValueError(reason)
            with self.subTest(reason=reason):
                code,response=self.request({})
                self.assertEqual(code,400)
                self.assertEqual(response,{"ok":False,"error":reason})
        self.assertEqual(self.best.start.call_count,len(reasons))
        self.assertTrue(all(call.args == () and call.kwargs == {} for call in self.best.start.call_args_list))

    def test_existing_origin_host_main_token_json_and_live_guards_precede_broker_only_start(self):
        cases=(({"Host":"attacker.test"},403),({"Origin":"https://attacker.test"},403),
            ({"Sec-Fetch-Site":"cross-site"},403),({"X-CSRF-Token":""},403),
            ({"X-CSRF-Token":self.fixture.live_token},403),({"Content-Type":"text/plain"},415),
            ({"Transfer-Encoding":"chunked"},413))
        for headers,expected in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.request({},headers=headers)[0],expected)
        for token in (self.fixture.token,self.fixture.live_token):
            with self.subTest(token=token):
                self.assertEqual(self.request({},path="/api/live/broker-start",headers={"X-CSRF-Token":token})[0],403)
        self.best.start.assert_not_called()
        self.best.engine._get.assert_not_called()



class HgbResetRoutingTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        CatchupRoutingTests.setUp(self)
        self.cohort = Mock(spec=["authorize_catchup", "start", "stop", "halt", "state", "best_broker", "reset_hgb"])
        self.fixture.cohort = self.cohort
        self.best = self.cohort.best_broker
        self.cohort.reset_hgb.return_value = {"status": "RESET_PREPARED"}
        self.valid_body = dict(reset_id="20261004_hgb_reset", requested_at="2026-10-04T04:00:00Z",
            strategy_ids=["HGB_DIAG_5", "HGB_FACTOR_5"], signal_date="2026-10-02",
            expected_policy_id="HGB_TOP20_RISK_R1", expected_package_sha256="a" * 64)

    def request(self, body, **kwargs):
        return CatchupRoutingTests.request(self, body, path="/api/applied/reset-hgb", **kwargs)

    def test_reset_prepares_original_broker_then_restarts_two_books_without_activation(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 4, 4, 10, tzinfo=timezone.utc)
        with patch.object(server, "datetime") as clock:
            clock.now.return_value = now
            code, response = self.request(self.valid_body)
        self.assertEqual(code, 200)
        self.assertTrue(response["ok"])
        self.best.prepare_full_liquidation_reset.assert_called_once_with(self.valid_body, now=now)
        self.cohort.reset_hgb.assert_called_once_with(self.valid_body, now=now)
        self.cohort.start.assert_not_called()
        self.best.start.assert_not_called()
        self.best.engine.step.assert_not_called()

    def test_reset_rejects_injected_account_cash_price_model_and_other_strategy(self):
        invalid = [{}, {**self.valid_body, "strategy_ids": ["RAW_A2"]}]
        invalid.extend({**self.valid_body, key: value} for key, value in (
            ("account_id", "another"), ("budget", 10000), ("prices", {}), ("targets", []),
            ("now", "2026-10-04T04:00:00Z"), ("mode", "real"), ("force", True)))
        invalid.extend({**self.valid_body, key: value} for key, value in (
            ("reset_id", "../escape"), ("expected_policy_id", "RAW_TOP20_FROZEN_LEGACY"),
            ("expected_package_sha256", "bad"), ("requested_at", None)))
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.request(body)[0], 400)
        self.best.prepare_full_liquidation_reset.assert_not_called()
        self.cohort.reset_hgb.assert_not_called()

    def test_reset_preserves_csrf_and_origin_guards(self):
        for headers in ({"X-CSRF-Token": "wrong"}, {"Origin": "https://external.invalid"},
                        {"X-CSRF-Token": self.fixture.live_token}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(self.valid_body, headers=headers)[0], 403)
        self.best.prepare_full_liquidation_reset.assert_not_called()
        self.cohort.reset_hgb.assert_not_called()

    def test_failed_broker_prepare_cannot_reset_paper_books(self):
        self.best.prepare_full_liquidation_reset.side_effect = ValueError("original account mismatch")
        self.assertEqual(self.request(self.valid_body)[0], 400)
        self.cohort.reset_hgb.assert_not_called()

class CatchupRenewalRoutingTests(unittest.TestCase):
    """An explicit additional instruction remains separate from ordinary catchup."""
    def setUp(self):
        from unittest.mock import Mock
        CatchupRoutingTests.setUp(self)
        self.cohort = Mock(spec=["renew_catchup", "authorize_catchup", "start", "stop", "halt", "state", "best_broker"])
        self.fixture.cohort = self.cohort
        self.best = self.cohort.best_broker
        self.best.engine._get.return_value = "original-simulate-account"
        self.body = dict(execution_date="2026-10-07", deadline_utc="2026-10-07T15:10:00+00:00",
            expected_prior_sha256="a" * 64, renewal_id="manual_remainder_20261007", allowed_codes=["US.KDK"])
        self.cohort.renew_catchup.return_value = {"status": "AUTHORIZED", "automatic_execution_started": False}
        self.best.renew_catchup.return_value = self.cohort.renew_catchup.return_value

    def request(self, body, *, broker=False, path=None, headers=None):
        path = path or ("/api/applied/broker-catchup-renew" if broker else "/api/applied/catchup-renew")
        response = CatchupRoutingTests.request(self, body, path=path, headers=headers)
        for owner in (self.cohort, self.best):
            for action in ("start", "stop", "halt", "authorize_catchup"):
                getattr(owner, action).assert_not_called()
        self.best.reconcile.assert_not_called()
        self.best.tick.assert_not_called()
        self.best.engine.connect.assert_not_called()
        self.best.engine.step.assert_not_called()
        return response

    def test_paper_renewal_uses_explicit_scope_and_server_clock_without_execution(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)
        with patch.object(server, "datetime") as clock:
            clock.now.return_value = now
            code, response = self.request(self.body)
            clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(code, 200)
        self.assertTrue(response["ok"])
        self.cohort.renew_catchup.assert_called_once_with(**self.body, now=now)
        self.best.renew_catchup.assert_not_called()
        self.best.engine._get.assert_not_called()

    def test_broker_renewal_binds_original_simulator_and_server_clock(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)
        with patch.object(server, "datetime") as clock:
            clock.now.return_value = now
            self.assertEqual(self.request(self.body, broker=True)[0], 200)
        self.best.renew_catchup.assert_called_once_with(**self.body,
            account_id="original-simulate-account", now=now)
        self.best.engine._get.assert_called_once_with("best_account", None)
        self.cohort.renew_catchup.assert_not_called()

    def test_malformed_or_injected_renewal_never_reaches_account_owner(self):
        invalid = [{}, {k:v for k,v in self.body.items() if k != "renewal_id"}]
        invalid += [{**self.body, key:value} for key,value in (
            ("account_id", "other"), ("budget", 1), ("now", "injected"), ("prices", {}),
            ("targets", []), ("force", True), ("quote_refresh", True), ("mode", "real"),
            ("expected_prior_sha256", "A"*64), ("expected_prior_sha256", "x"),
            ("renewal_id", "../escape"), ("renewal_id", ""), ("renewal_id", True),
            ("allowed_codes", []), ("allowed_codes", ["US.KDK", "US.KDK"]),
            ("allowed_codes", ["HK.KDK"]), ("allowed_codes", [False]),
            ("allowed_codes", ["US.KDK", {}]), ("deadline_utc", False))]
        for body in invalid:
            for broker in (False, True):
                with self.subTest(body=body, broker=broker):
                    self.assertEqual(self.request(body, broker=broker)[0], 400)
        self.cohort.renew_catchup.assert_not_called()
        self.best.renew_catchup.assert_not_called()
        self.best.engine._get.assert_not_called()

    def test_renewal_retains_token_origin_and_live_execution_isolation(self):
        for broker in (False, True):
            for headers in ({"X-CSRF-Token": "wrong"}, {"X-CSRF-Token": self.fixture.live_token},
                            {"Origin": "http://127.0.0.1:8506"}, {"Sec-Fetch-Site": "cross-site"}):
                with self.subTest(broker=broker, headers=headers):
                    self.assertEqual(self.request(self.body, broker=broker, headers=headers)[0], 403)
        for path in ("/api/live/catchup-renew", "/api/live/broker-catchup-renew"):
            self.assertEqual(self.request(self.body, path=path)[0], 403)
        self.cohort.renew_catchup.assert_not_called()
        self.best.renew_catchup.assert_not_called()

    def test_original_guard_failure_is_returned_without_start_or_fallback(self):
        for broker in (False, True):
            owner = self.best if broker else self.cohort
            owner.renew_catchup.side_effect = ValueError("original permission or quantity changed")
            code, response = self.request(self.body, broker=broker)
            self.assertEqual(code, 400)
            self.assertEqual(response["error"], "original permission or quantity changed")

    def test_missing_original_owner_has_no_manual_or_live_fallback(self):
        self.cohort.best_broker = None
        self.assertEqual(self.request(self.body, broker=True)[0], 400)
        self.fixture.cohort = None
        self.assertEqual(self.request(self.body)[0], 400)
        self.best.renew_catchup.assert_not_called()
        self.cohort.renew_catchup.assert_not_called()


class WorkspaceThemeAssetTests(unittest.TestCase):
    """Exercise only the fixed GET asset handler; no socket, engine, SDK or state reads."""

    def response(self,path):
        from email.message import Message
        from types import SimpleNamespace
        from unittest.mock import Mock
        handler=server.Handler.__new__(server.Handler)
        engine=Mock();live=Mock();cohort=Mock()
        handler.server=SimpleNamespace(server_port=8766,engine=engine,live=live,cohort=cohort)
        handler.path=path;handler.headers=Message();handler.headers['Host']='127.0.0.1:8766'
        codes=[];headers={};handler.wfile=io.BytesIO()
        handler.send_response=lambda code:codes.append(code)
        handler.send_header=lambda key,value:headers.__setitem__(key,value)
        handler.end_headers=lambda:None
        handler.do_GET()
        self.assertEqual(engine.mock_calls,[]);self.assertEqual(live.mock_calls,[]);self.assertEqual(cohort.mock_calls,[])
        return codes,headers,handler.wfile.getvalue()

    def test_workspace_theme_route_reads_only_the_fixed_shared_css(self):
        from pathlib import Path
        payload=b'/* synthetic shared theme */'
        expected=Path(__file__).resolve().parents[3]/'apps/shared_ui/theme.css'
        with patch.object(server.Path,'read_bytes',autospec=True,return_value=payload) as read:
            codes,headers,body=self.response('/static/workspace_theme.css')
        read.assert_called_once_with(expected)
        self.assertEqual(codes,[200]);self.assertEqual(body,payload)
        self.assertEqual(headers['Content-Type'],'text/css; charset=utf-8')
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(headers['X-Frame-Options'],'DENY')
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])

    def test_query_parameters_cannot_select_another_theme_file(self):
        from pathlib import Path
        expected=Path(__file__).resolve().parents[3]/'apps/shared_ui/theme.css'
        with patch.object(server.Path,'read_bytes',autospec=True,return_value=b'fixed') as read:
            self.assertEqual(self.response('/static/workspace_theme.css?path=../../AGENTS.md')[0],[200])
        read.assert_called_once_with(expected)
        for path in ('/static/../workspace_theme.css','/static/workspace_theme.css/../server.py',
                     '/static/workspace_theme.css%2f..%2fserver.py','/static/theme.css'):
            with self.subTest(path=path),patch.object(server.Path,'read_bytes') as read:
                self.assertEqual(self.response(path)[0],[404]);read.assert_not_called()

    def test_applied_shell_loads_shared_theme_before_local_aliases(self):
        from pathlib import Path
        shell=(Path(__file__).parents[1]/'moomoo_component/static/applied.html').read_text(encoding='utf-8')
        self.assertLess(shell.index('/static/workspace_theme.css'),shell.index('/static/applied.css'))
        css=(Path(__file__).parents[1]/'moomoo_component/static/applied.css').read_text(encoding='utf-8')
        for alias,source in (('bg','bg'),('paper','panel'),('text','text'),('muted','muted'),('line','line'),('accent','accent')):
            self.assertIn('--'+alias+':var(--ui-'+source+')',css)
        self.assertIn('var(--ui-font)',css)


if __name__ == "__main__":
    unittest.main()
