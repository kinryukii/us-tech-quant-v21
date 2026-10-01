"""Paper feed tests are SDK fakes only; no network, account or order APIs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from moomoo_component.brokers import BrokerError
from moomoo_component.quotes import MoomooQuoteFeed


NOW = datetime(2026, 9, 25, 15, 0, 15, tzinfo=timezone.utc)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return deepcopy(self.rows)


class QuoteContext:
    def __init__(self, sdk):
        self.sdk, self.closed = sdk, False

    def close(self):
        self.closed = True

    def get_stock_basicinfo(self, **kwargs):
        return self.sdk.respond("get_stock_basicinfo", kwargs, "basic")

    def subscribe(self, **kwargs):
        return self.sdk.respond("subscribe", kwargs, None)

    def get_market_state(self, **kwargs):
        return self.sdk.respond("get_market_state", kwargs, "states")

    def get_market_snapshot(self, **kwargs):
        return self.sdk.respond("get_market_snapshot", kwargs, "snapshots")

    def get_order_book(self, **kwargs):
        return self.sdk.respond("get_order_book", kwargs, "books")

    def __getattr__(self, name):
        raise AssertionError(f"Forbidden / unexpected SDK call: {name}")


class QuoteSDK:
    RET_OK = 0

    def __init__(self):
        for group, members in {
            "SecurityFirm": ["FUTUSECURITIES"], "Market": ["US"],
            "SubType": ["QUOTE", "ORDER_BOOK"], "Session": ["RTH"],
            "SecurityStatus": ["NORMAL", "SUSPENDED", "DELISTED"],
        }.items():
            setattr(self, group, SimpleNamespace(**{member: member for member in members}))
        self.calls, self.failures, self.exceptions = [], {}, set()
        self.basic, self.states, self.snapshots, self.books = {}, {}, {}, {}
        self.context = None
        self.dataframes = False
        self.add("US.AAPL")
        self.add("US.SPY", "ETF")

    def add(self, code, stock_type="STOCK"):
        self.basic[code] = {"code": code, "stock_type": stock_type, "delisting": False,
                            "lot_size": 1}
        self.states[code] = {"code": code, "market_state": "AFTERNOON"}
        self.snapshots[code] = {"code": code, "last_price": 100.0,
            "update_time": "2026-09-25 11:00:00", "lot_size": 1, "price_spread": 0.01,
            "suspension": False, "sec_status": "NORMAL"}
        self.books[code] = {"code": code, "order_book_type": "NORMAL",
            "svr_recv_time_bid": "2026-09-25 11:00:05",
            "svr_recv_time_ask": "2026-09-25 11:00:06",
            "Bid": [(99.99, 500, 1, {})], "Ask": [(100.01, 300, 1, {})]}

    def OpenQuoteContext(self, **kwargs):
        self.calls.append(("OpenQuoteContext", kwargs))
        self.context = QuoteContext(self)
        return self.context

    def OpenSecTradeContext(self, **kwargs):
        raise AssertionError("Quote feed must never create a trade context")

    def respond(self, method, kwargs, attr):
        self.calls.append((method, kwargs))
        if method in self.exceptions:
            raise TimeoutError("account/password must not be echoed")
        if method in self.failures:
            return -1, self.failures[method]
        if attr is None:
            return 0, None
        data = getattr(self, attr)
        if attr == "books":
            return 0, deepcopy(data[kwargs["code"]])
        rows = [deepcopy(data[code]) for code in kwargs["code_list"]]
        return 0, Rows(rows) if self.dataframes else rows


class QuoteFeedTests(unittest.TestCase):
    def setUp(self):
        self.sdk, self.now, self.mono = QuoteSDK(), NOW, 100.0
        self.feed = MoomooQuoteFeed(sdk=self.sdk, now=lambda: self.now,
                                    monotonic=lambda: self.mono)

    def test_lazy_constructor_empty_batch_and_close_never_connect(self):
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(self.feed.quotes([]), {})
        self.feed.close()
        self.feed.close()
        self.assertEqual(self.sdk.calls, [])
        with self.assertRaisesRegex(BrokerError, "已关闭"):
            self.feed.quotes(["US.AAPL"])

    def test_prewarm_subscribes_without_price_calls_cache_or_source_clock(self):
        self.sdk.snapshots["US.AAPL"]["update_time"] = "invalid-source-time"
        snapshots, books = deepcopy(self.sdk.snapshots), deepcopy(self.sdk.books)
        with patch.object(self.feed, "_utc_now", side_effect=AssertionError("no price clock during prewarm")):
            self.assertIsNone(self.feed.prewarm(["US.SPY", "US.AAPL"]))
        self.assertEqual([method for method, _ in self.sdk.calls],
                         ["OpenQuoteContext", "get_stock_basicinfo", "subscribe"])
        subscription = self.sdk.calls[-1][1]
        self.assertEqual(subscription["code_list"], ["US.AAPL", "US.SPY"])
        self.assertEqual(subscription["subtype_list"], ["QUOTE", "ORDER_BOOK"])
        self.assertEqual(subscription["session"], "RTH")
        self.assertTrue(subscription["is_first_push"])
        self.assertTrue(subscription["subscribe_push"])
        self.assertFalse(subscription["extended_time"])
        self.assertEqual((self.feed._cache, self.feed._state_cache), ({}, {}))
        self.assertEqual((self.sdk.snapshots, self.sdk.books), (snapshots, books))

    def test_prewarm_and_quotes_share_idempotent_subscription_and_keep_price_gates(self):
        codes = ["US.AAPL", "US.SPY"]
        self.feed.prewarm(codes)
        self.feed.prewarm(list(reversed(codes)))
        self.mono += 6  # Even expired basic metadata cannot duplicate the subscription.
        self.feed.prewarm(codes)
        self.assertEqual(sum(method == "subscribe" for method, _ in self.sdk.calls), 1)
        self.sdk.snapshots["US.SPY"]["update_time"] = (self.now - timedelta(seconds=31)).isoformat()
        with self.assertRaisesRegex(BrokerError, "US.SPY last_price.*30 秒"):
            self.feed.quotes(codes)
        self.assertEqual(self.feed._cache, {})
        self.sdk.snapshots["US.SPY"]["update_time"] = "2026-09-25 11:00:00"
        self.assertEqual(set(self.feed.quotes(codes)), set(codes))
        self.assertEqual(sum(method == "subscribe" for method, _ in self.sdk.calls), 1)

    def test_prewarm_rejects_unsupported_security_before_any_subscription(self):
        self.sdk.basic["US.SPY"]["stock_type"] = "OPTION"
        with self.assertRaisesRegex(BrokerError, "不是股票或 ETF"):
            self.feed.prewarm(["US.AAPL", "US.SPY"])
        self.assertFalse(any(method == "subscribe" for method, _ in self.sdk.calls))
        self.assertEqual(self.feed._subscribed, set())
        self.assertEqual(self.feed._cache, {})

    def test_prewarm_empty_closed_and_invalid_batches_do_not_connect(self):
        self.assertIsNone(self.feed.prewarm([]))
        for codes in ("US.AAPL", ["HK.00700"], ["US.AAPL"] * 101):
            with self.subTest(codes=codes), self.assertRaises(BrokerError):
                self.feed.prewarm(codes)
        self.feed.close()
        with self.assertRaisesRegex(BrokerError, "已关闭"):
            self.feed.prewarm(["US.AAPL"])
        self.assertEqual(self.sdk.calls, [])

    def test_partial_stale_bynd_returns_only_valid_security_and_deletes_failed_cache(self):
        self.sdk.add("US.BYND")
        codes = ["US.AAPL", "US.BYND"]
        self.feed.quotes(codes)
        self.sdk.snapshots["US.BYND"]["update_time"] = (self.now - timedelta(seconds=31)).isoformat()
        result = self.feed.quotes_partial(codes, refresh=True)
        self.assertEqual(set(result["quotes"]), {"US.AAPL"})
        self.assertEqual(set(result["errors"]), {"US.BYND"})
        self.assertIn("US.BYND last_price", result["errors"]["US.BYND"])
        self.assertEqual(set(self.feed._cache), {"US.AAPL"})
        row = result["quotes"]["US.AAPL"]
        self.assertEqual(row["received_at"], NOW.isoformat())
        self.assertEqual(row["raw_timestamps"]["last_price"], "2026-09-25 11:00:00")
        source_clocks = [datetime.fromisoformat(row[field + "_asof"])
                         for field in ("last_price", "bid", "ask")]
        self.assertTrue(all(0 <= (NOW - stamp).total_seconds() <= 30 for stamp in source_clocks))
        self.assertEqual(datetime.fromisoformat(row["asof"]), min(source_clocks))
        self.assertLess(datetime.fromisoformat(row["asof"]), NOW)
        self.sdk.snapshots["US.BYND"]["update_time"] = "2026-09-25 11:00:00"
        self.assertEqual(set(self.feed.quotes_partial(codes, refresh=True)["quotes"]), set(codes))

    def test_partial_invalid_clock_is_local_and_redacted(self):
        secret = "private-invalid-source-value"
        self.sdk.books["US.SPY"]["svr_recv_time_ask"] = secret
        result = self.feed.quotes_partial(["US.AAPL", "US.SPY"])
        self.assertEqual(set(result["quotes"]), {"US.AAPL"})
        self.assertEqual(set(result["errors"]), {"US.SPY"})
        self.assertIn("US.SPY ask", result["errors"]["US.SPY"])
        self.assertNotIn(secret, str(result))

    def test_partial_book_rpc_failure_is_local_and_redacted(self):
        original = self.sdk.respond
        def respond(method, kwargs, attr):
            if method == "get_order_book" and kwargs["code"] == "US.SPY":
                return -1, "private-provider-payload"
            return original(method, kwargs, attr)
        with patch.object(self.sdk, "respond", side_effect=respond):
            result = self.feed.quotes_partial(["US.AAPL", "US.SPY"])
        self.assertEqual(set(result["quotes"]), {"US.AAPL"})
        self.assertEqual(set(result["errors"]), {"US.SPY"})
        self.assertNotIn("private-provider-payload", str(result))
        self.assertEqual(set(self.feed._cache), {"US.AAPL"})

    def test_partial_bulk_missing_duplicate_or_unexpected_codes_fail_every_security(self):
        codes = ["US.AAPL", "US.SPY"]
        for method, attr in (("get_stock_basicinfo", "basic"), ("get_market_state", "states"),
                             ("get_market_snapshot", "snapshots")):
            for shape in ("missing", "duplicate", "unexpected"):
                with self.subTest(method=method, shape=shape):
                    self.feed.quotes(codes, refresh=True)
                    self.mono += 6
                    data = getattr(self.sdk, attr)
                    rows = [deepcopy(data["US.AAPL"]), deepcopy(data["US.SPY"])]
                    if shape == "missing":
                        rows.pop()
                    elif shape == "duplicate":
                        rows.append(deepcopy(rows[0]))
                    else:
                        rows.append({**rows[0], "code": "US.UNEXPECTED"})
                    calls = len(self.sdk.calls)
                    with patch.object(self.sdk.context, method, return_value=(0, rows)):
                        result = self.feed.quotes_partial(codes, refresh=True)
                    self.assertEqual(result["quotes"], {})
                    self.assertEqual(set(result["errors"]), set(codes))
                    self.assertEqual(self.feed._cache, {})
                    self.assertFalse(any(name == "get_order_book" for name, _ in self.sdk.calls[calls:]))

    def test_partial_bulk_provider_refusal_has_no_old_price_fallback(self):
        codes = ["US.AAPL", "US.SPY"]
        for method in ("get_stock_basicinfo", "subscribe", "get_market_state", "get_market_snapshot"):
            with self.subTest(method=method):
                self.feed.quotes(codes, refresh=True)
                self.mono += 6
                if method == "subscribe":
                    self.feed._subscribed.clear()
                with patch.dict(self.sdk.failures, {method: "permission private-provider-payload"}):
                    result = self.feed.quotes_partial(codes, refresh=True)
                self.assertEqual(result["quotes"], {})
                self.assertEqual(set(result["errors"]), set(codes))
                self.assertNotIn("private-provider-payload", str(result))
                self.assertEqual(self.feed._cache, {})

    def test_partial_nontradable_and_unsupported_security_are_local_failures(self):
        codes = ["US.AAPL", "US.SPY"]
        for attr, field, invalid in (("snapshots", "suspension", True),
                                      ("states", "market_state", "CLOSED"),
                                      ("basic", "stock_type", "OPTION")):
            with self.subTest(attr=attr, field=field):
                data = getattr(self.sdk, attr)["US.SPY"]
                prior = data[field]
                self.mono += 6
                data[field] = invalid
                result = self.feed.quotes_partial(codes, refresh=True)
                self.assertEqual(set(result["quotes"]), {"US.AAPL"})
                self.assertEqual(set(result["errors"]), {"US.SPY"})
                self.assertEqual(set(self.feed._cache), {"US.AAPL"})
                data[field] = prior

    def test_partial_cache_keeps_original_source_clocks_and_returns_copies(self):
        codes = ["US.AAPL", "US.SPY"]
        result = self.feed.quotes_partial(codes)
        calls = len(self.sdk.calls)
        result["quotes"]["US.AAPL"]["raw_timestamps"]["bid"] = "mutated"
        self.mono += 4.99
        self.now += timedelta(seconds=4.99)
        second = self.feed.quotes_partial(codes)
        self.assertEqual(len(self.sdk.calls), calls)
        self.assertEqual(second["errors"], {})
        self.assertEqual(second["quotes"]["US.AAPL"]["received_at"], NOW.isoformat())
        self.assertEqual(second["quotes"]["US.AAPL"]["bid_asof"], "2026-09-25T15:00:05+00:00")
        self.assertEqual(second["quotes"]["US.AAPL"]["raw_timestamps"]["bid"], "2026-09-25 11:00:05")

    def test_partial_invalid_local_clock_blocks_all_and_empty_batch_never_connects(self):
        self.assertEqual(self.feed.quotes_partial([]), {"quotes": {}, "errors": {}})
        self.now = self.now.replace(tzinfo=None)
        result = self.feed.quotes_partial(["US.AAPL", "US.SPY"])
        self.assertEqual(result["quotes"], {})
        self.assertEqual(set(result["errors"]), {"US.AAPL", "US.SPY"})
        self.assertTrue(all("时区" in error for error in result["errors"].values()))
        self.assertEqual(self.sdk.calls, [])

    def test_batch_is_quote_only_and_preserves_evidence_times(self):
        rows = self.feed.quotes(["US.SPY", "US.AAPL"])
        self.assertEqual(set(rows), {"US.AAPL", "US.SPY"})
        row = rows["US.AAPL"]
        self.assertEqual((row["price"], row["bid"], row["ask"]), (100, 99.99, 100.01))
        self.assertEqual(row["asof"], "2026-09-25T15:00:00+00:00")
        self.assertEqual(row["bid_asof"], "2026-09-25T15:00:05+00:00")
        self.assertEqual(row["ask_asof"], "2026-09-25T15:00:06+00:00")
        self.assertEqual(row["received_at"], NOW.isoformat())
        self.assertEqual(row["raw_timestamps"]["bid"], "2026-09-25 11:00:05")
        self.assertEqual((row["source"], row["currency"], row["market"]), ("MOOMOO_OPEND", "USD", "US"))
        self.assertTrue(row["tradable"])
        self.assertEqual(rows["US.SPY"]["security_type"], "ETF")
        allowed = {"OpenQuoteContext", "get_stock_basicinfo", "subscribe", "get_market_state",
                   "get_market_snapshot", "get_order_book"}
        self.assertTrue(all(method in allowed for method, _ in self.sdk.calls))
        self.assertEqual(self.sdk.calls[0][1], {"host": "127.0.0.1", "port": 18441,
                                             "security_firm": "FUTUSECURITIES"})
        for method, kwargs in self.sdk.calls:
            if method in {"get_stock_basicinfo", "subscribe", "get_market_state", "get_market_snapshot"}:
                self.assertEqual(kwargs["code_list"], ["US.AAPL", "US.SPY"])
            if method == "subscribe":
                self.assertEqual(kwargs["subtype_list"], ["QUOTE", "ORDER_BOOK"])
                self.assertEqual(kwargs["session"], "RTH")
                self.assertFalse(kwargs["extended_time"])
                self.assertTrue(kwargs["is_first_push"])
                self.assertTrue(kwargs["subscribe_push"])
        self.assertEqual(sum(method == "get_order_book" for method, _ in self.sdk.calls), 2)
        self.feed.close()
        self.assertTrue(self.sdk.context.closed)

    def test_dataframe_shape_supported_without_pandas_dependency(self):
        self.sdk.dataframes = True
        self.assertTrue(self.feed.quotes(["US.AAPL"])["US.AAPL"]["tradable"])

    def test_three_ledgers_share_cached_subset_and_results_cannot_mutate_cache(self):
        original = self.feed.quotes(["US.AAPL", "US.SPY"])
        calls = len(self.sdk.calls)
        original["US.AAPL"]["bid"] = 1
        original["US.AAPL"]["raw_timestamps"]["bid"] = "fake"
        self.mono += 4.99
        self.now += timedelta(seconds=4.99)
        second = self.feed.quotes(["US.AAPL"])["US.AAPL"]
        third = self.feed.quotes(["US.SPY"])["US.SPY"]
        self.assertEqual(len(self.sdk.calls), calls)
        self.assertEqual(second["bid"], 99.99)
        self.assertEqual(second["raw_timestamps"]["bid"], "2026-09-25 11:00:05")
        self.assertEqual(third["received_at"], NOW.isoformat())
        self.mono = 105
        self.feed.quotes(["US.AAPL"])
        self.assertGreater(len(self.sdk.calls), calls)
        self.assertEqual(sum(method == "subscribe" for method, _ in self.sdk.calls), 1)

    def test_force_refresh_updates_quotes_without_exceeding_metadata_quota(self):
        codes = ["US.AAPL", "US.SPY"] + [f"US.T{index:02d}" for index in range(18)]
        for code in codes[2:]:
            self.sdk.add(code)
        # Repeated preview/submit over the same 20-code universe for 30s.
        for index in range(121):
            self.mono = 100 + index / 4
            self.now = NOW + timedelta(seconds=index / 4)
            price = 100 + index / 10
            for code in codes:
                self.sdk.snapshots[code]["last_price"] = price
                self.sdk.snapshots[code]["update_time"] = (self.now - timedelta(seconds=2)).isoformat()
                self.sdk.books[code].update({"Bid": [(price - .01, 500)],
                    "Ask": [(price + .01, 300)],
                    "svr_recv_time_bid": (self.now - timedelta(seconds=1)).isoformat(),
                    "svr_recv_time_ask": (self.now - timedelta(seconds=.5)).isoformat()})
            row = self.feed.quotes(codes, refresh=True)["US.AAPL"]
            self.assertEqual((row["price"], row["bid"], row["ask"]),
                             (price, price - .01, price + .01))
            self.assertEqual(row["asof"], (self.now - timedelta(seconds=2)).isoformat())
            self.assertEqual(row["received_at"], self.now.isoformat())
        counts = {name: sum(method == name for method, _ in self.sdk.calls)
                  for name in ("get_stock_basicinfo", "get_market_state", "get_market_snapshot", "get_order_book")}
        self.assertEqual(counts["get_market_state"], 7)
        self.assertLessEqual(counts["get_market_state"], 10)  # Official 30s quota.
        self.assertEqual(counts["get_stock_basicinfo"], 7)
        self.assertEqual(counts["get_market_snapshot"], 121)
        self.assertEqual(counts["get_order_book"], 121 * len(codes))
        # Cached metadata cannot conceal a newly suspended security or old price.
        self.sdk.snapshots["US.AAPL"]["suspension"] = True
        self.assertFalse(self.feed.quotes(["US.AAPL"], refresh=True)["US.AAPL"]["tradable"])
        self.sdk.snapshots["US.AAPL"]["suspension"] = False
        self.sdk.snapshots["US.AAPL"]["sec_status"] = "SUSPENDED"
        self.assertFalse(self.feed.quotes(["US.AAPL"], refresh=True)["US.AAPL"]["tradable"])
        self.sdk.snapshots["US.AAPL"]["sec_status"] = "NORMAL"
        self.sdk.snapshots["US.AAPL"]["update_time"] = (self.now - timedelta(seconds=31)).isoformat()
        with self.assertRaisesRegex(BrokerError, "超过 30 秒"):
            self.feed.quotes(["US.AAPL"], refresh=True)
        self.assertNotIn("US.AAPL", self.feed._cache)

    def test_metadata_expiry_and_new_codes_require_new_verified_rows(self):
        self.feed.quotes(["US.AAPL"], refresh=True)
        self.mono = 104.99
        self.feed.quotes(["US.AAPL"], refresh=True)
        self.sdk.add("US.BOND", "DRVT")
        with self.assertRaisesRegex(BrokerError, "不是股票"):
            self.feed.quotes(["US.AAPL", "US.BOND"], refresh=True)
        self.assertFalse(any(method == "subscribe" and "US.BOND" in args["code_list"]
                             for method, args in self.sdk.calls))
        self.feed.quotes(["US.AAPL", "US.SPY"], refresh=True)
        self.assertEqual([args["code_list"] for method, args in self.sdk.calls
                          if method == "get_market_state"], [["US.AAPL"], ["US.SPY"]])
        # Hitting AAPL at 4.99s or adding SPY must not renew AAPL's metadata TTL.
        self.mono = 105
        self.sdk.basic["US.AAPL"]["stock_type"] = "ETF"
        self.sdk.states["US.AAPL"]["market_state"] = "CLOSED"
        # Even a 0.01s-old price cache cannot extend older metadata past 5s.
        rows = self.feed.quotes(["US.AAPL", "US.SPY"])
        self.assertEqual(rows["US.AAPL"]["security_type"], "ETF")
        self.assertFalse(rows["US.AAPL"]["tradable"])
        self.assertTrue(rows["US.SPY"]["tradable"])
        for name in ("get_stock_basicinfo", "get_market_state"):
            self.assertEqual([args["code_list"] for method, args in self.sdk.calls if method == name][-1],
                             ["US.AAPL"])
        self.mono = 110
        self.sdk.failures["get_market_state"] = "quota exceeded"
        with self.assertRaisesRegex(BrokerError, "额度受限"):
            self.feed.quotes(["US.AAPL", "US.SPY"], refresh=True)
        self.assertEqual(self.feed._cache, {})

    def test_cached_price_age_is_checked_and_failure_has_no_cached_fallback(self):
        self.now = NOW + timedelta(seconds=14)
        self.feed.quotes(["US.AAPL"])
        self.now += timedelta(seconds=2)
        self.mono += 2
        with self.assertRaisesRegex(BrokerError, "超过 30 秒"):
            self.feed.quotes(["US.AAPL"])
        self.assertNotIn("US.AAPL", self.feed._cache)

    def test_invalid_batch_caches_no_partial_success(self):
        self.sdk.books["US.SPY"]["Ask"] = []
        with self.assertRaisesRegex(BrokerError, "Ask"):
            self.feed.quotes(["US.AAPL", "US.SPY"])
        self.assertEqual(self.feed._cache, {})

    def test_permission_error_is_actionable_redacted_and_never_substitutes_quote(self):
        self.sdk.failures["subscribe"] = "No US market quote rights for login secret123/account99"
        with self.assertRaisesRegex(BrokerError, "subscribe: 美股实时行情 / 盘口权限不足") as caught:
            self.feed.quotes(["US.AAPL"])
        self.assertNotIn("secret123", str(caught.exception))
        self.assertNotIn("account99", str(caught.exception))
        self.assertFalse(any(method == "get_order_book" for method, _ in self.sdk.calls))
        self.assertEqual(self.feed._cache, {})

    def test_timeout_and_quota_are_explicit_and_do_not_return_prior_prices(self):
        self.feed.quotes(["US.AAPL"])
        self.mono += 5
        self.sdk.exceptions.add("get_market_snapshot")
        with self.assertRaisesRegex(BrokerError, "调用异常") as caught:
            self.feed.quotes(["US.AAPL"])
        self.assertNotIn("password", str(caught.exception))
        self.sdk.exceptions.clear()
        self.sdk.failures["get_order_book"] = "subscription quota exceeded"
        with self.assertRaisesRegex(BrokerError, "额度受限"):
            self.feed.quotes(["US.AAPL"])

    def test_bad_connection_and_codes_rejected_before_network(self):
        for kwargs in ({"host": "remote.example"}, {"host": "8.8.8.8"}, {"port": True},
                       {"port": 0}, {"security_firm": "bad name"}, {"now": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(BrokerError):
                MoomooQuoteFeed(**kwargs)
        for codes in ("US.AAPL", ["HK.00700"], ["US.aapl"], [True], ["US.AAPL"] * 101):
            with self.subTest(codes=codes), self.assertRaises(BrokerError):
                self.feed.quotes(codes)
        self.assertEqual(self.sdk.calls, [])

    def test_nonstock_rejected_before_subscription_and_currency_conflicts_rejected(self):
        self.sdk.basic["US.AAPL"]["stock_type"] = "DRVT"
        with self.assertRaisesRegex(BrokerError, "不是股票"):
            self.feed.quotes(["US.AAPL"])
        self.assertFalse(any(method == "subscribe" for method, _ in self.sdk.calls))
        self.mono += 5
        self.sdk.basic["US.AAPL"]["stock_type"] = "STOCK"
        self.sdk.snapshots["US.AAPL"]["currency"] = "HKD"
        with self.assertRaisesRegex(BrokerError, "不是美元"):
            self.feed.quotes(["US.AAPL"])

    def test_security_and_session_states_are_verified(self):
        original = deepcopy(self.sdk.snapshots["US.AAPL"])
        for field, value in (("suspension", True), ("sec_status", "SUSPENDED")):
            self.feed._cache.clear()
            self.sdk.snapshots["US.AAPL"] = {**original, field: value}
            self.assertFalse(self.feed.quotes(["US.AAPL"])["US.AAPL"]["tradable"])
        self.sdk.snapshots["US.AAPL"] = original
        for state in ("CLOSED", "PRE_MARKET_BEGIN", "AFTER_HOURS_BEGIN", "OVERNIGHT", "NONE"):
            self.mono += 5
            self.feed._cache.clear()
            self.sdk.states["US.AAPL"]["market_state"] = state
            self.assertFalse(self.feed.quotes(["US.AAPL"])["US.AAPL"]["tradable"])
        self.feed._cache.clear()
        self.mono += 5
        self.sdk.states["US.AAPL"]["market_state"] = "N/A"
        with self.assertRaisesRegex(BrokerError, "时段状态"):
            self.feed.quotes(["US.AAPL"])

    def test_missing_or_unknown_status_is_not_assumed_normal(self):
        for data, field, value in ((self.sdk.basic, "delisting", None),
                (self.sdk.snapshots, "suspension", "False"),
                (self.sdk.snapshots, "sec_status", "UNKNOWN")):
            self.mono += 5
            prior = data["US.AAPL"].get(field)
            data["US.AAPL"][field] = value
            with self.subTest(field=field), self.assertRaises(BrokerError):
                self.feed.quotes(["US.AAPL"])
            data["US.AAPL"][field] = prior

    def test_optional_basic_suspension_does_not_replace_authoritative_snapshot(self):
        for optional in (None, "N/A", float("nan")):
            self.mono += 5
            self.feed._cache.clear()
            self.sdk.basic["US.AAPL"]["suspension"] = optional
            with self.subTest(optional=optional):
                self.assertTrue(self.feed.quotes(["US.AAPL"])["US.AAPL"]["tradable"])
            self.feed._cache.clear()
            self.sdk.snapshots["US.AAPL"]["suspension"] = None
            with self.assertRaisesRegex(BrokerError, "停牌状态"):
                self.feed.quotes(["US.AAPL"])
            self.sdk.snapshots["US.AAPL"]["suspension"] = False
        self.mono += 5
        self.sdk.basic["US.AAPL"]["suspension"] = True
        self.assertFalse(self.feed.quotes(["US.AAPL"])["US.AAPL"]["tradable"])

    def test_real_clock_and_cache_boundary_prevent_off_session_fills(self):
        self.now = datetime(2026, 9, 25, 19, 59, 59, tzinfo=timezone.utc)
        self.sdk.snapshots["US.AAPL"]["update_time"] = "2026-09-25 15:59:58"
        for field in ("svr_recv_time_bid", "svr_recv_time_ask"):
            self.sdk.books["US.AAPL"][field] = "2026-09-25 15:59:58"
        self.assertTrue(self.feed.quotes(["US.AAPL"])["US.AAPL"]["tradable"])
        calls = len(self.sdk.calls)
        self.now += timedelta(seconds=1)
        self.mono += 1
        closing = self.feed.quotes(["US.AAPL"])["US.AAPL"]
        self.assertFalse(closing["tradable"])
        self.assertEqual(closing["session"], "OUTSIDE_RTH")
        self.assertEqual(len(self.sdk.calls), calls)

    def test_winter_eastern_timestamp_uses_correct_utc_offset(self):
        self.now = datetime(2026, 1, 5, 15, 0, 15, tzinfo=timezone.utc)
        self.sdk.snapshots["US.AAPL"]["update_time"] = "2026-01-05 10:00:00"
        for field in ("svr_recv_time_bid", "svr_recv_time_ask"):
            self.sdk.books["US.AAPL"][field] = "2026-01-05 10:00:00"
        self.assertEqual(self.feed.quotes(["US.AAPL"])["US.AAPL"]["asof"],
                         "2026-01-05T15:00:00+00:00")

    def test_missing_stale_future_times_are_not_replaced_with_receipt_time(self):
        for attr, field in (("snapshots", "update_time"), ("books", "svr_recv_time_bid"),
                            ("books", "svr_recv_time_ask")):
            data = getattr(self.sdk, attr)["US.AAPL"]
            prior = data[field]
            for value in (None, "", "0", "2026-09-25 10:59:00", "2026-09-25 11:00:16"):
                data[field] = value
                with self.subTest(attr=attr, field=field, value=value), self.assertRaises(BrokerError):
                    self.feed.quotes(["US.AAPL"])
            data[field] = prior

    def test_invalid_source_time_identifies_security_and_clock_without_echoing_value(self):
        private_value = "private-invalid-time-payload"
        codes = ["US.AAPL", "US.SPY"]
        for code in codes:
            for attr, field, clock_field in (("snapshots", "update_time", "last_price"),
                                              ("books", "svr_recv_time_bid", "bid"),
                                              ("books", "svr_recv_time_ask", "ask")):
                data = getattr(self.sdk, attr)[code]
                prior = data[field]
                for invalid in (private_value, None):
                    with self.subTest(code=code, clock=clock_field, missing=invalid is None):
                        self.feed.quotes(codes, refresh=True)
                        data[field] = invalid
                        with self.assertRaises(BrokerError) as caught:
                            self.feed.quotes(codes, refresh=True)
                        message = str(caught.exception)
                        self.assertIn(f"{code} {clock_field}: ", message)
                        self.assertIn("行情原始更新时间", message)
                        self.assertNotIn(private_value, message)
                        self.assertTrue(caught.exception.__suppress_context__)
                        self.assertEqual(self.feed._cache, {})
                        data[field] = prior

    def test_nonpositive_nan_bool_prices_ticks_lots_and_book_depth_are_rejected(self):
        row = self.sdk.snapshots["US.AAPL"]
        for field in ("last_price", "price_spread", "lot_size"):
            prior = row[field]
            for value in (0, -1, None, True, float("nan"), float("inf")):
                row[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(BrokerError):
                    self.feed.quotes(["US.AAPL"])
            row[field] = prior
        book = self.sdk.books["US.AAPL"]
        for side, values in (("Bid", []), ("Ask", [(100, 0)]), ("Ask", [(float("nan"), 10)]),
                             ("Bid", [(101, 10)]), ("Bid", [100])):
            prior = book[side]
            book[side] = values
            with self.subTest(side=side, values=values), self.assertRaises(BrokerError):
                self.feed.quotes(["US.AAPL"])
            book[side] = prior

    def test_mismatched_security_lot_and_book_type_rejected(self):
        for attr, field, value in (("books", "code", "US.SPY"), ("basic", "lot_size", 100),
                                  ("books", "order_book_type", "ODD_LOT")):
            self.mono += 5
            data = getattr(self.sdk, attr)["US.AAPL"]
            prior = data[field]
            data[field] = value
            with self.subTest(field=field), self.assertRaises(BrokerError):
                self.feed.quotes(["US.AAPL"])
            data[field] = prior

    def test_missing_sdk_and_unsupported_firm_do_not_open_context(self):
        with patch("moomoo_component.quotes.importlib.import_module", side_effect=ImportError):
            with self.assertRaisesRegex(BrokerError, "尚未安装"):
                MoomooQuoteFeed().quotes(["US.AAPL"])
        with self.assertRaisesRegex(BrokerError, "SecurityFirm"):
            MoomooQuoteFeed(security_firm="NOT_SUPPORTED", sdk=self.sdk).quotes(["US.AAPL"])
        self.assertEqual(self.sdk.calls, [])

    def test_naive_local_validation_clock_is_rejected(self):
        self.now = NOW.replace(tzinfo=None)
        with self.assertRaisesRegex(BrokerError, "明确时区"):
            self.feed.quotes(["US.AAPL"])
        self.assertEqual(self.sdk.calls, [])


if __name__ == "__main__":
    unittest.main()
