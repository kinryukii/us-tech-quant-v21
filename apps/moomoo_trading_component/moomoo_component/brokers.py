"""Moomoo OpenD adapter with an intentionally simulation-only execution boundary.

Official API reference: https://openapi.moomoo.com/moomoo-api-doc/en/
No SDK import, network connection, account selection or order occurs on import.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections import deque
from decimal import Decimal
import importlib
import ipaddress
import math
import re
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class BrokerError(RuntimeError):
    """The broker response cannot be safely used; execution must stop."""


class BrokerReadError(BrokerError):
    """A pre-write read/guard failed; no broker mutation was attempted."""

    retry_after_seconds = 30


class BrokerOrderNotSent(BrokerError):
    """Preflight failed before place_order; the client ID was not attempted."""

    retry_after_seconds = 0


_READ_ONLY_QUERY_LABELS = frozenset({
    "get_acc_list", "accinfo_query", "position_list_query",
    "order_list_query", "history_order_list_query", "acctradinginfo_query",
})
_RATE_LIMIT_KEYWORDS = (
    "too frequent", "too many requests", "rate limit", "frequency limit",
    "frequency restriction", "frequency too high", "限频", "调用频率",
    "请求频率", "调用太频繁", "请求太频繁", "查询太频繁", "请求过于频繁",
)


TERMINAL_STATUSES = frozenset({
    "FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED",
})
KNOWN_STATUSES = TERMINAL_STATUSES | frozenset({
    "UNSUBMITTED", "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED", "FILLED_PART",
    "CANCELLING_PART", "CANCELLING_ALL", "CANCELLED_PART", "UNKNOWN",
})


def _name(value: Any) -> str:
    return str(value).rsplit(".", 1)[-1]


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        raise BrokerError(f"{field} 必须是有效数字")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise BrokerError(f"{field} 缺失或无效，已停止交易") from None
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise BrokerError(f"{field} 必须为有限{'正' if positive else '非负'}数")
    return result


def _quantity(value: Any, field: str, *, positive: bool = False) -> int:
    result = _number(value, field, positive=positive)
    if not result.is_integer():
        raise BrokerError(f"{field} 必须是整数，本版本不支持碎股")
    return int(result)


def _code(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"US\.[A-Z][A-Z0-9.\-]{0,14}", value):
        raise BrokerError("仅支持 US. 开头的美股股票 / ETF 代码")
    return value


def _false(value: Any, field: str) -> bool:
    # pandas bool scalars are accepted, strings such as 'False' are not.
    if not (isinstance(value, bool) or type(value).__name__ == "bool_"):
        raise BrokerError(f"{field} 缺失或无法确认")
    return not bool(value)


def _order_id(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    result = str(value).strip()
    return "" if result in {"", "None", "nan", "N/A", "0"} else result


class MoomooBroker:
    def __init__(self, host: str = "127.0.0.1", port: int = 18441,
                 security_firm: str = "FUTUSECURITIES", account_id: str | None = None,
                 *, sdk: Any = None, now: Any = None, cancel_check: Any = None,
                 monotonic: Any = None):
        if host == "localhost":
            host = "127.0.0.1"
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise BrokerError("OpenD 只允许连接本机回环地址")
        if type(port) is not int or not 1 <= port <= 65535:
            raise BrokerError("OpenD 端口无效")
        if not isinstance(security_firm, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,40}", security_firm):
            raise BrokerError("券商区域参数无效")
        if account_id is not None and (isinstance(account_id, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(account_id))):
            raise BrokerError("必须明确选择非零模拟账户 ID")
        self.host, self.port = host, port
        self.security_firm = security_firm
        self.account_id = str(account_id) if account_id is not None else None
        self._sdk = sdk
        self._trade = None
        self._quote = None
        self._quote_feed = None
        self._now = now or (lambda: datetime.now(timezone.utc))
        if cancel_check is not None and not callable(cancel_check):
            raise BrokerError("停止状态检查必须是可调用函数")
        self.cancel_check = cancel_check if cancel_check is not None else (lambda: False)
        self._lock = threading.RLock()
        self._attempted: set[str] = set()
        self._monotonic = monotonic or time.monotonic
        self._funds_reads = deque()
        # Reserve one call below OpenD's 10/30s allowance for another client.
        # Current-order reads are shared by snapshots, reconcile and repricing.
        self._order_reads = {"order_list_query": deque(),
                              "history_order_list_query": deque()}
        self._market_cash_reads = deque()
        self._reprice_attempted: set[tuple[str, int, str]] = set()
        self._limit_read_queries = False

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

    def _trade_context(self):
        if self._trade is None:
            sdk = self._load()
            firm = self._enum("SecurityFirm", self.security_firm)
            try:
                self._trade = sdk.OpenSecTradeContext(
                    filter_trdmarket=self._enum("TrdMarket", "US"),
                    host=self.host, port=self.port, security_firm=firm)
            except Exception:
                raise BrokerError("无法连接本机 OpenD 交易查询接口，请检查端口、登录和 SDK 版本") from None
        return self._trade

    def _quote_context(self):
        if self._quote is None:
            try:
                self._quote = self._load().OpenQuoteContext(host=self.host, port=self.port)
            except Exception:
                raise BrokerError("无法连接本机 OpenD 行情接口") from None
        return self._quote

    def _call(self, method, **kwargs) -> list[dict]:
        label = getattr(method, "__name__", "OpenD")
        error_type = BrokerReadError if label in _READ_ONLY_QUERY_LABELS else BrokerError
        if label in self._order_reads and (label != "order_list_query" or kwargs.get("refresh_cache") is True):
            clock = self._monotonic()
            recent = self._order_reads[label]
            while recent and clock - recent[0] >= 30:
                recent.popleft()
            if len(recent) >= 9:
                raise BrokerReadError(f"{label} 已达到本地每30秒9次配额；30秒后重新查询")
            recent.append(clock)  # Failed calls still consume the server allowance.
        if label == "accinfo_query" and kwargs.get("refresh_cache") is True:
            clock = self._monotonic()
            while self._funds_reads and clock - self._funds_reads[0] >= 30:
                self._funds_reads.popleft()
            if self._limit_read_queries and len(self._funds_reads) >= 10:
                raise BrokerReadError("资金读取已达到本地每30秒10次配额；30秒后重新查询")
            # Failed calls count too. No cached funds are substituted for this read.
            self._funds_reads.append(clock)
        if label == "acctradinginfo_query":
            clock = self._monotonic()
            while self._market_cash_reads and clock - self._market_cash_reads[0] >= 30:
                self._market_cash_reads.popleft()
            # The server allows 10/30s per account; reserve one call for another client.
            if len(self._market_cash_reads) >= 9:
                raise BrokerReadError("市价单现金可买查询已达到本地每30秒9次配额；30秒后重新查询")
            self._market_cash_reads.append(clock)
        try:
            ret, data = method(**kwargs)
        except Exception:
            # SDK exceptions may contain account identifiers or unredacted payloads.
            message = (f"{label} 只读查询调用异常；30 秒后重新查询"
                       if error_type is BrokerReadError else
                       f"{label} 调用异常；提交订单时请按未知状态对账，不可重试")
            raise error_type(message) from None
        if ret != self._load().RET_OK:
            message = (f"{label} 只读查询未成功；30 秒后重新查询"
                       if error_type is BrokerReadError else
                       f"{label} 请求未成功，请检查 OpenD 日志；禁止自动重试")
            if error_type is BrokerReadError:
                # Inspect solely to select a fixed classification. Never expose SDK
                # payloads, which can include full account identifiers or secrets.
                try:
                    rate_limited = any(word in str(data).casefold()
                                       for word in _RATE_LIMIT_KEYWORDS)
                except Exception:
                    rate_limited = False
                if rate_limited:
                    message = f"{label} 只读查询限频；请等待 30 秒后重新查询"
            raise error_type(message) from None
        if hasattr(data, "to_dict"):
            data = data.to_dict("records")
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise BrokerError(f"{label} 返回数据格式无效")
        return data

    @staticmethod
    def _eligible(row: dict) -> bool:
        markets = row.get("trdmarket_auth")
        return (
            _name(row.get("trd_env")) == "SIMULATE"
            and _name(row.get("sim_acc_type")) in {"STOCK", "STOCK_AND_OPTION"}
            and _name(row.get("acc_status")) == "ACTIVE"
            and isinstance(markets, (list, tuple))
            and "US" in {_name(item) for item in markets}
            and re.fullmatch(r"[1-9][0-9]{0,19}", str(row.get("acc_id", ""))) is not None
        )

    def probe(self) -> dict:
        """Read account metadata only; never return live IDs or live balances."""
        with self._lock:
            rows = self._call(self._trade_context().get_acc_list)
            accounts = [{"account_id": str(row["acc_id"]), "market": "US", "environment": "SIMULATE"}
                        for row in rows if self._eligible(row)]
            return {"connected": True, "host": self.host, "port": self.port,
                    "sdk_version": str(getattr(self._load(), "__version__", "unknown")),
                    "security_firm": self.security_firm, "accounts": accounts,
                    "live_enabled": False}

    def _validate_account(self) -> dict:
        if self.account_id is None:
            raise BrokerError("尚未明确选择 Moomoo 美股模拟账户")
        rows = self._call(self._trade_context().get_acc_list)
        selected = [row for row in rows if str(row.get("acc_id")) == self.account_id]
        if len(selected) != 1 or not self._eligible(selected[0]):
            raise BrokerError("选定账户不是有效的美股股票模拟账户，已阻止操作")
        return selected[0]

    def _account_args(self) -> dict:
        return {"trd_env": self._enum("TrdEnv", "SIMULATE"), "acc_id": int(self.account_id)}

    @staticmethod
    def _by_code(rows: list[dict], expected: set[str], label: str) -> dict:
        result = {}
        for row in rows:
            code = row.get("code")
            if code not in expected or code in result:
                raise BrokerError(f"{label} 含重复或意外的证券")
            result[code] = row
        if set(result) != expected:
            raise BrokerError(f"{label} 缺少证券数据，已停止交易")
        return result

    @staticmethod
    def _quote_time(value: Any) -> str:
        if not isinstance(value, str):
            raise BrokerError("行情原始更新时间缺失")
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
        except ZoneInfoNotFoundError:
            raise BrokerError("缺少纽约时区数据，请安装 tzdata；禁止猜测行情时间") from None
        except ValueError:
            raise BrokerError("行情原始更新时间无效") from None
        return parsed.astimezone(timezone.utc).isoformat()

    def _feed(self):
        if self._quote_feed is None:
            # Import lazily: quotes.py reuses the existing field validators.
            # This context is quote-only, never an account/trade context.
            from .quotes import MoomooQuoteFeed
            self._quote_feed = MoomooQuoteFeed(
                host=self.host, port=self.port, security_firm=self.security_firm,
                sdk=self._load(), now=self._now)
        return self._quote_feed

    def prewarm(self, codes: list[str]) -> None:
        """Subscribe to quote updates only; never read funds or submit orders."""
        with self._lock:
            if not isinstance(codes, list) or len(codes) > 100:
                raise BrokerError("每次最多预热100个目标证券")
            requested = {_code(code) for code in codes}
            if requested:
                self._feed().prewarm(sorted(requested))

    def _read_quotes(self, codes: set[str]) -> dict:
        if not codes:
            return {}
        # The feed preserves source clocks and always refreshes prices/books here.
        return self._feed().quotes(sorted(codes), refresh=True)

    def snapshot_partial(self, codes: list[str]) -> dict:
        """Fresh account state with independently qualified quote results."""
        return self._snapshot_read(codes, allow_partial_quotes=True)

    def snapshot(self, codes: list[str], *, include_quotes: bool = True) -> dict:
        return self._snapshot_read(codes, include_quotes=include_quotes)

    def _snapshot_read(self, codes: list[str], *, include_quotes: bool = True,
                       allow_partial_quotes: bool = False) -> dict:
        """Read validated simulation funds/positions and, by default, live quotes.

        The explicit empty-code metadata path is usable after hours to prepare a
        canonical close state. It carries no executable quote or price evidence.
        """
        with self._lock:
            if not isinstance(codes, list) or len(codes) > 100:
                raise BrokerError("每次最多读取 100 个目标证券")
            if type(include_quotes) is not bool:
                raise BrokerError("include_quotes 必须是明确布尔值")
            if not include_quotes and codes:
                raise BrokerError("只读账户元数据快照仅允许空证券列表")
            requested = {_code(code) for code in codes}
            account = self._validate_account()
            quote_errors = {}
            # Bad target quotes must fail before consuming fresh funds/position
            # queries. The SIMULATE identity is still validated first every time.
            if allow_partial_quotes:
                self._limit_read_queries = True
                batch = self._feed().quotes_partial(sorted(requested), refresh=True)
                quotes, quote_errors = batch['quotes'], batch['errors']
            else:
                quotes = self._read_quotes(requested) if include_quotes else {}
            trade = self._trade_context()
            args = self._account_args()
            funds = self._call(trade.accinfo_query, **args, refresh_cache=True,
                               currency=self._enum("Currency", "USD"))
            if len(funds) != 1:
                raise BrokerError("无法确认唯一的账户资金信息，已停止交易")
            fund = funds[0]
            if _name(fund.get("currency")) == "USD":
                # Standard path: explicitly denominated USD, never margin power.
                cash = min(_number(fund.get("us_cash"), "us_cash"),
                           _number(fund.get("usd_net_cash_power"), "usd_net_cash_power"))
                funds_source = "usd_net_cash_power_bounded_by_us_cash"
            elif (fund.get("currency") == "N/A"
                    and fund.get("usd_net_cash_power") == "N/A"
                    and fund.get("net_cash_power") == "N/A"
                    and [_name(market) for market in account["trdmarket_auth"]] == ["US"]):
                # Official get-funds: currency is inapplicable to single-market
                # accounts. SDK 10.11 maps absent currency/netCashPower to N/A.
                # For the separately validated US-only SIMULATE account, use
                # nonmargin cash, bounded by the explicit USD cashInfo amount,
                # then deduct every dollar on hold. Never substitute 'power'.
                # https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-funds.html
                for field in ("hk_cash", "cn_cash", "jp_cash", "sg_cash", "au_cash", "ca_cash", "my_cash"):
                    if field in fund and fund[field] != "N/A" and _number(fund[field], field) != 0:
                        raise BrokerError("旧版美股模拟账户含其他币种现金，已停止交易")
                raw_cash = min(_number(fund.get("cash"), "cash"),
                               _number(fund.get("us_cash"), "us_cash"))
                frozen = _number(fund.get("frozen_cash"), "frozen_cash")
                cash = float(max(Decimal("0"), Decimal(str(raw_cash)) - Decimal(str(frozen))))
                funds_source = "legacy_us_simulate_cash_less_frozen"
            else:
                raise BrokerError("无法确认美元资金信息，已停止交易")
            equity = _number(fund.get("total_assets"), "total_assets", positive=True)
            positions = {}
            rows = self._call(trade.position_list_query, **args, refresh_cache=True)
            for row in rows:
                qty = _quantity(row.get("qty"), "持仓数量")
                if qty == 0:
                    continue
                code = _code(row.get("code"))
                if (code in positions or _name(row.get("position_side")) != "LONG"
                        or _name(row.get("currency")) != "USD"):
                    raise BrokerError("存在重复、空头或非美元持仓，已停止交易")
                if "acc_id" in row and str(row["acc_id"]) != self.account_id:
                    raise BrokerError("持仓账户不匹配")
                sellable = _quantity(row.get("can_sell_qty"), "可卖数量")
                if sellable > qty:
                    raise BrokerError("可卖数量超出持仓")
                positions[code] = {"qty": qty, "sellable": sellable,
                                   "market_value": _number(row.get("market_val"), "持仓市值")}
            all_codes = requested | set(positions)
            if len(all_codes) > 100:
                raise BrokerError("持仓与目标证券合计超过 100 个")
            if include_quotes:
                # Holdings outside the requested targets must be freshly validated
                # as well; never reuse a target price for a different security.
                extra = all_codes - requested
                if allow_partial_quotes and extra:
                    batch = self._feed().quotes_partial(sorted(extra), refresh=True)
                    quotes.update(batch['quotes'])
                    quote_errors.update(batch['errors'])
                elif not allow_partial_quotes:
                    quotes.update(self._read_quotes(extra))
            orders = self._call(trade.order_list_query, **args, refresh_cache=True)
            open_orders = []
            for row in orders:
                status = _name(row.get("order_status", "UNKNOWN"))
                if status not in TERMINAL_STATUSES:
                    # All pending orders block the core, including unsupported instruments.
                    open_orders.append({"order_id": str(row.get("order_id", "")),
                        "code": str(row.get("code", "")), "status": status})
            result = {"cash": cash, "equity": equity, "positions": positions, "funds_source": funds_source,
                      "quotes": quotes, "open_orders": open_orders}
            if not include_quotes:
                result.update(funds_only=True, valuation_basis="BROKER_ACCOUNT_METADATA")
            if allow_partial_quotes:
                result.update(quote_errors=quote_errors, valuation_basis="BROKER_ACCOUNT_REFRESH",
                              account_observed_at=self._now().astimezone(timezone.utc).isoformat())
            return result

    @staticmethod
    def _deadline(value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise BrokerError("模拟执行截止时间必须是含时区时间")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise BrokerError("模拟执行截止时间无效") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise BrokerError("模拟执行截止时间必须含明确时区")
        return parsed.astimezone(timezone.utc)

    def _require_deadline(self, deadline):
        if deadline is not None and self._now().astimezone(timezone.utc) >= deadline:
            raise BrokerError("执行窗口已结束，订单尚未发送")

    def _market_cash_buyable(self, code: str, reference_price: float) -> int | None:
        """Read the broker's cash-only MARKET quantity, when this SDK exposes it.

        Moomoo applies a variable buying-power multiplier to market orders, so
        ask * quantity alone may overstate what a cash-only order can buy.
        Absence of this SDK method is handled by the separate cash-buffer guard.
        A failed or malformed *available* query blocks submission instead.
        """
        query = getattr(self._trade_context(), "acctradinginfo_query", None)
        if not callable(query):
            return None
        rows = self._call(query, order_type=self._enum("OrderType", "MARKET"),
                          code=code, price=reference_price, **self._account_args(),
                          session=self._enum("Session", "NONE"))
        if len(rows) != 1:
            raise BrokerReadError("市价单现金可买查询未返回唯一结果；订单尚未发送")
        row = rows[0]
        if (("acc_id" in row and str(row["acc_id"]) != self.account_id)
                or ("trd_env" in row and _name(row["trd_env"]) != "SIMULATE")
                or ("code" in row and row["code"] != code)):
            raise BrokerReadError("市价单现金可买结果与模拟账户或证券不符；订单尚未发送")
        try:
            return _quantity(row.get("max_cash_buy"), "市价单现金可买数量")
        except BrokerError:
            raise BrokerReadError("市价单现金可买数量无效；订单尚未发送") from None

    def market_cash_buyable(self, code: str, reference_price: float) -> int | None:
        """Cash-only MARKET capacity for strategy sizing; None means SDK lacks it."""
        with self._lock:
            code = _code(code)
            price = _number(reference_price, "市价单参考价", positive=True)
            self._validate_account()
            return self._market_cash_buyable(code, price)

    def submit(self, order: dict, client_id: str, *, allow_partial_quotes: bool = False,
               execution_deadline_utc: str | None = None, order_type: str = "NORMAL") -> dict:
        with self._lock:
            if type(allow_partial_quotes) is not bool:
                raise BrokerError("逐票执行必须为明确布尔值")
            if type(order_type) is not str or order_type not in {"NORMAL", "MARKET"}:
                raise BrokerError("模拟订单类型仅支持 NORMAL 或 MARKET")
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", client_id):
                raise BrokerError("订单客户端标识必须为 1–64 个 ASCII 字母、数字、下划线或连字符")
            if client_id in self._attempted:
                raise BrokerError("该客户端订单标识已尝试提交，必须对账，禁止重试")
            try:
                deadline = self._deadline(execution_deadline_utc)
                if allow_partial_quotes and deadline is None:
                    raise BrokerError("逐票模拟执行缺少截止时间，订单尚未发送")
                self._require_deadline(deadline)
                place_order, submission, quote = self._submission_preflight(
                    order, client_id, allow_partial_quotes, order_type)
                # This is after the final account/quote RPC, immediately before I/O.
                self._require_deadline(deadline)
                age = (self._now().astimezone(timezone.utc) - datetime.fromisoformat(quote['asof'])).total_seconds()
                if not 0 <= age <= 30:
                    raise BrokerError("最终盘口行情已过期，订单尚未发送")
            except BrokerError as exc:
                if allow_partial_quotes:
                    unsent = BrokerOrderNotSent(str(exc))
                    unsent.retry_after_seconds = getattr(exc, 'retry_after_seconds', 0)
                    raise unsent from None
                raise
            self._attempted.add(client_id)  # Before I/O, including failures and timeouts.
            result = self._call(place_order, **submission)
            if len(result) != 1 or not _order_id(result[0].get("order_id")):
                raise BrokerError("提交结果缺少唯一订单号，请按未知状态对账")
            row = result[0]
            if (("acc_id" in row and str(row["acc_id"]) != self.account_id)
                    or ("trd_env" in row and _name(row["trd_env"]) != "SIMULATE")
                    or ("code" in row and row["code"] != order["code"])
                    or ("trd_side" in row and _name(row["trd_side"]) != order["side"])
                    or ("order_type" in row and _name(row["order_type"]) != order_type)):
                raise BrokerError("提交回执与模拟账户、证券或订单类型不符；按未知状态对账")
            status = _name(row.get("order_status", "UNKNOWN"))
            return {"order_id": _order_id(row["order_id"]),
                    "status": status if status in KNOWN_STATUSES else "UNKNOWN",
                    "order_type": order_type}

    def _submission_preflight(self, order, client_id, allow_partial_quotes, order_type="NORMAL"):
        if not isinstance(order, dict) or set(order) != {"code", "side", "qty", "limit_price"}:
            raise BrokerError("订单字段不符合接口约定")
        code = _code(order["code"])
        side = order["side"]
        if side not in {"BUY", "SELL"}:
            raise BrokerError("只允许买入或卖出已有股票")
        if order_type == "MARKET" and not allow_partial_quotes:
            raise BrokerError("市价单仅允许已授权逐票模拟买卖")
        if type(order["qty"]) is not int:
            raise BrokerError("订单数量必须为整数")
        qty = _quantity(order["qty"], "订单数量", positive=True)
        price = _number(order["limit_price"], "限价", positive=True)
        # Partial execution excludes bad holdings quotes, not account/funds checks.
        state = self.snapshot_partial([code]) if allow_partial_quotes else self.snapshot([code])
        quote = state['quotes'].get(code)
        if quote is None:
            raise BrokerError(state.get('quote_errors', {}).get(code, code + " 缺少合格报价"))
        age = (self._now().astimezone(timezone.utc) - datetime.fromisoformat(quote["asof"])).total_seconds()
        if not quote["tradable"] or not 0 <= age <= 30:
            raise BrokerError("当前不在正常交易时段、证券不可交易或行情超过 30 秒")
        if state["open_orders"]:
            raise BrokerError("模拟账户存在未完成订单，必须先对账")
        if qty % quote["lot_size"] or Decimal(str(price)) % Decimal(str(quote["price_tick"])):
            raise BrokerError("订单数量或限价不符合最小交易单位")
        price_decimal = Decimal(str(price))
        reference = Decimal(str(quote["price"]))
        if abs(price_decimal - reference) > reference * Decimal("0.02"):
            raise BrokerError("最终限价偏离最新行情超过 2%，已停止提交")
        if Decimal(str(quote["ask"])) - Decimal(str(quote["bid"])) > reference * Decimal("0.02"):
            raise BrokerError("最新买卖价差超过 200 bps，已停止提交")
        if allow_partial_quotes and (quote['ask'] - quote['bid']) / ((quote['ask'] + quote['bid']) / 2) * 10000 > 50:
            raise BrokerError("最新买卖价差超过50bp，订单尚未发送")
        if side == "BUY":
            cash_reference = (max(price_decimal, Decimal(str(quote["ask"])))
                              if order_type == "MARKET" else price_decimal)
            cash_buffer = Decimal("1.03") if order_type == "MARKET" else Decimal("1.005")
            if cash_reference * qty * cash_buffer > Decimal(str(state["cash"])):
                if order_type == "MARKET":
                    raise BrokerError("美元现金不足以覆盖市价委托及 3% 缓冲，禁止融资")
                raise BrokerError("美元现金不足以覆盖委托及 0.5% 费用缓冲，禁止融资")
            if order_type == "MARKET":
                cash_buyable = self._market_cash_buyable(code, float(cash_reference))
                if cash_buyable is not None and qty > cash_buyable:
                    raise BrokerError("市价单数量超过券商现金可买股数，订单尚未发送")
        if side == "SELL" and qty > state["positions"].get(code, {}).get("sellable", 0):
            raise BrokerError("可卖持仓不足，禁止卖空")
        # Resolve all submission arguments before the final emergency-stop check.
        place_order = self._trade_context().place_order
        submission = {"price": price, "qty": qty, "code": code,
            "trd_side": self._enum("TrdSide", side), "order_type": self._enum("OrderType", order_type),
            "adjust_limit": 0, **self._account_args(), "remark": client_id,
            "time_in_force": self._enum("TimeInForce", "DAY"),
            "fill_outside_rth": False, "session": self._enum("Session", "NONE")}
        try:
            cancelled = self.cancel_check()
        except Exception:
            raise BrokerError("无法确认停止状态，已阻止提交") from None
        if cancelled:
            raise BrokerError("已收到停止请求，订单尚未提交")
        return place_order, submission, quote

    def reconcile(self, client_id: str, order_id: str | None = None) -> dict:
        """Read the refreshed current order, falling back to history on absence.

        Moomoo's current/historical *deal* APIs do not support paper trading.
        Their order APIs' dealt_qty is therefore the simulation fill authority.
        Read failures propagate as BrokerReadError, preserving the pending intent.
        History API defaults to the preceding 90 days; older/missing stays UNKNOWN.
        """
        with self._lock:
            self._validate_account()
            if not isinstance(client_id, str) or not client_id:
                raise BrokerError("对账需要原始客户端订单标识")
            unknown = {"status": "UNKNOWN", "order_id": order_id,
                       "dealt_qty": 0, "dealt_avg_price": None}
            trade, args = self._trade_context(), self._account_args()
            try:
                query = {**args, "refresh_cache": True}
                if order_id is not None:
                    query["order_id"] = str(order_id)
                current = self._call(trade.order_list_query, **query)
            except BrokerReadError:
                raise
            except BrokerError:
                raise BrokerReadError("当前订单查询结果无效；稍后重试核对") from None
            # Filter locally as well: a malformed or unexpectedly broad SDK
            # result cannot bind another account's/order’s row to this intent.
            matches = [row for row in current if
                       (order_id is not None and _order_id(row.get("order_id")) == str(order_id))
                       or (order_id is None and str(row.get("remark", "")) == client_id)]
            if order_id is not None and any(
                    str(row.get("remark", "")) == client_id
                    and _order_id(row.get("order_id")) not in {"", str(order_id)}
                    for row in current):
                return unknown
            if not matches:
                try:
                    historical = self._call(trade.history_order_list_query, **args)
                except BrokerReadError:
                    raise
                except BrokerError:
                    raise BrokerReadError("历史订单查询结果无效；稍后重试核对") from None
                matches = [row for row in historical if
                           (order_id is not None and _order_id(row.get("order_id")) == str(order_id))
                           or (order_id is None and str(row.get("remark", "")) == client_id)]
                if order_id is not None and not matches:
                    # A broker-acknowledged order may take time to appear in
                    # either list. Absence is not evidence that it was rejected.
                    raise BrokerReadError("原订单暂未出现在当前或历史订单查询；稍后继续对账")
            if any(str(row.get("remark", "")) != client_id for row in matches):
                return unknown
            if any("acc_id" in row and str(row["acc_id"]) != self.account_id for row in matches):
                return unknown
            if any("trd_env" in row and _name(row["trd_env"]) != "SIMULATE" for row in matches):
                return unknown
            ids = {_order_id(row.get("order_id")) for row in matches}
            if len(ids) != 1 or "" in ids or (order_id is not None and ids != {str(order_id)}):
                return unknown
            # If the same remark maps to multiple orders, or data is contradictory,
            # require manual investigation instead of choosing an arbitrary row.
            try:
                parsed = [(row, _quantity(row.get("dealt_qty"), "成交数量"),
                           _quantity(row.get("qty"), "委托数量", positive=True)) for row in matches]
                if len({qty for _, _, qty in parsed}) != 1 or any(done > qty for _, done, qty in parsed):
                    return unknown
                terminals = {_name(row.get("order_status")) for row, _, _ in parsed
                             if _name(row.get("order_status")) in TERMINAL_STATUSES}
                if len(terminals) > 1:
                    return unknown
                row, dealt, qty = max(parsed, key=lambda item: (item[1], _name(item[0].get("order_status")) in TERMINAL_STATUSES))
                status = _name(row.get("order_status", "UNKNOWN"))
                if status not in KNOWN_STATUSES or (status == "FILLED_ALL" and dealt != qty):
                    return unknown
                if dealt and status not in {"FILLED_ALL", "FILLED_PART", "CANCELLED_PART"}:
                    return unknown
                if terminals and status not in terminals:
                    return unknown
                types = {_name(candidate["order_type"]) for candidate, _, _ in parsed
                         if candidate.get("order_type") is not None}
                if len(types) > 1 or any(kind not in {"NORMAL", "MARKET"} for kind in types):
                    return unknown
                order_type = next(iter(types)) if types else None
                limits = []
                if order_type != "MARKET":
                    for candidate, _, _ in parsed:
                        try:
                            limits.append(_number(candidate.get("price"), "委托限价", positive=True))
                        except BrokerError:
                            continue
                    if limits and any(not math.isclose(value, limits[0], rel_tol=1e-9, abs_tol=1e-9)
                                      for value in limits[1:]):
                        return unknown
                prices = []
                if dealt:
                    for candidate, done, _ in parsed:
                        if done != dealt:
                            continue
                        try:
                            price = _number(candidate.get("dealt_avg_price"), "成交均价", positive=True)
                        except BrokerError:
                            # Unknown average never becomes the submitted limit.
                            continue
                        prices.append(price)
                    if prices and any(not math.isclose(price, prices[0], rel_tol=1e-9, abs_tol=1e-9)
                                      for price in prices[1:]):
                        return unknown
                result = {"status": status, "order_id": next(iter(ids)), "dealt_qty": dealt,
                        "dealt_avg_price": prices[0] if prices else None,
                        "qty": qty, "limit_price": limits[0] if limits else None}
                if order_type is not None:
                    result["order_type"] = order_type
                return result
            except BrokerError:
                return unknown

    def reprice(self, order: dict, order_id: str, client_id: str, *,
                expected_dealt_qty: int, execution_deadline_utc: str) -> dict:
        """Modify the same US SIMULATE order; never place a replacement order.

        ``qty`` is the *total* quantity after modification, not the remaining
        amount. The caller supplies the frozen per-symbol notional ceiling.
        """
        with self._lock:
            if not isinstance(order, dict) or set(order) != {
                    "code", "side", "qty", "limit_price", "max_order_notional"}:
                raise BrokerReadError("改单缺少原策略预算或订单字段；尚未调用券商")
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", client_id):
                raise BrokerReadError("改单客户端标识无效；尚未调用券商")
            oid = _order_id(order_id)
            if not oid or oid != str(order_id):
                raise BrokerReadError("改单原订单号无效；尚未调用券商")
            try:
                code = _code(order["code"])
                qty = _quantity(order["qty"], "改单总数量", positive=True)
                expected = _quantity(expected_dealt_qty, "改单预期成交量")
                price = _number(order["limit_price"], "改单限价", positive=True)
                cap = _number(order["max_order_notional"], "原策略单票预算", positive=True)
                deadline = self._deadline(execution_deadline_utc)
            except BrokerError as exc:
                raise BrokerReadError(str(exc) + "；尚未发送改单") from None
            side = order["side"]
            if side not in {"BUY", "SELL"} or type(order["qty"]) is not int:
                raise BrokerReadError("改单方向或总数量无效；尚未调用券商")
            if type(expected_dealt_qty) is not int:
                raise BrokerReadError("改单预期成交量无效；尚未调用券商")
            if Decimal(str(qty)) * Decimal(str(price)) > Decimal(str(cap)):
                raise BrokerReadError("改单金额超过原策略单票预算；尚未调用券商")
            if deadline is None:
                raise BrokerReadError("改单缺少执行截止时间；尚未调用券商")
            if self._now().astimezone(timezone.utc) >= deadline:
                raise BrokerReadError("执行窗口已结束；尚未发送改单")
            key = (oid, qty, str(Decimal(str(price))))
            if key in self._reprice_attempted:
                raise BrokerReadError("同一原订单及价格已尝试改单；先对账，禁止重复发送")
            try:
                self._validate_account()
            except BrokerReadError:
                raise
            except BrokerError as exc:
                raise BrokerReadError(str(exc) + "；尚未发送改单") from None
            # A fresh account/quote snapshot ensures only this original order
            # is pending and obtains free cash excluding existing order holds.
            try:
                state = self.snapshot_partial([code])
            except BrokerReadError:
                raise
            except BrokerError as exc:
                raise BrokerReadError(str(exc) + "；尚未发送改单") from None
            quote = state["quotes"].get(code)
            if quote is None:
                raise BrokerReadError("当前股票没有合格实时报价；稍后重新查询")
            if any(item["order_id"] != oid for item in state["open_orders"]):
                raise BrokerReadError("模拟账户有其他未完成委托；先对账")
            age = (self._now().astimezone(timezone.utc)
                   - datetime.fromisoformat(quote["asof"])).total_seconds()
            if not quote["tradable"] or not 0 <= age <= 30:
                raise BrokerReadError("当前不在正常交易时段或报价已过期；稍后重新查询")
            if qty % quote["lot_size"] or Decimal(str(price)) % Decimal(str(quote["price_tick"])):
                raise BrokerReadError("改单数量或价格不符合最小交易单位")
            reference = Decimal(str(quote["price"]))
            if abs(Decimal(str(price)) - reference) > reference * Decimal("0.02"):
                raise BrokerReadError("改单价格偏离最新行情超过 2%")
            spread = (Decimal(str(quote["ask"])) - Decimal(str(quote["bid"]))) / (
                (Decimal(str(quote["ask"])) + Decimal(str(quote["bid"]))) / 2)
            if spread * 10000 > 50:
                raise BrokerReadError("最新买卖价差超过 50bp；稍后重新报价")
            if (side == "BUY" and price < quote["ask"]) or (side == "SELL" and price > quote["bid"]):
                raise BrokerReadError("新限价尚未贴近实时盘口；稍后重新报价")
            # Repeat the authoritative order read immediately before the
            # modification. The snapshot's all-orders query is not enough to
            # validate identity or detect a fill racing with repricing.
            try:
                rows = self._call(self._trade_context().order_list_query,
                                  **self._account_args(), order_id=oid, refresh_cache=True)
            except BrokerReadError:
                raise
            except BrokerError:
                raise BrokerReadError("改单前订单查询无效；稍后重新对账") from None
            rows = [row for row in rows if _order_id(row.get("order_id")) == oid]
            if len(rows) != 1:
                raise BrokerReadError("改单前未找到唯一原订单；尚未发送改单")
            original = rows[0]
            if (str(original.get("remark", "")) != client_id
                    or original.get("code") != code
                    or _name(original.get("trd_side")) != side
                    or ("acc_id" in original and str(original["acc_id"]) != self.account_id)
                    or ("trd_env" in original and _name(original["trd_env"]) != "SIMULATE")
                    or ("order_type" in original and _name(original["order_type"]) != "NORMAL")):
                raise BrokerReadError("原订单身份与改单意图不一致；尚未发送改单")
            try:
                original_qty = _quantity(original.get("qty"), "原委托数量", positive=True)
                dealt = _quantity(original.get("dealt_qty"), "原委托成交量")
                old_price = _number(original.get("price"), "原委托限价", positive=True)
            except BrokerError:
                raise BrokerReadError("原委托数量、成交量或限价无效；尚未发送改单") from None
            status = _name(original.get("order_status"))
            if status not in {"SUBMITTED", "FILLED_PART"} or dealt != expected:
                raise BrokerReadError("原订单状态或成交数量已变化；先对账再决定是否改单")
            if qty > original_qty or qty <= dealt or original_qty < dealt:
                raise BrokerReadError("改单不得增加原总股数或低于已成交数")
            if qty == original_qty and Decimal(str(price)) == Decimal(str(old_price)):
                raise BrokerReadError("原委托数量与限价未变化；无需重复改单")
            remaining = qty - dealt
            if side == "SELL":
                if remaining > state["positions"].get(code, {}).get("qty", 0):
                    raise BrokerReadError("改单卖出数量超过当前持仓；尚未发送改单")
            else:
                held_qty = state["positions"].get(code, {}).get("qty", 0)
                if Decimal(str(held_qty + remaining)) * Decimal(str(price)) > Decimal(str(cap)):
                    raise BrokerReadError("改单后该股总持仓将超过原策略单票预算；尚未发送改单")
                old_outstanding = (original_qty - dealt) * Decimal(str(old_price))
                new_outstanding = remaining * Decimal(str(price))
                additional_cash = max(Decimal("0"), new_outstanding - old_outstanding)
                if additional_cash * Decimal("1.005") > Decimal(str(state["cash"])):
                    raise BrokerReadError("可用美元现金不足以覆盖改单新增占款和费用缓冲")
            if self._now().astimezone(timezone.utc) >= deadline:
                raise BrokerReadError("执行窗口已结束；尚未发送改单")
            age = (self._now().astimezone(timezone.utc)
                   - datetime.fromisoformat(quote["asof"])).total_seconds()
            if not 0 <= age <= 30:
                raise BrokerReadError("最终盘口行情已过期；尚未发送改单")
            try:
                cancelled = self.cancel_check()
            except Exception:
                raise BrokerReadError("无法确认停止状态；尚未发送改单") from None
            if cancelled:
                raise BrokerReadError("已收到停止请求；尚未发送改单")
            try:
                operation = self._enum("ModifyOrderOp", "NORMAL")
                modify_order = self._trade_context().modify_order
                account_args = self._account_args()
            except BrokerError as exc:
                raise BrokerReadError(str(exc) + "；尚未发送改单") from None
            self._reprice_attempted.add(key)  # Before the external side effect.
            result = self._call(modify_order,
                modify_order_op=operation,
                order_id=oid, qty=qty, price=price, adjust_limit=0,
                **account_args)
            if len(result) != 1 or _order_id(result[0].get("order_id")) != oid:
                raise BrokerError("改单回执无法确认同一原订单，必须先对账，禁止重试")
            return {"order_id": oid, "status": "PENDING_RECONCILE", "qty": qty,
                    "limit_price": price, "dealt_qty": dealt}

    def close(self) -> None:
        with self._lock:
            contexts = (self._quote_feed, self._quote, self._trade)
            self._quote_feed = self._quote = self._trade = None
            for context in contexts:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
