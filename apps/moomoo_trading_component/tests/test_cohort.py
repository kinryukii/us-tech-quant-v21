"""Calendar-gated, isolated paper accounting. All sources/quotes are offline fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from moomoo_component.cohort import Cohort, STRATEGIES
from moomoo_component.core import Engine


OPEN = datetime(2026, 9, 29, 13, 30, tzinfo=timezone.utc)
CLOSE = datetime(2026, 9, 28, 20, tzinfo=timezone.utc)
CODES = ["US.A" + letter for letter in "ABCDEFGHIJKLMNOPQRST"]


class Source:
    def __init__(self):
        self.loads = []
        self.close_inputs = []
        self.refresh_count = 0
        self.missing = False
        self.refresh_error = None
        self.prices = {code: 100 for code in CODES}
        self.weights = {
            "RAW_A2": {code: .05 for code in CODES},
            "HGB_DIAG_5": {code: .06 for code in CODES[:10]},
            "HGB_FACTOR_5": {code: .04 for code in CODES[:8]},
        }

    def status(self, now=None):
        status = "READY" if now < OPEN else "OPEN_WINDOW" if now < OPEN + timedelta(seconds=60) else "MISSED_OPEN"
        if self.missing:
            status = "WAITING_SOURCE"
        return dict(status=status, reason="fixture", signal_date="2026-09-28", source_date="2026-09-28",
                    execution_date="2026-09-29", signal_close_utc=CLOSE.isoformat(),
                    next_open_utc=OPEN.isoformat(), next_close_utc="2026-09-29T20:00:00+00:00",
                    source_refs={"manifest": "a" * 64}, data_gaps=["missing"] if self.missing else [])

    def close_states(self, books, signal_date):
        self.close_inputs.append(deepcopy(books))
        result = {}
        for sid, book in books.items():
            prices = {code: self.prices.get(code, 100) for code in book["positions"]}
            equity = book["cash"] + sum(qty * prices[code] for code, qty in book["positions"].items())
            result[sid] = dict(signal_date=signal_date, valuation_basis="SIGNAL_CLOSE", equity=equity,
                               cash_weight=book["cash"] / equity,
                               weights={code.removeprefix("US."): qty * prices[code] / equity
                                        for code, qty in book["positions"].items()},
                               prices=prices, source_refs={"close": "b" * 64}, close_asof_utc=CLOSE.isoformat())
        return result

    def load(self, states, now=None):
        self.loads.append(deepcopy(states))
        result = self.status(now)
        result["plans"] = {sid: dict(source_date=result["signal_date"], target_cash_weight=1 - sum(weights.values()),
            account_basis="SIGNAL_CLOSE", rows=[dict(code=code, ticker=code[3:], target_weight=weight,
                                                   weight_before=states[sid]["weights"].get(code[3:], 0))
                                                for code, weight in weights.items()])
                           for sid, weights in self.weights.items()}
        return result

    def refresh(self):
        self.refresh_count += 1
        if self.refresh_error:
            raise self.refresh_error
        self.missing = False


class Quotes:
    def __init__(self):
        self.clock = OPEN + timedelta(seconds=10)
        self.calls = []
        self.error = None
        self.errors = {}
        self.overrides = {}
        self.closed = False
        self.prewarm_calls = []
        self.prewarm_error = None

    def prewarm(self, codes):
        self.prewarm_calls.append(list(codes))
        if self.prewarm_error:
            raise self.prewarm_error

    def quotes_partial(self, codes):
        self.calls.append(list(codes))
        quotes, errors = {}, {}
        for code in codes:
            error = self.error or self.errors.get(code)
            if error:
                errors[code] = str(error)
            else:
                quotes[code] = {**dict(price=100, bid=100, ask=100, asof=self.clock.isoformat(),
                    tradable=True, lot_size=1, source="MOOMOO_OPEND", currency="USD", market="US"),
                    **self.overrides.get(code, {})}
        return {"quotes": quotes, "errors": errors}

    def quotes(self, codes):
        self.calls.append(list(codes))
        if self.error:
            raise self.error
        for code in codes:
            if code in self.errors:
                raise self.errors[code]
        return {code: {**dict(price=100, bid=100, ask=100, asof=self.clock.isoformat(),
                           tradable=True, lot_size=1, source="MOOMOO_OPEND", currency="USD", market="US",
                           ), **self.overrides.get(code, {})} for code in codes}

    def close(self):
        self.closed = True


class NoWorker:
    """A manual test clock drives tick; no daemon or real-time wait is started."""
    def __init__(self, **kwargs):
        pass

    def start(self):
        pass

    def is_alive(self):
        return False

    def join(self, **kwargs):
        pass


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        inception = patch("moomoo_component.core.now_iso", return_value=(CLOSE - timedelta(hours=6)).isoformat())
        inception.start()
        self.addCleanup(inception.stop)
        self.source, self.quotes = Source(), Quotes()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.addCleanup(lambda: self.cohort.close() if not self.cohort.closed else None)

    def start(self):
        with patch("moomoo_component.cohort.threading.Thread", NoWorker):
            self.cohort.start()

    def tick(self, clock=OPEN + timedelta(seconds=10)):
        self.quotes.clock = clock
        return self.cohort.tick(now=clock)

    def reopen(self, delay=None, window=None, partial=None):
        self.cohort.close()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes,
                             execution_delay_minutes=delay, execution_window_seconds=window,
                             allow_partial_quotes=partial)

    def test_delay_validation_rejects_invalid_values_before_creating_runtime(self):
        for index, value in enumerate((True, False, -1, 181, 45.0, "45")):
            with self.subTest(value=value):
                path = Path(self.temp.name) / ("invalid-delay-" + str(index))
                with self.assertRaises(ValueError):
                    Cohort(path, self.source, self.quotes, execution_delay_minutes=value)
                self.assertFalse(path.exists())

    def test_subscription_prewarm_is_early_rth_only_and_never_quote_or_fill(self):
        self.reopen(45, 600, True)
        self.start()
        self.tick(OPEN - timedelta(minutes=1))
        self.tick(OPEN + timedelta(minutes=39))
        self.assertEqual(self.quotes.prewarm_calls, [])
        self.cohort.engines['RAW_A2']._set('paper', {'cash': 9900, 'positions': {'US.ZZ': 1}, 'fees': 0})
        self.cohort._prewarm(self.source.status(now=OPEN + timedelta(minutes=40)),
                            OPEN + timedelta(minutes=40), OPEN + timedelta(minutes=45))
        state = self.cohort.state()
        plans = deepcopy(self.cohort.plans)
        self.assertEqual(set(self.quotes.prewarm_calls[0]), set(CODES) | {'US.ZZ'})
        self.assertEqual(state['subscription_prewarm']['status'], 'SUBSCRIBED')
        self.assertNotIn('asof', state['subscription_prewarm'])
        self.assertEqual(self.quotes.calls, [])
        self.assertEqual(state['trades'], [])
        self.assertIsNone(state.get('quote_asof'))
        self.tick(OPEN + timedelta(minutes=44))
        self.assertEqual(len(self.quotes.prewarm_calls), 1)
        self.assertEqual(self.cohort.plans, plans)

    def test_zero_delay_warms_subscription_before_open_without_quote_or_fill(self):
        self.reopen(0, 600, True)
        self.start()
        self.tick(OPEN - timedelta(minutes=6))
        self.assertEqual(self.quotes.prewarm_calls, [])
        waiting = self.tick(OPEN - timedelta(minutes=5))
        self.assertEqual(waiting["status"], "WAITING_OPEN")
        self.assertEqual(len(self.quotes.prewarm_calls), 1)
        self.assertEqual(self.quotes.calls, [])
        self.assertEqual(waiting["trades"], [])
        self.assertEqual(self.tick(OPEN)["status"], "EXECUTED")

    def test_opening_poll_delay_is_bounded_and_preserves_actual_clock(self):
        self.cohort.meta["execution_time_utc"] = OPEN.isoformat()
        for offset, expected in ((-60, 30.0), (-30, 1.0), (-.2, .2), (0, 1.0), (59, 1.0), (60, 30.0)):
            with self.subTest(offset=offset):
                self.assertAlmostEqual(self.cohort._poll_delay(OPEN + timedelta(seconds=offset)), expected)
        self.assertEqual(self.cohort.meta["execution_time_utc"], OPEN.isoformat())

    def test_subscription_prewarm_failure_cools_down_and_restart_resubscribes(self):
        self.reopen(45)
        self.start()
        self.quotes.prewarm_error = ValueError('subscription permission unavailable')
        first = self.tick(OPEN + timedelta(minutes=40))
        self.assertEqual(first['status'], 'WAITING_OPEN')
        self.assertEqual(first['subscription_prewarm']['status'], 'ERROR')
        self.tick(OPEN + timedelta(minutes=40, seconds=29))
        self.assertEqual(len(self.quotes.prewarm_calls), 1)
        self.quotes.prewarm_error = None
        self.tick(OPEN + timedelta(minutes=40, seconds=30))
        self.assertEqual(len(self.quotes.prewarm_calls), 2)
        self.assertEqual(self.quotes.calls, [])
        self.reopen()
        self.start()
        self.tick(OPEN + timedelta(minutes=41))
        self.assertEqual(len(self.quotes.prewarm_calls), 3)
        self.assertEqual(self.cohort.trades(), [])

    def test_partial_window_recovers_only_missing_codes_and_keeps_original_plan(self):
        self.reopen(45, 600, True)
        self.start()
        scheduled = OPEN + timedelta(minutes=45)
        self.quotes.errors[CODES[-1]] = ValueError('source clock stale')
        first = self.tick(scheduled + timedelta(seconds=10))
        self.assertEqual(first['status'], 'PARTIALLY_EXECUTED')
        raw = first['books']['RAW_A2']
        self.assertEqual(raw['execution']['status'], 'PARTIALLY_EXECUTED')
        self.assertTrue(raw['execution']['skipped'])
        self.assertNotIn(CODES[-1], {row['code'] for row in raw['trades']})
        original = deepcopy(self.cohort.plans)
        first_ids = {row['id'] for row in first['trades']}
        self.assertEqual(len(self.source.loads), 1)
        self.quotes.errors.clear()
        resumed = self.tick(scheduled + timedelta(minutes=5))
        self.assertEqual(resumed['status'], 'EXECUTED')
        new = [row for row in resumed['trades'] if row['id'] not in first_ids]
        self.assertEqual({row['code'] for row in new}, {CODES[-1]})
        self.assertEqual(self.cohort.plans, original)
        self.assertEqual(len(self.source.loads), 1)
        self.assertEqual(len({row['id'] for row in resumed['trades']}), len(resumed['trades']))

    def test_partial_quote_aging_during_read_skips_only_that_code_without_weakening_clock(self):
        self.reopen(45, 600, True)
        self.start()
        scheduled = OPEN + timedelta(minutes=45)
        self.quotes.overrides[CODES[-1]] = {'asof': (scheduled - timedelta(seconds=21)).isoformat()}
        state = self.tick(scheduled + timedelta(seconds=10))
        raw = state['books']['RAW_A2']
        self.assertEqual(raw['status'], 'PARTIALLY_EXECUTED')
        self.assertNotIn(CODES[-1], {row['code'] for row in raw['trades']})
        self.assertEqual(len(raw['trades']), 19)
        self.assertEqual(raw['execution']['skipped'][0]['code'], CODES[-1])
        self.assertIn('过期', raw['execution']['skipped'][0]['reason'])
        self.assertEqual(state['books']['HGB_DIAG_5']['status'], 'EXECUTED')
        self.assertEqual(state['books']['HGB_FACTOR_5']['status'], 'EXECUTED')

    def test_partial_window_restart_freezes_progress_and_never_replays_after_end(self):
        self.reopen(45, 600, True)
        self.start()
        scheduled = OPEN + timedelta(minutes=45)
        self.quotes.errors[CODES[0]] = ValueError('bad quote')
        first = self.tick(scheduled + timedelta(seconds=10))
        frozen = deepcopy(self.cohort.plans)
        committed = deepcopy(first['trades'])
        self.reopen()
        self.start()
        self.assertEqual((self.cohort.execution_window_seconds, self.cohort.allow_partial_quotes), (600, True))
        with patch.object(self.source, 'load', side_effect=AssertionError('partial progress must not reinfer')):
            self.tick(scheduled + timedelta(minutes=1))
        self.assertEqual(self.cohort.plans, frozen)
        self.assertEqual(self.cohort.trades(), committed)
        calls = len(self.quotes.calls)
        expired = self.tick(scheduled + timedelta(seconds=600))
        self.assertEqual(expired['status'], 'PARTIALLY_EXECUTED')
        self.assertEqual(self.cohort.trades(), committed)
        # Only existing positions can be marked after expiry; no missing target is bought.
        self.assertTrue(all(CODES[0] not in codes for codes in self.quotes.calls[calls:]))

    def test_old_missed_signal_remains_missed_under_new_ten_minute_policy(self):
        self.start()
        self.tick(OPEN + timedelta(seconds=60))
        self.reopen(45, 600, True)
        self.start()
        with patch.object(self.quotes, 'quotes_partial', side_effect=AssertionError('expired signal cannot request execution quotes')):
            state = self.tick(OPEN + timedelta(hours=1, minutes=17))
        self.assertEqual(state['status'], 'MISSED_OPEN')
        self.assertEqual(state['trades'], [])
        self.assertEqual(self.quotes.prewarm_calls, [])

    def test_noon_reschedules_only_unfilled_signal_preserving_frozen_plans_and_original_open(self):
        self.reopen(45, 600, True)
        self.start()
        missed = self.tick(OPEN + timedelta(minutes=80))
        self.assertEqual(missed['status'], 'MISSED_OPEN')
        original = deepcopy(self.cohort.plans)
        refs = deepcopy(self.cohort.plan_metadata['source_refs'])
        source_status = self.source.status
        self.source.status = lambda now=None: {**source_status(now), 'execute_now': False}
        self.reopen(150)
        self.start()
        noon = OPEN + timedelta(minutes=150)
        waiting = self.tick(OPEN + timedelta(minutes=130))
        self.assertEqual(waiting['status'], 'WAITING_OPEN')
        self.assertTrue(all(book['status'] == 'WAITING_OPEN' for book in waiting['books'].values()))
        self.assertEqual(waiting['next_open_utc'], OPEN.isoformat())
        self.assertEqual(waiting['execution_time_utc'], noon.isoformat())
        self.assertEqual(waiting['next_expected_execution_utc'], noon.isoformat())
        self.assertEqual((waiting['execution_delay_minutes'], waiting['execution_window_seconds']), (150, 600))
        self.assertEqual(self.tick(noon - timedelta(microseconds=1))['status'], 'WAITING_OPEN')
        self.assertEqual(self.quotes.calls, [])
        executed = self.tick(noon + timedelta(seconds=599, milliseconds=999))
        self.assertEqual(executed['status'], 'EXECUTED')
        self.assertEqual(self.cohort.plans, original)
        self.assertEqual(self.cohort.plan_metadata['source_refs'], refs)
        self.assertEqual(self.cohort.plan_metadata['next_open_utc'], OPEN.isoformat())
        self.assertTrue(all(row['signal_date'] == '2026-09-28' for row in executed['trades']))
        self.reopen()
        self.assertEqual((self.cohort.execution_delay_minutes, self.cohort.execution_window_seconds), (150, 600))

    def test_noon_ten_minute_window_expires_without_catching_up_or_requesting_target_quotes(self):
        self.reopen(150, 600, True)
        self.start()
        noon = OPEN + timedelta(minutes=150)
        self.quotes.error = ValueError('real source clocks stale')
        blocked = self.tick(noon + timedelta(seconds=599))
        self.assertEqual(blocked['trades'], [])
        calls = len(self.quotes.calls)
        state = self.tick(noon + timedelta(seconds=600))
        self.assertEqual(state['status'], 'MISSED_OPEN')
        self.assertEqual(state['trades'], [])
        self.assertEqual(len(self.quotes.calls), calls)
        self.assertEqual(self.tick(noon + timedelta(minutes=20))['status'], 'MISSED_OPEN')
        self.assertEqual(len(self.quotes.calls), calls)

    def test_window_partial_configuration_is_bounded_and_persisted(self):
        for value in (True, 0, -1, 601, 600.0, '600'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Cohort(Path(self.temp.name) / 'bad-window', self.source, self.quotes, execution_window_seconds=value)
        with self.assertRaises(ValueError):
            Cohort(Path(self.temp.name) / 'bad-partial', self.source, self.quotes, allow_partial_quotes='yes')
        self.reopen(45, 600, True)
        self.reopen()
        self.assertEqual((self.cohort.execution_window_seconds, self.cohort.allow_partial_quotes), (600, True))
        rows = self.cohort.db.execute("SELECT detail FROM events WHERE event='EXECUTION_POLICY_CHANGED'").fetchall()
        self.assertEqual(len(rows), 1)

    def test_delayed_window_uses_actual_source_identity_and_keeps_refresh_guard(self):
        self.reopen(45)
        self.start()
        scheduled = OPEN + timedelta(minutes=45)
        state = self.tick(OPEN + timedelta(minutes=20))
        self.assertEqual(state["status"], "WAITING_OPEN")
        self.assertEqual(state["next_open_utc"], OPEN.isoformat())
        self.assertEqual(state["execution_time_utc"], scheduled.isoformat())
        self.assertEqual(state["next_expected_execution_utc"], scheduled.isoformat())
        self.assertEqual((state["execution_delay_minutes"], state["execution_window_seconds"]), (45, 60))
        self.assertEqual(self.quotes.calls, [])
        self.assertEqual(self.source.refresh_count, 0)
        frozen = deepcopy(self.cohort.plans)
        self.assertEqual(self.tick(scheduled - timedelta(microseconds=1))["status"], "WAITING_OPEN")
        self.assertEqual(self.quotes.calls, [])
        executed = self.tick(scheduled)
        self.assertEqual(executed["status"], "EXECUTED")
        self.assertEqual(self.cohort.plans, frozen)
        self.assertEqual(self.cohort.plan_metadata["next_open_utc"], OPEN.isoformat())
        self.assertEqual(self.cohort.plan_metadata["execution_time_utc"], scheduled.isoformat())
        self.assertTrue(all(t["filled_at"] == scheduled.isoformat() for t in executed["trades"]))
        self.assertTrue(all(t["signal_date"] == "2026-09-28" and t["execution_date"] == "2026-09-29"
                            for t in executed["trades"]))

    def test_delayed_window_expires_at_sixty_seconds_without_catchup(self):
        self.reopen(45)
        self.start()
        scheduled = OPEN + timedelta(minutes=45)
        state = self.tick(scheduled + timedelta(seconds=60))
        self.assertEqual(state["status"], "MISSED_OPEN")
        self.assertEqual(state["trades"], [])
        self.assertEqual(self.quotes.calls, [])
        self.assertEqual(self.tick(scheduled + timedelta(minutes=20))["status"], "MISSED_OPEN")
        self.assertEqual(self.quotes.calls, [])

    def test_delayed_window_does_not_accept_the_original_opening_quote(self):
        self.reopen(45)
        self.start()
        self.quotes.overrides[CODES[0]] = {"asof": (OPEN + timedelta(seconds=10)).isoformat()}
        state = self.tick(OPEN + timedelta(minutes=45, seconds=10))
        self.assertEqual(state["trades"], [])
        self.assertTrue(all(b["cash"] == 10000 and not b["positions"] for b in state["books"].values()))
        self.assertIn("过期", state["last_error"])

    def test_delay_persists_across_restart_and_records_only_configuration_changes(self):
        self.reopen(45)
        self.start()
        self.tick(OPEN + timedelta(minutes=20))
        self.reopen()
        self.assertEqual(self.cohort.execution_delay_minutes, 45)
        changes = [json.loads(row[0]) for row in self.cohort.db.execute(
            "SELECT detail FROM events WHERE event='EXECUTION_SCHEDULE_CHANGED'")]
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]["previous_delay_minutes"], changes[0]["execution_delay_minutes"]), (0, 45))
        self.start()
        self.assertEqual(self.tick(OPEN + timedelta(minutes=45, seconds=10))["status"], "EXECUTED")
        committed = self.cohort.trades()
        fees = {sid: b["fees"] for sid, b in self.cohort.state()["books"].items()}
        self.reopen(45)
        self.start()
        calls = len(self.quotes.calls)
        with patch.object(self.source, "load", side_effect=AssertionError("executed signal must not be inferred again")):
            state = self.tick(OPEN + timedelta(minutes=45, seconds=20))
        self.assertEqual(state["status"], "EXECUTED")
        self.assertEqual(self.cohort.trades(), committed)
        self.assertEqual(len(self.quotes.calls), calls)
        self.assertEqual({sid: b["fees"] for sid, b in state["books"].items()}, fees)
        self.assertEqual(self.cohort.db.execute(
            "SELECT count(*) FROM events WHERE event='EXECUTION_SCHEDULE_CHANGED'").fetchone()[0], 1)

    def test_rescheduling_missed_attempt_waits_but_never_reexecutes_a_committed_signal(self):
        self.start()
        missed = self.tick(OPEN + timedelta(seconds=60))
        self.assertEqual(missed["status"], "MISSED_OPEN")
        self.cohort.meta["book_quote_errors"] = {"RAW_A2": "original failed quote"}
        self.cohort._persist()
        self.reopen(45)
        self.start()
        waiting = self.tick(OPEN + timedelta(minutes=20))
        self.assertEqual(waiting["status"], "WAITING_OPEN")
        self.assertTrue(all(book["status"] == "WAITING_OPEN" for book in waiting["books"].values()))
        self.assertEqual(waiting["books"]["RAW_A2"]["execution"]["status"], "MISSED_OPEN")
        self.assertEqual(waiting["books"]["RAW_A2"]["connection_error"], "original failed quote")
        self.assertEqual(self.cohort.db.execute("SELECT count(*) FROM events WHERE event='MISSED_OPEN'").fetchone()[0], 1)
        executed = self.tick(OPEN + timedelta(minutes=45, seconds=10))
        self.assertEqual(executed["status"], "EXECUTED")
        committed = self.cohort.trades()
        self.reopen(150)
        self.start()
        with patch.object(self.source, "load", side_effect=AssertionError("configuration cannot repeat a fill")):
            state = self.tick(OPEN + timedelta(minutes=150, seconds=10))
        self.assertEqual(state["status"], "EXECUTED")
        self.assertEqual(self.cohort.trades(), committed)

    def test_delayed_execution_tracks_dst_from_the_verified_session_open(self):
        winter_open = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
        winter_close = datetime(2026, 10, 30, 20, tzinfo=timezone.utc)

        class WinterSource(Source):
            def status(self, now=None):
                data = super().status(now)
                data.update(status="READY" if now < winter_open else "OPEN_WINDOW" if now < winter_open + timedelta(seconds=60) else "MISSED_OPEN",
                            signal_date="2026-10-30", source_date="2026-10-30", execution_date="2026-11-02",
                            signal_close_utc=winter_close.isoformat(), next_open_utc=winter_open.isoformat(),
                            next_close_utc="2026-11-02T21:00:00+00:00")
                return data

            def close_states(self, books, signal_date):
                states = super().close_states(books, signal_date)
                for state in states.values():
                    state["close_asof_utc"] = winter_close.isoformat()
                return states

        self.source = WinterSource()
        self.reopen(150, 600, True)
        self.start()
        scheduled = winter_open + timedelta(minutes=150)
        self.assertEqual(scheduled.hour, 17)
        from zoneinfo import ZoneInfo
        self.assertEqual((scheduled.astimezone(ZoneInfo('America/New_York')).hour,
                          scheduled.astimezone(ZoneInfo('America/New_York')).minute), (12, 0))
        state = self.tick(scheduled - timedelta(seconds=1))
        self.assertEqual(state["status"], "WAITING_OPEN")
        self.assertEqual(self.quotes.calls, [])
        state = self.tick(scheduled + timedelta(seconds=10))
        self.assertEqual(state["status"], "EXECUTED")
        self.assertEqual(state["next_open_utc"], winter_open.isoformat())
        self.assertEqual(state["execution_time_utc"], scheduled.isoformat())
        self.assertTrue(all(t["execution_date"] == "2026-11-02" for t in state["trades"]))

    def test_missed_cash_session_records_nav_once_without_market_or_order_io(self):
        self.start()
        state = self.tick(OPEN + timedelta(seconds=60))
        self.assertEqual(self.quotes.calls, [])
        originals = {}
        for sid, book in state["books"].items():
            row = next(r for r in book["nav_history"] if r["date"] == "2026-09-29")
            self.assertEqual((row["nav"], row["cash"], row["equity"], row["fees"], row["basis"]),
                             (1.0, 10000.0, 10000.0, 0.0, "CASH_LEDGER"))
            self.assertIsNone(row["asof"])
            self.assertEqual(row["sources"], [])
            originals[sid] = self.cohort.engines[sid].db.execute(
                "SELECT payload FROM paper_nav WHERE day='2026-09-29'").fetchone()[0]
        with patch.object(self.cohort.engines["RAW_A2"], "paper_mark", side_effect=AssertionError("cash day must not be replaced")):
            repeated = self.tick(OPEN + timedelta(hours=2))
        self.assertEqual(self.quotes.calls, [])
        self.assertEqual(repeated["trades"], [])
        for sid, engine in self.cohort.engines.items():
            self.assertEqual(engine.db.execute("SELECT payload FROM paper_nav WHERE day='2026-09-29'").fetchone()[0], originals[sid])
            self.assertEqual(engine.db.execute("SELECT count(*) FROM paper_nav WHERE day='2026-09-29'").fetchone()[0], 1)
            self.assertEqual(engine.db.execute("SELECT count(*) FROM orders").fetchone()[0], 0)

    def test_blocked_cash_nav_preserves_quote_errors_and_frozen_execution_state(self):
        self.start()
        self.quotes.error = ValueError("real feed unavailable")
        blocked = self.tick()
        frozen = deepcopy(self.cohort.plans)
        self.assertEqual(blocked["status"], "BLOCKED")
        calls = len(self.quotes.calls)
        state = self.tick(OPEN + timedelta(minutes=2))
        self.assertEqual(len(self.quotes.calls), calls)
        self.assertEqual(self.cohort.plans, frozen)
        for sid, book in state["books"].items():
            self.assertEqual(book["status"], "MISSED_OPEN")
            self.assertEqual(book["connection_error"], "real feed unavailable")
            row = next(r for r in book["nav_history"] if r["date"] == "2026-09-29")
            self.assertEqual((row["basis"], row["nav"]), ("CASH_LEDGER", 1.0))
            self.assertEqual((book["cash"], book["fees"], book["trade_count"], book["positions"]), (10000, 0, 0, []))

    def test_constructor_and_state_do_not_start_fetch_or_trade(self):
        state = self.cohort.state()
        self.assertFalse(state["running"])
        self.assertEqual(self.quotes.calls, [])
        self.assertEqual(self.source.loads, [])
        self.assertEqual(self.source.refresh_count, 0)
        self.assertEqual(set(state["books"]), set(STRATEGIES))
        for sid, book in state["books"].items():
            self.assertEqual(book["account_id"], "paper-" + sid)
            self.assertEqual(book["cash"], 10000)
            self.assertEqual(book["equity"], 10000)
            self.assertEqual(book["positions"], [])
            with self.assertRaises(ValueError):
                self.cohort.engines[sid].set_mode("moomoo_simulate", "1", "SIMULATE")
            with self.assertRaises(ValueError):
                self.cohort.engines[sid].connect()

    def test_next_open_executes_three_full_independent_books_at_five_bp(self):
        self.start()
        before = self.tick(OPEN - timedelta(seconds=1))
        self.assertEqual(before["status"], "WAITING_OPEN")
        self.assertEqual(before["trades"], [])
        state = self.tick()
        self.assertEqual(state["status"], "EXECUTED")
        raw, diag, factor = [state["books"][sid] for sid in STRATEGIES]
        self.assertEqual(len(raw["positions"]), 20)
        self.assertEqual(len(diag["positions"]), 10)
        self.assertEqual(len(factor["positions"]), 8)
        self.assertEqual(sum(p["market_value"] for p in raw["positions"]), 9900)
        self.assertGreater(raw["cash"], 0)
        self.assertAlmostEqual(raw["fees"], 4.95)
        self.assertAlmostEqual(raw["equity"], 9995.05)
        for trade in state["trades"]:
            self.assertEqual(trade["mode"], "paper")
            self.assertEqual(trade["fee_bps"], 5)
            self.assertAlmostEqual(trade["fee"], trade["qty"] * trade["fill_price"] * .0005)
            self.assertEqual(trade["signal_date"], "2026-09-28")
            self.assertEqual(trade["execution_date"], "2026-09-29")
            self.assertEqual(trade["source"], "MOOMOO_OPEND")
            self.assertEqual(trade["order_status"], "FILLED")
        self.assertEqual(len({b["account_id"] for b in state["books"].values()}), 3)

    def test_window_edge_and_missed_open_never_catch_up(self):
        self.start()
        missed = self.tick(OPEN + timedelta(seconds=60))
        self.assertEqual(missed["status"], "MISSED_OPEN")
        self.assertEqual(missed["trades"], [])
        again = self.tick(OPEN + timedelta(hours=2))
        self.assertEqual(again["status"], "MISSED_OPEN")
        self.assertEqual(again["trades"], [])
        self.assertEqual(self.source.refresh_count, 0)

    def test_stale_future_nontradable_quotes_reject_before_ledger_changes(self):
        self.start()
        for override in ({"asof": (OPEN - timedelta(seconds=1)).isoformat()},
                         {"asof": (OPEN + timedelta(seconds=20)).isoformat()}, {"tradable": False}):
            self.quotes.overrides[CODES[0]] = override
            state = self.tick()
            self.assertEqual(state["status"], "BLOCKED")
            self.assertEqual(state["trades"], [])
            self.assertTrue(all(book["cash"] == 10000 for book in state["books"].values()))
        self.quotes.overrides = {}
        self.assertEqual(self.tick()["status"], "EXECUTED")

    def test_raw_only_missing_book_clock_is_isolated_and_expires_without_fills(self):
        self.start()
        bad = CODES[-1]  # Neither HGB account requires this Raw-only security.
        self.quotes.errors[bad] = ValueError(bad + " 盘口原始更新时间无效")
        state = self.tick()
        raw = state["books"]["RAW_A2"]
        self.assertEqual(raw["status"], "BLOCKED")
        self.assertIn(bad, raw["reason"])
        self.assertEqual((raw["cash"], raw["fees"], raw["trade_count"]), (10000, 0, 0))
        self.assertEqual(raw["positions"], [])
        self.assertEqual(self.cohort.engines["RAW_A2"].db.execute("SELECT count(*) FROM orders").fetchone()[0], 0)
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.assertEqual(state["books"][sid]["status"], "EXECUTED")
            self.assertGreater(state["books"][sid]["trade_count"], 0)
            self.assertEqual(state["books"][sid]["connection_error"], "")
        self.assertIn("RAW_A2", state["reason"])
        self.assertIn("HGB_DIAG_5", state["reason"])
        committed = self.cohort.trades()
        missed = self.tick(OPEN + timedelta(seconds=60))
        self.assertEqual(missed["books"]["RAW_A2"]["status"], "MISSED_OPEN")
        self.assertEqual(missed["books"]["HGB_DIAG_5"]["status"], "EXECUTED")
        self.assertEqual(missed["books"]["HGB_FACTOR_5"]["status"], "EXECUTED")
        self.assertEqual(self.cohort.trades(), committed)

    def test_raw_quote_recovery_retries_only_raw_and_restart_does_not_refill(self):
        self.start()
        self.quotes.errors[CODES[-1]] = ValueError("Raw-only quote unavailable")
        first = self.tick()
        hgb_fills = [row for row in self.cohort.trades() if row["strategy_id"] != "RAW_A2"]
        self.assertEqual(len(hgb_fills), 18)
        frozen = deepcopy(first["books"]["RAW_A2"]["plan"])
        calls = len(self.quotes.calls)
        self.quotes.errors.clear()
        with patch.object(self.source, "load", side_effect=AssertionError("post-fill re-inference forbidden")):
            resumed = self.tick(OPEN + timedelta(seconds=20))
        self.assertEqual(resumed["status"], "EXECUTED")
        self.assertEqual(resumed["books"]["RAW_A2"]["plan"], frozen)
        self.assertEqual(self.quotes.calls[calls:], [sorted(CODES)])
        self.assertEqual([row for row in self.cohort.trades() if row["strategy_id"] != "RAW_A2"], hgb_fills)
        complete = self.cohort.trades()
        self.assertEqual(len(complete), 38)
        self.cohort.close()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.start()
        calls = len(self.quotes.calls)
        with patch.object(self.source, "load", side_effect=AssertionError("restart must keep frozen plan")):
            restarted = self.tick(OPEN + timedelta(seconds=30))
        self.assertEqual(restarted["status"], "EXECUTED")
        self.assertEqual(len(self.quotes.calls), calls)
        self.assertEqual(self.cohort.trades(), complete)

    def test_diag_only_quote_older_than_thirty_seconds_does_not_block_other_accounts(self):
        exclusive = "US.DIAGONLY"
        weights = self.source.weights["HGB_DIAG_5"]
        weights[exclusive] = weights.pop(CODES[9])
        self.quotes.overrides[exclusive] = {"asof": (OPEN + timedelta(seconds=14)).isoformat()}
        self.start()
        state = self.tick(OPEN + timedelta(seconds=45))
        self.assertEqual(state["status"], "BLOCKED")
        diag = state["books"]["HGB_DIAG_5"]
        self.assertEqual(diag["status"], "BLOCKED")
        self.assertIn(exclusive, diag["reason"])
        self.assertEqual((diag["cash"], diag["fees"], diag["trade_count"]), (10000, 0, 0))
        self.assertEqual(diag["positions"], [])
        self.assertEqual(self.cohort.engines["HGB_DIAG_5"].db.execute("SELECT count(*) FROM paper_batches").fetchone()[0], 0)
        for sid in ("RAW_A2", "HGB_FACTOR_5"):
            self.assertEqual(state["books"][sid]["status"], "EXECUTED")
            self.assertGreater(state["books"][sid]["trade_count"], 0)

    def test_raw_only_held_quote_failure_keeps_raw_marks_but_updates_hgb_marks(self):
        self.start()
        first = self.tick()
        raw = first["books"]["RAW_A2"]
        raw_marks = {row["code"]: (row["mark_price"], row["mark_asof"]) for row in raw["positions"]}
        nav = deepcopy(raw["nav_history"])
        self.quotes.errors[CODES[-1]] = ValueError("Raw-only held book clock missing")
        self.quotes.overrides[CODES[0]] = {"price": 120, "bid": 119.99, "ask": 120.01}
        clock = OPEN + timedelta(minutes=10)
        state = self.tick(clock)
        self.assertEqual(state["books"]["RAW_A2"]["status"], "EXECUTED")
        self.assertEqual({row["code"]: (row["mark_price"], row["mark_asof"])
                          for row in state["books"]["RAW_A2"]["positions"]}, raw_marks)
        self.assertEqual(state["books"]["RAW_A2"]["nav_history"], nav)
        self.assertIn("Raw-only", state["books"]["RAW_A2"]["connection_error"])
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            book = state["books"][sid]
            position = next(row for row in book["positions"] if row["code"] == CODES[0])
            self.assertEqual((position["mark_price"], position["mark_asof"]), (120, clock.isoformat()))
            self.assertGreater(book["equity"], first["books"][sid]["equity"])
            self.assertEqual(book["connection_error"], "")

    def test_repeated_tick_and_restart_do_not_refill_or_change_fees(self):
        self.start()
        first = self.tick()
        expected = self.cohort.trades()
        self.tick(OPEN + timedelta(seconds=20))
        self.assertEqual(self.cohort.trades(), expected)
        self.cohort.close()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.start()
        restarted = self.tick(OPEN + timedelta(seconds=30))
        self.assertEqual(self.cohort.trades(), expected)
        self.assertEqual(restarted["books"]["RAW_A2"]["fees"], first["books"]["RAW_A2"]["fees"])
        self.assertEqual(restarted["status"], "EXECUTED")

    def test_partial_account_execution_freezes_close_state_and_resumes_without_inference(self):
        self.start()
        with patch.object(self.cohort.engines["HGB_DIAG_5"], "paper_rebalance", side_effect=ValueError("temporary")):
            partial = self.tick()
        self.assertEqual(partial["status"], "BLOCKED")
        self.assertEqual(partial["books"]["RAW_A2"]["status"], "EXECUTED")
        self.assertEqual(len(self.source.loads), 1)
        frozen = deepcopy(partial["books"]["HGB_DIAG_5"]["plan"])
        self.cohort.close()
        # Simulate a crash after the SQLite book committed but before cohort status saved.
        db = sqlite3.connect(Path(self.temp.name) / "cohort" / "cohort.sqlite3")
        meta = json.loads(db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
        meta["book_status"] = {}
        db.execute("UPDATE settings SET value=? WHERE key='cohort'", (json.dumps(meta),))
        db.commit()
        db.close()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.start()
        with patch.object(self.source, "load", side_effect=AssertionError("post-open re-inference forbidden")):
            resumed = self.tick(OPEN + timedelta(seconds=20))
        self.assertEqual(resumed["status"], "EXECUTED")
        self.assertEqual(resumed["books"]["HGB_DIAG_5"]["plan"], frozen)
        self.assertEqual(resumed["books"]["RAW_A2"]["close_state"]["weights"], {})
        self.assertEqual(len(self.source.loads), 1)
        self.assertEqual(len(self.cohort.trades()), 38)

    def test_sells_settle_before_buys_and_more_than_twenty_orders_do_not_block(self):
        old = ["US.B" + letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        engine = self.cohort.engines["RAW_A2"]
        engine._set("paper", {"cash": 0, "positions": {code: 4 for code in old}, "fees": 0})
        self.start()
        state = self.tick()
        trades = state["books"]["RAW_A2"]["trades"]
        self.assertEqual(state["status"], "EXECUTED")
        self.assertEqual([t["side"] for t in trades[:26]], ["SELL"] * 26)
        self.assertEqual([t["side"] for t in trades[26:]], ["BUY"] * 20)
        self.assertGreaterEqual(state["books"]["RAW_A2"]["cash"], 0)
        self.assertEqual(set(p["code"] for p in state["books"]["RAW_A2"]["positions"]), set(CODES))
        self.assertEqual(len(self.source.loads[0]["RAW_A2"]["weights"]), 26)
        self.assertEqual(self.source.loads[0]["HGB_DIAG_5"]["weights"], {})

    def test_unlisted_old_holdings_are_visible_sales_in_the_plan(self):
        engine = self.cohort.engines["RAW_A2"]
        engine._set("paper", {"cash": 9000, "positions": {"US.ZZ": 10}, "fees": 0})
        self.start()
        state = self.tick(OPEN - timedelta(seconds=10))
        sale = next(row for row in state["books"]["RAW_A2"]["planned_actions"] if row["code"] == "US.ZZ")
        self.assertEqual(sale["action"], "SELL")
        self.assertEqual(sale["target_weight"], 0)
        self.assertEqual(sale["weight_before"], .1)

    def test_stop_and_halt_prevent_execution_and_halt_survives_restart(self):
        self.start()
        self.tick(OPEN - timedelta(seconds=30))
        self.cohort.stop()
        self.assertEqual(self.tick()["trades"], [])
        self.start()
        self.cohort.halt()
        self.assertEqual(self.tick()["trades"], [])
        self.assertTrue(self.cohort.state()["halted"])
        self.cohort.close()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        with self.assertRaises(ValueError):
            self.start()

    def test_refresh_retries_no_more_than_every_fifteen_minutes_then_once_per_day(self):
        self.start()
        self.source.missing = True
        self.source.refresh_error = ValueError("unavailable")
        self.tick(CLOSE + timedelta(minutes=1))
        self.tick(CLOSE + timedelta(minutes=14))
        self.assertEqual(self.source.refresh_count, 1)
        self.source.refresh_error = None
        self.tick(CLOSE + timedelta(minutes=16))
        self.assertEqual(self.source.refresh_count, 2)
        self.tick(CLOSE + timedelta(minutes=40))
        self.assertEqual(self.source.refresh_count, 2)

    def test_refresh_waits_until_completed_bar_plus_sixty_seconds(self):
        self.start()
        self.source.missing = True
        self.tick(CLOSE + timedelta(seconds=30))
        self.assertEqual(self.source.refresh_count, 0)
        self.tick(CLOSE + timedelta(seconds=60))
        self.assertEqual(self.source.refresh_count, 1)

    def test_old_close_signal_does_not_create_a_paper_nav_before_account_registration(self):
        self.cohort.close()
        with patch("moomoo_component.core.now_iso", return_value=OPEN.isoformat()):
            self.cohort = Cohort(Path(self.temp.name) / "new-books", self.source, self.quotes)
        self.start()
        state = self.tick(OPEN + timedelta(seconds=10))
        self.assertEqual(state["status"], "EXECUTED")
        for book in state["books"].values():
            self.assertEqual(book["inception_date"], "2026-09-29")
            self.assertEqual([row["date"] for row in book["nav_history"]], ["2026-09-29"])

    def test_closed_session_state_uses_exact_raw_close_not_current_quote(self):
        engine = self.cohort.engines["HGB_DIAG_5"]
        engine._set("paper", {"cash": 9000, "positions": {CODES[0]: 10}, "fees": 0})
        self.start()
        state = self.tick(OPEN - timedelta(hours=1))
        self.assertEqual(self.quotes.calls, [])
        held = self.source.loads[0]["HGB_DIAG_5"]
        self.assertEqual(held["weights"], {CODES[0][3:]: .1})
        self.assertEqual(held["cash_weight"], .9)
        self.assertEqual(state["books"]["HGB_DIAG_5"]["positions"][0]["mark_source"], "CANONICAL_RAW_USD_CLOSE")
        self.assertEqual(state["books"]["HGB_DIAG_5"]["nav_history"][-1]["date"], "2026-09-28")
        self.assertEqual(state["books"]["HGB_DIAG_5"]["nav_history"][-1]["basis"], "SIGNAL_CLOSE")

    def test_live_mark_failure_keeps_actual_last_value_and_reports_connection_error(self):
        self.start()
        first = self.tick()
        self.quotes.error = ValueError("OpenD unavailable")
        state = self.tick(OPEN + timedelta(minutes=10))
        self.assertIn("OpenD unavailable", state["connection_error"])
        for sid in STRATEGIES:
            self.assertIn(sid, state["connection_error"])
            self.assertEqual(state["books"][sid]["connection_error"], "OpenD unavailable")
        self.assertEqual(state["books"]["RAW_A2"]["equity"], first["books"]["RAW_A2"]["equity"])
        self.assertEqual(state["books"]["RAW_A2"]["positions"][0]["mark_asof"], first["books"]["RAW_A2"]["positions"][0]["mark_asof"])

    def test_no_scheduler_before_start_and_broker_hook_isolated(self):
        calls = []

        class Broker:
            def start(self):
                calls.append("start")
                raise ValueError("broker disconnected")

            def tick(self, now=None):
                calls.append("tick")

            def state(self):
                return {"status": "WAITING_OPEN"}

            def stop(self):
                calls.append("stop")

            def close(self):
                calls.append("close")

        self.cohort.best_broker = Broker()
        self.start()
        self.assertTrue(self.cohort.state()["running"])
        self.assertEqual(self.cohort.state()["broker_error"], "broker disconnected")
        self.assertEqual(self.tick()["status"], "EXECUTED")
        self.assertEqual(self.cohort.state()["broker"]["status"], "WAITING_OPEN")
        self.cohort.stop()
        self.assertIn("stop", calls)

    def test_successful_broker_start_clears_stale_startup_error(self):
        class Broker:
            def start(self):
                return {"status": "WAITING_OPEN"}

            def state(self):
                return {"status": "WAITING_OPEN"}

            def stop(self):
                pass

            def close(self):
                pass

        self.cohort.meta["broker_error"] = "previous local SDK logging failure"
        self.cohort.best_broker = Broker()
        self.start()
        self.assertEqual(self.cohort.state()["broker_error"], "")


class SettlementTests(unittest.TestCase):
    def test_intraday_peak_and_drawdown_persist_despite_daily_nav_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("moomoo_component.core.now_iso", return_value=OPEN.isoformat()):
                engine = Engine(Path(temp), paper_only=True, paper_account_id="paper-metrics")
            self.assertEqual(engine.paper_book()["max_drawdown_fraction"], 0)
            engine._set("paper", dict(cash=0, positions={"US.AA": 100}, fees=0))
            try:
                self.assertIsNone(engine.paper_book()["equity"])
                engine.paper_mark({})
                self.assertEqual(engine.paper_book()["max_drawdown_fraction"], 0)
                for minute, price in enumerate((100, 120, 90, 110), start=1):
                    engine.paper_mark({"US.AA": dict(price=price, source="MOOMOO_OPEND",
                        asof=(OPEN + timedelta(minutes=minute)).isoformat())}, day="2026-09-29")
                self.assertEqual(engine.paper_book()["equity"], 11000)
                self.assertAlmostEqual(engine.paper_book()["max_drawdown_fraction"], -.25)
                self.assertEqual(len(engine.paper_nav_history()), 1)
                self.assertEqual(engine.paper_nav_history()[0]["equity"], 11000)
            finally:
                engine.close()
            reopened = Engine(Path(temp), paper_only=True, paper_account_id="paper-metrics")
            try:
                self.assertAlmostEqual(reopened.paper_book()["max_drawdown_fraction"], -.25)
                reopened.paper_mark({"US.AA": dict(price=130, source="MOOMOO_OPEND",
                    asof=(OPEN + timedelta(minutes=5)).isoformat())}, day="2026-09-29")
                reopened.paper_mark({"US.AA": dict(price=91, source="MOOMOO_OPEND",
                    asof=(OPEN + timedelta(minutes=6)).isoformat())}, day="2026-09-29")
                self.assertAlmostEqual(reopened.paper_book()["max_drawdown_fraction"], -.3)
            finally:
                reopened.close()

    def test_permanent_paper_cannot_use_manual_execution_and_identity_is_fixed(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Engine(Path(temp), paper_only=True, paper_account_id="paper-fixed")
            try:
                with self.assertRaises(ValueError):
                    engine.step()
                with self.assertRaises(ValueError):
                    engine.start()
            finally:
                engine.close()
            with self.assertRaises(ValueError):
                Engine(Path(temp), paper_only=True, paper_account_id="paper-other")
            reopened = Engine(Path(temp), paper_only=True, paper_account_id="paper-fixed")
            reopened.close()

    def test_paper_commit_failure_rolls_back_cash_orders_and_fill_records_together(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Engine(Path(temp), paper_only=True, paper_account_id="paper-test")
            try:
                engine.db.execute("CREATE TRIGGER fail_fill BEFORE INSERT ON paper_fills BEGIN SELECT RAISE(ABORT,'fixture'); END")
                engine.db.commit()
                plan = dict(source_date="2026-09-28", target_cash_weight=0,
                            rows=[dict(code="US.AA", target_weight=1)])
                quotes = Quotes().quotes(["US.AA"])
                with self.assertRaises(Exception):
                    engine.paper_rebalance("RAW_A2", plan, quotes, now=OPEN + timedelta(seconds=10),
                        next_open_utc=OPEN.isoformat(), signal_date="2026-09-28", execution_date="2026-09-29",
                        signal_close_utc=CLOSE.isoformat())
                self.assertEqual(engine.paper_book()["cash"], 10000)
                self.assertEqual(engine.paper_trades(), [])
                self.assertEqual(engine.state()["orders"], [])
                self.assertEqual(engine.db.execute("SELECT count(*) FROM paper_batches").fetchone()[0], 0)
            finally:
                engine.close()


class BrokerFillPersistenceTests(unittest.TestCase):
    def engine(self, temp):
        class Broker:
            result = {"status": "FILLED_ALL", "order_id": "broker-one", "dealt_qty": 1,
                      "dealt_avg_price": 102.75}

            def probe(self):
                return {"accounts": [{"account_id": "sim-one", "market": "US", "environment": "SIMULATE"}]}

            def close(self):
                pass

            def snapshot(self, codes):
                return dict(cash=10000, equity=10000, positions={}, open_orders=[],
                    quotes={code: dict(price=100, bid=99.99, ask=100.01, lot_size=1, price_tick=.01,
                                      tradable=True, asof=datetime.now(timezone.utc).isoformat()) for code in codes})

            def submit(self, order, client_id):
                return {"status": "FILLED_ALL", "order_id": "broker-one"}

            def reconcile(self, client_id, order_id):
                return deepcopy(self.result)

        broker = Broker()
        engine = Engine(Path(temp), broker_factory=lambda **kwargs: broker)
        now = datetime.now(timezone.utc)
        engine.import_strategy(dict(schema_version=1, strategy_id="test", name="test", revision="1",
            asof=(now - timedelta(seconds=1)).isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
            provenance="live", targets=[dict(code="US.AA", target_qty=1)]))
        engine.switch("test")
        engine.connect()
        engine.set_mode("moomoo_simulate", "sim-one", "SIMULATE")
        return engine, broker

    def test_broker_dealt_price_is_persisted_and_never_replaced_by_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, broker = self.engine(temp)
            try:
                engine.step()
                engine.reconcile()
                order = engine.state()["orders"][0]
                self.assertEqual(order["fill_qty"], 1)
                self.assertEqual(order["fill_price"], 102.75)
                self.assertNotEqual(order["fill_price"], order["limit_price"])
                self.assertEqual(order["fill_time_basis"], "RECONCILE_OBSERVED")
                self.assertIsNone(order["fee"])
            finally:
                engine.close()
            restarted = Engine(Path(temp))
            try:
                self.assertEqual(restarted.state()["orders"][0]["fill_price"], 102.75)
            finally:
                restarted.close()

    def test_missing_actual_average_is_unknown_not_a_limit_fill(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, broker = self.engine(temp)
            try:
                broker.result["dealt_avg_price"] = None
                engine.step()
                engine.reconcile()
                order = engine.state()["orders"][0]
                self.assertEqual(order["fill_qty"], 1)
                self.assertIsNone(order["fill_price"])
            finally:
                engine.close()

    def test_respect_cancel_does_not_erase_stop_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, _ = self.engine(temp)
            try:
                engine.stop()
                with self.assertRaises(ValueError):
                    engine.step(respect_cancel=True)
                self.assertEqual(engine.state()["orders"], [])
            finally:
                engine.close()

    def test_bad_clock_nan_weights_and_non_normalized_plan_fail_without_fills(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Engine(Path(temp), paper_only=True)
            try:
                for weight, cash, clock in ((float("nan"), 0, OPEN), (.1, .1, OPEN), (1, 0, OPEN + timedelta(seconds=60))):
                    plan = dict(source_date="2026-09-28", target_cash_weight=cash,
                                rows=[dict(code="US.AA", target_weight=weight)])
                    with self.assertRaises(ValueError):
                        engine.paper_rebalance("RAW_A2", plan, Quotes().quotes(["US.AA"]), now=clock,
                            next_open_utc=OPEN.isoformat(), signal_date="2026-09-28", execution_date="2026-09-29",
                            signal_close_utc=CLOSE.isoformat())
                self.assertEqual(engine.paper_book()["cash"], 10000)
                self.assertEqual(engine.paper_trades(), [])
            finally:
                engine.close()


if __name__ == "__main__":
    unittest.main()
