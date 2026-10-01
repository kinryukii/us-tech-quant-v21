"""Broker safety tests use a fake SDK only: no OpenD connection or broker order."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from moomoo_component.brokers import BrokerError, BrokerReadError, BrokerOrderNotSent, MoomooBroker


NOW = datetime(2026, 9, 25, 15, 0, 15, tzinfo=timezone.utc)


class FakeContext:
    def __init__(self, sdk, kind):
        self.sdk, self.kind = sdk, kind
        self.closed = False

    def close(self):
        self.closed = True

    def __getattr__(self, method):
        if method == "unlock_trade":
            raise AssertionError("Forbidden broker operation")
        def call(**kwargs):
            self.sdk.calls.append((method, kwargs))
            if method in self.sdk.errors:
                raise TimeoutError(self.sdk.error_message)
            if method in self.sdk.failures:
                return -1, deepcopy(self.sdk.failures[method])
            if method == "get_acc_list":
                data = self.sdk.accounts
            elif method == "accinfo_query":
                data = self.sdk.funds
            elif method == "position_list_query":
                data = self.sdk.positions
            elif method == "get_stock_basicinfo":
                data = [self.sdk.basic[c] for c in kwargs["code_list"]]
            elif method == "get_market_state":
                data = [self.sdk.states[c] for c in kwargs["code_list"]]
            elif method == "get_market_snapshot":
                data = [self.sdk.quotes[c] for c in kwargs["code_list"]]
            elif method == "subscribe":
                return 0, None
            elif method == "get_order_book":
                row = self.sdk.quotes[kwargs["code"]]
                data = {"code": kwargs["code"], "order_book_type": "NORMAL",
                    "svr_recv_time_bid": row.get("update_time"),
                    "svr_recv_time_ask": row.get("update_time"),
                    "Bid": [(row.get("bid_price"), 500, 1, {})],
                    "Ask": [(row.get("ask_price"), 500, 1, {})]}
            elif method == "order_list_query":
                data = self.sdk.orders
            elif method == "history_order_list_query":
                data = self.sdk.history
            elif method == "acctradinginfo_query":
                data = self.sdk.trading_info
            elif method == "place_order":
                data = self.sdk.submit_result
            elif method == "modify_order":
                data = self.sdk.modify_result
            else:
                raise AssertionError(f"Unexpected SDK method: {method}")
            return 0, deepcopy(data)
        call.__name__ = method
        return call


class FakeSDK:
    RET_OK = 0
    __version__ = "fake-for-unit-tests"

    def __init__(self):
        for group, names in {
            "TrdEnv": ["SIMULATE", "REAL"], "TrdMarket": ["US"], "Market": ["US"],
            "SecurityFirm": ["FUTUSECURITIES", "FUTUSG"], "Currency": ["USD"],
            "TrdSide": ["BUY", "SELL"], "OrderType": ["NORMAL", "MARKET"],
            "TimeInForce": ["DAY"], "Session": ["NONE", "RTH"],
            "ModifyOrderOp": ["NORMAL"],
            "SubType": ["QUOTE", "ORDER_BOOK"], "SecurityStatus": ["NORMAL", "SUSPENDED"],
        }.items():
            setattr(self, group, SimpleNamespace(**{name: name for name in names}))
        self.calls, self.contexts, self.errors = [], [], set()
        self.failures = {}
        self.error_message = "simulated timeout"
        self.accounts = [
            {"acc_id": 111, "trd_env": "REAL", "sim_acc_type": "N/A", "acc_status": "ACTIVE", "trdmarket_auth": ["US"]},
            {"acc_id": 222, "trd_env": "SIMULATE", "sim_acc_type": "STOCK_AND_OPTION", "acc_status": "ACTIVE", "trdmarket_auth": ["US"]},
            {"acc_id": 333, "trd_env": "SIMULATE", "sim_acc_type": "FUTURES", "acc_status": "ACTIVE", "trdmarket_auth": ["US"]},
        ]
        self.funds = [{"us_cash": 1000.0, "usd_net_cash_power": 900.0, "total_assets": 2000.0, "currency": "USD", "power": 1000000}]
        self.positions, self.orders, self.history = [], [], []
        self.trading_info = [{"acc_id": 222, "trd_env": "SIMULATE", "code": "US.AAPL",
                              "max_cash_buy": 1000}]
        self.basic, self.states, self.quotes = {}, {}, {}
        self.add_quote("US.AAPL")
        self.submit_result = [{"order_id": "test-order", "order_status": "SUBMITTED"}]
        self.modify_result = [{"order_id": "test-order", "order_status": "SUBMITTED"}]

    def add_quote(self, code, stock_type="STOCK"):
        self.basic[code] = {"code": code, "stock_type": stock_type, "delisting": False}
        self.states[code] = {"code": code, "market_state": "AFTERNOON"}
        self.quotes[code] = {"code": code, "last_price": 100, "bid_price": 99.99,
            "ask_price": 100.01, "update_time": "2026-09-25 11:00:00", "lot_size": 1,
            "price_spread": 0.01, "suspension": False, "sec_status": "NORMAL"}

    def OpenSecTradeContext(self, **kwargs):
        self.calls.append(("OpenSecTradeContext", kwargs))
        context = FakeContext(self, "trade")
        self.contexts.append(context)
        return context

    def OpenQuoteContext(self, **kwargs):
        self.calls.append(("OpenQuoteContext", kwargs))
        context = FakeContext(self, "quote")
        self.contexts.append(context)
        return context


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.broker = MoomooBroker(account_id="222", sdk=self.sdk, now=lambda: NOW)
        self.order = {"code": "US.AAPL", "side": "BUY", "qty": 1, "limit_price": 100.01}

    def reprice_fixture(self, *, dealt_qty=3):
        self.sdk.orders = [{"order_id": "test-order", "remark": "client-1", "code": "US.AAPL",
                            "trd_side": "BUY", "order_type": "NORMAL", "trd_env": "SIMULATE",
                            "acc_id": 222, "qty": 9, "dealt_qty": dealt_qty,
                            "dealt_avg_price": 100.01 if dealt_qty else None,
                            "price": 100.01,
                            "order_status": "FILLED_PART" if dealt_qty else "SUBMITTED"}]
        return {"code": "US.AAPL", "side": "BUY", "qty": 9,
                "limit_price": 100.02, "max_order_notional": 1000.0}

    def test_constructor_is_lazy_and_probe_is_read_only_and_redacted(self):
        self.assertEqual(self.sdk.calls, [])
        result = self.broker.probe()
        self.assertEqual(result["accounts"], [{"account_id": "222", "market": "US", "environment": "SIMULATE"}])
        self.assertNotIn("111", str(result))
        self.assertEqual([name for name, _ in self.sdk.calls], ["OpenSecTradeContext", "get_acc_list"])

    def test_import_missing_is_actionable_and_no_network_at_construction(self):
        broker = MoomooBroker()
        with patch("moomoo_component.brokers.importlib.import_module", side_effect=ImportError):
            with self.assertRaisesRegex(BrokerError, "尚未安装"):
                broker.probe()

    def test_loopback_and_port_validation(self):
        for kwargs in [{"host": "1.2.3.4"}, {"host": "example.com"}, {"port": True}, {"port": 0}, {"account_id": "0"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(BrokerError):
                MoomooBroker(**kwargs)

    def test_explicit_simulation_account_required_every_time(self):
        for account in [None, "111", "333", "999"]:
            broker = MoomooBroker(account_id=account, sdk=self.sdk)
            with self.subTest(account=account), self.assertRaises(BrokerError):
                broker.snapshot(["US.AAPL"])
        self.broker.snapshot(["US.AAPL"])
        self.sdk.accounts[1]["trd_env"] = "REAL"
        with self.assertRaises(BrokerError):
            self.broker.submit(self.order, "client-1")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_snapshot_cash_cap_timestamp_and_server_refresh(self):
        result = self.broker.snapshot(["US.AAPL"])
        self.assertEqual(result["cash"], 900)
        self.assertEqual(result["quotes"]["US.AAPL"]["asof"], "2026-09-25T15:00:00+00:00")
        self.assertTrue(result["quotes"]["US.AAPL"]["tradable"])
        for method, args in self.sdk.calls:
            if method in {"accinfo_query", "position_list_query", "order_list_query"}:
                self.assertEqual(args["acc_id"], 222)
                self.assertEqual(args["trd_env"], "SIMULATE")
                self.assertTrue(args["refresh_cache"])

    def test_funds_missing_nan_negative_or_wrong_currency_fail_closed(self):
        original = deepcopy(self.sdk.funds)
        for field, bad in [("us_cash", None), ("usd_net_cash_power", "N/A"), ("total_assets", float("nan")),
                           ("us_cash", -1), ("currency", "HKD")]:
            self.sdk.funds = deepcopy(original)
            self.sdk.funds[0][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(BrokerError):
                self.broker.snapshot(["US.AAPL"])

    def test_legacy_us_simulation_uses_only_cash_less_frozen_with_source(self):
        self.sdk.funds = [{"currency": "N/A", "cash": 1000, "us_cash": 900,
            "usd_net_cash_power": "N/A", "net_cash_power": "N/A", "frozen_cash": 100,
            "total_assets": 2000, "power": 999999999, "hk_cash": "N/A"}]
        result = self.broker.snapshot(["US.AAPL"])
        self.assertEqual(result["cash"], 800)
        self.assertEqual(result["funds_source"], "legacy_us_simulate_cash_less_frozen")
        self.sdk.funds[0]["power"] = float("nan")
        self.sdk.funds[0]["frozen_cash"] = 901
        self.assertEqual(self.broker.snapshot([])["cash"], 0)

    def test_legacy_cash_fallback_rejects_ambiguous_or_mixed_market(self):
        self.sdk.funds = [{"currency": "N/A", "cash": 1000, "us_cash": 1000,
            "usd_net_cash_power": "N/A", "net_cash_power": "N/A", "frozen_cash": 100,
            "total_assets": 2000}]
        for markets in [["US", "HK"], ["HK"], [], ["US", "US"]]:
            self.sdk.accounts[1]["trdmarket_auth"] = markets
            with self.subTest(markets=markets), self.assertRaises(BrokerError):
                self.broker.snapshot([])
        self.sdk.accounts[1]["trdmarket_auth"] = ["US"]
        self.sdk.funds[0]["hk_cash"] = 10
        with self.assertRaisesRegex(BrokerError, "其他币种"):
            self.broker.snapshot([])

    def test_legacy_cash_fallback_requires_explicit_na_and_valid_cash_fields(self):
        original = {"currency": "N/A", "cash": 1000, "us_cash": 1000,
            "usd_net_cash_power": "N/A", "net_cash_power": "N/A", "frozen_cash": 100,
            "total_assets": 2000}
        for field, value in [("currency", None), ("currency", "HKD"), ("currency", "USD"),
                ("usd_net_cash_power", None), ("usd_net_cash_power", float("nan")),
                ("net_cash_power", 0), ("cash", None), ("us_cash", -1), ("frozen_cash", True),
                ("frozen_cash", -1), ("frozen_cash", None), ("hk_cash", float("nan"))]:
            self.sdk.funds = [{**original, field: value}]
            with self.subTest(field=field, value=value), self.assertRaises(BrokerError):
                self.broker.snapshot([])

    def test_modern_funds_path_has_traceable_source(self):
        result = self.broker.snapshot([])
        self.assertEqual(result["funds_source"], "usd_net_cash_power_bounded_by_us_cash")

    def test_all_held_positions_included_and_derivatives_rejected(self):
        self.sdk.add_quote("US.SPY", "ETF")
        self.sdk.positions = [{"code": "US.SPY", "qty": 2, "can_sell_qty": 1, "market_val": 200,
                               "position_side": "LONG", "currency": "USD"}]
        result = self.broker.snapshot(["US.AAPL"])
        self.assertEqual(set(result["quotes"]), {"US.SPY", "US.AAPL"})
        self.assertEqual(result["positions"]["US.SPY"]["sellable"], 1)
        self.sdk.basic["US.SPY"]["stock_type"] = "DRVT"
        feed = self.broker._quote_feed
        with patch.object(feed, "_monotonic", return_value=feed._monotonic() + 5):
            with self.assertRaisesRegex(BrokerError, "不是股票"):
                self.broker.snapshot(["US.AAPL"])

    def test_short_fractional_foreign_positions_fail_closed(self):
        original = {"code": "US.AAPL", "qty": 2, "can_sell_qty": 1, "market_val": 200,
                    "position_side": "LONG", "currency": "USD"}
        for field, bad in [("qty", -1), ("qty", 0.5), ("position_side", "SHORT"), ("currency", "HKD"), ("can_sell_qty", 3)]:
            self.sdk.positions = [{**original, field: bad}]
            with self.subTest(field=field), self.assertRaises(BrokerError):
                self.broker.snapshot([])

    def test_closed_market_and_suspension_not_tradable(self):
        self.sdk.states["US.AAPL"]["market_state"] = "PRE_MARKET_BEGIN"
        self.assertFalse(self.broker.snapshot(["US.AAPL"])["quotes"]["US.AAPL"]["tradable"])
        self.sdk.states["US.AAPL"]["market_state"] = "AFTERNOON"
        self.sdk.quotes["US.AAPL"]["suspension"] = True
        feed = self.broker._quote_feed
        with patch.object(feed, "_monotonic", return_value=feed._monotonic() + 5):
            row = self.broker.snapshot(["US.AAPL"])["quotes"]["US.AAPL"]
        self.assertEqual(row["market_state"], "AFTERNOON")
        self.assertFalse(row["tradable"])

    def test_order_is_explicit_simulate_limit_day_and_normal_session(self):
        result = self.broker.submit(self.order, "client-1")
        self.assertEqual(result["order_id"], "test-order")
        args = [args for name, args in self.sdk.calls if name == "place_order"][0]
        self.assertEqual(args["trd_env"], "SIMULATE")
        self.assertEqual(args["acc_id"], 222)
        self.assertEqual(args["order_type"], "NORMAL")
        self.assertEqual(args["time_in_force"], "DAY")
        self.assertEqual(args["session"], "NONE")
        self.assertFalse(args["fill_outside_rth"])
        self.assertEqual(args["remark"], "client-1")
        with self.assertRaisesRegex(BrokerError, "已尝试"):
            self.broker.submit(self.order, "client-1")

    def test_market_order_uses_simulation_account_and_sdk_market_type(self):
        deadline = (NOW + timedelta(minutes=10)).isoformat()
        result = self.broker.submit(self.order, "market-client", allow_partial_quotes=True,
                                    execution_deadline_utc=deadline, order_type="MARKET")
        self.assertEqual(result["order_id"], "test-order")
        calls = [args for name, args in self.sdk.calls if name == "place_order"]
        self.assertEqual(len(calls), 1)
        args = calls[0]
        self.assertEqual(args["order_type"], "MARKET")
        self.assertEqual(args["trd_env"], "SIMULATE")
        self.assertEqual(args["acc_id"], 222)
        self.assertEqual(args["code"], "US.AAPL")
        self.assertEqual(args["trd_side"], "BUY")
        self.assertEqual(args["qty"], 1)
        self.assertEqual(args["time_in_force"], "DAY")
        self.assertFalse(args["fill_outside_rth"])
        self.assertEqual(args["session"], "NONE")
        self.assertIsInstance(args["price"], (int, float))  # Required by the Python SDK for MARKET.
        self.assertGreater(args["price"], 0)
        capacity = [args for name, args in self.sdk.calls if name == "acctradinginfo_query"]
        self.assertEqual(len(capacity), 1)
        self.assertEqual(capacity[0]["order_type"], "MARKET")
        self.assertEqual(capacity[0]["trd_env"], "SIMULATE")
        self.assertEqual(capacity[0]["code"], "US.AAPL")
        with self.assertRaises(BrokerError):
            self.broker.submit(self.order, "market-client", allow_partial_quotes=True,
                               execution_deadline_utc=deadline, order_type="MARKET")
        self.assertEqual(sum(name == "place_order" for name, _ in self.sdk.calls), 1)

    def test_market_sell_inventory_simulate_and_unknown_no_duplicate(self):
        deadline = (NOW + timedelta(minutes=10)).isoformat()
        self.sdk.positions = [{"code": "US.AAPL", "qty": 2, "can_sell_qty": 2,
            "market_val": 200, "position_side": "LONG", "currency": "USD"}]
        order = {**self.order, "side": "SELL", "qty": 3}
        with self.assertRaises(BrokerOrderNotSent):
            self.broker.submit(order, "oversell-market", allow_partial_quotes=True,
                               execution_deadline_utc=deadline, order_type="MARKET")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))
        self.sdk.errors.add("place_order")
        order["qty"] = 2
        with self.assertRaises(BrokerError):
            self.broker.submit(order, "unknown-sell-market", allow_partial_quotes=True,
                               execution_deadline_utc=deadline, order_type="MARKET")
        with self.assertRaises(BrokerError):
            self.broker.submit(order, "unknown-sell-market", allow_partial_quotes=True,
                               execution_deadline_utc=deadline, order_type="MARKET")
        submits = [args for name, args in self.sdk.calls if name == "place_order"]
        self.assertEqual(len(submits), 1)
        self.assertEqual(submits[0]["order_type"], "MARKET")
        self.assertEqual(submits[0]["trd_side"], "SELL")
        self.assertEqual(submits[0]["trd_env"], "SIMULATE")
        self.assertEqual(submits[0]["qty"], 2)

    def test_market_order_preserves_qualified_quote_and_cash_guards(self):
        deadline = (NOW + timedelta(minutes=10)).isoformat()
        cases = (
            ("stale", lambda sdk: sdk.quotes["US.AAPL"].update(update_time="2026-09-24 16:00:00")),
            ("wide", lambda sdk: sdk.quotes["US.AAPL"].update(bid_price=98.0, ask_price=102.0)),
            ("cash", lambda sdk: sdk.funds[0].update(usd_net_cash_power=100.0, us_cash=100.0)),
        )
        for label, change in cases:
            sdk = FakeSDK()
            change(sdk)
            broker = MoomooBroker(account_id="222", sdk=sdk, now=lambda: NOW)
            with self.subTest(label=label), self.assertRaises(BrokerOrderNotSent):
                broker.submit(self.order, "guarded-market", allow_partial_quotes=True,
                              execution_deadline_utc=deadline, order_type="MARKET")
            self.assertFalse(any(name == "place_order" for name, _ in sdk.calls))
            self.assertNotIn("guarded-market", broker._attempted)

    def test_market_order_rejects_expired_window_before_sdk_order(self):
        with self.assertRaises(BrokerOrderNotSent):
            self.broker.submit(self.order, "expired-market", allow_partial_quotes=True,
                               execution_deadline_utc=NOW.isoformat(), order_type="MARKET")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_market_order_respects_broker_cash_only_buyable_quantity(self):
        self.sdk.trading_info[0]["max_cash_buy"] = 1
        with self.assertRaises(BrokerOrderNotSent):
            self.broker.submit({**self.order, "qty": 2}, "no-cash-buyable", allow_partial_quotes=True,
                execution_deadline_utc=(NOW + timedelta(minutes=10)).isoformat(),
                order_type="MARKET")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_market_cash_buyable_query_failure_never_places_order(self):
        deadline = (NOW + timedelta(minutes=10)).isoformat()
        for label, change in (
            ("timeout", lambda sdk: sdk.errors.add("acctradinginfo_query")),
            ("missing", lambda sdk: setattr(sdk, "trading_info", [])),
            ("wrong-account", lambda sdk: sdk.trading_info[0].update(acc_id=999)),
            ("malformed", lambda sdk: sdk.trading_info[0].update(max_cash_buy="N/A")),
        ):
            sdk = FakeSDK()
            change(sdk)
            broker = MoomooBroker(account_id="222", sdk=sdk, now=lambda: NOW)
            with self.subTest(label=label), self.assertRaises(BrokerOrderNotSent):
                broker.submit(self.order, "capacity-query", allow_partial_quotes=True,
                              execution_deadline_utc=deadline, order_type="MARKET")
            self.assertFalse(any(name == "place_order" for name, _ in sdk.calls))
            self.assertNotIn("capacity-query", broker._attempted)

    def test_market_order_reconcile_uses_actual_fill_not_zero_sdk_price(self):
        self.sdk.orders = [{"order_id": "market-order", "remark": "market-fill", "code": "US.AAPL",
                            "acc_id": 222, "trd_env": "SIMULATE", "order_type": "MARKET",
                            "qty": 2, "dealt_qty": 2, "dealt_avg_price": 100.25,
                            "price": 0, "order_status": "FILLED_ALL"}]
        result = self.broker.reconcile("market-fill", "market-order")
        self.assertEqual(result["status"], "FILLED_ALL")
        self.assertEqual(result["dealt_qty"], 2)
        self.assertEqual(result["dealt_avg_price"], 100.25)
        self.assertIsNone(result["limit_price"])
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_submit_timeout_never_retried(self):
        self.sdk.errors.add("place_order")
        with self.assertRaises(BrokerError) as failure:
            self.broker.submit(self.order, "timeout-id")
        self.assertNotIsInstance(failure.exception, BrokerReadError)
        self.assertFalse(hasattr(failure.exception, "retry_after_seconds"))
        with self.assertRaisesRegex(BrokerError, "已尝试"):
            self.broker.submit(self.order, "timeout-id")
        self.assertEqual(sum(name == "place_order" for name, _ in self.sdk.calls), 1)

    def test_bad_target_quotes_fail_before_funds_positions_or_orders(self):
        original = deepcopy(self.sdk.quotes["US.AAPL"])
        invalid = ({"update_time": "2026-09-25 10:59:00"},
                   {"bid_price": 101, "ask_price": 100})
        for change in invalid:
            self.sdk.calls.clear()
            self.sdk.quotes["US.AAPL"] = {**original, **change}
            with self.subTest(change=change), self.assertRaises(BrokerError):
                self.broker.snapshot(["US.AAPL"])
            calls = [method for method, _ in self.sdk.calls]
            self.assertIn("get_acc_list", calls)
            self.assertIn("get_order_book", calls)
            self.assertFalse(set(calls) & {"accinfo_query", "position_list_query",
                                          "order_list_query", "place_order"})

    def test_snapshot_preserves_valid_wide_spread_for_execution_core(self):
        self.sdk.quotes["US.AAPL"].update(bid_price=99.5, ask_price=100.5)
        result = self.broker.snapshot(["US.AAPL"])
        self.assertEqual(result["quotes"]["US.AAPL"]["bid"], 99.5)
        self.assertEqual(result["quotes"]["US.AAPL"]["ask"], 100.5)
        self.assertTrue(result["quotes"]["US.AAPL"]["tradable"])
        self.assertFalse(any(method == "place_order" for method, _ in self.sdk.calls))

    def test_target_preflight_then_refresh_account_and_verify_extra_holdings(self):
        self.sdk.add_quote("US.SPY", "ETF")
        self.sdk.positions = [{"code": "US.SPY", "qty": 2, "can_sell_qty": 2,
                               "market_val": 200, "position_side": "LONG", "currency": "USD"}]
        result = self.broker.snapshot(["US.AAPL"])
        self.assertEqual(set(result["quotes"]), {"US.AAPL", "US.SPY"})
        calls = [method for method, _ in self.sdk.calls]
        self.assertLess(calls.index("get_order_book"), calls.index("accinfo_query"))
        books = [args["code"] for method, args in self.sdk.calls if method == "get_order_book"]
        self.assertEqual(books, ["US.AAPL", "US.SPY"])
        for method, args in self.sdk.calls:
            if method in {"accinfo_query", "position_list_query", "order_list_query"}:
                self.assertIs(args["refresh_cache"], True)
                self.assertEqual(args["trd_env"], "SIMULATE")
        # A fresh target must never conceal stale prices for existing holdings.
        self.sdk.calls.clear()
        self.sdk.quotes["US.SPY"]["update_time"] = "2026-09-25 10:59:00"
        with self.assertRaisesRegex(BrokerError, "超过 30 秒"):
            self.broker.snapshot(["US.AAPL"])
        self.assertFalse(any(method in {"order_list_query", "place_order"}
                             for method, _ in self.sdk.calls))

    def test_readonly_query_exceptions_and_nonok_are_typed_and_sanitized(self):
        context = self.broker._trade_context()
        secret = "account=987654321012345 password=not-for-public"
        self.sdk.error_message = secret
        for label in ("get_acc_list", "accinfo_query", "position_list_query",
                      "order_list_query", "history_order_list_query"):
            for failure_kind in ("exception", "nonok"):
                self.sdk.errors.clear()
                self.sdk.failures.clear()
                if failure_kind == "exception":
                    self.sdk.errors.add(label)
                else:
                    self.sdk.failures[label] = {"message": secret}
                with self.subTest(label=label, failure=failure_kind):
                    with self.assertRaises(BrokerReadError) as raised:
                        self.broker._call(getattr(context, label))
                    self.assertEqual(raised.exception.retry_after_seconds, 30)
                    self.assertNotIn("987654321012345", str(raised.exception))
                    self.assertNotIn("not-for-public", str(raised.exception))
                    self.assertNotIn("限频", str(raised.exception))
                    expected = (f"{label} 只读查询调用异常；30 秒后重新查询"
                                if failure_kind == "exception" else
                                f"{label} 只读查询未成功；30 秒后重新查询")
                    self.assertEqual(str(raised.exception), expected)

    def test_only_explicit_readonly_rate_errors_get_fixed_rate_classification(self):
        context = self.broker._trade_context()
        for message in ("Too many requests account=987654321012345", "调用频率限制 password=private",
                        "get_acc_list 请求太频繁 account=987654321012345"):
            self.sdk.failures["accinfo_query"] = message
            with self.subTest(message=message), self.assertRaises(BrokerReadError) as raised:
                self.broker._call(context.accinfo_query)
            self.assertEqual(str(raised.exception), "accinfo_query 只读查询限频；请等待 30 秒后重新查询")
        self.sdk.failures["accinfo_query"] = "limit price invalid account=987654321012345"
        with self.assertRaises(BrokerReadError) as generic:
            self.broker._call(context.accinfo_query)
        self.assertEqual(str(generic.exception),
                         "accinfo_query 只读查询未成功；30 秒后重新查询")
        # Successful-but-malformed data and unknown method failures are not retryable.
        self.sdk.failures.clear()
        self.sdk.funds = "bad response"
        with self.assertRaises(BrokerError) as malformed:
            self.broker._call(context.accinfo_query)
        self.assertNotIsInstance(malformed.exception, BrokerReadError)
        self.sdk.failures["unexpected_query"] = "Too many requests account=987654321012345"
        with self.assertRaises(BrokerError) as unknown:
            self.broker._call(context.unexpected_query)
        self.assertNotIsInstance(unknown.exception, BrokerReadError)
        self.assertNotIn("987654321012345", str(unknown.exception))

    def test_nonok_submission_is_not_retryable_even_for_rate_error(self):
        self.sdk.failures["place_order"] = "Too many requests account=987654321012345"
        with self.assertRaises(BrokerError) as raised:
            self.broker.submit(self.order, "nonok-id")
        self.assertNotIsInstance(raised.exception, BrokerReadError)
        self.assertFalse(hasattr(raised.exception, "retry_after_seconds"))
        self.assertNotIn("987654321012345", str(raised.exception))
        with self.assertRaisesRegex(BrokerError, "已尝试"):
            self.broker.submit(self.order, "nonok-id")
        self.assertEqual(sum(method == "place_order" for method, _ in self.sdk.calls), 1)

    def test_null_order_id_cannot_confirm_submission_or_reconciliation(self):
        self.sdk.submit_result = [{"order_id": None, "order_status": "SUBMITTED"}]
        with self.assertRaisesRegex(BrokerError, "订单号"):
            self.broker.submit(self.order, "null-id")
        self.sdk.orders = [{"order_id": None, "remark": "null-id", "qty": 1,
                            "dealt_qty": 1, "order_status": "FILLED_ALL"}]
        self.assertEqual(self.broker.reconcile("null-id")["status"], "UNKNOWN")

    def test_missing_quote_metadata_does_not_get_fabricated(self):
        for field in ["update_time", "price_spread", "lot_size", "suspension"]:
            original = self.sdk.quotes["US.AAPL"].pop(field)
            with self.subTest(field=field), self.assertRaises(BrokerError):
                self.broker.snapshot(["US.AAPL"])
            self.sdk.quotes["US.AAPL"][field] = original

    def test_submit_guards_stale_future_prices_cash_and_sellable(self):
        for timestamp in ["2026-09-25 10:59:00", "2026-09-25 11:00:16"]:
            self.sdk.quotes["US.AAPL"]["update_time"] = timestamp
            with self.assertRaises(BrokerError):
                self.broker.submit(self.order, "time-id")
        self.sdk.quotes["US.AAPL"]["update_time"] = "2026-09-25 11:00:00"
        for order in [{**self.order, "qty": 10}, {**self.order, "side": "SELL"},
                      {**self.order, "limit_price": 100.015}, {**self.order, "qty": True}]:
            with self.subTest(order=order), self.assertRaises(BrokerError):
                self.broker.submit(order, "invalid-id")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_pending_order_any_instrument_blocks_submit(self):
        self.sdk.orders = [{"order_id": "foreign", "code": "HK.00700", "order_status": "FILLED_PART"}]
        with self.assertRaisesRegex(BrokerError, "未完成订单"):
            self.broker.submit(self.order, "new-id")

    def test_cancel_during_snapshot_stops_before_submission_attempt(self):
        cancelled = False
        self.broker.cancel_check = lambda: cancelled
        original_snapshot = self.broker.snapshot

        def snapshot_then_cancel(codes):
            nonlocal cancelled
            result = original_snapshot(codes)
            cancelled = True
            return result

        with patch.object(self.broker, "snapshot", side_effect=snapshot_then_cancel):
            with self.assertRaisesRegex(BrokerError, "停止请求"):
                self.broker.submit(self.order, "cancelled-id")
        self.assertNotIn("cancelled-id", self.broker._attempted)
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_cancel_check_failure_fails_closed(self):
        def broken_check():
            raise RuntimeError("stop status unavailable")
        self.broker.cancel_check = broken_check
        with self.assertRaisesRegex(BrokerError, "无法确认停止状态"):
            self.broker.submit(self.order, "broken-stop")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_final_limit_deviation_and_spread_limits(self):
        for price in [97.99, 102.01]:
            with self.subTest(price=price), self.assertRaisesRegex(BrokerError, "限价偏离"):
                self.broker.submit({**self.order, "limit_price": price}, "deviation-id")
        self.sdk.quotes["US.AAPL"]["bid_price"] = 98.99
        self.sdk.quotes["US.AAPL"]["ask_price"] = 101.01
        with self.assertRaisesRegex(BrokerError, "价差"):
            self.broker.submit(self.order, "spread-id")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_fee_buffer_is_enforced_and_exact_boundary_is_allowed(self):
        order = {**self.order, "limit_price": 100, "qty": 9}
        with self.assertRaisesRegex(BrokerError, "费用缓冲"):
            self.broker.submit(order, "fee-id")
        self.sdk.funds[0]["usd_net_cash_power"] = 904.5
        self.assertEqual(self.broker.submit(order, "fee-boundary")["status"], "SUBMITTED")

    def test_reconcile_missing_or_duplicate_is_unknown_but_query_failure_is_read_error(self):
        self.assertEqual(self.broker.reconcile("lost")["status"], "UNKNOWN")
        self.sdk.orders = [{"order_id": "one", "remark": "lost", "qty": 1, "dealt_qty": 0, "order_status": "SUBMITTED"},
                           {"order_id": "two", "remark": "lost", "qty": 1, "dealt_qty": 0, "order_status": "SUBMITTED"}]
        self.assertEqual(self.broker.reconcile("lost")["status"], "UNKNOWN")
        self.sdk.orders = []
        self.sdk.errors.add("history_order_list_query")
        with self.assertRaises(BrokerReadError):
            self.broker.reconcile("lost", "one")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_known_order_temporarily_absent_from_both_lists_remains_pending(self):
        self.sdk.orders = []
        self.sdk.history = []
        with self.assertRaises(BrokerReadError):
            self.broker.reconcile("client-1", "test-order")
        self.assertEqual(self.broker.reconcile("client-1")["status"], "UNKNOWN")
        self.assertFalse(any(name in {"modify_order", "place_order"} for name, _ in self.sdk.calls))

    def test_terminal_failure_with_reported_fill_never_becomes_safe_to_retry(self):
        for status in ("FAILED", "CANCELLED_ALL", "SUBMITTED"):
            with self.subTest(status=status):
                self.sdk.orders = [{"order_id": "test-order", "remark": "client-1", "qty": 9,
                                    "dealt_qty": 1, "dealt_avg_price": 100.0,
                                    "order_status": status, "price": 100.0}]
                self.assertEqual(self.broker.reconcile("client-1", "test-order")["status"], "UNKNOWN")

    def test_current_and_history_order_reads_each_obey_nine_per_thirty_seconds(self):
        clock = [100.0]
        self.broker._monotonic = lambda: clock[0]
        trade = self.broker._trade_context()
        for _ in range(9):
            self.assertEqual(self.broker._call(trade.order_list_query, refresh_cache=True), [])
        with self.assertRaises(BrokerReadError):
            self.broker._call(trade.order_list_query, refresh_cache=True)
        self.assertEqual(sum(name == "order_list_query" for name, _ in self.sdk.calls), 9)
        for _ in range(9):
            self.assertEqual(self.broker._call(trade.history_order_list_query), [])
        with self.assertRaises(BrokerReadError):
            self.broker._call(trade.history_order_list_query)
        self.assertEqual(sum(name == "history_order_list_query" for name, _ in self.sdk.calls), 9)
        clock[0] += 30.0
        self.assertEqual(self.broker._call(trade.order_list_query, refresh_cache=True), [])
        self.assertEqual(self.broker._call(trade.history_order_list_query), [])

    def test_funds_only_snapshot_consumes_the_same_current_order_read_quota(self):
        self.broker._monotonic = lambda: 100.0
        self.broker.snapshot([], include_quotes=False)
        trade = self.broker._trade_context()
        for _ in range(8):
            self.broker._call(trade.order_list_query, refresh_cache=True)
        with self.assertRaises(BrokerReadError):
            self.broker._call(trade.order_list_query, refresh_cache=True)
        self.assertEqual(sum(name == "order_list_query" for name, _ in self.sdk.calls), 9)

    def test_reprice_uses_original_broker_order_id_and_total_quantity_after_partial_fill(self):
        order = self.reprice_fixture(dealt_qty=3)
        deadline = (NOW + timedelta(seconds=60)).isoformat()
        result = self.broker.reprice(order, "test-order", "client-1",
                                     expected_dealt_qty=3, execution_deadline_utc=deadline)
        self.assertEqual(result["order_id"], "test-order")
        self.assertEqual(result["status"], "PENDING_RECONCILE")
        self.assertEqual(result["qty"], 9)
        self.assertEqual(result["dealt_qty"], 3)
        self.assertEqual(result["limit_price"], 100.02)
        modifications = [kwargs for name, kwargs in self.sdk.calls if name == "modify_order"]
        self.assertEqual(len(modifications), 1)
        self.assertEqual(modifications[0]["order_id"], "test-order")
        self.assertEqual(modifications[0]["qty"], 9)  # Moomoo modify qty is total, not six remaining shares.
        self.assertEqual(modifications[0]["price"], 100.02)
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_reprice_rejects_budget_excess_quantity_increase_and_stale_fill_expectation(self):
        deadline = (NOW + timedelta(seconds=60)).isoformat()
        order = self.reprice_fixture(dealt_qty=3)
        with self.assertRaises(BrokerError):
            self.broker.reprice({**order, "max_order_notional": 900.0}, "test-order", "client-1",
                                expected_dealt_qty=3, execution_deadline_utc=deadline)
        with self.assertRaises(BrokerError):
            self.broker.reprice({**order, "qty": 10}, "test-order", "client-1",
                                expected_dealt_qty=3, execution_deadline_utc=deadline)
        with self.assertRaises(BrokerReadError):
            self.broker.reprice(order, "test-order", "client-1",
                                expected_dealt_qty=2, execution_deadline_utc=deadline)
        self.assertFalse(any(name == "modify_order" for name, _ in self.sdk.calls))

    def test_reprice_rejects_existing_position_plus_remaining_above_symbol_budget(self):
        order = self.reprice_fixture(dealt_qty=3)
        self.sdk.positions = [{"code": "US.AAPL", "qty": 4, "can_sell_qty": 4,
                               "market_val": 400, "position_side": "LONG", "currency": "USD"}]
        with self.assertRaises(BrokerReadError):
            self.broker.reprice(order, "test-order", "client-1", expected_dealt_qty=3,
                execution_deadline_utc=(NOW + timedelta(seconds=60)).isoformat())
        self.assertFalse(any(name in {"modify_order", "place_order"} for name, _ in self.sdk.calls))

    def test_reprice_expiry_and_read_failure_do_not_modify_or_place_order(self):
        order = self.reprice_fixture(dealt_qty=0)
        with self.assertRaises(BrokerError):
            self.broker.reprice(order, "test-order", "client-1", expected_dealt_qty=0,
                                execution_deadline_utc=NOW.isoformat())
        self.sdk.errors.add("order_list_query")
        with self.assertRaises(BrokerReadError):
            self.broker.reprice(order, "test-order", "client-1", expected_dealt_qty=0,
                                execution_deadline_utc=(NOW + timedelta(seconds=60)).isoformat())
        self.assertFalse(any(name in {"modify_order", "place_order"} for name, _ in self.sdk.calls))

    def test_reprice_can_recheck_a_wide_spread_and_modify_after_quote_recovers(self):
        order = self.reprice_fixture(dealt_qty=0)
        deadline = (NOW + timedelta(seconds=60)).isoformat()
        self.sdk.quotes["US.AAPL"].update(bid_price=98, ask_price=102)
        with self.assertRaises(BrokerReadError):
            self.broker.reprice(order, "test-order", "client-1", expected_dealt_qty=0,
                                execution_deadline_utc=deadline)
        self.assertFalse(any(name == "modify_order" for name, _ in self.sdk.calls))
        self.sdk.quotes["US.AAPL"].update(bid_price=100.00, ask_price=100.02, last_price=100.01)
        result = self.broker.reprice(order, "test-order", "client-1", expected_dealt_qty=0,
                                     execution_deadline_utc=deadline)
        self.assertEqual(result["order_id"], "test-order")
        self.assertEqual(sum(name == "modify_order" for name, _ in self.sdk.calls), 1)

    def test_reprice_rpc_failure_never_falls_back_to_new_order(self):
        order = self.reprice_fixture(dealt_qty=0)
        self.sdk.errors.add("modify_order")
        with self.assertRaises(BrokerError):
            self.broker.reprice(order, "test-order", "client-1", expected_dealt_qty=0,
                                execution_deadline_utc=(NOW + timedelta(seconds=60)).isoformat())
        self.assertEqual(sum(name == "modify_order" for name, _ in self.sdk.calls), 1)
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_reconcile_order_fill_from_history_and_contradictions(self):
        self.sdk.orders = []
        self.sdk.history = [{"order_id": "one", "remark": "lost", "qty": 2, "dealt_qty": 2, "order_status": "FILLED_ALL"}]
        self.assertEqual(self.broker.reconcile("lost"), {"status": "FILLED_ALL", "order_id": "one",
                                                       "dealt_qty": 2, "dealt_avg_price": None,
                                                       "qty": 2, "limit_price": None})
        self.sdk.history[0]["dealt_qty"] = 1
        self.assertEqual(self.broker.reconcile("lost")["status"], "UNKNOWN")

    def test_reconcile_average_is_actual_cumulative_fill_not_order_limit(self):
        self.sdk.orders = []
        self.sdk.history = [{"order_id": "one", "remark": "lost", "qty": 2, "dealt_qty": 2,
                             "order_status": "FILLED_ALL", "dealt_avg_price": 100.2, "price": 101}]
        result = self.broker.reconcile("lost", "one")
        self.assertEqual(result, {"status": "FILLED_ALL", "order_id": "one", "dealt_qty": 2,
                                  "dealt_avg_price": 100.2, "qty": 2, "limit_price": 101.0})
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_reconcile_unknown_average_remains_none_without_invented_limit_fill(self):
        row = {"order_id": "one", "remark": "lost", "qty": 2, "dealt_qty": 2,
               "order_status": "FILLED_ALL", "price": 500}
        for invalid in (None, "N/A", 0, -1, True, float("nan"), float("inf")):
            self.sdk.orders = [{**row, "dealt_avg_price": invalid}]
            with self.subTest(invalid=invalid):
                result = self.broker.reconcile("lost")
                self.assertEqual(result["dealt_qty"], 2)
                self.assertEqual(result["status"], "FILLED_ALL")
                self.assertIsNone(result["dealt_avg_price"])
        self.sdk.orders = [{**row, "dealt_qty": 0, "order_status": "SUBMITTED", "dealt_avg_price": 500}]
        self.assertIsNone(self.broker.reconcile("lost")["dealt_avg_price"])

    def test_reconcile_conflicting_averages_for_same_fill_quantity_are_unknown(self):
        row = {"order_id": "one", "remark": "lost", "qty": 2, "dealt_qty": 2,
               "order_status": "FILLED_ALL", "dealt_avg_price": 100}
        self.sdk.orders = [row, {**row, "dealt_avg_price": 101}]
        self.assertEqual(self.broker.reconcile("lost", "one")["status"], "UNKNOWN")
        self.sdk.orders = [row, {**row, "dealt_avg_price": None}]
        self.assertEqual(self.broker.reconcile("lost", "one")["dealt_avg_price"], 100)

    def test_snapshot_requires_order_book_and_uses_quote_context_firm(self):
        self.broker.snapshot(["US.AAPL"])
        self.assertTrue(any(name == "get_order_book" for name, _ in self.sdk.calls))
        context_args = [args for name, args in self.sdk.calls if name == "OpenQuoteContext"][0]
        self.assertEqual(context_args["security_firm"], "FUTUSECURITIES")

    def test_closed_market_funds_only_reads_account_metadata_without_quotes(self):
        self.sdk.positions = [{"code": "US.AAPL", "qty": 2, "can_sell_qty": 2,
                               "market_val": 200, "position_side": "LONG", "currency": "USD"}]
        self.sdk.orders = [{"order_id": "pending", "code": "US.AAPL", "order_status": "SUBMITTED"}]
        self.sdk.states["US.AAPL"]["market_state"] = "CLOSED"
        self.sdk.quotes["US.AAPL"]["update_time"] = "2026-09-24 16:00:00"
        result = self.broker.snapshot([], include_quotes=False)
        self.assertEqual(result["cash"], 900)
        self.assertEqual(result["positions"]["US.AAPL"]["qty"], 2)
        self.assertEqual(result["open_orders"][0]["order_id"], "pending")
        self.assertEqual(result["quotes"], {})
        self.assertTrue(result["funds_only"])
        self.assertEqual(result["valuation_basis"], "BROKER_ACCOUNT_METADATA")
        allowed = {"OpenSecTradeContext", "get_acc_list", "accinfo_query",
                   "position_list_query", "order_list_query"}
        self.assertTrue(all(name in allowed for name, _ in self.sdk.calls))
        self.assertFalse(any(context.kind == "quote" for context in self.sdk.contexts))
        # The default path must still require current real quotes for held stock.
        with self.assertRaisesRegex(BrokerError, "超过 30 秒"):
            self.broker.snapshot([])

    def test_funds_only_rejects_nonempty_codes_and_ambiguous_flag_before_network(self):
        for codes, flag in ((["US.AAPL"], False), ([], "False"), ([], 0), ([], None)):
            with self.subTest(codes=codes, flag=flag), self.assertRaises(BrokerError):
                self.broker.snapshot(codes, include_quotes=flag)
        self.assertEqual(self.sdk.calls, [])

    def test_funds_only_still_requires_valid_simulation_account_and_positions(self):
        self.sdk.accounts[1]["trd_env"] = "REAL"
        with self.assertRaises(BrokerError):
            self.broker.snapshot([], include_quotes=False)
        self.sdk.accounts[1]["trd_env"] = "SIMULATE"
        self.sdk.positions = [{"code": "HK.00700", "qty": 2, "can_sell_qty": 2,
                               "market_val": 200, "position_side": "LONG", "currency": "HKD"}]
        with self.assertRaises(BrokerError):
            self.broker.snapshot([], include_quotes=False)

    def test_submit_always_uses_default_quote_validation_after_metadata_read(self):
        self.broker.snapshot([], include_quotes=False)
        original = self.broker.snapshot
        with patch.object(self.broker, "snapshot", wraps=original) as observed:
            self.broker.submit(self.order, "metadata-is-not-price")
        self.assertEqual(observed.call_args.args, (["US.AAPL"],))
        self.assertEqual(observed.call_args.kwargs, {})
        self.assertTrue(any(name == "get_order_book" for name, _ in self.sdk.calls))
        args = [kwargs for name, kwargs in self.sdk.calls if name == "place_order"][0]
        self.assertEqual(args["trd_env"], "SIMULATE")

    def test_metadata_read_never_allows_stale_market_order(self):
        self.sdk.quotes["US.AAPL"]["update_time"] = "2026-09-24 16:00:00"
        self.broker.snapshot([], include_quotes=False)
        with self.assertRaisesRegex(BrokerError, "超过 30 秒"):
            self.broker.submit(self.order, "stale-after-metadata")
        self.assertFalse(any(name == "place_order" for name, _ in self.sdk.calls))

    def test_close_closes_both_contexts(self):
        self.broker.snapshot(["US.AAPL"])
        self.broker.close()
        self.assertTrue(all(context.closed for context in self.sdk.contexts))

    def test_prewarm_has_no_account_queries_prices_or_orders(self):
        self.broker.prewarm(['US.AAPL'])
        self.assertTrue(any(name == 'subscribe' for name, _ in self.sdk.calls))
        forbidden = {'OpenSecTradeContext', 'get_acc_list', 'accinfo_query',
                     'position_list_query', 'order_list_query', 'get_market_snapshot',
                     'get_order_book', 'place_order'}
        self.assertFalse(any(name in forbidden for name, _ in self.sdk.calls))

    def test_partial_snapshot_keeps_good_target_and_reports_bad_held_quote(self):
        self.sdk.add_quote('US.SPY')
        self.sdk.quotes['US.SPY']['update_time'] = '2026-09-24 16:00:00'
        self.sdk.positions = [{'code': 'US.SPY', 'qty': 2, 'can_sell_qty': 2,
                               'market_val': 200, 'position_side': 'LONG', 'currency': 'USD'}]
        state = self.broker.snapshot_partial(['US.AAPL'])
        self.assertEqual(set(state['quotes']), {'US.AAPL'})
        self.assertEqual(set(state['quote_errors']), {'US.SPY'})
        self.assertEqual(state['positions']['US.SPY']['qty'], 2)
        self.assertEqual(state['valuation_basis'], 'BROKER_ACCOUNT_REFRESH')
        self.assertEqual(state['cash'], 900)
        self.assertTrue(all(args['refresh_cache'] for name, args in self.sdk.calls
                            if name in {'accinfo_query', 'position_list_query', 'order_list_query'}))

    def test_partial_good_order_can_submit_without_using_bad_held_price(self):
        self.sdk.add_quote('US.SPY')
        self.sdk.quotes['US.SPY']['update_time'] = '2026-09-24 16:00:00'
        self.sdk.positions = [{'code': 'US.SPY', 'qty': 2, 'can_sell_qty': 2,
                               'market_val': 200, 'position_side': 'LONG', 'currency': 'USD'}]
        result = self.broker.submit(self.order, 'qualified-only', allow_partial_quotes=True,
                                   execution_deadline_utc=(NOW + timedelta(minutes=10)).isoformat())
        self.assertEqual(result['status'], 'SUBMITTED')
        submitted = [args for name, args in self.sdk.calls if name == 'place_order']
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]['code'], 'US.AAPL')
        self.assertEqual(submitted[0]['trd_env'], 'SIMULATE')

    def test_partial_bad_quote_is_definitely_unsent_and_can_recover(self):
        self.sdk.quotes['US.AAPL']['update_time'] = '2026-09-24 16:00:00'
        expiry = (NOW + timedelta(minutes=10)).isoformat()
        with self.assertRaises(BrokerOrderNotSent):
            self.broker.submit(self.order, 'recover-preflight', allow_partial_quotes=True,
                               execution_deadline_utc=expiry)
        self.assertNotIn('recover-preflight', self.broker._attempted)
        self.assertFalse(any(name == 'place_order' for name, _ in self.sdk.calls))
        self.sdk.quotes['US.AAPL']['update_time'] = '2026-09-25 11:00:00'
        self.broker.submit(self.order, 'recover-preflight', allow_partial_quotes=True,
                           execution_deadline_utc=expiry)
        with self.assertRaises(BrokerError) as caught:
            self.broker.submit(self.order, 'recover-preflight', allow_partial_quotes=True,
                               execution_deadline_utc=expiry)
        self.assertNotIsInstance(caught.exception, BrokerOrderNotSent)
        self.assertEqual(sum(name == 'place_order' for name, _ in self.sdk.calls), 1)

    def test_partial_deadline_is_rechecked_after_long_account_rpc(self):
        current = [NOW]
        self.broker._now = lambda: current[0]
        original = self.broker.snapshot_partial
        def delayed_read(codes):
            state = original(codes)
            current[0] += timedelta(seconds=6)
            return state
        with patch.object(self.broker, 'snapshot_partial', side_effect=delayed_read):
            with self.assertRaisesRegex(BrokerOrderNotSent, '执行窗口已结束'):
                self.broker.submit(self.order, 'expired-during-read', allow_partial_quotes=True,
                    execution_deadline_utc=(NOW + timedelta(seconds=5)).isoformat())
        self.assertNotIn('expired-during-read', self.broker._attempted)
        self.assertFalse(any(name == 'place_order' for name, _ in self.sdk.calls))

    def test_partial_final_spread_and_missing_deadline_cannot_send(self):
        with self.assertRaisesRegex(BrokerOrderNotSent, '缺少截止时间'):
            self.broker.submit(self.order, 'missing-window', allow_partial_quotes=True)
        self.assertEqual(self.sdk.calls, [])
        self.sdk.quotes['US.AAPL'].update(bid_price=99.5, ask_price=100.5)
        with self.assertRaisesRegex(BrokerOrderNotSent, '超过50bp'):
            self.broker.submit(self.order, 'spread-changed', allow_partial_quotes=True,
                execution_deadline_utc=(NOW + timedelta(minutes=10)).isoformat())
        self.assertFalse(any(name == 'place_order' for name, _ in self.sdk.calls))

    def test_partial_funds_rate_limit_never_uses_cached_money(self):
        clock = [1.0]
        self.broker._monotonic = lambda: clock[0]
        self.broker.snapshot_partial(['US.AAPL'])
        context = self.broker._trade_context()
        for _ in range(9):
            self.broker._call(context.accinfo_query, **self.broker._account_args(), refresh_cache=True)
        count = sum(name == 'accinfo_query' for name, _ in self.sdk.calls)
        with self.assertRaises(BrokerReadError):
            self.broker.snapshot_partial(['US.AAPL'])
        self.assertEqual(sum(name == 'accinfo_query' for name, _ in self.sdk.calls), count)
        clock[0] += 30
        self.assertEqual(self.broker.snapshot_partial(['US.AAPL'])['cash'], 900)
        self.assertEqual(sum(name == 'accinfo_query' for name, _ in self.sdk.calls), count + 1)

    def test_partial_read_failure_is_unsent_but_sdk_send_timeout_stays_unknown(self):
        expiry = (NOW + timedelta(minutes=10)).isoformat()
        self.sdk.failures['accinfo_query'] = 'provider error with private payload'
        with self.assertRaises(BrokerOrderNotSent) as caught:
            self.broker.submit(self.order, 'failed-read', allow_partial_quotes=True,
                               execution_deadline_utc=expiry)
        self.assertEqual(caught.exception.retry_after_seconds, 30)
        self.assertNotIn('failed-read', self.broker._attempted)
        self.assertNotIn('private payload', str(caught.exception))
        self.sdk.failures.clear()
        self.sdk.errors.add('place_order')
        with self.assertRaises(BrokerError) as unknown:
            self.broker.submit(self.order, 'send-timeout', allow_partial_quotes=True,
                               execution_deadline_utc=expiry)
        self.assertNotIsInstance(unknown.exception, BrokerOrderNotSent)
        self.assertIn('send-timeout', self.broker._attempted)


if __name__ == "__main__":
    unittest.main()
