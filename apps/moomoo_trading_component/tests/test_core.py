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


class ObservedPaperValuationTests(unittest.TestCase):
    CLOCK = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)
    OLD = datetime(2026, 9, 29, 13, 30, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        with patch("moomoo_component.core.now_iso", return_value=self.OLD.isoformat()):
            self.engine = Engine(Path(self.temp.name), paper_only=True)
        self.addCleanup(self.engine.close)
        self.engine._set("paper", dict(cash=9000, fees=2, positions={"US.AAPL": 5, "US.MSFT": 5}))
        self.engine.paper_mark({code: dict(price=100, asof=self.OLD.isoformat(), source="MOOMOO_OPEND")
            for code in ("US.AAPL", "US.MSFT")}, day="2026-09-29")

    def quote(self, **changes):
        return dict(price=120, asof=(self.CLOCK - timedelta(seconds=3)).isoformat(), source="MOOMOO_OPEND",
            currency="USD", market="US", tradable=True, **changes)

    def test_partial_nav_retains_actual_old_marks_and_excludes_sold_marks_from_times(self):
        marks = self.engine._get("paper_marks", {})
        marks["US.SOLD"] = dict(price=999, asof=(self.CLOCK + timedelta(days=1)).isoformat(),
            source="MOOMOO_OPEND", basis="MOOMOO_REALTIME")
        self.engine._set("paper_marks", marks)
        ledger = deepcopy(self.engine._get("paper", {}))
        book = self.engine.paper_mark({"US.AAPL": self.quote()}, day="2026-09-29",
            observed_at_utc=self.CLOCK.isoformat(), failed_quotes={"US.MSFT": "source older than 30s"})
        row = self.engine.paper_nav_history()[-1]
        self.assertEqual(row["equity"], 10100)
        self.assertEqual(row["basis"], "OBSERVED_MIXED_MARKS")
        self.assertEqual(row["asof"], self.OLD.isoformat())
        self.assertEqual(row["held_asof_min"], self.OLD.isoformat())
        self.assertEqual(row["held_asof_max"], self.quote()["asof"])
        self.assertEqual(row["observed_at_utc"], self.CLOCK.isoformat())
        self.assertFalse(row["complete_live_coverage"])
        self.assertEqual(row["fresh_held_count"], 1)
        self.assertEqual(self.engine._get("paper", {}), ledger)
        self.assertEqual(self.engine._get("paper_marks", {})["US.MSFT"], marks["US.MSFT"])
        self.assertEqual(self.engine._get("paper_marks", {})["US.AAPL"]["basis"], "MOOMOO_REALTIME")
        self.assertTrue(book["valuation"]["nav_recorded"])

    def test_zero_fresh_or_missing_true_mark_cannot_record_nav(self):
        old = deepcopy(self.engine.paper_nav_history())
        result = self.engine.paper_mark({}, day="2026-09-29", observed_at_utc=self.CLOCK.isoformat(),
            failed_quotes={"US.AAPL": "failed", "US.MSFT": "failed"})
        self.assertFalse(result["valuation"]["nav_recorded"])
        self.assertEqual(self.engine.paper_nav_history(), old)
        marks = self.engine._get("paper_marks", {}); marks.pop("US.MSFT"); self.engine._set("paper_marks", marks)
        result = self.engine.paper_mark({"US.AAPL": self.quote()}, day="2026-09-29", observed_at_utc=self.CLOCK.isoformat())
        self.assertEqual(self.engine.paper_nav_history(), old)
        self.assertEqual(result["valuation"]["unmarked_codes"], ["US.MSFT"])

    def test_complete_fresh_nav_has_real_source_times_and_no_mix_label(self):
        self.engine.paper_mark({code: self.quote() for code in ("US.AAPL", "US.MSFT")},
            day="2026-09-29", observed_at_utc=self.CLOCK.isoformat())
        row = self.engine.paper_nav_history()[-1]
        self.assertEqual(row["basis"], "MOOMOO_REALTIME")
        self.assertTrue(row["complete_live_coverage"])
        self.assertEqual(row["held_asof_min"], self.quote()["asof"])
        self.assertNotEqual(row["asof"], row["observed_at_utc"])

    def test_engine_boundary_rejects_stale_future_and_nontradable_quotes(self):
        for change in ({"asof": (self.CLOCK - timedelta(seconds=31)).isoformat()},
                       {"asof": (self.CLOCK + timedelta(seconds=1)).isoformat()}, {"tradable": False}):
            with self.subTest(change=change):
                quote = self.quote(); quote.update(change)
                old = deepcopy(self.engine._get("paper_marks", {}))
                with self.assertRaisesRegex(ValueError, "30秒"):
                    self.engine.paper_mark({"US.AAPL": quote}, day="2026-09-29", observed_at_utc=self.CLOCK.isoformat())
                self.assertEqual(self.engine._get("paper_marks", {}), old)


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



class ResetOrderIdentityTests(unittest.TestCase):
    setUp = EngineSafetyTests.setUp
    close_engines = EngineSafetyTests.close_engines
    engine = EngineSafetyTests.engine
    ready = EngineSafetyTests.ready

    def prepared(self):
        import hashlib
        engine, broker = self.ready(PartialBrokerFixture())
        now = datetime.now(timezone.utc)
        plan = dict(reset_id="reset-test", source_hash="frozen-reset-source")
        metadata = dict(next_open_utc=(now - timedelta(seconds=1)).isoformat(),
            signal_close_utc="2026-10-02T20:00:00Z")
        fingerprint = lambda v: hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        record = dict(reset_id="reset-test", account_id="sim-one", signal_date="2026-10-02",
            stage="ARMED", post_liquidation_baseline=None, unused_cash=0,
            plan_sha256=fingerprint(plan), metadata_sha256=fingerprint(metadata))
        engine._set("best_plan", dict(plan=plan, metadata=metadata))
        engine._set("best_capital", dict(account_id="sim-one", budget=10000, unused_cash=0))
        engine._set("best_full_liquidation_reset", record)
        source = dict(kind="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN", reset_id="reset-test",
            signal_date="2026-10-02", phase="SELL", source_hash=plan["source_hash"],
            budget=10000, **metadata)
        return engine, broker, source, record, now

    def install(self, engine, source, stamp, target):
        engine.import_strategy(manifest(strategy_id="HGB_DIAG_5", asof=stamp,
            targets=[dict(code="US.AAPL", target_qty=target)], source=json.dumps(source)))
        engine.switch("HGB_DIAG_5")

    def confirmed(self, engine, record, now):
        record.update(stage="REBUYING", post_liquidation_baseline=dict(reset_id="reset-test",
            account_id="sim-one", cash=10000, equity=10000, positions={},
            asof=now.isoformat(), valuation_basis="ACTUAL_POST_LIQUIDATION_CASH"))
        engine._set("best_full_liquidation_reset", record)

    def test_confirmed_reset_sell_and_buy_same_clock_have_distinct_ids(self):
        engine, broker, source, record, now = self.prepared()
        stamp = now.isoformat()
        broker.positions["US.AAPL"] = dict(qty=1, sellable=1, market_value=200)
        self.install(engine, source, stamp, 0)
        sell = engine.preview(allow_partial_quotes=True)["orders"][0]
        broker.positions = {}
        self.confirmed(engine, record, now)
        source["phase"] = "BUY"
        self.install(engine, source, stamp, 1)
        buy = engine.preview(allow_partial_quotes=True)["orders"][0]
        self.assertNotEqual(sell["id"], buy["id"])
        self.assertEqual((sell["side"], buy["side"]), ("SELL", "BUY"))
        self.assertEqual(broker.submissions, [])

    def test_reset_origin_without_matching_original_account_is_rejected(self):
        engine, broker, source, record, now = self.prepared()
        record["account_id"] = "another-sim"
        engine._set("best_full_liquidation_reset", record)
        self.install(engine, source, now.isoformat(), 0)
        with self.assertRaisesRegex(ValueError, "SIMULATE_RESET_ORDER_IDENTITY_MISMATCH"):
            engine.preview(allow_partial_quotes=True)
        self.assertEqual(broker.submissions, [])

    def test_buy_before_flat_and_sell_after_baseline_are_rejected(self):
        engine, broker, source, record, now = self.prepared()
        source["phase"] = "BUY"
        self.install(engine, source, now.isoformat(), 1)
        with self.assertRaisesRegex(ValueError, "BUY_REQUIRES_CONFIRMED_LIQUIDATION"):
            engine.preview(allow_partial_quotes=True)
        self.confirmed(engine, record, now)
        source["phase"] = "SELL"
        self.install(engine, source, now.isoformat(), 0)
        with self.assertRaisesRegex(ValueError, "SELL_REQUIRES_UNFINISHED_FULL_LIQUIDATION"):
            engine.preview(allow_partial_quotes=True)
        self.assertEqual(broker.submissions, [])

    def test_changed_source_and_nonzero_liquidation_target_are_rejected(self):
        engine, broker, source, record, now = self.prepared()
        self.install(engine, source, now.isoformat(), 1)
        with self.assertRaisesRegex(ValueError, "SELL_REQUIRES_UNFINISHED_FULL_LIQUIDATION"):
            engine.preview(allow_partial_quotes=True)
        source["source_hash"] = "changed"
        self.install(engine, source, now.isoformat(), 0)
        with self.assertRaisesRegex(ValueError, "SOURCE_BINDING_CHANGED"):
            engine.preview(allow_partial_quotes=True)
        self.assertEqual(broker.submissions, [])

    def test_paper_batch_identity_is_unique_across_restarted_epochs(self):
        engine = self.engine()
        original = engine._paper_batch_id("HGB_DIAG_5", "2026-10-02", "2026-10-05")
        engine._set("paper_epoch_id", "reset-one")
        first = engine._paper_batch_id("HGB_DIAG_5", "2026-10-02", "2026-10-05")
        engine._set("paper_epoch_id", "reset-two")
        second = engine._paper_batch_id("HGB_DIAG_5", "2026-10-02", "2026-10-05")
        self.assertEqual(len({original, first, second}), 3)
        self.assertEqual(second, engine._paper_batch_id("HGB_DIAG_5", "2026-10-02", "2026-10-05"))


class AutomaticPaperCompletionTests(unittest.TestCase):
    """Standing completion uses only synthetic ledgers and original paper batches."""
    setUp = PartialPaperExecutionTests.setUp
    def quotes(self, codes, clock=None, **changes):
        values=PartialPaperExecutionTests.quotes(self,codes,clock)
        for quote in values.values():quote.update(changes)
        return values

    rebalance = PartialPaperExecutionTests.rebalance
    OPEN = PartialPaperExecutionTests.OPEN
    CLOSE = PartialPaperExecutionTests.CLOSE

    def automatic(self, **changes):
        self.OPEN = datetime(2026, 9, 29, 13, 30, tzinfo=timezone.utc)
        self.auto_close = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)
        self.auto_primary = dict(schema_version=1, enabled=True, policy_id="synthetic_auto_20260929",
            reason="USER_EXPLICIT_DAILY_AUTO_COMPLETION", authorized_at_utc=self.CLOSE.isoformat(),
            effective_execution_date="2026-09-29", evaluation_end_exclusive="2027-01-01",
            priority_window_seconds=600, close_buffer_seconds=600, one_tick_spread=True,
            normal_spread_bps=50, max_single_tick_spread_bps=200, quote_max_age_seconds=30,
            price_deviation_fraction=.02, active_strategy_ids=["HGB_DIAG_5","HGB_FACTOR_5"],
            broker_account_id="3604", broker_budget=10000, **{})
        self.auto_primary.update(changes)
        self.engine.automatic_completion_policy_provider = lambda: self.auto_primary
        self.engine._set("automatic_completion_policy", self.auto_primary)
        self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",
            (self.auto_primary["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",
             json.dumps(self.auto_primary)))
        self.engine.db.commit()
        return self.auto_primary

    def auto_rebalance(self, quotes, *, clock=None, errors=None, plan=None, **changes):
        options=dict(now=clock or self.OPEN+timedelta(seconds=10), next_open_utc=self.OPEN.isoformat(),
            signal_date="2026-09-28",execution_date="2026-09-29",signal_close_utc=self.CLOSE.isoformat(),
            source_refs={"manifest":"a"*64},allow_partial_quotes=True,quote_errors=errors,
            execution_window_seconds=600,automatic_completion_policy=self.auto_primary,
            next_close_utc=self.auto_close.isoformat())
        options.update(changes)
        return self.engine.paper_rebalance("HGB_DIAG_5",plan or self.plan,quotes,**options)

    def test_automatic_afternoon_quote_resumes_original_batch_and_preserves_fills(self):
        self.automatic()
        first=self.auto_rebalance(self.quotes(["US.AAPL"]),errors={"US.MSFT":"missing"})
        old=deepcopy(self.engine.paper_trades())
        clock=self.OPEN+timedelta(hours=4)
        resumed=self.auto_rebalance(self.quotes(["US.MSFT"],clock),clock=clock)
        self.assertEqual(resumed["status"],"EXECUTED")
        self.assertEqual((resumed["batch_id"],resumed["source_plan_sha256"],resumed["pretrade_equity"]),
                         (first["batch_id"],first["source_plan_sha256"],first["pretrade_equity"]))
        self.assertEqual(self.engine.paper_trades()[0],old[0])
        self.assertEqual(self.engine.paper_trades()[-1]["filled_at"],clock.isoformat())
        again=self.auto_rebalance(self.quotes(["US.MSFT"],clock),clock=clock)
        self.assertEqual(again["new_fill_count"],0)
        self.assertEqual(len(self.engine.paper_trades()),2)
        self.assertIsNone(self.engine._get("paper_same_day_catchup",None))

    def test_automatic_first_qualified_quotes_can_arrive_after_priority_window(self):
        self.automatic()
        clock=self.OPEN+timedelta(hours=1)
        result=self.auto_rebalance(self.quotes(["US.AAPL","US.MSFT"],clock),clock=clock)
        self.assertEqual(result["status"],"EXECUTED")
        self.assertEqual(result["pretrade_equity"],10000)
        self.assertEqual(result["source_plan"],self.plan)
        self.assertTrue(all(row["filled_at"]==clock.isoformat() for row in self.engine.paper_trades()))

    def test_automatic_early_close_and_exclusive_close_buffer(self):
        self.automatic()
        self.auto_close=datetime(2026,9,29,17,0,tzinfo=timezone.utc)
        cutoff=self.auto_close-timedelta(seconds=600)
        result=self.auto_rebalance(self.quotes(["US.AAPL"],cutoff-timedelta(seconds=1)),
                                   clock=cutoff-timedelta(seconds=1))
        self.assertEqual(result["new_fill_count"],1)
        before=deepcopy(self.engine._get("paper",{}))
        with self.assertRaisesRegex(ValueError,"WINDOW_CLOSED"):
            self.auto_rebalance(self.quotes(["US.MSFT"],cutoff),clock=cutoff)
        self.assertEqual(self.engine._get("paper",{}),before)
        self.assertEqual(len(self.engine.paper_trades()),1)

    def test_automatic_one_actual_tick_can_pass_above_50bp(self):
        self.automatic()
        quote=self.quotes(["US.AAPL"],price=1.605,bid=1.60,ask=1.61,price_tick=.01)
        result=self.auto_rebalance(quote)
        self.assertIn("US.AAPL",result["processed_codes"])
        self.assertEqual(self.engine.paper_trades()[0]["quote_price_tick"],.01)

    def test_automatic_wide_multitick_stale_deviation_and_bad_security_never_fill(self):
        self.automatic()
        cases=[
            dict(price=1.605,bid=1.60,ask=1.61),
            dict(price=1.605,bid=1.60,ask=1.61,price_tick=.005),
            dict(price=1.605,bid=1.60,ask=1.61,price_tick=.01,tick_size=.02),
            dict(price=.405,bid=.40,ask=.41,price_tick=.01),
            dict(price=1.60,bid=1.70,ask=1.70,price_tick=.01),
            dict(asof=(self.OPEN-timedelta(seconds=1)).isoformat()),
            dict(asof=(self.OPEN+timedelta(seconds=100)).isoformat()),
            dict(tradable=False),dict(currency="HKD"),dict(lot_size=100)]
        for changes in cases:
            with self.subTest(changes=changes):
                result=self.auto_rebalance(self.quotes(["US.AAPL"],**changes))
                self.assertEqual(result["new_fill_count"],0)
                self.assertEqual(self.engine.paper_trades(),[])
                self.assertNotIn("US.AAPL",result["processed_codes"])
        self.assertEqual(self.engine._get("paper",{})["cash"],10000)

    def test_automatic_one_tick_opt_out_uses_normal_spread(self):
        self.automatic(one_tick_spread=False)
        result=self.auto_rebalance(self.quotes(["US.AAPL"],price=1.605,bid=1.60,ask=1.61,price_tick=.01))
        self.assertEqual(result["new_fill_count"],0)
        self.assertEqual(self.engine.paper_trades(),[])

    def test_automatic_cash_wait_keeps_fixed_target_then_sale_funds_residual_buy(self):
        self.automatic()
        self.engine._set("paper",dict(cash=1000,positions={"US.MSFT":90},fees=0))
        self.engine.paper_mark({"US.MSFT":dict(price=100,asof=self.CLOSE.isoformat(),
            source="CANONICAL_RAW_USD_CLOSE")},basis="SIGNAL_CLOSE")
        plan=dict(source_date="2026-09-28",target_cash_weight=.5,
            rows=[dict(code="US.AAPL",target_weight=.5),dict(code="US.MSFT",target_weight=0)])
        first=self.auto_rebalance(self.quotes(["US.AAPL"]),errors={"US.MSFT":"sale waiting"},plan=plan)
        self.assertEqual(first["pending_targets"]["US.AAPL"],49)
        self.assertEqual(first["processed_codes"],[])
        self.assertEqual(first["status"],"PARTIALLY_EXECUTED")
        self.assertEqual(self.engine._get("paper",{})["positions"]["US.AAPL"],9)
        old=deepcopy(self.engine.paper_trades())
        clock=self.OPEN+timedelta(hours=2)
        quotes=self.quotes(["US.MSFT"],clock)
        quotes.update(self.quotes(["US.AAPL"],clock,price=50,bid=49.95,ask=50.05))
        result=self.auto_rebalance(quotes,clock=clock,plan=plan)
        self.assertEqual(result["status"],"EXECUTED")
        self.assertEqual(result["pending_targets"]["US.AAPL"],49,"fresh lower price cannot increase fixed shares")
        self.assertEqual(self.engine._get("paper",{})["positions"],{"US.AAPL":49})
        self.assertGreaterEqual(self.engine._get("paper",{})["cash"],0)
        self.assertEqual(result["code_fill_counts"],{"US.AAPL":2,"US.MSFT":1})
        fills=self.engine.paper_trades()
        self.assertEqual(fills[0],old[0])
        self.assertEqual(len({row["id"] for row in fills}),3)
        self.assertEqual([row["side"] for row in fills[1:]],["SELL","BUY"])
        self.assertEqual(result["pretrade_equity"],10000)
        again=self.auto_rebalance(quotes,clock=clock,plan=plan)
        self.assertEqual(again["new_fill_count"],0)
        self.assertEqual(self.engine.paper_trades(),fills)

    def test_automatic_final_cash_shortfall_is_not_reported_executed(self):
        self.automatic()
        plan=dict(source_date="2026-09-28",target_cash_weight=0,
            rows=[dict(code="US.AAPL",target_weight=1)])
        quotes=self.quotes(["US.AAPL"],price=100,bid=100,ask=100)
        first=self.auto_rebalance(quotes,plan=plan)
        self.assertEqual(first["pending_targets"]["US.AAPL"],100)
        self.assertEqual(self.engine._get("paper",{})["positions"]["US.AAPL"],99)
        self.assertEqual(first["processed_codes"],[])
        self.assertEqual(first["status"],"PARTIALLY_EXECUTED")
        self.assertIn("CASH_CONSTRAINT",first["reason"])
        second=self.auto_rebalance(quotes,plan=plan)
        self.assertEqual(second["new_fill_count"],0)
        self.assertEqual(second["status"],"PARTIALLY_EXECUTED")
        self.assertEqual(len(self.engine.paper_trades()),1)

    def test_automatic_restart_retains_targets_counts_and_prior_fills(self):
        self.automatic()
        first=self.auto_rebalance(self.quotes(["US.AAPL"]))
        old=deepcopy(self.engine.paper_trades())
        self.engine.close()
        with patch("moomoo_component.core.now_iso",return_value=self.CLOSE.isoformat()):
            self.engine=Engine(self.folder,paper_only=True,paper_account_id="partial-paper")
        self.engine.automatic_completion_policy_provider=lambda:self.auto_primary
        clock=self.OPEN+timedelta(hours=2)
        result=self.auto_rebalance(self.quotes(["US.MSFT"],clock),clock=clock)
        self.assertEqual(result["batch_id"],first["batch_id"])
        self.assertEqual(self.engine.paper_trades()[0],old[0])
        self.assertEqual(result["code_fill_counts"],{"US.AAPL":1,"US.MSFT":1})

    def test_automatic_policy_projection_audit_and_owner_mismatch_block_without_fills(self):
        self.automatic()
        old=self.engine._get("paper",{"cash":10000,"positions":{}})
        for change in ("projection","audit","owner"):
            with self.subTest(change=change):
                if change=="projection":
                    self.engine._set("automatic_completion_policy",{**self.auto_primary,"enabled":False})
                elif change=="audit":
                    self.engine._set("automatic_completion_policy",self.auto_primary)
                    self.engine.db.execute("DELETE FROM audit WHERE event='AUTOMATIC_COMPLETION_POLICY_AUTHORIZED'")
                    self.engine.db.commit()
                else:
                    self.engine.automatic_completion_policy_provider=lambda:None
                with self.assertRaisesRegex(ValueError,"AUTOMATIC_COMPLETION"):
                    self.auto_rebalance(self.quotes(["US.AAPL"]))
                self.assertEqual(self.engine.paper_trades(),[])
                self.assertEqual(self.engine._get("paper",{"cash":10000,"positions":{}}),old)

    def test_automatic_source_plan_session_and_signal_changes_do_not_create_extra_fills(self):
        self.automatic()
        self.auto_rebalance(self.quotes(["US.AAPL"]))
        old=deepcopy(self.engine.paper_trades())
        clock=self.OPEN+timedelta(hours=1)
        for change in ("source","plan","session","future"):
            with self.subTest(change=change):
                options=dict(clock=clock)
                if change=="source":options["source_refs"]={"manifest":"b"*64}
                elif change=="plan":
                    options["plan"]={**self.plan,"evidence":"changed"}
                elif change=="session":options["next_close_utc"]=(self.auto_close-timedelta(hours=1)).isoformat()
                else:options["execution_date"]="2027-01-01"
                with self.assertRaises(ValueError):
                    self.auto_rebalance(self.quotes(["US.MSFT"],clock),**options)
                self.assertEqual(self.engine.paper_trades(),old)

    def test_automatic_commit_wait_rechecks_quote_age_deadline_and_policy(self):
        self.automatic()
        for kind in ("quote","deadline","owner"):
            with self.subTest(kind=kind):
                clock=self.OPEN+timedelta(seconds=10)
                elapsed=31 if kind=="quote" else 2
                if kind=="deadline":clock=self.auto_close-timedelta(seconds=601)
                values=iter([0.0,float(elapsed)])
                if kind=="owner":
                    calls=[0]
                    primary=self.auto_primary
                    def provider():
                        calls[0]+=1
                        return primary if calls[0]==1 else None
                    self.engine.automatic_completion_policy_provider=provider
                with patch("moomoo_component.core.time.monotonic",side_effect=lambda:next(values)):
                    with self.assertRaisesRegex(ValueError,"AUTOMATIC_COMPLETION"):
                        self.auto_rebalance(self.quotes(["US.AAPL"],clock),clock=clock)
                self.assertEqual(self.engine.paper_trades(),[])
                self.assertEqual(self.engine.db.execute("SELECT count(*) FROM paper_batches").fetchone()[0],0)
                self.assertEqual(self.engine._get("paper",{"cash":10000})["cash"],10000)

    def test_automatic_commit_plan_or_source_mutation_rolls_back_all_fills(self):
        self.automatic()
        for field in ("plan","source"):
            with self.subTest(field=field):
                plan=deepcopy(self.plan)
                refs={"manifest":"a"*64}
                calls=[0]
                def monotonic():
                    calls[0]+=1
                    if calls[0]==2:
                        if field=="plan":plan["evidence"]="changed after validation"
                        else:refs["manifest"]="b"*64
                    return float(calls[0]-1)
                with patch("moomoo_component.core.time.monotonic",side_effect=monotonic):
                    with self.assertRaisesRegex(ValueError,"EXPIRED_BEFORE_COMMIT"):
                        self.auto_rebalance(self.quotes(["US.AAPL"]),plan=plan,source_refs=refs)
                self.assertEqual(self.engine.paper_trades(),[])
                self.assertEqual(self.engine.db.execute("SELECT count(*) FROM paper_batches").fetchone()[0],0)
                self.assertEqual(self.engine._get("paper",{"cash":10000})["cash"],10000)

    def test_legacy_cash_constraint_keeps_original_one_decision_behavior(self):
        self.automatic()
        self.engine._set("paper",dict(cash=1000,positions={"US.MSFT":90},fees=0))
        self.engine.paper_mark({"US.MSFT":dict(price=100,asof=self.CLOSE.isoformat(),
            source="CANONICAL_RAW_USD_CLOSE")},basis="SIGNAL_CLOSE")
        plan=dict(source_date="2026-09-28",target_cash_weight=.5,
            rows=[dict(code="US.AAPL",target_weight=.5),dict(code="US.MSFT",target_weight=0)])
        result=self.rebalance(self.quotes(["US.AAPL"]),plan=plan)
        self.assertIn("US.AAPL",result["processed_codes"])
        self.assertNotIn("pending_targets",result)
        self.assertEqual(len(self.engine.paper_trades()),1)

    def test_automatic_priority_clock_accepts_legacy_open_and_ten_only(self):
        policy=self.automatic();before=self.engine._get('automatic_completion_policy',None)
        for minutes in (0,30):
            with self.subTest(minutes=minutes):
                opening=self.OPEN+timedelta(minutes=minutes)
                ending=self.engine._paper_automatic_completion_end(policy,strategy_id='HGB_DIAG_5',
                    clock=opening+timedelta(seconds=10),opening=opening,closing=self.CLOSE,
                    signal_date='2026-09-28',execution_date='2026-09-29',next_close_utc=self.auto_close.isoformat(),
                    source_refs={'manifest':'a'*64},execution_window_seconds=600)
                self.assertEqual(ending,self.auto_close-timedelta(seconds=600))
        for minutes in (1,31):
            with self.subTest(rejected_minutes=minutes),self.assertRaisesRegex(ValueError,'SESSION_BINDING'):
                opening=self.OPEN+timedelta(minutes=minutes)
                self.engine._paper_automatic_completion_end(policy,strategy_id='HGB_DIAG_5',
                    clock=opening+timedelta(seconds=10),opening=opening,closing=self.CLOSE,
                    signal_date='2026-09-28',execution_date='2026-09-29',next_close_utc=self.auto_close.isoformat(),
                    source_refs={'manifest':'a'*64},execution_window_seconds=600)
        self.assertEqual(self.engine._get('automatic_completion_policy',None),before)
        self.assertEqual(self.engine.paper_trades(),[])

    def test_schema_two_priority_accepts_only_0955_and_1500_without_policy_mutation(self):
        policy=self.automatic(schema_version=2,execution_delay_minutes=25,priority_window_seconds=1500)
        before=deepcopy(policy)
        for minutes,window in ((0,1500),(30,1500),(25,600),(25,1501)):
            opening=self.OPEN+timedelta(minutes=minutes)
            with self.subTest(minutes=minutes,window=window),self.assertRaisesRegex(ValueError,"SESSION_BINDING"):
                self.engine._paper_automatic_completion_end(policy,strategy_id="HGB_DIAG_5",
                    clock=opening+timedelta(seconds=10),opening=opening,closing=self.CLOSE,
                    signal_date="2026-09-28",execution_date="2026-09-29",next_close_utc=self.auto_close.isoformat(),
                    source_refs={"manifest":"a"*64},execution_window_seconds=window)
        opening=self.OPEN+timedelta(minutes=25)
        end=self.engine._paper_automatic_completion_end(policy,strategy_id="HGB_DIAG_5",
            clock=opening+timedelta(seconds=10),opening=opening,closing=self.CLOSE,
            signal_date="2026-09-28",execution_date="2026-09-29",next_close_utc=self.auto_close.isoformat(),
            source_refs={"manifest":"a"*64},execution_window_seconds=1500)
        self.assertEqual(end,opening+timedelta(seconds=1500))
        for too_early_close in (opening+timedelta(seconds=1499),opening+timedelta(seconds=1500)):
            with self.subTest(session_close=too_early_close),self.assertRaisesRegex(ValueError,"SESSION_BINDING"):
                self.engine._paper_automatic_completion_end(policy,strategy_id="HGB_DIAG_5",
                    clock=opening+timedelta(seconds=10),opening=opening,closing=self.CLOSE,
                    signal_date="2026-09-28",execution_date="2026-09-29",next_close_utc=too_early_close.isoformat(),
                    source_refs={"manifest":"a"*64},execution_window_seconds=1500)
        self.assertEqual(self.engine._get("automatic_completion_policy",None),before)
        for sid in ("RAW_A2","R10_DIRECT_MEAN4_ELASTICNET_MID","R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR"):
            with self.subTest(strategy_id=sid):
                self.assertIsNone(self.engine._automatic_completion_policy(opening,sid,execution_date="2026-09-29"))
        self.assertEqual(self.engine.paper_trades(),[])

    def test_schema_two_real_paper_rebalance_keeps_fills_inside_hard_window(self):
        self.automatic(schema_version=2,execution_delay_minutes=25,priority_window_seconds=1500)
        self.OPEN+=timedelta(minutes=25)
        before=deepcopy(self.auto_primary)
        early=self.OPEN-timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,"WINDOW_CLOSED"):
            self.auto_rebalance(self.quotes(["US.AAPL"],early),clock=early,execution_window_seconds=1500)
        first=self.auto_rebalance(self.quotes(["US.AAPL"]),execution_window_seconds=1500)
        old=deepcopy(self.engine.paper_trades())
        clock=self.OPEN+timedelta(seconds=1499)
        result=self.auto_rebalance(self.quotes(["US.MSFT"],clock),clock=clock,execution_window_seconds=1500)
        self.assertEqual(result["status"],"EXECUTED")
        self.assertEqual(result["batch_id"],first["batch_id"])
        self.assertEqual(self.engine.paper_trades()[0],old[0])
        self.assertEqual(self.engine.paper_trades()[-1]["filled_at"],clock.isoformat())
        self.assertEqual(self.auto_primary,before)
        self.assertIsNone(self.engine._get("paper_same_day_catchup",None))

    def test_schema_two_hard_deadline_blocks_unfilled_targets_at_1020_and_1100(self):
        self.automatic(schema_version=2,execution_delay_minutes=25,priority_window_seconds=1500)
        self.OPEN+=timedelta(minutes=25)
        first=self.auto_rebalance(self.quotes(["US.AAPL"]),execution_window_seconds=1500)
        before=deepcopy(self.engine.paper_trades())
        self.assertEqual(len(before),1)
        for clock in (self.OPEN+timedelta(seconds=1500),self.OPEN+timedelta(minutes=65)):
            with self.subTest(clock=clock),self.assertRaisesRegex(ValueError,"WINDOW_CLOSED"):
                self.auto_rebalance(self.quotes(["US.MSFT"],clock),clock=clock,execution_window_seconds=1500)
            self.assertEqual(self.engine.paper_trades(),before)
            frozen=self.engine.db.execute("SELECT payload FROM paper_batches WHERE id=?",(first["batch_id"],)).fetchone()
            self.assertEqual(json.loads(frozen[0])["processed_codes"],["US.AAPL"])
        self.assertIsNone(self.engine._get("paper_same_day_catchup",None))

    def test_ten_priority_clock_never_transfers_hgb_afternoon_permission(self):
        self.automatic();opening=self.OPEN+timedelta(minutes=30)
        for sid in ('RAW_A2','R10_DIRECT_MEAN4_ELASTICNET_MID','R10_DIRECT_H5_RIDGE_MID','R7_GROSS_LINEAR'):
            with self.subTest(strategy_id=sid):
                self.assertIsNone(self.engine._automatic_completion_policy(opening,sid,execution_date='2026-09-29'))
                clock=opening+timedelta(seconds=600)
                with self.assertRaisesRegex(ValueError,'MISSED_OPEN'):
                    self.engine.paper_rebalance(sid,self.plan,self.quotes(['US.AAPL'],clock),now=clock,
                        next_open_utc=opening.isoformat(),signal_date='2026-09-28',execution_date='2026-09-29',
                        signal_close_utc=self.CLOSE.isoformat(),source_refs={'manifest':'a'*64},allow_partial_quotes=True,
                        execution_window_seconds=600,automatic_completion_policy=self.auto_primary,
                        next_close_utc=self.auto_close.isoformat())
        self.assertEqual(self.engine.paper_trades(),[])

    def test_automatic_ineffective_policy_and_legacy_path_keep_original_windows_and_50bp(self):
        self.automatic(effective_execution_date="2026-09-30")
        quote=self.quotes(["US.AAPL"],price=1.605,bid=1.60,ask=1.61,price_tick=.01)
        result=self.auto_rebalance(quote)
        self.assertEqual(result["new_fill_count"],0)
        clock=self.OPEN+timedelta(minutes=11)
        with self.assertRaisesRegex(ValueError,"MISSED_OPEN"):
            self.auto_rebalance(self.quotes(["US.AAPL"],clock),clock=clock)
        result=self.rebalance(quote)
        self.assertEqual(result["new_fill_count"],0)
        self.assertEqual(self.engine.paper_trades(),[])



class OrdinaryTwentyFiveMinuteWindowTests(unittest.TestCase):
    quotes = PartialPaperExecutionTests.quotes

    def test_real_paper_window_is_0955_to_exclusive_1020_across_dst(self):
        from zoneinfo import ZoneInfo
        ny=ZoneInfo("America/New_York")
        for signal,execution,opening_text,closing_text in (
            ("2026-10-29","2026-10-30","2026-10-30T13:55:00+00:00","2026-10-29T20:00:00+00:00"),
            ("2026-10-30","2026-11-02","2026-11-02T14:55:00+00:00","2026-10-30T20:00:00+00:00")):
            with self.subTest(execution_date=execution),tempfile.TemporaryDirectory() as folder:
                opening=datetime.fromisoformat(opening_text);closing=datetime.fromisoformat(closing_text)
                self.OPEN=opening
                self.assertEqual((opening.astimezone(ny).hour,opening.astimezone(ny).minute),(9,55))
                end=opening+timedelta(seconds=1500)
                self.assertEqual((end.astimezone(ny).hour,end.astimezone(ny).minute),(10,20))
                with patch("moomoo_component.core.now_iso",return_value=closing.isoformat()):
                    engine=Engine(Path(folder)/"ordinary",paper_only=True,paper_account_id="synthetic-ordinary")
                try:
                    plan=dict(source_date=signal,target_cash_weight=0,
                        rows=[dict(code="US.AAPL",target_weight=.4),dict(code="US.MSFT",target_weight=.6)])
                    def execute(clock,window=1500,scheduled=None):
                        return engine.paper_rebalance("R10_DIRECT_H5_RIDGE_MID",plan,self.quotes(["US.AAPL","US.MSFT"],clock),
                            now=clock,next_open_utc=(scheduled or opening).isoformat(),signal_date=signal,execution_date=execution,
                            signal_close_utc=closing.isoformat(),source_refs={"manifest":"a"*64},
                            allow_partial_quotes=True,execution_window_seconds=window)
                    for rejected in (opening-timedelta(seconds=1),end):
                        with self.subTest(rejected=rejected),self.assertRaisesRegex(ValueError,"MISSED_OPEN"):
                            execute(rejected)
                    for bad_window in (0,601,1499,1501,3600,3601,True,1500.0):
                        with self.subTest(bad_window=bad_window),self.assertRaises(ValueError):
                            execute(opening+timedelta(seconds=1),bad_window)
                    for delta in (-25,5):
                        wrong_opening=opening+timedelta(minutes=delta)
                        with self.subTest(wrong_opening=wrong_opening),self.assertRaisesRegex(ValueError,"CLOCK_PAIR"):
                            execute(wrong_opening+timedelta(seconds=1),scheduled=wrong_opening)
                    self.assertEqual(engine.paper_trades(),[])
                    clock=end-timedelta(seconds=1)
                    result=execute(clock)
                    self.assertEqual(result["status"],"EXECUTED")
                    self.assertEqual(result["new_fill_count"],2)
                    self.assertTrue(all(row["filled_at"]==clock.isoformat() for row in engine.paper_trades()))
                    before=deepcopy(engine.paper_trades())
                    with self.assertRaisesRegex(ValueError,"MISSED_OPEN"):execute(end)
                    self.assertEqual(engine.paper_trades(),before)
                finally:
                    engine.close()


if __name__ == "__main__":
    unittest.main()
