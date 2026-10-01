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

    def post(self, body, token=None):
        request = urllib.request.Request(self.url + "/api/applied/reconcile", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-CSRF-Token": token or self.server.token, "Origin": self.url}, method="POST")
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


if __name__ == "__main__":
    unittest.main()
