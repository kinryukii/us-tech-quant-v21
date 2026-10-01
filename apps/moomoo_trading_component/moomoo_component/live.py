"""An isolated, opt-in reader for real accounts, with no execution interface.

API references: https://openapi.moomoo.com/moomoo-api-doc/en/trade/
get-acc-list.html, get-funds.html, get-position-list.html, get-order-list.html.
Construction and state() never load the SDK or contact OpenD. All values are
ephemeral; real account data is not persisted by this module.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import math
import re
import threading
from typing import Any


class LiveReadOnlyError(RuntimeError):
    """Real-account metadata or a read-only snapshot could not be confirmed."""


def _name(value: Any) -> str:
    return str(value).rsplit(".", 1)[-1]


def _text(value: Any) -> str:
    if value is None:
        return ""
    result = str(value).strip()
    return "" if result in {"nan", "NaN", "N/A", "None"} else result[:200]


def _account_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    result = str(value)
    return result if re.fullmatch(r"[1-9][0-9]{0,19}", result) else None


def _number(value: Any) -> float | None:
    # Negative balances, fractional positions and short positions are real data
    # in a viewer. Unknowns are null, never a made-up zero or an available limit.
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


class LiveReadOnly:
    """Separate from both the simulation broker and execution engine."""

    def __init__(self, *, sdk: Any = None, now: Any = None):
        self._sdk = sdk
        self._trade = None
        self._lock = threading.RLock()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._port = 18441
        self._security_firm = "FUTUSECURITIES"
        self._connected = False
        self._accounts: list[dict] = []
        self._account_id: str | None = None
        self._account: dict | None = None
        self._last_error = ""

    def state(self) -> dict:
        """Return only a detached local snapshot; no polling or lazy connection."""
        with self._lock:
            return deepcopy({
                "environment": "REAL", "execution_enabled": False,
                "permission": "LOCKED", "connected": self._connected,
                "accounts": self._accounts, "account_id": self._account_id,
                "account": self._account, "last_error": self._last_error,
                "port": self._port, "security_firm": self._security_firm,
            })

    def _load(self):
        if self._sdk is None:
            try:
                self._sdk = importlib.import_module("moomoo")
            except ImportError:
                raise LiveReadOnlyError("尚未安装 Moomoo SDK，请安装项目的 moomoo 可选依赖") from None
        return self._sdk

    def _enum(self, group: str, member: str):
        value = getattr(getattr(self._load(), group, None), member, None)
        if value is None:
            raise LiveReadOnlyError(f"Moomoo SDK 不支持 {group}.{member}，请检查版本和券商区域")
        return value

    def _call(self, name: str, **kwargs) -> list[dict]:
        # Keep the only SDK query surface here explicitly bounded.
        if name not in {"get_acc_list", "accinfo_query", "position_list_query", "order_list_query"}:
            raise LiveReadOnlyError("请求不属于实盘只读接口")
        try:
            ret, data = getattr(self._trade, name)(**kwargs)
            if ret != self._load().RET_OK:
                raise LiveReadOnlyError(f"{name} 只读请求未成功，请检查 OpenD 登录、权限与日志")
            if hasattr(data, "to_dict"):
                data = data.to_dict("records")
        except LiveReadOnlyError:
            raise
        except Exception:
            # SDK exceptions may contain identifiers or balances; do not echo.
            raise LiveReadOnlyError(f"{name} 只读请求异常，请检查本机 OpenD") from None
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise LiveReadOnlyError(f"{name} 返回数据格式无法确认")
        return data

    @staticmethod
    def _eligible(row: dict) -> bool:
        markets = row.get("trdmarket_auth")
        return (
            _name(row.get("trd_env")) == "REAL"
            and _name(row.get("acc_status")) == "ACTIVE"
            and isinstance(markets, (list, tuple))
            and "US" in {_name(market) for market in markets}
            and _account_id(row.get("acc_id")) is not None
        )

    def _discover(self) -> list[dict]:
        rows = self._call("get_acc_list")
        counts = Counter(str(row.get("acc_id")) for row in rows)
        self._accounts = [
            {"account_id": str(row["acc_id"]), "market": "US", "environment": "REAL"}
            for row in rows if self._eligible(row) and counts[str(row["acc_id"])] == 1
        ]
        return rows

    def _validate_selected(self, account_id: str) -> None:
        rows = self._discover()
        selected = [row for row in rows if str(row.get("acc_id")) == account_id]
        if len(selected) != 1 or not self._eligible(selected[0]):
            raise LiveReadOnlyError("所选账户不再是有效的美股实盘账户，请重新连接并选择")

    def _error(self, error: Exception, fallback: str) -> LiveReadOnlyError:
        self._account = None
        self._last_error = str(error) if isinstance(error, LiveReadOnlyError) else fallback
        return LiveReadOnlyError(self._last_error)

    def connect(self, port: int = 18441, security_firm: str = "FUTUSECURITIES") -> dict:
        """Discover eligible real accounts, without selecting or reading funds."""
        with self._lock:
            try:
                if type(port) is not int or not 1 <= port <= 65535:
                    raise LiveReadOnlyError("OpenD 端口无效")
                if not isinstance(security_firm, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,40}", security_firm):
                    raise LiveReadOnlyError("券商区域参数无效")
                self.close()
                self._port, self._security_firm = port, security_firm
                sdk = self._load()
                market = self._enum("TrdMarket", "US")
                firm = self._enum("SecurityFirm", security_firm)
                self._trade = sdk.OpenSecTradeContext(
                    filter_trdmarket=market, host="127.0.0.1", port=port, security_firm=firm)
                self._discover()
                self._connected = True
                self._last_error = ""
                return self.state()
            except Exception as error:
                self.close()
                raise self._error(error, "无法连接本机 OpenD 实盘只读接口，请检查端口、登录和 SDK 版本") from None

    def select(self, account_id: str) -> dict:
        """Explicit selection revalidates metadata but does not query balances."""
        with self._lock:
            try:
                normalized = _account_id(account_id)
                if not self._connected or self._trade is None:
                    raise LiveReadOnlyError("请先连接 OpenD 实盘只读接口")
                if normalized is None or normalized not in {item["account_id"] for item in self._accounts}:
                    raise LiveReadOnlyError("必须明确选择已发现的实盘账户")
                self._validate_selected(normalized)
                self._account_id = normalized
                self._account = None
                self._last_error = ""
                return self.state()
            except Exception as error:
                self._account_id = None
                raise self._error(error, "实盘账户选择未能确认") from None

    def _check_rows(self, rows: list[dict], label: str) -> None:
        for row in rows:
            if "acc_id" in row and str(row["acc_id"]) != self._account_id:
                raise LiveReadOnlyError(f"{label}账户标识不匹配，无法展示")
            if "trd_env" in row and _name(row["trd_env"]) != "REAL":
                raise LiveReadOnlyError(f"{label}账户环境不匹配，无法展示")

    def refresh(self) -> dict:
        """Read real account data only after an explicit connection and choice."""
        with self._lock:
            try:
                if not self._connected or self._trade is None or self._account_id is None:
                    raise LiveReadOnlyError("请先连接并明确选择实盘账户，再刷新只读数据")
                self._account = None
                self._validate_selected(self._account_id)
                args = {"trd_env": self._enum("TrdEnv", "REAL"),
                        "acc_id": int(self._account_id), "refresh_cache": True}
                currency = self._enum("Currency", "USD")
                funds = self._call("accinfo_query", **args, currency=currency)
                self._check_rows(funds, "资金")
                if len(funds) != 1:
                    raise LiveReadOnlyError("无法确认唯一的实盘资金记录")
                fund = funds[0]
                if _name(fund.get("currency")) != "USD":
                    raise LiveReadOnlyError("资金展示币种无法确认为 USD，可能存在混合币种；未展示或换算余额")
                warnings: list[str] = []

                def read_number(row: dict, key: str, label: str) -> float | None:
                    result = _number(row.get(key))
                    if result is None:
                        warnings.append(f"{label}缺失或无效，显示为未知")
                    return result

                account = {
                    "cash": read_number(fund, "us_cash", "美元现金"),
                    "equity": read_number(fund, "total_assets", "美元计价净资产"),
                    "currency": "USD", "cash_label": "美元现金（非可下单额度）",
                    "positions": [], "orders": [], "warnings": warnings,
                }
                positions = self._call("position_list_query", **args, currency=currency)
                self._check_rows(positions, "持仓")
                for row in positions:
                    if _name(row.get("currency")) != "USD":
                        raise LiveReadOnlyError("持仓包含非美元或无法确认的币种；混合币种快照未展示，未做隐含换算")
                    cost_valid = row.get("cost_price_valid")
                    cost = None
                    if (isinstance(cost_valid, bool) or type(cost_valid).__name__ == "bool_") and bool(cost_valid):
                        cost = read_number(row, "cost_price", "持仓成本")
                    else:
                        warnings.append("持仓成本有效性无法确认，显示为未知")
                    # pl_val is diluted-cost gain/loss, not unrealized P/L.
                    pnl = read_number(row, "unrealized_pl", "未实现盈亏")
                    account["positions"].append({
                        "code": _text(row.get("code")), "name": _text(row.get("stock_name")),
                        "qty": read_number(row, "qty", "持仓数量"),
                        "sellable": read_number(row, "can_sell_qty", "可卖数量"),
                        "market_value": read_number(row, "market_val", "持仓市值"),
                        "cost_price": cost, "unrealized_pl": pnl,
                        "currency": "USD", "position_side": _text(row.get("position_side")),
                    })
                orders = self._call("order_list_query", **args)
                self._check_rows(orders, "订单")
                for row in orders:
                    code = _text(row.get("code"))
                    order_currency = "USD" if code.startswith("US.") else None
                    if order_currency is None:
                        warnings.append("存在非美股订单，价格原始币种无法确认；订单金额未合并")
                    account["orders"].append({
                        "order_id": _text(row.get("order_id")), "code": code,
                        "side": _text(row.get("trd_side")), "status": _text(row.get("order_status")),
                        "qty": read_number(row, "qty", "委托数量"),
                        "limit_price": read_number(row, "price", "委托价格"),
                        "filled_qty": read_number(row, "dealt_qty", "成交数量"),
                        "created_at": _text(row.get("create_time")),
                        "updated_at": _text(row.get("updated_time")), "currency": order_currency,
                    })
                account["warnings"] = list(dict.fromkeys(warnings))
                account["asof"] = self._now().astimezone(timezone.utc).isoformat()
                self._account = account
                self._last_error = ""
                return self.state()
            except Exception as error:
                raise self._error(error, "实盘只读快照无法确认，请检查 OpenD") from None

    def close(self) -> None:
        """Release the reader and clear all ephemeral account data."""
        with self._lock:
            context, self._trade = self._trade, None
            self._connected = False
            self._accounts = []
            self._account_id = None
            self._account = None
            self._last_error = ""
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
