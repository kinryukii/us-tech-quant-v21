from datetime import datetime, timedelta, timezone
from copy import deepcopy
import json
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
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock):
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
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock):
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
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock):
            self.runner.tick(now=now)
        self.assertEqual(len(FakeBroker.submissions), 1)

    def test_delayed_window_expiry_never_catches_up(self):
        self.delayed_runner()
        self.connect()
        self.runner.tick(now=self.opening+timedelta(minutes=46))
        self.assertEqual(self.runner.status, 'MISSED_OPEN')
        self.assertEqual(FakeBroker.submissions, [])
        self.assertEqual(self.engine.state()['orders'], [])

    def test_delayed_schedule_follows_dst_calendar_open(self):
        from zoneinfo import ZoneInfo
        self.delayed_runner()
        for regular_open in ('2026-09-29T13:30:00+00:00','2026-11-02T14:30:00+00:00'):
            scheduled = self.runner._scheduled_open(regular_open).astimezone(ZoneInfo('America/New_York'))
            self.assertEqual((scheduled.hour,scheduled.minute),(10,15))

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
        with patch('moomoo_component.core.datetime', Clock), patch('moomoo_component.strategy.datetime', Clock):
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
        tomorrow = self.opening + timedelta(days=1)
        self.runner.metadata = {**self.source.status(), 'next_expected_open_utc': tomorrow.isoformat()}
        self.runner._now = lambda: self.opening + timedelta(minutes=44)
        self.assertEqual(self.runner.state()['next_expected_execution_utc'],
                         (self.opening + timedelta(minutes=45)).isoformat())
        self.runner._now = lambda: self.opening + timedelta(minutes=46)
        self.assertEqual(self.runner.state()['next_expected_execution_utc'],
                         (tomorrow + timedelta(minutes=45)).isoformat())

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


if __name__ == '__main__':
    unittest.main()
