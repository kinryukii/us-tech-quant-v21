"""Calendar-gated, isolated paper accounting. All sources/quotes are offline fixtures."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from moomoo_component.cohort import Cohort, STRATEGIES
from moomoo_component.core import Engine
from moomoo_component.strategy import timestamp


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

    def quotes_partial(self, codes, refresh=False):
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

    def test_successful_prepare_clears_only_a_recovered_single_close_bridge_error(self):
        self.start()
        error = 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO'
        with patch.object(self.source, 'close_states', side_effect=ValueError(error)):
            failed = self.tick(OPEN - timedelta(minutes=1))
        self.assertEqual(failed['last_error'], error)
        recovered = self.tick(OPEN - timedelta(minutes=1))
        self.assertEqual(recovered['status'], 'WAITING_OPEN')
        self.assertEqual(recovered['last_error'], '')
        self.assertEqual(recovered['trades'], [])
        self.assertEqual(set(self.cohort.plans), set(STRATEGIES))
        events = self.cohort.db.execute("SELECT detail FROM events WHERE event='SOURCE_PREPARATION_RECOVERED'").fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0][0])['previous_error'], error)

    def test_prepare_preserves_quote_order_and_composite_errors(self):
        self.start()
        for error in ('US.FICO 报价过期', '模拟委托结果未知', 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:',
                      'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO; 模拟委托结果未知',
                      'DAILY_REFRESH: QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO'):
            with self.subTest(error=error):
                self.cohort.loaded_key = None
                self.cohort.meta['last_error'] = error
                self.cohort.meta['book_quote_errors'] = {'RAW_A2': '有效报价错误'}
                result = self.tick(OPEN - timedelta(minutes=1))
                self.assertEqual(result['last_error'], error)
                self.assertEqual(result['book_quote_errors'], {'RAW_A2': '有效报价错误'})
                self.assertEqual(result['trades'], [])

    def test_blocked_or_gapped_prepare_does_not_clear_close_error(self):
        self.start()
        error = 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO'
        load = self.source.load
        for status, gaps in [('BLOCKED', []), ('READY', ['missing'])]:
            with self.subTest(status=status):
                self.cohort.loaded_key = None
                self.cohort.meta['last_error'] = error
                def loaded(states, now=None):
                    return {**load(states, now), 'status': status, 'data_gaps': gaps}
                with patch.object(self.source, 'load', side_effect=loaded):
                    result = self.tick(OPEN - timedelta(minutes=1))
                self.assertTrue(result['last_error'])
                if gaps:
                    self.assertEqual(result['last_error'], error)
                self.assertEqual(result['trades'], [])

    def test_failed_plan_persistence_cannot_record_recovery(self):
        self.start()
        error = 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO'
        self.cohort.meta['last_error'] = error
        clock = OPEN - timedelta(minutes=1)
        with patch.object(self.cohort, '_persist', side_effect=OSError('synthetic write failed')):
            with self.assertRaisesRegex(OSError, 'synthetic write failed'):
                self.cohort._prepare(self.source.status(clock), clock)
        self.assertEqual(self.cohort.meta['last_error'], error)
        self.assertEqual(self.cohort.db.execute("SELECT COUNT(*) FROM events WHERE event='SOURCE_PREPARATION_RECOVERED'").fetchone()[0], 0)

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

    def test_raw_only_held_quote_failure_keeps_its_mark_and_reports_mixed_nav(self):
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
        rows = {row["code"]: row for row in state["books"]["RAW_A2"]["positions"]}
        self.assertEqual((rows[CODES[-1]]["mark_price"], rows[CODES[-1]]["mark_asof"]), raw_marks[CODES[-1]])
        self.assertEqual((rows[CODES[0]]["mark_price"], rows[CODES[0]]["mark_asof"]), (120, clock.isoformat()))
        latest = state["books"]["RAW_A2"]["nav_history"][-1]
        self.assertEqual(latest["basis"], "OBSERVED_MIXED_MARKS")
        self.assertFalse(latest["complete_live_coverage"])
        self.assertEqual(latest["fresh_held_count"], 19)
        self.assertEqual(latest["held_asof_min"], raw_marks[CODES[-1]][1])
        self.assertEqual(latest["observed_at_utc"], clock.isoformat())
        self.assertNotEqual(state["books"]["RAW_A2"]["nav_history"], nav)
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
            self.assertIn("OpenD unavailable", state["books"][sid]["connection_error"])
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


    def _valuation_trade_snapshot(self):
        return dict(plans=deepcopy(self.cohort.plans), statuses=deepcopy(self.cohort.book_status),
            plan_metadata=deepcopy(self.cohort.plan_metadata), active=self.cohort._active_ids(),
            stopped=self.cohort.stop_event.is_set(), halted=self.cohort.halt_event.is_set(),
            delay=self.cohort.execution_delay_minutes, window=self.cohort.execution_window_seconds,
            ledgers={sid: engine._get("paper", {}) for sid, engine in self.cohort.engines.items()},
            tables={sid: {table: [tuple(row) for row in engine.db.execute("SELECT * FROM " + table)]
                for table in ("paper_fills", "paper_batches", "orders", "order_fills")}
                for sid, engine in self.cohort.engines.items()})

    def test_explicit_mark_never_calls_signal_or_trading_and_can_mark_paused_raw(self):
        self.start(); self.tick(); self.cohort.stop()
        self.cohort.meta["active_strategy_ids"] = ["HGB_DIAG_5", "HGB_FACTOR_5"]
        before = self._valuation_trade_snapshot()
        clock = OPEN + timedelta(hours=1)
        self.quotes.clock = clock
        self.quotes.errors[CODES[-1]] = ValueError("old raw source clock")
        self.quotes.overrides[CODES[0]] = {"price": 110}
        with patch.object(self.source, "status", side_effect=AssertionError("no source status")), \
             patch.object(self.source, "refresh", side_effect=AssertionError("no refresh")), \
             patch.object(self.source, "load", side_effect=AssertionError("no inference")), \
             patch.object(self.cohort, "_hook", side_effect=AssertionError("no broker hook")), \
             patch.object(self.cohort, "state", side_effect=AssertionError("no broker state")), \
             patch.object(Engine, "paper_rebalance", side_effect=AssertionError("no rebalance")), \
             patch.object(Engine, "step", side_effect=AssertionError("no execution")):
            report = self.cohort.mark_current_books(now=clock)
        self.assertEqual(self._valuation_trade_snapshot(), before)
        self.assertTrue(report["valuation_only"])
        self.assertEqual(set(report["books"]), set(STRATEGIES))
        self.assertEqual(self.quotes.calls[-1], CODES)
        raw = report["books"]["RAW_A2"]
        self.assertEqual((raw["fresh_held_count"], raw["held_count"]), (19, 20))
        self.assertEqual(raw["failed_quotes"], [{"code": CODES[-1], "reason": "old raw source clock"}])
        self.assertTrue(raw["nav_recorded"])
        self.assertEqual(self.cohort.state()["books"]["RAW_A2"]["status"], "PAUSED")

    def test_all_failed_or_unqualified_mark_keeps_old_nav(self):
        self.start(); self.tick()
        clock = OPEN + timedelta(hours=1)
        self.quotes.clock = clock
        before = {sid: deepcopy(engine.paper_nav_history()) for sid, engine in self.cohort.engines.items()}
        for case in ("provider", "stale", "future", "nontradable", "currency", "market", "source"):
            with self.subTest(case=case):
                self.quotes.error = ValueError("provider denied") if case == "provider" else None
                override = {"stale": {"asof": (clock - timedelta(seconds=31)).isoformat()},
                    "future": {"asof": (clock + timedelta(seconds=1)).isoformat()},
                    "nontradable": {"tradable": False}, "currency": {"currency": "JPY"},
                    "market": {"market": "HK"}, "source": {"source": "UNKNOWN"}}.get(case, {})
                self.quotes.overrides = {code: override for code in CODES}
                report = self.cohort.mark_current_books(now=clock)
                for sid, engine in self.cohort.engines.items():
                    self.assertEqual(engine.paper_nav_history(), before[sid])
                    self.assertEqual(report["books"][sid]["fresh_held_count"], 0)
                    self.assertFalse(report["books"][sid]["nav_recorded"])

    def test_real_clock_is_rechecked_before_later_book_writes(self):
        self.start(); self.tick()
        clock = OPEN + timedelta(hours=1); self.quotes.clock = clock
        with patch("moomoo_component.cohort._now", side_effect=[clock, clock,
                clock + timedelta(seconds=31), clock + timedelta(seconds=31)]):
            report = self.cohort.mark_current_books()
        self.assertTrue(report["books"]["RAW_A2"]["nav_recorded"])
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.assertFalse(report["books"][sid]["nav_recorded"])
            self.assertEqual(report["books"][sid]["fresh_held_count"], 0)
            self.assertEqual(report["books"][sid]["observed_at_utc"], (clock + timedelta(seconds=31)).isoformat())

    def test_missing_old_mark_updates_real_fresh_mark_but_does_not_invent_nav(self):
        self.start(); self.tick()
        engine = self.cohort.engines["RAW_A2"]
        marks = engine._get("paper_marks", {}); marks.pop(CODES[-1]); engine._set("paper_marks", marks)
        before = deepcopy(engine.paper_nav_history())
        self.quotes.clock = OPEN + timedelta(hours=1)
        self.quotes.errors[CODES[-1]] = ValueError("no real old mark")
        self.quotes.overrides[CODES[0]] = {"price": 125}
        report = self.cohort.mark_current_books(now=self.quotes.clock)
        self.assertEqual(engine.paper_nav_history(), before)
        self.assertEqual(engine._get("paper_marks", {})[CODES[0]]["price"], 125)
        self.assertEqual(report["books"]["RAW_A2"]["unmarked_codes"], [CODES[-1]])
        self.assertFalse(report["books"]["RAW_A2"]["nav_recorded"])
        self.assertTrue(report["books"]["HGB_DIAG_5"]["nav_recorded"])

    def test_book_mark_failure_does_not_block_other_books(self):
        self.start(); self.tick()
        clock = OPEN + timedelta(hours=1); self.quotes.clock = clock
        with patch.object(self.cohort.engines["RAW_A2"], "paper_mark", side_effect=ValueError("isolated book failure")):
            report = self.cohort.mark_current_books(now=clock)
        self.assertFalse(report["books"]["RAW_A2"]["nav_recorded"])
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.assertTrue(report["books"][sid]["nav_recorded"])
            self.assertTrue(report["books"][sid]["complete_live_coverage"])

    def test_mark_control_requires_shared_tick_lock_and_empty_books_do_not_make_nav(self):
        nav = {sid: deepcopy(engine.paper_nav_history()) for sid, engine in self.cohort.engines.items()}
        self.cohort.tick_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "稍后刷新估值"):
                self.cohort.mark_current_books(now=OPEN)
        finally:
            self.cohort.tick_lock.release()
        report = self.cohort.mark_current_books(now=OPEN)
        self.assertEqual(report["books"], {})
        self.assertEqual(self.quotes.calls, [])
        for sid, engine in self.cohort.engines.items():
            self.assertEqual(engine.paper_nav_history(), nav[sid])


    def _broker_tick_owner_fixture(self):
        from moomoo_component.best_broker import BestBroker
        from unittest.mock import Mock
        broker = BestBroker(Path(self.temp.name) / 'tick-owner', self.source)
        self.addCleanup(broker.engine.close)
        broker.start = Mock(return_value={})
        broker.stop = Mock()
        broker.close = Mock()
        broker.state = Mock(return_value={'status': 'WAITING_QUOTES', 'running': True})
        broker.tick = Mock()
        self.cohort.best_broker = broker
        return broker

    def test_live_best_broker_worker_owns_ticks_while_paper_cohort_runs(self):
        from types import SimpleNamespace
        broker = self._broker_tick_owner_fixture()
        broker.worker = SimpleNamespace(is_alive=lambda: True)
        self.start()
        state = self.tick(OPEN + timedelta(seconds=10))
        self.assertEqual(state['status'], 'EXECUTED')
        broker.start.assert_called_once_with()
        broker.tick.assert_not_called()

    def test_inactive_best_broker_worker_keeps_direct_tick(self):
        from types import SimpleNamespace
        broker = self._broker_tick_owner_fixture()
        self.start()
        for index, worker in enumerate((None, SimpleNamespace(is_alive=lambda: False)), 1):
            broker.worker = worker
            stamp = OPEN + timedelta(seconds=10 * index)
            self.tick(stamp)
            self.assertEqual(broker.tick.call_count, index)
            self.assertEqual(broker.tick.call_args.kwargs, {'now': stamp})

    def test_broker_without_worker_interface_keeps_direct_tick(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        broker = SimpleNamespace(start=Mock(), tick=Mock(), stop=Mock(), close=Mock(), state=Mock(return_value={'status': 'WAITING_OPEN'}))
        self.cohort.best_broker = broker
        self.start()
        stamp = OPEN + timedelta(seconds=10)
        self.tick(stamp)
        broker.tick.assert_called_once_with(now=stamp)

    def test_broker_read_cooldown_cannot_be_bypassed_by_cohort_ticks(self):
        from moomoo_component.brokers import BrokerReadError
        from types import SimpleNamespace
        broker = self._broker_tick_owner_fixture()
        broker.worker = SimpleNamespace(is_alive=lambda: True)
        self.start()
        broker.stop_event.clear()
        calls = []
        error = BrokerReadError('synthetic read quota cooldown')
        error.retry_after_seconds = 30

        def read_only_failure(*args, **kwargs):
            calls.append('read')
            raise error
        broker.tick.side_effect = read_only_failure
        waits = []

        def during_cooldown(seconds):
            waits.append(seconds)
            for offset in (10, 11, 12):
                self.tick(OPEN + timedelta(seconds=offset))
            broker.stop_event.set()
            return True
        with patch.object(broker.stop_event, 'wait', side_effect=during_cooldown):
            broker._run()
        self.assertEqual(calls, ['read'])
        self.assertEqual(waits, [30])
        self.assertEqual(broker.last_error, str(error))
        self.assertEqual(broker.engine.db.execute("SELECT count(*) FROM audit WHERE event='BROKER_READ_COOLDOWN'").fetchone()[0], 1)


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


class PaperCatchupTests(unittest.TestCase):
    """Same fixture and original paper path; no source/quote/broker connections."""
    setUp = CohortTests.setUp
    start = CohortTests.start
    tick = CohortTests.tick
    reopen = CohortTests.reopen

    def partial(self):
        self.reopen(0, 600, True)
        self.start()
        self.quotes.errors[CODES[0]] = ValueError("original stale source clock")
        first = self.tick(OPEN + timedelta(seconds=10))
        self.assertTrue(all(book["execution"]["status"] == "PARTIALLY_EXECUTED" for book in first["books"].values()))
        self.cohort.stop()
        self.now = OPEN + timedelta(minutes=20)
        self.deadline = self.now + timedelta(seconds=600)
        return first

    def authorize(self, **changes):
        return self.cohort.authorize_catchup(**dict(dict(execution_date="2026-09-29",
            deadline_utc=self.deadline.isoformat(), now=self.now), **changes))

    def batches(self):
        return {sid: engine.db.execute("SELECT payload FROM paper_batches").fetchone()[0]
                for sid, engine in self.cohort.engines.items()}

    def test_only_remaining_symbols_resume_with_original_plan_equity_ids_and_actual_time(self):
        first = self.partial()
        plans, batches, old = deepcopy(self.cohort.plans), self.batches(), deepcopy(first["trades"])
        calls = len(self.quotes.calls)
        record = self.authorize()
        self.assertEqual(self.batches(), batches, "permission alone must not mutate old batches or failures")
        self.assertEqual(self.cohort.trades(), old)
        self.assertEqual(len(self.quotes.calls), calls, "authorization must not obtain executable quotes")
        self.assertEqual((self.cohort.execution_delay_minutes, self.cohort.execution_window_seconds), (0, 600))
        self.assertEqual(record["deadline_utc"], self.deadline.isoformat())
        self.quotes.errors.clear()
        self.quotes.overrides[CODES[0]] = dict(price=101, bid=100.99, ask=101.01)
        self.quotes.overrides[CODES[1]] = dict(price=200, bid=199.99, ask=200.01)
        self.start()
        fill_time = self.now + timedelta(seconds=1)
        with patch.object(self.source, "load", side_effect=AssertionError("must not infer a replacement plan")):
            resumed = self.tick(fill_time)
        self.assertEqual(resumed["status"], "EXECUTED")
        new = [row for row in resumed["trades"] if row["id"] not in {row["id"] for row in old}]
        self.assertEqual(len(new), 3)
        self.assertEqual({row["code"] for row in new}, {CODES[0]})
        self.assertEqual({row["fill_price"] for row in new}, {101.01})
        self.assertEqual({row["filled_at"] for row in new}, {fill_time.isoformat()})
        self.assertEqual({row["quote_asof"] for row in new}, {fill_time.isoformat()})
        self.assertEqual(self.cohort.plans, plans)
        self.assertEqual([row for row in resumed["trades"] if row["id"] in {row["id"] for row in old}], old)
        for sid in STRATEGIES:
            before, after = json.loads(batches[sid]), resumed["books"][sid]["execution"]
            self.assertEqual(before["batch_id"], after["batch_id"])
            self.assertEqual(before["pretrade_equity"], after["pretrade_equity"])
            self.assertEqual(before["source_plan_sha256"], after["source_plan_sha256"])
            self.assertTrue(set(before["processed_codes"]).issubset(after["processed_codes"]))
        again = self.tick(fill_time + timedelta(seconds=1))
        self.assertEqual(again["trades"], resumed["trades"])
        self.assertEqual(len(self.source.loads), 1)

    def test_permission_and_idempotency_survive_restart_without_reinference(self):
        first = self.partial()
        record = self.authorize()
        self.reopen()
        self.assertEqual(self.cohort.meta["paper_same_day_catchup"], record)
        self.quotes.errors.clear()
        self.start()
        with patch.object(self.source, "load", side_effect=AssertionError("frozen partial input must survive restart")):
            resumed = self.tick(self.now + timedelta(seconds=2))
        self.assertEqual(len(resumed["trades"]), len(first["trades"]) + 3)
        committed = deepcopy(resumed["trades"])
        self.reopen()
        self.start()
        self.assertEqual(self.tick(self.now + timedelta(seconds=3))["trades"], committed)

    def test_deadline_remains_exclusive_and_does_not_reopen_after_restart(self):
        first = self.partial()
        self.authorize()
        self.quotes.errors.clear()
        self.start()
        expired = self.tick(self.deadline)
        self.assertEqual(expired["trades"], first["trades"])
        self.assertEqual(expired["status"], "PARTIALLY_EXECUTED")
        self.reopen()
        self.start()
        self.assertEqual(self.tick(self.deadline + timedelta(seconds=1))["trades"], first["trades"])
        self.assertEqual(self.cohort._poll_delay(now=self.deadline), 30.0)

    def test_invalid_day_deadlines_and_unexpired_original_window_never_authorize(self):
        first = self.partial()
        for changes in (dict(execution_date="2026-09-30"), dict(deadline_utc=self.now.isoformat()),
                        dict(deadline_utc=(self.now + timedelta(seconds=601)).isoformat()),
                        dict(deadline_utc="2026-09-29T20:00:01+00:00"),
                        dict(now=OPEN + timedelta(seconds=599), deadline_utc=(OPEN + timedelta(seconds=700)).isoformat()),
                        dict(now=self.now + timedelta(days=1), deadline_utc=(self.deadline + timedelta(days=1)).isoformat()),
                        dict(now=None), dict(now=self.now.replace(tzinfo=None))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.authorize(**changes)
        self.assertIsNone(self.cohort.meta.get("paper_same_day_catchup"))
        self.assertEqual(self.cohort.trades(), first["trades"])

    def test_running_worker_halt_tick_and_halted_account_are_rejected(self):
        self.partial()
        self.cohort.stop_event.clear()
        with self.assertRaisesRegex(ValueError, "STOPPED"):
            self.authorize()
        self.cohort.stop_event.set()
        old_worker = self.cohort.worker
        self.cohort.worker = type("Busy", (), {"is_alive":lambda self: True})()
        with self.assertRaisesRegex(ValueError, "STOPPED"):
            self.authorize()
        self.cohort.worker = old_worker
        self.cohort.halt_event.set()
        with self.assertRaisesRegex(ValueError, "STOPPED"):
            self.authorize()
        self.cohort.halt_event.clear()
        self.cohort.tick_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "WAIT_FOR_TICK"):
                self.authorize()
        finally:
            self.cohort.tick_lock.release()
        self.cohort.engines["HGB_DIAG_5"].halt_event.set()
        with self.assertRaisesRegex(ValueError, "HALTED"):
            self.authorize()
        self.assertTrue(all(engine._get("paper_same_day_catchup", None) is None for engine in self.cohort.engines.values()))

    def test_missing_original_batch_never_grants_other_books_partial_permissions(self):
        self.partial()
        engine = self.cohort.engines["HGB_FACTOR_5"]
        engine.db.execute("DELETE FROM paper_batches")
        engine.db.commit()
        with self.assertRaisesRegex(ValueError, "BINDING"):
            self.authorize()
        self.assertTrue(all(engine._get("paper_same_day_catchup", None) is None for engine in self.cohort.engines.values()))

    def test_changed_current_source_plan_hash_or_account_rejects_without_rewriting_evidence(self):
        self.partial()
        batches = self.batches()
        status = self.source.status
        self.source.status = lambda now=None: {**status(now), "source_refs":{"manifest":"c" * 64}}
        with self.assertRaisesRegex(ValueError, "SOURCE"):
            self.authorize()
        self.source.status = status
        original = deepcopy(self.cohort.plans["RAW_A2"])
        self.cohort.plans["RAW_A2"]["extra"] = "changed"
        with self.assertRaisesRegex(ValueError, "BINDING"):
            self.authorize()
        self.cohort.plans["RAW_A2"] = original
        engine = self.cohort.engines["RAW_A2"]
        engine.account_id = "different-paper-account"
        with self.assertRaisesRegex(ValueError, "BINDING"):
            self.authorize()
        self.assertEqual(self.batches(), batches)
        self.assertTrue(all(engine._get("paper_same_day_catchup", None) is None for engine in self.cohort.engines.values()))

    def test_core_rechecks_account_hash_equity_and_processed_binding_after_authorization(self):
        first = self.partial()
        record = self.authorize()
        self.start()
        engine = self.cohort.engines["RAW_A2"]
        permission = record["books"]["RAW_A2"]
        self.quotes.errors.clear()
        self.quotes.clock = self.now + timedelta(seconds=1)
        quotes = self.quotes.quotes(CODES)
        for key, value in (("account_id","changed"), ("source_plan_sha256","f" * 64),
                           ("source_refs",{"manifest":"f" * 64}), ("pretrade_equity",1),
                           ("processed_codes",["US.ZZ"]), ("execution_date","2026-09-30")):
            engine._set("paper_same_day_catchup", {**permission,key:value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                engine.paper_rebalance("RAW_A2", self.cohort.plans["RAW_A2"], quotes,
                    now=self.quotes.clock, next_open_utc=OPEN.isoformat(), signal_date="2026-09-28",
                    execution_date="2026-09-29", signal_close_utc=CLOSE.isoformat(),
                    source_refs=self.cohort.plan_metadata["source_refs"], allow_partial_quotes=True,
                    execution_window_seconds=600)
        self.assertEqual(self.cohort.trades(), first["trades"])
        engine._set("paper_same_day_catchup", permission)

    def test_catchup_keeps_strict_quote_age_spread_currency_tradability_and_future_guards(self):
        first = self.partial()
        self.authorize()
        self.start()
        self.quotes.errors.clear()
        for changes in (dict(asof=(self.now - timedelta(seconds=31)).isoformat()),
                        dict(asof=(self.now + timedelta(seconds=1)).isoformat()),
                        dict(bid=99,ask=102), dict(tradable=False), dict(currency="HKD"), dict(lot_size=100)):
            self.quotes.overrides[CODES[0]] = changes
            with self.subTest(changes=changes):
                state = self.tick(self.now)
                self.assertEqual(state["trades"], first["trades"])
                self.assertTrue(all(book["execution"]["skipped"] for book in state["books"].values()))

    def test_identical_authorization_is_idempotent_and_cannot_extend_its_deadline(self):
        self.partial()
        record = self.authorize()
        self.assertEqual(self.authorize(now=self.now + timedelta(seconds=1)), record)
        with self.assertRaisesRegex(ValueError, "ALREADY_AUTHORIZED"):
            self.authorize(deadline_utc=(self.deadline - timedelta(seconds=1)).isoformat())
        self.assertEqual(self.cohort._poll_delay(now=self.now), 1.0)

    def test_permission_never_reopens_original_batch_on_a_future_day(self):
        first = self.partial()
        self.authorize()
        self.start()
        self.quotes.errors.clear()
        future = self.tick(self.now + timedelta(days=1))
        self.assertEqual(future["trades"], first["trades"])
        self.assertEqual(future["status"], "PARTIALLY_EXECUTED")

    def test_original_batch_without_verified_frozen_equity_cannot_authorize(self):
        self.partial()
        engine = self.cohort.engines["HGB_FACTOR_5"]
        row = engine.db.execute("SELECT id,payload FROM paper_batches").fetchone()
        batch = {**json.loads(row["payload"]), "pretrade_equity":None}
        engine.db.execute("UPDATE paper_batches SET payload=? WHERE id=?", (json.dumps(batch), row["id"]))
        engine.db.commit()
        before = self.batches()
        with self.assertRaisesRegex(ValueError,"BINDING"):
            self.authorize()
        self.assertEqual(self.batches(), before)
        self.assertTrue(all(engine._get("paper_same_day_catchup", None) is None for engine in self.cohort.engines.values()))

    def test_catchup_requests_only_pending_and_preserves_incomplete_held_marks(self):
        first = self.partial()
        self.authorize()
        calls = len(self.quotes.calls)
        held_marks = {sid:deepcopy(engine._get("paper_marks", {})) for sid,engine in self.cohort.engines.items()}
        self.quotes.errors.clear()
        self.start()
        with patch.object(self.cohort,"_mark",side_effect=AssertionError("pending-only quotes do not fully cover held marks")):
            state = self.tick(self.now + timedelta(seconds=1))
        self.assertEqual(self.quotes.calls[calls:], [[CODES[0]]] * 3)
        for sid,engine in self.cohort.engines.items():
            marks = engine._get("paper_marks", {})
            for code,value in held_marks[sid].items():
                self.assertEqual(marks[code],value)
            self.assertEqual(state["books"][sid]["nav_history"][-1]["basis"], "PARTIAL_REALTIME_WITH_RECORDED_MARKS")
            before = first["books"][sid]["execution"]
            after = state["books"][sid]["execution"]
            self.assertTrue(set(before["processed_codes"]).issubset(after["processed_codes"]))
        self.assertEqual([row for row in state["trades"] if row["id"] in {row["id"] for row in first["trades"]}],first["trades"])

    def canonical_ref_subset(self):
        required = ("frozen_calendar", "session_hours_rules", "daily/report.json", "selected/package.json",
                    "selected/current_report.json", "current/features.parquet")
        subset = {key:{"path":"synthetic/" + key,"sha256":"a" * 64} for key in required}
        full = {**subset,"current/mapped_members.parquet":{"path":"synthetic/pool","sha256":"b" * 64},
                "close/SYNTHETIC":{"path":"synthetic/close","sha256":"c" * 64}}
        original_status,original_load = self.source.status,self.source.load
        self.source.status = lambda now=None: {**original_status(now),"source_refs":deepcopy(subset)}
        self.source.load = lambda states,now=None: {**original_load(states,now),"source_refs":deepcopy(full)}
        return subset,full

    def test_status_subset_retains_original_full_source_refs_in_permission_batch_and_fills(self):
        subset,full = self.canonical_ref_subset()
        self.partial()
        batches = self.batches()
        self.assertEqual(self.cohort.plan_metadata["source_refs"],full)
        record = self.authorize()
        self.assertTrue(all(permission["source_refs"] == full for permission in record["books"].values()))
        self.assertEqual(self.batches(),batches)
        self.quotes.errors.clear()
        self.start()
        result = self.tick(self.now + timedelta(seconds=1))
        self.assertEqual(result["status"],"EXECUTED")
        self.assertTrue(all(book["execution"]["source_refs"] == full for book in result["books"].values()))
        self.assertTrue(all(trade["signal_source_refs"] == full for trade in result["trades"]))
        self.assertEqual(self.cohort.plan_metadata["source_refs"],full)

    def test_status_required_ref_missing_path_sha_changed_or_extra_unbound_ref_rejects(self):
        subset,full = self.canonical_ref_subset()
        self.partial()
        status = self.source.status
        variants=[]
        for key in subset:
            variants.append({name:value for name,value in subset.items() if name != key})
        for field,value in (("path","synthetic/changed"),("sha256","f" * 64)):
            refs=deepcopy(subset)
            refs["selected/package.json"][field]=value
            variants.append(refs)
        variants.append({**subset,"unexpected/ref":{"path":"synthetic/unbound","sha256":"a" * 64}})
        for refs in variants:
            self.source.status = lambda now=None, refs=refs: {**status(now),"source_refs":refs}
            with self.subTest(keys=tuple(refs)),self.assertRaisesRegex(ValueError,"SOURCE"):
                self.authorize()
        self.source.status=status
        record=self.authorize()
        self.start()
        bad=deepcopy(subset)
        bad["current/features.parquet"]["sha256"]="f" * 64
        self.source.status=lambda now=None: {**status(now),"source_refs":bad}
        result=self.tick(self.now + timedelta(seconds=1))
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(self.cohort.meta["paper_same_day_catchup"],record)
        self.assertTrue(all(engine._get("paper_same_day_catchup", None) == record["books"][sid]
                            for sid,engine in self.cohort.engines.items()))

    def test_no_remaining_targets_cannot_authorize(self):
        self.partial()
        self.quotes.errors.clear()
        self.start()
        self.tick(OPEN + timedelta(seconds=20))
        self.cohort.stop()
        with self.assertRaisesRegex(ValueError, "NO_REMAINING"):
            self.authorize()
        self.assertTrue(all(engine._get("paper_same_day_catchup", None) is None for engine in self.cohort.engines.values()))


    def failed_same_signal_progress(self, stage):
        first = self.partial()
        sid = 'HGB_DIAG_5'
        original = deepcopy(first['books'][sid]['execution'])
        batches = self.batches()
        trades = deepcopy(first['books'][sid]['trades'])
        self.start()
        if stage == 'REBALANCE':
            subject = self.cohort.engines[sid]
            method = 'paper_rebalance'
        else:
            subject = self.quotes
            method = 'quotes_partial'
        reason = 'synthetic latest permission failure'
        with patch.object(subject, method, side_effect=ValueError(reason)):
            failed = self.tick(OPEN + timedelta(seconds=20))
        execution = failed['books'][sid]['execution']
        self.assertEqual(execution['status'], 'BLOCKED')
        self.assertEqual(execution['reason'], reason)
        self.assertEqual(execution['failure_stage'], stage)
        self.assertEqual(execution['required_codes'], original['required_codes'])
        self.assertEqual(execution['processed_codes'], original['processed_codes'])
        self.assertEqual(execution['source_plan_sha256'], original['source_plan_sha256'])
        self.assertEqual(self.batches()[sid], batches[sid])
        self.assertEqual(failed['books'][sid]['trades'], trades)
        expired = self.tick(OPEN + timedelta(seconds=600))
        terminal = expired['books'][sid]['execution']
        self.assertEqual(terminal['status'], 'PARTIALLY_EXECUTED')
        self.assertEqual(set(terminal['required_codes']) - set(terminal['processed_codes']), {CODES[0]})
        self.assertEqual(terminal['failure_stage'], stage)
        self.assertEqual(self.batches()[sid], batches[sid])

    def test_rebalance_failure_retains_same_signal_progress_and_latest_failure(self):
        self.failed_same_signal_progress('REBALANCE')

    def test_quote_failure_retains_same_signal_progress_after_window_end(self):
        self.failed_same_signal_progress('QUOTES')

    def test_other_signal_progress_does_not_leak_into_current_failure(self):
        self.partial()
        sid = 'HGB_DIAG_5'
        self.cohort.book_status[sid] = {'status': 'PARTIALLY_EXECUTED', 'signal_date': '2026-09-25', 'execution_date': '2026-09-28', 'required_codes': ['US.OLD'], 'processed_codes': []}
        self.start()
        with patch.object(self.cohort.engines[sid], 'paper_rebalance', side_effect=ValueError('synthetic current permission invalid')):
            current = self.tick(OPEN + timedelta(seconds=20))['books'][sid]['execution']
        self.assertEqual(current['status'], 'BLOCKED')
        self.assertEqual(current['reason'], 'synthetic current permission invalid')
        self.assertNotIn('required_codes', current)
        self.assertEqual(current['signal_date'], '2026-09-28')



class ResetSource(Source):
    def __init__(self, root):
        super().__init__()
        self.daily_root = Path(root)
        self.runtime_root = self.daily_root / "source"
        self.runtime_root.mkdir()
        self.package = self.runtime_root / "package.json"
        self.package.write_text("synthetic accepted direct package", encoding="utf-8")
        self.package_sha = Cohort._file_sha(self.package)
        self.shift, self.reset_loads, self.change = 0, [], None

    def status(self, now=None):
        opening = OPEN + timedelta(days=self.shift)
        close = CLOSE + timedelta(days=self.shift)
        status = "READY" if now < opening else "OPEN_WINDOW" if now < opening + timedelta(seconds=600) else "MISSED_OPEN"
        return dict(status=status, source_date=close.date().isoformat(), signal_date=close.date().isoformat(),
            execution_date=opening.date().isoformat(), signal_close_utc=close.isoformat(), next_open_utc=opening.isoformat(),
            next_close_utc=(opening + timedelta(hours=6, minutes=30)).isoformat(), data_gaps=[],
            source_refs={"manifest": "a" * 64,
                **{key: {"path": str(self.package), "sha256": self.package_sha} for key in
                   ("frozen_calendar", "session_hours_rules", "daily/report.json", "selected/package.json",
                    "selected/current_report.json", "current/features.parquet")}})

    def close_states(self, books, signal_date):
        result = super().close_states(books, signal_date)
        for state in result.values():
            state["close_asof_utc"] = (CLOSE + timedelta(days=self.shift)).isoformat()
        return result

    def load(self, states=None, now=None, *, reset_request=None):
        from moomoo_component.applied_source import _reset_request, _bytes, _assumed_states
        if reset_request is None:
            self.loads.append(deepcopy(states))
            value = self.status(now)
            value["plans"] = {sid: dict(source_date=value["signal_date"], policy_id="HGB_TOP20_RISK_R1",
                target_cash_weight=1 - sum(self.weights[sid].values()), account_basis="SIGNAL_CLOSE",
                rows=[dict(code=code, ticker=code[3:], target_weight=weight, weight_before=states[sid]["weights"].get(code[3:], 0))
                      for code, weight in self.weights[sid].items()]) for sid in states}
            return value
        request = _reset_request(reset_request, now=now)
        self.reset_loads.append(deepcopy(request))
        value = self.status(now)
        value.update(reset_request=request, reset_request_sha256=Cohort._file_sha(self.package),
                     reset_id=request["reset_id"], requested_at=request["requested_at"], assumed_states=_assumed_states(request))
        import hashlib
        value["reset_request_sha256"] = hashlib.sha256(_bytes(request)).hexdigest()
        value["plans"] = {sid: dict(source_date=value["signal_date"], policy_id="HGB_TOP20_RISK_R1", reset_id=request["reset_id"],
            requested_at=request["requested_at"], valuation_basis="POST_LIQUIDATION_ASSUMPTION",
            account_basis="USER_REQUESTED_POST_LIQUIDATION_CASH_START", target_origin_account_basis="CASH_START",
            execution_condition="ACCOUNT_FLAT_AFTER_CONFIRMED_LIQUIDATION", target_cash_weight=1 - sum(self.weights[sid].values()),
            rows=[dict(code=code, ticker=code[3:], target_weight=weight, weight_before=0) for code, weight in self.weights[sid].items()])
            for sid in request["strategy_ids"]}
        if self.change:
            self.change(value)
        # Exercise the production immutable-archive owner with synthetic payloads only.
        from moomoo_component.applied_source import DailySource
        owner = object.__new__(DailySource)
        owner.daily_root, owner.runtime_root = self.daily_root, self.runtime_root
        owner._read_only_roots = (self.daily_root / "canonical_repo", self.daily_root / "canonical_data")
        owner._archive(value, states=None)
        return value


class HgbEpochResetTests(unittest.TestCase):
    start = CohortTests.start
    tick = CohortTests.tick

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source, self.quotes = ResetSource(Path(self.temp.name)), Quotes()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.addCleanup(lambda: self.cohort.close() if not self.cohort.closed else None)
        self.clock = OPEN + timedelta(days=1, hours=-1)
        self.request = dict(reset_id="synthetic_epoch_1", requested_at=self.clock.isoformat(),
            strategy_ids=["HGB_DIAG_5", "HGB_FACTOR_5"], signal_date="2026-09-29",
            expected_policy_id="HGB_TOP20_RISK_R1", expected_package_sha256=self.source.package_sha)

    def seed(self):
        self.start()
        result = self.tick()
        self.assertEqual(result["status"], "EXECUTED")
        self.cohort.stop()
        self.old_trades = {sid: self.cohort.engines[sid].paper_trades() for sid in STRATEGIES}
        self.old_raw = deepcopy(self.cohort.engines["RAW_A2"].paper_book())
        self.source.shift = 1

    def reset(self):
        return self.cohort.reset_hgb(self.request, now=self.clock)

    def reopen(self):
        self.cohort.close()
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)

    def test_two_books_restart_with_archived_exact_fills_fresh_cash_and_paused_raw(self):
        self.seed()
        raw_path = self.cohort.engines["RAW_A2"].path / "state.sqlite3"
        before_raw_sha = Cohort._file_sha(raw_path)
        result = self.reset()
        self.assertEqual(result["paper_reset"]["phase"], "COMMITTED")
        self.assertEqual(result["active_strategy_ids"], ["HGB_DIAG_5", "HGB_FACTOR_5"])
        self.assertEqual((result["execution_delay_minutes"], result["execution_window_seconds"]), (0, 600))
        self.assertEqual(result["books"]["RAW_A2"]["status"], "PAUSED")
        self.assertEqual(self.cohort.engines["RAW_A2"].paper_book(), self.old_raw)
        self.assertEqual(Cohort._file_sha(raw_path), before_raw_sha)
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            book = result["books"][sid]
            self.assertEqual((book["cash"], book["positions"], book["trade_count"], book["fees"]), (10000, [], 0, 0))
            self.assertEqual(book["close_state"]["valuation_basis"], "POST_LIQUIDATION_ASSUMPTION")
            self.assertEqual(book["plan"]["account_basis"], "USER_REQUESTED_POST_LIQUIDATION_CASH_START")
            self.assertEqual(self.cohort.engines[sid]._get("paper_epoch_id", None), self.request["reset_id"])
            archive = Path(result["paper_reset"]["archives"][sid])
            with closing(sqlite3.connect((archive / "state.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
                old = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM paper_fills ORDER BY rowid")]
                self.assertEqual({row["id"] for row in old}, {row["id"] for row in self.old_trades[sid]})
            self.assertEqual(self.cohort._reset_book_proof(archive), result["paper_reset"]["old_book_proofs"][sid])
        self.assertEqual(len(self.source.close_inputs), 1)

    def test_initial_reset_signal_does_not_read_old_closes_then_executes_only_two_once(self):
        self.seed()
        self.reset()
        self.source.close_states = lambda **kwargs: (_ for _ in ()).throw(AssertionError("initial epoch must not fabricate signal-close"))
        self.start()
        opening = OPEN + timedelta(days=1)
        self.assertEqual(self.tick(opening - timedelta(minutes=1))["status"], "WAITING_OPEN")
        self.quotes.calls.clear()
        result = self.tick(opening + timedelta(seconds=10))
        self.assertEqual(result["status"], "EXECUTED")
        self.assertEqual(len(self.quotes.calls), 2)
        self.assertEqual(self.cohort.engines["RAW_A2"].paper_trades(), self.old_trades["RAW_A2"])
        trades = {sid: self.cohort.engines[sid].paper_trades() for sid in ("HGB_DIAG_5", "HGB_FACTOR_5")}
        repeated = self.tick(opening + timedelta(seconds=11))
        self.assertEqual(repeated["status"], "EXECUTED")
        for sid in trades:
            self.assertEqual(self.cohort.engines[sid].paper_trades(), trades[sid])
            self.assertTrue(set(row["id"] for row in trades[sid]).isdisjoint(row["id"] for row in self.old_trades[sid]))
        self.cohort.stop()
        self.assertEqual(self.reset()["reset_id"], self.request["reset_id"])
        for sid in trades:
            self.assertEqual(self.cohort.engines[sid].paper_trades(), trades[sid])

    def test_restart_preserves_epoch_plan_and_next_signal_uses_only_active_account_states(self):
        self.seed()
        self.reset()
        self.reopen()
        self.assertEqual(self.cohort.meta["active_strategy_ids"], ["HGB_DIAG_5", "HGB_FACTOR_5"])
        self.start()
        self.assertEqual(self.tick(OPEN + timedelta(days=1, seconds=10))["status"], "EXECUTED")
        self.source.shift = 2
        result = self.tick(OPEN + timedelta(days=2, minutes=-1))
        self.assertEqual(result["status"], "WAITING_OPEN")
        self.assertEqual(set(self.source.close_inputs[-1]), {"HGB_DIAG_5", "HGB_FACTOR_5"})
        self.assertEqual(set(self.source.loads[-1]), {"HGB_DIAG_5", "HGB_FACTOR_5"})
        self.assertEqual(self.cohort.engines["RAW_A2"].paper_trades(), self.old_trades["RAW_A2"])

    def test_guard_failures_never_archive_or_clear_any_old_book(self):
        self.seed()
        for case in ("running", "tick", "worker", "halted", "policy", "date", "package", "missing_plan", "assumption", "weight", "current_ref"):
            with self.subTest(case=case):
                self.source.change = None
                self.cohort.stop_event.set()
                self.cohort.halt_event.clear()
                self.cohort.worker = None
                if case == "running": self.cohort.stop_event.clear()
                if case == "halted": self.cohort.halt_event.set()
                if case == "worker": self.cohort.worker = type("Active", (), {"is_alive": lambda self: True})()
                if case == "tick": self.cohort.tick_lock.acquire()
                if case in {"policy", "date", "package", "missing_plan", "assumption", "weight"}:
                    def change(value):
                        if case == "policy": value["plans"]["HGB_DIAG_5"]["policy_id"] = "LEGACY"
                        elif case == "date": value["source_date"] = "2026-09-28"
                        elif case == "package": value["source_refs"]["selected/package.json"]["sha256"] = "0" * 64
                        elif case == "missing_plan": value["plans"].pop("HGB_FACTOR_5")
                        elif case == "assumption": value["assumed_states"]["HGB_DIAG_5"]["valuation_basis"] = "SIGNAL_CLOSE"
                        elif case == "weight": value["plans"]["HGB_DIAG_5"]["rows"][0]["weight_before"] = .1
                    self.source.change = change
                current = self.source.status
                def bad_status(now=None):
                    value = current(now)
                    value["source_refs"]["selected/package.json"]["sha256"] = "0" * 64
                    return value
                self.request["reset_id"] = "guard_" + case
                try:
                    with patch.object(self.source, "status", side_effect=bad_status) if case == "current_ref" else patch.object(self.source, "change", self.source.change):
                        with self.assertRaises(ValueError): self.reset()
                    self.assertNotIn("paper_reset", self.cohort.meta)
                    for sid in STRATEGIES:
                        self.assertEqual(self.cohort.engines[sid].paper_trades(), self.old_trades[sid])
                finally:
                    if case == "tick": self.cohort.tick_lock.release()
                    self.cohort.stop_event.set(); self.cohort.halt_event.clear(); self.cohort.worker = None

    def test_partial_archive_failure_stays_stopped_and_recovers_same_intent_on_restart(self):
        self.seed()
        original = Path.rename
        def fail_second(path, destination):
            if path.name == "HGB_FACTOR_5": raise OSError("synthetic interrupted second move")
            return original(path, destination)
        with patch.object(Path, "rename", fail_second), self.assertRaisesRegex(OSError, "interrupted"):
            self.reset()
        self.assertNotEqual(self.cohort.meta["paper_reset"]["phase"], "COMMITTED")
        with self.assertRaisesRegex(ValueError, "UNFINISHED"): self.start()
        self.reopen()
        self.assertEqual(self.cohort.meta["paper_reset"]["phase"], "COMMITTED")
        self.assertEqual(len(self.source.reset_loads), 1)
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.assertEqual(self.cohort.engines[sid].paper_book()["cash"], 10000)
            self.assertEqual(self.cohort.engines[sid].paper_trades(), [])

    def test_commit_failure_is_not_treated_as_committed_and_retries_without_rearchive(self):
        self.seed()
        persist = self.cohort._persist
        def fail_commit():
            if self.cohort.meta.get("paper_reset", {}).get("phase") == "COMMITTED":
                raise OSError("synthetic commit failure")
            return persist()
        with patch.object(self.cohort, "_persist", side_effect=fail_commit), self.assertRaisesRegex(OSError, "commit failure"):
            self.reset()
        self.assertEqual(self.cohort.meta["paper_reset"]["phase"], "ARCHIVED")
        with self.assertRaisesRegex(ValueError, "UNFINISHED"): self.start()
        record = deepcopy(self.cohort.meta["paper_reset"])
        result = self.reset()
        self.assertEqual(result["paper_reset"]["old_book_proofs"], record["old_book_proofs"])
        self.assertEqual(len(self.source.reset_loads), 1)
        self.assertEqual(result["paper_reset"]["phase"], "COMMITTED")

    def test_resolved_archive_parent_escape_is_rejected_before_any_book_is_closed(self):
        self.seed()
        resolve = Path.resolve
        archive_prefix = str(self.cohort.path / "archives")
        outside = Path(self.temp.name) / "outside"
        def escaped(path, *args, **kwargs):
            if str(path).startswith(archive_prefix):
                return outside / path.name
            return resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", escaped), self.assertRaisesRegex(ValueError, "OUTSIDE_OWNED"):
            self.reset()
        self.assertFalse(outside.exists())
        self.assertNotIn("paper_reset", self.cohort.meta)
        for sid in STRATEGIES:
            self.assertEqual(self.cohort.engines[sid].paper_trades(), self.old_trades[sid])

    def test_source_rotation_after_archive_freeze_rejects_without_clearing_old_books(self):
        self.seed()
        load = self.source.load
        def rotate(*args, **kwargs):
            result = load(*args, **kwargs)
            self.source.package_sha = "0" * 64
            return result
        with patch.object(self.source, "load", side_effect=rotate), self.assertRaisesRegex(ValueError, "SOURCE_CHANGED_DURING_FREEZE"):
            self.reset()
        self.assertNotIn("paper_reset", self.cohort.meta)
        for sid in STRATEGIES:
            self.assertEqual(self.cohort.engines[sid].paper_trades(), self.old_trades[sid])

    def test_restore_finish_failure_closes_all_new_engine_and_cohort_locks(self):
        self.seed()
        with patch.object(self.cohort, "_finish_hgb_reset", side_effect=OSError("synthetic initialize interruption")), \
                self.assertRaisesRegex(OSError, "initialize interruption"):
            self.reset()
        self.cohort.close()
        with patch.object(Cohort, "_finish_hgb_reset", side_effect=ValueError("synthetic restore guard")), \
                self.assertRaisesRegex(ValueError, "restore guard"):
            Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.cohort = Cohort(Path(self.temp.name) / "cohort", self.source, self.quotes)
        self.assertEqual(self.cohort.meta["paper_reset"]["phase"], "COMMITTED")
        self.assertTrue(all(not engine.paper_trades() for sid, engine in self.cohort.engines.items() if sid != "RAW_A2"))

    def test_reset_exact_ten_minute_end_never_creates_new_fills(self):
        self.seed()
        self.reset()
        self.start()
        result = self.tick(OPEN + timedelta(days=1, seconds=600))
        self.assertEqual(result["status"], "MISSED_OPEN")
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.assertEqual(self.cohort.engines[sid].paper_trades(), [])
            self.assertEqual(self.cohort.engines[sid].paper_book()["cash"], 10000)

    def test_initial_reset_clock_or_readiness_change_never_creates_fresh_fills(self):
        self.seed()
        self.reset()
        self.start()
        status = self.source.status
        for case in ("opening", "closing", "gaps", "status"):
            with self.subTest(case=case):
                def changed(now=None):
                    value = status(now)
                    if case == "opening": value["next_open_utc"] = (OPEN + timedelta(days=1, minutes=1)).isoformat()
                    elif case == "closing": value["signal_close_utc"] = (CLOSE + timedelta(days=1, minutes=-1)).isoformat()
                    elif case == "gaps": value["data_gaps"] = ["unverified current source"]
                    else: value["status"] = "WAITING_SOURCE"
                    return value
                with patch.object(self.source, "status", side_effect=changed):
                    result = self.tick(OPEN + timedelta(days=1, seconds=10))
                self.assertNotEqual(result["status"], "EXECUTED")
                for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
                    self.assertEqual(self.cohort.engines[sid].paper_trades(), [])

    def test_initial_source_or_plan_change_blocks_before_any_fresh_fill(self):
        self.seed()
        self.reset()
        self.start()
        original = self.cohort.plans["HGB_DIAG_5"]["rows"][0]["target_weight"]
        self.cohort.plans["HGB_DIAG_5"]["rows"][0]["target_weight"] += .01
        result = self.tick(OPEN + timedelta(days=1, seconds=10))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("FROZEN_PLAN_CHANGED", result["last_error"])
        self.assertEqual(self.cohort.engines["HGB_DIAG_5"].paper_trades(), [])
        self.cohort.plans["HGB_DIAG_5"]["rows"][0]["target_weight"] = original
        self.source.package_sha = "0" * 64
        result = self.tick(OPEN + timedelta(days=1, seconds=11))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("INITIAL_SOURCE_CHANGED", result["last_error"])
        self.assertEqual(self.cohort.engines["HGB_FACTOR_5"].paper_trades(), [])


    def revision_fixture(self):
        self.seed()
        self.cohort.allow_partial_quotes = True
        self.cohort.meta["allow_partial_quotes"] = True
        self.reset()
        original = deepcopy(self.cohort.meta["paper_reset"])
        old_refs = deepcopy(self.cohort.plan_metadata["source_refs"])
        status = self.source.status
        self.source.package = self.source.runtime_root / "revision_package.json"
        self.source.package.write_text("synthetic completed-market-data revision", encoding="utf-8")
        self.source.package_sha = Cohort._file_sha(self.source.package)
        def revised_status(now=None):
            value = status(now); value["ready"] = True
            for key in ("frozen_calendar", "session_hours_rules"):
                value["source_refs"][key] = deepcopy(old_refs[key])
            return value
        self.source.status = revised_status
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.source.weights[sid] = {CODES[0]: .09, CODES[1]: .08}
        self.quotes.calls.clear()
        return original

    def revision_books(self):
        return {sid: {table: [tuple(row) for row in engine.db.execute("SELECT * FROM " + table + " ORDER BY rowid")]
                      for table in ("settings", "orders", "order_fills", "paper_batches", "paper_fills", "paper_nav")}
                for sid, engine in self.cohort.engines.items()}

    def revise(self, now=None):
        return self.cohort.revise_hgb_targets(self.request["reset_id"], self.source.package_sha,
            now=now or self.clock + timedelta(minutes=10))

    def test_target_revision_preserves_epoch_books_and_original_archive_restarts_and_executes_new_targets_once(self):
        original = self.revision_fixture()
        old_archive = Path(original["loaded"]["archive"]["path"])
        old_bytes = old_archive.read_bytes()
        books = self.revision_books()
        with patch.object(self.source, "close_states", side_effect=AssertionError("no synthetic old close")), \
                patch.object(self.quotes, "quotes", side_effect=AssertionError("no quote request before open")):
            state = self.revise()
        self.assertEqual(state["status"], "STOPPED")
        self.assertEqual(self.cohort.meta["paper_reset"], original)
        self.assertEqual(old_archive.read_bytes(), old_bytes)
        self.assertEqual(self.revision_books(), books)
        revision = deepcopy(self.cohort.meta["paper_target_revision"])
        template = revision["source_template"]
        self.assertNotEqual(template["request"]["reset_id"], self.request["reset_id"])
        self.assertEqual(template["request"]["requested_at"], original["request"]["requested_at"])
        self.assertEqual(Path(template["loaded"]["archive"]["path"]).parent.parent.name, template["request"]["reset_id"])
        self.assertEqual(revision["original_epoch_id"], self.request["reset_id"])
        for sid in ("HGB_DIAG_5", "HGB_FACTOR_5"):
            self.assertEqual(self.cohort.engines[sid]._get("paper_epoch_id", None), self.request["reset_id"])
            self.assertEqual(self.cohort.plans[sid]["reset_id"], self.request["reset_id"])
            self.assertEqual(self.cohort.plans[sid]["valuation_basis"], "PAPER_CASH_EPOCH")
            self.assertAlmostEqual(self.cohort.plans[sid]["target_cash_weight"], .83)
        load_count = len(self.source.reset_loads)
        self.revise(now=self.clock + timedelta(minutes=15))
        self.assertEqual(self.cohort.meta["paper_target_revision"], revision)
        self.assertEqual(len(self.source.reset_loads), load_count)
        self.assertEqual(len(self.cohort.meta["paper_target_revision_history"]), 1)
        self.reopen(); self.start()
        opening = OPEN + timedelta(days=1)
        with patch.object(self.source, "load", side_effect=AssertionError("same-signal must not infer or reload")), \
                patch.object(self.source, "close_states", side_effect=AssertionError("same-signal must not value old close")):
            self.assertEqual(self.tick(opening - timedelta(minutes=1))["status"], "WAITING_OPEN")
            self.assertEqual(self.tick(opening + timedelta(seconds=10))["status"], "EXECUTED")
            trades = {sid: self.cohort.engines[sid].paper_trades() for sid in ("HGB_DIAG_5", "HGB_FACTOR_5")}
            self.assertTrue(all(len(rows) == 2 for rows in trades.values()))
            self.assertEqual(self.tick(opening + timedelta(seconds=11))["status"], "EXECUTED")
            for sid, rows in trades.items(): self.assertEqual(self.cohort.engines[sid].paper_trades(), rows)
        self.assertEqual(self.cohort.engines["RAW_A2"].paper_trades(), self.old_trades["RAW_A2"])
        self.source.shift = 2
        self.assertEqual(self.tick(OPEN + timedelta(days=2, minutes=-1))["status"], "WAITING_OPEN")
        self.assertEqual(set(self.source.close_inputs[-1]), {"HGB_DIAG_5", "HGB_FACTOR_5"})

    def test_target_revision_real_immutable_archive_survives_database_failure_and_retry_at_later_clock(self):
        from moomoo_component.applied_source import DailySource, DailySourceError
        original = self.revision_fixture()
        old_path = Path(original["loaded"]["archive"]["path"]); old_bytes = old_path.read_bytes()
        meta, plans, metadata, books = deepcopy(self.cohort.meta), deepcopy(self.cohort.plans), deepcopy(self.cohort.plan_metadata), self.revision_books()
        self.cohort.db.execute("CREATE TRIGGER synthetic_target_revision_failure BEFORE INSERT ON settings WHEN NEW.key='cohort' BEGIN SELECT RAISE(ABORT,'synthetic target revision failure'); END")
        self.cohort.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic target revision failure"): self.revise()
        self.assertEqual((self.cohort.meta, self.cohort.plans, self.cohort.plan_metadata), (meta, plans, metadata))
        self.assertEqual(self.revision_books(), books)
        self.assertEqual(self.cohort.db.execute("SELECT count(*) FROM events WHERE event='HGB_PAPER_TARGETS_REVISED'").fetchone()[0], 0)
        template_id = self.source.reset_loads[-1]["reset_id"]
        new_path = self.source.runtime_root / "policies/HGB_TOP20_RISK_R1/resets" / template_id / self.request["signal_date"] / "plans.json"
        first_bytes = new_path.read_bytes()
        # Prove the actual owner rejects changing the old original epoch in-place.
        owner = object.__new__(DailySource)
        owner.daily_root, owner.runtime_root = self.source.daily_root, self.source.runtime_root
        owner._read_only_roots = (self.source.daily_root / "canonical_repo",)
        bad = deepcopy(original["loaded"]); bad["plans"]["HGB_DIAG_5"]["rows"][0]["target_weight"] += .01
        with self.assertRaisesRegex(DailySourceError, "IMMUTABLE_PAPER_PLAN_CONFLICT"): owner._archive(bad)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.cohort.db.execute("DROP TRIGGER synthetic_target_revision_failure"); self.cohort.db.commit()
        self.revise(now=self.clock + timedelta(minutes=15))
        self.assertEqual(new_path.read_bytes(), first_bytes)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual(self.source.reset_loads[-1], self.source.reset_loads[-2])
        self.assertEqual(self.cohort.meta["paper_reset"], original)
        self.assertEqual(self.revision_books(), books)

    def test_target_revision_guard_failures_never_write_books_or_replace_active_control(self):
        self.revision_fixture()
        meta, plans, metadata = deepcopy(self.cohort.meta), deepcopy(self.cohort.plans), deepcopy(self.cohort.plan_metadata)
        status, load = self.source.status, self.source.load
        engine = self.cohort.engines["HGB_DIAG_5"]
        ledger = deepcopy(engine._get("paper", {"cash":10000., "positions":{}, "fees":0.}))
        for case in ("running", "worker", "tick", "halt", "engine_running", "engine_worker", "engine_halt", "wrong_id", "bad_sha", "package", "epoch", "cash", "positions", "fees", "batches", "fills", "orders", "delay", "window", "partial", "backwards", "opening", "catchup", "source_error", "load_error", "source_signal", "source_open", "source_close", "source_ready", "source_status", "source_gaps", "calendar", "session_rules", "policy", "fit", "weight", "assumption"):
            with self.subTest(case=case):
                self.cohort.meta, self.cohort.plans, self.cohort.plan_metadata = deepcopy(meta), deepcopy(plans), deepcopy(metadata)
                self.cohort.stop_event.set();self.cohort.halt_event.clear();self.cohort.worker=None
                engine.stop_event.set();engine.halt_event.clear();engine.worker=None
                self.cohort.execution_delay_minutes=0;self.cohort.execution_window_seconds=600;self.cohort.allow_partial_quotes=True
                self.source.status,self.source.load,self.source.change=status,load,None
                engine._set("paper",deepcopy(ledger));engine._set("paper_epoch_id",self.request["reset_id"])
                now, identity, sha = self.clock+timedelta(minutes=10),self.request["reset_id"],self.source.package_sha
                if case == "running":self.cohort.stop_event.clear()
                if case == "worker":self.cohort.worker=type("Worker",(),{"is_alive":lambda s:True})()
                if case == "tick":self.cohort.tick_lock.acquire()
                if case == "halt":self.cohort.halt_event.set()
                if case == "engine_running":engine.stop_event.clear()
                if case == "engine_worker":engine.worker=type("Worker",(),{"is_alive":lambda s:True})()
                if case == "engine_halt":engine.halt_event.set()
                if case == "wrong_id":identity="other"
                if case == "bad_sha":sha="BAD"
                if case == "package":sha="c"*64
                if case == "epoch":engine._set("paper_epoch_id","other")
                if case in {"cash","positions","fees"}:
                    changed=deepcopy(ledger);changed[case]=9999. if case=="cash" else {CODES[0]:1} if case=="positions" else .1
                    engine._set("paper",changed)
                if case in {"batches","fills"}:
                    table={"batches":"paper_batches","fills":"paper_fills"}[case]
                    engine.db.execute("INSERT INTO "+table+" VALUES (?,?)",("revision-test",'{}'));engine.db.commit()
                if case == "orders":
                    engine.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",("revision-test",now.isoformat(),"HGB_DIAG_5","paper",engine.account_id,CODES[0],"BUY",1,100.,"CANCELLED_BEFORE_SEND",None,"MARKET"));engine.db.commit()
                if case == "delay":self.cohort.execution_delay_minutes=1
                if case == "window":self.cohort.execution_window_seconds=60
                if case == "partial":self.cohort.allow_partial_quotes=False
                if case == "backwards":now=self.clock-timedelta(minutes=1)
                if case == "opening":now=OPEN+timedelta(days=1)
                if case == "catchup":self.cohort.meta["paper_same_day_catchup"]={"active":True}
                if case == "source_error":self.source.status=lambda **kw:(_ for _ in ()).throw(ValueError("source unavailable"))
                if case == "load_error":self.source.load=lambda *a,**kw:(_ for _ in ()).throw(ValueError("load unavailable"))
                if case.startswith("source_") and case not in {"source_error"} or case in {"calendar","session_rules"}:
                    changed=deepcopy(status(now))
                    if case=="source_signal":changed["signal_date"]="2026-09-28"
                    if case=="source_open":changed["next_open_utc"]=(OPEN+timedelta(days=1,minutes=1)).isoformat()
                    if case=="source_close":changed["signal_close_utc"]=(CLOSE+timedelta(days=1,minutes=-1)).isoformat()
                    if case=="source_ready":changed["ready"]=False
                    if case=="source_status":changed["status"]="WAITING_SOURCE"
                    if case=="source_gaps":changed["data_gaps"]=["missing"]
                    if case in {"calendar","session_rules"}:changed["source_refs"][{"calendar":"frozen_calendar","session_rules":"session_hours_rules"}[case]]={"sha256":"c"*64}
                    self.source.status=lambda **kw:deepcopy(changed)
                if case in {"policy","fit","weight","assumption"}:
                    def change(value):
                        plan=value["plans"]["HGB_DIAG_5"]
                        if case=="policy":plan["policy_id"]="LEGACY"
                        if case=="fit":value["model_fit_calls"]=1
                        if case=="weight":plan["rows"][0]["target_weight"]=-.1
                        if case=="assumption":value["assumed_states"]["HGB_DIAG_5"]["cash_weight"]=.5
                    self.source.change=change
                try:
                    before=(deepcopy(self.cohort.meta),deepcopy(self.cohort.plans),deepcopy(self.cohort.plan_metadata));books=self.revision_books()
                    with self.assertRaises(ValueError):self.cohort.revise_hgb_targets(identity,sha,now=now)
                    self.assertEqual((self.cohort.meta,self.cohort.plans,self.cohort.plan_metadata),before)
                    self.assertEqual(self.revision_books(),books)
                    self.assertEqual(self.quotes.calls,[])
                finally:
                    if case=="tick":self.cohort.tick_lock.release()
                    self.cohort.stop_event.set();self.cohort.halt_event.clear();self.cohort.worker=None
                    engine.stop_event.set();engine.halt_event.clear();engine.worker=None
                    for table in ("paper_batches","paper_fills","orders"):
                        engine.db.execute("DELETE FROM "+table+" WHERE id='revision-test'")
                    engine.db.commit()
        self.source.status,self.source.load,self.source.change=status,load,None
        engine._set("paper",ledger);engine._set("paper_epoch_id",self.request["reset_id"])

    def test_target_revision_active_authorization_or_template_archive_tampering_blocks_before_any_fill(self):
        original=self.revision_fixture();self.revise()
        active,plans,metadata=deepcopy(self.cohort.meta),deepcopy(self.cohort.plans),deepcopy(self.cohort.plan_metadata)
        new_path=Path(active["paper_target_revision"]["source_template"]["loaded"]["archive"]["path"]);raw=new_path.read_bytes()
        self.start()
        for case in ("plan", "template_request", "template_sha", "epoch", "metadata_sha", "archive", "old_history"):
            with self.subTest(case=case):
                self.cohort.meta,self.cohort.plans,self.cohort.plan_metadata=deepcopy(active),deepcopy(plans),deepcopy(metadata)
                rev=self.cohort.meta["paper_target_revision"]
                if case=="plan":self.cohort.plans["HGB_DIAG_5"]["rows"][0]["target_weight"]+=.01
                if case=="template_request":rev["source_template"]["request"]["requested_at"]=(self.clock+timedelta(minutes=1)).isoformat()
                if case=="template_sha":rev["source_template"]["request_sha256"]="c"*64
                if case=="epoch":rev["original_epoch_id"]="other"
                if case=="metadata_sha":rev["metadata_sha256"]="c"*64
                if case=="archive":new_path.write_bytes(raw+b" ")
                if case=="old_history":
                    self.cohort.plans.update(deepcopy(original["loaded"]["plans"]))
                    self.cohort.meta["paper_target_revision_history"][0]["previous_revision"]=deepcopy(rev)
                try:
                    state=self.tick(OPEN+timedelta(days=1,seconds=10))
                    self.assertEqual(state["status"],"BLOCKED")
                    self.assertTrue(all(not self.cohort.engines[sid].paper_trades() for sid in ("HGB_DIAG_5","HGB_FACTOR_5")))
                finally:new_path.write_bytes(raw)
        self.cohort.meta,self.cohort.plans,self.cohort.plan_metadata=active,plans,metadata


    def zulu_revision_fixture(self):
        status=self.source.status
        def zulu(now=None):
            value=status(now)
            for key in ("next_open_utc","signal_close_utc","next_close_utc"):
                value[key]=value[key].replace("+00:00","Z")
            return value
        self.source.status=zulu
        self.revision_fixture(); self.revise()

    def test_target_revision_zulu_clock_survives_restart_before_and_after_completed_fills(self):
        self.zulu_revision_fixture()
        metadata=deepcopy(self.cohort.plan_metadata)
        revision=deepcopy(self.cohort.meta["paper_target_revision"])
        reset=deepcopy(self.cohort.meta["paper_reset"])
        self.assertTrue(metadata["execution_time_utc"].endswith("Z"))
        self.reopen(); self.start()
        self.assertEqual(self.cohort.plan_metadata["execution_time_utc"],metadata["execution_time_utc"])
        self.assertEqual(self.cohort.plan_metadata,metadata)
        self.assertEqual(self.cohort.meta["paper_target_revision"],revision)
        self.assertEqual(self.cohort.meta["paper_reset"],reset)
        opening=OPEN+timedelta(days=1)
        with patch.object(self.source,"load",side_effect=AssertionError("no re-inference or revision")), \
                patch.object(self.source,"close_states",side_effect=AssertionError("no stale close valuation")):
            self.assertEqual(self.tick(opening-timedelta(minutes=1))["status"],"WAITING_OPEN")
            self.assertEqual(self.tick(opening+timedelta(seconds=10))["status"],"EXECUTED")
        books=self.revision_books()
        self.cohort.stop(); self.reopen(); self.start()
        with patch.object(self.source,"load",side_effect=AssertionError("no re-inference after filled")), \
                patch.object(self.source,"close_states",side_effect=AssertionError("no old close after filled")):
            self.assertEqual(self.tick(opening+timedelta(minutes=30))["status"],"EXECUTED")
            self.assertEqual(self.tick(opening+timedelta(minutes=31))["status"],"EXECUTED")
        self.assertEqual(self.cohort.meta["paper_target_revision"],revision)
        self.assertEqual(self.cohort.meta["paper_reset"],reset)
        for sid,engine in self.cohort.engines.items():
            for table in ("orders","paper_fills","paper_batches","order_fills"):
                self.assertEqual([tuple(row) for row in engine.db.execute("SELECT * FROM "+table+" ORDER BY rowid")],books[sid][table])

    def test_target_revision_zulu_equivalence_rejects_changed_instant_policy_source_and_receipt(self):
        self.zulu_revision_fixture(); self.reopen()
        metadata=deepcopy(self.cohort.plan_metadata);active=deepcopy(self.cohort.meta)
        for case in ("minute","delay","window","partial","receipt","refs","template_time","epoch"):
            with self.subTest(case=case):
                self.cohort.plan_metadata=deepcopy(metadata);self.cohort.meta=deepcopy(active)
                if case=="minute":self.cohort.plan_metadata["execution_time_utc"]=(OPEN+timedelta(days=1,minutes=1)).isoformat()
                if case=="delay":self.cohort.plan_metadata["execution_delay_minutes"]=1
                if case=="window":self.cohort.plan_metadata["execution_window_seconds"]=601
                if case=="partial":self.cohort.plan_metadata["allow_partial_quotes"]=False
                if case=="receipt":self.cohort.meta["paper_target_revision"]["metadata_sha256"]="a"*64
                if case=="refs":self.cohort.plan_metadata["source_refs"]["selected/package.json"]["sha256"]="a"*64
                if case=="template_time":self.cohort.meta["paper_target_revision"]["source_template"]["loaded"]["next_open_utc"]=(OPEN+timedelta(days=1,minutes=1)).isoformat()
                if case=="epoch":self.cohort.meta["paper_target_revision"]["original_epoch_id"]="other"
                with self.assertRaises(ValueError):self.cohort._initial_hgb_target_plans(self.cohort.meta["paper_reset"])
        self.cohort.plan_metadata=metadata;self.cohort.meta=active
        self.assertEqual(self.cohort._initial_hgb_target_plans(self.cohort.meta["paper_reset"]),self.cohort.meta["paper_target_revision"]["plans"])


    def test_target_revision_valid_original_metadata_hash_precedes_zulu_compatibility(self):
        from moomoo_component.cohort import _fingerprint
        self.zulu_revision_fixture()
        self.cohort.plan_metadata["execution_time_utc"]=(OPEN+timedelta(days=1)).isoformat()
        self.cohort.meta["paper_target_revision"]["metadata_sha256"]=_fingerprint(self.cohort.plan_metadata)
        receipt=deepcopy(self.cohort.meta["paper_target_revision"])
        self.assertTrue(self.cohort.plan_metadata["next_open_utc"].endswith("Z"))
        self.assertTrue(self.cohort.plan_metadata["execution_time_utc"].endswith("+00:00"))
        self.cohort._persist();self.reopen();self.start()
        with patch.object(self.source,"load",side_effect=AssertionError("must reuse accepted target")):
            self.assertEqual(self.tick(OPEN+timedelta(days=1,seconds=10))["status"],"EXECUTED")
            self.assertEqual(self.tick(OPEN+timedelta(days=1,minutes=30))["status"],"EXECUTED")
        self.assertEqual(self.cohort.meta["paper_target_revision"],receipt)
        for sid in ("HGB_DIAG_5","HGB_FACTOR_5"):
            self.assertEqual(len(self.cohort.engines[sid].paper_trades()),2)



class AutomaticCohortCompletionTests(unittest.TestCase):
    """Existing fixture drives the original worker-free Cohort/Engine flow."""
    setUp=CohortTests.setUp
    start=CohortTests.start
    tick=CohortTests.tick
    reopen=CohortTests.reopen

    def automatic(self):
        self.source.weights.pop("RAW_A2")
        self.reopen(0,600,True)
        self.cohort.meta["active_strategy_ids"]=["HGB_DIAG_5","HGB_FACTOR_5"]
        policy=dict(schema_version=1,enabled=True,policy_id="synthetic_cohort_auto_20260929",
            reason="USER_EXPLICIT_DAILY_AUTO_COMPLETION",authorized_at_utc=CLOSE.isoformat(),
            effective_execution_date="2026-09-29",evaluation_end_exclusive="2027-01-01",
            priority_window_seconds=600,close_buffer_seconds=600,one_tick_spread=True,
            normal_spread_bps=50,max_single_tick_spread_bps=200,quote_max_age_seconds=30,
            price_deviation_fraction=.02,active_strategy_ids=["HGB_DIAG_5","HGB_FACTOR_5"],
            broker_account_id="3604",broker_budget=10000)
        self.cohort.meta["automatic_completion_policy"]=policy
        for sid in self.cohort._active_ids():
            engine=self.cohort.engines[sid]
            engine._set("automatic_completion_policy",policy)
            engine.db.execute("INSERT INTO audit VALUES (?,?,?)",
                (policy["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(policy)))
            engine.db.commit()
        self.cohort._persist()
        self.cohort._bind_automatic_completion_policy()
        self.start()
        return policy

    def test_automatic_afternoon_retry_uses_only_pending_codes_without_manual_grants(self):
        self.automatic()
        self.quotes.errors[CODES[0]]=ValueError("initial quote missing")
        first=self.tick()
        self.assertEqual(first["status"],"PARTIALLY_EXECUTED")
        plans,old=deepcopy(self.cohort.plans),deepcopy(self.cohort.trades())
        self.quotes.errors.clear()
        clock=OPEN+timedelta(hours=4)
        with patch.object(self.source,"load",side_effect=AssertionError("cannot replace frozen plan")):
            resumed=self.tick(clock)
        self.assertEqual(resumed["status"],"EXECUTED")
        self.assertEqual(self.cohort.plans,plans)
        new=[row for row in self.cohort.trades() if row["id"] not in {x["id"] for x in old}]
        self.assertEqual(len(new),2)
        self.assertEqual({row["code"] for row in new},{CODES[0]})
        self.assertEqual({row["filled_at"] for row in new},{clock.isoformat()})
        self.assertIsNone(self.cohort.meta.get("paper_same_day_catchup"))
        self.assertEqual(self.cohort._poll_delay(now=clock),30)
        self.tick(clock+timedelta(seconds=1))
        self.assertEqual(len(self.cohort.trades()),len(old)+2)

    def test_automatic_first_qualified_quotes_after_0940_use_original_plan(self):
        self.automatic()
        self.quotes.error=ValueError("temporarily no quotes")
        first=self.tick()
        self.assertEqual(first["trades"],[])
        plans=deepcopy(self.cohort.plans)
        self.quotes.error=None
        with patch.object(self.source,"load",side_effect=AssertionError("waiting batch must retain plan")):
            result=self.tick(OPEN+timedelta(hours=1))
        self.assertEqual(result["status"],"EXECUTED")
        self.assertEqual(self.cohort.plans,plans)
        self.assertTrue(all(row["filled_at"]==(OPEN+timedelta(hours=1)).isoformat() for row in result["trades"]))

    def test_automatic_cash_wait_restart_preserves_fixed_targets_and_residual_fill_ids(self):
        self.automatic()
        self.cohort.stop()
        for sid in self.cohort._active_ids():
            self.source.weights[sid]={CODES[0]:.5,CODES[1]:0}
            self.cohort.engines[sid]._set("paper",dict(cash=1000,positions={CODES[1]:90},fees=0))
        self.start()
        self.quotes.errors[CODES[1]]=ValueError("pending sale")
        first=self.tick()
        self.assertEqual(first["status"],"PARTIALLY_EXECUTED")
        for sid in self.cohort._active_ids():
            record=first["books"][sid]["execution"]
            self.assertEqual(record["processed_codes"],[])
            self.assertEqual(record["pending_targets"][CODES[0]],50)
            self.assertEqual(record["status"],"PARTIALLY_EXECUTED")
        plans,old=deepcopy(self.cohort.plans),deepcopy(self.cohort.trades())
        self.cohort.stop()
        self.reopen()
        self.quotes.errors.clear()
        self.start()
        with patch.object(self.source,"load",side_effect=AssertionError("do not revalue after partial fills")):
            result=self.tick(OPEN+timedelta(hours=2))
        self.assertEqual(result["status"],"EXECUTED")
        self.assertEqual(self.cohort.plans,plans)
        for sid in self.cohort._active_ids():
            record=result["books"][sid]["execution"]
            self.assertEqual(record["pending_targets"][CODES[0]],50)
            self.assertEqual(record["code_fill_counts"][CODES[0]],2)
            self.assertEqual(self.cohort.engines[sid]._get("paper",{})["positions"],{CODES[0]:50})
        new=[row for row in self.cohort.trades() if row["id"] not in {x["id"] for x in old}]
        self.assertEqual(len(new),4)
        self.assertEqual(len({row["id"] for row in self.cohort.trades()}),6)

    def test_automatic_close_buffer_stops_new_trades_and_leaves_genuine_pending(self):
        self.automatic()
        self.quotes.error=ValueError("no valid quote yet")
        self.tick()
        self.quotes.error=None
        cutoff=timestamp("2026-09-29T19:50:00+00:00")
        result=self.tick(cutoff)
        self.assertNotEqual(result["status"],"EXECUTED")
        self.assertEqual(result["trades"],[])
        self.assertTrue(all(result["books"][sid]["execution"]["status"]!="EXECUTED"
                            for sid in self.cohort._active_ids()))

    def test_automatic_cash_shortfall_at_deadline_retains_actual_partial_status(self):
        self.automatic()
        self.cohort.stop()
        for sid in self.cohort._active_ids():
            self.source.weights[sid]={CODES[0]:1}
        self.start()
        first=self.tick()
        self.assertEqual(first["status"],"PARTIALLY_EXECUTED")
        for sid in self.cohort._active_ids():
            self.assertEqual(first["books"][sid]["execution"]["processed_codes"],[])
        at_end=self.tick(timestamp("2026-09-29T19:50:00+00:00"))
        self.assertEqual(at_end["status"],"PARTIALLY_EXECUTED")
        self.assertTrue(all(at_end["books"][sid]["execution"]["status"]=="PARTIALLY_EXECUTED"
                            for sid in self.cohort._active_ids()))
        self.assertEqual(len(at_end["trades"]),2)

    def test_automatic_source_gap_prevents_first_trade(self):
        self.automatic()
        original=self.source.status
        def gap(now=None):
            return {**original(now),"data_gaps":["verified source gap"]}
        with patch.object(self.source,"status",side_effect=gap):
            result=self.tick()
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["trades"],[])
        self.assertTrue(all(engine.db.execute("SELECT count(*) FROM paper_batches").fetchone()[0]==0
            for engine in self.cohort._active_engines().values()))

    def test_automatic_source_change_blocks_without_replacing_plan_or_fills(self):
        self.automatic()
        self.quotes.errors[CODES[0]]=ValueError("missing")
        self.tick()
        plans,old=deepcopy(self.cohort.plans),deepcopy(self.cohort.trades())
        self.quotes.errors.clear()
        original=self.source.status
        def changed(now=None):
            return {**original(now),"source_refs":{"manifest":"b"*64}}
        with patch.object(self.source,"status",side_effect=changed):
            result=self.tick(OPEN+timedelta(hours=2))
        self.assertEqual(result["status"],"BLOCKED")
        self.assertIn("SOURCE_CHANGED",result["reason"])
        self.assertEqual(self.cohort.plans,plans)
        self.assertEqual(self.cohort.trades(),old)

    def test_completed_automatic_books_keep_original_live_mark_route_during_long_window(self):
        self.automatic()
        first=self.tick()
        self.assertEqual(first["status"],"EXECUTED")
        old=deepcopy(self.cohort.trades())
        self.quotes.overrides[CODES[0]]=dict(price=110,bid=110,ask=110)
        clock=OPEN+timedelta(hours=3)
        with patch.object(self.cohort,"_mark_current_books",wraps=self.cohort._mark_current_books) as marks:
            current=self.tick(clock)
            marks.assert_called_once_with(now=clock,record_cash=True,respect_stop=True)
        self.assertEqual(current["status"],"EXECUTED")
        self.assertEqual(self.cohort.trades(),old)
        for sid in self.cohort._active_ids():
            engine=self.cohort.engines[sid]
            self.assertEqual(engine._get("paper_marks",{})[CODES[0]]["asof"],clock.isoformat())
            self.assertEqual(engine._get("paper_marks",{})[CODES[0]]["price"],110)
            nav=engine.paper_nav_history()[-1]
            self.assertEqual(nav["asof"],clock.isoformat())
        # The standing policy does not permit session-external market marks.
        with patch.object(self.cohort,"_mark_current_books",wraps=self.cohort._mark_current_books) as marks:
            self.tick(timestamp("2026-09-29T20:00:00+00:00"))
            marks.assert_not_called()
        self.assertEqual(self.cohort.trades(),old)

    def test_incomplete_automatic_books_keep_trade_priority_without_full_mark_poll(self):
        self.automatic()
        self.quotes.errors[CODES[0]]=ValueError("quote still pending")
        first=self.tick()
        self.assertEqual(first["status"],"PARTIALLY_EXECUTED")
        old=deepcopy(self.cohort.trades())
        with patch.object(self.cohort,"_mark_current_books",wraps=self.cohort._mark_current_books) as marks:
            current=self.tick(OPEN+timedelta(hours=3))
            marks.assert_not_called()
        self.assertEqual(current["status"],"PARTIALLY_EXECUTED")
        self.assertEqual(self.cohort.trades(),old)

    def test_nonstanding_completed_books_keep_original_priority_window_mark_behavior(self):
        self.reopen(0,600,True)
        self.start()
        first=self.tick()
        self.assertEqual(first["status"],"EXECUTED")
        old=deepcopy(self.cohort.trades())
        with patch.object(self.cohort,"_mark_current_books",wraps=self.cohort._mark_current_books) as marks:
            self.tick(OPEN+timedelta(seconds=20))
            marks.assert_not_called()
        self.assertEqual(self.cohort.trades(),old)



class NewOrdinaryWindowCohortTests(unittest.TestCase):
    setUp=CohortTests.setUp
    start=CohortTests.start
    tick=CohortTests.tick
    reopen=CohortTests.reopen

    def test_paper_25_minute_window_uses_original_engine_and_deadline(self):
        self.reopen(delay=25,window=1500,partial=True);self.start()
        opening=OPEN+timedelta(minutes=25)
        self.assertEqual(self.tick(opening-timedelta(microseconds=1))["trades"],[])
        inside=self.tick(opening+timedelta(seconds=1499));self.assertTrue(inside["trades"])
        before=deepcopy(inside["trades"]);self.assertEqual(self.tick(opening+timedelta(seconds=1500))["trades"],before)

    def test_completed_paper_signal_defers_clock_and_keeps_batches_byte_identical(self):
        self.reopen(delay=30,window=600,partial=True);self.start()
        completed=self.tick(OPEN+timedelta(minutes=30,seconds=1));self.assertEqual(completed["status"],"EXECUTED")
        before={sid:[tuple(r) for r in e.db.execute("SELECT * FROM paper_batches ORDER BY rowid")] for sid,e in self.cohort.engines.items()}
        self.cohort.stop()
        with patch("moomoo_component.cohort._now",return_value=OPEN+timedelta(hours=1)):
            self.reopen(delay=25,window=1500,partial=True)
        self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(30,600))
        self.assertEqual(self.cohort.meta["next_ordinary_execution_clock"]["execution_window_seconds"],1500)
        self.start();self.tick(OPEN+timedelta(hours=2))
        self.assertEqual({sid:[tuple(r) for r in e.db.execute("SELECT * FROM paper_batches ORDER BY rowid")] for sid,e in self.cohort.engines.items()},before)
        data=self.source.status(now=OPEN+timedelta(days=1))
        data.update(signal_date="2026-09-29",source_date="2026-09-29",execution_date="2026-09-30",
            signal_close_utc="2026-09-29T20:00:00+00:00",next_open_utc="2026-09-30T13:30:00+00:00",next_close_utc="2026-09-30T20:00:00+00:00")
        self.cohort.stop()
        base_close = self.source.close_states
        self.source.status = lambda now=None: deepcopy(data)
        def close_states(books, signal_date):
            values = base_close(books=books, signal_date=signal_date)
            for value in values.values():
                value["close_asof_utc"] = data["signal_close_utc"]
            return values
        self.source.close_states = close_states
        self.source.daily_root = Path(self.temp.name) / "synthetic_daily"
        self.cohort._prepare(data,OPEN+timedelta(hours=8),explicit_update=True)
        self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(25,1500))
        self.assertIsNone(self.cohort.meta["next_ordinary_execution_clock"])
        self.assertEqual({sid:[tuple(r) for r in e.db.execute("SELECT * FROM paper_batches ORDER BY rowid")] for sid,e in self.cohort.engines.items()},before)

    def test_paper_new_window_is_only_explicit_25_1500_pair(self):
        for delay,window in ((25,601),(30,1500),(25,1499),(25,1501),(25,3600)):
            with self.subTest(delay=delay,window=window),self.assertRaises(ValueError):
                Cohort(Path(self.temp.name)/("bad_"+str(delay)+"_"+str(window)),self.source,self.quotes,
                    execution_delay_minutes=delay,execution_window_seconds=window)

    def test_pending_clock_does_not_activate_from_ordinary_tick_in_manual_mode(self):
        self.cohort.manual_data_updates=True
        record=dict(after_signal_date="2026-09-28",previous_delay_minutes=0,previous_window_seconds=60,
            execution_delay_minutes=25,execution_window_seconds=1500)
        self.cohort.meta["next_ordinary_execution_clock"]=record
        self.cohort._persist(event=("ORDINARY_EXECUTION_CLOCK_DEFERRED",record,CLOSE))
        data={**self.source.status(now=OPEN),"signal_date":"2026-09-29","source_date":"2026-09-29"}
        self.assertIsNone(self.cohort._next_ordinary_clock(data,OPEN))
        self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(0,60))

    def test_new_policy_upgrade_preserves_original_hgb_ids_and_old_audit_bytes(self):
        old=AutomaticCohortCompletionTests.automatic(self);self.cohort.stop();old_bytes=json.dumps(old,sort_keys=True)
        self.reopen(delay=25,window=1500,partial=True)
        with self.assertRaisesRegex(ValueError,"SCHEMA2_POLICY_UPDATE_REQUIRED"):self.start()
        self.assertTrue(self.cohort.stop_event.is_set())
        from moomoo_component.best_broker import BestBroker
        from test_best_broker import FakeBroker
        FakeBroker.positions={};FakeBroker.cash=1000000.;FakeBroker.submissions=[]
        engine=Engine(Path(self.temp.name)/"broker-policy",broker_factory=FakeBroker)
        broker=BestBroker(Path(self.temp.name)/"broker-policy",self.source,engine=engine,
            execution_delay_minutes=25,execution_window_seconds=1500,allow_partial_quotes=True)
        self.addCleanup(broker.close);broker._connect()
        engine._set("automatic_completion_policy",old)
        engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(old["authorized_at_utc"],"AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",json.dumps(old)))
        engine.db.commit()
        self.cohort.best_broker=broker
        self.cohort._bind_automatic_completion_policy()
        with patch.object(broker,"_connect",side_effect=AssertionError("no connection while migration missing")):
            with self.assertRaisesRegex(ValueError,"SCHEMA2_POLICY_UPDATE_REQUIRED"):broker.start()
        self.assertTrue(broker.stop_event.is_set())
        now=CLOSE+timedelta(minutes=1)
        new=self.cohort.authorize_automatic_completion_policy(enabled=True,close_buffer_seconds=600,one_tick_spread=True,now=now)
        self.assertEqual(new["schema_version"],2);self.assertEqual(new["execution_delay_minutes"],25)
        self.assertEqual(new["priority_window_seconds"],1500)
        self.assertEqual(new["active_strategy_ids"],["HGB_DIAG_5","HGB_FACTOR_5"])
        self.assertEqual(old_bytes,json.dumps(old,sort_keys=True))
        self.assertTrue(any(json.loads(r[0])==old for r in self.cohort.db.execute("SELECT detail FROM events WHERE event='AUTOMATIC_COMPLETION_POLICY_AUTHORIZED'")) or
            all(any(json.loads(r[0])==old for r in self.cohort.engines[sid].db.execute(
                "SELECT detail FROM audit WHERE event='AUTOMATIC_COMPLETION_POLICY_AUTHORIZED'")) for sid in new["active_strategy_ids"]))
        self.assertIsNone(engine._automatic_completion_policy(OPEN,"R10_DIRECT_H5_RIDGE_MID",execution_date="2026-09-29"))
        data=self.source.status(now=OPEN)
        policy,end=self.cohort._book_execution_window("HGB_DIAG_5",data,OPEN+timedelta(minutes=25))
        self.assertEqual(policy,new);self.assertEqual(end,OPEN+timedelta(minutes=50))
        broker.plan={"rows":[]};broker.metadata=data;broker._now=lambda:OPEN+timedelta(minutes=25)
        self.assertEqual(broker._automatic_completion()[1],OPEN+timedelta(minutes=50))
        self.assertEqual(broker._execution_end(),OPEN+timedelta(minutes=50))
        self.cohort.best_broker=None  # Broker deadline was checked above; paper tick stays isolated.
        self.start();self.quotes.error=ValueError("fake missing quotes")
        self.tick(OPEN+timedelta(minutes=25));self.quotes.error=None
        self.assertEqual(self.tick(OPEN+timedelta(minutes=50))["trades"],[])
        self.assertEqual(self.tick(OPEN+timedelta(hours=2))["trades"],[])

if __name__ == "__main__":
    unittest.main()


from moomoo_component.applied_source import DailySource
class ClosedPaperTests(unittest.TestCase):
    setUp=HgbEpochResetTests.setUp
    start=HgbEpochResetTests.start;tick=HgbEpochResetTests.tick;seed=HgbEpochResetTests.seed;reset=HgbEpochResetTests.reset
    def make(self,partial=False):
        from test_best_broker import _closed_decision_fixture, _closed_write
        self.cohort.allow_partial_quotes=True;self.seed();day=self.request['signal_date'];plans={sid:dict(policy_id='HGB_TOP20_RISK_R1',rows=[dict(code=k,ticker=k[3:],target_weight=v) for k,v in self.source.weights[sid].items()],target_cash_weight=1-sum(self.source.weights[sid].values())) for sid in ['HGB_DIAG_5','HGB_FACTOR_5']}
        self.d=_closed_decision_fixture(self.temp.name,day,plans);base_status=self.source.status;self.live_refs=deepcopy(self.d['refs']);self.source.status=lambda now=None:{**base_status(now),"source_refs":deepcopy(self.live_refs)}
        self.source.package=Path(self.d['refs']['selected/package.json']['path']);self.source.package_sha=self.d['refs']['selected/package.json']['sha256'];self.request['expected_package_sha256']=self.source.package_sha
        original=DailySource._archive
        def enrich(owner,result,states=None):result['scores']=deepcopy(self.d['archive']['scores']);result['source_hashes']=deepcopy(self.d['archive']['source_hashes']);return original(owner,result,states)
        with patch.object(DailySource,'_archive',enrich):self.reset()
        self.start();self.opening=OPEN+timedelta(days=1)
        if partial:self.quotes.errors['US.AA']='synthetic missing quote'
        self.tick(self.opening+timedelta(seconds=10))
        self.d['package']['performance_period']['end']='2026-09-30';self.live_refs['selected/package.json']=_closed_write(self.d['folder']/'latest.json',self.d['package'])
    def immutable_books(self):
        return {sid:dict(cash=e.paper_book()['cash'],positions={p['code']:p['qty'] for p in e.paper_book()['positions']},fees=e.paper_book()['fees'],fills=e.paper_trades(),batches=e.db.execute('select id,payload from paper_batches order by id').fetchall(),plan=deepcopy(self.cohort.plans[sid])) for sid,e in self.cohort.engines.items()}
    def test_closed_executed_books_mark_only_and_preserve_paused_raw_all_fills_and_plans(self):
        self.make();before=self.immutable_books()
        with patch.object(self.source,'load',side_effect=AssertionError('no load')),patch.object(self.source,'close_states',side_effect=AssertionError('no old close')):
            result=self.tick(self.opening+timedelta(seconds=601))
        self.assertEqual(result['status'],'EXECUTED');self.assertEqual(self.immutable_books(),before);self.assertEqual(result['books']['RAW_A2']['status'],'PAUSED')
    def test_partial_or_active_paper_window_keeps_old_strict_source_guard(self):
        self.make(partial=True);before=self.immutable_books();result=self.tick(self.opening+timedelta(seconds=601))
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(self.immutable_books(),before)
    def test_closed_paper_real_input_changed_is_blocked(self):
        from test_best_broker import _closed_write
        self.make();self.d['package']['strategies']['HGB_FACTOR_5']['application']['target_cash_weight']-=.01;self.live_refs['selected/package.json']=_closed_write(self.d['folder']/'latest.json',self.d['package']);before=self.immutable_books()
        result=self.tick(self.opening+timedelta(seconds=601));self.assertEqual(result['status'],'BLOCKED');self.assertEqual(self.immutable_books(),before)
    def test_expired_paper_catchup_is_not_renewed_and_record_retained(self):
        self.make();record=dict(signal_date=self.request['signal_date'],execution_date=self.opening.date().isoformat(),deadline_utc=(self.opening+timedelta(seconds=1200)).isoformat(),books={});self.cohort.meta['paper_same_day_catchup']=record
        data=self.source.status(now=self.opening+timedelta(seconds=1200));self.assertIsNone(self.cohort._catchup_end(data,self.opening+timedelta(seconds=1200)));self.assertEqual(self.cohort.meta['paper_same_day_catchup'],record)


class ExecutionChartsHookTests(unittest.TestCase):
    """Fixed chart job only; all processes, owner receipts and market clocks are fake."""
    def setUp(self):
        from unittest.mock import Mock
        CohortTests.setUp(self)
        self.cohort.stop_event.clear()
        self.clock = OPEN + timedelta(seconds=601)
        self.data = self.source.status(now=self.clock)
        self.data['source_refs']['selected/package.json'] = {'path': 'synthetic-only-package.json', 'sha256': 'a' * 64}
        self.job = Mock()
        self.job.poll.return_value = None
        self.source.start_execution_charts = Mock(return_value=self.job)
        self.source.execution_charts_status = Mock(return_value={'status': 'UNAVAILABLE'})
        self.ready = dict(status='READY', signal_date=self.data['signal_date'], execution_date=self.data['execution_date'], package_sha256='a' * 64)
    def call(self, clock=None, data=None):
        self.cohort._execution_charts_tick(self.data if data is None else data, self.clock if clock is None else clock)
    def test_single_async_job_while_running_has_no_replan_trade_or_policy_change(self):
        before = {sid: e.paper_book() for sid, e in self.cohort.engines.items()}
        policy = self.cohort.execution_delay_minutes, self.cohort.execution_window_seconds, self.cohort.allow_partial_quotes
        with patch.object(self.source, 'load', side_effect=AssertionError('no inference')), patch.object(self.source, 'refresh', side_effect=AssertionError('no refresh')):
            for _ in range(5): self.call()
        self.source.start_execution_charts.assert_called_once_with()
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'], 'RUNNING')
        self.assertEqual({sid: e.paper_book() for sid, e in self.cohort.engines.items()}, before)
        self.assertEqual((self.cohort.execution_delay_minutes, self.cohort.execution_window_seconds, self.cohort.allow_partial_quotes), policy)
    def test_ready_owner_receipt_stops_repeated_job_and_survives_handle_restart(self):
        self.call(); self.job.poll.return_value = 0; self.source.execution_charts_status.return_value = self.ready
        self.call(); self.cohort._execution_charts_job = None
        for _ in range(3): self.call(clock=self.clock + timedelta(minutes=5))
        self.source.start_execution_charts.assert_called_once_with()
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'], 'READY')
    def test_rc_zero_waiting_or_wrong_date_or_sha_is_retryable_not_success(self):
        for changed in ({'status':'WAITING_SOURCE'}, {'execution_date':'2026-09-30'}, {'package_sha256':'b'*64}, {'signal_date':'2026-09-27'}):
            with self.subTest(changed=changed):
                self.cohort._execution_charts_job = None; self.cohort.meta.pop('execution_charts_update', None)
                self.source.execution_charts_status.return_value = {'status':'UNAVAILABLE'}; self.job.poll.return_value = None; self.call()
                self.source.execution_charts_status.return_value = {**self.ready, **changed}; self.job.poll.return_value = 0; self.call()
                update = self.cohort.meta['execution_charts_update']; self.assertEqual(update['status'],'RETRY_WAIT')
                self.assertEqual(timestamp(update['next_retry_at_utc']),self.clock+timedelta(minutes=15)); self.assertTrue(update['error'])
    def test_worker_failure_retries_only_after_fifteen_minutes(self):
        self.call(); self.job.poll.return_value = 2; self.call()
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'RETRY_WAIT')
        self.call(clock=self.clock+timedelta(minutes=14)); self.assertEqual(self.source.start_execution_charts.call_count,1)
        self.job.poll.return_value = None; self.call(clock=self.clock+timedelta(minutes=15))
        self.assertEqual(self.source.start_execution_charts.call_count,2)
    def test_stop_halt_before_open_after_close_unready_or_identity_gap_never_starts(self):
        cases = ['stop','halt','before','active_window','waiting','gap','stale_source','wrong_date','bad_sha']
        for case in cases:
            with self.subTest(case=case):
                self.cohort.stop_event.clear(); self.cohort.halt_event.clear(); d=deepcopy(self.data); t=self.clock
                if case=='stop':self.cohort.stop_event.set()
                if case=='halt':self.cohort.halt_event.set()
                if case=='before':t=OPEN-timedelta(seconds=1)
                if case=='active_window':t=OPEN+timedelta(seconds=1)
                if case=='waiting':d['status']='WAITING_SOURCE'
                if case=='gap':d['data_gaps']=['synthetic missing input']
                if case=='stale_source':d['source_date']='2026-09-27'
                if case=='wrong_date':d['execution_date']='2026-09-30'
                if case=='bad_sha':d['source_refs']['selected/package.json']['sha256']='bad'
                self.call(clock=t,data=d)
        self.source.start_execution_charts.assert_not_called()
        self.cohort.stop_event.clear();self.cohort.halt_event.clear()
    def test_maintenance_waits_for_standing_book_deadline_even_when_ordinary_window_closed(self):
        from unittest.mock import patch
        self.cohort.execution_window_seconds=600;self.cohort.allow_partial_quotes=True
        closing=timestamp(self.data["next_close_utc"])
        policy=dict(priority_window_seconds=600,close_buffer_seconds=600)
        engines=self.cohort._active_engines()
        with __import__('contextlib').ExitStack() as stack:
            for sid,engine in engines.items():
                stack.enter_context(patch.object(engine,"_automatic_completion_policy",return_value=policy if sid=="HGB_DIAG_5" else None))
            self.call(clock=closing-timedelta(seconds=601));self.source.start_execution_charts.assert_not_called()
            self.call(clock=closing-timedelta(seconds=600));self.source.start_execution_charts.assert_called_once_with()

    def test_maintenance_waits_for_broker_window_and_pending_or_halted_account(self):
        import threading
        from types import SimpleNamespace
        pending=[];halt=threading.Event()
        broker=SimpleNamespace(lock=threading.RLock(),engine=SimpleNamespace(halt_event=halt,_pending=lambda:pending),
            execution_window_seconds=1200,plan=None,metadata={},_scheduled_open=timestamp)
        self.cohort.best_broker=broker
        try:
            self.call();self.source.start_execution_charts.assert_not_called()
            pending.append({"id":"unknown"});self.call(clock=OPEN+timedelta(seconds=1200));self.source.start_execution_charts.assert_not_called()
            pending.clear();halt.set();self.call(clock=OPEN+timedelta(seconds=1200));self.source.start_execution_charts.assert_not_called()
            halt.clear();self.call(clock=OPEN+timedelta(seconds=1200));self.source.start_execution_charts.assert_called_once_with()
        finally:self.cohort.best_broker=None

    def test_future_legacy_open_keeps_original_waiting_open_without_replay(self):
        data=deepcopy(self.data);data.update(signal_date="2026-09-28",source_date="2026-09-28",execution_date="2026-09-29",
            signal_close_utc="2026-09-28T20:00:00+00:00",next_open_utc="2026-09-29T13:30:00+00:00",next_close_utc="2026-09-29T20:00:00+00:00")
        close=timestamp(data["signal_close_utc"])
        self.call(data=data,clock=close-timedelta(seconds=1));self.source.start_execution_charts.assert_not_called()
        self.call(data=data,clock=close+timedelta(seconds=1));self.source.start_execution_charts.assert_not_called()
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'WAITING_OPEN')

    def test_existing_persistent_same_context_ready_receipt_reuses_without_spawn(self):
        self.source.execution_charts_status.return_value=self.ready
        self.call();self.assertEqual(self.cohort.meta['execution_charts_update']['action'],'REUSED_OWNER_RECEIPT')
        self.source.start_execution_charts.assert_not_called()
    def test_chart_start_failure_after_trading_tick_does_not_block_paper_execution(self):
        self.source.start_execution_charts.side_effect=RuntimeError('synthetic chart child start failed')
        original=self.source.status
        self.source.status=lambda now=None:{**original(now),'source_refs':deepcopy(self.data['source_refs'])}
        self.quotes.clock=OPEN+timedelta(seconds=10)
        result=self.cohort.tick(now=OPEN+timedelta(seconds=10))
        self.assertEqual(result['status'],'EXECUTED');self.assertEqual(self.cohort.meta['status'],'EXECUTED')
        self.call()  # Trading has finished; only now may maintenance attempt its provider.
        update=self.cohort.meta['execution_charts_update'];self.assertEqual(update['status'],'RETRY_WAIT');self.assertIn('child start failed',update['error'])
        self.assertTrue(all(self.cohort.engines[sid].paper_book()['trade_count'] for sid in STRATEGIES))


class RefreshWindowBoundaryTests(unittest.TestCase):
    """Source refresh follows the existing window; all quotes/inputs are synthetic."""
    setUp = CohortTests.setUp
    start = CohortTests.start
    tick = CohortTests.tick

    def make(self, *, delay=0, window=600, missing=True):
        self.cohort.close()
        self.source, self.quotes = Source(), Quotes()
        self.source.missing = missing
        self.case_count = getattr(self, "case_count", 0) + 1
        self.cohort = Cohort(Path(self.temp.name) / str(self.case_count), self.source, self.quotes,
            execution_delay_minutes=delay, execution_window_seconds=window, allow_partial_quotes=True)
        self.start()

    def durable_books(self):
        return {sid: dict(cash=e.paper_book()["cash"], fees=e.paper_book()["fees"],
            positions={row["code"]:row["qty"] for row in e.paper_book()["positions"]},
            fills=e.paper_trades(), batches=[tuple(row) for row in e.db.execute(
                "SELECT id,payload FROM paper_batches ORDER BY id")])
            for sid,e in self.cohort.engines.items()}

    def test_six_hundred_second_window_refreshes_at_ninety_and_599_seconds(self):
        for seconds in (90,599):
            with self.subTest(seconds=seconds):
                self.make();clock=OPEN+timedelta(seconds=seconds)
                result=self.tick(clock)
                self.assertEqual(self.source.refresh_count,1)
                self.assertEqual(result["status"],"EXECUTED")
                self.assertTrue(result["trades"])
                self.assertTrue(all(row["filled_at"]==clock.isoformat() for row in result["trades"]))
                self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(0,600))

    def test_six_hundred_second_end_is_exclusive_without_refresh_or_fill(self):
        for seconds in (600,601):
            with self.subTest(seconds=seconds):
                self.make();before=self.durable_books()
                result=self.tick(OPEN+timedelta(seconds=seconds))
                self.assertEqual(self.source.refresh_count,0)
                self.assertEqual(self.durable_books(),before)
                self.assertEqual(result["trades"],[])
                self.assertEqual(self.quotes.calls,[])

    def test_delayed_window_uses_scheduled_open_and_exact_end(self):
        for delay in (45,180):
            for offset,allowed,executed in ((-1,True,False),(90,True,True),(599,True,True),(600,False,False)):
                with self.subTest(delay=delay,offset=offset):
                    self.make(delay=delay);clock=OPEN+timedelta(minutes=delay,seconds=offset)
                    result=self.tick(clock)
                    self.assertEqual(self.source.refresh_count,int(allowed))
                    self.assertEqual(bool(result["trades"]),executed)
                    if not executed:self.assertEqual(self.quotes.calls,[])
                    self.assertEqual(self.cohort.execution_window_seconds,600)
                    self.assertEqual(result["next_open_utc"],OPEN.isoformat())

    def test_closed_old_signal_does_not_refresh_or_replay_during_session(self):
        self.make(missing=False);self.tick(OPEN+timedelta(seconds=10));before=self.durable_books()
        self.source.missing=True
        for seconds in (600,601,3600):
            with self.subTest(seconds=seconds):
                result=self.tick(OPEN+timedelta(seconds=seconds))
                self.assertEqual(self.source.refresh_count,0)
                self.assertEqual(self.durable_books(),before)
                self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(0,600))

    def test_original_sixty_second_configuration_keeps_its_deadline(self):
        for seconds,allowed in ((59,True),(60,False),(90,False)):
            with self.subTest(seconds=seconds):
                self.make(window=60);result=self.tick(OPEN+timedelta(seconds=seconds))
                self.assertEqual(self.source.refresh_count,int(allowed))
                self.assertEqual(bool(result["trades"]),allowed)
                self.assertEqual(self.cohort.execution_window_seconds,60)

    def test_after_close_refresh_prepares_next_signal_without_replaying_old_batch(self):
        self.make(missing=False);self.tick(OPEN+timedelta(seconds=10));before=self.durable_books()
        prior_status=self.source.status;prior_refresh=self.source.refresh;prior_closes=self.source.close_states
        next_open=OPEN+timedelta(days=1);next_close=OPEN.replace(hour=20,minute=0)
        updated={**prior_status(now=OPEN),"signal_date":"2026-09-29","source_date":"2026-09-29",
            "execution_date":"2026-09-30","signal_close_utc":next_close.isoformat(),
            "next_open_utc":next_open.isoformat(),"next_close_utc":(next_close+timedelta(days=1)).isoformat(),"data_gaps":[]}
        rotated=[False];self.source.missing=True
        def refresh():prior_refresh();rotated[0]=True
        def status(now=None):
            if not rotated[0]:return prior_status(now=now)
            return {**updated,"status":"READY" if now<next_open else "OPEN_WINDOW" if now<next_open+timedelta(seconds=60) else "MISSED_OPEN"}
        def closes(books,signal_date):
            values=prior_closes(books,signal_date)
            for value in values.values():value["close_asof_utc"]=next_close.isoformat()
            return values
        self.source.refresh,self.source.status,self.source.close_states=refresh,status,closes
        night=next_close+timedelta(seconds=61);result=self.tick(night)
        self.assertEqual(self.source.refresh_count,1)
        self.assertEqual(result["status"],"WAITING_OPEN")
        self.assertEqual(result["signal_date"],"2026-09-29")
        self.assertEqual(result["execution_date"],"2026-09-30")
        self.assertEqual(self.durable_books(),before)
        result=self.tick(next_open+timedelta(seconds=10));self.assertEqual(result["status"],"EXECUTED")
        after=self.durable_books()
        for sid in STRATEGIES:
            original={row["id"]:row for row in before[sid]["fills"]}
            self.assertEqual({row["id"]:row for row in after[sid]["fills"] if row["id"] in original},original)
            self.assertTrue(any(row["execution_date"]=="2026-09-30" for row in after[sid]["fills"]))
        self.tick(next_open+timedelta(seconds=20));self.assertEqual(self.durable_books(),after)
        self.assertEqual(self.source.refresh_count,1)


class PaperCatchupRenewalTests(unittest.TestCase):
    """Explicit one-time KDK renewal; synthetic paper books only."""
    setUp = CohortTests.setUp
    start = CohortTests.start
    tick = CohortTests.tick
    reopen = CohortTests.reopen
    CODE = "US.KDK"

    def expired_permission(self):
        import hashlib
        from moomoo_component.cohort import _bytes
        self.source.weights.pop("RAW_A2")
        for weights in self.source.weights.values():
            weights[self.CODE] = weights.pop(CODES[0])
        self.source.prices[self.CODE] = 100
        self.reopen(0, 600, True)
        self.cohort.meta["active_strategy_ids"] = ["HGB_DIAG_5", "HGB_FACTOR_5"]
        self.cohort._persist()
        self.start()
        self.quotes.errors[self.CODE] = ValueError("KDK original quote unavailable")
        self.first = self.tick(OPEN + timedelta(seconds=10))
        self.assertTrue(all(self.first["books"][sid]["execution"]["status"] == "PARTIALLY_EXECUTED" for sid in self.cohort._active_ids()))
        self.cohort.stop()
        authorized = OPEN + timedelta(minutes=20)
        self.old = self.cohort.authorize_catchup(execution_date="2026-09-29",
            deadline_utc=(authorized + timedelta(seconds=600)).isoformat(), now=authorized)
        self.old_sha = hashlib.sha256(_bytes(self.old)).hexdigest()
        self.now = authorized + timedelta(seconds=601)
        self.deadline = self.now + timedelta(seconds=600)
        self.old_book_bytes = {sid: engine.db.execute("SELECT value FROM settings WHERE key='paper_same_day_catchup'").fetchone()[0]
            for sid, engine in self.cohort._active_engines().items()}
        self.batches = {sid: engine.db.execute("SELECT payload FROM paper_batches").fetchone()[0]
            for sid, engine in self.cohort._active_engines().items()}

    def renew(self, **changes):
        values = dict(execution_date="2026-09-29", deadline_utc=self.deadline.isoformat(),
            expected_prior_sha256=self.old_sha, renewal_id="manual_renewal_fixture", now=self.now,
            allowed_codes=[self.CODE])
        values.update(changes)
        return self.cohort.renew_catchup(**values)

    def test_renewal_keeps_old_bytes_and_resumes_only_remaining_KDK_after_restart(self):
        self.expired_permission()
        plans = deepcopy(self.cohort.plans)
        calls = len(self.quotes.calls)
        record = self.renew()
        self.assertEqual(record["expected_prior_sha256"], self.old_sha)
        self.assertEqual(record["allowed_codes"], [self.CODE])
        self.assertEqual(self.cohort.meta["paper_same_day_catchup"], self.old)
        for sid, engine in self.cohort._active_engines().items():
            self.assertEqual(engine.db.execute("SELECT value FROM settings WHERE key='paper_same_day_catchup'").fetchone()[0], self.old_book_bytes[sid])
            self.assertEqual(engine.db.execute("SELECT payload FROM paper_batches").fetchone()[0], self.batches[sid])
        self.assertEqual(len(self.quotes.calls), calls)
        self.assertEqual(self.cohort.trades(), self.first["trades"])
        self.reopen()
        self.assertEqual(self.cohort.meta["paper_same_day_catchup_renewal"], record)
        self.quotes.errors.clear()
        self.start()
        fill_time = self.now + timedelta(seconds=1)
        with patch.object(self.source, "load", side_effect=AssertionError("do not re-infer or replace plan")):
            resumed = self.tick(fill_time)
        old_ids = {row["id"] for row in self.first["trades"]}
        fresh = [row for row in resumed["trades"] if row["id"] not in old_ids]
        self.assertEqual(len(fresh), 2)
        self.assertEqual({row["code"] for row in fresh}, {self.CODE})
        self.assertEqual({row["filled_at"] for row in fresh}, {fill_time.isoformat()})
        self.assertEqual([row for row in resumed["trades"] if row["id"] in old_ids], self.first["trades"])
        self.assertEqual(self.cohort.plans, plans)
        for sid in self.cohort._active_ids():
            before, after = json.loads(self.batches[sid]), resumed["books"][sid]["execution"]
            self.assertEqual(after["pretrade_equity"], before["pretrade_equity"])
            self.assertEqual(after["execution_decisions"][:len(before["execution_decisions"])], before["execution_decisions"])
            self.assertEqual(after["source_plan_sha256"], before["source_plan_sha256"])
        self.assertEqual(self.tick(fill_time + timedelta(seconds=1))["trades"], resumed["trades"])

    def test_identical_renewal_idempotent_but_never_renews_twice_or_changes_default_authorize(self):
        self.expired_permission()
        record = self.renew()
        self.assertEqual(self.renew(now=self.now + timedelta(seconds=1)), record)
        with self.assertRaisesRegex(ValueError, "ALREADY_RENEWED"):
            self.renew(renewal_id="different_manual_renewal")
        with self.assertRaisesRegex(ValueError, "ALREADY_AUTHORIZED"):
            self.cohort.authorize_catchup(execution_date="2026-09-29", deadline_utc=self.deadline.isoformat(), now=self.now)
        self.assertEqual(self.cohort._poll_delay(now=self.now), 1.0)

    def test_renewed_deadline_is_exclusive_and_does_not_reopen_next_day(self):
        self.expired_permission()
        self.renew()
        self.quotes.errors.clear()
        self.start()
        self.assertEqual(self.tick(self.deadline)["trades"], self.first["trades"])
        self.reopen()
        self.start()
        self.assertEqual(self.tick(self.deadline + timedelta(seconds=1))["trades"], self.first["trades"])
        self.assertEqual(self.tick(self.now + timedelta(days=1))["trades"], self.first["trades"])
        self.assertEqual(self.cohort._poll_delay(now=self.deadline), 30.0)

    def test_bad_deadlines_dates_prior_hash_scope_and_active_original_never_grant(self):
        self.expired_permission()
        cases = [dict(deadline_utc=(self.now+timedelta(seconds=601)).isoformat()),
            dict(deadline_utc=self.now.isoformat()), dict(deadline_utc="2026-09-29T20:00:01+00:00"),
            dict(now=timestamp(self.old["deadline_utc"])-timedelta(seconds=1)),
            dict(now=self.now+timedelta(days=1),deadline_utc=(self.deadline+timedelta(days=1)).isoformat()),
            dict(expected_prior_sha256="0"*64), dict(allowed_codes=[self.CODE,"US.MASS"]),
            dict(allowed_codes=["KDK"]), dict(execution_date="2026-09-30"), dict(now=None),
            dict(now=self.now.replace(tzinfo=None)), dict(renewal_id="short")]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.renew(**changes)
        self.assertNotIn("paper_same_day_catchup_renewal", self.cohort.meta)
        self.assertEqual(self.cohort.trades(), self.first["trades"])

    def test_worker_tick_pending_halt_and_changed_source_or_account_reject(self):
        self.expired_permission()
        self.cohort.stop_event.clear()
        with self.assertRaisesRegex(ValueError, "STOPPED"):
            self.renew()
        self.cohort.stop_event.set()
        self.cohort.tick_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "WAIT_FOR_TICK"):
                self.renew()
        finally:
            self.cohort.tick_lock.release()
        engine = self.cohort.engines["HGB_DIAG_5"]
        with patch.object(engine, "_pending", return_value=[dict(status="UNKNOWN")]), self.assertRaisesRegex(ValueError,"PENDING"):
            self.renew()
        engine.halt_event.set()
        with self.assertRaisesRegex(ValueError,"PENDING_OR_HALTED"):
            self.renew()
        engine.halt_event.clear()
        with patch.object(self.source,"status",return_value={**self.source.status(self.now),"source_refs":{"manifest":"f"*64}}), self.assertRaisesRegex(ValueError,"SOURCE_CHANGED"):
            self.renew()
        original_account=engine.account_id
        engine.account_id="another-paper-account"
        with self.assertRaisesRegex(ValueError,"BINDING_INVALID"):
            self.renew()
        engine.account_id=original_account
        self.assertNotIn("paper_same_day_catchup_renewal",self.cohort.meta)

    def test_original_batch_plan_equity_and_processed_quantities_cannot_change(self):
        self.expired_permission()
        engine=self.cohort.engines["HGB_DIAG_5"]
        original=json.loads(self.batches["HGB_DIAG_5"])
        for key,value in (("pretrade_equity",1),("source_plan_sha256","f"*64),("processed_codes",[])):
            engine.db.execute("UPDATE paper_batches SET payload=?",(json.dumps({**original,key:value}),));engine.db.commit()
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,"BINDING_INVALID"):
                self.renew()
        engine.db.execute("UPDATE paper_batches SET payload=?",(json.dumps(original),));engine.db.commit()
        self.assertNotIn("paper_same_day_catchup_renewal",self.cohort.meta)

    def test_renewed_quotes_keep_all_original_execution_guards(self):
        self.expired_permission()
        self.renew();self.start();self.quotes.errors.clear()
        for changes in (dict(asof=(self.now-timedelta(seconds=31)).isoformat()),dict(asof=(self.now+timedelta(seconds=1)).isoformat()),
                        dict(bid=99,ask=102),dict(tradable=False),dict(currency="HKD"),dict(lot_size=100)):
            self.quotes.overrides[self.CODE]=changes
            with self.subTest(changes=changes):
                self.assertEqual(self.tick(self.now)["trades"],self.first["trades"])

    def test_core_rejects_renewal_record_tampering_and_keeps_old_decision_prefix(self):
        self.expired_permission();record=self.renew();self.start();self.quotes.errors.clear()
        engine=self.cohort.engines["HGB_DIAG_5"];permission=record["books"]["HGB_DIAG_5"]
        clock=self.now+timedelta(seconds=1);self.quotes.clock=clock;quotes=self.quotes.quotes([self.CODE])
        for key,value in (("prior_permission_sha256","f"*64),("allowed_codes",["US.MASS"]),
                          ("prior_execution_decisions",[]),("processed_codes",["US.ZZ"]),
                          ("deadline_utc",(self.now+timedelta(seconds=601)).isoformat())):
            mutated={**permission,key:value}
            engine._set("paper_same_day_catchup_renewal",mutated)
            with self.subTest(key=key),self.assertRaises(ValueError):
                engine.paper_rebalance("HGB_DIAG_5",self.cohort.plans["HGB_DIAG_5"],quotes,now=clock,
                    next_open_utc=OPEN.isoformat(),signal_date="2026-09-28",execution_date="2026-09-29",
                    signal_close_utc=CLOSE.isoformat(),source_refs=self.cohort.plan_metadata["source_refs"],
                    allow_partial_quotes=True,execution_window_seconds=600)
        engine._set("paper_same_day_catchup_renewal",permission)
        self.assertEqual(self.cohort.trades(),self.first["trades"])

    def test_partial_settings_failure_restores_only_new_keys_and_preserves_old_bytes(self):
        self.expired_permission()
        engine=self.cohort.engines["HGB_FACTOR_5"]
        with patch.object(engine,"_set",side_effect=OSError("synthetic disk error")),self.assertRaises(OSError):
            self.renew()
        self.assertNotIn("paper_same_day_catchup_renewal",self.cohort.meta)
        for sid,book in self.cohort._active_engines().items():
            self.assertIsNone(book._get("paper_same_day_catchup_renewal",None))
            self.assertEqual(book.db.execute("SELECT value FROM settings WHERE key='paper_same_day_catchup'").fetchone()[0],self.old_book_bytes[sid])
        self.assertEqual(self.cohort.trades(),self.first["trades"])

    def test_slow_metadata_validation_cannot_grant_after_new_deadline(self):
        self.expired_permission()
        with patch("moomoo_component.cohort.time.monotonic",side_effect=[0,601]),self.assertRaisesRegex(ValueError,"EXPIRED_DURING_VALIDATION"):
            self.renew()
        self.assertNotIn("paper_same_day_catchup_renewal",self.cohort.meta)

    def test_restart_preserves_exact_frozen_clock_lexeme_only_with_unchanged_policy(self):
        self.expired_permission()
        metadata = deepcopy(self.cohort.plan_metadata)
        metadata["execution_time_utc"] = metadata["execution_time_utc"].replace("+00:00", "Z")
        self.cohort.plan_metadata = deepcopy(metadata)
        self.cohort._persist()
        self.reopen()
        self.assertEqual(self.cohort.plan_metadata, metadata)
        self.assertEqual(self.cohort.meta["paper_same_day_catchup"], self.old)
        self.assertEqual(self.cohort.trades(), self.first["trades"])
        self.reopen(delay=1)
        self.assertEqual(self.cohort.plan_metadata["execution_time_utc"], (OPEN + timedelta(minutes=1)).isoformat())
        self.assertEqual(self.cohort.plan_metadata["execution_delay_minutes"], 1)
        self.assertEqual(self.cohort.trades(), self.first["trades"])


    def zero_target_scope_fixture(self, extra_pending=False):
        for sid, qty in (('HGB_DIAG_5', 366), ('HGB_FACTOR_5', 309)):
            self.source.weights[sid][CODES[0]] = 0
            engine = self.cohort.engines[sid]
            engine._set('paper', {'cash': 10000 - qty * 1.7, 'positions': {'US.KDK': qty}, 'fees': 0})
            engine._set('paper_marks', {'US.KDK': {'price': 1.7, 'asof': CLOSE.isoformat(), 'source': 'SYNTHETIC'}})
        if extra_pending:
            self.quotes.errors[CODES[1]] = ValueError('synthetic other ticker pending')
        self.expired_permission()

    def quotes_for_scope(self, **changes):
        stamp = self.now + timedelta(seconds=1)
        self.quotes.clock = stamp
        quote = self.quotes.quotes(['US.KDK'])['US.KDK']
        quote.update(price=1.7, bid=1.695, ask=1.705)
        quote.update(changes)
        return (stamp, {'US.KDK': quote})

    def direct_scope_execution(self, sid='HGB_DIAG_5', **changes):
        self.start()
        stamp, quotes = self.quotes_for_scope(**changes)
        engine = self.cohort.engines[sid]
        return engine.paper_rebalance(sid, self.cohort.plans[sid], quotes, now=stamp, next_open_utc=self.cohort.plan_metadata['execution_time_utc'], signal_date=self.cohort.plan_metadata['signal_date'], execution_date=self.cohort.plan_metadata['execution_date'], signal_close_utc=self.cohort.plan_metadata['signal_close_utc'], source_refs=self.cohort.plan_metadata['source_refs'], allow_partial_quotes=True, execution_window_seconds=600)

    def test_signed_sixty_bp_sells_only_original_kdk_caps_and_preserves_other_fills(self):
        self.zero_target_scope_fixture()
        plans = deepcopy(self.cohort.plans)
        old_trades = deepcopy(self.cohort.trades())
        record = self.renew(single_sell_spread_bps=60)
        for sid, qty in (('HGB_DIAG_5', 366), ('HGB_FACTOR_5', 309)):
            permission = record['books'][sid]
            self.assertEqual(permission['single_sell_override'], dict(code='US.KDK', side='SELL', target_qty=0, max_qty=qty, spread_bps=60))
            engine = self.cohort.engines[sid]
            self.assertEqual(engine.db.execute("SELECT value FROM settings WHERE key='paper_same_day_catchup'").fetchone()[0], self.old_book_bytes[sid])
            self.assertEqual(engine.db.execute('SELECT payload FROM paper_batches').fetchone()[0], self.batches[sid])
        self.reopen()
        self.quotes.errors.clear()
        self.quotes.overrides['US.KDK'] = dict(price=1.7, bid=1.695, ask=1.705)
        self.start()
        state = self.tick(self.now + timedelta(seconds=1))
        self.assertEqual(state['status'], 'EXECUTED')
        old_ids = {row['id'] for row in old_trades}
        new = [row for row in self.cohort.trades() if row['id'] not in old_ids]
        self.assertEqual(sorted(((row['strategy_id'], row['code'], row['side'], row['qty']) for row in new)), [('HGB_DIAG_5', 'US.KDK', 'SELL', 366), ('HGB_FACTOR_5', 'US.KDK', 'SELL', 309)])
        self.assertTrue(all((row['fee_bps'] == 5 for row in new)))
        self.assertEqual(self.cohort.plans, plans)
        self.assertEqual([row for row in self.cohort.trades() if row['id'] in old_ids], old_trades)
        committed = deepcopy(self.cohort.trades())
        self.tick(self.now + timedelta(seconds=2))
        self.assertEqual(self.cohort.trades(), committed)
        for engine in self.cohort._active_engines().values():
            self.assertEqual(engine._get('paper', {})['positions'].get('US.KDK', 0), 0)

    def test_default_renewal_retains_fifty_bp(self):
        self.zero_target_scope_fixture()
        self.renew()
        before = deepcopy(self.cohort.trades())
        self.quotes.errors.clear()
        result = self.direct_scope_execution()
        self.assertEqual(result['new_fill_count'], 0)
        self.assertIn('上限50bp', result['reason'])
        self.assertEqual(self.cohort.trades(), before)

    def test_sixty_bp_scope_rejects_invalid_values_other_pending_and_buy_targets(self):
        self.zero_target_scope_fixture()
        for value in (50, 61, True, 60.0, '60'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.renew(single_sell_spread_bps=value)
        self.assertNotIn('paper_same_day_catchup_renewal', self.cohort.meta)
        self.cohort.plans['HGB_DIAG_5']['rows'][0]['target_weight'] += 0.01
        with self.assertRaises(ValueError):
            self.renew(single_sell_spread_bps=60)
        self.assertNotIn('paper_same_day_catchup_renewal', self.cohort.meta)

    def test_other_pending_ticker_cannot_receive_the_sixty_bp_scope(self):
        self.zero_target_scope_fixture(extra_pending=True)
        before = deepcopy(self.cohort.trades())
        with self.assertRaisesRegex(ValueError, 'REMAINDER_SCOPE_CHANGED'):
            self.renew(single_sell_spread_bps=60)
        self.assertEqual(self.cohort.trades(), before)
        self.assertNotIn('paper_same_day_catchup_renewal', self.cohort.meta)

    def test_positive_original_kdk_weight_cannot_authorize_a_sell_override(self):
        self.expired_permission()
        before = deepcopy(self.cohort.trades())
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_ZERO_TARGET'):
            self.renew(single_sell_spread_bps=60)
        self.assertEqual(self.cohort.trades(), before)

    def test_missing_scope_signature_and_changed_cap_fail_before_any_fill(self):
        self.zero_target_scope_fixture()
        record = self.renew(single_sell_spread_bps=60)
        engine = self.cohort.engines['HGB_DIAG_5']
        permission = deepcopy(record['books']['HGB_DIAG_5'])
        before = deepcopy(engine.paper_trades())
        self.quotes.errors.clear()
        changed = deepcopy(permission)
        changed['single_sell_override']['max_qty'] += 1
        engine._set('paper_same_day_catchup_renewal', changed)
        with self.assertRaisesRegex(ValueError, 'OVERRIDE_BINDING_INVALID'):
            self.direct_scope_execution()
        self.assertEqual(engine.paper_trades(), before)
        engine._set('paper_same_day_catchup_renewal', permission)
        engine.db.execute("DELETE FROM audit WHERE event='PAPER_SINGLE_SELL_SPREAD_AUTHORIZED'")
        engine.db.commit()
        with self.assertRaisesRegex(ValueError, 'OVERRIDE_BINDING_INVALID'):
            self.direct_scope_execution()
        self.assertEqual(engine.paper_trades(), before)

    def test_signed_exception_keeps_sixty_bp_thirty_seconds_and_tradability_guards(self):
        self.zero_target_scope_fixture()
        self.renew(single_sell_spread_bps=60)
        engine = self.cohort.engines['HGB_DIAG_5']
        self.quotes.errors.clear()
        before = deepcopy(engine.paper_trades())
        ledger = deepcopy(engine._get('paper', {}))
        for changes in (dict(bid=1.69, ask=1.705), dict(asof=(self.now - timedelta(seconds=31)).isoformat()), dict(tradable=False), dict(currency='HKD'), dict(lot_size=100)):
            with self.subTest(changes=changes):
                result = self.direct_scope_execution(**changes)
                self.assertEqual(result['new_fill_count'], 0)
                self.assertEqual(engine.paper_trades(), before)
                self.assertEqual(engine._get('paper', {}), ledger)

    def test_locked_quote_with_bid_deviating_over_two_percent_has_zero_fills(self):
        self.zero_target_scope_fixture()
        self.renew(single_sell_spread_bps=60)
        engine = self.cohort.engines['HGB_DIAG_5']
        self.quotes.errors.clear()
        before = deepcopy(engine.paper_trades())
        ledger = deepcopy(engine._get('paper', {}))
        result = self.direct_scope_execution(price=1.6, bid=1.7, ask=1.7)
        self.assertEqual(result['new_fill_count'], 0)
        self.assertIn('超过2%', result['reason'])
        self.assertEqual(engine.paper_trades(), before)
        self.assertEqual(engine._get('paper', {}), ledger)

    def test_exception_deadline_and_commit_clock_are_exclusive_and_atomic(self):
        self.zero_target_scope_fixture()
        self.renew(single_sell_spread_bps=60)
        engine = self.cohort.engines['HGB_DIAG_5']
        self.quotes.errors.clear()
        before = deepcopy(engine.paper_trades())
        ledger = deepcopy(engine._get('paper', {}))
        batch = engine.db.execute('SELECT payload FROM paper_batches').fetchone()[0]
        with patch('moomoo_component.core.time.monotonic', side_effect=[100.0, 700.0]):
            with self.assertRaisesRegex(ValueError, 'EXPIRED_OR_CHANGED_BEFORE_COMMIT'):
                self.direct_scope_execution()
        self.assertEqual(engine._get('paper', {}), ledger)
        self.assertEqual(engine.paper_trades(), before)
        self.assertEqual(engine.db.execute('SELECT payload FROM paper_batches').fetchone()[0], batch)


class ExecutionChartLifecycleTests(unittest.TestCase):
    setUp = ExecutionChartsHookTests.setUp
    call = ExecutionChartsHookTests.call
    def test_stop_halt_and_close_cancel_the_registered_job(self):
        for control in ('stop','halt','close'):
            with self.subTest(control=control):
                if self.cohort.closed: break
                self.cohort.stop_event.clear(); self.cohort.halt_event.clear()
                for engine in self.cohort._active_engines().values():engine.halt_event.clear()
                self.cohort._execution_charts_job=None; self.job.reset_mock(); self.job.poll.return_value=None
                self.call(); getattr(self.cohort,control)()
                self.job.cancel.assert_called_once_with()
                self.assertIsNone(self.cohort._execution_charts_job)
                self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'CANCELLED')

    def test_cleanup_pending_retains_owned_handle_and_never_starts_duplicate(self):
        self.call(); self.job.cancel.side_effect=RuntimeError('EXECUTION_CHART_CLEANUP_PENDING')
        try:
            with self.assertRaisesRegex(RuntimeError,'CLEANUP_PENDING'): self.cohort.stop()
            self.assertIs(self.cohort._execution_charts_job,self.job)
            self.cohort.stop_event.clear()
            self.call(); self.source.start_execution_charts.assert_called_once_with()
        finally:
            self.job.cancel.side_effect=None

    def test_stop_between_receipt_read_and_start_never_registers_new_job(self):
        self.source.execution_charts_status.side_effect=lambda day:(self.cohort.stop() or {'status':'UNAVAILABLE'})
        self.call(); self.source.start_execution_charts.assert_not_called()

    def test_worker_failure_cancels_owned_job_before_leaving_run(self):
        self.call()
        with patch.object(self.cohort,'tick',side_effect=RuntimeError('synthetic parent failure')):
            with self.assertRaisesRegex(RuntimeError,'parent failure'): self.cohort._run()
        self.job.cancel.assert_called_once_with(); self.assertIsNone(self.cohort._execution_charts_job)

    def test_close_blocks_start_during_the_stop_join_close_gap(self):
        calls=[]
        def hook(method, **kwargs):
            if method=='close':
                with self.assertRaises(ValueError): self.cohort.start()
                calls.append(method)
        with patch.object(self.cohort,'_hook',side_effect=hook), patch('moomoo_component.cohort.threading.Thread',NoWorker):
            self.cohort.close()
        self.assertEqual(calls,['close']); self.assertTrue(self.cohort.closed)


class ExecutionChartStartStopRaceTests(unittest.TestCase):
    setUp = ExecutionChartsHookTests.setUp
    call = ExecutionChartsHookTests.call
    def test_stop_during_starter_registration_cannot_miss_owned_child(self):
        import threading
        entered, release=threading.Event(), threading.Event(); errors=[]
        def starter():
            entered.set()
            if not release.wait(2): raise AssertionError('synthetic start release timeout')
            return self.job
        def invoke(action):
            try: action()
            except BaseException as exc: errors.append(exc)
        self.source.start_execution_charts.side_effect=starter
        tick=threading.Thread(target=lambda:invoke(self.call))
        stop=threading.Thread(target=lambda:invoke(self.cohort.stop))
        tick.start()
        try:
            self.assertTrue(entered.wait(2)); stop.start()
            self.assertTrue(self.cohort.stop_event.wait(2))
        finally:
            release.set(); tick.join(2)
            if stop.ident is not None: stop.join(2)
        self.assertFalse(tick.is_alive()); self.assertFalse(stop.is_alive()); self.assertEqual(errors,[])
        self.job.cancel.assert_called_once_with()
        self.assertIsNone(self.cohort._execution_charts_job)
        self.assertEqual(self.cohort.meta['execution_charts_update']['status'],'CANCELLED')


class ExecutionChartFinancialStopPriorityTests(unittest.TestCase):
    setUp = ExecutionChartsHookTests.setUp
    call = ExecutionChartsHookTests.call

    def broker(self):
        import threading
        class Broker:
            def __init__(self):
                from types import SimpleNamespace
                self.calls=[]; self.stopped=threading.Event(); self.lock=threading.RLock()
                self.engine=SimpleNamespace(halt_event=threading.Event(),_pending=lambda:[])
                self.plan=None;self.metadata={};self.execution_window_seconds=60
            def _scheduled_open(self,value):return timestamp(value)
            def stop(self): self.calls.append('stop'); self.stopped.set()
            def halt(self): self.calls.append('halt'); self.stopped.set()
            def close(self): pass
            def state(self): return {'calls':list(self.calls)}
        broker=Broker(); self.cohort.best_broker=broker
        return broker

    def durable_meta(self):
        return json.loads(self.cohort.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])

    def test_chart_cleanup_failure_cannot_skip_original_broker_stop_or_durable_halt(self):
        for control in ('stop','halt'):
            with self.subTest(control=control):
                self.cohort.stop_event.clear(); self.cohort.halt_event.clear()
                broker=self.broker(); self.call()
                self.job.cancel.side_effect=RuntimeError('EXECUTION_CHART_CLEANUP_PENDING')
                try:
                    with self.assertRaisesRegex(RuntimeError,'CLEANUP_PENDING'): getattr(self.cohort,control)()
                    self.assertTrue(broker.stopped.is_set()); self.assertEqual(broker.calls,[control])
                    self.assertIs(self.cohort._execution_charts_job,self.job)
                    durable=self.durable_meta()
                    self.assertFalse(durable['running']); self.assertEqual(durable['status'],'STOPPED' if control=='stop' else 'HALTED')
                    if control=='halt': self.assertTrue(durable['halted'])
                finally:
                    self.job.cancel.side_effect=None; self.cohort._cancel_execution_charts()

    def test_blocked_chart_cleanup_observes_financial_stop_already_persisted(self):
        import threading
        for control in ('stop','halt'):
            with self.subTest(control=control):
                self.cohort.stop_event.clear(); self.cohort.halt_event.clear()
                broker=self.broker(); self.call()
                cleaning,release=threading.Event(),threading.Event(); errors=[]
                def cancel():
                    cleaning.set()
                    if not release.wait(2): raise AssertionError('synthetic cleanup release timeout')
                def stopping():
                    try: getattr(self.cohort,control)()
                    except BaseException as exc: errors.append(exc)
                self.job.cancel.side_effect=cancel
                thread=threading.Thread(target=stopping); thread.start()
                try:
                    self.assertTrue(cleaning.wait(2)); self.assertTrue(broker.stopped.is_set())
                    self.assertEqual(broker.calls,[control]); self.assertIs(self.cohort._execution_charts_job,self.job)
                    durable=self.durable_meta()
                    self.assertFalse(durable['running']); self.assertEqual(durable['status'],'STOPPED' if control=='stop' else 'HALTED')
                finally:
                    release.set(); thread.join(2); self.job.cancel.side_effect=None
                self.assertFalse(thread.is_alive()); self.assertEqual(errors,[])
                self.assertEqual(self.durable_meta()['execution_charts_update']['status'],'CANCELLED')


class DelayedCompletedSignalRefreshGuardTests(unittest.TestCase):
    """Only complete same-date MISSED_OPEN before configured execution is reused."""
    setUp = CohortTests.setUp
    make = RefreshWindowBoundaryTests.make
    start = CohortTests.start

    def test_complete_same_date_signal_is_reused_at_actual_open_and_before_scheduled_open(self):
        for offset in (0, 20*60, 45*60-0.000001):
            with self.subTest(offset=offset):
                self.make(delay=45,window=60,missing=False)
                clock=OPEN+timedelta(seconds=offset)
                data={**self.source.status(now=clock),'status':'MISSED_OPEN'}
                before=deepcopy(data)
                result=self.cohort._refresh_if_due(data,clock)
                self.assertIs(result,data); self.assertEqual(data,before)
                self.assertEqual(self.source.refresh_count,0); self.assertEqual(self.quotes.calls,[])
                self.assertNotIn('last_refresh_attempt',self.cohort.meta)
                self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(45,60))

    def test_missing_stale_or_preopen_missed_signal_keeps_original_refresh(self):
        cases=('gaps','stale_date','missing_date','empty_date','before_actual_open','waiting_source')
        for case in cases:
            with self.subTest(case=case):
                self.make(delay=45,window=60,missing=False)
                clock=OPEN+timedelta(minutes=20)
                data={**self.source.status(now=clock),'status':'MISSED_OPEN'}
                if case=='gaps':data['data_gaps']=['synthetic missing']
                elif case=='stale_date':data['source_date']='2026-09-25'
                elif case=='missing_date':data.pop('source_date')
                elif case=='empty_date':data['source_date']=''
                elif case=='before_actual_open':clock=OPEN-timedelta(microseconds=1)
                elif case=='waiting_source':data['status']='WAITING_SOURCE'
                self.cohort._refresh_if_due(data,clock)
                self.assertEqual(self.source.refresh_count,1); self.assertEqual(self.quotes.calls,[])

    def test_scheduled_open_boundary_and_zero_delay_keep_original_refresh_window(self):
        for delay,offset in ((45,45*60),(0,0),(0,59)):
            with self.subTest(delay=delay,offset=offset):
                self.make(delay=delay,window=60,missing=False)
                clock=OPEN+timedelta(seconds=offset)
                data={**self.source.status(now=clock),'status':'MISSED_OPEN'}
                self.cohort._refresh_if_due(data,clock)
                self.assertEqual(self.source.refresh_count,1); self.assertEqual(self.quotes.calls,[])

    def test_same_date_flag_never_skips_original_source_load_identity_validation(self):
        self.make(delay=45,window=60,missing=False)
        clock=OPEN+timedelta(minutes=20); self.quotes.clock=clock
        with patch.object(self.source,'load',side_effect=ValueError('synthetic SOURCE_BINDING_CHANGED')) as load:
            result=self.cohort.tick(now=clock)
        load.assert_called_once()
        self.assertEqual(self.source.refresh_count,0); self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('SOURCE_BINDING_CHANGED',result['last_error'])
        self.assertEqual(result['trades'],[]); self.assertEqual(self.quotes.calls,[])


class HgbRevisionClockBindingTests(unittest.TestCase):
    setUp=HgbEpochResetTests.setUp
    start=HgbEpochResetTests.start;tick=HgbEpochResetTests.tick
    seed=HgbEpochResetTests.seed;reset=HgbEpochResetTests.reset;reopen=HgbEpochResetTests.reopen
    revision_fixture=HgbEpochResetTests.revision_fixture;revise=HgbEpochResetTests.revise
    zulu_revision_fixture=HgbEpochResetTests.zulu_revision_fixture;revision_books=HgbEpochResetTests.revision_books

    def test_original_hash_and_legacy_lexeme_compatibility_keep_authorization_exact(self):
        self.zulu_revision_fixture()
        metadata=deepcopy(self.cohort.plan_metadata);active=deepcopy(self.cohort.meta)
        books=self.revision_books()
        for route in ("original_hash","legacy_compatibility"):
            with self.subTest(route=route):
                self.cohort.plan_metadata=deepcopy(metadata);self.cohort.meta=deepcopy(active)
                if route=="legacy_compatibility":
                    self.cohort.plan_metadata["execution_time_utc"]=metadata["execution_time_utc"].replace("Z","+00:00")
                before=deepcopy(self.cohort.plan_metadata)
                self.assertEqual(self.cohort._initial_hgb_target_plans(self.cohort.meta["paper_reset"]),active["paper_target_revision"]["plans"])
                self.assertEqual(self.cohort.plan_metadata,before)
                self.assertEqual(self.cohort.meta,active)
                self.assertEqual(self.revision_books(),books)
                self.assertEqual(self.quotes.calls,[])

    def test_each_template_clock_field_is_bound_before_both_hash_paths(self):
        self.zulu_revision_fixture()
        metadata=deepcopy(self.cohort.plan_metadata);active=deepcopy(self.cohort.meta)
        books=self.revision_books()
        changes=(("signal_date","2026-09-28"),("execution_date","2026-10-01"),
                 ("next_open_utc",(OPEN+timedelta(days=1,minutes=1)).isoformat()),
                 ("signal_close_utc",(CLOSE+timedelta(days=1,minutes=-1)).isoformat()),
                 ("next_open_utc",metadata["next_open_utc"].replace("Z","+00:00")))
        for route in ("original_hash","legacy_compatibility"):
            for field,value in changes:
                with self.subTest(route=route,field=field,value=value):
                    self.cohort.plan_metadata=deepcopy(metadata);self.cohort.meta=deepcopy(active)
                    if route=="legacy_compatibility":
                        self.cohort.plan_metadata["execution_time_utc"]=metadata["execution_time_utc"].replace("Z","+00:00")
                    self.cohort.meta["paper_target_revision"]["source_template"]["loaded"][field]=value
                    before=(deepcopy(self.cohort.plan_metadata),deepcopy(self.cohort.meta))
                    with self.assertRaisesRegex(ValueError,"HGB_TARGET_REVISION_AUTHORIZATION_CHANGED"):
                        self.cohort._initial_hgb_target_plans(self.cohort.meta["paper_reset"])
                    self.assertEqual((self.cohort.plan_metadata,self.cohort.meta),before)
                    self.assertEqual(self.revision_books(),books)
                    self.assertEqual(self.quotes.calls,[])

    def test_valid_hash_never_bypasses_invalid_or_changed_execution_instant(self):
        from moomoo_component.cohort import _fingerprint
        self.zulu_revision_fixture()
        metadata=deepcopy(self.cohort.plan_metadata);active=deepcopy(self.cohort.meta)
        books=self.revision_books()
        for value in (None,"not-a-clock",(OPEN+timedelta(days=1)).replace(tzinfo=None).isoformat(),
                      (OPEN+timedelta(days=1,minutes=1)).isoformat()):
            with self.subTest(value=value):
                self.cohort.plan_metadata=deepcopy(metadata);self.cohort.meta=deepcopy(active)
                self.cohort.plan_metadata["execution_time_utc"]=value
                # A self-consistent hash alone cannot authorize a different/invalid instant.
                self.cohort.meta["paper_target_revision"]["metadata_sha256"]=_fingerprint(self.cohort.plan_metadata)
                before=(deepcopy(self.cohort.plan_metadata),deepcopy(self.cohort.meta))
                with self.assertRaises(ValueError):
                    self.cohort._initial_hgb_target_plans(self.cohort.meta["paper_reset"])
                self.assertEqual((self.cohort.plan_metadata,self.cohort.meta),before)
                self.assertEqual(self.revision_books(),books)
                self.assertEqual(self.quotes.calls,[])

class DeferredClockPlanAcceptanceTests(unittest.TestCase):
    """Pending migration commits only with accepted plans; all inputs are synthetic."""
    setUp = CohortTests.setUp
    start = CohortTests.start
    tick = CohortTests.tick

    def deferred_fixture(self, membership, label):
        self.cohort.close()
        from test_five_strategy_execution import FiveSource
        self.source, self.quotes = (FiveSource() if membership else Source()), Quotes()
        self.source.daily_root = Path(self.temp.name) / "synthetic_daily"
        root = Path(self.temp.name) / ("acceptance_" + label + str(membership))
        self.cohort = Cohort(root, self.source, self.quotes,
            execution_delay_minutes=30, execution_window_seconds=600, allow_partial_quotes=True)
        if membership:
            from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
            now = CLOSE + timedelta(minutes=10)
            self.cohort.migrate_strategy_membership(
                migration_id="synthetic-clock-acceptance-" + label,
                requested_at=now.isoformat(),
                expected_precondition_sha256=self.cohort.state()["membership_precondition_sha256"],
                target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS), now=now)
        self.start()
        completed = self.tick(OPEN + timedelta(minutes=30, seconds=1))
        self.assertEqual(completed["status"], "EXECUTED", completed)
        self.cohort.stop()
        self.cohort.close()
        with patch("moomoo_component.cohort._now", return_value=OPEN + timedelta(hours=1)):
            self.cohort = Cohort(root, self.source, self.quotes,
                execution_delay_minutes=25, execution_window_seconds=1500, allow_partial_quotes=True)
        self.assertEqual((self.cohort.execution_delay_minutes, self.cohort.execution_window_seconds), (30,600))
        data = {**self.source.status(now=OPEN), "status":"READY",
            "signal_date":"2026-09-29", "source_date":"2026-09-29", "execution_date":"2026-09-30",
            "signal_close_utc":"2026-09-29T20:00:00+00:00",
            "next_open_utc":"2026-09-30T13:30:00+00:00", "next_close_utc":"2026-09-30T20:00:00+00:00"}
        self.source.status = lambda now=None: deepcopy(data)
        base_close = self.source.close_states
        def successor_close(books, signal_date):
            values = base_close(books=books, signal_date=signal_date)
            for value in values.values():
                value["close_asof_utc"] = data["signal_close_utc"]
            return values
        self.source.close_states = successor_close
        return data, datetime(2026,9,29,20,1,1,tzinfo=timezone.utc)

    def acceptance_snapshot(self):
        saved = json.loads(self.cohort.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
        fields = ("execution_delay_minutes","execution_window_seconds","next_ordinary_execution_clock",
            "plan_signal_date","plan_execution_date","execution_time_utc","next_expected_execution_utc")
        return dict(clock=(self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),
            meta={k:deepcopy(self.cohort.meta.get(k)) for k in fields},
            saved={k:deepcopy(saved.get(k)) for k in fields},
            plans=deepcopy(self.cohort.plans), metadata=deepcopy(self.cohort.plan_metadata),
            book_metadata=deepcopy(self.cohort.meta.get("book_plan_metadata")),
            loaded_key=self.cohort.loaded_key,
            events=[tuple(r) for r in self.cohort.db.execute("SELECT * FROM events ORDER BY rowid")],
            batches={sid:[tuple(r) for r in e.db.execute("SELECT * FROM paper_batches ORDER BY rowid")]
                for sid,e in self.cohort.engines.items()},
            fills={sid:deepcopy(e.paper_trades()) for sid,e in self.cohort.engines.items()})

    def prepare_successor(self, membership, data, now):
        if membership:
            return self.cohort._prepare_active_members(data, now, explicit_update=True)
        return self.cohort._prepare(data, now, explicit_update=True)

    def assert_successor_commit(self, membership, data, now, before):
        original_persist = self.cohort._persist
        observed = []
        def persist(*, event=None):
            if event and event[0] == "ORDINARY_EXECUTION_CLOCK_APPLIED":
                self.assertEqual(self.cohort.meta["plan_signal_date"], data["signal_date"])
                self.assertIsNone(self.cohort.meta["next_ordinary_execution_clock"])
                self.assertTrue(set(self.cohort._active_ids()).issubset(self.cohort.plans))
                for sid in self.cohort._active_ids():
                    metadata = self.cohort.meta.get("book_plan_metadata", {}).get(sid, self.cohort.plan_metadata)
                    self.assertEqual(metadata["signal_date"], data["signal_date"])
                    self.assertEqual(metadata["execution_time_utc"], "2026-09-30T13:55:00+00:00")
                    self.assertEqual((metadata["execution_delay_minutes"],metadata["execution_window_seconds"]), (25,1500))
                observed.append(event)
            return original_persist(event=event)
        with patch.object(self.cohort, "_persist", side_effect=persist):
            self.assertFalse(self.prepare_successor(membership,data,now))
        after = self.acceptance_snapshot()
        self.assertEqual(after["clock"], (25,1500))
        self.assertIsNone(after["meta"]["next_ordinary_execution_clock"])
        self.assertIsNone(after["saved"]["next_ordinary_execution_clock"])
        self.assertEqual(after["saved"]["plan_signal_date"], data["signal_date"])
        self.assertEqual(after["batches"], before["batches"])
        self.assertEqual(after["fills"], before["fills"])
        self.assertEqual(after["events"][:len(before["events"])], before["events"])
        self.assertEqual(len(observed),1)
        applied = [r for r in after["events"] if r[1] == "ORDINARY_EXECUTION_CLOCK_APPLIED"]
        self.assertEqual(len(applied),1)
        durable = json.loads(self.cohort.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
        self.assertEqual(durable["plan_metadata"], self.cohort.plan_metadata)
        self.assertEqual(durable["plans"], self.cohort.plans)

    def failure_then_retry(self, kind):
        for membership in (False,True):
            with self.subTest(membership=membership, failure=kind):
                data, now = self.deferred_fixture(membership, kind)
                before = self.acceptance_snapshot()
                if kind == "persist":
                    self.cohort.db.execute("""CREATE TEMP TRIGGER reject_clock_apply BEFORE INSERT ON events
                        WHEN NEW.event='ORDINARY_EXECUTION_CLOCK_APPLIED'
                        BEGIN SELECT RAISE(ABORT,'synthetic clock commit failure'); END""")
                    context = patch.object(self.source,"status",side_effect=self.source.status)
                elif kind == "plans":
                    base_load = self.source.load
                    def missing_plans(*args,**kwargs):
                        value = base_load(*args,**kwargs)
                        value.pop("plans",None)
                        return value
                    context = patch.object(self.source,"load",side_effect=missing_plans)
                else:
                    context = patch.object(self.source,kind,side_effect=ValueError("synthetic "+kind+" failure"))
                with context:
                    if membership:
                        self.assertTrue(self.prepare_successor(membership,data,now))
                    else:
                        with self.assertRaises((ValueError,sqlite3.IntegrityError)):
                            self.prepare_successor(membership,data,now)
                self.assertEqual(self.acceptance_snapshot(),before)
                if kind == "persist":
                    self.cohort.db.execute("DROP TRIGGER reject_clock_apply")
                self.assert_successor_commit(membership,data,now,before)

    def test_close_states_failure_preserves_pending_and_old_plans_then_retry_commits(self):
        self.failure_then_retry("close_states")

    def test_source_load_failure_preserves_pending_and_old_plans_then_retry_commits(self):
        self.failure_then_retry("load")

    def test_missing_plans_preserve_pending_and_old_plans_then_retry_commits(self):
        self.failure_then_retry("plans")

    def test_clock_event_insert_failure_rolls_back_plans_clock_pending_and_audit(self):
        self.failure_then_retry("persist")

    def test_partial_membership_success_does_not_consume_global_pending_clock(self):
        data, now = self.deferred_fixture(True, "partial")
        before = self.acceptance_snapshot()
        blocked = "R10_DIRECT_H5_RIDGE_MID"
        self.source.blocked.add(blocked)
        errors = self.prepare_successor(True,data,now)
        self.assertEqual(errors[blocked], "synthetic missing identity")
        self.assertEqual(self.cohort.book_status[blocked]["reason"], "synthetic missing identity")
        for sid in set(self.cohort._active_ids()) - {blocked}:
            self.assertEqual(errors[sid], "DEFERRED_ORDINARY_CLOCK_REQUIRES_ALL_ACCEPTED_PLANS")
            self.assertEqual(self.cohort.book_status[sid]["status"], "BLOCKED")
        self.assertEqual(self.acceptance_snapshot(),before)
        self.source.blocked.clear()
        self.assert_successor_commit(True,data,now,before)

    def test_successor_tick_accepts_plans_before_new_clock_execution_on_both_routes(self):
        for membership in (False,True):
            with self.subTest(membership=membership):
                data, _ = self.deferred_fixture(membership,"tick")
                before = self.acceptance_snapshot()
                self.start()
                state = self.tick(datetime(2026,9,30,13,55,1,tzinfo=timezone.utc))
                self.assertEqual(state["status"],"EXECUTED",state)
                self.assertEqual((self.cohort.execution_delay_minutes,self.cohort.execution_window_seconds),(25,1500))
                self.assertIsNone(self.cohort.meta["next_ordinary_execution_clock"])
                applied = [r for r in self.cohort.db.execute("SELECT * FROM events")
                    if r[1] == "ORDINARY_EXECUTION_CLOCK_APPLIED"]
                self.assertEqual(len(applied),1)
                for sid in self.cohort._active_ids():
                    frozen = self.cohort.meta.get("book_plan_metadata",{}).get(sid,self.cohort.plan_metadata)
                    self.assertEqual(frozen["signal_date"],data["signal_date"])
                    self.assertEqual(frozen["execution_time_utc"],"2026-09-30T13:55:00+00:00")
                    self.assertEqual(self.cohort.book_status[sid]["execution_date"],data["execution_date"])
                self.assertEqual(self.acceptance_snapshot()["events"][:len(before["events"])],before["events"])


class ManualCachedValuationTickTests(unittest.TestCase):
    """Manual daily mode keeps cached marks between explicit or execution-owner updates."""
    setUp = CohortTests.setUp
    start = CohortTests.start
    tick = CohortTests.tick
    _valuation_trade_snapshot = CohortTests._valuation_trade_snapshot

    def cached_fixture(self, membership, *, manual=True, execute=True):
        self.cohort.close()
        from test_five_strategy_execution import FiveSource
        self.source, self.quotes = (FiveSource() if membership else Source()), Quotes()
        root = Path(self.temp.name) / ("cached_valuation_" + str(membership) + str(manual))
        self.source.daily_root = root / "synthetic_daily"
        self.cohort = Cohort(root, self.source, self.quotes, execution_delay_minutes=25,
            execution_window_seconds=1500, allow_partial_quotes=True, manual_data_updates=manual)
        if membership:
            from moomoo_component.strategy import ACTIVE_PAPER_STRATEGY_IDS
            now = CLOSE + timedelta(minutes=10)
            self.cohort.migrate_strategy_membership(migration_id="synthetic-cached-valuation",
                requested_at=now.isoformat(),
                expected_precondition_sha256=self.cohort.state()["membership_precondition_sha256"],
                target_strategy_ids=list(ACTIVE_PAPER_STRATEGY_IDS), now=now)
        clock = OPEN - timedelta(minutes=1)
        data = self.source.status(now=clock)
        if membership:
            self.assertEqual(self.cohort._prepare_active_members(data,clock,explicit_update=True),{})
        else:
            self.cohort._prepare(data,clock,explicit_update=True)
        self.start()
        if execute:
            self.assertEqual(self.tick(OPEN+timedelta(minutes=25,seconds=10))["status"],"EXECUTED")
        return OPEN + timedelta(minutes=50,seconds=1)

    def test_manual_mode_window_external_ticks_keep_cached_marks_and_never_pull_quotes(self):
        for membership in (False,True):
            with self.subTest(membership=membership):
                outside = self.cached_fixture(membership)
                before = self._valuation_trade_snapshot()
                marks = {sid:deepcopy(e._get("paper_marks",{})) for sid,e in self.cohort.engines.items()}
                nav = {sid:deepcopy(e.paper_nav_history()) for sid,e in self.cohort.engines.items()}
                with patch.object(self.cohort,"_mark_current_books",side_effect=AssertionError("no automatic mark")), \
                     patch.object(self.quotes,"quotes_partial",side_effect=AssertionError("no external quote pull")), \
                     patch.object(self.source,"load",side_effect=AssertionError("no repeated inference")):
                    for offset in (0,30,90):
                        result = self.tick(outside+timedelta(seconds=offset))
                        self.assertEqual(result["status"],"EXECUTED",result)
                self.assertEqual(self._valuation_trade_snapshot(),before)
                self.assertEqual({sid:e._get("paper_marks",{}) for sid,e in self.cohort.engines.items()},marks)
                self.assertEqual({sid:e.paper_nav_history() for sid,e in self.cohort.engines.items()},nav)

    def test_nonmanual_mode_retains_original_window_external_valuation_owner(self):
        for membership in (False,True):
            with self.subTest(membership=membership):
                outside = self.cached_fixture(membership,manual=False)
                with patch.object(self.cohort,"_mark_current_books",wraps=self.cohort._mark_current_books) as marks:
                    result = self.tick(outside)
                    options = dict(now=outside,record_cash=True,respect_stop=True)
                    if membership:
                        options["active_only"] = True
                    marks.assert_called_once_with(**options)
                self.assertEqual(result["status"],"EXECUTED",result)

    def test_manual_mode_explicit_mark_still_uses_original_quote_owner_without_orders(self):
        for membership in (False,True):
            with self.subTest(membership=membership):
                outside = self.cached_fixture(membership)
                self.cohort.stop()
                before = self._valuation_trade_snapshot()
                self.quotes.clock = outside
                self.quotes.overrides[CODES[0]] = {"price":110,"bid":110,"ask":110}
                with patch.object(self.source,"status",side_effect=AssertionError("no signal read")), \
                     patch.object(self.source,"load",side_effect=AssertionError("no inference")), \
                     patch.object(self.source,"refresh",side_effect=AssertionError("no provider")), \
                     patch.object(self.cohort,"_hook",side_effect=AssertionError("no broker hook")), \
                     patch.object(Engine,"paper_rebalance",side_effect=AssertionError("no rebalance")), \
                     patch.object(self.quotes,"quotes_partial",wraps=self.quotes.quotes_partial) as quotes:
                    report = self.cohort.mark_current_books(now=outside)
                self.assertTrue(report["valuation_only"])
                self.assertTrue(report["books"])
                quotes.assert_called_once()
                self.assertEqual(quotes.call_args.kwargs,{"refresh":True})
                self.assertEqual(self._valuation_trade_snapshot(),before)
                self.assertEqual(self.cohort.engines["RAW_A2"]._get("paper_marks",{})[CODES[0]]["price"],110)

    def test_manual_mode_inside_window_execution_keeps_fresh_quotes_mark_and_idempotence(self):
        for membership in (False,True):
            with self.subTest(membership=membership):
                self.cached_fixture(membership,execute=False)
                with patch.object(self.cohort,"_mark_current_books",side_effect=AssertionError("no extra valuation")), \
                     patch.object(self.quotes,"quotes_partial",wraps=self.quotes.quotes_partial) as quotes, \
                     patch.object(self.cohort,"_mark",wraps=self.cohort._mark) as marks:
                    result = self.tick(OPEN+timedelta(minutes=25,seconds=10))
                self.assertEqual(result["status"],"EXECUTED",result)
                self.assertEqual(quotes.call_count,len(self.cohort._active_ids()))
                self.assertEqual(marks.call_count,len(self.cohort._active_ids()))
                self.assertTrue(all("refresh" not in call.kwargs for call in quotes.call_args_list))
                self.assertTrue(self.cohort.trades())
                before = self._valuation_trade_snapshot()
                with patch.object(self.quotes,"quotes_partial",side_effect=AssertionError("no duplicate execution quotes")):
                    self.assertEqual(self.tick(OPEN+timedelta(minutes=26))["status"],"EXECUTED")
                self.assertEqual(self._valuation_trade_snapshot(),before)

    def test_manual_mode_all_missed_aggregates_missed_without_empty_blocked_error(self):
        for membership in (False,True):
            with self.subTest(membership=membership):
                outside = self.cached_fixture(membership,execute=False)
                with patch.object(self.quotes,"quotes_partial",side_effect=AssertionError("no expired quote read")):
                    result = self.tick(outside)
                self.assertEqual(result["status"],"MISSED_OPEN",result)
                self.assertFalse(result.get("last_error"))
                self.assertTrue(all(self.cohort.book_status[sid]["status"]=="MISSED_OPEN"
                    for sid in self.cohort._active_ids()))
                self.assertEqual(result["trades"],[])

    def test_real_membership_window_error_is_not_hidden_by_other_missed_books(self):
        outside = self.cached_fixture(True,execute=False)
        original = self.cohort._book_execution_window
        def window(sid,data,clock):
            if sid == "RAW_A2":
                raise ValueError("synthetic policy identity changed")
            return original(sid,data,clock)
        with patch.object(self.cohort,"_book_execution_window",side_effect=window), \
             patch.object(self.quotes,"quotes_partial",side_effect=AssertionError("no expired quote read")):
            result = self.tick(outside)
        self.assertEqual(result["status"],"BLOCKED",result)
        self.assertIn("RAW_A2: synthetic policy identity changed",result["last_error"])
        self.assertEqual(result["trades"],[])
