from copy import deepcopy
import http.client
import json
import tempfile
import threading
import unittest

from moomoo_component.core import Engine
from moomoo_component.server import LocalServer


class FakeLive:
    """HTTP routing fixture; contains no SDK or network connection."""

    def __init__(self):
        self.calls = []
        self.value = {
            'environment': 'REAL', 'execution_enabled': False, 'permission': 'LOCKED',
            'connected': False, 'accounts': [], 'account_id': None, 'account': None,
            'last_error': '', 'port': 18441, 'security_firm': 'FUTUSECURITIES',
        }

    def state(self):
        return deepcopy(self.value)

    def connect(self, port=18441, security_firm='FUTUSECURITIES'):
        self.calls.append(('connect', {'port': port, 'security_firm': security_firm}))
        self.value.update(connected=True, port=port, security_firm=security_firm,
                          accounts=[{'account_id': '91001', 'market': 'US', 'environment': 'REAL'}],
                          account_id=None, account=None)
        return self.state()

    def select(self, account_id):
        self.calls.append(('select', {'account_id': account_id}))
        self.value.update(account_id=account_id, account=None)
        return self.state()

    def refresh(self):
        self.calls.append(('refresh', {}))
        self.value['account'] = {
            'cash': 125.0, 'equity': 250.0, 'currency': 'USD',
            'positions': [], 'orders': [], 'asof': '2026-09-26T03:00:00+00:00',
        }
        return self.state()


class LocalHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(self.temp.name)
        self.live = FakeLive()
        self.server = LocalServer(0, self.engine, live=self.live)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.engine.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        client.request(method, path, body, headers or {})
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    def test_get_does_not_start_or_select_account(self):
        status, body = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        self.assertFalse(body['data']['running'])
        self.assertFalse(body['data']['live_enabled'])
        self.assertEqual(body['data']['mode'], 'paper')
        self.assertFalse(body['data']['connection']['connected'])

    def test_cross_origin_and_missing_token_cannot_mutate(self):
        for headers in ({'Content-Type': 'application/json'},
                        {'Content-Type': 'application/json', 'X-CSRF-Token': self.server.token, 'Origin': 'https://attacker.test'}):
            status, _ = self.request('POST', '/api/demo', '{}', headers)
            self.assertEqual(status, 403)
        self.assertEqual(self.engine.state()['strategies'], [])

    def test_host_rebinding_rejected(self):
        status, _ = self.request('GET', '/api/token', headers={'Host': 'attacker.test'})
        self.assertEqual(status, 403)

    def test_explicit_paper_workflow_and_live_rejection(self):
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.server.token}
        self.assertEqual(self.request('POST', '/api/demo', '{}', headers)[0], 200)
        self.assertTrue(self.request('POST', '/api/preview', '{}', headers)[1]['data']['allowed'])
        self.assertEqual(len(self.request('POST', '/api/step', '{}', headers)[1]['data']['submitted']), 2)
        self.assertEqual(len(self.request('POST', '/api/step', '{}', headers)[1]['data']['submitted']), 0)
        self.assertEqual(self.request('POST', '/api/mode', '{"mode":"real"}', headers)[0], 400)

    def test_live_page_has_separate_empty_state_and_token(self):
        status, state = self.request('GET', '/api/live/state')
        self.assertEqual(status, 200)
        self.assertEqual(state['data']['environment'], 'REAL')
        self.assertFalse(state['data']['execution_enabled'])
        self.assertIsNone(state['data']['account'])
        self.assertNotIn('strategies', state['data'])
        live_token = self.request('GET', '/api/live/token')[1]['data']['token']
        self.assertNotEqual(live_token, self.server.token)
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': live_token}
        self.assertEqual(self.request('POST', '/api/demo', '{}', headers)[0], 403)
        self.assertEqual(self.engine.state()['strategies'], [])
        paper_headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.server.token}
        self.assertEqual(self.request('POST', '/api/live/select', '{"account_id":"1"}', paper_headers)[0], 403)

    def test_live_trade_endpoints_fail_before_engine_access(self):
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.server.live_token}
        for action in ('step', 'start', 'unlock', 'order', 'cancel', 'mode', 'import'):
            with self.subTest(action=action):
                status, _ = self.request('POST', '/api/live/' + action, '{}', headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.engine.state()['orders'], [])
        self.assertFalse(self.engine.state()['running'])

    def test_live_readonly_http_workflow_routes_parameters_without_mutating_paper(self):
        # A nonempty paper ledger makes accidental resets or cross-account
        # state replacement visible, as well as accidental execution.
        self.engine.demo()
        self.engine.step()
        paper_before = deepcopy(self.engine.state())
        status, body = self.request('GET', '/api/live/token')
        self.assertEqual(status, 200)
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': body['data']['token']}
        self.assertEqual(self.live.calls, [])

        status, body = self.request('POST', '/api/live/connect',
                                    json.dumps({'port': 11111, 'security_firm': 'FUTUINC'}), headers)
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertTrue(body['data']['connected'])
        self.assertEqual(body['data']['accounts'][0]['account_id'], '91001')
        self.assertIsNone(body['data']['account_id'])
        self.assertIsNone(body['data']['account'])
        self.assertEqual(self.engine.state(), paper_before)

        status, body = self.request('POST', '/api/live/select', '{"account_id":"91001"}', headers)
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['data']['account_id'], '91001')
        self.assertIsNone(body['data']['account'])
        self.assertEqual(self.engine.state(), paper_before)

        status, body = self.request('POST', '/api/live/refresh', '{}', headers)
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['data']['account']['cash'], 125.0)
        self.assertEqual(body['data']['account']['equity'], 250.0)
        self.assertFalse(body['data']['execution_enabled'])
        self.assertEqual(body['data']['permission'], 'LOCKED')
        self.assertEqual(self.engine.state(), paper_before)
        self.assertEqual(self.live.calls, [
            ('connect', {'port': 11111, 'security_firm': 'FUTUINC'}),
            ('select', {'account_id': '91001'}), ('refresh', {}),
        ])
        status, state = self.request('GET', '/api/live/state')
        self.assertEqual(status, 200)
        self.assertEqual(state, body)
        self.assertEqual(len(self.live.calls), 3)
        self.assertEqual(self.request('GET', '/api/state')[1]['data'], paper_before)

    def test_health_contract_is_data_free(self):
        status, body = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertEqual(body['data'], {'component': 'moomoo-trading-component', 'api_version': 1,
                         'live_execution_enabled': False, 'pages': ['paper', 'live']})

    def test_applied_routes_are_opt_in_and_get_never_starts_books(self):
        self.assertEqual(self.request('GET', '/api/applied/state')[0], 503)
        class FakeCohort:
            starts = 0
            def state(self):
                return {'running': False, 'books': {'RAW_A2': {'cash': 10000}}}
            def start(self):
                self.starts += 1
                return self.state()
            def stop(self):
                return self.state()
            def halt(self):
                return self.state()
            def trades(self):
                return []
        cohort = FakeCohort()
        self.server.cohort = cohort
        self.assertEqual(self.request('GET', '/api/applied/state')[1]['data']['books']['RAW_A2']['cash'], 10000)
        self.assertEqual(cohort.starts, 0)
        self.assertEqual(self.request('POST', '/api/applied/start', '{}', {'Content-Type': 'application/json'})[0], 403)
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.server.token}
        self.assertEqual(self.request('POST', '/api/applied/start', '{"budget":1000000}', headers)[0], 400)
        self.assertEqual(cohort.starts, 0)
        self.assertEqual(self.request('POST', '/api/applied/start', '{}', headers)[0], 200)
        self.assertEqual(cohort.starts, 1)

    def test_only_pages_allow_exact_demo_origins_for_embedding(self):
        for path in ('/paper?embed=1', '/live?embed=1', '/api/state'):
            client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
            client.request('GET', path)
            response = client.getresponse()
            csp = response.getheader('Content-Security-Policy')
            response.read()
            self.assertEqual(response.status, 200)
            if path.startswith('/api/'):
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertEqual(response.getheader('X-Frame-Options'), 'DENY')
            else:
                self.assertIn('http://127.0.0.1:8506', csp)
                self.assertNotIn('*', csp)
                self.assertIsNone(response.getheader('X-Frame-Options'))
            client.close()


if __name__ == '__main__':
    unittest.main()
