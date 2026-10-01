"""Fake SDK only: tests must never contact a real OpenD account."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from moomoo_component.live import LiveReadOnly, LiveReadOnlyError


NOW = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)


class FakeContext:
    def __init__(self, sdk):
        self.sdk = sdk
        self.closed = False

    def _query(self, name, rows, kwargs):
        self.sdk.calls.append((name, kwargs))
        if name in self.sdk.errors:
            raise RuntimeError("sensitive-balance-and-account-id")
        if name in self.sdk.failures:
            return -1, "sensitive-balance-and-account-id"
        return 0, deepcopy(rows)

    def get_acc_list(self, **kwargs):
        return self._query("get_acc_list", self.sdk.accounts, kwargs)

    def accinfo_query(self, **kwargs):
        return self._query("accinfo_query", self.sdk.funds, kwargs)

    def position_list_query(self, **kwargs):
        return self._query("position_list_query", self.sdk.positions, kwargs)

    def order_list_query(self, **kwargs):
        return self._query("order_list_query", self.sdk.orders, kwargs)

    def close(self):
        self.closed = True
        self.sdk.calls.append(("close", {}))

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected SDK method: {name}")


class FakeSDK:
    RET_OK = 0
    TrdMarket = SimpleNamespace(US="US")
    TrdEnv = SimpleNamespace(REAL="REAL")
    Currency = SimpleNamespace(USD="USD")
    SecurityFirm = SimpleNamespace(FUTUSECURITIES="FUTUSECURITIES", FUTUINC="FUTUINC")

    def __init__(self):
        self.calls = []
        self.contexts = []
        self.errors = set()
        self.failures = set()
        self.accounts = [
            {"acc_id": 111, "trd_env": "REAL", "acc_status": "ACTIVE", "trdmarket_auth": ["US", "HK"]},
            {"acc_id": 222, "trd_env": "SIMULATE", "acc_status": "ACTIVE", "trdmarket_auth": ["US"]},
            {"acc_id": 333, "trd_env": "REAL", "acc_status": "DISABLED", "trdmarket_auth": ["US"]},
            {"acc_id": 444, "trd_env": "REAL", "acc_status": "ACTIVE", "trdmarket_auth": ["HK"]},
        ]
        self.funds = [{"currency": "USD", "us_cash": 500, "total_assets": 1250, "power": 999999}]
        self.positions = [{"code": "US.AAPL", "stock_name": "Apple", "qty": 2.5,
            "can_sell_qty": 2, "market_val": 750, "cost_price": 100, "cost_price_valid": True,
            "pl_val": 500, "pl_val_valid": True, "unrealized_pl": 450,
            "currency": "USD", "position_side": "LONG"}]
        self.orders = [{"order_id": "order-1", "code": "US.AAPL", "trd_side": "BUY",
            "qty": 1, "price": 300, "dealt_qty": 0, "order_status": "SUBMITTED",
            "create_time": "2026-09-25 10:00:00", "updated_time": "2026-09-25 10:00:01"}]

    def OpenSecTradeContext(self, **kwargs):
        self.calls.append(("OpenSecTradeContext", kwargs))
        context = FakeContext(self)
        self.contexts.append(context)
        return context


class LiveReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.reader = LiveReadOnly(sdk=self.sdk, now=lambda: NOW)

    def ready(self):
        self.reader.connect()
        self.reader.select("111")

    def test_state_and_constructor_never_load_sdk_or_connect(self):
        with patch("moomoo_component.live.importlib.import_module", side_effect=AssertionError):
            state = LiveReadOnly().state()
        self.assertEqual(state["environment"], "REAL")
        self.assertFalse(state["execution_enabled"])
        self.assertEqual(state["permission"], "LOCKED")
        self.assertFalse(state["connected"])
        self.assertIsNone(state["account"])
        self.assertIsNone(state["account_id"])
        self.assertEqual(state["accounts"], [])
        self.assertEqual(self.sdk.calls, [])

    def test_connect_only_discovers_real_active_us_accounts(self):
        state = self.reader.connect()
        self.assertEqual(state["accounts"], [{"account_id": "111", "market": "US", "environment": "REAL"}])
        self.assertIsNone(state["account_id"])
        self.assertIsNone(state["account"])
        self.assertEqual([name for name, _ in self.sdk.calls], ["OpenSecTradeContext", "get_acc_list"])
        args = self.sdk.calls[0][1]
        self.assertEqual(args, {"filter_trdmarket": "US", "host": "127.0.0.1", "port": 18441, "security_firm": "FUTUSECURITIES"})
        self.assertNotIn("222", json.dumps(state))

    def test_refresh_requires_explicit_connection_and_selection(self):
        with self.assertRaises(LiveReadOnlyError):
            self.reader.refresh()
        self.assertEqual(self.sdk.calls, [])
        self.reader.connect()
        with self.assertRaises(LiveReadOnlyError):
            self.reader.refresh()
        self.assertFalse(any(name == "accinfo_query" for name, _ in self.sdk.calls))

    def test_select_metadata_only_and_refresh_explicit_real_account(self):
        self.ready()
        self.assertEqual([name for name, _ in self.sdk.calls], ["OpenSecTradeContext", "get_acc_list", "get_acc_list"])
        result = self.reader.refresh()["account"]
        self.assertEqual(result["cash"], 500)
        self.assertEqual(result["equity"], 1250)
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["positions"][0]["qty"], 2.5)
        self.assertEqual(result["positions"][0]["unrealized_pl"], 450)
        self.assertEqual(result["orders"][0]["status"], "SUBMITTED")
        self.assertEqual(result["asof"], NOW.isoformat())
        self.assertEqual(result["warnings"], [])
        self.assertNotIn("power", result)
        for name, args in self.sdk.calls:
            if name in {"accinfo_query", "position_list_query", "order_list_query"}:
                self.assertEqual(args["trd_env"], "REAL")
                self.assertEqual(args["acc_id"], 111)
                self.assertTrue(args["refresh_cache"])
                if name != "order_list_query":
                    self.assertEqual(args["currency"], "USD")

    def test_rejects_all_unlisted_or_invalid_account_ids(self):
        self.reader.connect()
        for value in [None, True, 0, "0", "222", "333", "444", "999", "111.0", "00111"]:
            with self.subTest(value=value), self.assertRaises(LiveReadOnlyError):
                self.reader.select(value)
        self.assertFalse(any(name == "accinfo_query" for name, _ in self.sdk.calls))

    def test_select_rechecks_live_environment_and_account_status(self):
        for key, value in [("trd_env", "SIMULATE"), ("acc_status", "DISABLED"), ("trdmarket_auth", ["HK"])]:
            sdk = FakeSDK()
            reader = LiveReadOnly(sdk=sdk)
            reader.connect()
            sdk.accounts[0][key] = value
            with self.subTest(key=key), self.assertRaises(LiveReadOnlyError):
                reader.select("111")
            self.assertIsNone(reader.state()["account_id"])

    def test_refresh_rechecks_account_before_every_funds_read(self):
        self.ready()
        self.reader.refresh()
        self.sdk.accounts[0]["trd_env"] = "SIMULATE"
        calls = len(self.sdk.calls)
        with self.assertRaises(LiveReadOnlyError):
            self.reader.refresh()
        self.assertEqual([name for name, _ in self.sdk.calls[calls:]], ["get_acc_list"])
        self.assertIsNone(self.reader.state()["account"])

    def test_duplicate_account_ids_are_never_exposed_as_selectable(self):
        self.sdk.accounts.append(deepcopy(self.sdk.accounts[0]))
        self.assertEqual(self.reader.connect()["accounts"], [])
        with self.assertRaises(LiveReadOnlyError):
            self.reader.select("111")

    def test_missing_or_invalid_numbers_are_null_not_zero(self):
        self.ready()
        self.sdk.funds[0].pop("us_cash")
        self.sdk.funds[0]["total_assets"] = float("nan")
        self.sdk.positions[0]["qty"] = "N/A"
        self.sdk.orders[0]["dealt_qty"] = None
        account = self.reader.refresh()["account"]
        self.assertIsNone(account["cash"])
        self.assertIsNone(account["equity"])
        self.assertIsNone(account["positions"][0]["qty"])
        self.assertIsNone(account["orders"][0]["filled_qty"])
        self.assertGreaterEqual(len(account["warnings"]), 4)
        json.dumps(account, allow_nan=False)

    def test_negative_cash_and_short_positions_are_reported_without_hiding_debt(self):
        self.ready()
        self.sdk.funds[0]["us_cash"] = -100
        self.sdk.positions[0].update(qty=-1.5, market_val=-450, position_side="SHORT")
        account = self.reader.refresh()["account"]
        self.assertEqual(account["cash"], -100)
        self.assertEqual(account["positions"][0]["qty"], -1.5)
        self.assertEqual(account["positions"][0]["position_side"], "SHORT")

    def test_unknown_or_non_usd_funds_do_not_receive_implicit_conversion(self):
        self.ready()
        for currency in [None, "N/A", "HKD", "JPY"]:
            self.sdk.funds[0]["currency"] = currency
            with self.subTest(currency=currency), self.assertRaisesRegex(LiveReadOnlyError, "币种"):
                self.reader.refresh()
            self.assertIsNone(self.reader.state()["account"])

    def test_mixed_position_currency_is_explicitly_unconfirmed(self):
        self.ready()
        for currency in [None, "HKD"]:
            self.sdk.positions[0]["currency"] = currency
            with self.subTest(currency=currency), self.assertRaisesRegex(LiveReadOnlyError, "混合币种"):
                self.reader.refresh()
            self.assertIsNone(self.reader.state()["account"])

    def test_non_us_order_currency_is_unknown_with_warning(self):
        self.ready()
        self.sdk.orders[0]["code"] = "HK.00700"
        account = self.reader.refresh()["account"]
        self.assertIsNone(account["orders"][0]["currency"])
        self.assertTrue(any("订单" in text for text in account["warnings"]))

    def test_cost_validity_requires_explicit_true_and_missing_unrealized_is_unknown(self):
        self.ready()
        self.sdk.positions[0].pop("unrealized_pl")
        for flag in [False, "False", "True", None, float("nan")]:
            self.sdk.positions[0]["cost_price_valid"] = flag
            position = self.reader.refresh()["account"]["positions"][0]
            self.assertIsNone(position["cost_price"])
            self.assertIsNone(position["unrealized_pl"])

    def test_error_after_previous_success_clears_snapshot_and_redacts_sdk_payload(self):
        self.ready()
        self.reader.refresh()
        for mode in [self.sdk.errors, self.sdk.failures]:
            mode.add("order_list_query")
            with self.assertRaises(LiveReadOnlyError) as caught:
                self.reader.refresh()
            state = self.reader.state()
            self.assertIsNone(state["account"])
            self.assertNotIn("sensitive", str(caught.exception))
            self.assertNotIn("sensitive", state["last_error"])
            mode.clear()

    def test_response_cannot_mix_accounts_or_environments(self):
        self.ready()
        for rows in [self.sdk.funds, self.sdk.positions, self.sdk.orders]:
            for field, value in [("acc_id", 222), ("trd_env", "SIMULATE")]:
                rows[0][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(LiveReadOnlyError, "不匹配"):
                    self.reader.refresh()
                rows[0].pop(field)

    def test_states_are_detached_and_state_never_requeries(self):
        self.ready()
        self.reader.refresh()
        count = len(self.sdk.calls)
        state = self.reader.state()
        state["accounts"].clear()
        state["account"]["cash"] = 999
        state["execution_enabled"] = True
        fresh = self.reader.state()
        self.assertEqual(fresh["account"]["cash"], 500)
        self.assertEqual(len(fresh["accounts"]), 1)
        self.assertFalse(fresh["execution_enabled"])
        self.assertEqual(len(self.sdk.calls), count)

    def test_reconnect_and_close_clear_selection_and_all_account_data(self):
        self.ready()
        self.reader.refresh()
        state = self.reader.connect(port=11111, security_firm="FUTUINC")
        self.assertTrue(self.sdk.contexts[0].closed)
        self.assertIsNone(state["account_id"])
        self.assertIsNone(state["account"])
        self.assertEqual(state["port"], 11111)
        self.reader.close()
        self.assertTrue(self.sdk.contexts[1].closed)
        self.assertFalse(self.reader.state()["connected"])
        self.assertEqual(self.reader.state()["accounts"], [])

    def test_no_execution_or_quote_interface_exists(self):
        for method in ["submit", "unlock_trade", "place_order", "modify_order", "cancel_order", "snapshot"]:
            self.assertFalse(hasattr(self.reader, method))
        with self.assertRaises(LiveReadOnlyError):
            self.reader._call("place_order")
        self.assertEqual(self.sdk.calls, [])

    def test_invalid_connection_configuration_never_connects(self):
        for args in [{"port": True}, {"port": 0}, {"port": 65536}, {"security_firm": "../bad"}, {"security_firm": "UNKNOWN"}]:
            with self.subTest(args=args), self.assertRaises(LiveReadOnlyError):
                self.reader.connect(**args)
        self.assertEqual(self.sdk.calls, [])

    def test_sdk_missing_has_actionable_error_and_no_connection(self):
        reader = LiveReadOnly()
        with patch("moomoo_component.live.importlib.import_module", side_effect=ImportError):
            with self.assertRaisesRegex(LiveReadOnlyError, "尚未安装"):
                reader.connect()
        self.assertFalse(reader.state()["connected"])

    def test_connect_failure_closes_context_and_clears_data(self):
        self.sdk.errors.add("get_acc_list")
        with self.assertRaises(LiveReadOnlyError):
            self.reader.connect()
        self.assertTrue(self.sdk.contexts[0].closed)
        self.assertFalse(self.reader.state()["connected"])
        self.assertEqual(self.reader.state()["accounts"], [])


if __name__ == "__main__":
    unittest.main()
