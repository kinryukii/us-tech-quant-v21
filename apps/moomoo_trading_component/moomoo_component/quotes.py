"""Quote-only OpenD feed for local paper ledgers; never creates a trade context.

Snapshot and market-state requests are batched. The SDK order-book API accepts
one security at a time, so subscriptions and the five-second cache are shared.
Reference: https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-order-book.html
Metadata quota: https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-market-state.html
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timezone
import importlib
import ipaddress
import re
import threading
import time as clock
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .brokers import BrokerError, MoomooBroker, _code, _false, _name, _number, _quantity


_US_MARKET_STATES = frozenset({
    "NONE", "AFTERNOON", "CLOSED", "WAITING_OPEN", "PRE_MARKET_BEGIN",
    "PRE_MARKET_END", "AFTER_HOURS_BEGIN", "AFTER_HOURS_END", "NIGHT_OPEN",
    "NIGHT_END", "OVERNIGHT",
})
_CACHE_SECONDS = 5.0
_MAX_SOURCE_AGE_SECONDS = 30.0


class MoomooQuoteFeed:
    """Lazy, loopback-only US stock/ETF quotes, with no account operations.

    ``asof`` is the oldest source timestamp among the last trade and both book
    sides. ``received_at`` records our retrieval time and never makes data fresh.
    A valid off-session or suspended quote is returned with ``tradable=False``;
    absent, stale, future, crossed or otherwise invalid data raises BrokerError.
    Share one feed across the three paper accounts to share its cache.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 18441,
                 security_firm: str = "FUTUSECURITIES", *, sdk: Any = None,
                 now: Any = None, monotonic: Any = None):
        host = "127.0.0.1" if host == "localhost" else host
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except (TypeError, ValueError):
            loopback = False
        if not loopback:
            raise BrokerError("OpenD 行情只允许连接本机回环地址")
        if type(port) is not int or not 1 <= port <= 65535:
            raise BrokerError("OpenD 端口无效")
        if not isinstance(security_firm, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,40}", security_firm):
            raise BrokerError("券商区域参数无效")
        if any(value is not None and not callable(value) for value in (now, monotonic)):
            raise BrokerError("行情时钟必须是可调用函数")
        self.host, self.port, self.security_firm = host, port, security_firm
        self._sdk, self._quote = sdk, None
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or clock.monotonic
        self._lock = threading.RLock()
        self._subscribed: set[str] = set()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._basic_cache: dict[str, tuple[float, dict]] = {}
        self._state_cache: dict[str, tuple[float, dict]] = {}
        self._closed = False

    def _load(self):
        if self._sdk is None:
            try:
                self._sdk = importlib.import_module("moomoo")
            except ImportError:
                raise BrokerError("尚未安装 Moomoo SDK，请安装项目的 moomoo 可选依赖") from None
        return self._sdk

    def _enum(self, group: str, member: str):
        value = getattr(getattr(self._load(), group, None), member, None)
        if value is None:
            raise BrokerError(f"Moomoo SDK 不支持 {group}.{member}，请检查版本和券商区域")
        return value

    def _context(self):
        if self._quote is None:
            firm = self._enum("SecurityFirm", self.security_firm)
            try:
                self._quote = self._load().OpenQuoteContext(
                    host=self.host, port=self.port, security_firm=firm)
            except Exception:
                raise BrokerError("无法连接本机 OpenD 行情接口，请检查端口、登录和 SDK 版本") from None
        return self._quote

    def _call(self, method, **kwargs):
        label = getattr(method, "__name__", "OpenD 行情")
        try:
            ret, data = method(**kwargs)
        except Exception:
            raise BrokerError(f"{label} 行情调用异常；本轮没有可用报价") from None
        if ret != self._load().RET_OK:
            # Do not echo unredacted SDK payloads or login identifiers. Preserve
            # actionable quote-only failure categories rather than fabricated data.
            detail = str(data).lower()
            if any(term in detail for term in ("权限", "permission", "right", "无权", "entitlement")):
                reason = "美股实时行情 / 盘口权限不足，请检查 OpenD 行情授权"
            elif any(term in detail for term in ("quota", "limit", "频率", "额度", "上限")):
                reason = "行情请求频率或订阅额度受限"
            elif any(term in detail for term in ("login", "登录", "connect", "连接")):
                reason = "行情服务器未登录或连接不可用"
            else:
                reason = "行情请求失败，请检查 OpenD 行情日志和证券支持范围"
            raise BrokerError(f"{label}: {reason}；本轮没有可用报价")
        return data

    def _rows(self, method, **kwargs) -> list[dict]:
        data = self._call(method, **kwargs)
        if hasattr(data, "to_dict"):
            data = data.to_dict("records")
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise BrokerError("OpenD 行情返回数据格式无效")
        return data

    def _metadata_rows(self, method, requested: set[str], cache: dict,
                       label: str, **kwargs) -> dict[str, dict]:
        # get_market_state permits 10 calls / 30 seconds. Stable execution
        # batches share metadata for <5s, even when prices are force-refreshed.
        # Hits never renew this clock; it is not a price/source timestamp.
        mono = self._monotonic()
        result, missing = {}, set()
        for code in requested:
            item = cache.get(code)
            if item is not None and 0 <= mono - item[0] < _CACHE_SECONDS:
                result[code] = deepcopy(item[1])
            else:
                cache.pop(code, None)
                missing.add(code)
        if missing:
            fresh = MoomooBroker._by_code(self._rows(method,
                code_list=sorted(missing), **kwargs), missing, label)
            for code, row in fresh.items():
                cache[code] = (mono, deepcopy(row))
            result.update(fresh)
        return result

    def _ensure_subscribed(self, quote, requested: set[str], *, basic=None) -> dict[str, dict]:
        if basic is None:
            basic = self._metadata_rows(quote.get_stock_basicinfo, requested,
                self._basic_cache, "证券类型", market=self._enum("Market", "US"))
        if any(_name(row.get("stock_type")) not in {"STOCK", "ETF"} for row in basic.values()):
            raise BrokerError("目标证券不是股票或 ETF；拒绝订阅该批行情")
        missing = requested - self._subscribed
        if missing:
            self._call(quote.subscribe, code_list=sorted(missing),
                subtype_list=[self._enum("SubType", "QUOTE"), self._enum("SubType", "ORDER_BOOK")],
                is_first_push=True, subscribe_push=True, extended_time=False,
                session=self._enum("Session", "RTH"))
            self._subscribed.update(missing)
        return basic

    def prewarm(self, codes: list[str]) -> None:
        """Subscribe eligible securities early; this returns no price/readiness evidence."""
        with self._lock:
            if self._closed:
                raise BrokerError("OpenD 行情连接已关闭")
            if not isinstance(codes, (list, tuple)) or len(codes) > 100:
                raise BrokerError("每次最多读取 100 个美股股票 / ETF 证券")
            requested = {_code(code) for code in codes}
            if requested:
                self._ensure_subscribed(self._context(), requested)

    def _utc_now(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise BrokerError("行情校验时钟必须含明确时区")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _regular_clock(now: datetime) -> bool:
        try:
            eastern = now.astimezone(ZoneInfo("America/New_York"))
        except ZoneInfoNotFoundError:
            raise BrokerError("缺少纽约时区数据，请安装 tzdata；禁止猜测交易时段") from None
        return eastern.weekday() < 5 and time(9, 30) <= eastern.time() < time(16)

    @staticmethod
    def _source_time(value: Any, now: datetime, field: str) -> str:
        # SDK US timestamps are Eastern time; use the existing DST-aware helper.
        try:
            stamp = MoomooBroker._quote_time(value)
        except BrokerError as exc:
            raise BrokerError(f"{field}: {exc}") from None
        age = (now - datetime.fromisoformat(stamp)).total_seconds()
        if not 0 <= age <= _MAX_SOURCE_AGE_SECONDS:
            raise BrokerError(f"{field} 行情时间在未来或已超过 30 秒；拒绝旧报价")
        return stamp

    @staticmethod
    def _book_side(book: dict, side: str) -> tuple[float, float]:
        levels = book.get(side)
        if not isinstance(levels, (list, tuple)) or not levels:
            raise BrokerError(f"实时盘口缺少 {side} 档位")
        first = levels[0]
        if not isinstance(first, (list, tuple)) or len(first) < 2:
            raise BrokerError(f"实时盘口 {side} 档位格式无效")
        return (_number(first[0], f"盘口 {side} 价格", positive=True),
                _number(first[1], f"盘口 {side} 数量", positive=True))

    def _validated_quote(self, code: str, info: dict, snapshot: dict,
                         state: dict, book: dict, now: datetime) -> dict:
        stock_type = _name(info.get("stock_type"))
        if stock_type not in {"STOCK", "ETF"}:
            raise BrokerError(f"{code} 不是股票或 ETF；拒绝该行情")
        for row in (info, snapshot, state, book):
            if "currency" in row and _name(row["currency"]) != "USD":
                raise BrokerError(f"{code} 行情不是美元计价")
        if not isinstance(book, dict) or book.get("code") != code:
            raise BrokerError("实时盘口证券不匹配")
        if "order_book_type" in book and _name(book["order_book_type"]) != "NORMAL":
            raise BrokerError("仅支持美股整股普通盘口")
        market_state = _name(state.get("market_state"))
        if market_state not in _US_MARKET_STATES:
            raise BrokerError(f"{code} 美股交易时段状态缺失或无效")
        sec_status = _name(snapshot.get("sec_status"))
        self._enum("SecurityStatus", sec_status)
        active = _false(info.get("delisting"), "退市状态")
        active = _false(snapshot.get("suspension"), "停牌状态") and active
        # SDK basicinfo may expose suspension as N/A/NaN for US securities.
        # The required snapshot boolean + sec_status are the current authority.
        # An explicitly known static suspension still conservatively blocks.
        static_suspension = info.get("suspension")
        if isinstance(static_suspension, bool) or type(static_suspension).__name__ == "bool_":
            active = _false(static_suspension, "证券基本信息停牌状态") and active
        active = active and sec_status == "NORMAL"
        lot_size = _quantity(snapshot.get("lot_size"), "每手股数", positive=True)
        if "lot_size" in info and _quantity(info["lot_size"], "证券基本信息每手股数", positive=True) != lot_size:
            raise BrokerError(f"{code} 每手股数来源不一致")
        price = _number(snapshot.get("last_price"), "最新价", positive=True)
        tick = _number(snapshot.get("price_spread"), "最小价格单位", positive=True)
        bid, bid_size = self._book_side(book, "Bid")
        ask, ask_size = self._book_side(book, "Ask")
        if bid > ask:
            raise BrokerError(f"{code} 实时盘口买卖价倒挂")
        # Preserve all evidence clocks. The minimum prevents a fresh book side
        # or a local cache read from concealing a stale last trade/other side.
        raw_times = {"last_price": snapshot.get("update_time"),
                     "bid": book.get("svr_recv_time_bid"),
                     "ask": book.get("svr_recv_time_ask")}
        times = {key: self._source_time(value, now, f"{code} {key}")
                 for key, value in raw_times.items()}
        asof = min(times.values(), key=datetime.fromisoformat)
        regular = market_state == "AFTERNOON" and self._regular_clock(now)
        return {"price": price, "bid": bid, "ask": ask, "asof": asof,
                "lot_size": lot_size, "price_tick": tick,
                "tradable": active and regular,
                "currency": "USD", "market": "US", "security_type": stock_type,
                "currency_basis": "US_STOCK_ETF_PRICE_USD", "market_state": market_state,
                "sec_status": sec_status, "session": "RTH" if regular else "OUTSIDE_RTH",
                "requested_session": "RTH", "source": "MOOMOO_OPEND",
                "bid_size": bid_size, "ask_size": ask_size,
                "last_price_asof": times["last_price"], "bid_asof": times["bid"],
                "ask_asof": times["ask"], "raw_timestamps": raw_times,
                "received_at": now.isoformat()}

    def quotes(self, codes: list[str], *, refresh: bool = False) -> dict[str, dict]:
        """Return a validated batch; refresh bypasses prices, not <5s metadata."""
        with self._lock:
            if self._closed:
                raise BrokerError("OpenD 行情连接已关闭")
            if not isinstance(codes, (list, tuple)) or len(codes) > 100:
                raise BrokerError("每次最多读取 100 个美股股票 / ETF 证券")
            requested = {_code(code) for code in codes}
            if not requested:
                return {}
            now, mono = self._utc_now(), self._monotonic()
            cached = {code: self._cache.get(code) for code in requested}
            metadata = [cache.get(code) for cache in (self._basic_cache, self._state_cache)
                        for code in requested]
            if not refresh and all(item is not None and 0 <= mono - item[0] < _CACHE_SECONDS
                   and 0 <= (now - datetime.fromisoformat(item[1]["asof"])).total_seconds() <= _MAX_SOURCE_AGE_SECONDS
                   for item in cached.values()) and all(
                   item is not None and 0 <= mono - item[0] < _CACHE_SECONDS for item in metadata):
                result = {code: deepcopy(item[1]) for code, item in cached.items()}
                # Crossing 16:00 or the weekend during a cache hit must block fills.
                if not self._regular_clock(now):
                    for row in result.values():
                        row["tradable"] = False
                        row["session"] = "OUTSIDE_RTH"
                return result
            # Invalidate the whole requested batch before any SDK call. Failures
            # cannot leave a partially refreshed or previous success as a fallback.
            for code in requested:
                self._cache.pop(code, None)
            quote, code_list = self._context(), sorted(requested)
            by_code = MoomooBroker._by_code
            basic = self._ensure_subscribed(quote, requested)
            states = self._metadata_rows(quote.get_market_state, requested,
                self._state_cache, "市场状态")
            snapshots = by_code(self._rows(quote.get_market_snapshot, code_list=code_list), requested, "行情快照")
            books = {code: self._call(quote.get_order_book, code=code, num=1) for code in code_list}
            if not all(isinstance(book, dict) for book in books.values()):
                raise BrokerError("实时盘口返回数据格式无效")
            now = self._utc_now()  # Validate age after the entire batch has arrived.
            result = {code: self._validated_quote(code, basic[code], snapshots[code],
                                                states[code], books[code], now) for code in code_list}
            finished = self._monotonic()
            for code, row in result.items():
                self._cache[code] = (finished, deepcopy(row))
            return result

    def quotes_partial(self, codes: list[str], *, refresh: bool = False) -> dict:
        """Return validated tradable rows and per-code errors, never old-price fallbacks.

        Bulk response failures block every requested code. Individual book or
        source validation failures block only that code. Execution risk limits
        remain the account engine's responsibility.
        """
        with self._lock:
            if self._closed:
                raise BrokerError("OpenD 行情连接已关闭")
            if not isinstance(codes, (list, tuple)) or len(codes) > 100:
                raise BrokerError("每次最多读取 100 个美股股票 / ETF 证券")
            requested = {_code(code) for code in codes}
            if not requested:
                return {"quotes": {}, "errors": {}}
            code_list = sorted(requested)
            try:
                now, mono = self._utc_now(), self._monotonic()
                cached = {code: self._cache.get(code) for code in requested}
                metadata = [cache.get(code) for cache in (self._basic_cache, self._state_cache)
                            for code in requested]
                if not refresh and self._regular_clock(now) and all(
                        item is not None and 0 <= mono - item[0] < _CACHE_SECONDS
                        and item[1].get("tradable") is True for item in cached.values()) and all(
                        item is not None and 0 <= mono - item[0] < _CACHE_SECONDS for item in metadata):
                    try:
                        for code, item in cached.items():
                            for field in ("last_price", "bid", "ask"):
                                self._source_time(item[1].get(field + "_asof"), now, f"{code} {field}")
                    except BrokerError:
                        pass  # A stale cache triggers a real read, never a stale-price return.
                    else:
                        return {"quotes": {code: deepcopy(cached[code][1]) for code in code_list}, "errors": {}}
                for code in requested:
                    self._cache.pop(code, None)
                quote = self._context()
                basic = self._metadata_rows(quote.get_stock_basicinfo, requested,
                    self._basic_cache, "证券类型", market=self._enum("Market", "US"))
                eligible = {code for code, row in basic.items()
                            if _name(row.get("stock_type")) in {"STOCK", "ETF"}}
                errors = {code: "目标证券不是股票或 ETF；拒绝该行情"
                          for code in requested - eligible}
                if not eligible:
                    return {"quotes": {}, "errors": errors}
                self._ensure_subscribed(quote, eligible, basic={code: basic[code] for code in eligible})
                states = self._metadata_rows(quote.get_market_state, eligible,
                    self._state_cache, "市场状态")
                snapshots = MoomooBroker._by_code(self._rows(quote.get_market_snapshot,
                    code_list=sorted(eligible)), eligible, "行情快照")
                books = {}
                for code in sorted(eligible):
                    try:
                        book = self._call(quote.get_order_book, code=code, num=1)
                        if not isinstance(book, dict):
                            raise BrokerError("实时盘口返回数据格式无效")
                        books[code] = book
                    except BrokerError as exc:
                        errors[code] = str(exc)
                now = self._utc_now()  # All source clocks are checked after the batch arrives.
            except BrokerError as exc:
                for code in requested:
                    self._cache.pop(code, None)
                return {"quotes": {}, "errors": {code: str(exc) for code in code_list}}
            result = {}
            for code in sorted(eligible):
                if code in errors:
                    continue
                try:
                    row = self._validated_quote(code, basic[code], snapshots[code], states[code], books[code], now)
                    if row["tradable"] is not True:
                        raise BrokerError("证券当前不可交易；拒绝非正常美股常规时段行情")
                    result[code] = row
                except BrokerError as exc:
                    errors[code] = str(exc)
            finished = self._monotonic()
            for code, row in result.items():
                self._cache[code] = (finished, deepcopy(row))
            return {"quotes": result, "errors": errors}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cache.clear()
            self._basic_cache.clear()
            self._state_cache.clear()
            self._subscribed.clear()
            quote, self._quote = self._quote, None
            if quote is not None:
                quote.close()
