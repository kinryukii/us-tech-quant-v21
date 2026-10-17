from datetime import datetime, timedelta, timezone
from copy import deepcopy
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from moomoo_component.best_broker import BestBroker, SID
from moomoo_component.core import Engine
from moomoo_component.brokers import BrokerError, BrokerReadError, BrokerOrderNotSent


class FakeBroker:
    positions = {}
    submissions = []
    cash = 1000000.0
    clock = staticmethod(lambda: datetime.now(timezone.utc))
    prewarm_calls = []
    prewarm_error = None
    snapshot_calls = []
    quote_errors = {}
    submit_options = []
    before_send_error = None
    reconcile_result = None
    reconcile_calls = []
    market_prices = {}

    def __init__(self, **kwargs):
        self.account_id = kwargs.get('account_id')
        self.cancel_check = lambda: False

    def probe(self):
        return {'connected': True, 'accounts': [{'account_id': '3604', 'market': 'US', 'environment': 'SIMULATE'}]}

    def snapshot(self, codes, *, include_quotes=True):
        self.snapshot_calls.append((tuple(codes), include_quotes))
        stamp = self.clock().isoformat()
        positions = {c: {'qty': qty, 'sellable': qty, 'market_value': qty * self.market_prices.get(c, 100.0)} for c, qty in self.positions.items()}
        return {'cash': self.cash, 'equity': self.cash + sum(p['market_value'] for p in positions.values()), 'positions': positions, 'open_orders': [],
                'funds_only': not include_quotes,
                'quotes': {c: {'price': 100.0, 'bid': 99.99, 'ask': 100.01, 'asof': stamp,
                               'lot_size': 1, 'price_tick': .01, 'tradable': True} for c in (set(codes) | set(positions)) if include_quotes}}

    def prewarm(self, codes):
        self.prewarm_calls.append(list(codes))
        if self.prewarm_error:
            raise self.prewarm_error

    def snapshot_partial(self, codes):
        result = self.snapshot(codes)
        result['quote_errors'] = {code: self.quote_errors[code] for code in result['quotes'] if code in self.quote_errors}
        result['quotes'] = {code: row for code, row in result['quotes'].items() if code not in result['quote_errors']}
        return result

    def close(self):
        pass

    def submit(self, order, client_id, *, allow_partial_quotes=False, execution_deadline_utc=None,
               order_type='NORMAL'):
        if self.cancel_check():
            raise ValueError('stopped before fake submission')
        self.submit_options.append({'client_id': client_id, 'allow_partial_quotes': allow_partial_quotes,
                                    'execution_deadline_utc': execution_deadline_utc,
                                    'order_type': order_type})
        if self.before_send_error:
            raise self.before_send_error
        self.submissions.append({**order, 'client_id': client_id, 'order_type': order_type})
        sign = 1 if order['side'] == 'BUY' else -1
        self.positions[order['code']] = self.positions.get(order['code'], 0) + sign * order['qty']
        FakeBroker.cash -= sign * order['qty'] * order['limit_price']
        return {'order_id': '123', 'status': 'SUBMITTED'}

    def reconcile(self, client_id, order_id):
        self.reconcile_calls.append((client_id, order_id))
        if self.reconcile_result is not None:
            return deepcopy(self.reconcile_result)
        order = next(o for o in self.submissions if o['client_id'] == client_id)
        return {'order_id': order_id, 'status': 'FILLED_ALL', 'dealt_qty': order['qty'], 'dealt_avg_price': order['limit_price']}


class FakeSource:
    def __init__(self, opening):
        self.opening = opening
        self.calls = []
        self.rows = [{'code': 'US.AAPL', 'target_weight': .1}]

    def status(self, now=None):
        self.calls.append('status')
        return {'status': 'READY', 'signal_date': '2026-09-25', 'execution_date': '2026-09-28',
                'next_open_utc': self.opening.isoformat(), 'signal_close_utc': '2026-09-25T20:00:00+00:00',
                'next_close_utc': (self.opening + timedelta(hours=6, minutes=30)).isoformat()}

    def close_states(self, books, signal_date):
        self.calls.append(('close_states', books))
        return {SID: {'weights': {}, 'cash_weight': 1.0, 'signal_date': signal_date, 'valuation_basis': 'SIGNAL_CLOSE'}}

    def load(self, states, now=None):
        return {**self.status(now), 'plans': {SID: {'rows': deepcopy(self.rows),
                  'target_cash_weight': 1 - sum(row['target_weight'] for row in self.rows), 'source_hash': 'verified-frozen-source'}}}


class BestBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.opening = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)
        self.source = FakeSource(self.opening)
        FakeBroker.positions = {}
        FakeBroker.submissions = []
        FakeBroker.cash = 1000000.0
        FakeBroker.clock = staticmethod(lambda: datetime.now(timezone.utc))
        FakeBroker.prewarm_calls, FakeBroker.snapshot_calls, FakeBroker.quote_errors = [], [], {}
        FakeBroker.prewarm_error = None
        FakeBroker.submit_options, FakeBroker.before_send_error = [], None
        FakeBroker.reconcile_result, FakeBroker.reconcile_calls, FakeBroker.market_prices = None, [], {}
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)

    def tearDown(self):
        self.runner.close()
        self.temp.cleanup()

    def connect(self):
        self.runner._connect()
        self.runner.stop_event.clear()

    def partial_runner(self, delay=45):
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=delay, execution_window_seconds=600, allow_partial_quotes=True)
        self.connect()

    def tick_at(self, now):
        FakeBroker.clock = staticmethod(lambda: now)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is None else now.astimezone(tz)
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock), \
             patch('moomoo_component.best_broker.datetime', Clock):
            self.runner.tick(now=now)

    @staticmethod
    def submit_without_fill(broker, order, client_id, **options):
        if broker.cancel_check():
            raise ValueError('stopped before fake submission')
        FakeBroker.submit_options.append({'client_id': client_id, **options})
        FakeBroker.submissions.append({**order, 'client_id': client_id,
                                       'order_type': options.get('order_type', 'NORMAL')})
        return {'order_id': 'pending-123', 'status': 'SUBMITTED'}

    def mark_pending_order_as_legacy_limit(self):
        """Represent a NORMAL broker order placed before the MARKET policy change."""
        row = self.engine.state()['orders'][0]
        self.assertEqual(row['status'], 'PENDING_RECONCILE')
        self.engine.db.execute("UPDATE orders SET order_type='NORMAL' WHERE id=?", (row['id'],))
        self.engine.db.commit()

    def paused_unknown_dna(self, *, average=11.24, actual_qty=88):
        self.source.rows = [{'code': 'US.DNA', 'target_weight': .1}]
        self.partial_runner(delay=150)
        self.runner._prepare(self.opening + timedelta(minutes=150, seconds=4))
        frozen = deepcopy(self.engine._get('best_plan', None))
        stamp = (self.opening + timedelta(minutes=150, seconds=9)).isoformat()
        self.engine.db.execute('INSERT INTO orders '
            '(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            ('original-dna-client', stamp, SID, 'moomoo_simulate', self.engine.account_id,
             'US.DNA', 'BUY', 88, 11.35, 'UNKNOWN', 'fixture-416313'))
        self.engine.db.commit()
        self.engine._halt('模拟委托结果未知；已暂停自动执行')
        self.runner.stop_event.set()
        self.runner.status = 'BLOCKED'
        self.runner.last_error = '模拟委托结果未知'
        self.engine._set('best_last_error', self.runner.last_error)
        FakeBroker.positions = {'US.DNA': actual_qty}
        FakeBroker.market_prices = {'US.DNA': 11.24}
        FakeBroker.cash = 1000000.0 - 88 * 11.24
        FakeBroker.reconcile_result = {'order_id': 'fixture-416313', 'status': 'FILLED_ALL',
                                       'dealt_qty': 88, 'dealt_avg_price': average}
        return frozen

    def test_paused_reconcile_records_actual_eighty_eight_shares_and_price_without_resume(self):
        frozen = self.paused_unknown_dna()
        with patch.object(self.source, 'status', side_effect=AssertionError('no source refresh')), \
             patch.object(self.source, 'load', side_effect=AssertionError('no replan')), \
             patch.object(self.engine, 'step', side_effect=AssertionError('no order step')), \
             patch.object(self.engine, 'reset_halt', side_effect=AssertionError('halt must stay')):
            result = self.runner.reconcile()
        self.assertEqual(result['status'], 'HALTED')
        self.assertFalse(result['running'])
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(result['orders'][0]['fill_qty'], 88)
        self.assertEqual(result['orders'][0]['fill_price'], 11.24)
        self.assertEqual(result['orders'][0]['limit_price'], 11.35)
        self.assertEqual(result['positions']['US.DNA']['qty'], 88)
        self.assertAlmostEqual(result['cash'], 10000 - 88 * 11.24)
        self.assertEqual(result['plan'], frozen['plan'])
        self.assertEqual(self.engine._get('best_plan', None), frozen)
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(FakeBroker.reconcile_calls, [('original-dna-client', 'fixture-416313')])
        self.assertTrue(all(not include for _, include in FakeBroker.snapshot_calls))
        self.assertEqual(result['last_error'], '')
        audit = self.engine.db.execute("SELECT detail FROM audit WHERE event='BEST_RECONCILE_SYNCED'").fetchone()
        self.assertIn('模拟委托结果未知', audit[0])

    def test_repeated_paused_reconcile_keeps_one_real_fill_without_more_order_queries(self):
        self.paused_unknown_dna()
        self.runner.reconcile()
        first = self.engine.db.execute('SELECT payload FROM order_fills WHERE id=?',
                                       ('original-dna-client',)).fetchone()[0]
        again = self.runner.reconcile()
        self.assertEqual(again['status'], 'HALTED')
        self.assertEqual(again['orders'][0]['fill_qty'], 88)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM order_fills').fetchone()[0], 1)
        self.assertEqual(self.engine.db.execute('SELECT payload FROM order_fills WHERE id=?',
                         ('original-dna-client',)).fetchone()[0], first)
        self.assertEqual(len(FakeBroker.reconcile_calls), 1)
        self.assertEqual(FakeBroker.submissions, [])

    def test_paused_reconcile_restores_only_saved_sim_identity_after_engine_reboot(self):
        frozen = self.paused_unknown_dna()
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.assertEqual(self.engine.mode, 'paper')
        self.assertIsNone(self.engine.broker)
        with patch.object(self.source, 'load', side_effect=AssertionError('no replan')), \
             patch.object(self.source, 'status', side_effect=AssertionError('no status refresh')), \
             patch.object(self.runner, '_connect', side_effect=AssertionError('must not start')):
            result = self.runner.reconcile()
        self.assertEqual(result['status'], 'HALTED')
        self.assertFalse(result['running'])
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(result['orders'][0]['fill_qty'], 88)
        self.assertEqual(result['orders'][0]['fill_price'], 11.24)
        self.assertEqual(result['positions']['US.DNA']['qty'], 88)
        self.assertEqual(self.engine._get('best_plan', None), frozen)
        self.assertEqual(result['plan'], frozen['plan'])
        self.assertEqual(FakeBroker.submissions, [])

    def test_paused_reconcile_rejects_wrong_saved_account_before_broker_reads(self):
        self.paused_unknown_dna()
        self.engine._set('best_account', 'different-account')
        calls = len(FakeBroker.snapshot_calls)
        with self.assertRaisesRegex(ValueError, '绑定'):
            self.runner.reconcile()
        self.assertEqual(len(FakeBroker.snapshot_calls), calls)
        self.assertEqual(FakeBroker.reconcile_calls, [])
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(self.runner.status, 'BLOCKED')

    def test_paused_reconcile_rejects_different_discovered_sim_account_on_restart(self):
        self.paused_unknown_dna()
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        discovered = {'connected': True, 'accounts': [{'account_id': 'wrong',
                      'market': 'US', 'environment': 'SIMULATE'}]}
        with patch.object(FakeBroker, 'probe', return_value=discovered), self.assertRaisesRegex(ValueError, '身份'):
            self.runner.reconcile()
        self.assertEqual(self.engine.mode, 'paper')
        self.assertIsNone(self.engine.broker)
        self.assertEqual(FakeBroker.reconcile_calls, [])
        self.assertTrue(self.engine.halt_event.is_set())

    def test_paused_reconcile_missing_actual_average_never_uses_order_limit(self):
        self.paused_unknown_dna(average=None)
        with self.assertRaisesRegex(ValueError, '均价未知'):
            self.runner.reconcile()
        row = self.engine.state()['orders'][0]
        self.assertEqual(row['fill_qty'], 88)
        self.assertIsNone(row['fill_price'])
        self.assertNotEqual(row['fill_price'], row['limit_price'])
        self.assertEqual(self.runner.status, 'BLOCKED')
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(FakeBroker.submissions, [])

    def test_paused_reconcile_rejects_account_position_mismatch_after_receipt(self):
        self.paused_unknown_dna(actual_qty=87)
        with self.assertRaisesRegex(ValueError, '持仓'):
            self.runner.reconcile()
        self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], 88)
        self.assertEqual(self.engine.state()['orders'][0]['fill_price'], 11.24)
        self.assertEqual(self.runner.status, 'BLOCKED')
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(FakeBroker.submissions, [])

    def test_paused_reconcile_rejects_insufficient_reserved_account_cash(self):
        self.paused_unknown_dna()
        FakeBroker.cash = 989999.99
        with self.assertRaisesRegex(ValueError, '保留资金'):
            self.runner.reconcile()
        self.assertEqual(self.runner.status, 'BLOCKED')
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(FakeBroker.submissions, [])

    def test_paused_reconcile_funds_read_error_keeps_halt_and_original_order_intent(self):
        self.paused_unknown_dna()
        with patch.object(self.engine.broker, 'snapshot', side_effect=BrokerReadError('只读账户查询未成功')):
            with self.assertRaises(BrokerReadError):
                self.runner.reconcile()
        self.assertEqual(self.runner.status, 'BLOCKED')
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], 88)
        self.assertEqual(FakeBroker.submissions, [])

    def test_paused_reconcile_keeps_unknown_receipt_blocked_without_funds_read(self):
        self.paused_unknown_dna()
        FakeBroker.reconcile_result = {'order_id': 'fixture-416313', 'status': 'UNKNOWN',
                                       'dealt_qty': 0, 'dealt_avg_price': None}
        calls = len(FakeBroker.snapshot_calls)
        with self.assertRaisesRegex(ValueError, '无法确认'):
            self.runner.reconcile()
        self.assertEqual(len(FakeBroker.snapshot_calls), calls)
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM order_fills').fetchone()[0], 0)
        self.assertEqual(self.runner.status, 'BLOCKED')
        self.assertTrue(self.engine.halt_event.is_set())
        self.assertEqual(FakeBroker.submissions, [])

    def test_reconcile_refuses_running_worker_before_any_account_query(self):
        self.connect()
        calls = len(FakeBroker.snapshot_calls)
        with self.assertRaisesRegex(ValueError, '暂停'):
            self.runner.reconcile()
        self.assertEqual(len(FakeBroker.snapshot_calls), calls)
        self.assertEqual(FakeBroker.reconcile_calls, [])
        self.assertEqual(FakeBroker.submissions, [])

    def test_prewarm_before_execution_reads_no_funds_or_prices_and_never_sends(self):
        self.partial_runner()
        self.runner._prepare(self.opening + timedelta(minutes=39))
        FakeBroker.snapshot_calls.clear()
        self.tick_at(self.opening + timedelta(minutes=39))
        self.assertEqual(FakeBroker.prewarm_calls, [])
        self.tick_at(self.opening + timedelta(minutes=40))
        self.assertEqual(FakeBroker.prewarm_calls, [['US.AAPL']])
        self.assertEqual(FakeBroker.snapshot_calls, [])
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.runner.status, 'WAITING_OPEN')
        self.assertEqual(self.runner.state()['subscription_prewarm']['status'], 'SUBSCRIBED')
        self.assertNotIn('asof', self.runner.state()['subscription_prewarm'])
        self.tick_at(self.opening + timedelta(minutes=44))
        self.assertEqual(FakeBroker.prewarm_calls, [['US.AAPL']])

    def test_zero_delay_preopen_warming_never_reads_prices_or_submits_orders(self):
        self.partial_runner(delay=0)
        self.runner._prepare(self.opening - timedelta(minutes=6))
        FakeBroker.snapshot_calls.clear()
        self.runner._prewarm(self.opening - timedelta(minutes=6), self.opening)
        self.assertEqual(FakeBroker.prewarm_calls, [])
        self.runner._prewarm(self.opening - timedelta(minutes=5), self.opening)
        self.assertEqual(FakeBroker.prewarm_calls, [["US.AAPL"]])
        self.assertEqual(FakeBroker.snapshot_calls, [])
        self.assertEqual(FakeBroker.submissions, [])
        self.assertNotIn("asof", self.runner.state()["subscription_prewarm"])

    def test_prewarm_failure_is_persistent_and_thirty_second_retry_is_subscription_only(self):
        self.partial_runner()
        FakeBroker.prewarm_error = BrokerError('subscription unavailable')
        self.tick_at(self.opening + timedelta(minutes=40))
        self.assertEqual(self.runner.status, 'WAITING_OPEN')
        self.assertEqual(self.engine._get('best_subscription_prewarm', {})['status'], 'ERROR')
        self.tick_at(self.opening + timedelta(minutes=40, seconds=29))
        self.assertEqual(len(FakeBroker.prewarm_calls), 1)
        FakeBroker.prewarm_error = None
        self.tick_at(self.opening + timedelta(minutes=40, seconds=30))
        self.assertEqual(len(FakeBroker.prewarm_calls), 2)
        self.assertEqual(FakeBroker.submissions, [])

    def test_partial_quote_recovery_buys_new_code_once_while_old_held_quote_is_bad(self):
        self.source.rows = [{'code': 'US.AAPL', 'target_weight': .1}, {'code': 'US.MSFT', 'target_weight': .1}]
        self.partial_runner()
        scheduled = self.opening + timedelta(minutes=45)
        FakeBroker.quote_errors = {'US.MSFT': 'real last-price source clock stale'}
        self.tick_at(scheduled + timedelta(seconds=1))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.AAPL'])
        first_asof = self.engine._get('best_execution', {})['phase_asof']
        plan = deepcopy(self.runner.plan)
        self.tick_at(scheduled + timedelta(seconds=2))
        self.assertEqual(self.runner.status, 'PARTIALLY_EXECUTED')
        FakeBroker.quote_errors = {'US.AAPL': 'held stock book clock unavailable'}
        self.tick_at(scheduled + timedelta(minutes=5))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.AAPL', 'US.MSFT'])
        self.assertEqual(self.engine._get('best_execution', {})['phase_asof'], first_asof)
        self.tick_at(scheduled + timedelta(minutes=5, seconds=1))
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 2)
        self.assertEqual([row['order_type'] for row in FakeBroker.submissions], ['MARKET', 'MARKET'])
        self.assertEqual([row['order_type'] for row in self.engine.state()['orders']], ['MARKET', 'MARKET'])
        self.assertEqual(self.runner.plan, plan)
        self.assertEqual(self.runner.plan['rows'][1]['target_weight'], .1)
        self.assertEqual(self.engine._get('best_capital', {})['unused_cash'], 990000)

    def test_partial_wide_spread_waits_for_new_quote_without_changing_frozen_weight(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        frozen = None
        original_snapshot_partial = FakeBroker.snapshot_partial

        def with_spread(self, codes, *, bid, ask, price):
            snapshot = original_snapshot_partial(self, codes)
            quote = snapshot['quotes'].get('US.AAPL')
            if quote:
                quote.update(bid=bid, ask=ask, price=price)
            return snapshot

        with patch.object(FakeBroker, 'snapshot_partial',
                          lambda broker, codes: with_spread(broker, codes, bid=98, ask=102, price=100)):
            self.tick_at(noon + timedelta(seconds=1))
            frozen = deepcopy(self.engine._get('best_plan', None))
            self.assertEqual(self.runner.status, 'WAITING_QUOTES')
            self.assertEqual(self.engine.state()['orders'], [])
            self.assertEqual(FakeBroker.submissions, [])
            self.assertIn('价差', self.runner.state()['skipped'][0]['reason'])

        with patch.object(FakeBroker, 'snapshot_partial',
                          lambda broker, codes: with_spread(broker, codes, bid=100.01, ask=100.03, price=100.02)):
            self.tick_at(noon + timedelta(seconds=31))
            self.assertEqual(len(FakeBroker.submissions), 1)
            self.assertEqual(FakeBroker.submissions[0]['code'], 'US.AAPL')
            self.assertEqual(FakeBroker.submissions[0]['limit_price'], 100.03)
            self.tick_at(noon + timedelta(seconds=32))

        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(self.engine._get('best_plan', None), frozen)
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_broker_reserved_cash_is_not_available_to_buy_after_quote_retry(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        self.runner._prepare(noon - timedelta(minutes=1))
        FakeBroker.cash = 990050.0  # Account has $990k idle cash, but this strategy has only $50.
        FakeBroker.quote_errors = {'US.AAPL': 'source clock stale'}
        self.tick_at(noon + timedelta(seconds=1))
        self.assertEqual(self.runner.status, 'WAITING_QUOTES')
        FakeBroker.quote_errors.clear()
        self.tick_at(noon + timedelta(seconds=31))
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.state()['orders'], [])
        self.assertAlmostEqual(self.runner.state()['cash'], 50.0)
        self.assertEqual(self.engine._get('best_capital', {})['unused_cash'], 990000.0)

    def test_transient_reconcile_read_error_preserves_pending_order_and_recovers_without_duplicate(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        with patch.object(FakeBroker, 'submit', self.submit_without_fill):
            self.tick_at(noon + timedelta(seconds=1))
            original = deepcopy(self.engine.state()['orders'][0])
            self.assertEqual(original['status'], 'PENDING_RECONCILE')
            self.assertEqual(len(FakeBroker.submissions), 1)
            with patch.object(FakeBroker, 'reconcile', side_effect=BrokerReadError('history query timed out')):
                with self.assertRaises(BrokerReadError):
                    self.tick_at(noon + timedelta(seconds=2))
            self.assertEqual(self.engine.state()['orders'][0]['status'], 'PENDING_RECONCILE')
            self.assertFalse(self.engine.halt_event.is_set())
            self.assertEqual(len(FakeBroker.submissions), 1)
            FakeBroker.positions = {'US.AAPL': original['qty']}
            FakeBroker.cash = 1000000.0 - original['qty'] * original['limit_price']
            FakeBroker.reconcile_result = {'order_id': 'pending-123', 'status': 'FILLED_ALL',
                'dealt_qty': original['qty'], 'dealt_avg_price': original['limit_price']}
            self.tick_at(noon + timedelta(seconds=33))
            self.assertEqual(self.runner.status, 'EXECUTED')
            self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], original['qty'])
            self.assertEqual(len(FakeBroker.submissions), 1)

    def test_ambiguous_reconcile_status_halts_and_never_reissues_buy(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        with patch.object(FakeBroker, 'submit', self.submit_without_fill):
            self.tick_at(noon + timedelta(seconds=1))
            FakeBroker.reconcile_result = {'order_id': 'pending-123', 'status': 'UNKNOWN',
                'dealt_qty': 0, 'dealt_avg_price': None}
            with self.assertRaisesRegex(ValueError, '结果未知'):
                self.tick_at(noon + timedelta(seconds=2))
            self.assertEqual(self.engine.state()['orders'][0]['status'], 'UNKNOWN')
            self.assertTrue(self.engine.halt_event.is_set())
            self.assertEqual(len(FakeBroker.submissions), 1)
            with self.assertRaises(ValueError):
                self.tick_at(noon + timedelta(seconds=62))
            self.assertEqual(len(FakeBroker.submissions), 1)

    def test_pending_order_reprices_same_broker_id_after_thirty_seconds_only(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        changed = []
        original_snapshot_partial = FakeBroker.snapshot_partial

        def changed_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            quote = snapshot['quotes'].get('US.AAPL')
            if quote:
                quote.update(price=100.02, bid=100.01, ask=100.03)
            return snapshot

        def reprice(broker, order, order_id, client_id, *, expected_dealt_qty, execution_deadline_utc):
            changed.append(dict(order=deepcopy(order), order_id=order_id, client_id=client_id,
                                expected_dealt_qty=expected_dealt_qty,
                                execution_deadline_utc=execution_deadline_utc))
            return dict(order_id=order_id, status='PENDING_RECONCILE', qty=order['qty'],
                        limit_price=order['limit_price'], dealt_qty=expected_dealt_qty)

        with patch.object(FakeBroker, 'submit', self.submit_without_fill), \
             patch.object(FakeBroker, 'reprice', reprice, create=True):
            self.tick_at(noon + timedelta(seconds=1))
            first = deepcopy(self.engine.state()['orders'][0])
            self.mark_pending_order_as_legacy_limit()
            FakeBroker.reconcile_result = dict(order_id='pending-123', status='SUBMITTED',
                                               dealt_qty=0, dealt_avg_price=None)
            with patch.object(FakeBroker, 'snapshot_partial', changed_quote):
                self.tick_at(noon + timedelta(seconds=20))
                self.assertEqual(changed, [])
                self.tick_at(noon + timedelta(seconds=31))
                self.assertEqual(len(changed), 1)
                self.assertEqual(changed[0]['order_id'], 'pending-123')
                self.assertEqual(changed[0]['client_id'], first['id'])
                self.assertEqual(changed[0]['order']['code'], 'US.AAPL')
                self.assertEqual(changed[0]['order']['side'], 'BUY')
                self.assertEqual(changed[0]['order']['qty'], first['qty'])
                self.assertEqual(changed[0]['order']['limit_price'], 100.03)
                self.assertEqual(changed[0]['expected_dealt_qty'], 0)
                self.assertEqual(changed[0]['execution_deadline_utc'],
                                 (noon + timedelta(seconds=600)).isoformat())
                self.assertLessEqual(changed[0]['order']['qty'] * changed[0]['order']['limit_price'],
                                     changed[0]['order']['max_order_notional'])
                self.tick_at(noon + timedelta(seconds=32))
                self.assertEqual(len(changed), 1)
                self.assertEqual(len(FakeBroker.submissions), 1)
                self.assertEqual(self.engine.state()['orders'][0]['order_id'], 'pending-123')
                self.tick_at(noon + timedelta(seconds=600))
                self.assertEqual(len(changed), 1)
                self.assertEqual(len(FakeBroker.submissions), 1)

    def test_market_pending_order_only_reconciles_without_limit_repricing_or_resubmission(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        original_snapshot_partial = FakeBroker.snapshot_partial

        def changed_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            quote = snapshot['quotes'].get('US.AAPL')
            if quote:
                quote.update(price=100.02, bid=100.01, ask=100.03)
            return snapshot

        with patch.object(FakeBroker, 'submit', self.submit_without_fill), \
             patch.object(FakeBroker, 'reprice', side_effect=AssertionError('MARKET must not amend'), create=True):
            self.tick_at(noon + timedelta(seconds=1))
            first = self.engine.state()['orders'][0]
            self.assertEqual(first['order_type'], 'MARKET')
            self.assertEqual(FakeBroker.submit_options[0]['order_type'], 'MARKET')
            FakeBroker.reconcile_result = dict(order_id='pending-123', status='SUBMITTED',
                                               dealt_qty=0, dealt_avg_price=None)
            with patch.object(FakeBroker, 'snapshot_partial', changed_quote):
                self.tick_at(noon + timedelta(seconds=31))
                self.tick_at(noon + timedelta(seconds=61))
            self.assertEqual(self.runner.status, 'PENDING_RECONCILE')
            self.assertEqual(len(FakeBroker.submissions), 1)
            self.assertEqual(self.engine._get('best_order_reprices', {}), {})
            self.assertEqual(self.engine.state()['orders'][0]['order_id'], 'pending-123')

    def test_paused_reconcile_recovers_confirmed_reduced_amendment_and_terminal_fill(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        with patch.object(FakeBroker, 'submit', self.submit_without_fill):
            self.tick_at(noon + timedelta(seconds=1))
        original = self.engine.state()['orders'][0]
        self.mark_pending_order_as_legacy_limit()
        amended_qty = original['qty'] - 1
        amended_price = 100.03
        self.engine._set('best_order_reprices', {original['id']: dict(
            order_id='pending-123', qty=amended_qty, limit_price=amended_price,
            original_limit_price=original['limit_price'], attempted_at=noon.isoformat(),
            count=1, status='ATTEMPTING')})
        FakeBroker.positions = {'US.AAPL': amended_qty}
        FakeBroker.cash -= amended_qty * amended_price
        FakeBroker.reconcile_result = dict(order_id='pending-123', status='FILLED_ALL',
            qty=amended_qty, limit_price=amended_price,
            dealt_qty=amended_qty, dealt_avg_price=amended_price)
        self.runner.stop()
        state = self.runner.reconcile()
        self.assertEqual(state['orders'][0]['qty'], amended_qty)
        self.assertEqual(state['orders'][0]['limit_price'], amended_price)
        self.assertEqual(state['orders'][0]['fill_qty'], amended_qty)
        self.assertEqual(self.engine._get('best_order_reprices', {})[original['id']]['status'],
                         'RESOLVED_TERMINAL')
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_reprice_reduces_remaining_buy_when_old_position_uses_symbol_budget(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        amended = []
        original_snapshot_partial = FakeBroker.snapshot_partial

        def quote_with_old_position(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            snapshot['quotes']['US.AAPL'].update(price=100.02, bid=100.01, ask=100.03)
            return snapshot

        def reprice(broker, order, order_id, client_id, **kwargs):
            amended.append(deepcopy(order))
            return dict(order_id=order_id, status='PENDING_RECONCILE',
                        qty=order['qty'], limit_price=order['limit_price'], dealt_qty=0)

        with patch.object(FakeBroker, 'submit', self.submit_without_fill), \
             patch.object(FakeBroker, 'reprice', reprice, create=True):
            self.tick_at(noon + timedelta(seconds=1))
            self.mark_pending_order_as_legacy_limit()
            original_qty = self.engine.state()['orders'][0]['qty']
            FakeBroker.reconcile_result = dict(order_id='pending-123', status='SUBMITTED',
                                               dealt_qty=0, dealt_avg_price=None)
            FakeBroker.positions = {'US.AAPL': 4}
            with patch.object(FakeBroker, 'snapshot_partial', quote_with_old_position), \
                 patch.object(self.runner, '_accept_snapshot'):
                self.tick_at(noon + timedelta(seconds=31))
        self.assertEqual(len(amended), 1)
        self.assertLess(amended[0]['qty'], original_qty)
        self.assertLessEqual((4 + amended[0]['qty']) * amended[0]['limit_price'],
                             amended[0]['max_order_notional'])

    def test_part_fill_reprices_original_total_quantity_then_final_fill_is_idempotent(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        changed = []
        original_snapshot_partial = FakeBroker.snapshot_partial

        def changed_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            quote = snapshot['quotes'].get('US.AAPL')
            if quote:
                quote.update(price=100.02, bid=100.01, ask=100.03)
            return snapshot

        def reprice(broker, order, order_id, client_id, *, expected_dealt_qty, execution_deadline_utc):
            changed.append((deepcopy(order), order_id, client_id, expected_dealt_qty))
            return dict(order_id=order_id, status='PENDING_RECONCILE', qty=order['qty'],
                        limit_price=order['limit_price'], dealt_qty=expected_dealt_qty)

        with patch.object(FakeBroker, 'submit', self.submit_without_fill), \
             patch.object(FakeBroker, 'reprice', reprice, create=True):
            self.tick_at(noon + timedelta(seconds=1))
            first = deepcopy(self.engine.state()['orders'][0])
            self.mark_pending_order_as_legacy_limit()
            self.assertGreater(first['qty'], 3)
            FakeBroker.positions = {'US.AAPL': 3}
            FakeBroker.cash = 1000000.0 - 3 * first['limit_price']
            FakeBroker.reconcile_result = dict(order_id='pending-123', status='FILLED_PART',
                                               dealt_qty=3, dealt_avg_price=first['limit_price'])
            with patch.object(FakeBroker, 'snapshot_partial', changed_quote):
                self.tick_at(noon + timedelta(seconds=31))
                self.assertEqual(len(changed), 1)
                order, order_id, client_id, expected = changed[0]
                self.assertEqual(order_id, 'pending-123')
                self.assertEqual(client_id, first['id'])
                self.assertEqual(order['qty'], first['qty'])  # Broker modify qty is total, not the six-share remainder.
                self.assertEqual(expected, 3)
                self.assertEqual(order['limit_price'], 100.03)
                self.assertEqual(len(FakeBroker.submissions), 1)
                FakeBroker.positions = {'US.AAPL': first['qty']}
                FakeBroker.cash = 1000000.0 - 3 * first['limit_price'] - (first['qty'] - 3) * 100.03
                FakeBroker.reconcile_result = dict(order_id='pending-123', status='FILLED_ALL',
                                                   dealt_qty=first['qty'], dealt_avg_price=100.02)
                self.tick_at(noon + timedelta(seconds=32))
                self.assertEqual(self.runner.status, 'EXECUTED')
                self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], first['qty'])
                self.tick_at(noon + timedelta(seconds=33))
                self.assertEqual(len(changed), 1)
                self.assertEqual(len(FakeBroker.submissions), 1)

    def test_pending_order_stops_repricing_after_ten_amendments(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        changed = []
        original_snapshot_partial = FakeBroker.snapshot_partial

        def moving_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            quote = snapshot['quotes'].get('US.AAPL')
            if quote:
                minute = int((FakeBroker.clock() - noon).total_seconds())
                ask = round(100.01 + .01 * max(1, (minute - 1) // 30), 2)
                quote.update(price=round(ask - .01, 2), bid=round(ask - .02, 2), ask=ask)
            return snapshot

        def reprice(broker, order, order_id, client_id, *, expected_dealt_qty, execution_deadline_utc):
            changed.append(deepcopy(order))
            return dict(order_id=order_id, status='PENDING_RECONCILE', qty=order['qty'],
                        limit_price=order['limit_price'], dealt_qty=expected_dealt_qty)

        with patch.object(FakeBroker, 'submit', self.submit_without_fill), \
             patch.object(FakeBroker, 'reprice', reprice, create=True):
            self.tick_at(noon + timedelta(seconds=1))
            self.mark_pending_order_as_legacy_limit()
            FakeBroker.reconcile_result = dict(order_id='pending-123', status='SUBMITTED',
                                               dealt_qty=0, dealt_avg_price=None)
            with patch.object(FakeBroker, 'snapshot_partial', moving_quote):
                for attempt in range(1, 12):
                    self.tick_at(noon + timedelta(seconds=1 + 30 * attempt))
            self.assertEqual(len(changed), 10)
            self.assertEqual(self.engine._get('best_order_reprices', {})[
                self.engine.state()['orders'][0]['id']]['count'], 10)
            self.assertEqual(len(FakeBroker.submissions), 1)

    def assert_terminal_buy_retries_remaining_once(self, terminal_status, dealt_qty, *, bad_retry_quote=False):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        frozen = None
        original_submit = FakeBroker.submit
        original_snapshot_partial = FakeBroker.snapshot_partial

        def first_pending_then_fill(broker, order, client_id, **options):
            if not FakeBroker.submissions:
                return self.submit_without_fill(broker, order, client_id, **options)
            return original_submit(broker, order, client_id, **options)

        def fresh_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            quote = snapshot['quotes'].get('US.AAPL')
            if quote:
                quote.update(price=100.02, bid=100.01, ask=100.03)
            return snapshot

        with patch.object(FakeBroker, 'submit', first_pending_then_fill):
            self.tick_at(noon + timedelta(seconds=1))
            first = deepcopy(self.engine.state()['orders'][0])
            frozen = deepcopy(self.engine._get('best_plan', None))
            self.assertEqual(len(FakeBroker.submissions), 1)
            self.assertEqual(FakeBroker.submissions[0]['order_type'], 'MARKET')
            if dealt_qty:
                FakeBroker.positions = {'US.AAPL': dealt_qty}
                FakeBroker.cash = 1000000.0 - dealt_qty * first['limit_price']
            FakeBroker.reconcile_result = dict(order_id='pending-123', status=terminal_status,
                                               dealt_qty=dealt_qty,
                                               dealt_avg_price=first['limit_price'] if dealt_qty else None)
            self.tick_at(noon + timedelta(seconds=2))
            self.assertEqual(len(FakeBroker.submissions), 1)
            with patch.object(FakeBroker, 'snapshot_partial', fresh_quote):
                self.tick_at(noon + timedelta(seconds=20))
                self.assertEqual(len(FakeBroker.submissions), 1)
                self.assertEqual(self.runner.status, 'RETRY_COOLDOWN')
                retry_second = 32
                if bad_retry_quote:
                    FakeBroker.quote_errors = {'US.AAPL': 'real source clock stale'}
                    self.tick_at(noon + timedelta(seconds=32))
                    self.assertEqual(len(FakeBroker.submissions), 1)
                    FakeBroker.quote_errors.clear()
                    retry_second = 62
                self.tick_at(noon + timedelta(seconds=retry_second))
                self.assertEqual(len(FakeBroker.submissions), 2)
                second = FakeBroker.submissions[1]
                self.assertEqual(second['code'], 'US.AAPL')
                self.assertEqual(second['side'], 'BUY')
                self.assertEqual(second['order_type'], 'MARKET')
                self.assertEqual(second['qty'], first['qty'] - dealt_qty)
                self.assertEqual(second['limit_price'], 100.03)
                self.assertNotEqual(second['client_id'], first['id'])
                self.assertLessEqual(second['qty'] * second['limit_price'],
                                     self.source.rows[0]['target_weight'] * self.runner.budget / 1.005)
                FakeBroker.reconcile_result = dict(order_id='123', status='FILLED_ALL',
                                                   dealt_qty=second['qty'], dealt_avg_price=100.03)
                self.tick_at(noon + timedelta(seconds=retry_second + 1))
                self.assertEqual(FakeBroker.positions['US.AAPL'], first['qty'])
                self.tick_at(noon + timedelta(seconds=retry_second + 31))
                self.assertEqual(len(FakeBroker.submissions), 2)
                self.assertEqual(self.engine._get('best_plan', None), frozen)

    def test_failed_buy_retries_frozen_remaining_after_terminal_cooldown(self):
        self.assert_terminal_buy_retries_remaining_once('FAILED', 0)

    def test_cancelled_all_buy_retries_frozen_remaining_after_terminal_cooldown(self):
        self.assert_terminal_buy_retries_remaining_once('CANCELLED_ALL', 0)

    def test_cancelled_part_buy_only_retries_unfilled_quantity(self):
        self.assert_terminal_buy_retries_remaining_once('CANCELLED_PART', 3)

    def test_terminal_failed_buy_waits_for_qualified_quote_before_retry(self):
        self.assert_terminal_buy_retries_remaining_once('FAILED', 0, bad_retry_quote=True)

    def test_confirmed_failed_buy_retry_survives_engine_restart_without_duplicate(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        original_submit = FakeBroker.submit

        def first_pending_then_fill(broker, order, client_id, **options):
            if not FakeBroker.submissions:
                return self.submit_without_fill(broker, order, client_id, **options)
            return original_submit(broker, order, client_id, **options)

        with patch.object(FakeBroker, 'submit', first_pending_then_fill):
            self.tick_at(noon + timedelta(seconds=1))
            first_id = self.engine.state()['orders'][0]['id']
            FakeBroker.reconcile_result = dict(order_id='pending-123', status='FAILED',
                                               dealt_qty=0, dealt_avg_price=None)
            self.tick_at(noon + timedelta(seconds=2))
            self.runner.close()
            self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
            self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
            self.connect()
            self.tick_at(noon + timedelta(seconds=20))
            self.assertEqual(len(FakeBroker.submissions), 1)
            self.tick_at(noon + timedelta(seconds=32))
            self.assertEqual(len(FakeBroker.submissions), 2)
            self.assertNotEqual(FakeBroker.submissions[1]['client_id'], first_id)
            second = FakeBroker.submissions[1]
            FakeBroker.reconcile_result = dict(order_id='123', status='FILLED_ALL',
                                               dealt_qty=second['qty'], dealt_avg_price=second['limit_price'])
            self.tick_at(noon + timedelta(seconds=33))
            self.assertEqual(len(FakeBroker.submissions), 2)

    def test_partial_definitely_unsent_retries_same_client_id_and_preserves_target_and_deadline(self):
        self.partial_runner()
        scheduled = self.opening + timedelta(minutes=45)
        error = BrokerOrderNotSent('只读查询暂未成功；尚未送出订单')
        error.retry_after_seconds = 30
        FakeBroker.before_send_error = error
        with self.assertRaises(BrokerReadError):
            self.tick_at(scheduled + timedelta(seconds=1))
        intent = deepcopy(self.engine._get('best_execution', {}))
        first = self.engine.state()['orders'][0]
        self.assertEqual(first['status'], 'CANCELLED_BEFORE_SEND')
        self.assertEqual(FakeBroker.submissions, [])
        self.assertFalse(self.engine.halt_event.is_set())
        self.assertFalse(self.engine._pending())
        FakeBroker.before_send_error = None
        self.tick_at(scheduled + timedelta(seconds=31))
        self.assertEqual(len(FakeBroker.submissions), 1)
        self.assertEqual(FakeBroker.submissions[0]['client_id'], first['id'])
        current = self.engine._get('best_execution', {})
        self.assertEqual(current['target_quantities'], intent['target_quantities'])
        self.assertEqual(current['phase_asof'], intent['phase_asof'])
        self.assertTrue(all(row['allow_partial_quotes'] for row in FakeBroker.submit_options))
        self.assertEqual({row['execution_deadline_utc'] for row in FakeBroker.submit_options},
                         {(scheduled + timedelta(seconds=600)).isoformat()})
        self.tick_at(scheduled + timedelta(seconds=32))
        self.assertEqual(self.engine.state()['orders'][0]['status'], 'FILLED_ALL')
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_partial_deferred_zero_target_held_quote_recovers_sell_then_resumes_frozen_buy_without_repeats(self):
        self.source.rows = [{'code': 'US.AAPL', 'target_weight': .1}, {'code': 'US.MSFT', 'target_weight': 0}]
        self.partial_runner()
        old = (self.opening - timedelta(days=3)).isoformat()
        self.engine.db.execute('INSERT INTO orders '
            '(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            ('prior-verified-msft', old, SID, 'moomoo_simulate', self.engine.account_id,
             'US.MSFT', 'BUY', 5, 100.0, 'FILLED_ALL', 'prior-broker-order'))
        self.engine.db.execute('INSERT INTO order_fills VALUES (?,?)',
            ('prior-verified-msft', json.dumps({'fill_qty': 5, 'fill_price': 100.0, 'filled_at': old})))
        self.engine.db.commit()
        FakeBroker.positions = {'US.MSFT': 5}
        FakeBroker.cash = 999500.0
        self.runner._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
        scheduled = self.opening + timedelta(minutes=45)
        FakeBroker.quote_errors = {'US.MSFT': 'held source clock stale'}
        self.tick_at(scheduled + timedelta(seconds=1))
        self.assertEqual([(row['code'], row['side']) for row in FakeBroker.submissions], [('US.AAPL', 'BUY')])
        buy = deepcopy(self.engine._get('best_execution', {}))
        self.tick_at(scheduled + timedelta(seconds=2))
        self.assertEqual(self.runner.status, 'PARTIALLY_EXECUTED')
        FakeBroker.quote_errors = {}
        self.tick_at(scheduled + timedelta(minutes=5))
        self.assertEqual([(row['code'], row['side'], row['qty']) for row in FakeBroker.submissions],
                         [('US.AAPL', 'BUY', 9), ('US.MSFT', 'SELL', 5)])
        self.assertEqual([row['order_type'] for row in FakeBroker.submissions], ['MARKET', 'MARKET'])
        sell = self.engine._get('best_execution', {})
        self.assertEqual(sell['phase'], 'SELL')
        self.assertEqual(sell['resume_buy_state']['target_quantities'], buy['target_quantities'])
        self.assertEqual(sell['resume_buy_state']['phase_asof'], buy['phase_asof'])
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.connect()
        self.tick_at(scheduled + timedelta(minutes=5, seconds=1))
        final = self.engine._get('best_execution', {})
        self.assertEqual(final['phase'], 'DONE')
        self.assertEqual(final['target_quantities'], buy['target_quantities'])
        self.assertEqual(final['phase_asof'], buy['phase_asof'])
        self.assertEqual(final['deferred_sells'], [])
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(FakeBroker.positions['US.MSFT'], 0)
        self.tick_at(scheduled + timedelta(minutes=6))
        self.assertEqual(len(FakeBroker.submissions), 2)

    def test_partial_completed_broker_signal_keeps_final_status_after_window_without_new_io(self):
        self.partial_runner()
        scheduled = self.opening + timedelta(minutes=45)
        self.tick_at(scheduled + timedelta(seconds=1))
        self.tick_at(scheduled + timedelta(seconds=2))
        self.assertEqual(self.runner.status, 'EXECUTED')
        count = len(FakeBroker.snapshot_calls)
        self.tick_at(scheduled + timedelta(seconds=600))
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.snapshot_calls), count)
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_partial_unavailable_quotes_preserve_cash_and_expire_without_late_replay(self):
        self.partial_runner()
        scheduled = self.opening + timedelta(minutes=45)
        FakeBroker.quote_errors = {'US.AAPL': 'source clock stale'}
        self.tick_at(scheduled + timedelta(seconds=1))
        self.assertEqual(self.runner.status, 'WAITING_QUOTES')
        self.assertEqual(self.engine.state()['orders'], [])
        self.assertEqual(self.runner.state()['skipped'][0]['code'], 'US.AAPL')
        calls = len(FakeBroker.snapshot_calls)
        self.tick_at(scheduled + timedelta(seconds=600))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(len(FakeBroker.snapshot_calls), calls)
        self.tick_at(self.opening + timedelta(hours=1, minutes=17))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(FakeBroker.submissions, [])

    def test_partial_phase_quantity_and_asof_survive_restart_and_do_not_resend_attempted(self):
        self.source.rows = [{'code': 'US.AAPL', 'target_weight': .1}, {'code': 'US.MSFT', 'target_weight': .1}]
        self.partial_runner()
        scheduled = self.opening + timedelta(minutes=45)
        FakeBroker.quote_errors = {'US.MSFT': 'not ready'}
        self.tick_at(scheduled + timedelta(seconds=1))
        self.tick_at(scheduled + timedelta(seconds=2))
        saved = deepcopy(self.engine._get('best_execution', {}))
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.connect()
        self.assertEqual((self.runner.execution_window_seconds, self.runner.allow_partial_quotes), (600, True))
        FakeBroker.quote_errors.clear()
        self.tick_at(scheduled + timedelta(minutes=1))
        restored = self.engine._get('best_execution', {})
        self.assertEqual(restored['phase_asof'], saved['phase_asof'])
        self.assertEqual(restored['target_quantities']['US.AAPL'], saved['target_quantities']['US.AAPL'])
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.AAPL', 'US.MSFT'])

    def test_partial_and_window_validation_defaults_and_policy_audit(self):
        self.assertEqual((self.runner.execution_window_seconds, self.runner.allow_partial_quotes), (60, False))
        for invalid in (True, False, 0, -1, 3601, 600.0, '600'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                BestBroker(self.temp.name, self.source, engine=self.engine, execution_window_seconds=invalid)
        with self.assertRaises(ValueError):
            BestBroker(self.temp.name, self.source, engine=self.engine, allow_partial_quotes='yes')
        self.partial_runner()
        changes = [json.loads(row[0]) for row in self.engine.db.execute("SELECT detail FROM audit WHERE event='EXECUTION_POLICY_CHANGED'")]
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]['execution_window_seconds'], changes[0]['allow_partial_quotes']), (600, True))

    def test_noon_replaces_only_unsent_intent_and_keeps_original_source_plan_hash_and_weights(self):
        self.partial_runner()
        source_status = self.source.status
        self.source.status = lambda now=None: {**source_status(now), 'status': 'MISSED_OPEN', 'execute_now': False}
        old_clock = self.opening + timedelta(minutes=45, seconds=1)
        FakeBroker.clock = staticmethod(lambda: old_clock)
        self.runner._prepare(old_clock)
        old = self.runner._execution(old_clock, 'BUY')
        original = deepcopy(self.engine._get('best_plan', None))
        self.tick_at(self.opening + timedelta(minutes=80))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(self.engine.state()['orders'], [])
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine, execution_delay_minutes=150)
        self.connect()
        noon = self.opening + timedelta(minutes=150)
        self.tick_at(self.opening + timedelta(minutes=130))
        self.assertEqual(self.runner.status, 'WAITING_OPEN')
        self.assertIn('美东 12:00', self.runner.reason)
        self.assertEqual(self.engine._get('best_execution', {}), {})
        archive = self.engine._get('best_execution_schedule_history', [])
        self.assertEqual(archive[0]['execution'], old)
        self.assertEqual(self.engine._get('best_plan', None), original)
        self.tick_at(noon - timedelta(microseconds=1))
        self.assertEqual(FakeBroker.submissions, [])
        self.tick_at(noon + timedelta(seconds=1))
        current = self.engine._get('best_execution', {})
        self.tick_at(noon + timedelta(seconds=2))
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 1)
        origin = json.loads(current['manifest']['source'])
        self.assertEqual(origin['next_open_utc'], self.opening.isoformat())
        self.assertEqual(origin['execution_time_utc'], noon.isoformat())
        self.assertEqual(origin['source_hash'], 'verified-frozen-source')
        self.assertEqual(current['manifest']['expires_at'], (noon + timedelta(seconds=600)).isoformat())
        self.assertEqual(self.engine._get('best_plan', None), original)
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.connect()
        self.assertEqual((self.runner.execution_delay_minutes, self.runner.execution_window_seconds), (150, 600))
        self.tick_at(noon + timedelta(seconds=600))
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_noon_window_expires_after_ten_minutes_without_late_submission(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        FakeBroker.quote_errors = {'US.AAPL': 'real source clock stale'}
        self.tick_at(noon + timedelta(seconds=599))
        self.assertEqual(self.runner.status, 'WAITING_QUOTES')
        calls = len(FakeBroker.snapshot_calls)
        self.tick_at(noon + timedelta(seconds=600))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(len(FakeBroker.snapshot_calls), calls)
        self.tick_at(noon + timedelta(minutes=20))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(self.engine.state()['orders'], [])
        self.assertEqual(FakeBroker.submissions, [])

    def test_noon_schedule_is_twelve_eastern_in_summer_and_winter_without_changing_market_open(self):
        from zoneinfo import ZoneInfo
        self.partial_runner(delay=150)
        for regular_open, utc_hour in (('2026-09-29T13:30:00+00:00', 16), ('2026-11-02T14:30:00+00:00', 17)):
            with self.subTest(regular_open=regular_open):
                scheduled = self.runner._scheduled_open(regular_open)
                local = scheduled.astimezone(ZoneInfo('America/New_York'))
                self.assertEqual((local.hour, local.minute), (12, 0))
                self.assertEqual(scheduled.hour, utc_hour)

    def test_initial_account_requires_empty_positions(self):
        FakeBroker.positions = {'US.MSFT': 1}
        with self.assertRaisesRegex(ValueError, '空仓'):
            self.connect()
        self.assertIsNone(self.engine._get('best_capital', None))

    def test_budget_separates_idle_simulated_cash_and_masks_account(self):
        self.connect()
        s = self.runner.state()
        self.assertEqual(s['cash'], 10000)
        self.assertEqual(s['equity'], 10000)
        self.assertEqual(s['account_id'], '****3604')
        self.assertEqual(self.engine.mode, 'moomoo_simulate')
        self.assertEqual(self.engine.limits['min_cash_reserve'], 990000)
        self.assertFalse(s['live_enabled'])

    def test_missed_open_and_before_open_cannot_submit(self):
        self.connect()
        self.runner.tick(now=self.opening - timedelta(seconds=1))
        self.assertEqual(self.runner.status, 'WAITING_OPEN')
        self.runner.tick(now=self.opening + timedelta(seconds=60))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(self.engine.state()['orders'], [])

    def test_stopped_tick_does_not_read_source_or_broker(self):
        self.runner.tick(now=self.opening)
        self.assertEqual(self.source.calls, [])
        self.assertEqual(self.engine.state()['orders'], [])

    def test_plan_preserves_signal_origin_and_uses_strategy_budget(self):
        self.connect()
        now = self.opening + timedelta(seconds=2)
        self.runner._prepare(now)
        sell = self.runner._execution(now, 'SELL')
        self.assertEqual(sell['manifest']['targets'][0]['target_qty'], 0)
        buy = self.runner._execution(now, 'BUY')
        self.assertEqual(buy['manifest']['targets'][0]['target_qty'], 9)
        origin = json.loads(buy['manifest']['source'])
        self.assertEqual(origin['signal_date'], '2026-09-25')
        self.assertEqual(origin['source_hash'], 'verified-frozen-source')
        self.assertFalse(origin['research_broker_action_allowed'])
        self.assertEqual(buy['manifest']['expires_at'], (self.opening + timedelta(seconds=60)).isoformat())
        self.assertEqual(self.runner._execution(now + timedelta(seconds=2), 'BUY'), buy)

    def test_different_selected_account_never_silently_rebinds(self):
        self.engine._set('best_account', '9999')
        with self.assertRaisesRegex(ValueError, '身份已变化'):
            self.connect()
        self.assertEqual(self.engine.mode, 'paper')

    def test_recovered_signal_reuses_original_close_plan(self):
        self.connect()
        self.runner._prepare(self.opening - timedelta(seconds=2))
        original = self.runner.plan.copy()
        self.source.close_states = lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not reconstruct yesterday from new holdings'))
        self.runner._prepare(self.opening + timedelta(seconds=2))
        self.assertEqual(self.runner.plan, original)

    def test_same_symbol_external_quantity_is_rejected(self):
        self.connect()
        FakeBroker.positions = {'US.AAPL': 1}
        with self.assertRaisesRegex(ValueError, '成交数量不一致'):
            self.runner._accept_snapshot(self.engine.broker.snapshot([]))

    def test_pause_resume_preserves_budget_without_rebinding(self):
        self.connect()
        before = self.engine._get('best_capital', None)
        self.runner.stop()
        self.runner._connect()
        self.assertEqual(self.engine._get('best_capital', None), before)
        self.assertEqual(self.engine.mode, 'moomoo_simulate')

    def test_open_window_orders_reconcile_to_real_qty_once_and_keep_original_plan(self):
        now = self.opening + timedelta(seconds=2)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is None else now.astimezone(tz)
        FakeBroker.clock = staticmethod(lambda: now)
        self.connect()
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock), patch('moomoo_component.best_broker.datetime', Clock):
            self.runner.tick(now=now)  # Freeze SELL, then prepare BUY after zero sells.
            original = self.engine._get('best_plan', None)
            self.runner.tick(now=now)  # Submit exactly one broker order.
            self.assertEqual(len(FakeBroker.submissions), 1)
            self.assertTrue(self.engine._pending())
            self.runner.tick(now=now)  # Reconcile actual qty and average; target reached.
            self.assertEqual(self.runner.status, 'EXECUTED')
            self.runner.tick(now=now)
            self.assertEqual(len(FakeBroker.submissions), 1)
            order = self.engine.state()['orders'][0]
            self.assertEqual(order['fill_qty'], 9)
            self.assertEqual(order['fill_price'], 100.01)
            self.assertEqual(self.engine._get('best_plan', None), original)

    def test_stop_during_source_read_blocks_all_subsequent_submission(self):
        self.connect()
        original = self.source.status
        def stopped(now=None):
            result = original(now)
            self.runner.stop()
            return result
        self.source.status = stopped
        with self.assertRaisesRegex(ValueError, '停止'):
            self.runner.tick(now=self.opening)
        self.assertEqual(self.engine.state()['orders'], [])

    def delayed_runner(self):
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
                                 execution_delay_minutes=45)

    def test_delayed_window_waits_then_buys_once_with_unchanged_signal_plan(self):
        self.delayed_runner()
        original_status = self.source.status
        self.source.status = lambda now=None: {**original_status(now), 'status': 'MISSED_OPEN'}
        self.connect()
        for now in (self.opening, self.opening + timedelta(minutes=44,seconds=59)):
            self.runner.tick(now=now)
            self.assertEqual(self.runner.status, 'WAITING_OPEN')
            self.assertEqual(FakeBroker.submissions, [])
        original_plan = self.engine._get('best_plan', None)
        now = self.opening + timedelta(minutes=45,seconds=2)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is None else now.astimezone(tz)
        FakeBroker.clock = staticmethod(lambda: now)
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock), patch('moomoo_component.best_broker.datetime', Clock):
            for _ in range(4):
                self.runner.tick(now=now)
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 1)
        self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], 9)
        execution = self.engine._get('best_execution', {})
        origin = json.loads(execution['manifest']['source'])
        self.assertEqual(origin['next_open_utc'], self.opening.isoformat())
        self.assertEqual(origin['execution_time_utc'], (self.opening+timedelta(minutes=45)).isoformat())
        self.assertEqual(origin['execution_delay_minutes'], 45)
        self.assertEqual(execution['manifest']['expires_at'],
                         (self.opening+timedelta(minutes=46)).isoformat())
        self.assertEqual(self.engine._get('best_plan', None), original_plan)
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.assertEqual(self.runner.execution_delay_minutes, 45)
        self.connect()
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock), patch('moomoo_component.best_broker.datetime', Clock):
            self.runner.tick(now=now)
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_delayed_window_expiry_never_catches_up(self):
        self.delayed_runner()
        self.connect()
        self.runner.tick(now=self.opening+timedelta(minutes=46))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.state()['orders'], [])

    def test_ten_eastern_ordinary_window_waits_and_uses_current_quotes(self):
        self.partial_runner(delay=30)
        opening=self.opening+timedelta(minutes=30)
        self.tick_at(opening-timedelta(microseconds=1))
        self.assertEqual(self.runner.status,'WAITING_OPEN');self.assertEqual(FakeBroker.submissions,[])
        for seconds in range(4):self.tick_at(opening+timedelta(seconds=seconds))
        self.assertTrue(FakeBroker.submissions)
        row=self.engine.db.execute('SELECT payload FROM strategies WHERE id=?',(self.runner.strategy_id,)).fetchone()
        self.assertIsNotNone(row);manifest=json.loads(row[0]);origin=json.loads(manifest['source'])
        self.assertEqual(origin['execution_time_utc'],opening.isoformat())
        self.assertEqual(origin['execution_delay_minutes'],30)
        self.assertEqual(manifest['expires_at'],(opening+timedelta(seconds=600)).isoformat())
        self.assertIsNone(self.engine._get('best_same_day_catchup',None))

    def test_ten_eastern_ordinary_window_expires_without_manual_grant(self):
        self.partial_runner(delay=30)
        self.tick_at(self.opening+timedelta(minutes=40))
        self.assertEqual(self.runner.status,'MISSED_OPEN');self.assertEqual(FakeBroker.submissions,[])
        self.assertEqual(self.engine.state()['orders'],[])
        self.assertIsNone(self.engine._get('best_same_day_catchup',None))

    def test_delayed_schedule_follows_dst_calendar_open(self):
        from zoneinfo import ZoneInfo
        self.delayed_runner()
        for delay,expected in ((0,(9,30)),(30,(10,0)),(45,(10,15))):
            self.runner.execution_delay_minutes=delay
            for regular_open in ('2026-09-29T13:30:00+00:00','2026-11-02T14:30:00+00:00'):
                with self.subTest(delay=delay,regular_open=regular_open):
                    scheduled = self.runner._scheduled_open(regular_open).astimezone(ZoneInfo('America/New_York'))
                    self.assertEqual((scheduled.hour,scheduled.minute),expected)

    def test_execution_delay_requires_bounded_integer(self):
        for invalid in (True,-1,181,45.0):
            with self.assertRaisesRegex(ValueError,'整数分钟'):
                BestBroker(self.temp.name,self.source,engine=self.engine,execution_delay_minutes=invalid)

    def old_unsubmitted_buy_intent(self):
        self.connect()
        self.runner._prepare(self.opening + timedelta(seconds=2))
        old = self.runner._execution(self.opening + timedelta(seconds=3), 'BUY')
        plan = self.engine._get('best_plan', None)
        self.delayed_runner()
        self.connect()
        return old, plan

    def test_changed_delay_archives_old_unsubmitted_intent_then_buys_once(self):
        old, plan = self.old_unsubmitted_buy_intent()
        self.runner.tick(now=self.opening + timedelta(minutes=44))
        self.assertEqual(self.engine._get('best_execution', {}), {})
        self.assertEqual(self.engine._get('best_execution_schedule_history', [])[0]['execution'], old)
        self.assertEqual(self.engine._get('best_plan', None), plan)
        now = self.opening + timedelta(minutes=45, seconds=2)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is None else now.astimezone(tz)
        FakeBroker.clock = staticmethod(lambda: now)
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock), patch('moomoo_component.best_broker.datetime', Clock):
            for _ in range(5):
                self.runner.tick(now=now)
        self.assertEqual(self.runner.status, 'EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 1)
        self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], 9)
        self.assertEqual(self.engine._get('best_execution', {})['manifest']['expires_at'],
                         (self.opening + timedelta(minutes=46)).isoformat())
        self.assertEqual(self.engine._get('best_plan', None), plan)

    def test_changed_delay_keeps_expired_intent_when_any_signal_order_was_attempted(self):
        old, _ = self.old_unsubmitted_buy_intent()
        self.engine.db.execute('INSERT INTO orders '
            '(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            ('previous-sell', (self.opening+timedelta(seconds=1)).isoformat(), SID,
             'moomoo_simulate', '3604', 'US.AAPL', 'SELL', 1, 99.99, 'FAILED', None))
        self.engine.db.commit()
        self.runner.tick(now=self.opening + timedelta(minutes=44))
        self.assertEqual(self.engine._get('best_execution', {}), old)
        self.assertEqual(self.engine._get('best_execution_schedule_history', []), [])
        self.assertEqual(FakeBroker.submissions, [])

    def test_hour_window_does_not_reopen_old_signal_with_a_submitted_order(self):
        old, _ = self.old_unsubmitted_buy_intent()
        self.engine.db.execute('INSERT INTO orders '
            '(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            ('old-terminal-attempt', (self.opening + timedelta(seconds=5)).isoformat(), SID,
             'moomoo_simulate', '3604', 'US.AAPL', 'BUY', 9, 100.01, 'FAILED', 'old-order'))
        self.engine.db.commit()
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=0, execution_window_seconds=3600, allow_partial_quotes=True)
        self.connect()
        self.runner._prepare(self.opening + timedelta(seconds=61))
        self.assertEqual(self.runner._execution_end(), self.opening + timedelta(seconds=60))
        self.tick_at(self.opening + timedelta(seconds=61))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(self.engine._get('best_execution', {}), old)
        self.assertEqual(FakeBroker.submissions, [])

    def expired_partial_dna_signal(self):
        """The old noon window filled DNA 88, while AAPL lacked a usable quote."""
        self.source.rows = [
            {'code': 'US.DNA', 'target_weight': .1},
            {'code': 'US.AAPL', 'target_weight': .1},
        ]
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        FakeBroker.market_prices = {'US.DNA': 11.25}
        FakeBroker.quote_errors = {'US.AAPL': 'quote source stale'}
        original_snapshot_partial = FakeBroker.snapshot_partial

        def dna_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            if 'US.DNA' in snapshot['quotes']:
                snapshot['quotes']['US.DNA'].update(price=11.245, bid=11.24, ask=11.25)
            return snapshot

        with patch.object(FakeBroker, 'snapshot_partial', dna_quote):
            self.tick_at(noon + timedelta(seconds=1))
            self.tick_at(noon + timedelta(seconds=2))
        expected_qty = int((.1 * self.runner.budget) // (11.25 * 1.005 * 1.03))
        self.assertEqual([(row['code'], row['qty']) for row in FakeBroker.submissions],
                         [('US.DNA', expected_qty)])
        self.assertEqual(FakeBroker.submissions[0]['order_type'], 'MARKET')
        self.assertEqual(self.engine.state()['orders'][0]['fill_qty'], expected_qty)
        self.assertEqual(self.engine._get('best_execution', {})['target_quantities']['US.DNA'], expected_qty)
        frozen_plan = deepcopy(self.engine._get('best_plan', None))
        self.tick_at(noon + timedelta(seconds=600))
        self.assertEqual(self.runner.status, 'PARTIALLY_EXECUTED')
        self.assertEqual(len(FakeBroker.submissions), 1)
        return noon, frozen_plan

    def authorize_same_day_catchup(self, noon, *, now=None, deadline=None, account_id='3604', execution_date='2026-09-28'):
        was_running = not self.runner.stop_event.is_set()
        self.runner.stop()
        try:
            return self.runner.authorize_catchup(
                execution_date=execution_date,
                deadline_utc=(deadline or noon + timedelta(hours=3)).isoformat(),
                account_id=account_id,
                now=now or noon + timedelta(seconds=601))
        finally:
            if was_running:
                self.engine.cancel_step.clear()
                self.runner.stop_event.clear()

    def test_explicit_same_day_catchup_buys_only_unfilled_code_at_fresh_price(self):
        noon, frozen_plan = self.expired_partial_dna_signal()
        FakeBroker.quote_errors.clear()
        # Changing the ordinary policy must not itself revive an already attempted signal.
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=150, execution_window_seconds=3600, allow_partial_quotes=True)
        self.connect()
        self.tick_at(noon + timedelta(seconds=601))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA'])
        self.authorize_same_day_catchup(noon)

        original_snapshot_partial = FakeBroker.snapshot_partial
        def current_quote(broker, codes):
            snapshot = original_snapshot_partial(broker, codes)
            if 'US.AAPL' in snapshot['quotes']:
                snapshot['quotes']['US.AAPL'].update(price=100.02, bid=100.01, ask=100.03)
            return snapshot

        with patch.object(FakeBroker, 'snapshot_partial', current_quote):
            self.tick_at(noon + timedelta(seconds=602))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA', 'US.AAPL'])
        self.assertEqual(FakeBroker.submissions[-1]['limit_price'], 100.03)
        self.tick_at(noon + timedelta(seconds=603))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA', 'US.AAPL'])
        dna = next(row for row in self.engine.state()['orders'] if row['code'] == 'US.DNA')
        self.assertEqual(dna['fill_qty'],
                         self.engine._get('best_execution', {})['target_quantities']['US.DNA'])
        self.assertEqual(self.engine._get('best_plan', None), frozen_plan)

    def test_catchup_rejects_wrong_trading_day_account_or_deadline(self):
        noon, _ = self.expired_partial_dna_signal()
        cases = (
            dict(execution_date='2026-09-29'),
            dict(account_id='different-sim-account'),
            dict(deadline=noon + timedelta(hours=5)),  # after the NY market close
            dict(deadline=noon + timedelta(seconds=600)),  # already expired
        )
        for override in cases:
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.authorize_same_day_catchup(noon, **override)
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA'])

    def test_catchup_deadline_stops_even_after_restart_with_fresh_quote(self):
        noon, _ = self.expired_partial_dna_signal()
        cutoff = noon + timedelta(seconds=660)
        self.authorize_same_day_catchup(noon, deadline=cutoff)
        self.tick_at(cutoff - timedelta(seconds=1))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA'])
        FakeBroker.quote_errors.clear()
        self.tick_at(cutoff)
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.connect()
        self.tick_at(cutoff + timedelta(seconds=1))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA'])

    def test_catchup_submitted_order_is_idempotent_across_restart(self):
        noon, _ = self.expired_partial_dna_signal()
        self.authorize_same_day_catchup(noon)
        FakeBroker.quote_errors.clear()
        self.tick_at(noon + timedelta(seconds=602))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA', 'US.AAPL'])
        self.tick_at(noon + timedelta(seconds=603))
        self.assertEqual(next(row for row in self.engine.state()['orders'] if row['code'] == 'US.AAPL')['status'], 'FILLED_ALL')
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.connect()
        self.tick_at(noon + timedelta(seconds=604))
        self.tick_at(noon + timedelta(seconds=605))
        self.assertEqual([row['code'] for row in FakeBroker.submissions], ['US.DNA', 'US.AAPL'])
        self.assertEqual(len(self.engine.state()['orders']), 2)

    def test_catchup_refuses_pending_or_unknown_original_broker_order(self):
        self.partial_runner(delay=150)
        noon = self.opening + timedelta(minutes=150)
        with patch.object(FakeBroker, 'submit', self.submit_without_fill):
            self.tick_at(noon + timedelta(seconds=1))
        self.assertEqual(self.engine.state()['orders'][0]['status'], 'PENDING_RECONCILE')
        with self.assertRaises(ValueError):
            self.authorize_same_day_catchup(noon)
        self.engine.db.execute("UPDATE orders SET status='UNKNOWN'")
        self.engine.db.commit()
        with self.assertRaises(ValueError):
            self.authorize_same_day_catchup(noon)
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_changed_delay_does_not_reset_done_signal_or_wrong_source(self):
        old, _ = self.old_unsubmitted_buy_intent()
        done = {**old, 'phase': 'DONE'}
        self.engine._set('best_execution', done)
        self.runner.tick(now=self.opening + timedelta(minutes=44))
        self.assertEqual(self.engine._get('best_execution', {}), done)
        bad = {**old, 'manifest': {**old['manifest'], 'source': json.dumps({
            **json.loads(old['manifest']['source']), 'source_hash': 'wrong-source'})}}
        self.engine._set('best_execution', bad)
        with self.assertRaisesRegex(ValueError, '冻结信号不一致'):
            self.runner.tick(now=self.opening + timedelta(minutes=44))
        self.assertEqual(self.engine._get('best_execution', {}), bad)
        self.assertEqual(self.engine._get('best_execution_schedule_history', []), [])
        self.assertEqual(FakeBroker.submissions, [])

    def test_next_expected_execution_uses_current_delayed_window_before_expiry(self):
        self.delayed_runner()
        self.connect()
        self.runner._prepare(self.opening + timedelta(minutes=44))
        self.assertIsNotNone(self.runner.plan)
        tomorrow = self.opening + timedelta(days=1)
        self.runner.metadata = {**self.source.status(), 'next_expected_open_utc': tomorrow.isoformat()}
        self.runner._now = lambda: self.opening + timedelta(minutes=44)
        self.assertEqual(self.runner.state()['next_expected_execution_utc'],
                         (self.opening + timedelta(minutes=45)).isoformat())
        self.runner._now = lambda: self.opening + timedelta(minutes=46)
        self.assertEqual(self.runner.state()['next_expected_execution_utc'],
                         (tomorrow + timedelta(minutes=45)).isoformat())

    def seed_close_error(self, error='QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO'):
        self.runner.last_error = error
        self.engine._set('best_last_error', error)

    def test_fresh_prepare_recovers_only_verified_close_source_error(self):
        self.connect()
        self.seed_close_error()
        self.runner._prepare(self.opening - timedelta(minutes=1))
        self.assertEqual(self.runner.last_error, '')
        self.assertEqual(self.engine._get('best_last_error', None), '')
        self.assertTrue(self.engine._get('best_plan', None))
        self.assertEqual(self.engine.state()['orders'], [])
        events = self.engine.db.execute("SELECT detail FROM audit WHERE event='SOURCE_PREPARATION_RECOVERED'").fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0][0])['previous_error'], 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO')

    def test_prepare_preserves_active_error_and_durable_error_mismatch(self):
        self.connect()
        for error in ('US.FICO 报价过期', '模拟委托结果未知', 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:',
                      'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO; UNKNOWN'):
            with self.subTest(error=error):
                self.engine._set('best_plan', None)
                self.seed_close_error(error)
                self.runner._prepare(self.opening - timedelta(minutes=1))
                self.assertEqual(self.runner.last_error, error)
                self.assertEqual(self.engine._get('best_last_error', ''), error)
        self.engine._set('best_plan', None)
        self.seed_close_error()
        self.engine._set('best_last_error', '最新模拟委托结果未知')
        self.runner._prepare(self.opening - timedelta(minutes=1))
        self.assertEqual(self.runner.last_error, 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO')
        self.assertEqual(self.engine._get('best_last_error', ''), '最新模拟委托结果未知')
        self.assertEqual(self.engine.state()['orders'], [])

    def test_failed_or_blocked_fresh_prepare_cannot_clear_source_error(self):
        self.connect()
        error = 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO'
        load = self.source.load
        for status, gaps in [('BLOCKED', []), ('READY', ['missing'])]:
            with self.subTest(status=status):
                self.engine._set('best_plan', None)
                self.seed_close_error(error)
                with patch.object(self.source, 'load', side_effect=lambda states, now=None:
                                  {**load(states, now), 'status': status, 'data_gaps': gaps}):
                    self.runner._prepare(self.opening - timedelta(minutes=1))
                self.assertEqual(self.runner.last_error, error)
                self.assertEqual(self.engine._get('best_last_error', ''), error)
        self.engine._set('best_plan', None)
        self.seed_close_error(error)
        with patch.object(self.source, 'close_states', side_effect=ValueError(error)):
            with self.assertRaisesRegex(ValueError, 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED'):
                self.runner._prepare(self.opening - timedelta(minutes=1))
        self.assertEqual(self.runner.last_error, error)

    def test_saved_plan_recovery_revalidates_closes_once_without_changing_frozen_state(self):
        self.connect()
        status = self.source.status
        close_states = self.source.close_states
        refs = {'report': {'path': 'immutable-report', 'sha256': 'a' * 64}}
        def checked_status(now=None):
            return {**status(now), 'source_refs': deepcopy(refs)}
        def checked_closes(books, signal_date):
            states = close_states(books, signal_date)
            states[SID]['source_refs'] = deepcopy(refs)
            return states
        with patch.object(self.source, 'status', side_effect=checked_status), \
             patch.object(self.source, 'close_states', side_effect=checked_closes):
            self.runner._prepare(self.opening - timedelta(minutes=1))
            saved = self.engine._get('best_plan', None)
            execution = {'signal_date': '2026-09-24', 'phase': 'DONE', 'processed_codes': ['US.AAPL']}
            self.engine._set('best_execution', execution)
            self.seed_close_error()
            with patch.object(self.source, 'load', side_effect=AssertionError('must retain original plan')):
                self.runner._prepare(self.opening - timedelta(minutes=1))
                count = len([call for call in self.source.calls if isinstance(call, tuple) and call[0] == 'close_states'])
                self.runner._prepare(self.opening - timedelta(minutes=1))
            self.assertEqual(len([call for call in self.source.calls if isinstance(call, tuple) and call[0] == 'close_states']), count)
            self.assertEqual(count, 2)
            self.assertEqual(self.runner.last_error, '')
            self.assertEqual(self.engine._get('best_plan', None), saved)
            self.assertEqual(self.engine._get('best_execution', {}), execution)
            self.assertEqual(FakeBroker.submissions, [])

    def test_saved_plan_has_no_implicit_error_recovery_from_status_alone(self):
        self.connect()
        self.runner._prepare(self.opening - timedelta(minutes=1))
        saved = self.engine._get('best_plan', None)
        self.seed_close_error()
        with patch.object(self.source, 'close_states', side_effect=AssertionError('unbound cached source')):
            self.runner._prepare(self.opening - timedelta(minutes=1))
        self.assertEqual(self.runner.last_error, 'QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO')
        self.assertEqual(self.engine._get('best_plan', None), saved)

    def test_skipped_source_dates_are_derived_only_from_the_original_batch(self):
        signal, execution = '2026-09-25', '2026-09-28'
        old = {'signal_date': signal, 'skipped': [{'code': 'US.AAPL', 'reason': '旧报价过期'}],
               'manifest': {'source': json.dumps({'kind': 'AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN',
                           'signal_date': signal, 'next_open_utc': self.opening.isoformat(),
                           'execution_time_utc': (self.opening + timedelta(minutes=45)).isoformat()})}}
        self.engine._set('best_execution', old)
        self.runner.plan = {'signal_date': '2026-09-28', 'execution_date': '2026-09-29', 'rows': []}
        view = self.runner.state()
        self.assertEqual(view['skipped'], old['skipped'])
        self.assertEqual(view['skipped_source'], {'signal_date': signal, 'execution_date': execution})
        self.assertEqual(self.engine._get('best_execution', None), old)
        self.assertEqual(BestBroker._skipped_source({'signal_date': signal, 'execution_date': execution}),
                         {'signal_date': signal, 'execution_date': execution})
        for state in ({'signal_date': signal}, {**old, 'execution_date': '2026-09-29'},
                      {**old, 'manifest': {'source': '{}'}},
                      {**old, 'manifest': {'source': json.dumps({'kind': 'AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN',
                          'signal_date': signal, 'next_open_utc': '2026-09-28T13:30:00'})}},
                      {'signal_date': signal, 'execution_date': signal},
                      {'signal_date': '2026-9-25', 'execution_date': execution}):
            with self.subTest(state=state):
                self.assertIsNone(BestBroker._skipped_source(state))

    def test_worker_cools_down_failed_account_reads_without_looping_or_orders(self):
        from unittest.mock import Mock
        class StopAfterWait:
            stopped = False
            waits = []
            def is_set(self):
                return self.stopped
            def set(self):
                self.stopped = True
            def wait(self, seconds):
                self.waits.append(seconds)
                self.set()
                return True
        for error, delay in ((BrokerReadError('accinfo_query 请求未成功'), 30),
                             (BrokerError('US.AAPL 报价过期'), 1)):
            with self.subTest(delay=delay):
                stop = StopAfterWait()
                stop.waits = []
                self.runner.stop_event = stop
                self.runner.tick = Mock(side_effect=error)
                self.runner._run()
                self.runner.tick.assert_called_once()
                self.assertEqual(stop.waits, [delay])
                self.assertEqual(self.engine.state()['orders'], [])
                self.assertEqual(FakeBroker.submissions, [])
        audits = self.engine.db.execute("SELECT detail FROM audit WHERE event='BROKER_READ_COOLDOWN'").fetchall()
        self.assertEqual(len(audits), 1)
        audit = json.loads(audits[0][0])
        self.assertEqual(audit['retry_after_seconds'], 30)
        self.assertEqual(audit['failed_operation'], 'READ_ONLY_QUERY')
        self.assertFalse(audit['automatic_order_retry'])
        recovered = BestBroker(self.temp.name, self.source, engine=self.engine)
        self.assertEqual(recovered.state()['last_error'], 'US.AAPL 报价过期')


    def full_reset_fixture(self):
        self.partial_runner(delay=0)
        old_time = "2026-09-24T13:30:00+00:00"
        for code, qty, price in (("US.AAPL", 5, 90.0), ("US.MSFT", 3, 100.0)):
            identity = "pre-reset-" + code
            self.engine.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (identity, old_time, SID, "moomoo_simulate", self.engine.account_id,
                 code, "BUY", qty, price, "FILLED_ALL", identity, "MARKET"))
            self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",
                (identity, json.dumps({"fill_qty": qty, "fill_price": price, "status": "FILLED_ALL"})))
        self.engine.db.commit()
        FakeBroker.positions = {"US.AAPL": 5, "US.MSFT": 3}
        FakeBroker.cash = 1000000.0 - 750
        self.runner.stop()
        old_plan = {"metadata": self.source.status(self.opening), "plan": {"rows": [], "old": True}}
        self.engine._set("best_plan", old_plan)
        self.engine._set("best_execution", {"signal_date": "2026-09-24", "phase": "DONE"})
        request = dict(reset_id="synthetic_reset_1", requested_at="2026-09-27T12:00:00+00:00",
            strategy_ids=[SID, "HGB_FACTOR_5"], signal_date="2026-09-25",
            expected_policy_id="HGB_TOP20_RISK_R1", expected_package_sha256="a" * 64)
        source_status = self.source.status
        refs = {key: {"sha256": "a" * 64} for key in ("frozen_calendar", "session_hours_rules",
            "daily/report.json", "selected/package.json", "selected/current_report.json", "current/features.parquet")}
        self.source.status = lambda now=None: {**source_status(now), "source_date": "2026-09-25",
            "ready": True, "data_gaps": [], "source_refs": deepcopy(refs)}
        def reset_load(states=None, now=None, reset_request=None):
            self.assertIsNone(states)
            self.assertEqual(reset_request["strategy_ids"], [SID])
            return {**self.source.status(now), "source_refs": deepcopy(refs),
                "plans": {SID: {"strategy_id": SID, "signal_date": "2026-09-25", "execution_date": "2026-09-28",
                    "policy_id": "HGB_TOP20_RISK_R1", "account_basis": "USER_REQUESTED_POST_LIQUIDATION_CASH_START",
                    "target_origin_account_basis": "CASH_START", "valuation_basis": "POST_LIQUIDATION_ASSUMPTION",
                    "execution_condition": "ACCOUNT_FLAT_AFTER_CONFIRMED_LIQUIDATION", "cash_weight_before": 1,
                    "rows": [{"code": "US.AAPL", "target_weight": .1}, {"code": "US.MSFT", "target_weight": .08}],
                    "target_cash_weight": .82, "model_fit_calls": 0,
                    "source_refs": deepcopy(refs)}}}
        self.source.load = reset_load
        return request, old_plan

    def reset_connect(self):
        self.connect()
        self.engine.cancel_step.clear()

    def prepare_reset(self):
        request, old = self.full_reset_fixture()
        self.runner.prepare_full_liquidation_reset(request, now=self.opening - timedelta(days=1))
        return request, old

    def test_full_reset_sunday_preparation_preserves_old_fills_and_sends_nothing(self):
        request, old = self.prepare_reset()
        frozen = self.engine._get("best_plan", None)
        self.assertEqual(frozen["plan"]["reset_id"], request["reset_id"])
        self.assertEqual(self.engine._get("best_reset_archive", {})[request["reset_id"]]["best_plan"], old)
        self.assertEqual(len(self.engine.state()["orders"]), 2)
        self.assertEqual(FakeBroker.submissions, [])
        self.assertIsNone(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])
        self.assertTrue(all(not include_quotes for _, include_quotes in FakeBroker.snapshot_calls))
        self.reset_connect()
        self.tick_at(self.opening - timedelta(hours=1))
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.runner.status, "WAITING_OPEN")

    def test_full_reset_sells_every_share_before_buy_and_records_actual_cash_once(self):
        request, old = self.prepare_reset()
        self.reset_connect()
        for offset in range(8):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        submissions = [(row["code"], row["side"], row["qty"]) for row in FakeBroker.submissions]
        self.assertEqual(submissions[:2], [("US.AAPL", "SELL", 5), ("US.MSFT", "SELL", 3)])
        self.assertEqual([side for _, side, _ in submissions[2:]], ["BUY", "BUY"])
        reset = self.engine._get("best_full_liquidation_reset", {})
        self.assertEqual(reset["stage"], "COMPLETED")
        baseline = deepcopy(reset["post_liquidation_baseline"])
        self.assertAlmostEqual(baseline["cash"], 10049.92, places=6)
        self.assertNotEqual(baseline["cash"], 10000)
        self.assertEqual(baseline["positions"], {})
        self.assertEqual(len(self.engine.state()["orders"]), 6)
        self.tick_at(self.opening + timedelta(seconds=12))
        self.assertEqual(len(FakeBroker.submissions), 4)
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"], baseline)
        self.assertEqual(self.engine._get("best_capital", {})["unused_cash"], 990000)

    def test_full_reset_missing_sell_quote_blocks_all_buys_and_baseline(self):
        self.prepare_reset()
        FakeBroker.quote_errors = {"US.MSFT": "no qualified quote"}
        self.reset_connect()
        for offset in range(4):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        self.assertEqual([(row["code"], row["side"]) for row in FakeBroker.submissions], [("US.AAPL", "SELL")])
        self.assertEqual(FakeBroker.positions.get("US.MSFT"), 3)
        self.assertIsNone(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])
        self.assertEqual(self.engine._get("best_execution", {})["phase"], "SELL")

    def test_full_reset_terminal_unfilled_sell_never_transitions_to_buy(self):
        self.prepare_reset()
        FakeBroker.quote_errors = {"US.MSFT": "no qualified quote"}
        self.reset_connect()
        with patch.object(FakeBroker, "submit", self.submit_without_fill):
            self.tick_at(self.opening + timedelta(seconds=1))
        pending = self.engine._pending()[0]
        FakeBroker.reconcile_result = {"order_id": pending["order_id"], "status": "CANCELLED_ALL",
                                       "dealt_qty": 0, "dealt_avg_price": None}
        self.tick_at(self.opening + timedelta(seconds=2))
        self.tick_at(self.opening + timedelta(seconds=3))
        self.assertTrue(all(row["side"] == "SELL" for row in FakeBroker.submissions))
        self.assertIsNone(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])

    def test_full_reset_partial_pending_sell_never_creates_buy_or_baseline(self):
        self.prepare_reset()
        FakeBroker.quote_errors = {"US.MSFT": "no qualified quote"}
        self.reset_connect()
        with patch.object(FakeBroker, "submit", self.submit_without_fill):
            self.tick_at(self.opening + timedelta(seconds=1))
        pending = self.engine._pending()[0]
        FakeBroker.positions["US.AAPL"] = 4
        FakeBroker.cash += 99.99
        FakeBroker.reconcile_result = {"order_id": pending["order_id"], "status": "FILLED_PART",
                                       "dealt_qty": 1, "dealt_avg_price": 99.99}
        self.tick_at(self.opening + timedelta(seconds=2))
        self.assertEqual(len(FakeBroker.submissions), 1)
        self.assertEqual(FakeBroker.submissions[0]["side"], "SELL")
        self.assertTrue(self.engine._pending())
        self.assertIsNone(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])

    def test_full_reset_same_clock_sell_and_rebuy_use_distinct_order_identity(self):
        self.prepare_reset()
        self.reset_connect()
        now = self.opening + timedelta(seconds=1)
        for _ in range(7):
            self.tick_at(now)
        rows = self.engine.state()["orders"]
        reset_rows = [row for row in rows if row["created_at"] == now.isoformat()]
        self.assertEqual(len(reset_rows), 4)
        self.assertEqual(len({row["id"] for row in reset_rows}), 4)
        self.assertEqual(sorted((row["code"], row["side"]) for row in reset_rows),
            [("US.AAPL", "BUY"), ("US.AAPL", "SELL"), ("US.MSFT", "BUY"), ("US.MSFT", "SELL")])
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["stage"], "COMPLETED")

    def test_full_reset_same_request_is_idempotent_and_changed_request_fails(self):
        request, _ = self.prepare_reset()
        archived = deepcopy(self.engine._get("best_reset_archive", {}))
        self.runner.prepare_full_liquidation_reset(request, now=self.opening - timedelta(hours=3))
        self.assertEqual(self.engine._get("best_reset_archive", {}), archived)
        changed = deepcopy(request)
        changed["expected_package_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "RESET_REQUEST_CHANGED"):
            self.runner.prepare_full_liquidation_reset(changed, now=self.opening - timedelta(hours=2))

    def test_full_reset_rejects_running_and_open_preparation_without_any_order(self):
        request, _ = self.full_reset_fixture()
        self.runner.stop_event.clear()
        with self.assertRaisesRegex(ValueError, "RESET_REQUIRES_STOPPED"):
            self.runner.prepare_full_liquidation_reset(request, now=self.opening - timedelta(days=1))
        self.runner.stop_event.set()
        with self.assertRaisesRegex(ValueError, "RESET_FROZEN_DIRECT_TARGET_BINDING"):
            self.runner.prepare_full_liquidation_reset(request, now=self.opening)
        self.assertEqual(FakeBroker.submissions, [])

    def test_full_reset_tampered_plan_source_binding_blocks_before_submission(self):
        self.prepare_reset()
        saved = self.engine._get("best_plan", None)
        saved["plan"]["target_cash_weight"] = .9
        self.engine._set("best_plan", saved)
        self.reset_connect()
        self.runner.prepared_at = 0
        with self.assertRaisesRegex(ValueError, "RESET_EXECUTION_BINDING_CHANGED"):
            self.tick_at(self.opening + timedelta(seconds=1))
        self.assertEqual(FakeBroker.submissions, [])

    def test_full_reset_restart_after_liquidation_keeps_baseline_and_sell_ids(self):
        self.prepare_reset()
        self.reset_connect()
        for offset in range(3):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        baseline = deepcopy(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])
        self.assertIsNotNone(baseline)
        sell_ids = [row["client_id"] for row in FakeBroker.submissions if row["side"] == "SELL"]
        self.engine.reconcile()  # Preserve its real BUY receipt before this clean restart.
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        self.reset_connect()
        for offset in range(3, 8):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        self.assertEqual([row["client_id"] for row in FakeBroker.submissions if row["side"] == "SELL"], sell_ids)
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"], baseline)
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["stage"], "COMPLETED")

    def test_full_reset_single_field_record_tampering_fails_before_any_order(self):
        self.prepare_reset()
        self.reset_connect()
        original = deepcopy(self.engine._get("best_full_liquidation_reset", {}))
        for field, value in (("stage", "INVALID"), ("stage", "REBUYING"), ("stage", "COMPLETED"),
                             ("policy_id", "RAW_TOP20_FROZEN_LEGACY"),
                             ("expected_package_sha256", "b" * 64), ("request_sha256", "b" * 64),
                             ("budget", 9999), ("account_id", "other-sim")):
            with self.subTest(field=field, value=value):
                changed = deepcopy(original)
                changed[field] = value
                self.engine._set("best_full_liquidation_reset", changed)
                self.runner.prepared_at = 0
                with self.assertRaises(ValueError):
                    self.tick_at(self.opening + timedelta(seconds=1))
                self.assertEqual(FakeBroker.submissions, [])
        self.engine._set("best_full_liquidation_reset", original)

    def test_full_reset_post_liquidation_crash_resumes_buy_without_another_sell(self):
        self.prepare_reset()
        self.reset_connect()
        self.tick_at(self.opening + timedelta(seconds=1))
        self.tick_at(self.opening + timedelta(seconds=2))
        original_partial = self.runner._partial_execution
        def crash_before_buy(now, phase, *args, **kwargs):
            if phase == "BUY":
                raise RuntimeError("synthetic crash after cash baseline")
            return original_partial(now, phase, *args, **kwargs)
        with patch.object(self.runner, "_partial_execution", side_effect=crash_before_buy):
            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                self.tick_at(self.opening + timedelta(seconds=3))
        baseline = deepcopy(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])
        self.assertEqual(self.engine._get("best_execution", {})["phase"], "SELL")
        self.assertFalse(any(FakeBroker.positions.values()))
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        self.reset_connect()
        for offset in range(4, 8):
            self.tick_at(self.opening + timedelta(seconds=offset))
        self.assertEqual([row["side"] for row in FakeBroker.submissions], ["SELL", "SELL", "BUY", "BUY"])
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"], baseline)
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["stage"], "COMPLETED")

    def test_full_reset_missing_buy_state_with_new_positions_never_reliquidates(self):
        self.prepare_reset()
        self.reset_connect()
        for offset in range(3):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        self.engine.reconcile()
        self.runner._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
        before = deepcopy(FakeBroker.submissions)
        for phase in (None, "SELL"):
            with self.subTest(phase=phase):
                self.engine._set("best_execution", {} if phase is None else {"signal_date": "2026-09-25", "phase": phase})
                self.runner.prepared_at = 0
                with self.assertRaisesRegex(ValueError, "RESET_(REBUY_STATE_MISSING_WITH_POSITIONS|EXECUTION_PHASE_MISMATCH)"):
                    self.tick_at(self.opening + timedelta(seconds=5))
                self.assertEqual(FakeBroker.submissions, before)

    def test_full_reset_completed_stage_must_match_done_execution(self):
        self.prepare_reset()
        self.reset_connect()
        for offset in range(7):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        completed = self.engine._get("best_full_liquidation_reset", {})
        self.assertEqual(completed["stage"], "COMPLETED")
        execution = self.engine._get("best_execution", {})
        execution["phase"] = "BUY"
        self.engine._set("best_execution", execution)
        before = deepcopy(FakeBroker.submissions)
        with self.assertRaisesRegex(ValueError, "RESET_EXECUTION_PHASE_MISMATCH"):
            self.tick_at(self.opening + timedelta(seconds=8))
        self.assertEqual(FakeBroker.submissions, before)

    def test_full_reset_nonascii_metadata_matches_core_frozen_hash(self):
        request, _ = self.full_reset_fixture()
        original_load = self.source.load
        def load_with_chinese_reason(*args, **kwargs):
            result = original_load(*args, **kwargs)
            result["reason"] = "已冻结目标，等待开盘清仓后重买"
            return result
        self.source.load = load_with_chinese_reason
        self.runner.prepare_full_liquidation_reset(request, now=self.opening - timedelta(days=1))
        self.reset_connect()
        self.tick_at(self.opening + timedelta(seconds=1))
        self.assertEqual(FakeBroker.submissions[0]["side"], "SELL")

    def test_full_reset_mutated_buy_targets_cannot_claim_completion(self):
        self.prepare_reset()
        self.reset_connect()
        for offset in range(3):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        self.engine.reconcile()
        self.runner._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
        execution = self.engine._get("best_execution", {})
        execution["original_target_cash_weight"] = .99
        self.engine._set("best_execution", execution)
        before = deepcopy(FakeBroker.submissions)
        with self.assertRaisesRegex(ValueError, "RESET_EXECUTION_PHASE_MISMATCH"):
            self.tick_at(self.opening + timedelta(seconds=5))
        self.assertEqual(FakeBroker.submissions, before)

    def test_full_reset_state_masks_actual_baseline_account_without_changing_database(self):
        self.prepare_reset()
        self.reset_connect()
        for offset in range(3):
            self.tick_at(self.opening + timedelta(seconds=offset + 1))
        persisted = deepcopy(self.engine._get("best_full_liquidation_reset", {}))
        self.assertEqual(persisted["post_liquidation_baseline"]["account_id"], self.engine.account_id)
        public = self.runner.state()
        baseline = public["full_liquidation_reset"]["post_liquidation_baseline"]
        self.assertEqual(baseline["account_id"], "****" + self.engine.account_id[-4:])
        baseline["cash"] = 1  # Public state has no shared nested reset object.
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {}), persisted)

    def cancellation_rows(self):
        return {table: [tuple(row) for row in self.engine.db.execute("SELECT * FROM " + table + " ORDER BY rowid")]
                for table in ("orders", "order_fills")}

    def test_cancel_unstarted_reset_preserves_positions_cash_orders_and_prior_archive(self):
        request, old = self.prepare_reset()
        before_rows, before_cash, before_positions = self.cancellation_rows(), FakeBroker.cash, deepcopy(FakeBroker.positions)
        capital = deepcopy(self.engine._get("best_capital", {}))
        reset = deepcopy(self.engine._get("best_full_liquidation_reset", {}))
        saved = deepcopy(self.engine._get("best_plan", {}))
        self.runner.last_error = "QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO"
        with patch.object(self.runner, "_connect", side_effect=AssertionError("cancel must not connect")), \
                patch.object(self.source, "status", side_effect=AssertionError("cancel must not read data")), \
                patch.object(self.source, "load", side_effect=AssertionError("cancel must not infer")), \
                patch.object(FakeBroker, "snapshot", side_effect=AssertionError("cancel must not query SDK")):
            result = self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(hours=1))
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(result["full_liquidation_reset"], {})
        self.assertIsNone(result["plan"])
        self.assertEqual(result["last_error"], "QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO")
        self.assertEqual(self.engine._get("best_full_liquidation_reset", None), {})
        self.assertIsNone(self.engine._get("best_plan", {}))
        self.assertEqual(self.engine._get("best_execution", None), {})
        self.assertEqual(self.cancellation_rows(), before_rows)
        self.assertEqual(self.engine._get("best_capital", {}), capital)
        self.assertEqual((FakeBroker.cash, FakeBroker.positions), (before_cash, before_positions))
        archive = self.engine._get("best_reset_archive", {})[request["reset_id"]]
        self.assertEqual(archive["best_plan"], old)
        self.assertEqual(archive["cancellation"]["full_liquidation_reset"], reset)
        self.assertEqual(archive["cancellation"]["best_plan"], saved)
        self.assertEqual(archive["cancellation"]["replacement_mode"], "EXISTING_POSITIONS_REBALANCE")
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='FULL_LIQUIDATION_RESET_CANCELLED'").fetchone()[0], 1)

    def test_cancelled_reset_reprepares_from_existing_positions_and_repeat_cannot_clear_normal_plan(self):
        request, _ = self.prepare_reset()
        self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(hours=1))
        actual = {}
        def actual_closes(books, signal_date):
            actual.update(deepcopy(books))
            return {SID: dict(weights={"AAPL": .05, "MSFT": .03}, cash_weight=.92,
                signal_date=signal_date, valuation_basis="SIGNAL_CLOSE")}
        def normal_load(states, now=None):
            self.assertEqual(states[SID]["weights"], {"AAPL": .05, "MSFT": .03})
            return {**self.source.status(now), "plans": {SID: dict(
                policy_id="HGB_TOP20_RISK_R1", account_basis="USER_SUPPLIED_SIGNAL_CLOSE_STATE",
                rows=[dict(code="US.AAPL", target_weight=.1), dict(code="US.MSFT", target_weight=.08)],
                target_cash_weight=.82, model_fit_calls=0)}}
        self.source.close_states, self.source.load = actual_closes, normal_load
        self.reset_connect()
        self.runner._prepare(self.opening - timedelta(minutes=30))
        self.assertEqual(actual[SID]["positions"], {"US.AAPL": 5, "US.MSFT": 3})
        self.assertEqual(self.runner.plan["account_basis"], "USER_SUPPLIED_SIGNAL_CLOSE_STATE")
        self.assertNotIn("reset_id", self.runner.plan)
        self.tick_at(self.opening + timedelta(seconds=1))
        self.assertEqual([row["side"] for row in FakeBroker.submissions], ["BUY"])
        self.assertGreater(FakeBroker.positions["US.AAPL"], 5)
        self.engine.reconcile()
        self.runner.stop()
        plan_before = deepcopy(self.engine._get("best_plan", None))
        archive_before = deepcopy(self.engine._get("best_reset_archive", {}))
        orders_before = self.cancellation_rows()
        self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening + timedelta(seconds=2))
        self.assertEqual(self.engine._get("best_plan", None), plan_before)
        self.assertEqual(self.engine._get("best_reset_archive", {}), archive_before)
        self.assertEqual(self.cancellation_rows(), orders_before)

    def test_cancel_unstarted_reset_after_restart_is_offline_and_idempotent(self):
        request, _ = self.prepare_reset()
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        self.assertEqual(self.engine.mode, "paper")
        self.assertIsNone(self.engine.broker)
        with patch.object(self.engine, "connect", side_effect=AssertionError("offline cancel must not connect")), \
                patch.object(self.source, "load", side_effect=AssertionError("offline cancel must not infer")):
            self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(hours=1))
        cancelled = deepcopy(self.engine._get("best_reset_archive", {}))
        self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(minutes=30))
        self.assertEqual(self.engine._get("best_reset_archive", {}), cancelled)
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.mode, "paper")

    def test_cancel_rejects_started_stage_pending_changed_identity_running_or_future_clock(self):
        request, _ = self.prepare_reset()
        record = deepcopy(self.engine._get("best_full_liquidation_reset", {}))
        archive = deepcopy(self.engine._get("best_reset_archive", {}))
        saved = deepcopy(self.engine._get("best_plan", {}))
        for case in ("wrong_id", "running", "worker", "engine_worker", "halted", "pending", "stage", "baseline", "account", "hash", "clock"):
            with self.subTest(case=case):
                self.engine._set("best_full_liquidation_reset", deepcopy(record))
                self.runner.stop_event.set()
                self.runner.worker, self.engine.worker = None, None
                self.engine.halt_event.clear()
                now, reset_id = self.opening - timedelta(hours=1), request["reset_id"]
                if case == "wrong_id": reset_id = "another-reset"
                if case == "running": self.runner.stop_event.clear()
                if case == "worker": self.runner.worker = type("Running", (), {"is_alive": lambda self: True})()
                if case == "engine_worker": self.engine.worker = type("Running", (), {"is_alive": lambda self: True})()
                if case == "halted": self.engine.halt_event.set()
                if case == "clock": now = self.opening - timedelta(days=2)
                if case in {"stage", "baseline", "account", "hash"}:
                    changed = deepcopy(record)
                    if case == "stage": changed["stage"] = "REBUYING"
                    if case == "baseline": changed["post_liquidation_baseline"] = {}
                    if case == "account": changed["account_id"] = "another-account"
                    if case == "hash": changed["plan_sha256"] = "0" * 64
                    self.engine._set("best_full_liquidation_reset", changed)
                if case == "pending":
                    self.engine.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("cancel-unknown", now.isoformat(), SID, "moomoo_simulate", "3604", "US.AAPL", "SELL", 5, 99.99, "UNKNOWN", None, "MARKET"))
                    self.engine.db.commit()
                try:
                    with self.assertRaises(ValueError): self.runner.cancel_full_liquidation_reset(reset_id, now=now)
                    self.assertEqual(self.engine._get("best_reset_archive", {}), archive)
                    self.assertEqual(self.engine._get("best_plan", {}), saved)
                    self.assertEqual(FakeBroker.submissions, [])
                finally:
                    if case == "pending":
                        self.engine.db.execute("DELETE FROM orders WHERE id='cancel-unknown'")
                        self.engine.db.commit()
                    self.runner.stop_event.set(); self.runner.worker=None; self.engine.worker=None; self.engine.halt_event.clear()
        self.engine._set("best_full_liquidation_reset", record)

    def test_cancel_rejects_terminal_reset_sell_even_without_pending_order(self):
        request, _ = self.prepare_reset()
        FakeBroker.quote_errors = {"US.MSFT": "missing quote"}
        self.reset_connect()
        self.tick_at(self.opening + timedelta(seconds=1))
        self.engine.reconcile()
        self.runner.stop()
        self.assertFalse(self.engine._pending())
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {})["stage"], "ARMED")
        before = self.cancellation_rows()
        with self.assertRaisesRegex(ValueError, "RESET_CANCEL_SUBMITTED_ORDER_EXISTS"):
            self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening + timedelta(seconds=2))
        self.assertEqual(self.cancellation_rows(), before)
        self.assertTrue(self.engine._get("best_full_liquidation_reset", {}))

    def test_cancel_keeps_definitely_unsent_intention_and_archives_its_execution(self):
        request, _ = self.prepare_reset()
        self.reset_connect()
        self.engine.broker.before_send_error = BrokerOrderNotSent("synthetic definitely unsent")
        self.tick_at(self.opening + timedelta(seconds=1))
        self.runner.stop()
        orders = self.cancellation_rows()
        self.assertEqual([row["status"] for row in self.engine.state()["orders"] if row["id"] not in
                         {"pre-reset-US.AAPL", "pre-reset-US.MSFT"}], ["CANCELLED_BEFORE_SEND"])
        result = self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening + timedelta(seconds=2))
        self.assertEqual(result["full_liquidation_reset"], {})
        self.assertEqual(self.cancellation_rows(), orders)
        self.assertEqual(FakeBroker.positions, {"US.AAPL": 5, "US.MSFT": 3})
        self.assertTrue(self.engine._get("best_reset_archive", {})[request["reset_id"]]["cancellation"]["best_execution"])

    def test_cancel_database_failure_rolls_back_audit_and_all_active_state(self):
        request, _ = self.prepare_reset()
        reset, saved = deepcopy(self.engine._get("best_full_liquidation_reset", {})), deepcopy(self.engine._get("best_plan", {}))
        archive = deepcopy(self.engine._get("best_reset_archive", {}))
        self.engine.db.execute("CREATE TRIGGER synthetic_cancel_failure BEFORE INSERT ON settings WHEN NEW.key='best_full_liquidation_reset' BEGIN SELECT RAISE(ABORT,'synthetic cancellation interruption'); END")
        self.engine.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic cancellation interruption"):
            self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(hours=1))
        self.assertEqual(self.engine._get("best_full_liquidation_reset", {}), reset)
        self.assertEqual(self.engine._get("best_plan", {}), saved)
        self.assertEqual(self.engine._get("best_reset_archive", {}), archive)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='FULL_LIQUIDATION_RESET_CANCELLED'").fetchone()[0], 0)
        self.engine.db.execute("DROP TRIGGER synthetic_cancel_failure")
        self.engine.db.commit()
        self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(hours=1))
        self.assertEqual(self.engine._get("best_full_liquidation_reset", None), {})

    def published_rebalance_fixture(self, *, overweight=False):
        request, _ = self.full_reset_fixture()
        if overweight:
            self.engine.db.execute("UPDATE orders SET qty=20 WHERE id='pre-reset-US.AAPL'")
            self.engine.db.execute("UPDATE order_fills SET payload=? WHERE id='pre-reset-US.AAPL'",
                (json.dumps(dict(fill_qty=20, fill_price=90.0, status="FILLED_ALL")),))
            self.engine.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                "old-exit", "2026-09-24T13:30:00+00:00", SID, "moomoo_simulate", self.engine.account_id,
                "US.META", "BUY", 4, 100.0, "FILLED_ALL", "old-exit", "MARKET"))
            self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)", (
                "old-exit", json.dumps(dict(fill_qty=4, fill_price=100.0, status="FILLED_ALL"))))
            self.engine.db.commit()
            FakeBroker.positions = {"US.AAPL": 20, "US.MSFT": 3, "US.META": 4}
            FakeBroker.cash -= 1750
        self.runner.prepare_full_liquidation_reset(request, now=self.opening - timedelta(days=1))
        self.runner.cancel_full_liquidation_reset(request["reset_id"], now=self.opening - timedelta(hours=2))
        return request

    def test_published_target_preparation_is_offline_transparent_and_preserves_all_old_account_records(self):
        request = self.published_rebalance_fixture()
        rows, capital = self.cancellation_rows(), deepcopy(self.engine._get("best_capital", {}))
        old_archive = deepcopy(self.engine._get("best_reset_archive", {}))
        actual = FakeBroker.cash, deepcopy(FakeBroker.positions)
        self.runner.last_error = "QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO"
        self.engine._set("best_last_error", self.runner.last_error)
        with patch.object(self.runner, "_connect", side_effect=AssertionError("must not connect")), \
                patch.object(self.source, "close_states", side_effect=AssertionError("must not fake old close")), \
                patch.object(self.source, "load", side_effect=AssertionError("must not infer")), \
                patch.object(FakeBroker, "snapshot", side_effect=AssertionError("must not use SDK")):
            result = self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        plan = result["plan"]
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(plan["account_basis"], "USER_REQUESTED_PUBLISHED_TARGET_REBALANCE")
        self.assertEqual(plan["valuation_basis"], "PUBLISHED_TARGET_WEIGHTS")
        self.assertEqual(plan["target_origin_account_basis"], "CASH_START")
        self.assertEqual(plan["execution_mode"], "REBALANCE_EXISTING_POSITIONS")
        for key in ("reset_id", "requested_at", "reset_request", "reset_request_sha256", "assumed_states",
                    "execution_condition", "cash_weight_before"):
            self.assertNotIn(key, plan)
            self.assertNotIn(key, self.runner.metadata)
        self.assertEqual(self.cancellation_rows(), rows)
        self.assertEqual(self.engine._get("best_capital", {}), capital)
        self.assertEqual((FakeBroker.cash, FakeBroker.positions), actual)
        self.assertIsNone(self.engine._get("best_plan", {})["close_state"])
        self.assertEqual(self.engine._get("best_full_liquidation_reset", None), {})
        entry = self.engine._get("best_reset_archive", {})[request["reset_id"]]
        receipt = entry["cancellation"].pop("published_target_rebalance")
        self.assertEqual(entry, old_archive[request["reset_id"]])
        self.assertEqual(receipt["previous_last_error"], "QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:FICO")
        self.assertEqual(receipt["order_submissions"], 0)
        self.assertEqual(result["last_error"], "")
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_REBALANCE_PREPARED'").fetchone()[0], 1)

    def test_published_target_rebalance_keeps_overlap_sells_only_excess_and_liquidates_zero_target(self):
        request = self.published_rebalance_fixture(overweight=True)
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        self.reset_connect()
        with patch.object(self.source, "close_states", side_effect=AssertionError("no old close required")), \
                patch.object(self.source, "load", side_effect=AssertionError("no new solve required")):
            for offset in range(8):
                self.tick_at(self.opening + timedelta(seconds=offset + 1))
        orders = [(o["code"], o["side"], o["qty"]) for o in FakeBroker.submissions]
        self.assertEqual(orders[:2], [("US.AAPL", "SELL", 10), ("US.META", "SELL", 4)])
        self.assertGreater(FakeBroker.positions["US.AAPL"], 0)
        self.assertEqual(FakeBroker.positions["US.META"], 0)
        self.assertTrue(all(code == "US.MSFT" and side == "BUY" for code, side, _ in orders[2:]))
        self.assertGreater(FakeBroker.positions["US.MSFT"], 3)
        self.assertEqual(self.engine._get("best_full_liquidation_reset", None), {})
        manifest = json.loads(self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (SID,)).fetchone()[0])
        source = json.loads(manifest["source"])
        self.assertNotIn("reset_id", source)
        self.assertNotIn("execution_mode", source)

    def test_published_target_rejects_current_dates_readiness_and_every_source_reference_change(self):
        request = self.published_rebalance_fixture()
        status = deepcopy(self.source.status())
        before = deepcopy(self.engine._get("best_reset_archive", {}))
        cases = list(status["source_refs"]) + ["status", "ready", "source_date", "signal_date", "execution_date",
                  "next_open_utc", "signal_close_utc", "data_gaps", "missing_ref"]
        for case in cases:
            with self.subTest(case=case):
                changed = deepcopy(status)
                if case in changed["source_refs"]: changed["source_refs"][case]["sha256"] = "b" * 64
                elif case == "missing_ref": changed["source_refs"].pop("frozen_calendar")
                elif case == "status": changed["status"] = "WAITING_SOURCE"
                elif case == "ready": changed["ready"] = False
                elif case == "data_gaps": changed["data_gaps"] = ["missing"]
                else: changed[case] = "changed"
                with patch.object(self.source, "status", return_value=changed):
                    with self.assertRaisesRegex(ValueError, "PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED"):
                        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
                self.assertIsNone(self.engine._get("best_plan", {}))
                self.assertEqual(self.engine._get("best_reset_archive", {}), before)
                self.assertEqual(FakeBroker.submissions, [])

    def test_published_target_rejects_frozen_plan_hash_account_budget_and_started_batches(self):
        request = self.published_rebalance_fixture()
        archive = deepcopy(self.engine._get("best_reset_archive", {}))
        capital = deepcopy(self.engine._get("best_capital", {}))
        for case in ("plan", "metadata", "account", "capital", "running", "pending", "execution", "active_reset", "early", "expired"):
            with self.subTest(case=case):
                self.engine._set("best_reset_archive", deepcopy(archive))
                self.engine._set("best_capital", deepcopy(capital))
                self.engine._set("best_execution", {})
                self.engine._set("best_full_liquidation_reset", {})
                self.runner.stop_event.set()
                clock = self.opening - timedelta(hours=1)
                changed = deepcopy(archive)
                frozen = changed[request["reset_id"]]["cancellation"]
                if case == "plan": frozen["best_plan"]["plan"]["rows"][0]["target_weight"] = .09
                if case == "metadata": frozen["best_plan"]["metadata"]["next_open_utc"] = "2026-09-29T13:30:00+00:00"
                if case == "account": frozen["full_liquidation_reset"]["account_id"] = "different"
                if case == "capital": self.engine._set("best_capital", {**capital, "budget": 20000})
                if case == "running": self.runner.stop_event.clear()
                if case == "execution": self.engine._set("best_execution", {"signal_date": "2026-09-25", "phase": "SELL"})
                if case == "active_reset": self.engine._set("best_full_liquidation_reset", frozen["full_liquidation_reset"])
                if case == "early": clock = self.opening - timedelta(days=2)
                if case == "expired": clock = self.opening + timedelta(seconds=600)
                self.engine._set("best_reset_archive", changed)
                if case == "pending":
                    self.engine.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                        "published-unknown", clock.isoformat(), SID, "moomoo_simulate", "3604", "US.AAPL", "SELL", 5, 99.99, "UNKNOWN", None, "MARKET"))
                    self.engine.db.commit()
                try:
                    with self.assertRaises(ValueError): self.runner.prepare_current_target_rebalance(request["reset_id"], now=clock)
                    self.assertIsNone(self.engine._get("best_plan", {}))
                    self.assertEqual(FakeBroker.submissions, [])
                finally:
                    self.runner.stop_event.set()
                    if case == "pending":
                        self.engine.db.execute("DELETE FROM orders WHERE id='published-unknown'")
                        self.engine.db.commit()
        self.engine._set("best_reset_archive", archive)
        self.engine._set("best_capital", capital)
        self.engine._set("best_execution", {})
        self.engine._set("best_full_liquidation_reset", {})

    def test_published_target_offline_restart_and_repeat_preserve_existing_prepared_batch(self):
        request = self.published_rebalance_fixture()
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        with patch.object(self.engine, "connect", side_effect=AssertionError("offline preparation")):
            self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        plan, archive = self.engine._get("best_plan", None), self.engine._get("best_reset_archive", {})
        self.engine._set("best_execution", {"signal_date": "2026-09-25", "phase": "DONE"})
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening + timedelta(seconds=601))
        self.assertEqual(self.engine._get("best_plan", None), plan)
        self.assertEqual(self.engine._get("best_reset_archive", {}), archive)
        self.assertEqual(self.engine._get("best_execution", {})["phase"], "DONE")
        self.assertEqual(FakeBroker.submissions, [])

    def test_published_target_runtime_guard_clears_cached_plan_after_hash_or_source_change(self):
        request = self.published_rebalance_fixture()
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        saved = deepcopy(self.engine._get("best_plan", None))
        status = deepcopy(self.source.status())
        self.reset_connect()
        for case in ("plan_hash", "metadata_hash", "mode_removed", "source_rotated", "capital"):
            with self.subTest(case=case):
                changed, live = deepcopy(saved), deepcopy(status)
                capital = deepcopy(self.engine._get("best_capital", {}))
                if case == "plan_hash": changed["plan"]["rows"][0]["target_weight"] = .09
                if case == "metadata_hash": changed["metadata"]["account_basis"] = "SIGNAL_CLOSE"
                if case == "mode_removed":
                    changed["plan"].pop("execution_mode")
                    changed["metadata"].pop("execution_mode")
                if case == "source_rotated": live["source_refs"]["selected/package.json"]["sha256"] = "b" * 64
                if case == "capital": self.engine._set("best_capital", {**capital, "unused_cash": 990001})
                self.engine._set("best_plan", changed)
                with patch.object(self.source, "status", return_value=live):
                    with self.assertRaises(ValueError): self.runner._prepare(self.opening - timedelta(minutes=1))
                self.assertIsNone(self.runner.plan)
                self.tick_at(self.opening + timedelta(seconds=1))
                self.assertEqual(FakeBroker.submissions, [])
                self.engine._set("best_capital", capital)
        self.engine._set("best_plan", saved)

    def test_published_target_next_signal_uses_actual_book_and_existing_close_load_path(self):
        request = self.published_rebalance_fixture()
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        self.reset_connect()
        with patch.object(self.source, "close_states", side_effect=AssertionError("same day must not require missing closes")), \
                patch.object(self.source, "load", side_effect=AssertionError("same day must not re-solve")):
            self.runner._prepare(self.opening - timedelta(minutes=1))
        observed = {}
        next_status = {**self.source.status(), "source_date": "2026-09-28", "signal_date": "2026-09-28",
            "execution_date": "2026-09-29", "next_open_utc": "2026-09-29T13:30:00+00:00", "signal_close_utc": "2026-09-28T20:00:00+00:00"}
        def closes(books, signal_date):
            observed.update(deepcopy(books))
            return {SID: dict(weights={"AAPL": .05, "MSFT": .03}, cash_weight=.92,
                signal_date=signal_date, valuation_basis="SIGNAL_CLOSE")}
        def load(states, now=None):
            self.assertEqual(states[SID]["signal_date"], "2026-09-28")
            return {**next_status, "plans": {SID: {"rows": [{"code": "US.AAPL", "target_weight": .1}],
                "target_cash_weight": .9, "account_basis": "USER_SUPPLIED_SIGNAL_CLOSE_STATE"}}}
        self.source.close_states, self.source.load = closes, load
        with patch.object(self.source, "status", return_value=next_status):
            self.runner._prepare(self.opening + timedelta(days=1) - timedelta(minutes=1))
        self.assertEqual(observed[SID]["positions"], {"US.AAPL": 5, "US.MSFT": 3})
        self.assertEqual(self.runner.plan["account_basis"], "USER_SUPPLIED_SIGNAL_CLOSE_STATE")
        self.assertNotIn("execution_mode", self.runner.plan)

    def test_published_target_source_read_or_next_signal_close_failure_cannot_renew_old_weights(self):
        request = self.published_rebalance_fixture()
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        saved = deepcopy(self.engine._get("best_plan", None))
        original_status = deepcopy(self.source.status())
        self.reset_connect()
        next_open = self.opening + timedelta(days=1)
        new_status = {**original_status, "source_date": "2026-09-28", "signal_date": "2026-09-28",
            "execution_date": "2026-09-29", "next_open_utc": next_open.isoformat(),
            "signal_close_utc": "2026-09-28T20:00:00+00:00"}
        for case in ("status_error", "next_signal_close_error"):
            with self.subTest(case=case):
                self.runner.plan, self.runner.metadata = deepcopy(saved["plan"]), deepcopy(saved["metadata"])
                status_options = {"side_effect": ValueError("synthetic source unavailable")} if case == "status_error" else {"return_value": new_status}
                with patch.object(self.source, "status", **status_options), \
                        patch.object(self.source, "close_states", side_effect=ValueError("synthetic close unavailable")):
                    with self.assertRaises(ValueError): self.runner._prepare(next_open - timedelta(seconds=1))
                self.assertIsNone(self.runner.plan)
                self.assertEqual(self.engine._get("best_plan", None), saved)
                self.tick_at(next_open + timedelta(seconds=1))
                self.assertEqual(FakeBroker.submissions, [])

    def test_published_target_database_interruption_rolls_back_receipt_and_plan(self):
        request = self.published_rebalance_fixture()
        archive = deepcopy(self.engine._get("best_reset_archive", {}))
        self.engine.db.execute("CREATE TRIGGER synthetic_published_failure BEFORE INSERT ON settings WHEN NEW.key='best_plan' BEGIN SELECT RAISE(ABORT,'synthetic preparation interruption'); END")
        self.engine.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic preparation interruption"):
            self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        self.assertEqual(self.engine._get("best_reset_archive", {}), archive)
        self.assertIsNone(self.engine._get("best_plan", {}))
        self.assertIsNone(self.runner.plan)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_REBALANCE_PREPARED'").fetchone()[0], 0)
        self.engine.db.execute("DROP TRIGGER synthetic_published_failure")
        self.engine.db.commit()
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))

    def test_full_reset_expired_window_never_sells_or_buys(self):
        self.prepare_reset()
        self.reset_connect()
        self.tick_at(self.opening + timedelta(seconds=600))
        self.assertEqual(FakeBroker.submissions, [])
        self.assertIsNone(self.engine._get("best_full_liquidation_reset", {})["post_liquidation_baseline"])


    def revision_fixture(self):
        request = self.published_rebalance_fixture()
        self.runner.prepare_current_target_rebalance(request["reset_id"], now=self.opening - timedelta(hours=1))
        saved = deepcopy(self.engine._get("best_plan", {}))
        status, load = self.source.status, self.source.load
        refs = deepcopy(saved["metadata"]["source_refs"])
        for key in ("daily/report.json", "selected/package.json", "selected/current_report.json", "current/features.parquet"):
            refs[key] = {"sha256": "b" * 64}
        self.source.status = lambda now=None: {**status(now), "source_refs": deepcopy(refs)}
        calls = []
        def revised_load(states=None, now=None, reset_request=None):
            self.assertIsNone(states)
            self.assertEqual(reset_request["expected_package_sha256"], "b" * 64)
            calls.append(deepcopy(reset_request))
            result = load(states, now=now, reset_request=reset_request)
            result["source_refs"] = deepcopy(refs)
            result["plans"][SID].update(rows=[dict(code="US.AMD", target_weight=.09, weight_before=0),
                dict(code="US.MSFT", target_weight=.08, weight_before=0)], target_cash_weight=.83, source_refs=deepcopy(refs))
            return result
        self.source.load = revised_load
        return request, saved, calls

    def test_same_signal_revision_is_offline_atomic_transparent_and_preserves_the_actual_account(self):
        request, old, calls = self.revision_fixture()
        orders, capital = self.cancellation_rows(), deepcopy(self.engine._get("best_capital", {}))
        original = deepcopy(self.engine._get("best_reset_archive", {}))
        actual = FakeBroker.cash, deepcopy(FakeBroker.positions)
        self.runner.prewarm_state = {"old_symbols": ["US.AAPL"]}
        self.engine._set("best_subscription_prewarm", self.runner.prewarm_state)
        with patch.object(self.runner, "_connect", side_effect=AssertionError("revision must not connect")), \
                patch.object(self.source, "close_states", side_effect=AssertionError("revision must not value old close")), \
                patch.object(FakeBroker, "snapshot", side_effect=AssertionError("revision must not query SDK")):
            state = self.runner.revise_current_target_rebalance(request["reset_id"], "b" * 64,
                now=self.opening - timedelta(minutes=30))
        self.assertEqual(state["status"], "STOPPED")
        self.assertEqual(calls[0]["strategy_ids"], [SID])
        self.assertEqual(self.runner.plan["rows"], [dict(code="US.AMD", target_weight=.09), dict(code="US.MSFT", target_weight=.08)])
        self.assertEqual(self.runner.plan["execution_mode"], "REBALANCE_EXISTING_POSITIONS")
        for value in (self.runner.plan, self.runner.metadata):
            self.assertFalse({"reset_id", "reset_request", "assumed_states", "execution_condition", "cash_weight_before"} & set(value))
        self.assertEqual(self.cancellation_rows(), orders)
        self.assertEqual(self.engine._get("best_capital", {}), capital)
        self.assertEqual((FakeBroker.cash, FakeBroker.positions), actual)
        archive = self.engine._get("best_reset_archive", {})[request["reset_id"]]
        self.assertEqual(archive["cancellation"]["best_plan"], original[request["reset_id"]]["cancellation"]["best_plan"])
        revision = archive["cancellation"]["published_target_rebalance_revisions"][0]
        self.assertEqual(revision["previous_best_plan"], old)
        self.assertEqual(revision["previous_receipt"], original[request["reset_id"]]["cancellation"]["published_target_rebalance"])
        self.assertEqual(revision["previous_subscription_prewarm"], {"old_symbols": ["US.AAPL"]})
        self.assertEqual(archive["cancellation"]["published_target_rebalance"]["package_sha256"], "b" * 64)
        self.assertEqual(self.engine._get("best_full_liquidation_reset", None), {})
        self.assertEqual(self.engine._get("best_subscription_prewarm", None), {})
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_REBALANCE_REVISED'").fetchone()[0], 1)
        self.reset_connect()
        self.runner._prepare(self.opening - timedelta(minutes=20))
        self.assertEqual(self.runner.plan["rows"][0]["code"], "US.AMD")
        self.runner.stop()
        archive_before = deepcopy(self.engine._get("best_reset_archive", {}))
        self.runner.revise_current_target_rebalance(request["reset_id"], "b" * 64, now=self.opening - timedelta(minutes=15))
        self.assertEqual(self.engine._get("best_reset_archive", {}), archive_before)
        self.assertEqual(len(calls), 1)

    def test_same_signal_revision_after_offline_restart_still_requires_active_receipt_and_source(self):
        request, _, _ = self.revision_fixture()
        self.runner.close()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.runner = BestBroker(self.temp.name, self.source, engine=self.engine,
            execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        with patch.object(self.engine, "connect", side_effect=AssertionError("offline revision must not connect")):
            self.runner.revise_current_target_rebalance(request["reset_id"], "b" * 64,
                now=self.opening - timedelta(minutes=30))
        self.assertEqual(self.engine.mode, "paper")
        self.assertIsNone(self.engine.broker)
        self.reset_connect()
        self.runner._prepare(self.opening - timedelta(minutes=20))
        self.assertEqual(self.runner.plan["rows"][0]["code"], "US.AMD")

    def test_same_signal_revision_rejects_running_orders_window_account_dates_and_bad_source_without_writing(self):
        request, old, _ = self.revision_fixture()
        archive = deepcopy(self.engine._get("best_reset_archive", {}))
        capital = deepcopy(self.engine._get("best_capital", {}))
        status, load = self.source.status, self.source.load
        cases = ("running", "worker", "engine_worker", "halt", "unknown", "terminal_sent", "filled", "order_not_definitely_unsent",
            "active_reset", "wrong_id", "bad_sha", "package_sha", "budget", "account", "unused_cash", "delay", "window", "partial",
            "clock_backwards", "at_open", "after_open", "started_batch", "catchup", "signal", "execution", "calendar", "session_rules",
            "open_time", "close_time", "not_ready", "gaps", "source_error", "load_error", "fit", "policy", "bad_weights")
        for case in cases:
            with self.subTest(case=case):
                self.engine._set("best_reset_archive", deepcopy(archive));self.engine._set("best_plan", deepcopy(old))
                self.engine._set("best_capital", deepcopy(capital));self.engine._set("best_account", capital["account_id"])
                self.engine._set("best_full_liquidation_reset", {});self.engine._set("best_execution", {});self.engine._set("best_same_day_catchup", None)
                self.runner.stop_event.set();self.runner.worker=None;self.engine.worker=None;self.engine.halt_event.clear()
                self.runner.execution_delay_minutes=0;self.runner.execution_window_seconds=600;self.runner.allow_partial_quotes=True
                self.source.status, self.source.load = status, load
                now, identity, sha = self.opening-timedelta(minutes=30), request["reset_id"], "b"*64
                if case == "running": self.runner.stop_event.clear()
                if case == "worker": self.runner.worker=type("Worker", (), {"is_alive":lambda s:True})()
                if case == "engine_worker": self.engine.worker=type("Worker", (), {"is_alive":lambda s:True})()
                if case == "halt": self.engine.halt_event.set()
                if case == "wrong_id": identity="other"
                if case == "bad_sha": sha="BAD"
                if case == "package_sha": sha="c"*64
                if case in {"budget", "unused_cash", "account"}:
                    changed=deepcopy(capital);changed[{"budget":"budget","unused_cash":"unused_cash","account":"account_id"}[case]]=1
                    self.engine._set("best_capital",changed)
                if case == "delay":self.runner.execution_delay_minutes=1
                if case == "window":self.runner.execution_window_seconds=60
                if case == "partial":self.runner.allow_partial_quotes=False
                if case == "clock_backwards":now=self.opening-timedelta(hours=3)
                if case == "at_open":now=self.opening
                if case == "after_open":now=self.opening+timedelta(seconds=1)
                if case == "active_reset":self.engine._set("best_full_liquidation_reset", {"stage":"ARMED"})
                if case == "started_batch":self.engine._set("best_execution", {"phase":"SELL"})
                if case == "catchup":self.engine._set("best_same_day_catchup", {"active":True})
                if case in {"unknown", "terminal_sent", "filled", "order_not_definitely_unsent"}:
                    order_status={"unknown":"UNKNOWN","terminal_sent":"CANCELLED_ALL","filled":"FILLED_ALL","order_not_definitely_unsent":"CANCELLED_BEFORE_SEND"}[case]
                    self.engine.db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("revision-test",now.isoformat(),SID,"moomoo_simulate",capital["account_id"],"US.AAPL","SELL",1,99.99,order_status,"sent","MARKET"));self.engine.db.commit()
                if case in {"signal","execution","open_time","close_time","not_ready","gaps","calendar","session_rules"}:
                    changed=deepcopy(status(now))
                    if case == "signal":changed["signal_date"]="2026-09-24"
                    if case == "execution":changed["execution_date"]="2026-09-29"
                    if case == "open_time":changed["next_open_utc"]=(self.opening+timedelta(minutes=1)).isoformat()
                    if case == "close_time":changed["signal_close_utc"]="2026-09-25T19:00:00+00:00"
                    if case == "not_ready":changed["ready"]=False
                    if case == "gaps":changed["data_gaps"]=[{"missing":True}]
                    if case in {"calendar","session_rules"}:changed["source_refs"][{"calendar":"frozen_calendar","session_rules":"session_hours_rules"}[case]]={"sha256":"c"*64}
                    self.source.status=lambda now=None:deepcopy(changed)
                if case == "source_error":self.source.status=lambda now=None:(_ for _ in ()).throw(ValueError("source unavailable"))
                if case == "load_error":self.source.load=lambda **kw:(_ for _ in ()).throw(ValueError("load unavailable"))
                if case in {"fit","policy","bad_weights"}:
                    def bad_load(**kw):
                        value=load(**kw)
                        if case == "fit":value["plans"][SID]["model_fit_calls"]=1
                        if case == "policy":value["plans"][SID]["policy_id"]="LEGACY"
                        if case == "bad_weights":value["plans"][SID]["rows"][0]["target_weight"]=.5
                        return value
                    self.source.load=bad_load
                try:
                    persisted_plan=deepcopy(self.engine._get("best_plan",{}));persisted_archive=deepcopy(self.engine._get("best_reset_archive",{}))
                    with self.assertRaises(ValueError):self.runner.revise_current_target_rebalance(identity,sha,now=now)
                    self.assertEqual(self.engine._get("best_plan",{}),persisted_plan)
                    self.assertEqual(self.engine._get("best_reset_archive",{}),persisted_archive)
                    self.assertEqual(FakeBroker.submissions,[])
                    if case not in {"running","worker","engine_worker","wrong_id","bad_sha"}:self.assertIsNone(self.runner.plan)
                finally:
                    self.engine.db.execute("DELETE FROM orders WHERE id='revision-test'");self.engine.db.commit()
                    self.runner.stop_event.set();self.runner.worker=None;self.engine.worker=None;self.engine.halt_event.clear()
        self.engine._set("best_capital",capital);self.engine._set("best_account",capital["account_id"])
        self.runner.execution_delay_minutes=0;self.runner.execution_window_seconds=600;self.runner.allow_partial_quotes=True

    def test_same_signal_revision_database_failure_preserves_old_authorization_and_orders(self):
        request, old, _ = self.revision_fixture()
        archive=deepcopy(self.engine._get("best_reset_archive",{}));orders=self.cancellation_rows()
        self.engine.db.execute("CREATE TRIGGER synthetic_revision_failure BEFORE INSERT ON settings WHEN NEW.key='best_plan' BEGIN SELECT RAISE(ABORT,'synthetic revision failure'); END");self.engine.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError,"synthetic revision failure"):
            self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=30))
        self.assertEqual(self.engine._get("best_plan",{}),old)
        self.assertEqual(self.engine._get("best_reset_archive",{}),archive)
        self.assertEqual(self.cancellation_rows(),orders)
        self.assertIsNone(self.runner.plan)
        self.assertEqual(self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='PUBLISHED_TARGET_REBALANCE_REVISED'").fetchone()[0],0)
        self.engine.db.execute("DROP TRIGGER synthetic_revision_failure");self.engine.db.commit()
        self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=20))

    def test_same_signal_revision_old_receipt_is_not_a_second_authority(self):
        request, old, _=self.revision_fixture()
        self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=30))
        new=deepcopy(self.engine._get("best_plan",{}))
        self.engine._set("best_plan",old)
        self.reset_connect()
        with self.assertRaisesRegex(ValueError,"PUBLISHED_TARGET_AUTHORIZATION_CHANGED"):
            self.runner._prepare(self.opening-timedelta(minutes=20))
        self.assertIsNone(self.runner.plan)
        self.engine._set("best_plan",new)
        self.runner._prepare(self.opening-timedelta(minutes=15))
        self.assertEqual(self.runner.plan["rows"][0]["code"],"US.AMD")


    def test_same_signal_revision_real_daily_source_archive_preserves_original_and_retries_after_sql_failure(self):
        from pathlib import Path
        from moomoo_component.applied_source import DailySource, _reset_request, _assumed_states, _bytes
        import hashlib
        request,_ = self.full_reset_fixture()
        owner=object.__new__(DailySource)
        owner.daily_root=Path(self.temp.name)
        owner.runtime_root=owner.daily_root/"source_archive"
        owner._read_only_roots=(owner.daily_root/"canonical_repo",owner.daily_root/"canonical_data")
        old_load=self.source.load
        def archived_load(states=None,now=None,reset_request=None):
            value=old_load(states,now=now,reset_request=reset_request)
            normalized=_reset_request(reset_request,now=now)
            refs=deepcopy(self.source.status(now)["source_refs"])
            value.update(reset_request=normalized,reset_request_sha256=hashlib.sha256(_bytes(normalized)).hexdigest(),
                assumed_states=_assumed_states(normalized),source_refs=refs)
            for plan in value["plans"].values():
                plan.update(reset_id=normalized["reset_id"],source_date=normalized["signal_date"],source_refs=deepcopy(refs))
                if normalized["expected_package_sha256"]=="b"*64:
                    plan.update(rows=[dict(code="US.AMD",target_weight=.09,weight_before=0),dict(code="US.MSFT",target_weight=.08,weight_before=0)],target_cash_weight=.83)
            owner._archive(value,states=None)
            return value
        self.source.load=archived_load
        self.runner.prepare_full_liquidation_reset(request,now=self.opening-timedelta(days=1))
        self.runner.cancel_full_liquidation_reset(request["reset_id"],now=self.opening-timedelta(hours=2))
        self.runner.prepare_current_target_rebalance(request["reset_id"],now=self.opening-timedelta(hours=1))
        original=deepcopy(self.engine._get("best_reset_archive",{}));saved=deepcopy(self.engine._get("best_plan",{}))
        old_path=Path(saved["metadata"]["archive"]["path"]);old_bytes=old_path.read_bytes()
        status=self.source.status;refs=deepcopy(status()["source_refs"])
        for key in ("daily/report.json","selected/package.json","selected/current_report.json","current/features.parquet"):
            refs[key]={"sha256":"b"*64}
        self.source.status=lambda now=None:{**status(now),"source_refs":deepcopy(refs)}
        self.engine.db.execute("CREATE TRIGGER synthetic_archive_revision_failure BEFORE INSERT ON settings WHEN NEW.key='best_plan' BEGIN SELECT RAISE(ABORT,'synthetic archive revision failure'); END");self.engine.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError,"synthetic archive revision failure"):
            self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=30))
        self.assertEqual(self.engine._get("best_plan",{}),saved)
        self.assertEqual(self.engine._get("best_reset_archive",{}),original)
        template=self.runner._source_revision_request(original[request["reset_id"]]["cancellation"]["full_liquidation_reset"]["request"],"b"*64)
        new_path=owner.runtime_root/"policies/HGB_TOP20_RISK_R1/resets"/template["reset_id"]/request["signal_date"]/"plans.json"
        new_bytes=new_path.read_bytes()
        self.engine.db.execute("DROP TRIGGER synthetic_archive_revision_failure");self.engine.db.commit()
        self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=20))
        self.assertEqual(old_path.read_bytes(),old_bytes)
        self.assertEqual(new_path.read_bytes(),new_bytes)
        receipt=self.engine._get("best_reset_archive",{})[request["reset_id"]]["cancellation"]["published_target_rebalance"]
        self.assertEqual(receipt["source_template_request"],template)
        self.assertEqual(receipt["original_epoch_id"],request["reset_id"])
        self.assertEqual(receipt["source_archive"],self.runner.metadata["archive"])
        self.assertEqual(FakeBroker.submissions,[])

    def test_same_signal_revision_active_template_authorization_cannot_be_removed_or_mutated(self):
        request,_,_=self.revision_fixture()
        self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=30))
        archive=deepcopy(self.engine._get("best_reset_archive",{}))
        for case in ("missing_request","missing_epoch","missing_sha","missing_archive","all_revision_fields","changed_timestamp","changed_sha"):
            with self.subTest(case=case):
                changed=deepcopy(archive);receipt=changed[request["reset_id"]]["cancellation"]["published_target_rebalance"]
                fields={"missing_request":"source_template_request","missing_epoch":"original_epoch_id","missing_sha":"source_template_request_sha256","missing_archive":"source_archive"}
                if case in fields:receipt.pop(fields[case])
                if case=="all_revision_fields":
                    for key in fields.values():receipt.pop(key)
                if case=="changed_timestamp":receipt["source_template_request"]["requested_at"]=(self.opening-timedelta(minutes=30)).isoformat()
                if case=="changed_sha":receipt["source_template_request_sha256"]="c"*64
                self.engine._set("best_reset_archive",changed)
                with self.assertRaisesRegex(ValueError,"AUTHORIZATION_CHANGED"):
                    self.runner.revise_current_target_rebalance(request["reset_id"],"b"*64,now=self.opening-timedelta(minutes=20))
                self.assertIsNone(self.runner.plan)
                self.assertEqual(FakeBroker.submissions,[])
        self.engine._set("best_reset_archive",archive)



class NewOrdinaryWindowBrokerTests(unittest.TestCase):
    setUp=BestBrokerTests.setUp
    tearDown=BestBrokerTests.tearDown
    connect=BestBrokerTests.connect
    tick_at=BestBrokerTests.tick_at

    def test_ordinary_0955_1020_uses_original_tick_and_never_replays_after_deadline(self):
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,
            execution_delay_minutes=25,execution_window_seconds=1500,allow_partial_quotes=True)
        self.connect();opening=self.opening+timedelta(minutes=25)
        self.tick_at(opening-timedelta(microseconds=1));self.assertEqual(FakeBroker.submissions,[])
        self.tick_at(opening+timedelta(seconds=1499))
        self.assertTrue(FakeBroker.submissions)
        count=len(FakeBroker.submissions)
        self.tick_at(opening+timedelta(seconds=1500))
        self.tick_at(opening+timedelta(seconds=1501))
        self.assertEqual(len(FakeBroker.submissions),count)
        for item in FakeBroker.submit_options:
            self.assertEqual(item["execution_deadline_utc"],(opening+timedelta(seconds=1500)).isoformat())

    def test_ordinary_25_window_unknown_submission_still_halts_and_never_retries(self):
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,
            execution_delay_minutes=25,execution_window_seconds=1500,allow_partial_quotes=True)
        self.connect();FakeBroker.before_send_error=BrokerError("submission result unknown")
        opening=self.opening+timedelta(minutes=25)
        with self.assertRaises(BrokerError):self.tick_at(opening+timedelta(seconds=1))
        self.assertTrue(self.engine.halt_event.is_set())
        row=self.engine.state()["orders"][-1];self.assertEqual(row["status"],"UNKNOWN")
        self.assertEqual(FakeBroker.submissions,[])
        with patch.object(self.engine.broker,"reconcile",side_effect=BrokerReadError("pending unknown read unavailable")):
            try:self.tick_at(opening+timedelta(seconds=2))
            except (BrokerError,ValueError):pass
        self.assertEqual(len(self.engine.state()["orders"]),1)

if __name__ == '__main__':
    unittest.main()



class SameDayRemainderTests(unittest.TestCase):
    """Bounded opt-in continuation, using only the existing fake SIMULATE broker."""
    setUp = BestBrokerTests.setUp
    tearDown = BestBrokerTests.tearDown
    connect = BestBrokerTests.connect
    partial_runner = BestBrokerTests.partial_runner
    tick_at = BestBrokerTests.tick_at

    def original_deferred_signal(self, with_processed_extra=False, extra_unknown=False, removed=False):
        self.source.rows = [{'code':'US.AAPL','target_weight':.1}] + ([] if removed else [{'code':'US.MSFT','target_weight':.09}])
        if extra_unknown:
            self.source.rows.append({'code':'US.NVDA','target_weight':.02})
        if with_processed_extra:
            self.source.rows.append({'code':'US.DNA','target_weight':.01})
        self.partial_runner(delay=0)
        old = (self.opening - timedelta(days=3)).isoformat()
        self.engine.db.execute('INSERT INTO orders '
            '(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('old-msft',old,SID,'moomoo_simulate','3604',
             'US.MSFT','BUY',17,100,'FILLED_ALL','old-msft-broker'))
        self.engine.db.execute('INSERT INTO order_fills VALUES (?,?)',
            ('old-msft',json.dumps({'fill_qty':17,'fill_price':100,'filled_at':old})))
        self.engine.db.commit()
        FakeBroker.positions,FakeBroker.cash={'US.MSFT':17},998300
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        error=BrokerOrderNotSent('definitely unsent synthetic read cooldown')
        error.retry_after_seconds=30
        FakeBroker.before_send_error=error
        FakeBroker.quote_errors={'US.MSFT':'stale original sell quote', **({'US.NVDA':'stale unresolved buy'} if extra_unknown else {})}
        with self.assertRaises(BrokerReadError):
            self.tick_at(self.opening + timedelta(seconds=1))
        FakeBroker.quote_errors={'US.AAPL':'stale original buy quote', **({'US.NVDA':'stale unresolved buy'} if extra_unknown else {})}
        with self.assertRaises(BrokerReadError):
            self.tick_at(self.opening + timedelta(seconds=31))
        FakeBroker.quote_errors={'US.AAPL':'stale buy quote','US.MSFT':'stale sell quote', **({'US.NVDA':'stale unresolved buy'} if extra_unknown else {})}
        self.tick_at(self.opening + timedelta(seconds=32))
        self.runner.stop()
        state=deepcopy(self.engine._get('best_execution',{}))
        self.assertEqual(state['phase'],'BUY')
        self.assertEqual(state['target_quantities'],{'US.AAPL':9,**({'US.DNA':0} if with_processed_extra else {})})
        self.assertEqual({row['code'] for row in state['deferred_sells']},{'US.MSFT'})
        evidence=json.loads(self.engine.db.execute('SELECT payload FROM strategies WHERE id=?',(SID,)).fetchone()[0])
        self.assertEqual(evidence['targets'],[{'code':'US.MSFT','target_qty':0 if removed else 8}])
        self.assertEqual(FakeBroker.submissions,[])
        self.now=self.opening + timedelta(seconds=601)
        self.deadline=self.now+timedelta(seconds=600)
        self.original_state,self.original_plan,self.original_evidence=state,deepcopy(self.engine._get('best_plan',{})),evidence
        return state

    def authorize(self, **changes):
        values=dict(execution_date='2026-09-28',deadline_utc=self.deadline.isoformat(),account_id='3604',
                    now=self.now,include_deferred_sells=True)
        values.update(changes)
        return self.runner.authorize_catchup(**values)

    def resume(self):
        FakeBroker.quote_errors,FakeBroker.before_send_error={},None
        self.engine.cancel_step.clear()
        self.runner.stop_event.clear()

    def test_deferred_sell_uses_original_nonzero_target_then_original_buy_without_repeats(self):
        self.original_deferred_signal()
        original_sell=[dict(row) for row in self.engine.db.execute("SELECT * FROM orders WHERE side='SELL'")]
        permission=self.authorize()
        self.assertEqual(permission['deferred_sell_targets'],{'US.MSFT':8})
        self.assertEqual(permission['original_buy']['target_quantities'],{'US.AAPL':9})
        self.assertEqual(self.engine._get('best_execution',{}),self.original_state)
        self.resume()
        for seconds in (1,2,3,4,5):
            self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual([(row['code'],row['side'],row['qty']) for row in FakeBroker.submissions],
                         [('US.MSFT','SELL',9),('US.AAPL','BUY',9)])
        self.assertEqual(FakeBroker.positions,{'US.MSFT':8,'US.AAPL':9})
        final=self.engine._get('best_execution',{})
        self.assertEqual(final['phase'],'DONE')
        self.assertEqual(final['phase_asof'],self.original_state['phase_asof'])
        self.assertEqual(final['target_quantities']['US.AAPL'],9)
        self.assertEqual(self.engine._get('best_plan',{}),self.original_plan)
        self.assertEqual([dict(self.engine.db.execute('SELECT * FROM orders WHERE id=?',(row['id'],)).fetchone())
                          for row in original_sell],original_sell)
        shown=self.runner.state()['same_day_catchup']
        self.assertEqual(set(shown),{'signal_date','execution_date','authorized_at_utc','deadline_utc','reason','include_deferred_sells'})
        self.assertNotIn('account_id',shown)
        self.assertNotIn('deferred_sell_manifest',shown)

    def test_restart_during_authorized_sell_preserves_buy_and_no_duplicate_sell(self):
        self.original_deferred_signal()
        self.authorize()
        self.resume()
        self.tick_at(self.now+timedelta(seconds=1))
        sell=deepcopy(self.engine._get('best_execution',{}))
        self.assertEqual(sell['phase'],'SELL')
        self.assertEqual(sell['resume_buy_state']['target_quantities'],self.original_state['target_quantities'])
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine)
        FakeBroker.clock=staticmethod(lambda:self.now+timedelta(seconds=2))
        self.connect()
        for seconds in (2,3,4):
            self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual(len(FakeBroker.submissions),2)
        self.assertEqual(self.runner.status,'EXECUTED')

    def test_default_buy_only_authorization_still_refuses_deferred_sell(self):
        self.original_deferred_signal()
        with self.assertRaises(ValueError):
            self.authorize(include_deferred_sells=False)
        self.assertIsNone(self.engine._get('best_same_day_catchup',None))

    def test_opt_in_type_and_exclusive_six_hundred_second_limit(self):
        self.original_deferred_signal()
        for value in (1,None,'true'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.authorize(include_deferred_sells=value)
        for deadline in (self.now,self.now+timedelta(seconds=601)):
            with self.subTest(deadline=deadline),self.assertRaises(ValueError):
                self.authorize(deadline_utc=deadline.isoformat())
        self.authorize()
        self.resume()
        self.tick_at(self.deadline)
        self.assertEqual(FakeBroker.submissions,[])

    def test_authorization_requires_original_sell_source_quantity_and_codes(self):
        self.original_deferred_signal()
        for mutate in ('missing_target','wrong_kind','wrong_phase','wrong_hash','future_asof','duplicate_target'):
            evidence=deepcopy(self.original_evidence)
            origin=json.loads(evidence['source'])
            if mutate=='missing_target': evidence['targets']=[]
            if mutate=='wrong_kind': origin['kind']='UNBOUND'
            if mutate=='wrong_phase': origin['phase']='BUY'
            if mutate=='wrong_hash': origin['source_hash']='other-source'
            if mutate=='future_asof': evidence['asof']=self.now.isoformat()
            if mutate=='duplicate_target': evidence['targets']*=2
            evidence['source']=json.dumps(origin)
            self.engine.db.execute('UPDATE strategies SET payload=? WHERE id=?',(json.dumps(evidence),SID))
            self.engine.db.commit()
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                self.authorize()
        self.engine.db.execute('UPDATE strategies SET payload=? WHERE id=?',(json.dumps(self.original_evidence),SID))
        self.engine.db.commit()
        self.authorize()

    def test_definitely_unsent_cannot_have_broker_id_or_dealt_evidence(self):
        self.original_deferred_signal()
        row=self.engine.db.execute("SELECT id FROM orders WHERE status='CANCELLED_BEFORE_SEND' LIMIT 1").fetchone()
        self.engine.db.execute('UPDATE orders SET order_id=? WHERE id=?',('real-order-id',row['id']))
        self.engine.db.commit()
        with self.assertRaises(ValueError): self.authorize()
        self.engine.db.execute('UPDATE orders SET order_id=NULL WHERE id=?',(row['id'],))
        for payload in ({'fill_qty':1,'fill_price':100},{'dealt_qty':1}, {'fill_qty':0,'fill_price':100},
                        {'fill_qty':0,'filled_at':self.now.isoformat()}):
            self.engine.db.execute('INSERT OR REPLACE INTO order_fills VALUES (?,?)',(row['id'],json.dumps(payload)))
            self.engine.db.commit()
            with self.subTest(payload=payload),self.assertRaises(ValueError): self.authorize()
        self.engine.db.execute('DELETE FROM order_fills WHERE id=?',(row['id'],))
        self.engine.db.commit()
        self.authorize()

    def test_persisted_permission_rejects_plan_refs_account_phase_targets_or_codes_tamper(self):
        self.original_deferred_signal()
        record=self.authorize()
        self.resume()
        state=deepcopy(self.engine._get('best_execution',{}))
        for mutate in ('plan','refs','account','phase','buy_target','buy_clock','sell_target','deferred_code','deadline'):
            permission=deepcopy(record)
            self.runner.plan=deepcopy(self.original_plan['plan'])
            self.runner.metadata=deepcopy(self.original_plan['metadata'])
            changed=deepcopy(state)
            if mutate=='plan': self.runner.plan['rows'][0]['target_weight']=.2
            if mutate=='refs': self.runner.plan['source_refs']={'changed':'a'*64}
            if mutate=='account': permission['account_id']='different-account'
            if mutate=='phase': changed['phase']='SELL'
            if mutate=='buy_target': changed['target_quantities']['US.AAPL']=900
            if mutate=='buy_clock': changed['phase_asof']=self.now.isoformat()
            if mutate=='sell_target': permission['deferred_sell_targets']['US.MSFT']=1
            if mutate=='deferred_code': changed['deferred_sells']=[{'code':'US.OTHER'}]
            if mutate=='deadline': permission['deadline_utc']=(self.now+timedelta(seconds=601)).isoformat()
            self.engine._set('best_same_day_catchup',permission)
            self.engine._set('best_execution',changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                self.runner._catchup_end()
        self.engine._set('best_same_day_catchup',record)
        self.engine._set('best_execution',state)

    def test_completed_original_sell_does_not_turn_into_buy_if_position_below_target(self):
        self.original_deferred_signal()
        self.authorize()
        self.resume()
        # An observed account divergence fails before any intention can reverse SELL into BUY.
        FakeBroker.positions['US.MSFT']=7
        with self.assertRaises(ValueError):
            self.tick_at(self.now+timedelta(seconds=1))
        self.assertEqual(FakeBroker.submissions,[])
    def test_opt_in_requires_current_original_simulate_connection(self):
        self.original_deferred_signal()
        original = self.engine.broker
        connection = deepcopy(self.engine.connection)
        for mutation in ('paper','missing_broker','wrong_broker_account','wrong_engine_account','real_environment'):
            self.engine.mode='moomoo_simulate'
            self.engine.account_id='3604'
            self.engine.broker=original
            original.account_id='3604'
            self.engine.connection=deepcopy(connection)
            if mutation=='paper': self.engine.mode='paper'
            if mutation=='missing_broker': self.engine.broker=None
            if mutation=='wrong_broker_account': original.account_id='other-account'
            if mutation=='wrong_engine_account': self.engine.account_id='other-account'
            if mutation=='real_environment': self.engine.connection['accounts'][0]['environment']='REAL'
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'SIMULATE_CONNECTION'):
                self.authorize()
            self.assertIsNone(self.engine._get('best_same_day_catchup',None))
        self.engine.mode='moomoo_simulate'
        self.engine.account_id='3604'
        self.engine.broker=original
        original.account_id='3604'
        self.engine.connection=connection
        self.authorize()

    def test_quote_batch_crossing_deadline_checks_actual_clock_before_rebuilding_state(self):
        self.original_deferred_signal()
        self.authorize()
        self.resume()
        before=deepcopy(self.engine._get('best_execution',{}))
        original=FakeBroker.snapshot_partial
        actual=[self.now+timedelta(seconds=1)]
        def delayed_snapshot(broker,codes):
            value=original(broker,codes)
            actual[0]=self.deadline
            return value
        self.runner._now=lambda:actual[0]
        with patch.object(FakeBroker,'snapshot_partial',delayed_snapshot):
            self.tick_at(self.now+timedelta(seconds=1))
        self.assertEqual(FakeBroker.submissions,[])
        self.assertEqual(self.engine._get('best_execution',{}),before)
        self.assertEqual(self.runner.status,'PARTIALLY_EXECUTED')

    def test_opt_in_first_target_batch_skips_processed_nonheld_but_preserves_full_funds_and_positions(self):
        self.original_deferred_signal(with_processed_extra=True)
        self.assertIn('US.DNA',self.original_state['processed_codes'])
        self.authorize()
        self.resume()
        original=FakeBroker.snapshot_partial
        observed=[]
        def full_snapshot(broker,codes):
            value=original(broker,codes)
            observed.append((set(codes),deepcopy(value['positions']),value['cash']))
            return value
        with patch.object(FakeBroker,'snapshot_partial',full_snapshot):
            self.tick_at(self.now+timedelta(seconds=1))
        self.assertEqual(observed[0][0],{'US.MSFT','US.AAPL'})
        self.assertEqual(observed[0][1]['US.MSFT']['qty'],17)
        self.assertEqual(observed[0][2],998300)
        self.assertEqual([(row['side'],row['qty']) for row in FakeBroker.submissions],[('SELL',9)])

    def test_resumed_buy_keeps_original_sell_quantity_when_price_falls(self):
        self.original_deferred_signal()
        self.authorize()
        self.resume()
        self.tick_at(self.now+timedelta(seconds=1))
        self.assertEqual([(row['code'],row['side'],row['qty']) for row in FakeBroker.submissions],
                         [('US.MSFT','SELL',9)])
        original=FakeBroker.snapshot_partial
        def lower_price(broker,codes):
            value=original(broker,codes)
            quote=value['quotes'].get('US.MSFT')
            if quote:
                quote.update(price=50,bid=49.99,ask=50.01)
            return value
        with patch.object(FakeBroker,'snapshot_partial',lower_price):
            for seconds in (2,3,4,5):
                self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual([(row['code'],row['side'],row['qty']) for row in FakeBroker.submissions],
                         [('US.MSFT','SELL',9),('US.AAPL','BUY',9)])
        final=self.engine._get('best_execution',{})
        self.assertEqual(final['target_quantities'],{'US.AAPL':9,'US.MSFT':8})
        self.assertEqual(final['phase_asof'],self.original_state['phase_asof'])
        self.assertEqual(FakeBroker.positions['US.MSFT'],8)
        self.assertEqual(final['phase'],'DONE')

    def test_original_buy_quantity_conflict_with_evidenced_sell_rejects_authorization(self):
        self.original_deferred_signal()
        state=deepcopy(self.original_state)
        state['target_quantities']['US.MSFT']=9
        self.engine._set('best_execution',state)
        with self.assertRaisesRegex(ValueError,'BUY_SELL_TARGET_CONFLICT'):
            self.authorize()
        self.assertIsNone(self.engine._get('best_same_day_catchup',None))

    def test_previous_signal_remainder_does_not_bind_next_signal(self):
        self.original_deferred_signal()
        record=self.authorize()
        record['signal_date']='2026-09-24'
        self.engine._set('best_same_day_catchup',record)
        self.resume()
        self.tick_at(self.opening+timedelta(seconds=33))
        self.assertEqual([(row['code'],row['side'],row['qty']) for row in FakeBroker.submissions],
                         [('US.MSFT','SELL',9)])
        self.assertEqual(self.engine._get('best_same_day_catchup',{}),record)
        self.assertEqual(self.engine._get('best_execution',{})['signal_date'],'2026-09-25')


class ManualQuoteRefreshTests(SameDayRemainderTests):
    """Fresh-quote residual targets are explicit and do not replace old execution evidence."""
    def discard_old_sell(self):
        value=deepcopy(self.original_evidence)
        value['revision']=self.original_state['signal_date']+':BUY'
        value['targets']=[{'code':'US.AAPL','target_qty':9}]
        origin=json.loads(value['source']); origin['phase']='BUY'; value['source']=json.dumps(origin)
        self.engine.db.execute('UPDATE strategies SET payload=? WHERE id=?',(json.dumps(value),SID))
        self.engine.db.commit()

    def new_permission(self, **fixture):
        self.original_deferred_signal(**fixture)
        self.discard_old_sell()
        with self.assertRaisesRegex(ValueError,'ORIGINAL_SELL_EVIDENCE'):
            self.authorize()
        value=self.authorize(quote_refresh=True)
        self.assertEqual(value['reason'],'USER_MANUAL_REMAINDER_QUOTE_REFRESH')
        self.assertEqual(value['original_execution'],self.original_state)
        self.assertEqual(self.engine._get('best_plan',{}),self.original_plan)
        self.resume()
        return value

    def priced(self, msft=100, aapl=100, nvda=100):
        original=FakeBroker.snapshot_partial
        def quotes(broker,codes):
            value=original(broker,codes)
            for code,price in [('US.MSFT',msft),('US.AAPL',aapl),('US.NVDA',nvda)]:
                if code in value['quotes']:
                    value['quotes'][code].update(price=price,bid=price-.01,ask=price+.01)
            return value
        return patch.object(FakeBroker,'snapshot_partial',quotes)

    def test_manual_decrease_uses_new_quote_and_never_buys_back_after_price_falls(self):
        self.new_permission()
        with self.priced(msft=200):
            self.tick_at(self.now+timedelta(seconds=1))
        proof=self.engine._get('best_same_day_catchup',{})
        row=proof['new_quantity_records'][0]
        self.assertEqual(row['held_before'],17)
        self.assertLess(row['desired'],17)
        self.assertEqual(row['desired'],row['new_buy_target'])
        self.assertEqual(row['new_sell_target'],row['desired'])
        self.assertEqual(row['quote_evidence']['ask'],200.01)
        self.assertEqual(FakeBroker.submissions[0]['side'],'SELL')
        with self.priced(msft=40,aapl=40):
            for seconds in (2,3,4,5): self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual([(r['code'],r['side']) for r in FakeBroker.submissions],[('US.MSFT','SELL'),('US.AAPL','BUY')])
        self.assertEqual(FakeBroker.positions['US.MSFT'],row['desired'])
        self.assertEqual(FakeBroker.positions['US.AAPL'],9)
        self.assertEqual(self.engine._get('best_execution',{})['phase'],'DONE')

    def test_manual_deferred_needing_increase_keeps_uncapped_desired_for_buy(self):
        self.new_permission()
        with self.priced(msft=40):
            for seconds in (1,2,3,4,5): self.tick_at(self.now+timedelta(seconds=seconds))
        proof=self.engine._get('best_same_day_catchup',{})
        row=proof['new_quantity_records'][0]
        self.assertGreater(row['desired'],17)
        self.assertEqual(row['new_sell_target'],17)
        self.assertEqual(row['new_buy_target'],row['desired'])
        self.assertEqual(FakeBroker.positions['US.MSFT'],row['desired'])
        self.assertTrue(any(r['code']=='US.MSFT' and r['side']=='BUY' for r in FakeBroker.submissions))
        self.assertFalse(any(r['code']=='US.MSFT' and r['side']=='SELL' for r in FakeBroker.submissions))
        self.assertEqual(self.engine._get('best_execution',{})['phase'],'DONE')

    def test_manual_new_buy_has_new_asof_evidence_original_cap_and_processed_scope(self):
        permission=self.new_permission(extra_unknown=True,with_processed_extra=True)
        self.assertEqual(set(permission['eligible_codes']),{'US.MSFT','US.AAPL','US.NVDA'})
        with self.priced(msft=200,aapl=40,nvda=40):
            for seconds in (1,2,3,4,5,6): self.tick_at(self.now+timedelta(seconds=seconds))
        permission=self.engine._get('best_same_day_catchup',{})
        self.assertIn('US.NVDA',permission['resolved_buy_targets'])
        row=next(r for r in permission['new_quantity_records'] if r['code']=='US.NVDA')
        self.assertGreaterEqual(row['resolved_at_utc'],permission['authorized_at_utc'])
        self.assertEqual(row['source_hash'],permission['source_hash'])
        self.assertEqual(FakeBroker.positions['US.AAPL'],9)
        self.assertFalse(any(r['code']=='US.DNA' for r in FakeBroker.submissions))
        self.assertEqual(self.engine._get('best_plan',{}),self.original_plan)

    def test_manual_removed_deferred_can_only_sell_to_zero(self):
        self.original_deferred_signal(removed=True)
        self.discard_old_sell()
        with self.assertRaises(ValueError): self.authorize()
        self.authorize(quote_refresh=True); self.resume()
        for seconds in (1,2,3,4,5): self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual([(r['code'],r['side'],r['qty']) for r in FakeBroker.submissions],[('US.MSFT','SELL',17),('US.AAPL','BUY',9)])
        self.assertEqual(self.engine._get('best_same_day_catchup',{})['deferred_buy_targets'],{'US.MSFT':0})

    def test_manual_resolution_survives_restart_without_duplicate_sell_or_resizing(self):
        self.new_permission()
        with self.priced(msft=200): self.tick_at(self.now+timedelta(seconds=1))
        proof=deepcopy(self.engine._get('best_same_day_catchup',{}))
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine)
        FakeBroker.clock=staticmethod(lambda:self.now+timedelta(seconds=2)); self.connect()
        with self.priced(msft=40):
            for seconds in (2,3,4,5): self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual(self.engine._get('best_same_day_catchup',{})['deferred_buy_targets'],proof['deferred_buy_targets'])
        self.assertEqual(len(FakeBroker.submissions),2)
        self.assertEqual(self.runner.status,'EXECUTED')

    def test_manual_strict_boolean_and_six_hundred_second_window(self):
        self.original_deferred_signal(); self.discard_old_sell()
        for value in (1,None,'true',[]):
            with self.subTest(value=value),self.assertRaises(ValueError): self.authorize(quote_refresh=value)
        for deadline in (self.now,self.now+timedelta(seconds=601)):
            with self.subTest(deadline=deadline),self.assertRaises(ValueError): self.authorize(quote_refresh=True,deadline_utc=deadline.isoformat())
        self.authorize(quote_refresh=True); self.resume(); self.tick_at(self.deadline)
        self.assertEqual(FakeBroker.submissions,[])

    def test_manual_binding_rejects_original_resolved_scope_and_audit_tampering(self):
        self.new_permission()
        with self.priced(msft=200): self.tick_at(self.now+timedelta(seconds=1))
        proof=deepcopy(self.engine._get('best_same_day_catchup',{}))
        state=deepcopy(self.engine._get('best_execution',{}))
        for kind in ('scope','original','sell_target','buy_target','proof','record_removed','account'):
            value=deepcopy(proof)
            if kind=='scope': value['eligible_codes'].append('US.OTHER')
            if kind=='original': value['original_execution']['target_quantities']['US.AAPL']=99
            if kind=='sell_target': value['deferred_sell_targets']['US.MSFT']=1
            if kind=='buy_target': value['deferred_buy_targets']['US.MSFT']=99
            if kind=='proof': value['new_quantity_records'][0]['held_before']=99
            if kind=='record_removed': value['new_quantity_records']=[]
            if kind=='account': value['account_id']='other'
            self.engine._set('best_same_day_catchup',value)
            with self.subTest(kind=kind),self.assertRaises(ValueError): self.runner._catchup_end()
        self.engine._set('best_same_day_catchup',proof); self.engine._set('best_execution',state)
        self.engine.db.execute("DELETE FROM audit WHERE event='MANUAL_REMAINDER_QUOTE_TARGET_RESOLVED'"); self.engine.db.commit()
        with self.assertRaises(ValueError): self.runner._catchup_end()

    def test_manual_stale_or_wide_quote_never_resolves_a_new_quantity(self):
        self.new_permission()
        original=FakeBroker.snapshot_partial
        for kind in ('stale','wide'):
            def invalid(broker,codes):
                value=original(broker,codes)
                for quote in value['quotes'].values():
                    if kind=='stale': quote['asof']=(self.now-timedelta(seconds=31)).isoformat()
                    else: quote.update(bid=90,ask=110)
                return value
            with patch.object(FakeBroker,'snapshot_partial',invalid): self.tick_at(self.now+timedelta(seconds=1))
            self.assertEqual(FakeBroker.submissions,[])
            self.assertEqual(self.engine._get('best_same_day_catchup',{})['new_quantity_records'],[])


    def resolved_but_unsent(self):
        self.new_permission()
        stamp = self.now + timedelta(seconds=1)
        FakeBroker.clock = staticmethod(lambda: stamp)
        with self.priced(msft=200):
            snap = self.engine.broker.snapshot_partial(['US.MSFT', 'US.AAPL'])
            state = self.runner._partial_execution(stamp, 'SELL', snap, sell_codes={'US.MSFT'}, resume_buy_state=deepcopy(self.original_state))
        proof = deepcopy(self.engine._get('best_same_day_catchup', {}))
        self.assertLess(proof['deferred_sell_targets']['US.MSFT'], 17)
        self.assertEqual(FakeBroker.submissions, [])
        return (proof, state)

    def assert_qualified_quote_later_finishes(self, proof, restart=False):
        if restart:
            self.runner = BestBroker(self.temp.name, self.source, engine=self.engine)
            FakeBroker.clock = staticmethod(lambda: self.now + timedelta(seconds=3))
            self.connect()
        FakeBroker.quote_errors = {}
        with self.priced(msft=40, aapl=40):
            for seconds in (3, 4, 5, 6):
                self.tick_at(self.now + timedelta(seconds=seconds))
        self.assertEqual([(o['code'], o['side'], o['qty']) for o in FakeBroker.submissions], [('US.MSFT', 'SELL', 17 - proof['deferred_sell_targets']['US.MSFT']), ('US.AAPL', 'BUY', 9)])
        self.assertEqual(FakeBroker.positions['US.MSFT'], proof['deferred_sell_targets']['US.MSFT'])
        self.assertEqual(self.engine._get('best_same_day_catchup', {}), proof)
        self.assertEqual(self.engine._get('best_execution', {})['phase'], 'DONE')

    def test_wide_quote_keeps_fixed_manual_sell_then_good_quote_finishes(self):
        proof, before = self.resolved_but_unsent()
        original = FakeBroker.snapshot_partial

        def wide(broker, codes):
            snap = original(broker, codes)
            snap['quotes']['US.MSFT'].update(bid=90, ask=110)
            return snap
        with patch.object(FakeBroker, 'snapshot_partial', wide):
            self.tick_at(self.now + timedelta(seconds=2))
        current = self.engine._get('best_execution', {})
        self.assertEqual(self.runner.status, 'WAITING_QUOTES')
        self.assertEqual(current['phase'], 'SELL')
        self.assertEqual(current['target_quantities'], before['target_quantities'])
        self.assertEqual(current['resume_buy_state'], self.original_state)
        self.assertEqual(self.engine._get('best_same_day_catchup', {}), proof)
        self.assertEqual(FakeBroker.submissions, [])
        self.assert_qualified_quote_later_finishes(proof)

    def test_missing_quote_wait_is_durable_and_restart_uses_fixed_target(self):
        proof, before = self.resolved_but_unsent()
        FakeBroker.quote_errors = {'US.MSFT': 'synthetic missing quote'}
        self.tick_at(self.now + timedelta(seconds=2))
        current = self.engine._get('best_execution', {})
        self.assertEqual(self.runner.status, 'WAITING_QUOTES')
        self.assertEqual(current['phase'], 'SELL')
        self.assertEqual(current['target_quantities'], before['target_quantities'])
        self.assertEqual(current['resume_buy_state'], self.original_state)
        self.assertEqual(FakeBroker.submissions, [])
        self.assert_qualified_quote_later_finishes(proof, restart=True)

    def test_waiting_does_not_extend_permission_or_send_at_deadline(self):
        proof, _ = self.resolved_but_unsent()
        FakeBroker.quote_errors = {'US.MSFT': 'synthetic missing quote'}
        self.tick_at(self.now + timedelta(seconds=2))
        self.assertEqual(self.runner.status, 'WAITING_QUOTES')
        self.tick_at(self.deadline)
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine._get('best_same_day_catchup', {}), proof)
        self.assertEqual(self.runner.status, 'MISSED_OPEN')


from pathlib import Path
import hashlib
def _closed_sha(raw):return hashlib.sha256(raw).hexdigest()

def _closed_write(path,value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode();path.write_bytes(raw);return {"path":str(path),"sha256":_closed_sha(raw)}

def _closed_decision_fixture(root,signal,plans):
    folder=Path(root)/"immutable_decision_fixture";folder.mkdir()
    refs={}
    keys=["frozen_calendar","session_hours_rules","daily/report.json","selected/current_report.json","current/features.parquet","current/mapped_members.parquet","current/report.json","current/selected_hgb_features.parquet"]
    for i,key in enumerate(keys):
        f=folder/(str(i)+".bin");f.write_bytes(("synthetic economic input "+key).encode());refs[key]={"path":str(f),"sha256":_closed_sha(f.read_bytes())}
    tickers=list(dict.fromkeys(row.get("ticker") or row["code"][3:] for plan in plans.values() for row in plan["rows"]))
    tickers+=['SYN'+str(i) for i in range(40-len(tickers))]
    rows=[dict(ticker=t,security_id="SYNTHETIC_ID_"+t,raw_rank=i,raw_score=.1/i,pred_hgb=.2/i,hgb_rank=i) for i,t in enumerate(tickers,1)]
    scores=dict(model_id="HGB_2026092501",model_sha256="b"*64,ranking_basis="PRED_HGB_DESC_TICKER_ASC",scoring_scope="RAW_TOP40",current=dict(status="READY",signal_date=signal,requested_signal_date=signal,rows=rows))
    apps={}
    for sid,plan in plans.items():apps[sid]=dict(status="READY",signal_date=signal,policy_id="HGB_TOP20_RISK_R1",rows=[dict(ticker=r.get("ticker") or r['code'][3:],target_weight=r['target_weight']) for r in plan['rows']],target_cash_weight=plan['target_cash_weight'])
    if "HGB_FACTOR_5" not in apps:apps['HGB_FACTOR_5']=deepcopy(apps[SID])
    snapshot=dict(signal_date=signal,policy_id="HGB_TOP20_RISK_R1",shared_scores={**{k:v for k,v in scores.items() if k!='current'},"rows":rows},applications=deepcopy(apps))
    snapref=_closed_write(folder/'snapshot.json',snapshot);history="history/"+signal+".json"
    protected={"frozen/model":"b"*64,"policy/frozen_contract":"c"*64,"current/report.json":refs['current/report.json']['sha256'],"current/selected_hgb_features.parquet":refs['current/selected_hgb_features.parquet']['sha256'],history:snapref['sha256']}
    package=dict(policy_id="HGB_TOP20_RISK_R1",model_fit_calls=0,broker_action_allowed=False,shared_scores=deepcopy(scores),strategies={sid:{"application":app} for sid,app in apps.items()},source_refs={history:snapref},source_hashes={**protected,"performance_extension/manifest":"d"*64},performance_period={"end":signal})
    pkgref=_closed_write(folder/'latest.json',package);refs['selected/package.json']=pkgref
    archived=dict(scores=deepcopy(scores),source_hashes=deepcopy(package['source_hashes']),plans=deepcopy(plans))
    ar=_closed_write(folder/'plans.json',archived)
    return dict(refs=refs,package=package,snapshot=snapshot,archive=archived,archive_ref=ar,folder=folder)

class ClosedBrokerTests(unittest.TestCase):
    setUp=BestBrokerTests.setUp;tearDown=BestBrokerTests.tearDown
    connect=BestBrokerTests.connect;partial_runner=BestBrokerTests.partial_runner
    tick_at=BestBrokerTests.tick_at;full_reset_fixture=BestBrokerTests.full_reset_fixture
    published_rebalance_fixture=BestBrokerTests.published_rebalance_fixture;reset_connect=BestBrokerTests.reset_connect
    def make(self):
        request=self.published_rebalance_fixture();self.runner.prepare_current_target_rebalance(request['reset_id'],now=self.opening-timedelta(hours=1))
        saved=deepcopy(self.engine._get('best_plan',{}));d=_closed_decision_fixture(self.temp.name,saved['metadata']['signal_date'],{SID:saved['plan']})
        saved['plan']['source_refs']=deepcopy(d['refs']);saved['metadata']['source_refs']=deepcopy(d['refs']);saved['metadata']['archive']=d['archive_ref']
        ar=self.engine._get('best_reset_archive',{});receipt=ar[request['reset_id']]['cancellation']['published_target_rebalance'];receipt.update(plan_sha256=self.runner._content_sha(saved['plan']),metadata_sha256=self.runner._content_sha(saved['metadata']),package_sha256=d['refs']['selected/package.json']['sha256'])
        self.engine._set('best_reset_archive',ar);self.engine._set('best_plan',saved)
        self.engine._set('best_execution',dict(signal_date=saved['metadata']['signal_date'],phase='BUY',processed_codes=['US.AAPL'],deferred_sells=[dict(code='US.MSFT',reason='synthetic stale original quote')],skipped=[dict(code='US.MSFT',reason='synthetic stale original quote')],target_quantities={'US.AAPL':9},phase_asof=(self.opening+timedelta(seconds=1)).isoformat()))
        self.saved,self.d,self.auth=saved,d,deepcopy(ar)
        self.live={**deepcopy(saved['metadata']),'status':'MISSED_OPEN','ready':False,'source_date':saved['metadata']['signal_date'],'source_refs':deepcopy(d['refs'])}
        self.source.status=lambda now=None:deepcopy(self.live)
        self.reset_connect();self.now=self.opening+timedelta(seconds=601);self.runner._now=lambda:self.now
        self.republish()
    def republish(self):
        self.d['package']['performance_period']['end']='2026-09-28'
        self.d['package']['source_hashes']['performance_extension/manifest']='e'*64
        self.live['source_refs']['selected/package.json']=_closed_write(self.d['folder']/'latest.json',self.d['package'])
    def frozen(self):
        return dict(saved=self.engine._get('best_plan',{}),auth=self.engine._get('best_reset_archive',{}),execution=self.engine._get('best_execution',{}),orders=[tuple(x) for x in self.engine.db.execute('select * from orders order by id')],fills=[tuple(x) for x in self.engine.db.execute('select * from order_fills order by id')],cash=FakeBroker.cash,positions=deepcopy(FakeBroker.positions))
    def test_closed_chart_only_restores_original_partial_without_sdk_or_trade_or_replan(self):
        self.make();before=self.frozen()
        with patch.object(self.source,'load',side_effect=AssertionError('no inference')),patch.object(self.source,'close_states',side_effect=AssertionError('no old close')),patch.object(FakeBroker,'snapshot',side_effect=AssertionError('no SDK')),patch.object(self.engine,'step',side_effect=AssertionError('no step')):
            self.runner.tick(now=self.now);state=self.runner.state()
        self.assertEqual(self.frozen(),before);self.assertEqual(state['status'],'PARTIALLY_EXECUTED');self.assertIn('US.MSFT',state['reason']);self.assertEqual(state['plan'],self.saved['plan']);self.assertEqual(FakeBroker.submissions,[])
    def test_exact_normal_deadline_never_sends_or_extends(self):
        self.make();self.now=self.opening+timedelta(seconds=600);self.runner.tick(now=self.now)
        self.assertEqual(FakeBroker.submissions,[]);self.assertEqual(self.runner.execution_window_seconds,600);self.assertEqual(self.runner.execution_delay_minutes,0)
    def test_active_window_still_rejects_chart_hash_change(self):
        self.make()
        with self.assertRaisesRegex(ValueError,'PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):self.runner._prepare(self.opening+timedelta(seconds=599))
        self.assertIsNone(self.runner.plan)
    def test_future_registered_manual_deadline_still_rejects_chart_hash_change(self):
        self.make();self.engine._set('best_same_day_catchup',dict(signal_date=self.saved['metadata']['signal_date'],deadline_utc=(self.now+timedelta(seconds=1)).isoformat()))
        with self.assertRaisesRegex(ValueError,'PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):self.runner._prepare(self.now)
    def test_pending_order_never_enters_closed_exception(self):
        self.make();self.engine.db.execute("update orders set status='PENDING_RECONCILE' where id=(select id from orders limit 1)");self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):self.runner._prepare(self.now)
    def test_source_score_target_cash_policy_security_and_fit_changes_rejected(self):
        self.make();baseline=deepcopy(self.d['package'])
        for kind in ['score','security','diag_weight','factor_weight','cash','policy','fit','broker_flag','frozen_hash','current_hash']:
            with self.subTest(kind=kind):
                self.d['package']=deepcopy(baseline);pkg=self.d['package'];app=pkg['strategies'][SID]['application']
                if kind=='score':pkg['shared_scores']['current']['rows'][0]['pred_hgb']+=.01
                if kind=='security':pkg['shared_scores']['current']['rows'][0]['security_id']='NEW_ID'
                if kind=='diag_weight':app['rows'][0]['target_weight']+=.01
                if kind=='factor_weight':pkg['strategies']['HGB_FACTOR_5']['application']['rows'][0]['target_weight']+=.01
                if kind=='cash':app['target_cash_weight']-=.01
                if kind=='policy':pkg['policy_id']='WRONG_POLICY'
                if kind=='fit':pkg['model_fit_calls']=1
                if kind=='broker_flag':pkg['broker_action_allowed']=True
                if kind=='frozen_hash':pkg['source_hashes']['frozen/model']='f'*64
                if kind=='current_hash':pkg['source_hashes']['current/report.json']='f'*64
                self.republish()
                with self.assertRaisesRegex(ValueError,'PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):self.runner._prepare(self.now)
                self.assertIsNone(self.runner.plan);self.assertEqual(self.engine._get('best_plan',{}),self.saved)
    def test_actual_omitted_economic_input_bytes_and_snapshot_hash_rejected(self):
        self.make();ref=self.saved['metadata']['source_refs']['current/mapped_members.parquet'];Path(ref['path']).write_bytes(b'changed actual identity')
        self.live['source_refs'].pop('current/mapped_members.parquet')
        with self.assertRaisesRegex(ValueError,'PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED'):self.runner._prepare(self.now)
    def test_tampered_snapshot_and_archive_or_saved_receipt_rejected(self):
        self.make();snap=self.d['package']['source_refs']['history/'+self.saved['metadata']['signal_date']+'.json'];raw=Path(snap['path']).read_bytes()
        Path(snap['path']).write_bytes(raw+b' ')
        with self.assertRaises(ValueError):self.runner._prepare(self.now)
        Path(snap['path']).write_bytes(raw);a=self.d['archive_ref'];araw=Path(a['path']).read_bytes();Path(a['path']).write_bytes(araw+b' ')
        with self.assertRaises(ValueError):self.runner._prepare(self.now)
        Path(a['path']).write_bytes(araw);changed=deepcopy(self.saved);changed['plan']['rows'][0]['target_weight']+=.01;self.engine._set('best_plan',changed)
        with self.assertRaisesRegex(ValueError,'PUBLISHED_TARGET_AUTHORIZATION_CHANGED'):self.runner._prepare(self.now)
    def test_current_ref_path_or_hash_change_cannot_use_same_chart_exception(self):
        self.make();self.live['source_refs']['current/features.parquet']['sha256']='f'*64
        with self.assertRaises(ValueError):self.runner._prepare(self.now)
    def test_expired_manual_deadline_and_receipt_remain_frozen(self):
        self.make();state=self.engine._get('best_execution',{});state['deferred_sells']=[];self.engine._set('best_execution',state)
        self.now=self.opening+timedelta(seconds=1201)
        record=dict(signal_date=self.saved['metadata']['signal_date'],execution_date=self.saved['metadata']['execution_date'],
            account_id=self.engine.account_id,budget=self.runner.budget,deadline_utc=(self.opening+timedelta(seconds=1200)).isoformat(),
            source_hash=hashlib.sha256(json.dumps(self.saved['plan']['source_refs'],sort_keys=True).encode()).hexdigest())
        self.engine._set('best_same_day_catchup',record);before=self.frozen()
        self.runner.tick(now=self.now)
        self.assertEqual(self.engine._get('best_same_day_catchup',{}),record);self.assertEqual(self.frozen(),before)
        self.assertEqual(self.runner.status,'PARTIALLY_EXECUTED');self.assertEqual(FakeBroker.submissions,[])
    def test_invalid_expired_registered_permission_never_becomes_closed_validity(self):
        self.make();self.engine._set('best_same_day_catchup',dict(signal_date=self.saved['metadata']['signal_date'],
            deadline_utc=(self.now-timedelta(seconds=1)).isoformat()))
        with self.assertRaisesRegex(ValueError,'EXPIRED_MANUAL_PERMISSION_INVALID'):self.runner._prepare(self.now)
        self.assertIsNone(self.runner.plan);self.assertEqual(self.engine._get('best_plan',{}),self.saved)
    def test_next_signal_uses_original_close_and_load_path(self):
        self.make();new={**self.live,'signal_date':'2026-09-28','source_date':'2026-09-28','execution_date':'2026-09-29','next_open_utc':'2026-09-29T13:30:00+00:00','signal_close_utc':'2026-09-28T20:00:00+00:00'}
        self.live=new;observed=[]
        def close(books,signal_date):observed.append(('close',signal_date));return {SID:dict(weights={},cash_weight=1,signal_date=signal_date,valuation_basis='SIGNAL_CLOSE')}
        def load(states,now=None):observed.append(('load',states[SID]['signal_date']));return {**new,'plans':{SID:dict(rows=[],target_cash_weight=1)}}
        with patch.object(self.source,'close_states',side_effect=close),patch.object(self.source,'load',side_effect=load):self.runner._prepare(self.opening+timedelta(days=1)-timedelta(minutes=1))
        self.assertEqual(observed,[('close','2026-09-28'),('load','2026-09-28')]);self.assertFalse(self.runner._closed_current_signal)


class OriginalSellCatchupTests(unittest.TestCase):
    """Explicit main-SELL remainder reuses the normal owner, fake SIMULATE only."""
    setUp = BestBrokerTests.setUp
    tearDown = BestBrokerTests.tearDown
    partial_runner = BestBrokerTests.partial_runner
    connect = BestBrokerTests.connect
    tick_at = BestBrokerTests.tick_at

    def make_sell(self, pending=False):
        self.source.rows = [{"code":"US.AAPL","target_weight":.1}, {"code":"US.MSFT","target_weight":.09}, {"code":"US.ZERO","target_weight":0}]
        self.partial_runner(delay=0)
        old = (self.opening - timedelta(days=3)).isoformat()
        for code, qty in (("US.MSFT",17),("US.ZERO",5)):
            self.engine.db.execute("INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("old-"+code,old,SID,"moomoo_simulate","3604",code,"BUY",qty,100,"FILLED_ALL","old-broker-"+code))
            self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",("old-"+code,json.dumps({"fill_qty":qty,"fill_price":100,"filled_at":old})))
        self.engine.db.commit()
        FakeBroker.positions, FakeBroker.cash = {"US.MSFT":17,"US.ZERO":5}, 997800
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        FakeBroker.quote_errors = {"US.ZERO":"synthetic missing original SELL quote"}
        self.tick_at(self.opening + timedelta(seconds=1))
        if not pending: self.engine.reconcile()
        self.runner.stop()
        self.original_state=deepcopy(self.engine._get("best_execution",{}))
        self.original_plan=deepcopy(self.engine._get("best_plan",{}))
        self.assertEqual(self.original_state["phase"],"SELL")
        self.assertNotIn("resume_buy_state",self.original_state)
        self.now=self.opening+timedelta(seconds=601); self.deadline=self.now+timedelta(seconds=600)

    def authorize(self, **kwargs):
        args=dict(execution_date="2026-09-28",deadline_utc=self.deadline.isoformat(),account_id="3604",now=self.now,include_deferred_sells=True,quote_refresh=True)
        args.update(kwargs);return self.runner.authorize_catchup(**args)

    def resume(self):
        FakeBroker.quote_errors={};self.engine.cancel_step.clear();self.runner.stop_event.clear()

    def test_original_sell_then_normal_buy_keeps_old_fills_and_no_duplicate_sell(self):
        self.make_sell();old_orders=deepcopy(self.engine.state()["orders"])
        permission=self.authorize();self.assertTrue(permission["original_sell_stage"])
        self.assertEqual(permission["original_execution"],self.original_state)
        self.assertEqual(self.engine._get("best_plan",{}),self.original_plan)
        self.resume()
        for seconds in range(1,7):self.tick_at(self.now+timedelta(seconds=seconds))
        orders=self.engine.state()["orders"]
        self.assertEqual([(x["code"],x["side"]) for x in FakeBroker.submissions],[("US.MSFT","SELL"),("US.ZERO","SELL"),("US.AAPL","BUY")])
        self.assertEqual(FakeBroker.positions["US.MSFT"],8)
        self.assertEqual(FakeBroker.positions["US.ZERO"],0)
        self.assertGreater(FakeBroker.positions["US.AAPL"],0)
        for old in old_orders:self.assertIn(old,orders)
        self.assertEqual(self.engine._get("best_plan",{}),self.original_plan)
        self.assertEqual(self.runner.execution_window_seconds,600)
        self.tick_at(self.now+timedelta(seconds=10));self.assertEqual(len(FakeBroker.submissions),3)

    def test_invalid_source_state_and_permission_changes_fail_closed(self):
        self.make_sell();self.authorize();self.resume()
        record=deepcopy(self.engine._get("best_same_day_catchup",{}));state=deepcopy(self.engine._get("best_execution",{}))
        for kind in ("original_state","plan","quantity","current_state","account"):
            with self.subTest(kind=kind):
                changed=deepcopy(record);current=deepcopy(state);plan=deepcopy(self.runner.plan)
                if kind=="original_state":changed["original_execution"]["target_quantities"]["US.MSFT"]=7
                if kind=="plan":self.runner.plan["rows"][0]["target_weight"]=.05
                if kind=="quantity":changed["resolved_sell_targets"]["US.MSFT"]=7
                if kind=="current_state":current["processed_codes"]=["US.ZERO"]
                if kind=="account":self.engine.account_id="different"
                self.engine._set("best_same_day_catchup",changed);self.engine._set("best_execution",current)
                with self.assertRaises(ValueError):self.runner._catchup_end()
                self.runner.plan=plan;self.engine.account_id="3604"
        self.engine._set("best_same_day_catchup",record);self.engine._set("best_execution",state)
        self.assertEqual(len(FakeBroker.submissions),1)

    def test_pending_and_wrong_scope_authorization_refuse_without_mutation(self):
        self.make_sell(pending=True)
        with self.assertRaisesRegex(ValueError,"订单尚未"):self.authorize()
        self.assertIsNone(self.engine._get("best_same_day_catchup",None));self.engine.reconcile()
        for changes in ({"account_id":"wrong"},{"execution_date":"2026-09-29"},{"deadline_utc":(self.now+timedelta(seconds=601)).isoformat()},{"quote_refresh":False}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.authorize(**changes)
        self.assertIsNone(self.engine._get("best_same_day_catchup",None))
        self.assertEqual(self.engine._get("best_execution",{}),self.original_state)

    def test_quote_batch_crossing_manual_deadline_never_sends(self):
        self.make_sell();self.authorize();self.resume();before=len(FakeBroker.submissions)
        original=FakeBroker.snapshot_partial
        current=[self.now+timedelta(seconds=1)]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return current[0] if tz is None else current[0].astimezone(tz)
        FakeBroker.clock=staticmethod(lambda:current[0])
        def slow(broker,codes):
            result=original(broker,codes)
            current[0]=self.deadline
            return result
        with patch.object(FakeBroker,"snapshot_partial",slow), patch("moomoo_component.best_broker.datetime",Clock), \
                patch("moomoo_component.core.datetime",Clock), patch("moomoo_component.strategy.datetime",Clock):
            self.runner.tick(now=current[0])
        self.assertEqual(len(FakeBroker.submissions),before)
        self.assertEqual(self.runner.status,"PARTIALLY_EXECUTED")

    def test_unqualified_quotes_keep_gap_then_current_owner_resolves_once(self):
        for invalid in ("missing","stale","spread","tradable"):
            with self.subTest(invalid=invalid):
                if invalid!="missing":
                    # Each quote failure has an isolated canonical fake account.
                    self.tearDown();self.setUp()
                self.make_sell();self.authorize();self.resume();before=len(FakeBroker.submissions)
                original=FakeBroker.snapshot_partial
                def bad(broker,codes):
                    result=original(broker,codes)
                    quote=result["quotes"].get("US.ZERO")
                    if invalid=="missing":result["quotes"].pop("US.ZERO",None);result.setdefault("quote_errors",{})["US.ZERO"]="synthetic missing"
                    if invalid=="stale" and quote:quote["asof"]=(self.now-timedelta(seconds=31)).isoformat()
                    if invalid=="spread" and quote:quote.update(bid=90,ask=110)
                    if invalid=="tradable" and quote:quote["tradable"]=False
                    return result
                with patch.object(FakeBroker,"snapshot_partial",bad):self.tick_at(self.now+timedelta(seconds=1))
                self.assertFalse(any(x["side"]=="SELL" and x["code"]=="US.ZERO" for x in FakeBroker.submissions))
                for sec in range(2,9):self.tick_at(self.now+timedelta(seconds=sec))
                self.assertEqual(sum(x["side"]=="SELL" and x["code"]=="US.ZERO" for x in FakeBroker.submissions),1)

    def test_restart_does_not_duplicate_filled_sell_or_resolved_target(self):
        self.make_sell();permission=self.authorize();self.resume();self.tick_at(self.now+timedelta(seconds=1));self.engine.reconcile()
        original=deepcopy(self.engine._get("best_same_day_catchup",{}));self.runner.close()
        self.engine=Engine(self.temp.name,broker_factory=FakeBroker)
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
        self.connect();self.engine.cancel_step.clear();self.runner.stop_event.clear()
        for sec in range(2,8):self.tick_at(self.now+timedelta(seconds=sec))
        self.assertEqual(sum(x["side"]=="SELL" and x["code"]=="US.ZERO" for x in FakeBroker.submissions),1)
        self.assertEqual(sum(x["side"]=="SELL" and x["code"]=="US.MSFT" for x in FakeBroker.submissions),1)
        self.assertEqual(self.engine._get("best_same_day_catchup",{})["resolved_sell_targets"],original["resolved_sell_targets"])


    def make_nested_sell(self):
        # Original owner reaches a SELL detour carrying a partially filled BUY.
        SameDayRemainderTests.original_deferred_signal(self, with_processed_extra=True)
        stamp=(self.opening+timedelta(seconds=20)).isoformat()
        self.engine.db.execute("INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("partial-aapl",stamp,SID,"moomoo_simulate","3604","US.AAPL","BUY",9,100,"CANCELLED_PART","partial-broker"))
        self.engine.db.execute("INSERT INTO order_fills VALUES (?,?)",("partial-aapl",json.dumps({"fill_qty":4,"fill_price":100,"filled_at":stamp})))
        self.engine.db.commit()
        FakeBroker.positions["US.AAPL"]=4;FakeBroker.cash-=400
        self.engine.cancel_step.clear();self.runner.stop_event.clear()
        FakeBroker.quote_errors={"US.AAPL":"synthetic original BUY still missing"}
        with self.assertRaises(BrokerReadError):self.tick_at(self.opening+timedelta(seconds=33))
        self.runner.stop()
        self.original_state=deepcopy(self.engine._get("best_execution",{}))
        self.original_plan=deepcopy(self.engine._get("best_plan",{}))
        self.assertEqual(self.original_state["phase"],"SELL")
        buy=self.original_state["resume_buy_state"]
        self.assertEqual(buy["phase"],"BUY");self.assertEqual(buy["target_quantities"],{"US.AAPL":9,"US.DNA":0})
        self.assertIn("US.DNA",buy["processed_codes"])
        self.now=self.opening+timedelta(seconds=601);self.deadline=self.now+timedelta(seconds=600)

    def test_nested_original_buy_quantities_progress_and_partial_fill_are_preserved(self):
        self.make_nested_sell();old_orders=deepcopy(self.engine.state()["orders"])
        nested=deepcopy(self.original_state["resume_buy_state"])
        record=self.authorize();self.assertEqual(record["original_execution"]["resume_buy_state"],nested)
        self.assertEqual(record["resolved_buy_targets"],nested["target_quantities"])
        self.resume();FakeBroker.before_send_error=None
        for seconds in range(1,39):self.tick_at(self.now+timedelta(seconds=seconds))
        self.assertEqual(sum(x["side"]=="SELL" and x["code"]=="US.MSFT" for x in FakeBroker.submissions),1)
        self.assertEqual(sum(x["side"]=="BUY" and x["code"]=="US.AAPL" for x in FakeBroker.submissions),1)
        self.assertEqual(next(x["qty"] for x in FakeBroker.submissions if x["side"]=="BUY" and x["code"]=="US.AAPL"),5)
        self.assertFalse(any(x["code"]=="US.DNA" for x in FakeBroker.submissions))
        self.assertEqual(FakeBroker.positions["US.AAPL"],9);self.assertEqual(FakeBroker.positions["US.MSFT"],8)
        latest=self.engine._get("best_same_day_catchup",{})
        self.assertEqual(latest["original_execution"]["resume_buy_state"],nested)
        self.assertEqual(latest["resolved_buy_targets"]["US.AAPL"],9)
        self.assertEqual(self.engine._get("best_plan",{}),self.original_plan)
        for old in old_orders:self.assertIn(old,self.engine.state()["orders"])

    def test_invalid_nested_buy_identity_or_plan_refuses_new_permission(self):
        self.make_nested_sell();original=deepcopy(self.original_state)
        for key,value in (("phase","SELL"),("signal_date","2026-09-24"),("original_target_weights",{}),("original_target_cash_weight",1),("target_quantities",{"US.AAPL":True})):
            with self.subTest(key=key):
                changed=deepcopy(original);changed["resume_buy_state"][key]=value
                self.engine._set("best_execution",changed)
                with self.assertRaises(ValueError):self.authorize()
                self.assertIsNone(self.engine._get("best_same_day_catchup",None))
        self.engine._set("best_execution",original)
        self.assertEqual(FakeBroker.submissions,[])

    def test_nested_buy_qty_processed_and_phase_asof_tampering_refuse_resume(self):
        self.make_nested_sell();record=self.authorize();original=deepcopy(self.original_state)
        for key,value in (("target_quantities",{"US.AAPL":10,"US.DNA":0}),("processed_codes",[]),("phase_asof",self.now.isoformat())):
            with self.subTest(key=key):
                changed=deepcopy(original);changed["resume_buy_state"][key]=value
                self.engine._set("best_execution",changed)
                with self.assertRaisesRegex(ValueError,"BINDING_CHANGED"):self.runner._catchup_end()
        self.engine._set("best_execution",original)
        self.assertEqual(self.engine._get("best_same_day_catchup",{}),record)
        self.assertEqual(FakeBroker.submissions,[])

    def test_done_progress_hash_is_atomic_and_restart_does_not_reauthorize_or_send(self):
        self.make_sell();self.authorize();self.resume()
        for seconds in range(1,8):self.tick_at(self.now+timedelta(seconds=seconds))
        state=self.engine._get("best_execution",{});record=self.engine._get("best_same_day_catchup",{})
        self.assertEqual(state["phase"],"DONE")
        self.assertEqual(record["latest_execution_sha256"],self.runner._content_sha(state))
        progress=json.loads(self.engine.db.execute("SELECT detail FROM audit WHERE event='ORIGINAL_SELL_REMAINDER_PROGRESS' ORDER BY rowid DESC LIMIT 1").fetchone()[0])
        self.assertEqual(progress["execution_sha256"],record["latest_execution_sha256"])
        self.runner._original_sell_stage_binding(record,state)
        count=len(FakeBroker.submissions);self.runner.close()
        self.engine=Engine(self.temp.name,broker_factory=FakeBroker)
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine,execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
        self.connect();self.runner.stop()
        with self.assertRaises(ValueError):self.authorize()
        self.assertIsNone(self.runner._catchup_end())
        self.engine.cancel_step.clear();self.runner.stop_event.clear()
        self.tick_at(self.now+timedelta(seconds=20))
        self.assertEqual(len(FakeBroker.submissions),count)
        self.assertEqual(self.engine._get("best_execution",{}),state)
        self.assertEqual(self.engine._get("best_same_day_catchup",{}),record)

    def test_prior_day_quote_refresh_has_no_manual_asof_sell_buffer_or_deadline_effect(self):
        self.make_sell();permission=self.authorize();count=len(FakeBroker.submissions)
        opening=self.opening+timedelta(days=1);now=opening+timedelta(seconds=1)
        self.runner.metadata={**self.runner.metadata,"signal_date":"2026-09-28","execution_date":"2026-09-29",
            "signal_close_utc":"2026-09-28T20:00:00+00:00","next_open_utc":opening.isoformat(),
            "next_close_utc":(opening+timedelta(hours=6,minutes=30)).isoformat()}
        self.runner.plan={**self.runner.plan,"rows":[{"code":"US.MSFT","target_weight":.093}],"target_cash_weight":.907}
        unused=self.engine._get("best_capital",{})["unused_cash"]
        quote=dict(price=100,bid=99.99,ask=100.01,asof=now.isoformat(),lot_size=1,price_tick=.01,tradable=True)
        snap=dict(cash=unused+8000,positions={"US.MSFT":{"qty":20,"sellable":20,"market_value":2000}},quotes={"US.MSFT":quote},quote_errors={})
        for original_sell in (False,True):
            with self.subTest(original_sell_stage=original_sell):
                old={**permission,"original_sell_stage":original_sell};self.engine._set("best_same_day_catchup",old)
                self.engine._set("best_execution",{})
                with patch.object(self.runner,"_desired_quantity",wraps=self.runner._desired_quantity) as sizing:
                    state=self.runner._partial_execution(now,"SELL",snap)
                self.assertFalse(sizing.call_args.kwargs["buy"])
                self.assertEqual(state["target_quantities"]["US.MSFT"],9)
                self.assertEqual(state["manifest"]["asof"],now.isoformat())
                origin=json.loads(state["manifest"]["source"])
                self.assertNotIn("manual_remainder_intent",origin);self.assertNotIn("manual_authorized_at_utc",origin)
                self.assertEqual(state["manifest"]["expires_at"],(opening+timedelta(seconds=600)).isoformat())
                self.assertIsNone(self.runner._catchup_end());self.assertEqual(self.engine._get("best_same_day_catchup",{}),old)
                self.engine.cancel_step.clear()
                late=opening+timedelta(seconds=601)
                class Clock(datetime):
                    @classmethod
                    def now(cls,tz=None):return late if tz is None else late.astimezone(tz)
                with patch("moomoo_component.core.datetime",Clock),patch("moomoo_component.strategy.datetime",Clock):
                    with self.assertRaises(ValueError):self.engine.step(respect_cancel=True,allow_partial_quotes=True,broker_order_type="MARKET")
                self.assertEqual(len(FakeBroker.submissions),count)


    def test_prior_signal_original_sell_permission_does_not_block_current_buy_authorization(self):
        self.make_sell();previous=self.authorize()
        self.tearDown();self.setUp()
        SameDayRemainderTests.original_deferred_signal(self,with_processed_extra=True)
        old={**previous,"signal_date":"2026-09-24","execution_date":"2026-09-25"}
        self.engine._set("best_same_day_catchup",old)
        original=deepcopy(self.engine._get("best_execution",{}));plan=deepcopy(self.engine._get("best_plan",{}))
        self.assertEqual(original["phase"],"BUY")
        permission=self.authorize()
        self.assertEqual(permission["signal_date"],"2026-09-25")
        self.assertEqual(permission["execution_date"],"2026-09-28")
        self.assertEqual(permission["reason"],"USER_MANUAL_REMAINDER_QUOTE_REFRESH")
        self.assertNotIn("original_sell_stage",permission)
        self.assertEqual(permission["original_execution"],original)
        self.assertEqual(self.engine._get("best_execution",{}),original)
        self.assertEqual(self.engine._get("best_plan",{}),plan)
        self.assertEqual(FakeBroker.submissions,[])


    def check_source_busy_state_projection(self, expired):
        self.make_sell();permission=self.authorize();self.resume()
        now=self.deadline+timedelta(seconds=1) if expired else self.now+timedelta(seconds=1)
        keys=("best_plan","best_execution","best_same_day_catchup")
        durable={key:deepcopy(self.engine._get(key,None)) for key in keys}
        orders=deepcopy(self.engine.state()["orders"]);count=len(FakeBroker.submissions)
        error="CANONICAL_SOURCE_WORKER_BUSY"
        with patch.object(self.source,"status",side_effect=ValueError(error)):
            with self.assertRaisesRegex(ValueError,error):self.runner._prepare(now)
        self.assertIsNone(self.runner.plan)
        self.runner.status="WAITING_SOURCE";self.runner.reason="Original canonical source worker is busy"
        self.runner.last_error=error
        expected_status=self.runner.status
        with patch.object(self.runner,"_now",return_value=now),patch.object(self.runner,"_execution_end",wraps=self.runner._execution_end) as deadline:
            view=self.runner.state()
        deadline.assert_not_called()
        self.assertTrue(view["running"]);self.assertEqual(view["status"],expected_status)
        self.assertEqual(view["last_error"],error);self.assertIsNone(view["plan"])
        self.assertIsNone(view["execution_deadline_utc"])
        for key,value in durable.items():self.assertEqual(self.engine._get(key,None),value)
        self.assertEqual(self.engine.state()["orders"],orders)
        self.assertEqual(len(FakeBroker.submissions),count)
        # A successful original preparation restores the frozen plan and strict binding.
        self.runner._prepare(now)
        self.assertEqual(self.runner.plan,durable["best_plan"]["plan"])
        with patch.object(self.runner,"_now",return_value=now),patch.object(self.runner,"_execution_end",wraps=self.runner._execution_end) as deadline:
            ready=self.runner.state()
        self.assertEqual(deadline.call_count,1)
        self.assertEqual(ready["execution_deadline_utc"],permission["deadline_utc"])
        if not expired:self.assertEqual(ready["next_expected_execution_utc"],self.opening.isoformat())
        else:self.assertIsNone(ready["next_expected_execution_utc"])
        self.assertEqual(ready["last_error"],"")  # Successful owner validation clears only the stale BUSY error.
        for key,value in durable.items():self.assertEqual(self.engine._get(key,None),value)
        self.assertEqual(self.engine.state()["orders"],orders);self.assertEqual(len(FakeBroker.submissions),count)
        changed=deepcopy(self.runner.plan);changed["rows"][0]["target_weight"]-=.01
        self.runner.plan=changed
        with self.assertRaisesRegex(ValueError,"ORIGINAL_SELL_REMAINDER_BINDING_CHANGED"):self.runner.state()
        self.runner.plan=deepcopy(durable["best_plan"]["plan"])
        self.assertEqual(len(FakeBroker.submissions),count)

    def test_source_busy_state_preserves_running_active_manual_permission_without_deadline(self):
        self.check_source_busy_state_projection(expired=False)

    def test_source_busy_state_preserves_running_expired_manual_permission_without_deadline(self):
        self.check_source_busy_state_projection(expired=True)


class ManualCatchupRenewalTests(unittest.TestCase):
    """Explicit one-session leases use only the existing synthetic SIMULATE broker."""
    setUp = BestBrokerTests.setUp
    tearDown = BestBrokerTests.tearDown
    connect = BestBrokerTests.connect
    partial_runner = BestBrokerTests.partial_runner
    tick_at = BestBrokerTests.tick_at
    original_deferred_signal = SameDayRemainderTests.original_deferred_signal
    authorize = SameDayRemainderTests.authorize
    resume = SameDayRemainderTests.resume
    discard_old_sell = ManualQuoteRefreshTests.discard_old_sell
    new_permission = ManualQuoteRefreshTests.new_permission
    priced = ManualQuoteRefreshTests.priced

    def expired_permission(self):
        self.new_permission(extra_unknown=True, with_processed_extra=True)
        FakeBroker.quote_errors = {'US.AAPL':'stale','US.MSFT':'stale','US.NVDA':'stale'}
        self.tick_at(self.now + timedelta(seconds=1))
        self.runner.stop()
        self.renew_now = self.deadline + timedelta(seconds=1)
        return deepcopy(self.engine._get('best_same_day_catchup', {}))

    def renew(self, **changes):
        prior = self.engine._get('best_same_day_catchup', {})
        buy = self.engine._get('best_execution', {})
        if buy.get('phase') == 'SELL': buy = buy['resume_buy_state']
        args = dict(execution_date='2026-09-28', deadline_utc=(self.renew_now+timedelta(seconds=590)).isoformat(),
            expected_prior_sha256=self.runner._content_sha(prior), renewal_id='explicit-once-1', now=self.renew_now,
            account_id='3604', allowed_codes=sorted(set(prior['eligible_codes'])-set(buy.get('processed_codes',[]))))
        args.update(changes)
        return self.runner.renew_catchup(**args)

    def test_explicit_renewal_preserves_original_bytes_once_and_replays_idempotently(self):
        prior = self.expired_permission()
        old_raw = self.engine.db.execute("SELECT value FROM settings WHERE key='best_same_day_catchup'").fetchone()[0]
        execution, plan = deepcopy(self.engine._get('best_execution', {})), deepcopy(self.engine._get('best_plan', {}))
        value = self.renew()
        self.assertEqual(self.engine.db.execute("SELECT value FROM settings WHERE key='best_same_day_catchup'").fetchone()[0], old_raw)
        self.assertEqual(value['prior_permission_raw'], old_raw)
        self.assertEqual(self.engine._get('best_execution', {}), execution)
        self.assertEqual(self.engine._get('best_plan', {}), plan)
        self.assertEqual(self.renew(), value)
        self.assertEqual(self.engine.db.execute("SELECT count(*) FROM audit WHERE event='BEST_CATCHUP_RENEWAL_AUTHORIZED'").fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,'ALREADY_AUTHORIZED'): self.renew(renewal_id='different')
        with self.assertRaises(ValueError): self.authorize(deadline_utc=value['deadline_utc'],now=self.renew_now,quote_refresh=True)
        self.assertEqual(self.runner._catchup_end().isoformat(),value['deadline_utc'])
        self.assertEqual(prior,self.engine._get('best_same_day_catchup', {}))

    def test_renewal_rejects_bad_scope_clock_hash_account_and_active_or_pending(self):
        self.expired_permission()
        for change in ({'expected_prior_sha256':'0'*64},{'allowed_codes':['US.DNA']},{'allowed_codes':[]},
                {'allowed_codes':['US.AAPL','US.AAPL']},{'account_id':'other'},
                {'deadline_utc':(self.renew_now+timedelta(seconds=601)).isoformat()},
                {'now':self.now+timedelta(seconds=1)}, {'execution_date':'2026-09-29'},
                {'now':self.renew_now.replace(tzinfo=None)}):
            with self.subTest(change=change),self.assertRaises(ValueError): self.renew(**change)
        self.runner.stop_event.clear()
        with self.assertRaisesRegex(ValueError,'STOPPED'): self.renew()
        self.runner.stop_event.set(); self.engine.halt_event.set()
        with self.assertRaisesRegex(ValueError,'RECONCILED'): self.renew()
        self.engine.halt_event.clear(); account=self.engine.broker.account_id; self.engine.broker.account_id='other'
        with self.assertRaises(ValueError): self.renew()
        self.engine.broker.account_id=account
        self.engine.db.execute("UPDATE orders SET status='UNKNOWN' WHERE id='old-msft'");self.engine.db.commit()
        with self.assertRaisesRegex(ValueError,'RECONCILED'): self.renew()
        self.assertIsNone(self.engine._get('best_same_day_catchup_renewal',None))

    def test_renewal_keeps_existing_resolution_prefix_and_fixed_buys_across_restart(self):
        self.new_permission(extra_unknown=True, with_processed_extra=True)
        FakeBroker.quote_errors={'US.AAPL':'stale','US.NVDA':'stale'}
        with self.priced(msft=200):
            self.tick_at(self.now+timedelta(seconds=1));self.tick_at(self.now+timedelta(seconds=2))
        self.runner.stop(); self.renew_now=self.deadline+timedelta(seconds=1)
        prior=deepcopy(self.engine._get('best_same_day_catchup',{}))
        self.assertTrue(prior['new_quantity_records'])
        value=self.renew(allowed_codes=['US.AAPL','US.NVDA'])
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine)
        FakeBroker.clock=staticmethod(lambda:self.renew_now+timedelta(seconds=1));self.connect();self.resume()
        with self.priced(msft=40,aapl=40,nvda=40):
            for sec in range(1,7): self.tick_at(self.renew_now+timedelta(seconds=sec))
        current=self.engine._get('best_same_day_catchup',{})
        self.assertEqual(current['new_quantity_records'][:len(prior['new_quantity_records'])],prior['new_quantity_records'])
        for name in ('deferred_sell_targets','deferred_buy_targets','resolved_buy_targets'):
            self.assertTrue(all(current[name][code]==qty for code,qty in prior[name].items()))
        self.assertEqual(FakeBroker.positions['US.AAPL'],9)
        self.assertTrue(set(row['code'] for row in FakeBroker.submissions[1:]).issubset({'US.AAPL','US.NVDA'}))
        self.assertFalse(any(row['code']=='US.DNA' for row in FakeBroker.submissions))
        self.assertEqual(self.runner._content_sha(value),self.runner._content_sha(self.engine._get('best_same_day_catchup_renewal',{})))

    def test_renewal_subset_filters_real_quote_and_order_scope(self):
        self.expired_permission();self.renew(allowed_codes=['US.MSFT'])
        FakeBroker.snapshot_calls=[]; self.resume()
        with self.priced(msft=200):
            for sec in range(1,5): self.tick_at(self.renew_now+timedelta(seconds=sec))
        self.assertTrue(FakeBroker.submissions)
        self.assertTrue(all(row['code']=='US.MSFT' for row in FakeBroker.submissions))
        self.assertTrue(all(set(codes).issubset({'US.MSFT'}) for codes,quoted in FakeBroker.snapshot_calls if quoted))
        self.assertNotIn('US.AAPL',FakeBroker.positions)

    def test_renewal_tamper_is_rejected_and_expiry_cannot_auto_renew(self):
        self.expired_permission();self.renew()
        old=deepcopy(self.engine._get('best_same_day_catchup_renewal',{}))
        for fault in ('audit','archive','allowed','quantity','prefix','plan'):
            self.engine.db.execute('SAVEPOINT renewal_tamper')
            try:
                if fault in ('audit','archive'):
                    event='BEST_CATCHUP_RENEWAL_AUTHORIZED' if fault=='audit' else 'BEST_CATCHUP_RENEWAL_PRIOR_ARCHIVED'
                    self.engine.db.execute('DELETE FROM audit WHERE event=?',(event,))
                elif fault=='allowed':
                    changed=deepcopy(old);changed['allowed_codes'].append('US.DNA')
                    self.engine.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(changed),'best_same_day_catchup_renewal'))
                elif fault in ('quantity','prefix'):
                    changed=deepcopy(self.engine._get('best_same_day_catchup',{}))
                    if fault=='quantity': changed['original_execution']['target_quantities']['US.AAPL']=100
                    else: changed['new_quantity_records'].append({'code':'US.DNA'})
                    self.engine.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(changed),'best_same_day_catchup'))
                else:
                    plan=self.runner.plan;self.runner.plan=deepcopy(plan);self.runner.plan['target_cash_weight']+=.01
                with self.subTest(fault=fault),self.assertRaises(ValueError): self.runner._catchup_end()
                if fault=='plan':self.runner.plan=plan
            finally:
                self.engine.db.execute('ROLLBACK TO renewal_tamper');self.engine.db.execute('RELEASE renewal_tamper')
        self.resume(); before=len(FakeBroker.submissions)
        self.tick_at(datetime.fromisoformat(old['deadline_utc']))
        self.assertEqual(len(FakeBroker.submissions),before)
        self.assertEqual(self.engine._get('best_same_day_catchup_renewal',{}),old)

    def test_known_thirteen_mass_cap_and_zero_weight_kdk_exit_never_reverse_after_renewal(self):
        self.source.rows=[{'code':'US.MASS','target_weight':.1},{'code':'US.KDK','target_weight':0.}]
        self.partial_runner(delay=0);old=(self.opening-timedelta(days=3)).isoformat()
        for code,qty,price in [('US.KDK',595,10.),('US.MASS',7,70.)]:
            oid='old-'+code
            self.engine.db.execute('INSERT INTO orders (id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (oid,old,SID,'moomoo_simulate','3604',code,'BUY',qty,price,'FILLED_ALL',oid))
            self.engine.db.execute('INSERT INTO order_fills VALUES (?,?)',(oid,json.dumps({'fill_qty':qty,'fill_price':price,'filled_at':old})))
        self.engine.db.commit();FakeBroker.positions={'US.KDK':595,'US.MASS':7};FakeBroker.market_prices={'US.KDK':10.,'US.MASS':70.};FakeBroker.cash=1000000.-5950.-490.
        self.runner._accept_snapshot(self.engine.broker.snapshot([],include_quotes=False))
        original=FakeBroker.snapshot_partial
        def prices(broker,codes):
            snap=original(broker,codes)
            for code,price in [('US.KDK',10.),('US.MASS',70. if not getattr(self,'lower_mass',False) else 20.)]:
                if code in snap['quotes']:snap['quotes'][code].update(price=price,bid=price-.01,ask=price+.01)
            return snap
        error=BrokerOrderNotSent('synthetic unsent');error.retry_after_seconds=30;FakeBroker.before_send_error=error;FakeBroker.quote_errors={'US.KDK':'stale'}
        with patch.object(FakeBroker,'snapshot_partial',prices):
            with self.assertRaises(BrokerReadError):self.tick_at(self.opening+timedelta(seconds=1))
        self.runner.stop();state=self.engine._get('best_execution',{})
        self.assertEqual(state['phase'],'BUY');self.assertEqual(state['target_quantities']['US.MASS'],13)
        self.now=self.opening+timedelta(seconds=601);self.deadline=self.now+timedelta(seconds=590)
        self.authorize(quote_refresh=True);self.renew_now=self.deadline+timedelta(seconds=1)
        self.renew(allowed_codes=['US.KDK','US.MASS']);self.lower_mass=True
        self.runner=BestBroker(self.temp.name,self.source,engine=self.engine);self.connect();self.resume()
        with patch.object(FakeBroker,'snapshot_partial',prices):
            for sec in range(1,7):self.tick_at(self.renew_now+timedelta(seconds=sec))
        self.assertEqual([(row['code'],row['side'],row['qty']) for row in FakeBroker.submissions],[('US.KDK','SELL',595),('US.MASS','BUY',6)])
        self.assertEqual(FakeBroker.positions['US.MASS'],13);self.assertEqual(FakeBroker.positions['US.KDK'],0)
        self.assertEqual(self.engine._get('best_execution',{})['target_quantities']['US.MASS'],13)


class ManualCompletionHistoryTests(unittest.TestCase):
    """Synthetic persisted owner records; no SDK, source worker or real account reads."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(self.temp.name, broker_factory=FakeBroker)
        self.sid = 'R7_GROSS_LINEAR'
        self.now = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
        self.engine._set('best_strategy_id', self.sid)
        self.engine._set('best_account', '3604')
        self.engine._set('best_capital', dict(account_id='3604', budget=10000.0, unused_cash=990000.0))
        binding = dict(target_strategy_id=self.sid, account_id='3604', budget=10000.0,
                       preserved_settings={}, preserved_settings_sha256=BestBroker._content_sha({}))
        self.engine._set('best_strategy_binding', binding)
        self.audit('SIM_STRATEGY_BOUND', binding)
        self.runner = BestBroker(self.temp.name, FakeSource(self.now), engine=self.engine,
            strategy_id=self.sid, now=lambda: self.now, execution_delay_minutes=0,
            execution_window_seconds=600, allow_partial_quotes=True)
        sha = BestBroker._content_sha
        self.alignment = dict(schema='PUBLISHED_TARGET_ALIGNMENT_R1',
            request=dict(alignment_id='old_alignment', expected_strategy_id=self.sid,
                         signal_date='2026-09-25', expected_target_sha256=sha('target')),
            strategy_id=self.sid, signal_date='2026-09-25', execution_date='2026-09-28',
            account_id='3604', budget=10000.0, published_target_sha256=sha('target'),
            plan_sha256=sha('old_plan'), metadata_sha256=sha('old_metadata'))
        self.manual = dict(schema='OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1',
            request=dict(manual_id='old_manual'), manual_id='old_manual',
            authorized_at_utc='2026-09-28T14:30:00+00:00', deadline_utc='2026-09-28T14:40:00+00:00',
            session_close_utc='2026-09-28T20:00:00+00:00', strategy_id=self.sid,
            signal_date='2026-09-25', execution_date='2026-09-28', account_id='3604', budget=10000.0,
            alignment_id='old_alignment', alignment_receipt_sha256=sha(self.alignment),
            published_target_sha256=sha('target'), plan_sha256=sha('old_plan'), metadata_sha256=sha('old_metadata'))
        self.completed = dict(schema='OWNER_PUBLISHED_TARGET_CONVERSION_R1', status='COMPLETED',
            conversion_id='old_conversion', account_id='3604', budget=10000.0, strategy_id=self.sid,
            origin_alignment_id='old_alignment', origin_alignment_sha256=sha(self.alignment),
            last_alignment_id='old_alignment', last_alignment_sha256=sha(self.alignment),
            last_signal_date='2026-09-25', last_execution_date='2026-09-28', last_published_target_sha256=sha('target'),
            completed_at='2026-09-28T15:00:00+00:00', updated_at='2026-09-28T15:00:00+00:00',
            completed_execution_sha256=sha(dict(signal_date='2026-09-25', phase='DONE', completion_status='EXECUTED')),
            reconciled_positions_sha256=sha({'US.AAPL': 17}))
        self.store_proofs()
        self.engine._set('best_execution', dict(signal_date='2026-09-28', phase='SELL'))
        self.runner.plan = dict(signal_date='2026-09-28', rows=[])
        self.runner.metadata = dict(signal_date='2026-09-28', execution_date='2026-09-29',
                                    next_open_utc='2026-09-29T13:30:00+00:00')
        self.engine._set('best_plan', dict(plan=self.runner.plan, metadata=self.runner.metadata))

    def audit(self, event, value):
        self.engine.db.execute('INSERT INTO audit VALUES (?,?,?)', ('2026-09-28T15:00:00+00:00', event, json.dumps(value)))
        self.engine.db.commit()

    def store_proofs(self):
        self.engine.db.execute("DELETE FROM audit WHERE event IN ('PUBLISHED_TARGET_ALIGNED',"
            "'PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED','PUBLISHED_TARGET_CONVERSION_STATE')")
        self.engine.db.commit()
        self.audit('PUBLISHED_TARGET_ALIGNED', self.alignment)
        self.audit('PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED', self.manual)
        self.audit('PUBLISHED_TARGET_CONVERSION_STATE', self.completed)
        self.engine._set('best_published_target_manual_completion', self.manual)
        self.engine._set('best_published_target_conversion', self.completed)

    def tearDown(self):
        self.runner.close()
        self.temp.cleanup()

    def test_manual_history_completed_rollover_uses_audited_owner_proof_without_writes_or_authority(self):
        before_settings = list(self.engine.db.execute('SELECT key,value FROM settings ORDER BY key'))
        before_audit = list(self.engine.db.execute('SELECT * FROM audit ORDER BY rowid'))
        with patch.object(self.source_if_any(), 'status', side_effect=AssertionError('no source lookup')):
            summary = self.runner._manual_completion_summary()
        self.assertEqual(summary['status'], 'COMPLETED')
        self.assertEqual(summary['signal_date'], '2026-09-25')
        self.assertEqual(summary['execution_date'], '2026-09-28')
        self.assertEqual(self.runner._target_conversion(), None)
        self.assertEqual(self.runner._manual_completion_record(), None)
        self.assertEqual(self.runner._execution_end(), datetime(2026, 9, 29, 13, 40, tzinfo=timezone.utc))
        self.assertEqual(list(self.engine.db.execute('SELECT key,value FROM settings ORDER BY key')), before_settings)
        self.assertEqual(list(self.engine.db.execute('SELECT * FROM audit ORDER BY rowid')), before_audit)

    def source_if_any(self):
        return self.runner.source

    def test_manual_history_current_done_branch_is_preserved_without_historical_proof(self):
        self.engine._set('best_published_target_conversion', None)
        self.engine._set('best_execution', dict(signal_date=self.manual['signal_date'], phase='DONE', completion_status='EXECUTED'))
        self.assertEqual(self.runner._manual_completion_summary()['status'], 'COMPLETED')

    def test_manual_history_missing_unfinished_or_unaudited_proof_falls_back_to_expiry(self):
        for kind in ('missing', 'active', 'audit_missing', 'audit_changed', 'manual_audit_missing', 'manual_audit_changed'):
            with self.subTest(kind=kind):
                self.store_proofs()
                if kind == 'missing': self.engine._set('best_published_target_conversion', None)
                elif kind == 'active':
                    value = dict(self.completed, status='ACTIVE'); self.engine._set('best_published_target_conversion', value)
                elif kind == 'audit_missing': self.engine.db.execute("DELETE FROM audit WHERE event='PUBLISHED_TARGET_CONVERSION_STATE'")
                elif kind == 'audit_changed': self.engine._set('best_published_target_conversion', dict(self.completed, budget=5000.0))
                elif kind == 'manual_audit_missing': self.engine.db.execute("DELETE FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED'")
                else: self.engine._set('best_published_target_manual_completion', dict(self.manual, budget=5000.0))
                self.engine.db.commit()
                self.assertEqual(self.runner._manual_completion_summary()['status'], 'EXPIRED')
        self.store_proofs()
        self.engine._set('best_published_target_conversion', None)
        self.now = datetime(2026, 9, 28, 14, 35, tzinfo=timezone.utc)
        self.assertEqual(self.runner._manual_completion_summary()['status'], 'ACTIVE')

    def test_manual_history_manual_identity_and_clock_mismatches_cannot_claim_completed(self):
        changes = {'schema':'OTHER', 'strategy_id':'HGB_DIAG_5', 'account_id':'OTHER', 'budget':5000.0,
            'signal_date':'2026-09-24', 'execution_date':'2026-09-29', 'alignment_id':'OTHER',
            'alignment_receipt_sha256':'b'*64, 'published_target_sha256':'b'*64,
            'plan_sha256':'b'*64, 'metadata_sha256':'b'*64,
            'authorized_at_utc':'2026-09-28T14:30:00', 'session_close_utc':'2026-09-27T20:00:00+00:00'}
        original = deepcopy(self.manual)
        for key,value in changes.items():
            with self.subTest(key=key):
                self.manual = dict(original, **{key:value}); self.store_proofs()
                self.assertEqual(self.runner._manual_completion_summary()['status'], 'EXPIRED')
        self.manual = original; self.store_proofs()

    def test_manual_history_conversion_bindings_hashes_and_future_completion_are_rejected(self):
        changes = {'schema':'OTHER', 'strategy_id':'HGB_DIAG_5', 'account_id':'OTHER', 'budget':5000.0,
            'last_signal_date':'2026-09-24', 'last_execution_date':'2026-09-29', 'last_alignment_id':'OTHER',
            'origin_alignment_sha256':'b'*64, 'last_alignment_sha256':'b'*64, 'last_published_target_sha256':'b'*64,
            'completed_execution_sha256':'UNKNOWN', 'reconciled_positions_sha256':None,
            'completed_at':'2026-09-30T15:00:00+00:00', 'updated_at':'2026-09-30T15:00:00+00:00'}
        original = deepcopy(self.completed)
        for key,value in changes.items():
            with self.subTest(key=key):
                self.completed = dict(original, **{key:value}); self.store_proofs()
                self.assertEqual(self.runner._manual_completion_summary()['status'], 'EXPIRED')
        self.completed = original; self.store_proofs()
        for stamp in ('2026-09-28T14:20:00+00:00', '2026-09-30T15:00:00+00:00', '2026-09-28T15:00:00', 'BAD'):
            with self.subTest(stamp=stamp):
                self.completed = dict(original, completed_at=stamp, updated_at=stamp); self.store_proofs()
                self.assertEqual(self.runner._manual_completion_summary()['status'], 'EXPIRED')

    def test_manual_history_original_expired_execution_permission_stays_rejected(self):
        self.runner.plan['source_hash'] = 'synthetic-source'
        manifest = dict(strategy_id=self.sid, expires_at=self.manual['deadline_utc'],
            source=json.dumps(dict(manual_id=self.manual['manual_id'], signal_date=self.manual['signal_date'],
                source_hash='synthetic-source',
                published_target_manual_completion_sha256=BestBroker._content_sha(self.manual))))
        with patch.object(self.runner, '_manual_completion_record', return_value=self.manual):
            with self.assertRaisesRegex(ValueError, 'CHANGED_OR_EXPIRED'):
                self.runner._manual_manifest_guard(manifest, self.now)

    def test_manual_history_actual_synthetic_completion_survives_successor_execution(self):
        from test_published_target_manual_completion import ManualCompletionTests
        fixture = ManualCompletionTests()
        fixture.setUp()
        try:
            fixture.prepare_manual()
            fixture.authorize()
            fixture.runner.stop_event.clear()
            for second in range(1, 9):
                fixture.now = fixture.opening + timedelta(hours=1, seconds=second)
                fixture.tick_at(fixture.now)
            self.assertEqual(fixture.runner.status, 'EXECUTED', fixture.runner.last_error)
            self.assertEqual(fixture.engine._get('best_published_target_conversion', {})['status'], 'COMPLETED')
            old = deepcopy(fixture.engine._get('best_published_target_manual_completion', {}))
            fixture.now = fixture.opening + timedelta(days=1, hours=1)
            fixture.engine._set('best_execution', dict(signal_date='2026-09-28', phase='SELL'))
            fixture.runner.plan = dict(signal_date='2026-09-28', rows=[])
            fixture.runner.metadata = dict(signal_date='2026-09-28', execution_date='2026-09-29',
                next_open_utc=(fixture.opening + timedelta(days=1)).isoformat())
            fixture.engine._set('best_plan', dict(plan=fixture.runner.plan, metadata=fixture.runner.metadata))
            self.assertEqual(fixture.runner._manual_completion_summary()['status'], 'COMPLETED')
            self.assertEqual(fixture.engine._get('best_published_target_manual_completion', {}), old)
            self.assertIsNone(fixture.runner._manual_completion_record())
            self.assertEqual(fixture.runner._execution_end(), fixture.opening + timedelta(days=1, seconds=600))
        finally:
            fixture.runner.close()
            fixture.doCleanups()
