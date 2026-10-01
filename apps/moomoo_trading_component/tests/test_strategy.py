from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from moomoo_component.strategy import execution_reasons, validate_manifest


class StrategyBoundaryTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.manifest = dict(schema_version=1, strategy_id='source-a', name='来源A', revision='1',
            asof=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
            provenance='live', targets=[dict(code='US.AAPL', target_qty=2)])

    def test_quantities_and_symbols_are_strict(self):
        for quantity in (-1, 0.5, True, '2', float('nan'), float('inf')):
            item = deepcopy(self.manifest)
            item['targets'][0]['target_qty'] = quantity
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                validate_manifest(item)
        for code in ('HK.00700', 'US.AAPL260925C200000', '../file', 'BTC', ''):
            item = deepcopy(self.manifest)
            item['targets'][0]['code'] = code
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_manifest(item)

    def test_arbitrary_code_and_unknown_keys_not_imported(self):
        for key in ('python', 'plugin', 'command', 'broker', 'account_id', 'risk_limits'):
            item = {**self.manifest, key: 'payload'}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_manifest(item)

    def test_duplicate_codes_and_naive_time_rejected(self):
        item = deepcopy(self.manifest)
        item['targets'].append(deepcopy(item['targets'][0]))
        with self.assertRaises(ValueError):
            validate_manifest(item)
        item = {**self.manifest, 'asof': '2026-09-25T12:00:00'}
        with self.assertRaises(ValueError):
            validate_manifest(item)

    def test_historical_demo_expired_and_future_execution_barriers(self):
        self.assertEqual(execution_reasons(self.manifest, 'moomoo_simulate', 86400), [])
        now = datetime.now(timezone.utc)
        for updates, mode in (({'provenance': 'historical'}, 'paper'),
                              ({'provenance': 'demo'}, 'moomoo_simulate'),
                              ({'asof': (now + timedelta(minutes=5)).isoformat()}, 'paper'),
                              ({'expires_at': (now - timedelta(seconds=1)).isoformat()}, 'paper'),
                              ({'asof': (now - timedelta(days=2)).isoformat()}, 'paper')):
            with self.subTest(updates=updates, mode=mode):
                self.assertTrue(execution_reasons({**self.manifest, **updates}, mode, 86400))


if __name__ == '__main__':
    unittest.main()
