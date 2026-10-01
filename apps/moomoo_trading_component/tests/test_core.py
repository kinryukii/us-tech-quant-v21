"""Safety invariants at the engine boundary; no SDK or network calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from moomoo_component.core import Engine


def manifest(targets=None, provenance="live", **changes):
    now = datetime.now(timezone.utc)
    result = dict(schema_version=1, strategy_id="safety-test", name="安全测试", revision="1",
                  asof=(now - timedelta(seconds=1)).isoformat(),
                  expires_at=(now + timedelta(hours=1)).isoformat(), provenance=provenance,
                  targets=targets or [{"code": "US.AAPL", "target_qty": 1}])
    result.update(changes)
    return result


class BrokerFixture:
    def __init__(self):
        self.cash = 10000.0
        self.equity = 10000.0
        self.positions = {}
        self.open_orders = []
        self.quotes = {
            code: dict(price=price, bid=price - .01, ask=price + .01,
                       asof=datetime.now(timezone.utc).isoformat(), lot_size=1,
                       price_tick=.01, tradable=True)
            for code, price in (("US.AAPL", 200.0), ("US.MSFT", 400.0))
        }
        self.submissions = []
        self.snapshot_calls = 0
        self.snapshot_hook = None
        self.submit_error = None
        self.reconcile_result = {"order_id": "fixture-order", "status": "FILLED_ALL"}

    def factory(self, **kwargs):
        return self

    def probe(self):
        return {"accounts": [{"account_id": "sim-one", "market": "US", "environment": "SIMULATE"}]}

    def snapshot(self, codes):
        self.snapshot_calls += 1
        if self.snapshot_hook:
            self.snapshot_hook(self.snapshot_calls)
        return deepcopy(dict(cash=self.cash, equity=self.equity, positions=self.positions,
                             quotes=self.quotes, open_orders=self.open_orders))

    def submit(self, order, client_id):
        self.submissions.append((deepcopy(order), client_id))
        if self.submit_error:
            raise self.submit_error
        return {"order_id": "fixture-order", "status": "FILLED_ALL"}

    def reconcile(self, client_id, order_id):
        return deepcopy(self.reconcile_result)

    def close(self):
        pass


class ObservedEvent(threading.Event):
    """Observe the stop request before stop() can acquire the engine lock."""
    def __init__(self):
        super().__init__()
        self.called = threading.Event()
        super().set()

    def set(self):
        super().set()
        self.called.set()


class StopAfterIntentCommit:
    """Inject a real stop request exactly when the durable intent finishes."""
    def __init__(self, connection, engine):
        self.connection = connection
        self.engine = engine
        self.armed = False

    def execute(self, sql, *args):
        result = self.connection.execute(sql, *args)
        if sql.lstrip().upper().startswith("INSERT INTO ORDERS"):
            self.armed = True
        return result

    def commit(self):
        self.connection.commit()
        if self.armed:
            self.armed = False
            self.engine.stop()

    def __getattr__(self, name):
        return getattr(self.connection, name)


class EngineSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.engines = []
        self.addCleanup(self.close_engines)

    def close_engines(self):
        for engine in reversed(self.engines):
            engine.close()

    def engine(self, broker=None, folder="state"):
        result = Engine(Path(self.temporary.name) / folder, broker_factory=broker.factory if broker else None)
        self.engines.append(result)
        return result

    def ready(self, broker=None, targets=None):
        broker = broker or BrokerFixture()
        engine = self.engine(broker)
        engine.import_strategy(manifest(targets=targets))
        engine.switch("safety-test")
        engine.connect()
        engine.set_mode("moomoo_simulate", "sim-one", "SIMULATE")
        return engine, broker

    def test_unknown_submission_is_durable_and_never_retried(self):
        engine, broker = self.ready()
        broker.submit_error = TimeoutError("broker may have accepted before response was lost")
        with self.assertRaises(TimeoutError):
            engine.step()
        state = engine.state()
        self.assertTrue(state["halted"])
        self.assertEqual(state["orders"][0]["status"], "UNKNOWN")
        self.assertEqual(len(broker.submissions), 1)
        with self.assertRaises(ValueError):
            engine.reset_halt()
        with self.assertRaises(ValueError):
            engine.step()
        engine.close()
        self.engines.remove(engine)
        rebooted = self.engine(broker)
        self.assertEqual(rebooted.state()["mode"], "paper")
        self.assertFalse(rebooted.state()["running"])
        self.assertTrue(rebooted.state()["halted"])
        self.assertEqual(rebooted.state()["orders"][0]["status"], "UNKNOWN")
        with self.assertRaises(ValueError):
            rebooted.set_mode("paper")
        rebooted.connect()
        rebooted.set_mode("moomoo_simulate", "sim-one", "SIMULATE")
        broker.reconcile_result = {"status": "UNKNOWN", "order_id": None}
        rebooted.reconcile()
        with self.assertRaises(ValueError):
            rebooted.reset_halt()
        self.assertEqual(len(broker.submissions), 1)

    def test_accepted_order_requires_reconciliation_even_if_submit_claims_filled(self):
        engine, broker = self.ready()
        engine.step()
        self.assertEqual(engine.state()["orders"][0]["status"], "PENDING_RECONCILE")
        with self.assertRaises(ValueError):
            engine.step()
        with self.assertRaises(ValueError):
            engine.switch("safety-test")
        self.assertEqual(len(broker.submissions), 1)

    def test_completed_signal_is_not_reissued_if_position_snapshot_lags(self):
        engine, broker = self.ready()
        engine.step()
        engine.reconcile()
        self.assertEqual(engine.state()["orders"][0]["status"], "FILLED_ALL")
        # Deliberately leave the fixture account at the old quantity.
        with self.assertRaisesRegex(ValueError, "已经处理"):
            engine.step()
        self.assertEqual(len(broker.submissions), 1)

    def test_whole_batch_rejected_before_any_order_when_one_target_exceeds_risk(self):
        engine, broker = self.ready(targets=[{"code": "US.AAPL", "target_qty": 1},
                                              {"code": "US.MSFT", "target_qty": 100}])
        with self.assertRaises(ValueError):
            engine.step()
        self.assertEqual(broker.submissions, [])
        self.assertEqual(engine.state()["orders"], [])

    def test_sales_do_not_finance_same_batch_buys(self):
        broker = BrokerFixture()
        broker.cash = 1000
        broker.equity = 1400
        broker.positions = {"US.MSFT": {"qty": 1, "sellable": 1, "market_value": 400}}
        engine, _ = self.ready(broker, [{"code": "US.MSFT", "target_qty": 0},
                                       {"code": "US.AAPL", "target_qty": 1}])
        with self.assertRaisesRegex(ValueError, "现金不足"):
            engine.step()
        self.assertEqual(broker.submissions, [])

    def test_external_open_order_blocks_all_submissions(self):
        engine, broker = self.ready()
        broker.open_orders = [{"order_id": "outside-component", "code": "US.MSFT"}]
        with self.assertRaisesRegex(ValueError, "未完成订单"):
            engine.step()
        self.assertEqual(broker.submissions, [])

    def test_stale_future_and_nontradable_quotes_block(self):
        for offset, tradable in ((-120, True), (10, True), (0, False)):
            with self.subTest(offset=offset, tradable=tradable):
                engine, broker = self.ready()
                broker.quotes["US.AAPL"]["asof"] = (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()
                broker.quotes["US.AAPL"]["tradable"] = tradable
                with self.assertRaises(ValueError):
                    engine.step()
                self.assertEqual(broker.submissions, [])
                engine.close()
                self.engines.remove(engine)

    def test_quote_is_refreshed_after_preview_and_before_submit(self):
        engine, broker = self.ready()

        def expire_on_second_snapshot(count):
            if count == 2:
                broker.quotes["US.AAPL"]["asof"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        broker.snapshot_hook = expire_on_second_snapshot
        with self.assertRaisesRegex(ValueError, "行情过期"):
            engine.step()
        self.assertEqual(broker.submissions, [])

    def test_daily_loss_latches_and_survives_reboot(self):
        engine, broker = self.ready()
        self.assertTrue(engine.preview()["allowed"])
        broker.equity -= 250
        with self.assertRaises(ValueError):
            engine.step()
        self.assertTrue(engine.state()["halted"])
        self.assertEqual(broker.submissions, [])
        engine.close()
        self.engines.remove(engine)
        rebooted = self.engine(broker)
        self.assertTrue(rebooted.state()["halted"])
        self.assertFalse(rebooted.state()["running"])

    def test_daily_budget_uses_persisted_orders(self):
        engine, broker = self.ready()
        engine.set_limits({"max_orders_per_day": 1})
        engine.step()
        engine.reconcile()
        broker.positions["US.AAPL"] = {"qty": 1, "sellable": 1, "market_value": 200}
        engine.import_strategy(manifest(targets=[{"code": "US.MSFT", "target_qty": 1}],
                                        strategy_id="next-signal"))
        engine.switch("next-signal")
        with self.assertRaisesRegex(ValueError, "每日订单数"):
            engine.step()
        self.assertEqual(len(broker.submissions), 1)

    def test_tick_rounding_cannot_escape_limit_deviation_guard(self):
        engine, broker = self.ready()
        broker.quotes["US.AAPL"]["price_tick"] = 100
        with self.assertRaises(ValueError):
            engine.step()
        self.assertEqual(broker.submissions, [])

    def test_only_one_engine_can_use_a_state_directory(self):
        engine = self.engine()
        with self.assertRaises(RuntimeError):
            Engine(Path(self.temporary.name) / "state")
        engine.close()
        self.engines.remove(engine)
        reopened = self.engine()
        self.assertFalse(reopened.state()["running"])

    def test_stop_after_durable_intent_prevents_the_network_send(self):
        engine, broker = self.ready()
        engine.db = StopAfterIntentCommit(engine.db, engine)
        try:
            engine.step()
        except ValueError:
            pass  # Explicit cancellation may raise or return an empty batch.
        self.assertEqual(broker.submissions, [], "stop during the intent commit must still prevent network submission")
        self.assertEqual(engine._pending(), [], "a definitely unsent intent must have a durable local terminal state")

    def test_manual_step_obeys_stop_arriving_during_fresh_snapshot(self):
        engine, broker = self.ready()
        engine.stop_event = ObservedEvent()
        snapshot_entered, release_snapshot = threading.Event(), threading.Event()
        errors = []

        def pause_fresh_snapshot(count):
            if count == 2:
                snapshot_entered.set()
                if not release_snapshot.wait(3):
                    raise RuntimeError("test synchronization timeout")

        def run_manual():
            try:
                engine.step()
            except ValueError as exc:
                errors.append(exc)  # Explicit cancellation may raise or return an empty batch.

        broker.snapshot_hook = pause_fresh_snapshot
        runner = threading.Thread(target=run_manual, daemon=True)
        stopper = threading.Thread(target=engine.stop, daemon=True)
        runner.start()
        try:
            self.assertTrue(snapshot_entered.wait(3), "manual step did not reach fresh snapshot")
            stopper.start()
            self.assertTrue(engine.stop_event.called.wait(3), "stop request not observed")
        finally:
            release_snapshot.set()
            runner.join(3)
            if stopper.ident is not None:
                stopper.join(3)
        self.assertFalse(runner.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(broker.submissions, [], "a stop request must cancel subsequent sends from a manual step")


class PartialPaperExecutionTests(unittest.TestCase):
    OPEN = datetime(2026, 9, 29, 14, 15, tzinfo=timezone.utc)
    CLOSE = datetime(2026, 9, 28, 20, tzinfo=timezone.utc)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "partial-paper"
        with patch("moomoo_component.core.now_iso", return_value=self.CLOSE.isoformat()):
            self.engine = Engine(self.folder, paper_only=True, paper_account_id="partial-paper")
        self.addCleanup(lambda: self.engine.close())
        self.plan = dict(source_date="2026-09-28", target_cash_weight=0,
            rows=[dict(code="US.AAPL", target_weight=.4), dict(code="US.MSFT", target_weight=.6)],
            evidence="frozen source rows, including the unqualified target")

    def quotes(self, codes, clock=None, **changes):
        clock = clock or self.OPEN + timedelta(seconds=10)
        return {code: dict(price=100, bid=99.95, ask=100.05, asof=clock.isoformat(),
            tradable=True, lot_size=1, source="MOOMOO_OPEND", market="US", currency="USD", **changes)
            for code in codes}

    def rebalance(self, quotes, *, clock=None, errors=None, plan=None, partial=True, window=600):
        return self.engine.paper_rebalance("RAW_A2", plan or self.plan, quotes,
            now=clock or self.OPEN + timedelta(seconds=10), next_open_utc=self.OPEN.isoformat(),
            signal_date="2026-09-28", execution_date="2026-09-29", signal_close_utc=self.CLOSE.isoformat(),
            source_refs={"manifest": "a" * 64}, allow_partial_quotes=partial,
            quote_errors=errors, execution_window_seconds=window)

    def test_qualified_purchase_keeps_other_weight_as_cash_and_full_source_plan(self):
        before = deepcopy(self.plan)
        result = self.rebalance(self.quotes(["US.AAPL"]), errors={"US.MSFT": "MSFT quote is stale"})
        self.assertEqual(result["status"], "PARTIALLY_EXECUTED")
        self.assertEqual(result["processed_codes"], ["US.AAPL"])
        self.assertEqual(result["executed_codes"], ["US.AAPL"])
        self.assertEqual(result["skipped"], [{"code": "US.MSFT", "reason": "MSFT quote is stale"}])
        self.assertEqual(result["target_weights"], {"US.AAPL": .4, "US.MSFT": .6})
        self.assertEqual(result["source_plan"], before)
        self.assertEqual(self.plan, before)
        trade = self.engine.paper_trades()[0]
        self.assertEqual(trade["qty"], 39)
        self.assertEqual(trade["fill_price"], 100.05)
        self.assertEqual(trade["source_plan_sha256"], result["source_plan_sha256"])
        self.assertAlmostEqual(self.engine.paper_book()["cash"], 10000 - 39 * 100.05 * 1.0005)
        self.assertGreater(self.engine.paper_book()["cash"], 6000)

    def test_all_unqualified_quotes_record_reasons_and_never_fill(self):
        result = self.rebalance({}, errors={"US.AAPL": "missing source time", "US.MSFT": "wide spread"})
        self.assertEqual(result["status"], "WAITING_QUOTES")
        self.assertEqual(result["fill_count"], 0)
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(self.engine.paper_trades(), [])
        self.assertEqual(self.engine.paper_book()["cash"], 10000)
        self.assertEqual(self.engine.paper_book()["fees"], 0)
        self.assertEqual(self.engine.state()["orders"], [])

    def test_recovered_quote_executes_once_with_original_equity_after_restart(self):
        first = self.rebalance(self.quotes(["US.AAPL"]), errors={"US.MSFT": "stale"})
        self.engine.close()
        self.engine = Engine(self.folder, paper_only=True, paper_account_id="partial-paper")
        clock = self.OPEN + timedelta(minutes=3)
        quotes = self.quotes(["US.AAPL", "US.MSFT"], clock)
        quotes["US.AAPL"].update(price=200, bid=199.95, ask=200.05)
        second = self.rebalance(quotes, clock=clock)
        self.assertEqual(second["status"], "EXECUTED")
        self.assertEqual(second["pretrade_equity"], first["pretrade_equity"])
        self.assertEqual(second["new_fill_count"], 1)
        self.assertEqual([(row["code"], row["qty"]) for row in self.engine.paper_trades()],
                         [("US.AAPL", 39), ("US.MSFT", 59)])
        again = self.rebalance(quotes, clock=clock)
        self.assertTrue(again["already_executed"])
        self.assertEqual(again["new_fill_count"], 0)
        self.assertEqual(len(self.engine.paper_trades()), 2)

    def test_changed_frozen_plan_is_rejected_after_a_partial_fill(self):
        self.rebalance(self.quotes(["US.AAPL"]), errors={"US.MSFT": "stale"})
        altered = deepcopy(self.plan)
        altered["rows"][0]["target_weight"] = .5
        altered["rows"][1]["target_weight"] = .5
        with self.assertRaisesRegex(ValueError, "冻结计划"):
            self.rebalance(self.quotes(["US.MSFT"]), plan=altered)
        self.assertEqual(len(self.engine.paper_trades()), 1)

    def test_bad_held_quote_uses_verified_recorded_mark_with_its_original_asof(self):
        self.engine._set("paper", dict(cash=9000, positions={"US.MSFT": 10}, fees=0))
        self.engine.paper_mark({"US.MSFT": dict(price=100, asof=self.CLOSE.isoformat(),
            source="CANONICAL_RAW_USD_CLOSE")}, basis="SIGNAL_CLOSE")
        old_mark = deepcopy(self.engine._get("paper_marks", {})["US.MSFT"])
        result = self.rebalance(self.quotes(["US.AAPL"]), errors={"US.MSFT": "stale"})
        self.assertEqual(result["pretrade_equity"], 10000)
        self.assertEqual(result["pretrade_valuation_basis"], "RECORDED_MARKS")
        self.assertEqual(result["pretrade_equity_asof"], self.CLOSE.isoformat())
        self.assertEqual(result["pretrade_valuation_marks"]["US.MSFT"]["basis"], "SIGNAL_CLOSE")
        self.assertEqual(self.engine._get("paper_marks", {})["US.MSFT"], old_mark)
        self.assertEqual(self.engine._get("paper", {})["positions"]["US.MSFT"], 10)
        self.assertEqual(self.engine.paper_trades()[0]["qty"], 39)
        latest_nav = self.engine.paper_nav_history()[-1]
        self.assertEqual(latest_nav["basis"], "PARTIAL_REALTIME_WITH_RECORDED_MARKS")
        self.assertEqual(latest_nav["asof"], self.CLOSE.isoformat())
        self.assertEqual(latest_nav["valuation_marks"]["US.MSFT"], old_mark)

    def test_missing_held_valuation_blocks_new_buys_without_fabricating_nav(self):
        self.engine._set("paper", dict(cash=9000, positions={"US.MSFT": 10}, fees=0))
        result = self.rebalance(self.quotes(["US.AAPL"]), errors={"US.MSFT": "missing quote"})
        self.assertIsNone(result["pretrade_equity"])
        self.assertEqual(result["pretrade_valuation_basis"], "INCOMPLETE")
        self.assertEqual(result["status"], "WAITING_QUOTES")
        self.assertIn("下单权益未能完整核验", result["skipped"][0]["reason"])
        self.assertEqual(self.engine.paper_trades(), [])
        self.assertIsNone(self.engine.paper_book()["equity"])
        self.assertEqual(self.engine.paper_book()["cash"], 9000)

    def test_missing_other_held_mark_still_allows_qualified_full_liquidation(self):
        self.engine._set("paper", dict(cash=8000, positions={"US.AAPL": 10, "US.MSFT": 10}, fees=0))
        plan = dict(source_date="2026-09-28", target_cash_weight=.5,
            rows=[dict(code="US.AAPL", target_weight=0), dict(code="US.MSFT", target_weight=0),
                  dict(code="US.SPY", target_weight=.5)])
        result = self.rebalance(self.quotes(["US.AAPL", "US.SPY"]), plan=plan,
                                errors={"US.MSFT": "missing source clock"})
        self.assertIsNone(result["pretrade_equity"])
        self.assertEqual(result["processed_codes"], ["US.AAPL"])
        trades = self.engine.paper_trades()
        self.assertEqual([(trade["code"], trade["side"], trade["qty"]) for trade in trades],
                         [("US.AAPL", "SELL", 10)])
        self.assertAlmostEqual(self.engine.paper_book()["cash"], 8000 + 10 * 99.95 * .9995)
        self.assertEqual(self.engine._get("paper", {})["positions"], {"US.MSFT": 10})

    def test_each_bad_quote_category_skips_only_that_security(self):
        for bad in (dict(asof=(self.OPEN - timedelta(seconds=40)).isoformat()),
                    dict(bid=99, ask=102), dict(tradable=False), dict(lot_size=100),
                    dict(currency="HKD"), dict(asof=(self.OPEN + timedelta(seconds=20)).isoformat())):
            with self.subTest(bad=bad):
                quotes = self.quotes(["US.AAPL", "US.MSFT"])
                quotes["US.MSFT"].update(bad)
                # A separate account prevents prior per-symbol idempotency hiding a failure.
                folder = self.folder.parent / ("variant-" + str(len(list(self.folder.parent.iterdir()))))
                engine = Engine(folder, paper_only=True, paper_account_id=folder.name)
                original = self.engine
                self.engine = engine
                try:
                    result = self.rebalance(quotes)
                    self.assertEqual(result["processed_codes"], ["US.AAPL"])
                    self.assertEqual(result["skipped"][0]["code"], "US.MSFT")
                    self.assertEqual(len(engine.paper_trades()), 1)
                finally:
                    engine.close()
                    self.engine = original

    def test_ten_minute_window_accepts_late_qualified_quote_and_rejects_deadline(self):
        clock = self.OPEN + timedelta(seconds=500)
        result = self.rebalance(self.quotes(["US.AAPL"], clock), clock=clock,
                                errors={"US.MSFT": "stale"})
        self.assertEqual(result["new_fill_count"], 1)
        end = self.OPEN + timedelta(seconds=600)
        with self.assertRaisesRegex(ValueError, "MISSED_OPEN"):
            self.rebalance(self.quotes(["US.MSFT"], end), clock=end)
        self.assertEqual(len(self.engine.paper_trades()), 1)

    def test_default_whole_batch_and_one_minute_policy_remain_unchanged(self):
        with self.assertRaisesRegex(ValueError, "真实行情缺失"):
            self.rebalance(self.quotes(["US.AAPL"]), partial=False, window=60)
        clock = self.OPEN + timedelta(seconds=61)
        with self.assertRaisesRegex(ValueError, "MISSED_OPEN"):
            self.engine.paper_rebalance("RAW_A2", self.plan, self.quotes(["US.AAPL", "US.MSFT"], clock),
                now=clock, next_open_utc=self.OPEN.isoformat(), signal_date="2026-09-28",
                execution_date="2026-09-29", signal_close_utc=self.CLOSE.isoformat())
        self.assertEqual(self.engine.paper_trades(), [])

    def test_partial_commit_failure_rolls_back_fills_batch_and_cash_together(self):
        self.engine.db.execute("CREATE TRIGGER fail_partial BEFORE INSERT ON paper_fills BEGIN SELECT RAISE(ABORT,'fixture'); END")
        self.engine.db.commit()
        with self.assertRaises(Exception):
            self.rebalance(self.quotes(["US.AAPL"]), errors={"US.MSFT": "stale"})
        self.assertEqual(self.engine.paper_book()["cash"], 10000)
        self.assertEqual(self.engine.paper_trades(), [])
        self.assertEqual(self.engine.state()["orders"], [])
        self.assertEqual(self.engine.db.execute("SELECT count(*) FROM paper_batches").fetchone()[0], 0)


class PartialBrokerFixture(BrokerFixture):
    def snapshot_partial(self, codes):
        result = self.snapshot(codes)
        result["quote_errors"] = getattr(self, "quote_errors", {})
        return result

    def submit(self, order, client_id, **options):
        self.submit_options = options
        return super().submit(order, client_id)


class PartialBrokerExecutionTests(unittest.TestCase):
    """The partial flag is limited to the authorized BestBroker route."""
    setUp = EngineSafetyTests.setUp
    close_engines = EngineSafetyTests.close_engines
    engine = EngineSafetyTests.engine
    ready = EngineSafetyTests.ready
    def ready_partial(self, broker=None, targets=None):
        broker = broker or PartialBrokerFixture()
        engine, broker = self.ready(broker, targets)
        source = json.dumps({"kind": "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"})
        engine.import_strategy(manifest(targets=targets, source=source))
        return engine, broker

    def test_partial_quote_failure_does_not_block_qualified_simulate_order(self):
        engine, broker = self.ready_partial(targets=[dict(code="US.AAPL", target_qty=1),
                                                    dict(code="US.MSFT", target_qty=1)])
        broker.quote_errors = {"US.MSFT": "quote stale"}
        result = engine.step(allow_partial_quotes=True)
        self.assertEqual([order["code"] for order in result["submitted"]], ["US.AAPL"])
        self.assertEqual(result["skipped"], [{"code": "US.MSFT", "reason": "quote stale"}])
        self.assertTrue(broker.submit_options["allow_partial_quotes"])
        self.assertEqual(broker.submit_options["execution_deadline_utc"], engine._manifest()["expires_at"])
        self.assertEqual(engine.state()["orders"][0]["status"], "PENDING_RECONCILE")

    def test_partial_flag_rejects_an_unrelated_manifest_before_snapshot(self):
        engine, broker = self.ready(PartialBrokerFixture())
        with self.assertRaisesRegex(ValueError, "已授权"):
            engine.step(allow_partial_quotes=True)
        self.assertEqual(broker.snapshot_calls, 0)
        self.assertEqual(broker.submissions, [])

    def test_partial_route_still_blocks_all_orders_for_global_risk(self):
        engine, broker = self.ready_partial(targets=[dict(code="US.AAPL", target_qty=100),
                                                    dict(code="US.MSFT", target_qty=1)])
        broker.quote_errors = {"US.MSFT": "stale"}
        with self.assertRaisesRegex(ValueError, "单笔金额"):
            engine.step(allow_partial_quotes=True)
        self.assertEqual(broker.submissions, [])
        self.assertEqual(engine.state()["orders"], [])

    def test_partial_route_keeps_thirty_second_fifty_bp_gates_if_manual_limits_are_looser(self):
        engine, broker = self.ready_partial(targets=[dict(code="US.AAPL", target_qty=1),
                                                    dict(code="US.MSFT", target_qty=1)])
        engine.set_limits(dict(max_quote_age_seconds=60, max_spread_bps=200))
        broker.quotes["US.MSFT"]["asof"] = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        preview = engine.preview(allow_partial_quotes=True)
        self.assertTrue(preview["allowed"])
        self.assertEqual([order["code"] for order in preview["orders"]], ["US.AAPL"])
        broker.quotes["US.MSFT"].update(asof=datetime.now(timezone.utc).isoformat(), bid=398, ask=402)
        preview = engine.preview(allow_partial_quotes=True)
        self.assertTrue(preview["allowed"])
        self.assertEqual([order["code"] for order in preview["orders"]], ["US.AAPL"])

    def test_bad_held_quote_does_not_replace_broker_account_market_value(self):
        engine, broker = self.ready_partial()
        broker.positions = {"US.MSFT": dict(qty=1, sellable=1, market_value=400)}
        broker.cash = 9600
        broker.quote_errors = {"US.MSFT": "held quote stale"}
        result = engine.preview(allow_partial_quotes=True)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["account"]["positions"]["US.MSFT"]["market_value"], 400)
        self.assertEqual(result["orders"][0]["code"], "US.AAPL")

    def test_known_order_is_not_reissued_when_broker_position_snapshot_lags(self):
        engine, broker = self.ready_partial()
        engine.step(allow_partial_quotes=True)
        engine.reconcile()
        result = engine.step(allow_partial_quotes=True)
        self.assertEqual(result["submitted"], [])
        self.assertEqual(len(broker.submissions), 1)
        self.assertTrue(result["skipped"][0]["already_processed"])

    def test_definitely_unsent_order_can_retry_without_unknown_halt(self):
        from moomoo_component.brokers import BrokerOrderNotSent

        class TemporaryBadBook(PartialBrokerFixture):
            calls = 0

            def submit(self, order, client_id, **options):
                self.calls += 1
                if self.calls == 1:
                    raise BrokerOrderNotSent("book became stale before place_order")
                return super().submit(order, client_id, **options)

        engine, broker = self.ready_partial(TemporaryBadBook())
        first = engine.step(allow_partial_quotes=True)
        self.assertEqual(first["submitted"], [])
        self.assertTrue(first["skipped"][0]["definitely_not_sent"])
        self.assertEqual(engine.state()["orders"][0]["status"], "CANCELLED_BEFORE_SEND")
        self.assertFalse(engine.halt_event.is_set())
        self.assertEqual(broker.submissions, [])
        second = engine.step(allow_partial_quotes=True)
        self.assertEqual(len(second["submitted"]), 1)
        self.assertEqual(len(broker.submissions), 1)
        self.assertEqual(len(engine.state()["orders"]), 1)

    def test_actual_partial_submission_error_still_halts_unknown_and_never_retries(self):
        engine, broker = self.ready_partial()
        broker.submit_error = TimeoutError("place_order may already have been accepted")
        with self.assertRaises(TimeoutError):
            engine.step(allow_partial_quotes=True)
        self.assertEqual(engine.state()["orders"][0]["status"], "UNKNOWN")
        self.assertTrue(engine.halt_event.is_set())
        with self.assertRaises(ValueError):
            engine.step(allow_partial_quotes=True)
        self.assertEqual(len(broker.submissions), 1)


if __name__ == "__main__":
    unittest.main()
